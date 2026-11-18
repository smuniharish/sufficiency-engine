"""Evaluate labeled readiness cases against a live OpenAI-compatible model.

Configure ``SUFFICIENCY_TEST_LLM_API_KEY``, ``SUFFICIENCY_TEST_LLM_MODEL`` and, for a
non-OpenAI endpoint, ``SUFFICIENCY_TEST_LLM_BASE_URL`` (or the ``OPENAI_*`` names),
then run::

    uv sync --group live
    uv run --no-sync python scripts/run_live_evaluation.py --repeats 3

Fixture inputs are sent to the configured provider. Reports are written to the
git-ignored ``reports/live-evaluation/`` directory and contain model output only,
never credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from _live import live_model_call, live_settings, scripted_answerer
from pydantic import BaseModel, ConfigDict, TypeAdapter

from sufficiency_engine import SufficiencyEngine

ROOT = Path(__file__).resolve().parents[1]


class LiveCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    input: str
    expected_sufficient: bool
    answer: str | None = None
    expected_sufficient_after_answer: bool | None = None


class Run(TypedDict):
    id: str
    repeat: int
    passed: bool
    status: str
    sufficient: bool
    questions_asked: int
    rounds: int
    requirements: int
    blocking: list[str]
    audited_decisions: int
    errors: list[str]
    seconds: float


async def run_case(case: LiveCase, repeat: int, model_call: Callable[..., object]) -> Run:
    asked: list[str] = []
    engine = SufficiencyEngine(
        model_call=model_call,
        interrupt_call=scripted_answerer(case.answer, asked) if case.answer else None,
    )
    started = time.perf_counter()
    result = await engine.execute(input=case.input)
    seconds = time.perf_counter() - started
    if case.answer is None:
        passed = result.sufficient == case.expected_sufficient
    else:
        # The initial assessment must ask; the reassessment must reach the expected state.
        passed = (bool(asked) == (not case.expected_sufficient)) and (
            result.sufficient == case.expected_sufficient_after_answer
        )
    decisions = len(result.provenance.decision_ids) if result.provenance else 0
    passed = passed and result.status.value != "failed" and decisions > 0
    return {
        "id": case.id,
        "repeat": repeat,
        "passed": passed,
        "status": result.status.value,
        "sufficient": result.sufficient,
        "questions_asked": len(asked),
        "rounds": result.iteration_count,
        "requirements": len(result.requirements),
        "blocking": [item.key for item in result.requirements if item.blocking],
        "audited_decisions": decisions,
        "errors": [error.code for error in result.errors],
        "seconds": round(seconds, 2),
    }


def summarize(runs: list[Run], model: str) -> dict[str, object]:
    by_case: dict[str, list[Run]] = {}
    for run in runs:
        by_case.setdefault(run["id"], []).append(run)
    seconds = [run["seconds"] for run in runs]
    return {
        "model": model,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "runs": len(runs),
        "passed": sum(run["passed"] for run in runs),
        "execution_failures": sum(run["status"] == "failed" for run in runs),
        "median_seconds": round(statistics.median(seconds), 2),
        "max_seconds": max(seconds),
        "cases": {
            case: {"passed": sum(run["passed"] for run in items), "runs": len(items)}
            for case, items in by_case.items()
        },
        "details": runs,
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        f"# Live readiness evaluation: {report['model']}",
        "",
        f"Generated {report['generated_at']}; {report['passed']}/{report['runs']} runs passed; "
        f"median {report['median_seconds']} s, max {report['max_seconds']} s.",
        "",
        "| Case | Repeat | Passed | Status | Questions | Rounds | Blocking | Seconds |",
        "| --- | ---: | :---: | --- | ---: | ---: | --- | ---: |",
    ]
    for run in cast(list[Run], report["details"]):
        lines.append(
            f"| {run['id']} | {run['repeat']} | {'yes' if run['passed'] else 'no'} | "
            f"{run['status']} | {run['questions_asked']} | {run['rounds']} | "
            f"{', '.join(run['blocking']) or '-'} | {run['seconds']} |"
        )
    return "\n".join(lines) + "\n"


async def evaluate(path: Path, repeats: int, concurrency: int) -> dict[str, object]:
    settings = live_settings()
    if settings is None:
        raise SystemExit("Set SUFFICIENCY_TEST_LLM_API_KEY and SUFFICIENCY_TEST_LLM_MODEL.")
    cases = TypeAdapter(list[LiveCase]).validate_json(path.read_text(encoding="utf-8"))
    model_call = live_model_call(settings)
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded(case: LiveCase, repeat: int) -> Run:
        async with semaphore:
            return await run_case(case, repeat, model_call)

    runs = await asyncio.gather(
        *(bounded(case, repeat) for repeat in range(1, repeats + 1) for case in cases)
    )
    return summarize(sorted(runs, key=lambda run: (run["id"], run["repeat"])), settings.model)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fixtures", type=Path, default=ROOT / "tests" / "fixtures" / "live_readiness.json"
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "live-evaluation")
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.fixtures, args.repeats, args.concurrency))
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = str(report["generated_at"]).replace(":", "").replace("+0000", "Z")
    (args.output / f"{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.output / f"{stamp}.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 0 if report["passed"] == report["runs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
