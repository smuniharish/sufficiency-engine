"""Opt-in checks against a real OpenAI-compatible model.

Set ``SUFFICIENCY_TEST_LLM_API_KEY``, ``SUFFICIENCY_TEST_LLM_MODEL`` and, for a
non-OpenAI endpoint, ``SUFFICIENCY_TEST_LLM_BASE_URL``, install the ``live`` group and
run ``uv run --no-sync pytest -m live``. Task text is sent to the configured provider.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _live import live_model_call, live_settings, scripted_answerer  # noqa: E402

from sufficiency_engine import AssessmentStatus, SufficiencyEngine  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("SUFFICIENCY_TEST_LLM_API_KEY")
        or not os.environ.get("SUFFICIENCY_TEST_LLM_MODEL"),
        reason="no live model was configured",
    ),
]


@pytest.fixture
def model_call():
    pytest.importorskip("openai")
    pytest.importorskip("truststore")
    settings = live_settings()
    assert settings is not None
    return live_model_call(settings)


async def test_complete_task_is_sufficient_and_audited(model_call):
    result = await SufficiencyEngine(model_call=model_call).execute(
        input="Translate the sentence 'Good morning' into French."
    )

    assert result.status is AssessmentStatus.SUFFICIENT
    assert result.iteration_count == 0
    assert not result.blocking_requirements
    assert result.provenance is not None and result.provenance.decision_ids


async def test_missing_information_blocks_readiness(model_call):
    result = await SufficiencyEngine(model_call=model_call).execute(input="Book a flight for me.")

    assert result.status is AssessmentStatus.INSUFFICIENT
    assert not result.sufficient
    assert result.blocking_requirements
    assert result.questions


async def test_clarification_answer_resolves_the_task(model_call):
    asked: list[str] = []
    result = await SufficiencyEngine(
        model_call=model_call, interrupt_call=scripted_answerer("French", asked)
    ).execute(input="Translate the sentence 'Good morning' into the language my customer speaks.")

    assert asked
    assert result.sufficient
    assert result.iteration_count >= 1
    assert result.answers
