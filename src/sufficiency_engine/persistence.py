"""Versioned session storage with atomic claims and revision-checked writes."""

from __future__ import annotations

import json
import math
import threading
import time
from abc import ABC, abstractmethod
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .exceptions import SerializationError, SessionConflictError


class SessionScope(BaseModel):
    """Trusted application and tenant scope plus an opaque session identifier.

    The storage key is not an authorization mechanism. The host must authorize
    access before passing a scope to the engine.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    application_id: Annotated[
        str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    ]
    tenant_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")]
    session_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")]


class SessionClaim(BaseModel):
    """An atomic lease and fencing token for a session writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner: UUID
    fence: int = Field(ge=1)


class StoredSession(BaseModel):
    """A JSON-safe, revisioned persistence envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    revision: int = Field(ge=1)
    state: dict[str, JsonValue]


class PersistenceABC(ABC):
    """Application-owned store with atomic claims and compare-and-swap writes.

    A durable implementation must atomically validate its lease, fencing token,
    and expected revision with each write. Lease expiry must permit recovery
    after a crashed writer; a session ID alone must never grant authorization.
    """

    @abstractmethod
    async def acquire(self, scope: SessionScope, owner: UUID, lease_seconds: float) -> SessionClaim:
        """Acquire an exclusive, expiring claim or raise a session conflict."""

    @abstractmethod
    async def renew(self, scope: SessionScope, claim: SessionClaim, lease_seconds: float) -> None:
        """Extend an active claim, rejecting expired or superseded claims."""

    @abstractmethod
    async def release(self, scope: SessionScope, claim: SessionClaim) -> None:
        """Release only the caller's claim."""

    @abstractmethod
    async def load(self, scope: SessionScope) -> StoredSession | None:
        """Load a copy of the session or return ``None`` if it does not exist."""

    @abstractmethod
    async def save(
        self,
        scope: SessionScope,
        state: dict[str, JsonValue],
        *,
        expected_revision: int | None,
        claim: SessionClaim,
    ) -> StoredSession:
        """Atomically save JSON state if the revision and claim still match."""

    @abstractmethod
    async def delete(
        self, scope: SessionScope, *, expected_revision: int, claim: SessionClaim
    ) -> None:
        """Atomically delete one session if the revision and claim still match."""


class InMemoryPersistence(PersistenceABC):
    """Thread-safe, copy-isolated ephemeral persistence for tests and small apps."""

    def __init__(self) -> None:
        self._states: dict[SessionScope, StoredSession] = {}
        self._claims: dict[SessionScope, tuple[SessionClaim, float]] = {}
        self._fences: dict[SessionScope, int] = {}
        self._lock = threading.RLock()

    def _active(self, scope: SessionScope, claim: SessionClaim) -> bool:
        current = self._claims.get(scope)
        return current is not None and current[0] == claim and current[1] > time.monotonic()

    async def acquire(self, scope: SessionScope, owner: UUID, lease_seconds: float) -> SessionClaim:
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        with self._lock:
            current = self._claims.get(scope)
            if current is not None and current[1] > time.monotonic():
                raise SessionConflictError("session already has an active writer")
            fence = self._fences.get(scope, 0) + 1
            self._fences[scope] = fence
            claim = SessionClaim(owner=owner, fence=fence)
            self._claims[scope] = (claim, time.monotonic() + lease_seconds)
            return claim

    async def renew(self, scope: SessionScope, claim: SessionClaim, lease_seconds: float) -> None:
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        with self._lock:
            if not self._active(scope, claim):
                raise SessionConflictError("session claim is expired or superseded")
            self._claims[scope] = (claim, time.monotonic() + lease_seconds)

    async def release(self, scope: SessionScope, claim: SessionClaim) -> None:
        with self._lock:
            current = self._claims.get(scope)
            if current is not None and current[0] == claim:
                del self._claims[scope]

    async def load(self, scope: SessionScope) -> StoredSession | None:
        with self._lock:
            state = self._states.get(scope)
            return None if state is None else state.model_copy(deep=True)

    async def save(
        self,
        scope: SessionScope,
        state: dict[str, JsonValue],
        *,
        expected_revision: int | None,
        claim: SessionClaim,
    ) -> StoredSession:
        try:
            safe_state = json.loads(json.dumps(state, allow_nan=False))
            if not isinstance(safe_state, dict) or safe_state != state:
                raise ValueError("state must be a JSON object")
        except (TypeError, ValueError) as exc:
            raise SerializationError("session state is not JSON serializable") from exc
        with self._lock:
            if not self._active(scope, claim):
                raise SessionConflictError("session claim is expired or superseded")
            current = self._states.get(scope)
            revision = None if current is None else current.revision
            if expected_revision != revision:
                raise SessionConflictError("session revision changed")
            saved = StoredSession(revision=(revision or 0) + 1, state=safe_state)
            self._states[scope] = saved
            return saved.model_copy(deep=True)

    async def delete(
        self, scope: SessionScope, *, expected_revision: int, claim: SessionClaim
    ) -> None:
        with self._lock:
            if not self._active(scope, claim):
                raise SessionConflictError("session claim is expired or superseded")
            current = self._states.get(scope)
            if current is None or current.revision != expected_revision:
                raise SessionConflictError("session revision changed")
            del self._states[scope]
