"""Conservative question deduplication and declarative answer validation."""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Sequence
from uuid import UUID, uuid5

from pydantic import JsonValue
from rapidfuzz.fuzz import ratio

from .embedding import EmbeddingModelABC
from .models import AnswerConstraints, AnswerType, ClarificationQuestion, Diagnostic


def validate_answer(
    value: JsonValue,
    expected_type: AnswerType,
    constraints: AnswerConstraints,
    max_bytes: int,
) -> str | None:
    """Return a safe validation reason, or ``None`` for an acceptable value."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        return "answer is not finite JSON"
    if len(encoded) > max_bytes:
        return "answer exceeds the configured size limit"
    if value is None:
        return None if constraints.nullable else "null is not allowed"
    types = {
        AnswerType.STRING: str,
        AnswerType.INTEGER: int,
        AnswerType.NUMBER: (int, float),
        AnswerType.BOOLEAN: bool,
        AnswerType.ARRAY: list,
        AnswerType.OBJECT: dict,
    }
    if expected_type is not AnswerType.ANY:
        expected = types[expected_type]
        if not isinstance(value, expected) or (
            expected_type in (AnswerType.INTEGER, AnswerType.NUMBER) and isinstance(value, bool)
        ):
            return "answer has the wrong type"
    if constraints.min_length is not None or constraints.max_length is not None:
        if not isinstance(value, (str, list, dict)):
            return "length constraints do not apply to this answer"
        if constraints.min_length is not None and len(value) < constraints.min_length:
            return "answer is shorter than the minimum"
        if constraints.max_length is not None and len(value) > constraints.max_length:
            return "answer is longer than the maximum"
    if constraints.minimum is not None or constraints.maximum is not None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "numeric constraints do not apply to this answer"
        if constraints.minimum is not None and value < constraints.minimum:
            return "answer is below the minimum"
        if constraints.maximum is not None and value > constraints.maximum:
            return "answer is above the maximum"
    if constraints.choices is not None:
        serialized_choices = {
            json.dumps(choice, ensure_ascii=False, sort_keys=True, allow_nan=False)
            for choice in constraints.choices
        }
        if json.dumps(value, ensure_ascii=False, sort_keys=True) not in serialized_choices:
            return "answer is not one of the allowed values"
    return None


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold()).removesuffix("?").rstrip()


def _same_slot(left: ClarificationQuestion, right: ClarificationQuestion) -> bool:
    return (
        set(left.requirement_ids) == set(right.requirement_ids)
        and left.answer_slot == right.answer_slot
        and left.expected_type is right.expected_type
        and left.constraints == right.constraints
        and left.required == right.required
        and left.follow_up_to is None
        and right.follow_up_to is None
    )


def _lexical_candidate(left: ClarificationQuestion, right: ClarificationQuestion) -> bool:
    return (
        _same_slot(left, right)
        and 90 <= ratio(_normalized(left.text), _normalized(right.text)) < 100
    )


def combine_related_questions(
    questions: Sequence[ClarificationQuestion], assessment_id: UUID
) -> tuple[ClarificationQuestion, ...]:
    """Combine explicitly identical, compatible initial questions into separate answer slots."""
    combined: list[ClarificationQuestion] = []
    for question in questions:
        for index, existing in enumerate(combined):
            if (
                question.follow_up_to is None
                and existing.follow_up_to is None
                and question.text == existing.text
                and question.reason == existing.reason
                and question.answer_slot == existing.answer_slot
                and question.expected_type is existing.expected_type
                and question.constraints == existing.constraints
                and question.required == existing.required
                and not set(question.requirement_ids) & set(existing.requirement_ids)
            ):
                ids = (*existing.requirement_ids, *question.requirement_ids)
                stable_ids = ":".join(sorted(str(item) for item in ids))
                combined[index] = existing.model_copy(
                    update={
                        "id": uuid5(
                            assessment_id, f"question-group:{existing.answer_slot}:{stable_ids}"
                        ),
                        "requirement_ids": ids,
                    }
                )
                break
        else:
            combined.append(question)
    return tuple(combined)


def _vectors_are_valid(vectors: list[list[float]], count: int) -> bool:
    if len(vectors) != count or not vectors:
        return False
    dimensions = len(vectors[0])
    if not 0 < dimensions <= 16_384 or any(len(vector) != dimensions for vector in vectors):
        return False
    for vector in vectors:
        if any(isinstance(value, bool) or not isinstance(value, (float, int)) for value in vector):
            return False
        if not all(math.isfinite(value) for value in vector):
            return False
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            return False
    return True


async def deduplicate_questions(
    questions: Sequence[ClarificationQuestion],
    embedding_model: EmbeddingModelABC | None = None,
    *,
    timeout: float = 120.0,
) -> tuple[tuple[ClarificationQuestion, ...], tuple[Diagnostic, ...]]:
    """Drop only demonstrably identical answer slots; preserve distinct follow-ups.

    Lexical and optional vector similarity identify candidates, but similarity
    alone never proves that two questions have the same meaning.
    """
    warnings: list[Diagnostic] = []
    if embedding_model is not None and questions:
        try:
            async with asyncio.timeout(timeout):
                vectors = await embedding_model.embed([question.text for question in questions])
            if not _vectors_are_valid(vectors, len(questions)):
                raise ValueError("invalid embedding vectors")
            norms = [math.hypot(*vector) for vector in vectors]
            potential_duplicate = False
            for index, vector in enumerate(vectors):
                for other_index, other in enumerate(vectors[:index]):
                    similarity = sum(
                        (a / norms[index]) * (b / norms[other_index])
                        for a, b in zip(vector, other, strict=True)
                    )
                    if (
                        not math.isfinite(similarity)
                        or not -1.000000001 <= similarity <= 1.000000001
                    ):
                        raise ValueError("invalid cosine similarity")
                    if similarity >= 0.98 and _lexical_candidate(
                        questions[index], questions[other_index]
                    ):
                        potential_duplicate = True
            if potential_duplicate:
                warnings.append(
                    Diagnostic(
                        code="potential_duplicate",
                        message="Similar questions were retained because equivalence is uncertain.",
                    )
                )
        except Exception:
            warnings.append(
                Diagnostic(
                    code="embedding_unavailable",
                    message=(
                        "Embedding deduplication failed; conservative lexical matching was used."
                    ),
                )
            )
    kept: list[ClarificationQuestion] = []
    seen_ids = set()
    for question in questions:
        if question.id in seen_ids:
            continue
        seen_ids.add(question.id)
        text = _normalized(question.text)
        duplicate = False
        for existing in kept:
            if _same_slot(question, existing) and ratio(text, _normalized(existing.text)) == 100:
                duplicate = True
                break
        if not duplicate:
            kept.append(question)
    return tuple(kept), tuple(warnings)
