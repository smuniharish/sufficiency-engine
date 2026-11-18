import asyncio
import json
from uuid import uuid4, uuid5

import pytest
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
from sufficiency_engine.models import AnswerStatus, AssumptionStatus, QuestionStatus
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
