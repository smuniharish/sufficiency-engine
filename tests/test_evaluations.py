"""Exercise the labeled evaluators as maintainers invoke them."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
        cwd=ROOT,
    )


def test_labeled_dedup_reports_candidate_errors_without_unsafe_suppression():
    result = run("evaluate_deduplication.py")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    for split in ("calibration", "validation"):
        assert report["lexical_candidate_stage"][split]["false_positive"] > 0
        assert report["lexical_candidate_stage"][split]["false_negative"] > 0
        assert report["actual_pipeline"][split]["false_positive"] == 0
    assert all(case["passed"] for case in report["cases"])


def test_explicit_embedding_evaluation_and_failure_are_visible(tmp_path):
    (tmp_path / "vectors.py").write_text(
        "from sufficiency_engine import EmbeddingModelABC\n"
        "class Model(EmbeddingModelABC):\n"
        "    async def embed(self, texts):\n"
        "        return [[1.0, 0.0] for text in texts]\n"
        "class Broken(EmbeddingModelABC):\n"
        "    async def embed(self, texts):\n"
        "        return [[] for text in texts]\n",
        encoding="utf-8",
    )
    result = run(
        "evaluate_deduplication.py", "--path", str(tmp_path), "--embedding-factory", "vectors:Model"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    negatives = [case for case in report["cases"] if not case["equivalent"]]
    assert all(case["retained"] == 2 for case in negatives)
    assert any("potential_duplicate" in case["warnings"] for case in negatives)
    broken = run(
        "evaluate_deduplication.py",
        "--path",
        str(tmp_path),
        "--embedding-factory",
        "vectors:Broken",
    )
    assert broken.returncode == 1
    assert not json.loads(broken.stdout)["ok"]


def test_readiness_seed_and_explicit_model_callback_gate(tmp_path):
    offline = run("evaluate_readiness.py")
    assert offline.returncode == 0, offline.stdout + offline.stderr
    report = json.loads(offline.stdout)
    assert report["mode"] == "offline_fixture"
    assert report["false_ready"] == report["false_not_ready"] == 0
    (tmp_path / "discovery.py").write_text(
        "async def empty(messages):\n    return {'requirements': []}\n",
        encoding="utf-8",
    )
    application = run(
        "evaluate_readiness.py", "--path", str(tmp_path), "--callback", "discovery:empty"
    )
    assert application.returncode == 1
    report = json.loads(application.stdout)
    assert report["mode"] == "application_callback"
    assert report["false_not_ready"] > 0
    assert "Deploy" not in application.stdout


def test_model_failures_do_not_count_as_successful_negative_evaluation(tmp_path):
    (tmp_path / "discovery.py").write_text(
        "def fail(messages):\n    raise RuntimeError('sensitive_provider_detail')\n",
        encoding="utf-8",
    )
    fixture = tmp_path / "negative.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "id": "missing",
                    "input": "Unknown platform",
                    "expected_sufficient": False,
                    "response": {"requirements": []},
                }
            ]
        ),
        encoding="utf-8",
    )
    result = run(
        "evaluate_readiness.py",
        "--path",
        str(tmp_path),
        "--callback",
        "discovery:fail",
        "--fixtures",
        str(fixture),
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["false_ready"] == 0 and report["execution_failures"] == 1
    assert not report["ok"]
    assert "sensitive_provider_detail" not in result.stdout + result.stderr
