"""Measure local engine overhead with a deterministic model and in-memory AGXAI.

The numbers describe this process on this machine only. They exclude model,
network, storage, and exporter latency, which usually dominate in production.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import statistics
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from uuid import uuid4

from sufficiency_engine import ClarificationQuestion, EmbeddingModelABC, SufficiencyEngine
from sufficiency_engine._clarification import deduplicate_questions
from sufficiency_engine.models import Requirement, RequirementClassification, RequirementStatus
from sufficiency_engine.policy import apply_blocking_policy


class SyntheticEmbedding(EmbeddingModelABC):
    """Orthogonal 1,024-dimensional vectors, so no question is a duplicate."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [1.0 if position == index % 1024 else 0.0 for position in range(1024)]
            for index in range(len(texts))
        ]


async def model_call(_messages: list[dict[str, str]]) -> dict[str, object]:
    return {
        "requirements": [
            {
                "key": "platform",
                "description": "Deployment platform",
                "classification": "mandatory",
                "status": "available",
                "evidence_quote": "Linux",
                "necessity": "not_needed",
                "reason": "Specified in the task.",
            }
        ]
    }


async def measure(runs: int, operation: Callable[[], Awaitable[None]]) -> dict[str, float]:
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        await operation()
        samples.append(time.perf_counter() - started)
    samples.sort()
    return {
        "samples": runs,
        "p50_ms": round(statistics.median(samples) * 1000, 3),
        "p95_ms": round(samples[math.ceil(0.95 * runs) - 1] * 1000, 3),
    }


async def benchmark(runs: int) -> dict[str, object]:
    tracemalloc.start()
    engine = SufficiencyEngine(model_call=model_call)

    async def assessment() -> None:
        assert (await engine.execute(input="Deploy on Linux")).sufficient

    await assessment()

    evidence = uuid4()
    requirements: list[Requirement] = []
    for index in range(256):
        requirements.append(
            Requirement(
                key=f"r{index}",
                description=f"Requirement {index}",
                classification=RequirementClassification.MANDATORY,
                status=RequirementStatus.AVAILABLE,
                source_evidence_ids=(evidence,),
                dependencies=tuple(item.id for item in requirements[-8:]),
            )
        )

    async def policy() -> None:
        assert not any(item.blocking for item in apply_blocking_policy(requirements))

    requirement_id = uuid4()
    questions = [
        ClarificationQuestion(
            requirement_ids=(requirement_id,),
            text=f"Which deployment target number {index} should be used?",
            reason="Target",
        )
        for index in range(64)
    ]
    embedding = SyntheticEmbedding()

    async def lexical() -> None:
        kept, _ = await deduplicate_questions(questions)
        assert len(kept) == len(questions)

    async def vectors() -> None:
        kept, _ = await deduplicate_questions(questions, embedding)
        assert len(kept) == len(questions)

    report: dict[str, object] = {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "audited_assessment": await measure(runs, assessment),
        "policy_256_requirements": {
            "edges": sum(len(item.dependencies) for item in requirements),
            **await measure(runs, policy),
        },
        "lexical_64_questions": await measure(max(runs // 4, 1), lexical),
        "vectors_64x1024": await measure(max(runs // 4, 1), vectors),
    }
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report["python_allocation_peak_mib"] = round(peak / 1024**2, 2)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=40, help="timed runs per scenario")
    arguments = parser.parse_args()
    if arguments.runs < 1:
        parser.error("--runs must be positive")
    print(json.dumps(asyncio.run(benchmark(arguments.runs)), indent=2))


if __name__ == "__main__":
    main()
