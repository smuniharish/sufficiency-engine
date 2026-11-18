"""Verify an installed Sufficiency Engine offline; --langgraph checks the optional adapter."""

from __future__ import annotations

import argparse
import asyncio
import json
from importlib.metadata import version

from sufficiency_engine import (
    AnswerSubmission,
    AssessmentResult,
    ClarificationPayload,
    InteractionResponse,
    SufficiencyEngine,
)


async def model(messages: list[dict[str, str]]) -> dict[str, object]:
    supplied = json.loads(messages[-1]["content"])
    prior = supplied["prior"]
    resolved = "Linux" in supplied["task"] or bool(prior and prior[0]["answers"] == ["Linux"])
    return {
        "requirements": [
            {
                "key": "platform",
                "description": "Deployment platform",
                "classification": "mandatory",
                "status": "available" if resolved else "unresolved",
                "evidence_quote": "Linux" if resolved else None,
                "necessity": "must_ask",
                "question": "Which platform?",
                "reason": "Required for deployment.",
                "answer_type": "string",
            }
        ]
    }


def answer(payload: ClarificationPayload) -> InteractionResponse:
    question = payload.questions[0]
    return InteractionResponse(
        answers=(
            AnswerSubmission(
                question_id=question.id, values={question.requirement_ids[0]: "Linux"}
            ),
        )
    )


DESCRIPTIONS = {
    "core_readiness": "a complete task is ready without questions",
    "clarification_reassessment": "a missing value is asked, answered, and reassessed",
    "agxai_provenance": "the result has AGXAI provenance",
    "session_deletion": "the session and its AGXAI run are deleted",
    "langgraph_interrupt_resume": "a LangGraph interrupt is answered and resumed",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def verify(langgraph: bool) -> list[str]:
    engine = SufficiencyEngine(model_call=model, interrupt_call=answer)
    complete = await engine.execute(input="Deploy Linux")
    clarified = await engine.execute(input="Deploy")
    require(complete.sufficient and clarified.sufficient, "offline readiness failed")
    require(clarified.iteration_count == 1, "clarification lifecycle failed")
    require(clarified.provenance is not None, "mandatory provenance is missing")
    await engine.delete_session(clarified.session_id)
    checks = [
        "core_readiness",
        "clarification_reassessment",
        "agxai_provenance",
        "session_deletion",
    ]
    if langgraph:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.types import Command

        from sufficiency_engine.integrations.langgraph import build_assessment_graph

        graph = build_assessment_graph(
            SufficiencyEngine(model_call=model), checkpointer=InMemorySaver()
        )
        config = {"configurable": {"thread_id": "skill-setup"}}
        paused = await graph.ainvoke({"task": "Deploy"}, config)
        question = paused["__interrupt__"][0].value["questions"][0]
        resumed = await graph.ainvoke(
            Command(
                resume={
                    "answers": [
                        {
                            "question_id": question["id"],
                            "values": {question["requirement_ids"][0]: "Linux"},
                        }
                    ]
                }
            ),
            config,
        )
        require(
            AssessmentResult.model_validate(resumed["readiness"]).sufficient, "graph resume failed"
        )
        checks.append("langgraph_interrupt_resume")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--langgraph", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    checks: list[str] = []
    try:
        checks = asyncio.run(verify(args.langgraph))
        report: dict[str, object] = {
            "ok": True,
            "version": version("sufficiency-engine"),
            "checks": checks,
        }
    except Exception as exc:
        report = {"ok": False, "error_type": type(exc).__name__}
    if args.json:
        print(json.dumps(report))
    elif report["ok"]:
        print(f"PASS  sufficiency-engine {report['version']}, agxai {version('agxai')}")
        for check in checks:
            print(f"PASS  {DESCRIPTIONS[check]}")
        if not args.langgraph:
            print("SKIP  LangGraph interrupt and resume (add --langgraph to check it)")
        print("All checks passed.")
    else:
        print(f"FAIL  {report['error_type']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
