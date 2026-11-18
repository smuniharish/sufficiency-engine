import asyncio
import json
import string
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sufficiency_engine._clarification import (
    combine_related_questions,
    deduplicate_questions,
    validate_answer,
)
from sufficiency_engine._discovery import discover, normalize_response
from sufficiency_engine.config import EngineConfig, Limits
from sufficiency_engine.embedding import EmbeddingModelABC
from sufficiency_engine.exceptions import (
    ModelInvocationError,
    ModelResponseError,
    TransientModelError,
)
from sufficiency_engine.models import AnswerConstraints, AnswerType, ClarificationQuestion


def proposal(**updates):
    return {
        "key": "platform",
        "description": "Deployment platform",
        "classification": "mandatory",
        "status": "unresolved",
        "necessity": "must_ask",
        "reason": "The platform determines deployment.",
        "question": "Which platform?",
        **updates,
    }


def question(text="Which platform?", **updates):
    return ClarificationQuestion(
        requirement_ids=updates.pop("requirement_ids", (uuid4(),)),
        text=text,
        reason="Needed",
        **updates,
    )


@pytest.mark.parametrize(
    ("value", "answer_type", "constraints"),
    [
        (0, AnswerType.INTEGER, AnswerConstraints()),
        ("none", AnswerType.STRING, AnswerConstraints()),
        ("no", AnswerType.STRING, AnswerConstraints()),
        ([], AnswerType.ARRAY, AnswerConstraints()),
        (False, AnswerType.BOOLEAN, AnswerConstraints()),
        (None, AnswerType.ANY, AnswerConstraints(nullable=True)),
    ],
)
def test_falsey_answers_are_not_generically_rejected(value, answer_type, constraints):
    assert validate_answer(value, answer_type, constraints, 100) is None


@pytest.mark.parametrize(
    ("value", "answer_type", "constraints"),
    [
        (False, AnswerType.INTEGER, AnswerConstraints()),
        (None, AnswerType.ANY, AnswerConstraints()),
        ("", AnswerType.STRING, AnswerConstraints(min_length=1)),
        (4, AnswerType.INTEGER, AnswerConstraints(minimum=5)),
        (6, AnswerType.INTEGER, AnswerConstraints(maximum=5)),
        ("yes", AnswerType.STRING, AnswerConstraints(choices=("no",))),
        (True, AnswerType.ANY, AnswerConstraints(choices=(1,))),
    ],
)
def test_invalid_answers_are_rejected_by_their_specific_constraints(
    value, answer_type, constraints
):
    assert validate_answer(value, answer_type, constraints, 100) is not None


def test_answer_size_is_measured_as_utf8_json_bytes():
    assert validate_answer("é", AnswerType.STRING, AnswerConstraints(), 4) is None
    assert validate_answer("é", AnswerType.STRING, AnswerConstraints(), 3) is not None


def test_response_normalization_and_untrusted_schema():
    response = {"requirements": [proposal()]}
    assert (
        normalize_response(json.dumps(response), EngineConfig()).requirements[0].key == "platform"
    )

    class Message:
        content = json.dumps(response)

    assert normalize_response(Message(), EngineConfig()).requirements
    for invalid in (
        "not json",
        {"requirements": [proposal(status="available")]},
        {"requirements": [proposal(), proposal()]},
        {"requirements": [proposal(necessity="must_ask", question=None)]},
        {"requirements": [proposal(blocking=False)]},
        [],
    ):
        with pytest.raises(ModelResponseError):
            normalize_response(invalid, EngineConfig())


async def test_transient_model_retry_is_bounded_and_validation_is_not_retried():
    calls = 0

    async def transient(_messages):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TransientModelError("temporary")
        return {"requirements": [proposal()]}

    result = await discover(transient, "task", [], EngineConfig(max_model_retries=2))
    assert len(result.requirements) == 1
    assert calls == 3

    calls = 0

    async def invalid(_messages):
        nonlocal calls
        calls += 1
        return "bad JSON"

    with pytest.raises(ModelResponseError):
        await discover(invalid, "task", [], EngineConfig(max_model_retries=2))
    assert calls == 1


async def test_permanent_failure_does_not_retry_and_callback_timeout_is_bounded():
    calls = 0

    def fail(_messages):
        nonlocal calls
        calls += 1
        raise ValueError("private callback details")

    with pytest.raises(ModelInvocationError, match="model callback failed"):
        await discover(fail, "task", [], EngineConfig())
    assert calls == 1

    async def slow(_messages):
        await asyncio.sleep(1)

    config = EngineConfig(max_model_retries=0, limits=Limits(callback_timeout_seconds=0.01))
    with pytest.raises(ModelInvocationError, match="retries exhausted"):
        await discover(slow, "task", [], config)


async def test_deduplication_preserves_followups_and_distinct_slots():
    original = question()
    exact = question("  which   platform  ", requirement_ids=original.requirement_ids)
    followup = question(requirement_ids=original.requirement_ids, follow_up_to=original.id)
    different_slot = question(requirement_ids=original.requirement_ids, answer_slot="region")
    negated = question("Which platform is not allowed?", requirement_ids=original.requirement_ids)
    kept, warnings = await deduplicate_questions(
        [original, exact, followup, different_slot, negated]
    )
    assert [item.id for item in kept] == [
        original.id,
        followup.id,
        different_slot.id,
        negated.id,
    ]
    assert not warnings


def test_grouping_requires_identical_compatible_questions_and_stable_members():
    first = question("Which platform and region?", expected_type=AnswerType.STRING)
    second = question("Which platform and region?", expected_type=AnswerType.STRING)
    different_type = question("Which platform and region?", expected_type=AnswerType.INTEGER)
    followup = question(
        "Which platform and region?", expected_type=AnswerType.STRING, follow_up_to=first.id
    )
    assessment_id = uuid4()
    grouped = combine_related_questions([first, second, different_type, followup], assessment_id)
    assert len(grouped) == 3
    assert grouped[0].requirement_ids == (*first.requirement_ids, *second.requirement_ids)
    assert grouped[1:] == (different_type, followup)
    reversed_group = combine_related_questions([second, first], assessment_id)
    assert grouped[0].id == reversed_group[0].id


class BadEmbedding(EmbeddingModelABC):
    async def embed(self, texts):
        return [[float("nan")] for _ in texts]


async def test_embedding_failure_preserves_questions_and_warns():
    first = question()
    second = question("Which platform is prohibited?", requirement_ids=first.requirement_ids)
    kept, warnings = await deduplicate_questions([first, second], BadEmbedding())
    assert kept == (first, second)
    assert warnings[0].code == "embedding_unavailable"


class SimilarEmbedding(EmbeddingModelABC):
    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


async def test_semantic_candidate_is_reported_without_suppressing_a_distinct_question():
    first = question("Which platform should be used?")
    second = question("Which platform should be used now?", requirement_ids=first.requirement_ids)
    kept, warnings = await deduplicate_questions([first, second], SimilarEmbedding())
    assert kept == (first, second)
    assert warnings[0].code == "potential_duplicate"


@given(st.text(alphabet=string.ascii_letters + " ", min_size=1, max_size=50))
def test_followup_with_identical_text_is_never_deduplicated(text):
    first = question(text)
    followup = question(text, requirement_ids=first.requirement_ids, follow_up_to=first.id)
    kept, _warnings = asyncio.run(deduplicate_questions([first, followup]))
    assert kept == (first, followup)
