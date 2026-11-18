"""Run labeled readiness cases; an external model is used only with --callback."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from _factories import load_callable
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from sufficiency_engine import SufficiencyEngine


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    input: str
    expected_sufficient: bool
    response: dict[str, JsonValue]


class Outcome(TypedDict):
    id: str
    expected_sufficient: bool
    sufficient: bool
    status: str
    passed: bool
    errors: list[str]


async def evaluate(path: Path, callback: Callable[..., object] | None) -> dict[str, object]:
    cases = TypeAdapter(list[Case]).validate_json(path.read_text(encoding="utf-8"))
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("fixtures need nonempty, unique case IDs")
    results: list[Outcome] = []
    for case in cases:

        def fixture_callback(_messages: object, response: object = case.response) -> object:
            return response

        result = await SufficiencyEngine(
            model_call=callback if callback is not None else fixture_callback,
            max_model_retries=0,
        ).execute(input=case.input)
        results.append(
            {
                "id": case.id,
                "expected_sufficient": case.expected_sufficient,
                "sufficient": result.sufficient,
                "status": result.status.value,
                "passed": result.sufficient == case.expected_sufficient,
                "errors": [error.code for error in result.errors],
            }
        )
    return {
        "ok": all(item["passed"] for item in results)
        and (callback is None or all(item["status"] != "failed" for item in results)),
        "mode": "application_callback" if callback is not None else "offline_fixture",
        "false_ready": sum(
            not item["expected_sufficient"] and item["sufficient"] for item in results
        ),
        "false_not_ready": sum(
            item["expected_sufficient"] and not item["sufficient"] for item in results
        ),
        "execution_failures": sum(item["status"] == "failed" for item in results),
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "readiness.json"),
    )
    parser.add_argument(
        "--callback",
        help="Explicit trusted MODULE:CALLABLE; may transmit fixture inputs to its provider",
    )
    parser.add_argument("--path", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        callback = load_callable(args.callback, args.path) if args.callback else None
        report = asyncio.run(evaluate(args.fixtures, callback))
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
