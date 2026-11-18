"""A LangGraph supervisor without a readiness gate: the starting point of eval 2."""

from __future__ import annotations

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class Work(TypedDict, total=False):
    task: str
    research: str
    code: str
    report: str


async def research(state: Work) -> Work:
    return {"research": f"notes for {state['task']}"}


async def develop(state: Work) -> Work:
    return {"code": f"patch based on {state['research']}"}


async def test(state: Work) -> Work:
    return {"report": f"tests passed for {state['code']}"}


def build_graph():
    builder = StateGraph(Work)
    builder.add_node("research", research)
    builder.add_node("develop", develop)
    builder.add_node("test", test)
    builder.add_edge(START, "research")
    builder.add_edge("research", "develop")
    builder.add_edge("develop", "test")
    builder.add_edge("test", END)
    return builder.compile(checkpointer=InMemorySaver())


graph = build_graph()


if __name__ == "__main__":
    config = {"configurable": {"thread_id": "demo"}}
    print(asyncio.run(graph.ainvoke({"task": "Add CSV export to reports."}, config)))
