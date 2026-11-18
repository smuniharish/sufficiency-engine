"""Check explicitly selected storage extensions using disposable unique scopes."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue

from sufficiency_engine import AGXAIAudit, PersistenceABC, SemanticArchiveABC, SessionScope
from sufficiency_engine.exceptions import SessionConflictError

DESCRIPTIONS = {
    "copy_and_tenant_isolation": "sessions are copy-isolated and scoped by application, tenant, "
    "and session",
    "exclusive_claim_and_revision": "a second claim and a stale revision conflict",
    "stale_fence_and_revision_rejected": "a superseded claim and a stale revision cannot write",
    "expiry_recovery_and_deletion": "an expired claim is fenced off and deletion works",
    "semantic_retention_and_replay": "AGXAI artifacts are kept and replay is idempotent",
    "archive_copy_and_scope": "archived artifacts are copy-isolated and scoped",
    "archive_deletion": "deleting a run is complete and idempotent",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def conflict(operation: Awaitable[object]) -> None:
    try:
        await operation
    except SessionConflictError:
        return
    raise AssertionError("a stale or concurrent operation did not conflict")


def construct(spec: str) -> object:
    module, separator, name = spec.partition(":")
    if not separator or not module or not name:
        raise ValueError("use MODULE:FACTORY")
    factory = getattr(import_module(module), name)
    if not callable(factory):
        raise TypeError("factory is not callable")
    return factory()


async def check_persistence(store: PersistenceABC, scope: SessionScope) -> list[str]:
    claim = await store.acquire(scope, uuid4(), 60)
    checks = []
    try:
        original: dict[str, JsonValue] = {"value": "original"}
        saved = await store.save(scope, original, expected_revision=None, claim=claim)
        original["value"] = "mutated"
        loaded = await store.load(scope)
        require(loaded is not None and loaded.state == {"value": "original"}, "save isolation")
        if loaded is None:
            raise AssertionError("saved state is missing")
        loaded.state["value"] = "mutated"
        fresh = await store.load(scope)
        require(fresh is not None and fresh.state == {"value": "original"}, "load isolation")
        for field in ("application_id", "tenant_id", "session_id"):
            other = scope.model_copy(update={field: "other"})
            require(await store.load(other) is None, "scope isolation")
        checks.append("copy_and_tenant_isolation")
        await conflict(store.acquire(scope, uuid4(), 60))
        await conflict(store.save(scope, {}, expected_revision=None, claim=claim))
        checks.append("exclusive_claim_and_revision")
        first = claim
        await store.release(scope, claim)
        claim = await store.acquire(scope, uuid4(), 60)
        require(claim.fence > first.fence, "fencing monotonicity")
        await conflict(store.save(scope, {}, expected_revision=saved.revision, claim=first))
        await store.renew(scope, claim, 60)
        updated = await store.save(
            scope, {"ok": True}, expected_revision=saved.revision, claim=claim
        )
        require(updated.revision > saved.revision, "revision monotonicity")
        await conflict(store.delete(scope, expected_revision=saved.revision, claim=claim))
        checks.append("stale_fence_and_revision_rejected")
        await store.delete(scope, expected_revision=updated.revision, claim=claim)
        require(await store.load(scope) is None, "session deletion")
        await store.release(scope, claim)
        expired = await store.acquire(scope, uuid4(), 0.1)
        claim = expired
        await asyncio.sleep(0.2)
        await conflict(store.renew(scope, expired, 60))
        claim = await store.acquire(scope, uuid4(), 60)
        require(claim.fence > expired.fence, "expired writer fencing")
        await conflict(store.save(scope, {}, expected_revision=None, claim=expired))
        checks.append("expiry_recovery_and_deletion")
    finally:
        await store.release(scope, claim)
        cleanup = await store.acquire(scope, uuid4(), 60)
        try:
            remaining = await store.load(scope)
            if remaining is not None:
                await store.delete(scope, expected_revision=remaining.revision, claim=cleanup)
        finally:
            await store.release(scope, cleanup)
    return checks


async def check_archive(archive: SemanticArchiveABC, scope: SessionScope) -> list[str]:
    audit = AGXAIAudit(archive=archive)
    intent = audit.prepare(
        scope=scope,
        run_id=uuid4(),
        assessment_id=uuid4(),
        started_at=datetime.now(UTC),
        step=0,
        action="insufficient",
        requirements=(),
        terminal=True,
    )
    context = intent.execution.context
    try:
        await audit.commit(intent, scope=scope)
        before = await archive.list_run(context=context)
        await audit.commit(intent, scope=scope)
        after = await archive.list_run(context=context)
        require({item.id for item in before} == {item.id for item in after}, "idempotent replay")
        require(len(after) == len(intent.evidence) + 1, "semantic artifact retention")
        evidence = await archive.get(intent.evidence[0].id, context=context)
        require(evidence is not None, "artifact lookup")
        if evidence is None:
            raise AssertionError("evidence was not retained")
        evidence.metadata["mutated"] = True
        again = await archive.get(intent.evidence[0].id, context=context)
        require(again is not None and "mutated" not in again.metadata, "archive copy isolation")
        for field, value in (
            ("application_id", "other"),
            ("tenant_id", "other"),
            ("run_id", uuid4()),
        ):
            other = context.model_copy(update={field: value})
            require(not await archive.list_run(context=other), "archive scope isolation")
            require(await archive.get(intent.decision.id, context=other) is None, "scoped lookup")
        await audit.delete_run(context)
        await audit.delete_run(context)
        require(not await archive.list_run(context=context), "idempotent archive deletion")
    finally:
        await audit.delete_run(context)
    return ["semantic_retention_and_replay", "archive_copy_and_scope", "archive_deletion"]


async def verify(store: PersistenceABC, archive: SemanticArchiveABC) -> list[str]:
    scope = SessionScope(
        application_id="sufficiency-contract",
        tenant_id="test",
        session_id=uuid4().hex,
    )
    return [*await check_persistence(store, scope), *await check_archive(archive, scope)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path.cwd())
    parser.add_argument("--persistence", default="sufficiency_engine:InMemoryPersistence")
    parser.add_argument("--archive", default="sufficiency_engine:InMemorySemanticArchive")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.path.resolve()))
    checks: list[str] = []
    try:
        store, archive = construct(args.persistence), construct(args.archive)
        if not isinstance(store, PersistenceABC) or not isinstance(archive, SemanticArchiveABC):
            raise TypeError("factories must return the actual extension ABCs")
        checks = asyncio.run(verify(store, archive))
        report: dict[str, object] = {"ok": True, "checks": checks}
    except Exception as exc:
        report = {"ok": False, "error_type": type(exc).__name__}
    if args.json:
        print(json.dumps(report))
    elif report["ok"]:
        print(f"Checked {args.persistence} and {args.archive}")
        for check in checks:
            print(f"PASS  {DESCRIPTIONS[check]}")
        print(f"All {len(checks)} contract checks passed.")
    else:
        print(f"FAIL  {report['error_type']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
