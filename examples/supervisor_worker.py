"""Checkpointed task entry before a realistic, isolated supervisor-worker flow."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from sufficiency_engine import AssessmentResult, SufficiencyEngine
from sufficiency_engine.integrations.langgraph import build_assessment_graph


class HostState(BaseModel):
    """Application-owned graph state; no conversation store is duplicated."""

    model_config = ConfigDict(extra="forbid")

    task: str
    session_id: str
    repository: str
    assessment: dict[str, JsonValue] | None = None
    response: JsonValue = None
    readiness: dict[str, JsonValue] | None = None
    plan: str = ""
    research: str = ""
    development: str = ""
    test_output: str = ""
    final: str = ""
    events: list[str] = Field(default_factory=list)


def discovery_item(**updates):
    return {
        "key": "expected_result",
        "description": "Expected result of add(3, 2)",
        "classification": "mandatory",
        "status": "unresolved",
        "necessity": "must_ask",
        "reason": "The worker needs the expected behavior before modifying code.",
        "question": "What should add(3, 2) return?",
        "answer_type": "integer",
        **updates,
    }


async def main():
    first = discovery_item()
    independent = discovery_item(
        key="operating_system",
        description="Target operating system",
        status="available",
        evidence_quote="Linux",
        necessity="not_needed",
        question=None,
        answer_type="string",
    )
    discovery_model = GenericFakeChatModel(
        messages=iter(
            AIMessage(content=json.dumps({"requirements": [item]}))
            for item in (
                first,
                discovery_item(status="available", evidence_quote="5"),
                independent,
            )
        )
    )
    worker_model = GenericFakeChatModel(
        messages=iter(
            AIMessage(content=text)
            for text in (
                "Plan: inspect, fix the arithmetic, run the tests, and report.",
                "Research: inspect the fixture's implementation and tests.",
                "Development: replace subtraction with addition.",
                "Testing: run the fixture's unit tests.",
                "Supervisor: the requested arithmetic fix was verified.",
            )
        )
    )
    calls = {"discovery": 0, "task_entries": 0, "after_entry_discovery": 0}

    async def model_call(messages):
        calls["discovery"] += 1
        return await discovery_model.ainvoke(messages)

    async def worker_call(message):
        response = await worker_model.ainvoke([{"role": "user", "content": message}])
        return str(response.content)

    engine = SufficiencyEngine(model_call=model_call)
    assessment = build_assessment_graph(engine)
    builder = StateGraph(HostState)

    def task_entry(state: HostState) -> dict[str, JsonValue]:
        calls["task_entries"] += 1
        return {"events": [*state.events, "task-entry"]}

    def route(state: HostState) -> str:
        if state.readiness is None:
            raise RuntimeError("assessment did not return readiness")
        return (
            "supervisor" if AssessmentResult.model_validate(state.readiness).sufficient else "stop"
        )

    async def supervisor(state: HostState) -> dict[str, JsonValue]:
        calls["after_entry_discovery"] = calls["discovery"]
        plan = await worker_call("Create a plan for the approved task.")
        return {"plan": plan, "events": [*state.events, "supervisor-plan"]}

    async def researcher(state: HostState) -> dict[str, JsonValue]:
        await worker_call("Inspect the repository.")
        code = (Path(state.repository) / "calculator.py").read_text(encoding="utf-8")
        if "return a - b" not in code:
            raise RuntimeError("fixture did not contain the expected defect")
        return {
            "research": "The add function subtracts instead of adding.",
            "events": [*state.events, "researcher"],
        }

    async def developer(state: HostState) -> dict[str, JsonValue]:
        await worker_call("Apply the requested change.")
        path = Path(state.repository) / "calculator.py"
        source = path.read_text(encoding="utf-8")
        if source.count("return a - b") != 1:
            raise RuntimeError("fixture changed unexpectedly")
        path.write_text(source.replace("return a - b", "return a + b", 1), encoding="utf-8")
        return {
            "development": "Changed subtraction to addition.",
            "events": [*state.events, "developer"],
        }

    async def tester(state: HostState) -> dict[str, JsonValue]:
        await worker_call("Run the tests.")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "unittest",
            "-q",
            cwd=state.repository,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError("fixture tests failed")
        return {
            "test_output": output.decode("utf-8", errors="replace"),
            "events": [*state.events, "tester"],
        }

    async def final_supervisor(state: HostState) -> dict[str, JsonValue]:
        if calls["discovery"] != calls["after_entry_discovery"]:
            raise RuntimeError("ordinary worker execution triggered reassessment")
        summary = await worker_call(
            f"Summarize research and actual test results: {state.research}\n{state.test_output}"
        )
        return {"final": summary, "events": [*state.events, "supervisor-final"]}

    builder.add_node("task_entry", task_entry)
    builder.add_node("readiness", assessment)
    builder.add_node("supervisor", supervisor)
    builder.add_node("researcher", researcher)
    builder.add_node("developer", developer)
    builder.add_node("tester", tester)
    builder.add_node("final_supervisor", final_supervisor)
    builder.add_edge(START, "task_entry")
    builder.add_edge("task_entry", "readiness")
    builder.add_conditional_edges("readiness", route, {"supervisor": "supervisor", "stop": END})
    builder.add_edge("supervisor", "researcher")
    builder.add_edge("researcher", "developer")
    builder.add_edge("developer", "tester")
    builder.add_edge("tester", "final_supervisor")
    builder.add_edge("final_supervisor", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    with tempfile.TemporaryDirectory(prefix="sufficiency-example-") as directory:
        root = Path(directory)
        (root / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (root / "test_calculator.py").write_text(
            "import unittest\nfrom calculator import add\n\n"
            "class CalculatorTests(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(3, 2), 5)\n",
            encoding="utf-8",
        )
        config = {"configurable": {"thread_id": "software-task"}}
        paused = await graph.ainvoke(
            {
                "task": "Fix the calculation in the sample project.",
                "session_id": "software-task",
                "repository": directory,
            },
            config,
        )
        payload = paused["__interrupt__"][0].value
        question = payload["questions"][0]
        print(f"Clarification: {question['text']} Answer: 5")
        resume = {
            "answers": [
                {"question_id": question["id"], "values": {question["requirement_ids"][0]: 5}}
            ]
        }
        finished = await graph.ainvoke(Command(resume=resume), config)
        assert finished["events"] == [
            "task-entry",
            "supervisor-plan",
            "researcher",
            "developer",
            "tester",
            "supervisor-final",
        ]
        assert "OK" in finished["test_output"]
        assert calls["task_entries"] == 1 and calls["discovery"] == 2
        print(finished["final"])

        calls["task_entries"] += 1
        new_task = await engine.execute(
            input="Document the project for Linux.", session_id="independent-task"
        )
        assert new_task.sufficient and calls["discovery"] == 3 and calls["task_entries"] == 2
        print("A separately created independent task was assessed explicitly.")


if __name__ == "__main__":
    asyncio.run(main())
