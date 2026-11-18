import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agxai import Decision as XAIDecision
from agxai import Evidence, ExecutionContext, Run
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from sufficiency_engine._state import AssessmentState
from sufficiency_engine.exceptions import ProvenanceError, SerializationError, SessionConflictError
from sufficiency_engine.models import Requirement, RequirementClassification
from sufficiency_engine.persistence import InMemoryPersistence, SessionScope
from sufficiency_engine.provenance import AGXAIAudit, InMemorySemanticArchive


def scope(tenant="tenant", session="session"):
    return SessionScope(application_id="app", tenant_id=tenant, session_id=session)


@given(st.text(max_size=200))
def test_assessment_state_round_trips_without_changing_identity(task):
    state = AssessmentState(scope=scope(), task=task)
    restored = AssessmentState.model_validate_json(state.model_dump_json())
    assert restored == state
    assert restored.assessment_id == state.assessment_id
    assert restored.run_id == state.run_id


async def test_storage_is_scoped_revision_checked_and_copy_isolated():
    store = InMemoryPersistence()
    claim = await store.acquire(scope(), uuid4(), 60)
    original: dict[str, JsonValue] = {"nested": {"items": [0, "no"]}}
    saved = await store.save(scope(), original, expected_revision=None, claim=claim)
    nested = original["nested"]
    assert isinstance(nested, dict)
    items = nested["items"]
    assert isinstance(items, list)
    items.append("changed")
    saved_nested = saved.state["nested"]
    assert isinstance(saved_nested, dict)
    saved_items = saved_nested["items"]
    assert isinstance(saved_items, list)
    saved_items.append("also changed")
    loaded = await store.load(scope())
    assert loaded is not None
    assert loaded.state == {"nested": {"items": [0, "no"]}}
    assert await store.load(scope("other")) is None
    with pytest.raises(SessionConflictError, match="revision"):
        await store.save(scope(), {}, expected_revision=None, claim=claim)
    with pytest.raises(SerializationError):
        await store.save(scope(), {"invalid": float("nan")}, expected_revision=1, claim=claim)
    updated = await store.save(scope(), {"ok": True}, expected_revision=1, claim=claim)
    assert updated.revision == 2
    await store.delete(scope(), expected_revision=2, claim=claim)
    await store.release(scope(), claim)
    assert await store.load(scope()) is None


async def test_claims_reject_concurrent_writers_and_recover_after_expiry(monkeypatch):
    store = InMemoryPersistence()
    clock = [100.0]
    monkeypatch.setattr("sufficiency_engine.persistence.time.monotonic", lambda: clock[0])
    first = await store.acquire(scope(), uuid4(), 2)
    with pytest.raises(SessionConflictError):
        await store.acquire(scope(), uuid4(), 2)
    clock[0] = 103.0
    second = await store.acquire(scope(), uuid4(), 2)
    assert second.fence > first.fence
    with pytest.raises(SessionConflictError):
        await store.save(scope(), {}, expected_revision=None, claim=first)
    await store.release(scope(), first)
    await store.renew(scope(), second, 2)
    await store.save(scope(), {}, expected_revision=None, claim=second)


async def test_parallel_claims_have_exactly_one_writer():
    store = InMemoryPersistence()
    results = await asyncio.gather(
        *(store.acquire(scope(), uuid4(), 60) for _ in range(10)),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, SessionConflictError) for result in results) == 9


def intent(audit, item=None):
    requirement = item or Requirement(
        key="platform", description="Platform", classification=RequirementClassification.MANDATORY
    )
    return audit.prepare(
        scope=scope(),
        run_id=uuid4(),
        assessment_id=uuid4(),
        started_at=datetime.now(UTC),
        step=0,
        action="insufficient",
        requirements=[requirement],
        terminal=True,
    )


async def test_real_agxai_artifacts_lineage_explanation_and_idempotent_replay():
    audit = AGXAIAudit()
    pending = intent(audit)
    await audit.commit(pending, scope=scope())
    await audit.commit(pending, scope=scope())
    context = pending.execution.context
    artifacts = await audit.archive.list_run(context=context)
    assert len(artifacts) == len(pending.evidence) + 1
    assert isinstance(await audit.archive.get(pending.evidence[0].id, context=context), Evidence)
    decision = await audit.archive.get(pending.decision.id, context=context)
    assert isinstance(decision, XAIDecision)
    parents = await audit.store.parents(str(pending.decision.id), context=context)
    assert {link.source_id for link in parents} == set(decision.evidence_ids)
    lineage = await audit.store.lineage(str(decision.id), context=context)
    assert len(lineage) == len(pending.links)
    explanation = await audit.runtime.explain_decision(
        decision, run=Run(pending.execution, artifacts=list(artifacts))
    )
    assert explanation.context.run_id == context.run_id
    other_tenant = context.model_copy(update={"tenant_id": "other"})
    assert not await audit.archive.list_run(context=other_tenant)
    assert not await audit.store.parents(str(decision.id), context=other_tenant)
    await audit.delete_run(context)
    assert not await audit.archive.list_run(context=context)
    assert not await audit.store.parents(str(decision.id), context=context)


class FlakyArchive(InMemorySemanticArchive):
    def __init__(self):
        super().__init__()
        self.fail = True

    async def record(self, artifact):
        if self.fail:
            self.fail = False
            raise RuntimeError("sensitive provider failure")
        await super().record(artifact)


async def test_failed_provenance_is_explicit_and_the_same_intent_is_replayable():
    audit = AGXAIAudit(archive=FlakyArchive())
    pending = intent(audit)
    with pytest.raises(ProvenanceError, match="required AGXAI provenance write failed"):
        await audit.commit(pending, scope=scope())
    await audit.commit(pending, scope=scope())
    assert await audit.archive.get(pending.decision.id, context=pending.execution.context)


async def test_mismatched_audit_scope_is_rejected():
    audit = AGXAIAudit()
    pending = intent(audit)
    with pytest.raises(ProvenanceError, match="scope"):
        await audit.commit(pending, scope=scope(tenant="other"))
    assert not await audit.archive.list_run(
        context=ExecutionContext(
            application_id="app",
            tenant_id="other",
            graph_id="sufficiency-engine",
            run_id=pending.execution.context.run_id,
        )
    )
