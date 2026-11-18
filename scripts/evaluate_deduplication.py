"""Evaluate conservative duplicate handling on labeled fixtures, offline by default."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Literal, TypedDict
from uuid import uuid4

from _factories import load_callable
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from sufficiency_engine import (
    AnswerConstraints,
    AnswerType,
    ClarificationQuestion,
    EmbeddingModelABC,
)
from sufficiency_engine._clarification import _lexical_candidate, deduplicate_questions


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    split: Literal["calibration", "validation"]
    left: str
    right: str
    equivalent: bool
    expected_retained: int = Field(ge=1, le=2)
    same_requirement: bool = True
    follow_up: bool = False
    right_slot: str = "value"
    right_type: AnswerType = AnswerType.STRING
    right_constraints: AnswerConstraints = Field(default_factory=AnswerConstraints)


class Outcome(TypedDict):
    id: str
    equivalent: bool
    retained: int
    passed: bool
    warnings: list[str]


def metrics(pairs: list[tuple[bool, bool]]) -> dict[str, int | float | None]:
    tp = sum(expected and actual for expected, actual in pairs)
    fp = sum(not expected and actual for expected, actual in pairs)
    fn = sum(expected and not actual for expected, actual in pairs)
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


async def evaluate(path: Path, embedding: EmbeddingModelABC | None) -> dict[str, object]:
    cases = TypeAdapter(list[Case]).validate_json(path.read_text(encoding="utf-8"))
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("fixtures need nonempty, unique case IDs")
    results: list[Outcome] = []
    lexical: dict[str, list[tuple[bool, bool]]] = {"calibration": [], "validation": []}
    pipeline: dict[str, list[tuple[bool, bool]]] = {"calibration": [], "validation": []}
    for case in cases:
        left = ClarificationQuestion(
            requirement_ids=(uuid4(),),
            text=case.left,
            reason="Fixture",
            expected_type=AnswerType.STRING,
        )
        right = ClarificationQuestion(
            requirement_ids=left.requirement_ids if case.same_requirement else (uuid4(),),
            text=case.right,
            reason="Fixture",
            expected_type=case.right_type,
            constraints=case.right_constraints,
            answer_slot=case.right_slot,
            follow_up_to=left.id if case.follow_up else None,
        )
        kept, warnings = await deduplicate_questions([left, right], embedding)
        detected = len(kept) == 1
        lexical[case.split].append((case.equivalent, detected or _lexical_candidate(left, right)))
        pipeline[case.split].append(
            (
                case.equivalent,
                detected or any(warning.code == "potential_duplicate" for warning in warnings),
            )
        )
        results.append(
            {
                "id": case.id,
                "equivalent": case.equivalent,
                "retained": len(kept),
                "passed": len(kept) == case.expected_retained,
                "warnings": [warning.code for warning in warnings],
            }
        )
    if any(not pairs for pairs in lexical.values()):
        raise ValueError("both calibration and validation fixtures are required")
    return {
        "ok": all(item["passed"] for item in results)
        and not any("embedding_unavailable" in item["warnings"] for item in results),
        "embedding_enabled": embedding is not None,
        "lexical_candidate_stage": {split: metrics(pairs) for split, pairs in lexical.items()},
        "actual_pipeline": {split: metrics(pairs) for split, pairs in pipeline.items()},
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "deduplication.json"),
    )
    parser.add_argument(
        "--embedding-factory", help="Explicit trusted MODULE:FACTORY returning an EmbeddingModelABC"
    )
    parser.add_argument("--path", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        embedding = None
        if args.embedding_factory:
            candidate = load_callable(args.embedding_factory, args.path)()
            if not isinstance(candidate, EmbeddingModelABC):
                raise TypeError("factory must return EmbeddingModelABC")
            embedding = candidate
        report = asyncio.run(evaluate(args.fixtures, embedding))
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
