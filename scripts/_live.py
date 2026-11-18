"""Shared helpers for live OpenAI-compatible model checks.

Settings come only from the environment so credentials never reach files:
``SUFFICIENCY_TEST_LLM_API_KEY``, ``SUFFICIENCY_TEST_LLM_BASE_URL`` and
``SUFFICIENCY_TEST_LLM_MODEL``, falling back to ``OPENAI_API_KEY``,
``OPENAI_BASE_URL`` and ``OPENAI_MODEL``.
"""

from __future__ import annotations

import os
import ssl
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sufficiency_engine import AnswerSubmission, InteractionResponse
from sufficiency_engine.models import ClarificationPayload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))


@dataclass(frozen=True)
class LiveSettings:
    api_key: str
    base_url: str | None
    model: str


def live_settings() -> LiveSettings | None:
    """Return live settings, or ``None`` when no key and model are configured."""
    api_key = os.environ.get("SUFFICIENCY_TEST_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("SUFFICIENCY_TEST_LLM_MODEL") or os.environ.get("OPENAI_MODEL")
    if not api_key or not model:
        return None
    base_url = os.environ.get("SUFFICIENCY_TEST_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    return LiveSettings(api_key=api_key, base_url=base_url, model=model)


def live_model_call(settings: LiveSettings) -> Callable[..., Awaitable[str]]:
    """Build the documented example adapter, verifying TLS with the OS trust store."""
    import httpx
    import truststore
    from openai import AsyncOpenAI
    from openai_compatible import make_model_call

    client = AsyncOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        http_client=httpx.AsyncClient(
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), timeout=120.0
        ),
    )
    return make_model_call(client, settings.model)


def scripted_answerer(
    value: str, asked: list[str]
) -> Callable[[ClarificationPayload], Awaitable[InteractionResponse]]:
    """Answer every question with ``value``, or the matching/first allowed choice."""

    async def answer(payload: ClarificationPayload) -> InteractionResponse:
        submissions = []
        for question in payload.questions:
            asked.append(question.text)
            choices = question.constraints.choices
            selected = (value if value in choices else choices[0]) if choices else value
            submissions.append(
                AnswerSubmission(
                    question_id=question.id,
                    values=dict.fromkeys(question.requirement_ids, selected),
                )
            )
        return InteractionResponse(answers=tuple(submissions))

    return answer
