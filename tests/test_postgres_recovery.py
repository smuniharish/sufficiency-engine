import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.environ.get("SUFFICIENCY_TEST_POSTGRES_DSN")
        or not os.environ.get("AGXAI_POSTGRES_EXAMPLE"),
        reason="isolated PostgreSQL and the AGXAI example store were not configured",
    ),
]


def test_postgres_checkpoint_and_agxai_survive_process_restart():
    script = Path(__file__).parent / "fixtures" / "postgres_recovery.py"
    first = subprocess.run(
        [sys.executable, str(script), "--phase", "prepare"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert first.returncode == 0, first.stderr
    prepared = json.loads(first.stdout)
    second = subprocess.run(
        [
            sys.executable,
            str(script),
            "--phase",
            "resume",
            "--question-id",
            prepared["question_id"],
            "--requirement-id",
            prepared["requirement_id"],
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert second.returncode == 0, second.stderr
    resumed = json.loads(second.stdout)
    assert resumed["assessment_id"] == prepared["assessment_id"]
    assert resumed["run_id"] == prepared["run_id"]
    assert resumed["question_id"] == prepared["question_id"]
    assert resumed["requirement_id"] == prepared["requirement_id"]
    assert resumed["parents"] >= 2
    assert resumed["artifacts"] >= 3
