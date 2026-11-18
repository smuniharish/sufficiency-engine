import json

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from sufficiency_engine import AGXAIAudit, AssessmentResult, SufficiencyEngine
from sufficiency_engine.exceptions import ConfigurationError
from sufficiency_engine.integrations.langgraph import build_assessment_graph
from sufficiency_engine.provenance import InMemorySemanticArchive


def proposal():
    return {
        "key": "platform",
        "description": "Deployment platform",
        "classification": "mandatory",
        "status": "unresolved",
        "necessity": "must_ask",
        "reason": "The platform affects the deployment.",
        "question": "Which platform?",
        "answer_type": "string",
    }


def model_with_calls(counts):
    model = GenericFakeChatModel(
        messages=iter(
            AIMessage(content=json.dumps({"requirements": [item]}))
            for item in (
                proposal(),
                {**proposal(), "status": "available", "evidence_quote": "Linux"},
            )
        )
    )

    async def call(prompt):
        counts.append(prompt)
        return await model.ainvoke(prompt)

    return call


def answer(payload):
    question = payload["questions"][0]
    return {
        "answers": [
            {"question_id": question["id"], "values": {question["requirement_ids"][0]: "Linux"}}
        ]
    }


async def test_interrupt_resume_uses_same_checkpoint_and_no_standalone_session():
    calls = []
    engine = SufficiencyEngine(model_call=model_with_calls(calls))
    graph = build_assessment_graph(engine, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "graph-thread"}}
    first = await graph.ainvoke({"task": "Deploy the service", "session_id": "graph"}, config)
    payload = first["__interrupt__"][0].value
    checkpoint = await graph.aget_state(config)
    assert checkpoint.values["assessment"]["pending_audit"] is None
    assert await engine.persistence.load(engine._scope("graph")) is None
    result = await graph.ainvoke(Command(resume=answer(payload)), config)
    readiness = AssessmentResult.model_validate(result["readiness"])
    assert readiness.sufficient
    assert readiness.iteration_count == 1
    assert readiness.questions[0].id.hex == payload["questions"][0]["id"].replace("-", "")
    assert len(calls) == 2


async def test_invalid_resume_reinterrupts_without_discarding_state():
    calls = []
    graph = build_assessment_graph(
        SufficiencyEngine(model_call=model_with_calls(calls)), checkpointer=InMemorySaver()
    )
    config = {"configurable": {"thread_id": "bad-answer"}}
    first = await graph.ainvoke({"task": "Deploy"}, config)
    payload = first["__interrupt__"][0].value
    bad = await graph.ainvoke(Command(resume={"answers": [{"question_id": "bad"}]}), config)
    again = bad["__interrupt__"][0].value
    assert again["questions"][0]["id"] == payload["questions"][0]["id"]
    finished = await graph.ainvoke(Command(resume=answer(again)), config)
    result = AssessmentResult.model_validate(finished["readiness"])
    assert result.sufficient
    assert any(warning.code == "clarification_error" for warning in result.warnings)
    assert len(calls) == 2


class FlakyArchive(InMemorySemanticArchive):
    def __init__(self):
        super().__init__()
        self.fail_once = True

    async def record(self, artifact):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("archive temporarily unavailable")
        await super().record(artifact)


async def test_checkpointed_audit_intent_can_be_replayed_without_rediscovery():
    calls = []
    engine = SufficiencyEngine(
        model_call=model_with_calls(calls), audit=AGXAIAudit(archive=FlakyArchive())
    )
    graph = build_assessment_graph(engine, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "audit-retry"}}
    failed = await graph.ainvoke({"task": "Deploy", "session_id": "retry"}, config)
    assert failed["readiness"]["status"] == "failed"
    assert failed["assessment"]["pending_audit"] is not None
    resumed = await graph.ainvoke(
        {"task": "Deploy", "session_id": "retry", "assessment": failed["assessment"]}, config
    )
    assert resumed["__interrupt__"]
    assert len(calls) == 1


async def test_repeated_malformed_resumes_exhaust_checkpointed_iteration_budget():
    calls = []
    graph = build_assessment_graph(
        SufficiencyEngine(model_call=model_with_calls(calls), max_iterations=2),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "bounded-invalid"}}
    initial = await graph.ainvoke({"task": "Deploy"}, config)
    question_id = initial["__interrupt__"][0].value["questions"][0]["id"]
    first = await graph.ainvoke(Command(resume={"answers": [{"question_id": "bad"}]}), config)
    assert first["__interrupt__"][0].value["questions"][0]["id"] == question_id
    second = await graph.ainvoke(Command(resume={"answers": [{"question_id": "bad"}]}), config)
    assert not second.get("__interrupt__")
    result = AssessmentResult.model_validate(second["readiness"])
    assert result.status.value == "iteration_limit_reached"
    assert result.iteration_count == 2
    assert result.blocking_requirements and result.provenance is not None
    assert len(result.warnings) == 2
    assert len(calls) == 1
    assert (await graph.aget_state(config)).values["assessment"]["pending_audit"] is None


async def test_graph_rejects_invalid_or_mismatched_entry_state():
    graph = build_assessment_graph(
        SufficiencyEngine(model_call=model_with_calls([])), checkpointer=InMemorySaver()
    )
    with pytest.raises(ConfigurationError, match="must be UUIDs"):
        await graph.ainvoke(
            {"task": "Deploy", "source_references": ["not-a-uuid"]},
            {"configurable": {"thread_id": "bad-reference"}},
        )
    with pytest.raises(ConfigurationError, match="assessment state is invalid"):
        await graph.ainvoke(
            {"task": "Deploy", "assessment": {"phase": "unknown"}},
            {"configurable": {"thread_id": "bad-assessment"}},
        )
    first = await graph.ainvoke(
        {"task": "Deploy", "session_id": "original"}, {"configurable": {"thread_id": "original"}}
    )
    with pytest.raises(ConfigurationError, match="does not match"):
        await graph.ainvoke(
            {"task": "Deploy elsewhere", "assessment": first["assessment"]},
            {"configurable": {"thread_id": "mismatch"}},
        )
    with pytest.raises(ConfigurationError, match="does not match"):
        await graph.ainvoke(
            {"task": "Deploy", "session_id": "other", "assessment": first["assessment"]},
            {"configurable": {"thread_id": "other-session"}},
        )


async def test_graph_discovery_failure_produces_a_failed_readiness_result():
    async def invalid_model(_messages):
        return "not discovery JSON"

    graph = build_assessment_graph(
        SufficiencyEngine(model_call=invalid_model), checkpointer=InMemorySaver()
    )
    result = await graph.ainvoke(
        {"task": "Deploy"}, {"configurable": {"thread_id": "invalid-model"}}
    )
    assert not result.get("__interrupt__")
    readiness = AssessmentResult.model_validate(result["readiness"])
    assert readiness.status.value == "failed"
    assert not readiness.sufficient
    assert readiness.errors[-1].code == "model_response_error"
    assert readiness.provenance is not None
