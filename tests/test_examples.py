"""Run the offline examples so the documented programs and output stay correct."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUICKSTART_OUTPUT = [
    "Question: Which platform should the service be deployed on?",
    "Status: sufficient",
    "Sufficient: True",
    "Clarification rounds: 1",
    "  platform: available, blocking=False",
    "Audited decisions: 2",
]


def run_example(name: str) -> str:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "examples" / name)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_quickstart_output_matches_the_documentation():
    assert run_example("quickstart.py").splitlines() == QUICKSTART_OUTPUT


def test_readme_quickstart_matches_the_example():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Quickstart", 1)[1]
    code, output = re.findall(r"```(?:python|text)\n(.*?)```", section, re.DOTALL)[:2]
    example = (ROOT / "examples" / "quickstart.py").read_text(encoding="utf-8")
    assert code == example.split("\n\n", 1)[1]
    assert output.splitlines() == QUICKSTART_OUTPUT


@pytest.mark.parametrize("name", ["standalone.py", "supervisor_worker.py"])
def test_offline_examples_run(name):
    pytest.importorskip("langgraph")
    pytest.importorskip("langchain_core")
    assert run_example(name)
