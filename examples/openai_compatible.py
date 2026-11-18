"""Assess a task with any OpenAI-compatible chat completions endpoint.

Install the client with ``pip install openai`` (or ``uv sync --group live``), then set:

* ``OPENAI_API_KEY``: the API key;
* ``OPENAI_BASE_URL`` (optional): a compatible endpoint such as a gateway or local server;
* ``OPENAI_MODEL``: a model that supports JSON mode.

Run ``python examples/openai_compatible.py "Deploy the billing service."``.
"""

import argparse
import asyncio
import os

import openai
from openai import AsyncOpenAI

from sufficiency_engine import AnswerSubmission, InteractionResponse, SufficiencyEngine
from sufficiency_engine.exceptions import TransientModelError

RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
    openai.RateLimitError,
)


def make_model_call(client: AsyncOpenAI, model: str):
    """Return a Sufficiency Engine model callback backed by chat completions."""

    async def model_call(messages):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except RETRYABLE as exc:
            raise TransientModelError("OpenAI-compatible endpoint is unavailable") from exc
        return response.choices[0].message.content or ""

    return model_call


async def ask_in_console(payload):
    answers = []
    for question in payload.questions:
        print(f"\n{question.text}\n  ({question.reason})")
        values = {}
        for requirement_id in question.requirement_ids:
            values[requirement_id] = await asyncio.to_thread(input, "> ")
        answers.append(AnswerSubmission(question_id=question.id, values=values))
    return InteractionResponse(answers=tuple(answers))


async def main(task: str) -> None:
    client = AsyncOpenAI(base_url=os.environ.get("OPENAI_BASE_URL"))
    engine = SufficiencyEngine(
        model_call=make_model_call(client, os.environ["OPENAI_MODEL"]),
        interrupt_call=ask_in_console,
    )
    result = await engine.execute(input=task)
    print("\nStatus:", result.status.value)
    print("Sufficient:", result.sufficient)
    for requirement in result.requirements:
        print(f"  {requirement.key}: {requirement.status.value}, blocking={requirement.blocking}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Assess a task with an OpenAI-compatible model.")
    parser.add_argument("task")
    asyncio.run(main(parser.parse_args().task))
