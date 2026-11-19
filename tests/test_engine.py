import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4, uuid5

import pytest
from agxai import ExecutionContext, StoreFilter
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from sufficiency_engine import (
    AGXAIAudit,
    AnswerSubmission,
    AssessmentStatus,
    ClarificationPayload,
    InteractionResponse,
    SufficiencyEngine,
)
from sufficiency_engine.config import Limits
from sufficiency_engine.exceptions import (
    CallbackError,
    ConfigurationError,
    PersistenceError,
    ProvenanceError,
    SerializationError,
    SessionConflictError,
)
from sufficiency_engine.models import Answer, AnswerStatus, AssumptionStatus, QuestionStatus
from sufficiency_engine.persistence import InMemoryPersistence
from sufficiency_engine.provenance import InMemorySemanticArchive


def proposal(**updates):
    return {
        "key": "platform",
        "description": "Deployment platform",
        "classification": "mandatory",
        "status": "unresolved",
        "necessity": "must_ask",
        "reason": "The platform determines deployment.",
        "question": "Which platform?",
        "answer_type": "string",
        **updates,
    }


def fake_model(*responses):
    messages = [
        AIMessage(
            content=json.dumps(items if isinstance(items, dict) else {"requirements": list(items)})
        )
        for items in responses
    ]
    model = GenericFakeChatModel(messages=iter(messages))

    async def call(prompt):
        return await model.ainvoke(prompt)

    return call


def available(item, value):
    return {**item, "status": "available", "evidence_quote": json.dumps(value, ensure_ascii=False)}


def submission(payload, value):
    question = payload.questions[0]
    return InteractionResponse(
        answers=(
            AnswerSubmission(question_id=question.id, values={question.requirement_ids[0]: value}),
        )
    )


@pytest.mark.parametrize("ready", [False, True])
async def test_preview_includes_optional_questions_without_dispatch_or_storage(ready, monkeypatch):
    required = proposal()
    if ready:
        required.update(status="available", evidence_quote="Linux", necessity="not_needed")
    optional = proposal(
        key="style",
        classification="optional",
        necessity="may_defer",
        question="Which presentation style?",
        reason="The style can tailor the deployment guide.",
    )
    model = AsyncMock(return_value={"requirements": [required, optional]})
    interaction = AsyncMock()
    notification = AsyncMock()
    engine = SufficiencyEngine(
        model_call=model,
        interrupt_call=interaction,
        command_call=notification,
        max_iterations=0,
    )
    storage_calls = []
    for name in ("acquire", "load", "save", "renew", "release"):
        callback = AsyncMock(side_effect=AssertionError("preview accessed persistence"))
        monkeypatch.setattr(engine.persistence, name, callback)
        storage_calls.append(callback)

    result = await engine.execute(input="Deploy Linux", preview_only=True)

    assert result.sufficient is ready
    assert result.status is (
        AssessmentStatus.SUFFICIENT if ready else AssessmentStatus.INSUFFICIENT
    )
    assert [question.required for question in result.questions] == (
        [False] if ready else [True, False]
    )
    assert result.questions[-1].text == optional["question"]
    assert result.questions[-1].reason == optional["reason"]
    assert result.iteration_count == 0
    assert not result.answers and not result.assumptions
    assert result.provenance is not None and result.provenance.decision_ids
    model.assert_awaited_once()
    interaction.assert_not_called()
    notification.assert_not_called()
    for callback in storage_calls:
        callback.assert_not_called()


async def test_preview_flag_does_not_change_subsequent_ordinary_execution():
    items = [
        proposal(status="available", evidence_quote="Linux", necessity="not_needed"),
        proposal(key="style", classification="optional", necessity="may_defer"),
    ]
    notification = AsyncMock()
    engine = SufficiencyEngine(model_call=fake_model(items, items), command_call=notification)
    preview = await engine.execute(input="Deploy Linux", preview_only=True)
    ordinary = await engine.execute(input="Deploy Linux")
    assert preview.sufficient and ordinary.sufficient
    assert len(preview.questions) == 1
    assert not ordinary.questions
    notification.assert_awaited_once_with(ordinary)
    assert await engine.persistence.load(engine._scope(ordinary.session_id)) is not None


@pytest.mark.parametrize("dependency", [False, True])
async def test_preview_question_required_follows_effective_policy(dependency):
    optional = proposal(key="platform", classification="optional", necessity="not_needed")
    items = [optional]
    if dependency:
        items.append(
            proposal(
                key="service",
                status="available",
                evidence_quote="billing",
                necessity="not_needed",
                dependencies=["platform"],
            )
        )
    result = await SufficiencyEngine(
        model_call=fake_model(items), require_optional=not dependency
    ).execute(input="Deploy billing", preview_only=True)
    assert not result.sufficient
    assert len(result.questions) == 1
    assert result.questions[0].required
    assert result.questions[0].requirement_ids == (result.blocking_requirements[0].id,)
    assert result.blocking_requirements[0].classification.value == "optional"


async def test_preview_groups_compatible_questions_but_separates_blocking_from_optional():
    result = await SufficiencyEngine(
        model_call=fake_model(
            [
                proposal(key="first"),
                proposal(key="second"),
                proposal(key="extra", classification="optional", necessity="may_defer"),
            ]
        )
    ).execute(input="Deploy", preview_only=True)
    assert len(result.questions) == 2
    assert len(result.questions[0].requirement_ids) == 2
    assert result.questions[0].required
    assert not result.questions[1].required


@pytest.mark.parametrize(
    "options",
    [
        {"preview_only": "yes"},
        {"preview_only": True, "resume": True, "session_id": "preview"},
        {"preview_only": True, "response": InteractionResponse()},
    ],
)
async def test_invalid_preview_options_fail_before_io(options, monkeypatch):
    model = AsyncMock()
    engine = SufficiencyEngine(model_call=model)
    acquire = AsyncMock()
    monkeypatch.setattr(engine.persistence, "acquire", acquire)
    commit = AsyncMock()
    monkeypatch.setattr(engine.audit, "commit", commit)
    with pytest.raises(ConfigurationError, match="preview_only"):
        await engine.execute(input="Deploy", **options)
    model.assert_not_called()
    acquire.assert_not_called()
    commit.assert_not_called()


async def test_preview_does_not_replace_an_existing_session_and_cannot_be_resumed():
    engine = SufficiencyEngine(
        model_call=fake_model(
            [proposal()],
            [proposal(status="available", evidence_quote="Linux", necessity="not_needed")],
            [proposal()],
        )
    )
    original = await engine.execute(input="Deploy", session_id="existing")
    stored = await engine.persistence.load(engine._scope("existing"))
    preview = await engine.execute(input="Deploy Linux", session_id="existing", preview_only=True)
    assert preview.sufficient
    assert await engine.persistence.load(engine._scope("existing")) == stored
    assert (await engine.execute(input="Deploy", session_id="existing", resume=True)) == original
    snapshot = await engine.execute(input="Deploy", preview_only=True)
    with pytest.raises(ConfigurationError, match="session does not exist"):
        await engine.execute(input="Deploy", session_id=snapshot.session_id, resume=True)


async def test_preview_does_not_assume_or_invent_questions_for_unanswerable_blockers():
    result = await SufficiencyEngine(
        model_call=fake_model(
            [
                proposal(
                    necessity="may_assume",
                    assumption={
                        "description": "Use Linux",
                        "value": "Linux",
                        "risk": "low",
                        "reversible": True,
                    },
                ),
                proposal(key="permission", necessity="must_block", question="Can this be done?"),
                proposal(
                    key="irrelevant",
                    classification="optional",
                    necessity="not_needed",
                    question=None,
                ),
            ]
        ),
        allow_assumptions=True,
    ).execute(input="Deploy", preview_only=True)
    assert not result.sufficient
    assert len(result.blocking_requirements) == 2
    assert len(result.questions) == 1
    assert not result.assumptions


async def test_preview_keeps_optional_not_needed_question_without_asking_available_information():
    result = await SufficiencyEngine(
        model_call=fake_model(
            [
                proposal(status="available", evidence_quote="Linux", necessity="not_needed"),
                proposal(
                    key="style",
                    classification="optional",
                    necessity="not_needed",
                    question="Which style?",
                ),
            ]
        )
    ).execute(input="Deploy Linux", preview_only=True)
    assert result.sufficient
    assert [(question.text, question.required) for question in result.questions] == [
        ("Which style?", False)
    ]


@pytest.mark.parametrize(
    ("items", "limits", "code"),
    [
        (
            [proposal(status="available", evidence_quote="invented")],
            Limits(),
            "model_response_error",
        ),
        (
            [
                proposal(),
                proposal(
                    key="other",
                    question="Which region?",
                    classification="optional",
                    necessity="may_defer",
                ),
            ],
            Limits(max_questions=1),
            "clarification_error",
        ),
        ([proposal(dependencies=["unknown"])], Limits(), "model_response_error"),
    ],
)
async def test_preview_validation_failures_are_explicit_and_audited(items, limits, code):
    result = await SufficiencyEngine(model_call=fake_model(items), limits=limits).execute(
        input="Deploy", preview_only=True
    )
    assert result.status is AssessmentStatus.FAILED
    assert not result.sufficient
    assert result.errors[-1].code == code
    assert result.provenance is not None


async def test_empty_preview_does_not_establish_readiness():
    result = await SufficiencyEngine(model_call=fake_model([])).execute(
        input="Deploy", preview_only=True
    )
    assert result.status is AssessmentStatus.INSUFFICIENT
    assert result.warnings[0].code == "empty_discovery"
    assert not result.questions


async def test_preview_fails_explicitly_if_audit_does_not_produce_a_terminal_result(monkeypatch):
    engine = SufficiencyEngine(model_call=fake_model([proposal()]))
    monkeypatch.setattr(engine, "_commit_audit", AsyncMock())
    with pytest.raises(SerializationError, match="preview has no result"):
        await engine.execute(input="Deploy", preview_only=True)


async def test_resume_rejects_unknown_persisted_schema_without_rediscovery():
    engine = SufficiencyEngine(model_call=fake_model([proposal()]))
    result = await engine.execute(input="Deploy", session_id="future-state")
    scope = engine._scope(result.session_id)
    claim = await engine.persistence.acquire(scope, uuid4(), 60)
    try:
        stored = await engine.persistence.load(scope)
        assert stored is not None
        stored.state["schema_version"] = 999
        await engine.persistence.save(
            scope, stored.state, expected_revision=stored.revision, claim=claim
        )
    finally:
        await engine.persistence.release(scope, claim)
    with pytest.raises(SerializationError, match="unsupported schema"):
        await engine.execute(input="Deploy", session_id=result.session_id, resume=True)
    retained = await engine.persistence.load(scope)
    assert retained is not None and retained.state["schema_version"] == 999


async def test_complete_task_is_audited_and_notification_is_not_replayed():
    notifications = []
    source = uuid4()
    engine = SufficiencyEngine(
        model_call=fake_model(
            [proposal(status="available", evidence_quote="Linux", necessity="not_needed")]
        ),
        command_call=notifications.append,
    )
    result = await engine.execute(input="Deploy to Linux", source_references=(source,))
    assert result.sufficient
    assert result.iteration_count == 0
    assert notifications == [result]
    assert result.provenance is not None
    archive = engine.audit.archive
    state = await engine.persistence.load(engine._scope(result.session_id))
    assert state is not None
    from sufficiency_engine._state import AssessmentState

    parsed = AssessmentState.model_validate(state.state)
    context = engine.audit.prepare(
        scope=parsed.scope,
        run_id=parsed.run_id,
        assessment_id=parsed.assessment_id,
        started_at=parsed.started_at,
        step=0,
        action="sufficient",
        requirements=parsed.requirements,
        terminal=True,
    ).execution.context
    artifacts = await archive.list_run(context=context)
    assert any(
        getattr(artifact, "source", None) and artifact.source.source_id == source
        for artifact in artifacts
    )
    assert "Deploy to Linux" not in repr(artifacts)
    resumed = await engine.execute(
        input="Deploy to Linux", session_id=result.session_id, resume=True
    )
    assert resumed == result
    assert notifications == [result]


async def test_clarification_preserves_identity_and_falsey_answer():
    initial = proposal(answer_type="integer", question="How many replicas?")
    calls = []

    async def interrupt(payload: ClarificationPayload):
        calls.append(payload)
        return submission(payload, 0)

    engine = SufficiencyEngine(
        model_call=fake_model([initial], [available(initial, 0)]), interrupt_call=interrupt
    )
    result = await engine.execute(input="Deploy the service")
    assert result.sufficient
    assert result.iteration_count == 1
    assert result.answers[0].value == 0
    assert result.answers[0].status is AnswerStatus.VALID
    assert result.requirements[0].id == calls[0].requirements[0].id
    assert result.questions[0].status is QuestionStatus.ANSWERED


async def test_invalid_answer_gets_a_targeted_stable_followup():
    initial = proposal(answer_type="integer", question="How many replicas?")
    payloads = []

    async def interrupt(payload):
        payloads.append(payload)
        return submission(payload, "bad" if len(payloads) == 1 else 0)

    engine = SufficiencyEngine(
        model_call=fake_model([initial], [initial], [available(initial, 0)]),
        interrupt_call=interrupt,
    )
    result = await engine.execute(input="Deploy the service")
    assert result.sufficient
    assert result.iteration_count == 2
    assert [answer.status for answer in result.answers] == [
        AnswerStatus.INVALID,
        AnswerStatus.VALID,
    ]
    assert len(payloads[1].questions) == 1
    assert payloads[1].questions[0].follow_up_to == payloads[0].questions[0].id
    assert payloads[1].questions[0].requirement_ids == payloads[0].questions[0].requirement_ids


async def test_combined_question_preserves_partial_answers_and_targets_missing_slot():
    shared = "Which platform and region should be used?"
    platform = proposal(question=shared)
    region = proposal(key="region", description="Deployment region", question=shared)
    payloads = []

    async def interrupt(payload):
        payloads.append(payload)
        question = payload.questions[0]
        assert len(payload.questions) == 1
        if len(payloads) == 1:
            assert len(question.requirement_ids) == 2
            return InteractionResponse(
                answers=(
                    AnswerSubmission(
                        question_id=question.id, values={question.requirement_ids[0]: "Linux"}
                    ),
                )
            )
        assert question.follow_up_to == payloads[0].questions[0].id
        assert question.requirement_ids == (payloads[0].questions[0].requirement_ids[1],)
        assert "region" in question.text.lower()
        assert "platform" not in question.text.lower()
        return submission(payload, "eu-west")

    result = await SufficiencyEngine(
        model_call=fake_model(
            [platform, region],
            [available(platform, "Linux"), region],
            [available(platform, "Linux"), available(region, "eu-west")],
        ),
        interrupt_call=interrupt,
    ).execute(input="Deploy a service")
    assert result.sufficient
    assert [answer.value for answer in result.answers] == ["Linux", "eu-west"]
    assert result.questions[0].status is QuestionStatus.PARTIALLY_ANSWERED
    assert result.questions[1].status is QuestionStatus.ANSWERED


async def test_conflicting_supplied_facts_require_an_explicit_correction():
    initial = proposal()
    conflicting = proposal(
        conflicts=["Windows", "Linux"],
        question="You supplied Windows and Linux; which is the intended platform?",
    )
    payloads = []

    async def interrupt(payload):
        payloads.append(payload)
        if len(payloads) == 1:
            return submission(payload, "Linux")
        question = payload.questions[0]
        requirement_id = question.requirement_ids[0]
        return InteractionResponse(
            answers=(
                AnswerSubmission(
                    question_id=question.id,
                    values={requirement_id: "Windows"},
                    corrections=(requirement_id,),
                ),
            )
        )

    result = await SufficiencyEngine(
        model_call=fake_model([initial], [conflicting], [available(initial, "Windows")]),
        interrupt_call=interrupt,
    ).execute(input="Deploy on Windows")
    assert result.sufficient
    assert [answer.status for answer in result.answers] == [
        AnswerStatus.CONTRADICTORY,
        AnswerStatus.VALID,
    ]
    assert payloads[1].questions[0].follow_up_to == payloads[0].questions[0].id


async def test_model_cannot_claim_availability_using_unprovided_evidence():
    item = proposal(status="available", evidence_quote="Linux")
    result = await SufficiencyEngine(model_call=fake_model([item])).execute(input="Deploy")
    assert result.status is AssessmentStatus.FAILED
    assert result.errors[0].code == "model_response_error"


async def test_optional_prerequisite_of_required_requirement_is_clarified():
    root = proposal(
        key="service",
        description="Service to deploy",
        status="available",
        evidence_quote="service",
        dependencies=["platform"],
        necessity="not_needed",
    )
    dependency = proposal(classification="optional")

    async def interrupt(payload):
        assert payload.questions[0].requirement_ids == (payload.requirements[1].id,)
        return submission(payload, "Linux")

    result = await SufficiencyEngine(
        model_call=fake_model([root, dependency], [root, available(dependency, "Linux")]),
        interrupt_call=interrupt,
    ).execute(input="Deploy the service")
    assert result.sufficient
    assert result.requirements[1].classification.value == "optional"


async def test_requirement_split_preserves_lineage_and_requires_successors():
    parent = proposal(key="deployment", question="What deployment is needed?")
    region = proposal(key="region", description="Region", question="Which region?")
    platform = proposal(key="platform", question="Which platform?")
    split = {
        "requirements": [region, platform],
        "lineage": [
            {
                "operation": "split",
                "parent_keys": ["deployment"],
                "successor_keys": ["region", "platform"],
            }
        ],
    }

    async def interrupt(payload):
        return InteractionResponse(
            answers=tuple(
                AnswerSubmission(
                    question_id=question.id, values={question.requirement_ids[0]: "approved"}
                )
                for question in payload.questions
            )
        )

    result = await SufficiencyEngine(
        model_call=fake_model(
            [parent], split, [available(region, "approved"), available(platform, "approved")]
        ),
        interrupt_call=interrupt,
    ).execute(input="Deploy a service")
    assert result.sufficient
    assert result.requirements[0].lifecycle.value == "superseded"
    change = next(event for event in result.lineage if event.operation == "split")
    assert change.parent_ids == (result.requirements[0].id,)
    assert set(change.successor_ids) == {result.requirements[1].id, result.requirements[2].id}
    assert all(result.requirements[0].id in item.parent_ids for item in result.requirements[1:])


async def test_requirement_merge_preserves_all_parent_identities():
    first = proposal(key="platform", question="Which platform?")
    second = proposal(key="region", description="Region", question="Which region?")
    merged = proposal(key="deployment", description="Deployment", question="Which deployment?")
    change = {
        "requirements": [merged],
        "lineage": [
            {
                "operation": "merge",
                "parent_keys": ["platform", "region"],
                "successor_keys": ["deployment"],
            }
        ],
    }

    async def interrupt(payload):
        return InteractionResponse(
            answers=tuple(
                AnswerSubmission(
                    question_id=question.id, values={question.requirement_ids[0]: "approved"}
                )
                for question in payload.questions
            )
        )

    result = await SufficiencyEngine(
        model_call=fake_model([first, second], change, [available(merged, "approved")]),
        interrupt_call=interrupt,
    ).execute(input="Deploy a service")
    assert result.sufficient
    event = next(event for event in result.lineage if event.operation == "merge")
    parents = result.requirements[:2]
    successor = result.requirements[2]
    assert set(event.parent_ids) == {item.id for item in parents}
    assert event.successor_ids == (successor.id,)
    assert set(successor.parent_ids) == set(event.parent_ids)
    assert all(item.lifecycle.value == "superseded" for item in parents)


async def test_only_available_unreferenced_requirement_can_be_retired():
    satisfied = proposal(key="platform", status="available", evidence_quote="Linux")
    remaining = proposal(key="region", description="Region", question="Which region?")
    retired = {
        "requirements": [available(remaining, "eu-west")],
        "lineage": [{"operation": "retire", "parent_keys": ["platform"]}],
    }

    async def interrupt(payload):
        return submission(payload, "eu-west")

    result = await SufficiencyEngine(
        model_call=fake_model([satisfied, remaining], retired), interrupt_call=interrupt
    ).execute(input="Deploy to Linux")
    assert result.sufficient
    assert result.requirements[0].lifecycle.value == "retired"
    event = next(event for event in result.lineage if event.operation == "retire")
    assert event.parent_ids == (result.requirements[0].id,)
    assert not event.successor_ids

    unresolved = proposal(key="platform")
    unsafe = await SufficiencyEngine(
        model_call=fake_model([unresolved, remaining], retired),
        interrupt_call=lambda payload: InteractionResponse(
            answers=(
                AnswerSubmission(
                    question_id=payload.questions[1].id,
                    values={payload.questions[1].requirement_ids[0]: "eu-west"},
                ),
            )
        ),
    ).execute(input="Deploy")
    assert unsafe.status is AssessmentStatus.FAILED
    assert unsafe.errors[-1].code == "model_response_error"


async def test_lineage_cannot_silently_weaken_a_mandatory_requirement():
    parent = proposal(key="parent")
    successor = proposal(key="successor", classification="optional")
    replacement = {
        "requirements": [successor],
        "lineage": [
            {
                "operation": "supersede",
                "parent_keys": ["parent"],
                "successor_keys": ["successor"],
            }
        ],
    }

    async def interrupt(payload):
        return submission(payload, "answer")

    result = await SufficiencyEngine(
        model_call=fake_model([parent], replacement), interrupt_call=interrupt
    ).execute(input="Deploy")
    assert result.status is AssessmentStatus.FAILED
    assert result.errors[0].code == "model_response_error"


async def test_declined_question_is_not_repeated():
    item = proposal()
    calls = 0

    async def interrupt(payload):
        nonlocal calls
        calls += 1
        question = payload.questions[0]
        return InteractionResponse(
            answers=(AnswerSubmission(question_id=question.id, declined=question.requirement_ids),)
        )

    result = await SufficiencyEngine(
        model_call=fake_model([item], [item]), interrupt_call=interrupt
    ).execute(input="Deploy the service")
    assert not result.sufficient
    assert result.status is AssessmentStatus.INSUFFICIENT
    assert len(result.blocking_requirements) == 1
    assert calls == 1


async def test_approved_safe_assumption_satisfies_only_when_enabled():
    item = proposal(
        necessity="may_assume",
        answer_type="integer",
        question=None,
        assumption={"description": "One replica", "value": 1, "risk": "low", "reversible": True},
    )

    async def approve(payload):
        return InteractionResponse(assumption_approvals={payload.assumptions[0].id: True})

    result = await SufficiencyEngine(
        model_call=fake_model([item], [item]), interrupt_call=approve, allow_assumptions=True
    ).execute(input="Deploy the service")
    assert result.sufficient
    assert result.assumptions[0].status is AssumptionStatus.APPROVED
    disabled = await SufficiencyEngine(model_call=fake_model([item])).execute(
        input="Deploy the service"
    )
    assert not disabled.sufficient
    assert disabled.blocking_requirements


async def test_empty_discovery_and_iteration_limit_fail_closed():
    empty = await SufficiencyEngine(model_call=fake_model([])).execute(input="A task")
    assert empty.status is AssessmentStatus.INSUFFICIENT
    assert empty.warnings[0].code == "empty_discovery"
    item = proposal()

    async def no_answer(payload):
        return InteractionResponse(answers=(AnswerSubmission(question_id=payload.questions[0].id),))

    limited = await SufficiencyEngine(
        model_call=fake_model([item], [item], [item]),
        interrupt_call=no_answer,
        max_iterations=2,
    ).execute(input="Deploy the service")
    assert limited.status is AssessmentStatus.ITERATION_LIMIT_REACHED
    assert limited.iteration_count == 2
    assert limited.blocking_requirements
    assert limited.provenance is not None


class FlakyArchive(InMemorySemanticArchive):
    def __init__(self):
        super().__init__()
        self.fail_once = True

    async def record(self, artifact):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("private")
        await super().record(artifact)


class WriteThenFailArchive(InMemorySemanticArchive):
    async def record(self, artifact):
        await super().record(artifact)
        raise RuntimeError("acknowledgement lost after write")


async def test_failed_preview_audit_is_not_advertised_as_resumable():
    item = proposal(status="available", evidence_quote="Linux", necessity="not_needed")
    engine = SufficiencyEngine(
        model_call=fake_model([item], [item]), audit=AGXAIAudit(archive=FlakyArchive())
    )
    failed = await engine.execute(input="Deploy Linux", preview_only=True)
    assert failed.status is AssessmentStatus.FAILED
    assert not failed.sufficient
    assert failed.errors[-1].code == "provenance_error"
    assert not failed.errors[-1].retryable
    assert "not saved" in failed.errors[-1].message
    assert failed.provenance is None
    assert failed.preview_run_id is not None
    context = ExecutionContext(
        application_id=engine.application_id,
        tenant_id=engine.tenant_id,
        graph_id="sufficiency-engine",
        run_id=failed.preview_run_id,
        thread_id=failed.session_id,
    )
    query = StoreFilter(
        application_id=engine.application_id, tenant_id=engine.tenant_id, run_id=context.run_id
    )
    assert [record async for record in engine.audit.store.query(query)]
    await engine.delete_preview_audit(session_id=failed.session_id, run_id=failed.preview_run_id)
    assert not [record async for record in engine.audit.store.query(query)]
    assert not await engine.audit.archive.list_run(context=context)
    assert await engine.persistence.load(engine._scope(failed.session_id)) is None
    fresh = await engine.execute(input="Deploy Linux", preview_only=True)
    assert fresh.sufficient
    assert fresh.assessment_id != failed.assessment_id


async def test_failed_preview_cleanup_removes_partially_written_archive():
    item = proposal(status="available", evidence_quote="Linux", necessity="not_needed")
    engine = SufficiencyEngine(
        model_call=fake_model([item]), audit=AGXAIAudit(archive=WriteThenFailArchive())
    )
    result = await engine.execute(input="Linux", preview_only=True)
    assert result.status is AssessmentStatus.FAILED
    assert result.provenance is None and result.preview_run_id is not None
    context = ExecutionContext(
        application_id=engine.application_id,
        tenant_id=engine.tenant_id,
        graph_id="sufficiency-engine",
        run_id=result.preview_run_id,
        thread_id=result.session_id,
    )
    assert await engine.audit.archive.list_run(context=context)
    await engine.delete_preview_audit(session_id=result.session_id, run_id=result.preview_run_id)
    assert not await engine.audit.archive.list_run(context=context)


async def test_failed_provenance_preserves_intent_and_resume_does_not_repeat_model():
    calls = 0
    model = fake_model(
        [proposal(status="available", evidence_quote="Linux", necessity="not_needed")]
    )

    async def counted(messages):
        nonlocal calls
        calls += 1
        return await model(messages)

    engine = SufficiencyEngine(model_call=counted, audit=AGXAIAudit(archive=FlakyArchive()))
    failed = await engine.execute(input="Deploy Linux")
    assert failed.status is AssessmentStatus.FAILED
    assert failed.errors[-1].code == "provenance_error"
    resumed = await engine.execute(input="Deploy Linux", session_id=failed.session_id, resume=True)
    assert resumed.sufficient
    assert calls == 1


async def test_ambiguous_callback_is_not_replayed_and_explicit_response_recovers():
    item = proposal()
    calls = 0

    async def fail(_payload):
        nonlocal calls
        calls += 1
        raise RuntimeError("provider may have sent a message")

    engine = SufficiencyEngine(
        model_call=fake_model([item], [available(item, "Linux")]), interrupt_call=fail
    )
    failed = await engine.execute(input="Deploy")
    assert failed.errors[-1].code == "clarification_callback_error"
    question = failed.questions[0]
    again = await engine.execute(input="Deploy", session_id=failed.session_id, resume=True)
    assert again.errors[-1].code == "interaction_ambiguous"
    answer = InteractionResponse(
        answers=(
            AnswerSubmission(
                question_id=question.id, values={question.requirement_ids[0]: "Linux"}
            ),
        )
    )
    recovered = await engine.execute(
        input="Deploy", session_id=failed.session_id, resume=True, response=answer
    )
    assert recovered.sufficient
    assert calls == 1


async def test_cancellation_and_same_session_conflict():
    entered = asyncio.Event()
    release = asyncio.Event()
    item = proposal()

    async def interrupt(_payload):
        entered.set()
        await release.wait()
        return InteractionResponse(cancelled=True)

    engine = SufficiencyEngine(model_call=fake_model([item]), interrupt_call=interrupt)
    task = asyncio.create_task(engine.execute(input="Deploy", session_id="shared"))
    await entered.wait()
    with pytest.raises(SessionConflictError):
        await engine.execute(input="Deploy", session_id="shared", resume=True)
    release.set()
    result = await task
    assert result.status is AssessmentStatus.CANCELLED
    assert not result.sufficient


async def test_concurrent_sessions_and_engines_remain_isolated():
    async def model(messages):
        await asyncio.sleep(0)
        task = json.loads(messages[-1]["content"])["task"]
        return {
            "requirements": [
                proposal(status="available", evidence_quote=task, necessity="not_needed")
            ]
        }

    first = SufficiencyEngine(model_call=model, tenant_id="tenant-a")
    second = SufficiencyEngine(
        model_call=model,
        tenant_id="tenant-b",
        persistence=first.persistence,
        audit=first.audit,
    )
    inputs = [f"Task {index}" for index in range(20)]
    results = await asyncio.gather(
        *(
            (first if index % 2 == 0 else second).execute(input=task, session_id=f"s{index}")
            for index, task in enumerate(inputs)
        )
    )
    assert all(result.sufficient for result in results)
    assert len({result.assessment_id for result in results}) == len(inputs)
    assert len({result.provenance.run_id for result in results if result.provenance}) == len(inputs)
    assert all(result.session_id == f"s{index}" for index, result in enumerate(results))
    for index in range(len(inputs)):
        other = second if index % 2 == 0 else first
        assert await other.persistence.load(other._scope(f"s{index}")) is None


async def test_task_input_utf8_limits_and_invalid_unicode_are_rejected_explicitly():
    engine = SufficiencyEngine(
        model_call=fake_model(
            [proposal(status="available", evidence_quote="é", necessity="not_needed")]
        ),
        limits=Limits(max_input_bytes=128),
    )
    assert (await engine.execute(input="é" * 64)).sufficient
    with pytest.raises(ConfigurationError, match="size limit"):
        await engine.execute(input="é" * 64 + "x")
    with pytest.raises(ConfigurationError, match="UTF-8"):
        await engine.execute(input="\ud800")


async def test_terminal_callback_failure_is_explicit_and_never_automatically_replayed():
    calls = 0

    async def notify(_result):
        nonlocal calls
        calls += 1
        raise RuntimeError("sent but acknowledgement failed")

    engine = SufficiencyEngine(
        model_call=fake_model([proposal(status="available", evidence_quote="Linux")]),
        command_call=notify,
    )
    with pytest.raises(CallbackError, match="notification failed"):
        await engine.execute(input="Linux", session_id="notify")
    with pytest.raises(CallbackError, match="ambiguous"):
        await engine.execute(input="Linux", session_id="notify", resume=True)
    assert calls == 1


class FailingDeletionArchive(InMemorySemanticArchive):
    def __init__(self):
        super().__init__()
        self.fail_once = True

    async def delete_run(self, context):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("deletion failed after a partial external side effect")
        await super().delete_run(context)


async def test_partial_deletion_is_tombstoned_until_retry():
    engine = SufficiencyEngine(
        model_call=fake_model([proposal(status="available", evidence_quote="Linux")]),
        audit=AGXAIAudit(archive=FailingDeletionArchive()),
    )
    result = await engine.execute(input="Linux")
    with pytest.raises(ProvenanceError, match="provenance deletion failed"):
        await engine.delete_session(result.session_id)
    with pytest.raises(PersistenceError, match="deletion is pending"):
        await engine.execute(input="Linux", session_id=result.session_id, resume=True)
    await engine.delete_session(result.session_id)
    assert await engine.persistence.load(engine._scope(result.session_id)) is None


async def test_preview_cleanup_is_scoped_idempotent_and_preserves_sessions_and_other_runs():
    item = proposal(status="available", evidence_quote="Linux", necessity="not_needed")
    audit = AGXAIAudit()
    engine = SufficiencyEngine(
        model_call=fake_model([item], [item], [item]), audit=audit, tenant_id="one"
    )
    session = await engine.execute(input="Linux", session_id="shared")
    first = await engine.execute(input="Linux", session_id="shared", preview_only=True)
    second = await engine.execute(input="Linux", session_id="shared", preview_only=True)
    assert first.preview_run_id is not None and first.provenance is not None
    assert session.provenance is not None
    assert first.preview_run_id == first.provenance.run_id
    assert second.preview_run_id is not None
    assert session.preview_run_id is None
    stored = await engine.persistence.load(engine._scope("shared"))
    assert stored is not None

    def context(run_id, tenant="one"):
        return ExecutionContext(
            application_id=engine.application_id,
            tenant_id=tenant,
            graph_id="sufficiency-engine",
            run_id=run_id,
            thread_id="shared",
        )

    def query(run_id, tenant="one"):
        return StoreFilter(application_id=engine.application_id, tenant_id=tenant, run_id=run_id)

    other = SufficiencyEngine(model_call=fake_model([item]), audit=audit, tenant_id="two")
    await other.delete_preview_audit(session_id="shared", run_id=first.preview_run_id)
    other_app = SufficiencyEngine(
        model_call=fake_model([item]), audit=audit, application_id="other"
    )
    await other_app.delete_preview_audit(session_id="shared", run_id=first.preview_run_id)
    assert await audit.archive.list_run(context=context(first.preview_run_id))
    assert [record async for record in audit.store.query(query(first.preview_run_id))]
    await engine.delete_preview_audit(session_id="shared", run_id=first.preview_run_id)
    await engine.delete_preview_audit(session_id="shared", run_id=first.preview_run_id)
    assert not await audit.archive.list_run(context=context(first.preview_run_id))
    assert not [record async for record in audit.store.query(query(first.preview_run_id))]
    assert await audit.archive.list_run(context=context(second.preview_run_id))
    assert await audit.archive.list_run(context=context(session.provenance.run_id))
    assert await engine.persistence.load(engine._scope("shared")) == stored
    assert (await engine.execute(input="Linux", session_id="shared", resume=True)) == session
    await engine.delete_session("shared")
    assert await audit.archive.list_run(context=context(second.preview_run_id))


async def test_preview_cleanup_rejects_invalid_identifiers():
    engine = SufficiencyEngine(model_call=fake_model([]))
    invalid_run_id: Any = "not-a-uuid"
    with pytest.raises(ConfigurationError, match="run ID"):
        await engine.delete_preview_audit(session_id="valid", run_id=invalid_run_id)
    with pytest.raises(ConfigurationError, match="session ID"):
        await engine.delete_preview_audit(session_id="", run_id=uuid4())


async def test_preview_cleanup_can_retry_after_partial_deletion():
    item = proposal(status="available", evidence_quote="Linux", necessity="not_needed")
    audit = AGXAIAudit(archive=FailingDeletionArchive())
    engine = SufficiencyEngine(model_call=fake_model([item]), audit=audit)
    result = await engine.execute(input="Linux", preview_only=True)
    assert result.preview_run_id is not None
    context = ExecutionContext(
        application_id=engine.application_id,
        tenant_id=engine.tenant_id,
        graph_id="sufficiency-engine",
        run_id=result.preview_run_id,
        thread_id=result.session_id,
    )
    query = StoreFilter(
        application_id=engine.application_id, tenant_id=engine.tenant_id, run_id=context.run_id
    )
    with pytest.raises(ProvenanceError, match="provenance deletion failed"):
        await engine.delete_preview_audit(
            session_id=result.session_id, run_id=result.preview_run_id
        )
    assert not [record async for record in audit.store.query(query)]
    assert await audit.archive.list_run(context=context)
    await engine.delete_preview_audit(session_id=result.session_id, run_id=result.preview_run_id)
    assert not await audit.archive.list_run(context=context)


async def test_unresolved_reassessment_cannot_reuse_a_structurally_valid_answer():
    item = proposal(key="region", description="Deployment region", question="Which region?")
    result = await SufficiencyEngine(
        model_call=fake_model([item], [item]),
        interrupt_call=lambda payload: submission(payload, "Linux"),
        max_iterations=1,
    ).execute(input="Deploy the service")
    assert result.status is AssessmentStatus.ITERATION_LIMIT_REACHED
    assert not result.sufficient
    assert result.requirements[0].status.value == "unresolved"
    assert not result.requirements[0].source_evidence_ids
    assert result.answers[0].value == "Linux"
    assert result.answers[0].status is AnswerStatus.AMBIGUOUS


@pytest.mark.parametrize(
    "updates",
    [
        {"description": "Deployment region"},
        {"answer_type": "integer"},
        {"constraints": {"choices": ["Europe"]}},
        {"answer_slot": "region"},
    ],
)
async def test_requirement_identity_drift_requires_explicit_lineage(updates):
    item = proposal()
    result = await SufficiencyEngine(
        model_call=fake_model([item], [{**item, **updates}]),
        interrupt_call=lambda payload: submission(payload, "Linux"),
    ).execute(input="Deploy the service")
    assert result.status is AssessmentStatus.FAILED
    assert result.errors[-1].code == "model_response_error"
    assert "identity" in result.errors[-1].message


async def test_new_requirement_cannot_borrow_another_requirements_answer():
    platform = proposal()
    region = proposal(key="region", description="Geographic deployment region")
    result = await SufficiencyEngine(
        model_call=fake_model(
            [platform], [available(platform, "Linux"), available(region, "Linux")]
        ),
        interrupt_call=lambda payload: submission(payload, "Linux"),
    ).execute(input="Deploy the service")
    assert result.status is AssessmentStatus.FAILED
    assert not result.sufficient
    assert result.errors[-1].code == "model_response_error"


async def test_existing_requirement_cannot_cite_a_sibling_answer():
    platform = proposal()
    region = proposal(key="region", description="Deployment region", question="Which region?")

    async def interrupt(payload):
        return InteractionResponse(
            answers=(
                AnswerSubmission(
                    question_id=payload.questions[0].id,
                    values={payload.questions[0].requirement_ids[0]: "Linux"},
                ),
            )
        )

    result = await SufficiencyEngine(
        model_call=fake_model(
            [platform, region], [available(platform, "Linux"), available(region, "Linux")]
        ),
        interrupt_call=interrupt,
    ).execute(input="Deploy the service")
    assert result.status is AssessmentStatus.FAILED
    assert not result.sufficient


async def test_explicit_supersede_lineage_may_carry_parent_answer_evidence():
    platform = proposal()
    runtime = proposal(key="runtime", description="Runtime operating system")
    result = await SufficiencyEngine(
        model_call=fake_model(
            [platform],
            {
                "requirements": [available(runtime, "Linux")],
                "lineage": [
                    {
                        "operation": "supersede",
                        "parent_keys": ["platform"],
                        "successor_keys": ["runtime"],
                    }
                ],
            },
        ),
        interrupt_call=lambda payload: submission(payload, "Linux"),
    ).execute(input="Deploy the service")
    assert result.sufficient
    parent, successor = result.requirements
    assert parent.lifecycle.value == "superseded"
    assert successor.source_evidence_ids == (
        uuid5(
            result.assessment_id,
            f"answer:{result.answers[0].question_id}:{parent.id}",
        ),
    )


async def test_task_sources_are_preserved_without_claim_specific_attribution():
    first = proposal(status="available", evidence_quote="Linux")
    second = proposal(
        key="region", description="Region", status="available", evidence_quote="Europe"
    )
    sources = (uuid4(), uuid4())
    engine = SufficiencyEngine(model_call=fake_model([first, second]))
    result = await engine.execute(input="Deploy Linux in Europe", source_references=sources)
    task_evidence = uuid5(result.assessment_id, "task-input")
    assert result.sufficient
    assert all(item.source_evidence_ids == (task_evidence,) for item in result.requirements)
    assert result.provenance is not None
    assert {uuid5(result.assessment_id, f"source:{source}") for source in sources}.issubset(
        result.provenance.evidence_ids
    )


async def test_malformed_standalone_response_consumes_persisted_interaction_budget():
    item = proposal()
    engine = SufficiencyEngine(
        model_call=fake_model([item]),
        interrupt_call=lambda _payload: {"answers": [{"question_id": "bad"}]},
        max_iterations=2,
    )
    first = await engine.execute(input="Deploy")
    assert first.status is AssessmentStatus.FAILED
    assert first.iteration_count == 1
    second = await engine.execute(
        input="Deploy",
        session_id=first.session_id,
        resume=True,
        response={"answers": [{"question_id": "bad"}]},
    )
    assert second.status is AssessmentStatus.ITERATION_LIMIT_REACHED
    assert second.iteration_count == 2
    assert second.provenance is not None


SOURCE = uuid4()


def answer_all(value):
    def interrupt(payload):
        return InteractionResponse(
            answers=tuple(
                AnswerSubmission(
                    question_id=question.id,
                    values={requirement_id: value for requirement_id in question.requirement_ids},
                )
                for question in payload.questions
            )
        )

    return interrupt


def failing_interrupt(_payload):
    raise RuntimeError("delivery outcome unknown")


async def edit_stored_state(engine, session_id, mutate):
    scope = engine._scope(session_id)
    claim = await engine.persistence.acquire(scope, uuid4(), 60)
    try:
        stored = await engine.persistence.load(scope)
        assert stored is not None
        mutate(stored.state)
        await engine.persistence.save(
            scope, stored.state, expected_revision=stored.revision, claim=claim
        )
    finally:
        await engine.persistence.release(scope, claim)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"model_call": "not callable"}, "model_call must be callable"),
        ({"interrupt_call": 1}, "interrupt_call must be callable"),
        ({"command_call": 1}, "command_call must be callable"),
        ({"telemetry_call": 1}, "telemetry_call must be callable"),
        ({"max_iterations": -1}, "invalid engine configuration"),
        ({"max_model_retries": 11}, "invalid engine configuration"),
        ({"tenant_id": "tenant with spaces"}, "invalid engine configuration"),
        ({"application_id": ""}, "invalid engine configuration"),
        ({"persistence": object()}, "persistence must implement PersistenceABC"),
        ({"audit": object()}, "audit must be an AGXAIAudit"),
        ({"embedding_model": object()}, "embedding_model must implement EmbeddingModelABC"),
    ],
)
def test_invalid_engine_configuration_is_rejected(options, message):
    with pytest.raises(ConfigurationError, match=message):
        arguments: dict[str, Any] = {"model_call": fake_model([]), **options}
        SufficiencyEngine(**arguments)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"input": "   "}, "nonempty text"),
        ({"input": None}, "nonempty text"),
        ({"input": "Deploy", "resume": True}, "requires a session ID"),
        ({"input": "Deploy", "response": InteractionResponse()}, "requires resume=True"),
        ({"input": "Deploy", "session_id": "not/opaque"}, "opaque identifier"),
        ({"input": "Deploy", "session_id": "missing", "resume": True}, "does not exist"),
        (
            {
                "input": "Deploy",
                "session_id": "refs",
                "source_references": (uuid4(), uuid4(), SOURCE),
            },
            "source reference limit",
        ),
        (
            {"input": "Deploy", "session_id": "refs", "source_references": (str(SOURCE),)},
            "must be UUIDs",
        ),
        (
            {"input": "Deploy", "session_id": "refs", "source_references": (SOURCE, SOURCE)},
            "must be unique",
        ),
    ],
)
async def test_invalid_execute_arguments_are_rejected_without_creating_sessions(options, message):
    engine = SufficiencyEngine(
        model_call=fake_model([proposal()]), limits=Limits(max_requirements=2)
    )
    with pytest.raises(ConfigurationError, match=message):
        await engine.execute(**options)
    for session_id in ("missing", "refs"):
        assert await engine.persistence.load(engine._scope(session_id)) is None


async def test_existing_session_must_be_resumed_with_matching_inputs():
    engine = SufficiencyEngine(
        model_call=fake_model([proposal(status="available", evidence_quote="Linux")])
    )
    result = await engine.execute(input="Linux", session_id="existing", source_references=(SOURCE,))
    with pytest.raises(SessionConflictError, match="already exists"):
        await engine.execute(input="Linux", session_id="existing")
    with pytest.raises(ConfigurationError, match="does not match"):
        await engine.execute(input="Windows", session_id="existing", resume=True)
    with pytest.raises(ConfigurationError, match="source references do not match"):
        await engine.execute(
            input="Linux", session_id="existing", resume=True, source_references=(uuid4(),)
        )
    with pytest.raises(ConfigurationError, match="finished assessment"):
        await engine.execute(
            input="Linux", session_id="existing", resume=True, response=InteractionResponse()
        )
    resumed = await engine.execute(
        input="Linux", session_id="existing", resume=True, source_references=(SOURCE,)
    )
    assert resumed == result


class BrokenPersistence(InMemoryPersistence):
    async def load(self, scope):
        raise RuntimeError("private database detail")


async def test_unexpected_persistence_failure_is_wrapped_and_claim_released():
    engine = SufficiencyEngine(model_call=fake_model([proposal()]), persistence=BrokenPersistence())
    with pytest.raises(PersistenceError, match="persistence operation failed") as raised:
        await engine.execute(input="Deploy", session_id="broken")
    assert "private" not in str(raised.value)
    assert isinstance(raised.value.__cause__, RuntimeError)
    claim = await engine.persistence.acquire(engine._scope("broken"), uuid4(), 60)
    assert claim.fence == 2


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda state: state.update(schema_version=999), "unsupported schema"),
        (lambda state: state["scope"].update(session_id="other"), "scope does not match"),
    ],
)
async def test_deleting_a_corrupted_session_fails_without_removing_it(mutate, message):
    engine = SufficiencyEngine(
        model_call=fake_model([proposal(status="available", evidence_quote="Linux")])
    )
    await engine.execute(input="Linux", session_id="corrupt")
    await edit_stored_state(engine, "corrupt", mutate)
    with pytest.raises(SerializationError, match=message):
        await engine.delete_session("corrupt")
    assert await engine.persistence.load(engine._scope("corrupt")) is not None


async def test_deleting_an_unknown_session_is_a_no_op():
    engine = SufficiencyEngine(model_call=fake_model([]))
    await engine.delete_session("unknown")
    assert await engine.persistence.load(engine._scope("unknown")) is None


async def test_finished_session_without_result_is_rejected_on_resume():
    engine = SufficiencyEngine(
        model_call=fake_model([proposal(status="available", evidence_quote="Linux")])
    )
    await engine.execute(input="Linux", session_id="no-result")
    await edit_stored_state(engine, "no-result", lambda state: state.update(result=None))
    with pytest.raises(SerializationError, match="no result"):
        await engine.execute(input="Linux", session_id="no-result", resume=True)


async def test_pending_terminal_audit_without_status_is_rejected_on_resume():
    engine = SufficiencyEngine(
        model_call=fake_model([proposal(status="available", evidence_quote="Linux")]),
        audit=AGXAIAudit(archive=FlakyArchive()),
    )
    failed = await engine.execute(input="Linux", session_id="no-status")
    assert failed.errors[-1].code == "provenance_error"
    await edit_stored_state(engine, "no-status", lambda state: state.update(terminal_status=None))
    with pytest.raises(SerializationError, match="no terminal status"):
        await engine.execute(input="Linux", session_id="no-status", resume=True)


async def test_stored_requirement_without_discovery_contract_fails_reassessment():
    item = proposal()
    engine = SufficiencyEngine(model_call=fake_model([item]), interrupt_call=failing_interrupt)
    waiting = await engine.execute(input="Deploy", session_id="contract")
    await edit_stored_state(engine, "contract", lambda state: state.update(proposals=[]))
    result = await engine.execute(
        input="Deploy",
        session_id="contract",
        resume=True,
        response=submission(waiting, "Linux"),
    )
    assert result.status is AssessmentStatus.FAILED
    assert result.errors[-1].code == "serialization_error"
    assert "discovery contract" in result.errors[-1].message


async def test_question_for_unknown_stored_requirement_is_rejected():
    shared = "Which platform and region?"
    platform = proposal(question=shared)
    region = proposal(key="region", description="Deployment region", question=shared)
    engine = SufficiencyEngine(
        model_call=fake_model([platform, region]), interrupt_call=failing_interrupt
    )
    waiting = await engine.execute(input="Deploy", session_id="dangling")
    assert len(waiting.questions[0].requirement_ids) == 2

    def drop_region(state):
        state["requirements"] = [item for item in state["requirements"] if item["key"] != "region"]

    await edit_stored_state(engine, "dangling", drop_region)
    result = await engine.execute(
        input="Deploy",
        session_id="dangling",
        resume=True,
        response=submission(waiting, "Linux"),
    )
    assert result.status is AssessmentStatus.FAILED
    assert result.errors[-1].code == "clarification_error"
    assert not result.answers


@pytest.mark.parametrize("corrected", [False, True])
async def test_answer_conflicting_with_a_prior_valid_answer_requires_correction(corrected):
    item = proposal()
    engine = SufficiencyEngine(
        model_call=fake_model([item], [available(item, "Linux") if corrected else item]),
        interrupt_call=failing_interrupt,
        max_iterations=1,
    )
    waiting = await engine.execute(input="Deploy", session_id="prior")
    question = waiting.questions[0]
    requirement_id = question.requirement_ids[0]
    prior = Answer(
        question_id=question.id,
        requirement_id=requirement_id,
        value="Windows",
        status=AnswerStatus.VALID,
    )
    await edit_stored_state(
        engine, "prior", lambda state: state["answers"].append(prior.model_dump(mode="json"))
    )
    response = InteractionResponse(
        answers=(
            AnswerSubmission(
                question_id=question.id,
                values={requirement_id: "Linux"},
                corrections=(requirement_id,) if corrected else (),
            ),
        )
    )
    result = await engine.execute(
        input="Deploy", session_id="prior", resume=True, response=response
    )
    if corrected:
        assert result.sufficient
        assert [answer.status for answer in result.answers] == [
            AnswerStatus.CONTRADICTORY,
            AnswerStatus.VALID,
        ]
    else:
        assert result.status is AssessmentStatus.ITERATION_LIMIT_REACHED
        assert result.answers[-1].status is AnswerStatus.CONTRADICTORY
        assert result.answers[-1].reason == "Answer conflicts with a prior answer."
        assert result.questions[0].status is QuestionStatus.INVALID


def supersede(parent, successor):
    return {"operation": "supersede", "parent_keys": [parent], "successor_keys": [successor]}


@pytest.mark.parametrize(
    ("responses", "options", "code", "message"),
    [
        (
            [[proposal(status="available", evidence_quote="  ")]],
            {},
            "model_response_error",
            "empty evidence quote",
        ),
        (
            [[proposal()], [proposal(status="available", evidence_quote="Windows")]],
            {},
            "model_response_error",
            "not supplied",
        ),
        (
            [[proposal()], [proposal(classification="optional")]],
            {},
            "model_response_error",
            "changed classification",
        ),
        (
            [[proposal(dependencies=["missing"])]],
            {},
            "model_response_error",
            "unknown dependency",
        ),
        (
            [
                [proposal(), proposal(key="region", description="Region")],
                {
                    "requirements": [proposal(), proposal(key="region", description="Region")],
                    "lineage": [supersede("platform", "region")],
                },
            ],
            {},
            "model_response_error",
            "ambiguous or unknown requirement lineage",
        ),
        (
            [
                [proposal()],
                {
                    "requirements": [proposal(key="runtime")],
                    "lineage": [supersede("platform", "runtime")],
                },
                {"requirements": [proposal(key="os")], "lineage": [supersede("platform", "os")]},
            ],
            {},
            "model_response_error",
            "lineage parent is inactive",
        ),
        (
            [
                [
                    proposal(dependencies=["region"]),
                    proposal(key="region", dependencies=["platform"]),
                ]
            ],
            {},
            "invalid_dependencies",
            "dependency cycle",
        ),
        (
            [[proposal(), proposal(key="region", question="Which region?")]],
            {"limits": Limits(max_questions=1)},
            "clarification_error",
            "pending question limit",
        ),
    ],
)
async def test_unsafe_discovery_or_reassessment_fails_closed(responses, options, code, message):
    result = await SufficiencyEngine(
        model_call=fake_model(*responses), interrupt_call=answer_all("Linux"), **options
    ).execute(input="Deploy the service")
    assert result.status is AssessmentStatus.FAILED
    assert not result.sufficient
    assert result.errors[-1].code == code
    assert message in result.errors[-1].message
    assert result.provenance is not None


async def test_superseded_dependency_is_replaced_by_its_successor():
    service = proposal(
        key="service",
        description="Service to deploy",
        status="available",
        evidence_quote="service",
        necessity="not_needed",
        dependencies=["platform"],
    )
    platform = proposal()
    runtime = proposal(key="runtime", description="Runtime operating system")
    result = await SufficiencyEngine(
        model_call=fake_model(
            [service, platform],
            {
                "requirements": [service, available(runtime, "Linux")],
                "lineage": [supersede("platform", "runtime")],
            },
        ),
        interrupt_call=answer_all("Linux"),
    ).execute(input="Deploy the service")
    assert result.sufficient
    by_key = {item.key: item for item in result.requirements}
    assert by_key["platform"].lifecycle.value == "superseded"
    assert by_key["service"].dependencies == (by_key["runtime"].id,)


async def test_rejected_assumption_is_not_offered_again():
    item = proposal(
        necessity="may_assume",
        answer_type="integer",
        question=None,
        assumption={"description": "One replica", "value": 1, "risk": "low", "reversible": True},
    )
    calls = 0

    async def reject(payload):
        nonlocal calls
        calls += 1
        return InteractionResponse(assumption_approvals={payload.assumptions[0].id: False})

    result = await SufficiencyEngine(
        model_call=fake_model([item], [item]), interrupt_call=reject, allow_assumptions=True
    ).execute(input="Deploy the service")
    assert result.status is AssessmentStatus.INSUFFICIENT
    assert result.assumptions[0].status is AssumptionStatus.REJECTED
    assert result.blocking_requirements[0].status.value == "unresolved"
    assert calls == 1


def unknown_question(payload):
    return InteractionResponse(answers=(AnswerSubmission(question_id=uuid4()),))


def duplicate_question(payload):
    answer = AnswerSubmission(question_id=payload.questions[0].id)
    return InteractionResponse(answers=(answer, answer))


def unknown_assumption(payload):
    return InteractionResponse(assumption_approvals={uuid4(): True})


def foreign_slot(payload):
    return InteractionResponse(
        answers=(AnswerSubmission(question_id=payload.questions[0].id, values={uuid4(): "x"}),)
    )


def provided_and_declined(payload):
    question = payload.questions[0]
    requirement_id = question.requirement_ids[0]
    return InteractionResponse(
        answers=(
            AnswerSubmission(
                question_id=question.id,
                values={requirement_id: "Linux"},
                declined=(requirement_id,),
            ),
        )
    )


@pytest.mark.parametrize(
    "respond",
    [unknown_question, duplicate_question, unknown_assumption, foreign_slot, provided_and_declined],
)
async def test_inconsistent_responses_are_rejected_without_accepting_answers(respond):
    result = await SufficiencyEngine(
        model_call=fake_model([proposal()]), interrupt_call=respond
    ).execute(input="Deploy")
    assert result.status is AssessmentStatus.FAILED
    assert result.errors[-1].code == "clarification_error"
    assert result.iteration_count == 1
    assert not result.answers
    assert result.requirements[0].status.value == "unresolved"


async def test_ambiguous_answer_gets_a_followup_question():
    item = proposal()
    payloads = []

    async def interrupt(payload):
        payloads.append(payload)
        question = payload.questions[0]
        if len(payloads) == 1:
            return InteractionResponse(
                answers=(
                    AnswerSubmission(question_id=question.id, ambiguous=question.requirement_ids),
                )
            )
        return submission(payload, "Linux")

    result = await SufficiencyEngine(
        model_call=fake_model([item], [item], [available(item, "Linux")]),
        interrupt_call=interrupt,
    ).execute(input="Deploy the service")
    assert result.sufficient
    assert [answer.status for answer in result.answers] == [
        AnswerStatus.AMBIGUOUS,
        AnswerStatus.VALID,
    ]
    assert result.answers[0].reason == "Answer is ambiguous."
    assert result.questions[0].status is QuestionStatus.INVALID
    assert payloads[1].questions[0].follow_up_to == payloads[0].questions[0].id
