"""Run the PostgreSQL process-restart recovery test against a disposable container.

The script mirrors the CI ``postgres`` job: it starts the pinned PostgreSQL image
with Podman or Docker, fetches AGXAI's ``examples/postgres_store.py`` at the pinned
commit, runs ``tests/test_postgres_recovery.py`` and always removes the container.

Usage::

    uv sync --extra langgraph --group local-integration
    uv run --no-sync python scripts/run_postgres_recovery.py
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "docker.io/library/postgres@sha256:"
    "b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24"
)
AGXAI_REF = "1cf60e96c4c804a964a9a164128ca0830cfe236d"
AGXAI_EXAMPLE_URL = (
    f"https://raw.githubusercontent.com/smuniharish/agxai/{AGXAI_REF}/examples/postgres_store.py"
)
USER = "sufficiency_test"


def _run(command: list[str], *, check: bool = True) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _engine(requested: str | None) -> str:
    for candidate in [requested] if requested else ["podman", "docker"]:
        if candidate and shutil.which(candidate):
            return candidate
    raise SystemExit("Podman or Docker is required; pass --engine to choose one.")


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _candidate_hosts(engine: str) -> list[str]:
    hosts = ["127.0.0.1"]
    if engine == "podman":
        # Podman machines on Windows do not always forward ports to localhost.
        output = _run(
            ["podman", "machine", "ssh", "--", "ip", "-4", "-o", "addr", "show"], check=False
        )
        hosts += [
            address
            for address in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", output)
            if not address.startswith("127.")
        ]
    return hosts


def _wait_ready(engine: str, name: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = subprocess.run(
            [engine, "exec", name, "pg_isready", "-U", USER, "-d", USER],
            capture_output=True,
            check=False,
        )
        if status.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("PostgreSQL did not become ready in time.")


def _resolve_host(engine: str, port: int, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    hosts = _candidate_hosts(engine)
    while time.monotonic() < deadline:
        for host in hosts:
            if _reachable(host, port):
                return host
        time.sleep(1)
    raise RuntimeError(f"No reachable address for port {port}; tried {', '.join(hosts)}.")


def _agxai_example(path: str | None, directory: Path) -> Path:
    if path:
        return Path(path).resolve()
    target = directory / "postgres_store.py"
    with urllib.request.urlopen(AGXAI_EXAMPLE_URL, timeout=30) as response:  # noqa: S310
        target.write_bytes(response.read())
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", choices=["podman", "docker"])
    parser.add_argument("--port", type=int, default=55432)
    parser.add_argument("--agxai-example", help="Local AGXAI examples/postgres_store.py")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    engine = _engine(args.engine)
    name = f"sufficiency-postgres-{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    with tempfile.TemporaryDirectory() as temporary:
        example = _agxai_example(args.agxai_example, Path(temporary))
        _run(
            [
                engine,
                "run",
                "-d",
                "--name",
                name,
                "-e",
                f"POSTGRES_USER={USER}",
                "-e",
                f"POSTGRES_PASSWORD={password}",
                "-e",
                f"POSTGRES_DB={USER}",
                "-p",
                f"{args.port}:5432",
                IMAGE,
            ]
        )
        try:
            _wait_ready(engine, name, args.timeout)
            host = _resolve_host(engine, args.port, args.timeout)
            environment = os.environ | {
                "SUFFICIENCY_TEST_POSTGRES_DSN": (
                    f"postgresql://{USER}:{password}@{host}:{args.port}/{USER}"
                ),
                "AGXAI_POSTGRES_EXAMPLE": str(example),
            }
            print(f"PostgreSQL ready at {host}:{args.port}", flush=True)
            return subprocess.run(
                [sys.executable, "-m", "pytest", "tests/test_postgres_recovery.py", "-v"],
                cwd=ROOT,
                env=environment,
                check=False,
            ).returncode
        finally:
            _run([engine, "rm", "-f", name], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
