"""SQLite session store and semantic archive for Sufficiency Engine.

A starting point for a durable `PersistenceABC` and `SemanticArchiveABC` that uses
only the standard library. Every operation opens its own connection and runs in
one `BEGIN IMMEDIATE` transaction in a worker thread, so claims, fencing tokens,
and revisions are checked atomically with each write, across processes.

Adapt the connection handling, table names, and retention to your database.
Leases use wall-clock time because they are shared between processes, so keep
host clocks synchronized. Check an adapted copy with `scripts/check_extensions.py`
against an isolated test database.
"""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import tempfile
import time
from collections.abc import Callable, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import UUID

from agxai import (
    AttributionResult,
    Decision,
    Evidence,
    ExecutionContext,
    Explanation,
    PolicyDecision,
    SemanticArtifact,
)
from agxai.core.models import MemoryReference
from pydantic import JsonValue, ValidationError

from sufficiency_engine import PersistenceABC, SemanticArchiveABC, SessionScope
from sufficiency_engine.exceptions import SerializationError, SessionConflictError
from sufficiency_engine.persistence import SessionClaim, StoredSession

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sufficiency_sessions (
    application_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    PRIMARY KEY (application_id, tenant_id, session_id)
);
CREATE TABLE IF NOT EXISTS sufficiency_claims (
    application_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    owner TEXT,
    fence INTEGER NOT NULL,
    expires_at REAL NOT NULL,
    PRIMARY KEY (application_id, tenant_id, session_id)
);
CREATE TABLE IF NOT EXISTS sufficiency_artifacts (
    application_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (application_id, tenant_id, run_id, artifact_type, artifact_id)
);
"""

_ARTIFACT_TYPES: dict[str, Any] = {
    model.__name__: model
    for model in (
        AttributionResult,
        Decision,
        Evidence,
        Explanation,
        MemoryReference,
        PolicyDecision,
    )
}


class _Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    async def transaction[T](self, operation: Callable[[sqlite3.Connection], T]) -> T:
        def run() -> T:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    result = operation(connection)
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
                connection.execute("COMMIT")
                return result

        return await asyncio.to_thread(run)


def _key(scope: SessionScope) -> tuple[str, str, str]:
    return scope.application_id, scope.tenant_id, scope.session_id


def _check_lease(lease_seconds: float) -> None:
    if not math.isfinite(lease_seconds) or lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")


def _require_claim(
    connection: sqlite3.Connection, scope: SessionScope, claim: SessionClaim
) -> None:
    row = connection.execute(
        "SELECT owner, fence, expires_at FROM sufficiency_claims "
        "WHERE application_id = ? AND tenant_id = ? AND session_id = ?",
        _key(scope),
    ).fetchone()
    if row is None or row[0] != str(claim.owner) or row[1] != claim.fence or row[2] <= time.time():
        raise SessionConflictError("session claim is expired or superseded")


def _revision(connection: sqlite3.Connection, scope: SessionScope) -> int | None:
    row = connection.execute(
        "SELECT revision FROM sufficiency_sessions "
        "WHERE application_id = ? AND tenant_id = ? AND session_id = ?",
        _key(scope),
    ).fetchone()
    return None if row is None else row[0]


class SQLitePersistence(PersistenceABC):
    """Durable sessions with expiring claims, fencing tokens, and revisions."""

    def __init__(self, path: str | Path) -> None:
        self._database = _Database(path)

    async def acquire(self, scope: SessionScope, owner: UUID, lease_seconds: float) -> SessionClaim:
        _check_lease(lease_seconds)

        def operation(connection: sqlite3.Connection) -> SessionClaim:
            row = connection.execute(
                "SELECT owner, fence, expires_at FROM sufficiency_claims "
                "WHERE application_id = ? AND tenant_id = ? AND session_id = ?",
                _key(scope),
            ).fetchone()
            now = time.time()
            if row is not None and row[0] is not None and row[2] > now:
                raise SessionConflictError("session already has an active writer")
            claim = SessionClaim(owner=owner, fence=(0 if row is None else row[1]) + 1)
            connection.execute(
                "INSERT INTO sufficiency_claims "
                "(application_id, tenant_id, session_id, owner, fence, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (application_id, tenant_id, session_id) DO UPDATE SET "
                "owner = excluded.owner, fence = excluded.fence, expires_at = excluded.expires_at",
                (*_key(scope), str(owner), claim.fence, now + lease_seconds),
            )
            return claim

        return await self._database.transaction(operation)

    async def renew(self, scope: SessionScope, claim: SessionClaim, lease_seconds: float) -> None:
        _check_lease(lease_seconds)

        def operation(connection: sqlite3.Connection) -> None:
            _require_claim(connection, scope, claim)
            connection.execute(
                "UPDATE sufficiency_claims SET expires_at = ? "
                "WHERE application_id = ? AND tenant_id = ? AND session_id = ?",
                (time.time() + lease_seconds, *_key(scope)),
            )

        await self._database.transaction(operation)

    async def release(self, scope: SessionScope, claim: SessionClaim) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(
                "UPDATE sufficiency_claims SET owner = NULL, expires_at = 0 "
                "WHERE application_id = ? AND tenant_id = ? AND session_id = ? "
                "AND owner = ? AND fence = ?",
                (*_key(scope), str(claim.owner), claim.fence),
            )

        await self._database.transaction(operation)

    async def load(self, scope: SessionScope) -> StoredSession | None:
        def operation(connection: sqlite3.Connection) -> tuple[int, int, str] | None:
            return connection.execute(
                "SELECT version, revision, state FROM sufficiency_sessions "
                "WHERE application_id = ? AND tenant_id = ? AND session_id = ?",
                _key(scope),
            ).fetchone()

        row = await self._database.transaction(operation)
        if row is None:
            return None
        try:
            return StoredSession.model_validate(
                {"version": row[0], "revision": row[1], "state": json.loads(row[2])}
            )
        except (ValueError, ValidationError) as exc:
            raise SerializationError("stored session is invalid or has an unknown version") from exc

    async def save(
        self,
        scope: SessionScope,
        state: dict[str, JsonValue],
        *,
        expected_revision: int | None,
        claim: SessionClaim,
    ) -> StoredSession:
        try:
            text = json.dumps(state, allow_nan=False, ensure_ascii=False)
            if not isinstance(state, dict) or json.loads(text) != state:
                raise ValueError("state must be a JSON object")
        except (TypeError, ValueError) as exc:
            raise SerializationError("session state is not JSON serializable") from exc

        def operation(connection: sqlite3.Connection) -> int:
            _require_claim(connection, scope, claim)
            current = _revision(connection, scope)
            if current != expected_revision:
                raise SessionConflictError("session revision changed")
            revision = (current or 0) + 1
            connection.execute(
                "INSERT INTO sufficiency_sessions "
                "(application_id, tenant_id, session_id, version, revision, state) "
                "VALUES (?, ?, ?, 1, ?, ?) "
                "ON CONFLICT (application_id, tenant_id, session_id) DO UPDATE SET "
                "version = excluded.version, revision = excluded.revision, state = excluded.state",
                (*_key(scope), revision, text),
            )
            return revision

        revision = await self._database.transaction(operation)
        return StoredSession(revision=revision, state=json.loads(text))

    async def delete(
        self, scope: SessionScope, *, expected_revision: int, claim: SessionClaim
    ) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            _require_claim(connection, scope, claim)
            if _revision(connection, scope) != expected_revision:
                raise SessionConflictError("session revision changed")
            connection.execute(
                "DELETE FROM sufficiency_sessions "
                "WHERE application_id = ? AND tenant_id = ? AND session_id = ?",
                _key(scope),
            )

        await self._database.transaction(operation)


def _run_key(context: ExecutionContext) -> tuple[str, str, str]:
    return context.application_id, context.tenant_id, str(context.run_id)


def _artifact(artifact_type: str, payload: str) -> SemanticArtifact:
    return _ARTIFACT_TYPES[artifact_type].model_validate_json(payload)


class SQLiteSemanticArchive(SemanticArchiveABC):
    """Durable, scoped, idempotent storage for AGXAI evidence and decisions."""

    def __init__(self, path: str | Path) -> None:
        self._database = _Database(path)

    async def record(self, artifact: SemanticArtifact) -> None:
        artifact_type = type(artifact).__name__
        if artifact_type not in _ARTIFACT_TYPES:
            raise TypeError("unsupported AGXAI semantic artifact")

        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(
                "INSERT INTO sufficiency_artifacts "
                "(application_id, tenant_id, run_id, artifact_type, artifact_id, payload) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (application_id, tenant_id, run_id, artifact_type, artifact_id) "
                "DO UPDATE SET payload = excluded.payload",
                (
                    *_run_key(artifact.context),
                    artifact_type,
                    str(artifact.id),
                    artifact.model_dump_json(),
                ),
            )

        await self._database.transaction(operation)

    async def get(self, artifact_id: UUID, *, context: ExecutionContext) -> SemanticArtifact | None:
        def operation(connection: sqlite3.Connection) -> list[tuple[str, str]]:
            return connection.execute(
                "SELECT artifact_type, payload FROM sufficiency_artifacts "
                "WHERE application_id = ? AND tenant_id = ? AND run_id = ? AND artifact_id = ? "
                "LIMIT 2",
                (*_run_key(context), str(artifact_id)),
            ).fetchall()

        rows = await self._database.transaction(operation)
        if len(rows) > 1:
            raise LookupError("artifact ID is ambiguous in this run")
        return None if not rows else _artifact(*rows[0])

    async def list_run(self, *, context: ExecutionContext) -> Sequence[SemanticArtifact]:
        def operation(connection: sqlite3.Connection) -> list[tuple[str, str]]:
            return connection.execute(
                "SELECT artifact_type, payload FROM sufficiency_artifacts "
                "WHERE application_id = ? AND tenant_id = ? AND run_id = ? "
                "ORDER BY artifact_type, artifact_id",
                _run_key(context),
            ).fetchall()

        return tuple(_artifact(*row) for row in await self._database.transaction(operation))

    async def delete_run(self, context: ExecutionContext) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            connection.execute(
                "DELETE FROM sufficiency_artifacts "
                "WHERE application_id = ? AND tenant_id = ? AND run_id = ?",
                _run_key(context),
            )

        await self._database.transaction(operation)


def _test_database() -> Path:
    return Path(tempfile.mkdtemp(prefix="sufficiency-sqlite-")) / "store.sqlite3"


def make_test_store() -> SQLitePersistence:
    """Factory for `check_extensions.py` that uses a fresh temporary database."""
    return SQLitePersistence(_test_database())


def make_test_archive() -> SQLiteSemanticArchive:
    """Factory for `check_extensions.py` that uses a fresh temporary database."""
    return SQLiteSemanticArchive(_test_database())
