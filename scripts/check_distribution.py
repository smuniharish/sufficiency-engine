"""Verify built distributions against the source manifest without extracting archives."""

from __future__ import annotations

import argparse
import json
import tarfile
import tomllib
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from packaging.requirements import Requirement


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check(dist: Path) -> list[str]:
    root = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = manifest["project"]
    stem = f"{project['name'].replace('-', '_')}-{project['version']}"
    with ZipFile(dist / f"{stem}-py3-none-any.whl") as wheel:
        names = set(wheel.namelist())
        metadata = BytesParser(policy=policy.default).parsebytes(
            wheel.read(f"{stem}.dist-info/METADATA")
        )
    require(metadata["Name"] == project["name"], "distribution name mismatch")
    require(metadata["Version"] == project["version"], "version mismatch")
    require(metadata["Requires-Python"] == project["requires-python"], "Python range mismatch")
    require(
        metadata["Author-email"] == "S MUNI HARISH <samamuniharish@gmail.com>",
        "author mismatch",
    )
    urls = {url.split(", ", 1)[0] for url in metadata.get_all("Project-URL") or []}
    require(set(project["urls"]) <= urls, "project URLs missing from metadata")
    require(metadata["License-Expression"] == "Apache-2.0", "license mismatch")
    expected = {Requirement(dependency) for dependency in project["dependencies"]}
    for extra, dependencies in project["optional-dependencies"].items():
        expected.update(
            Requirement(f'{dependency}; extra == "{extra}"') for dependency in dependencies
        )
    require(
        {Requirement(value) for value in metadata.get_all("Requires-Dist", [])} == expected,
        "core or optional dependency boundary mismatch",
    )
    require("sufficiency_engine/py.typed" in names, "missing typing marker")
    require(f"{stem}.dist-info/licenses/LICENSE" in names, "missing wheel license")
    require(
        all(name.startswith(("sufficiency_engine/", f"{stem}.dist-info/")) for name in names),
        "non-runtime files in wheel",
    )
    with tarfile.open(dist / f"{stem}.tar.gz", "r:gz") as source:
        archived = {
            str(PurePosixPath(member.name).relative_to(stem))
            for member in source.getmembers()
            if member.isfile()
        }
    expected_files = {"pyproject.toml", "README.md", "LICENSE"}
    expected_files.update(
        path.relative_to(root).as_posix()
        for pattern in manifest["tool"]["uv"]["build-backend"]["source-include"]
        for path in root.glob(pattern)
        if path.is_file()
    )
    expected_files.update(
        path.relative_to(root).as_posix()
        for path in (root / "src").rglob("*")
        if path.is_file() and (path.suffix == ".py" or path.name == "py.typed")
    )
    require(expected_files <= archived, "source archive omits manifest files")
    forbidden = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "models",
        ".env",
    }
    require(
        not any(
            forbidden.intersection(PurePosixPath(name).parts)
            or PurePosixPath(name).suffix in {".pyc", ".pyo", ".safetensors", ".bin"}
            for name in names | archived
        ),
        "incidental environment, cache, or model files in distribution",
    )
    return [
        "metadata_and_extras",
        "typed_runtime_only_wheel",
        "complete_source_archive",
        "license_and_incidental_file_exclusion",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path(__file__).resolve().parents[1] / "dist")
    args = parser.parse_args()
    try:
        report: dict[str, object] = {"ok": True, "checks": check(args.dist)}
    except Exception as exc:
        report = {"ok": False, "error_type": type(exc).__name__}
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
