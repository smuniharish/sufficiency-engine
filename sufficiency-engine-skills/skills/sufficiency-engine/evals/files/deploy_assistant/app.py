"""A deployment assistant without Sufficiency Engine: the starting point of eval 1."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

AskUser = Callable[[str], Awaitable[str]]


async def chat_model(messages: list[dict[str, str]]) -> str:
    """Stand-in for the application's existing model client."""
    return "Plan: build the image, push it, and roll out the service."


async def deploy(plan: str) -> str:
    """Stand-in for the application's existing deployment executor."""
    return f"executed: {plan}"


async def handle_task(task: str, ask_user: AskUser) -> str:
    plan = await chat_model([{"role": "user", "content": task}])
    return await deploy(plan)


async def console_user(question: str) -> str:
    return input(f"{question} ")


if __name__ == "__main__":
    print(asyncio.run(handle_task("Deploy the billing service.", console_user)))
