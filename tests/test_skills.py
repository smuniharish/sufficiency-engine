"""Validate the distributed instructions and execute their offline checks."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from skills_ref import read_properties, validate

ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "sufficiency-engine-skills" / "skills"
SKILLS = sorted(path.parent for path in SKILLS_ROOT.glob("*/SKILL.md"))
SCRIPTS = [path for skill in SKILLS for path in (skill / "scripts").glob("*.py")]


def run(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )


def test_discovery_manifest_and_skills_are_consistent():
    manifest = json.loads((ROOT / "skills.sh.json").read_text(encoding="utf-8"))
    assert [(ROOT / path).resolve() for path in manifest["paths"]] == [SKILLS_ROOT.resolve()]
    assert {skill.name for skill in SKILLS} == {"sufficiency-engine", "sufficiency-engine-extend"}


@pytest.mark.parametrize("skill", SKILLS, ids=lambda path: path.name)
def test_skill_specification_links_and_eval_datasets(skill):
    properties = read_properties(skill)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert validate(skill) == []
    assert properties.name == skill.name
    assert properties.metadata["version"] == project["version"]
    body = (skill / "SKILL.md").read_text(encoding="utf-8")
    for reference in (skill / "references").glob("*.md"):
        assert f"](references/{reference.name})" in body
    for script in (skill / "scripts").glob("*.py"):
        assert f"scripts/{script.name}" in body
    for asset in (skill / "assets").glob("*.py"):
        assert f"assets/{asset.name}" in body
    for page in skill.rglob("*.md"):
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", page.read_text(encoding="utf-8")):
            if "://" not in target:
                assert (page.parent / target).is_file()
    evaluations = json.loads((skill / "evals" / "evals.json").read_text(encoding="utf-8"))
    assert evaluations["skill_name"] == skill.name
    assert len({case["id"] for case in evaluations["evals"]}) == len(evaluations["evals"])
    for case in evaluations["evals"]:
        assert case["prompt"] and case["expected_output"] and case["assertions"]
        for name in case["files"]:
            assert (skill / "evals" / name).is_file()
    starting_files = {
        path.relative_to(skill / "evals").as_posix()
        for path in (skill / "evals" / "files").rglob("*.py")
    }
    assert starting_files == {name for case in evaluations["evals"] for name in case["files"]}
    for path in starting_files:
        compile((skill / "evals" / path).read_text(encoding="utf-8"), path, "exec")
    triggers = json.loads((skill / "evals" / "trigger_queries.json").read_text(encoding="utf-8"))
    assert triggers["skill_name"] == skill.name
    assert len({row["query"] for row in triggers["queries"]}) == len(triggers["queries"]) == 20
    for split in ("train", "validation"):
        labels = [row["should_trigger"] for row in triggers["queries"] if row["split"] == split]
        assert labels.count(True) == labels.count(False) > 0


def test_no_trigger_query_selects_both_skills():
    positives = [
        {
            row["query"]
            for row in json.loads(
                (skill / "evals" / "trigger_queries.json").read_text(encoding="utf-8")
            )["queries"]
            if row["should_trigger"]
        }
        for skill in SKILLS
    ]
    assert not set.intersection(*positives)


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.stem)
def test_skill_scripts_run_offline_and_support_help(script):
    assert run(script, "--help").returncode == 0
    result = run(script, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] and report["checks"]


def test_skill_checks_real_optional_graph_interrupt_resume():
    script = SKILLS_ROOT / "sufficiency-engine" / "scripts" / "verify_setup.py"
    result = run(script, "--langgraph", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "langgraph_interrupt_resume" in json.loads(result.stdout)["checks"]


def test_sqlite_template_passes_contract_checks_and_audits_an_assessment(tmp_path):
    skill = SKILLS_ROOT / "sufficiency-engine-extend"
    result = run(
        skill / "scripts" / "check_extensions.py",
        *("--path", str(skill / "assets"), "--json"),
        *("--persistence", "sqlite_store:make_test_store"),
        *("--archive", "sqlite_store:make_test_archive"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(json.loads(result.stdout)["checks"]) == 7

    script = f"""
import asyncio, sqlite3, sys
sys.path[:0] = [{str(skill / "assets")!r}, {str(ROOT / "examples")!r}]
from quickstart import ask_user, model_call
from sqlite_store import SQLitePersistence, SQLiteSemanticArchive
from sufficiency_engine import AGXAIAudit, SessionScope, SufficiencyEngine

async def main():
    path = {str(tmp_path / "store.sqlite3")!r}
    engine = SufficiencyEngine(
        model_call=model_call, interrupt_call=ask_user,
        persistence=SQLitePersistence(path),
        audit=AGXAIAudit(archive=SQLiteSemanticArchive(path)),
    )
    result = await engine.execute(input="Deploy the billing service.", session_id="s1")
    assert result.sufficient and result.provenance.decision_ids
    scope = SessionScope(application_id="application", tenant_id="default", session_id="s1")
    assert await SQLitePersistence(path).load(scope) is not None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sufficiency_artifacts").fetchone()[0]
    print("ok")

asyncio.run(main())
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip().endswith("ok")


def test_extension_checker_rejects_broken_store_and_sanitizes_errors(tmp_path):
    script = SKILLS_ROOT / "sufficiency-engine-extend" / "scripts" / "check_extensions.py"
    (tmp_path / "broken.py").write_text(
        "from sufficiency_engine import InMemoryPersistence\n"
        "class Store(InMemoryPersistence):\n"
        "    async def save(self, scope, state, *, expected_revision, claim):\n"
        "        state['value'] = 'corrupt'\n"
        "        return await super().save(\n"
        "            scope, state, expected_revision=expected_revision, claim=claim)\n"
        "def fail():\n"
        "    raise RuntimeError('sensitive_backend_detail')\n",
        encoding="utf-8",
    )
    for factory, error in (("broken:Store", "AssertionError"), ("broken:fail", "RuntimeError")):
        result = run(script, "--path", str(tmp_path), "--persistence", factory, "--json")
        assert result.returncode == 1
        assert json.loads(result.stdout) == {"ok": False, "error_type": error}
        assert "sensitive_backend_detail" not in result.stdout + result.stderr
