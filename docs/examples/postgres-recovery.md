# PostgreSQL recovery

A test that proves an assessment survives a process restart with durable
storage. The first process starts a LangGraph assessment and stops at the
clarification interrupt. A second, new process resumes the same thread,
answers, and reads the AGXAI records back.

It uses:

- LangGraph's `AsyncPostgresSaver` as the checkpointer.
- AGXAI's example PostgreSQL provenance store, from the AGXAI repository.
- A test-only PostgreSQL semantic archive in
  `tests/fixtures/postgres_recovery.py`.

## Run it

With Podman or Docker installed, one command starts a disposable container
from the pinned PostgreSQL image, fetches AGXAI's example store at the pinned
commit, runs the test, and removes the container:

```bash
uv sync --extra langgraph --group local-integration
uv run python scripts/run_postgres_recovery.py
```

On Windows, when a Podman machine does not forward ports to `localhost`, the
script connects through the machine's address instead.

To use your own **isolated, disposable** database instead (the test creates and
writes tables):

```bash
git clone https://github.com/smuniharish/agxai ../agxai
SUFFICIENCY_TEST_POSTGRES_DSN=postgresql://user:password@127.0.0.1:5432/test_db \
AGXAI_POSTGRES_EXAMPLE=../agxai/examples/postgres_store.py \
uv run pytest tests/test_postgres_recovery.py
```

Without both variables, the test is skipped. CI runs it in a separate job
against the same pinned PostgreSQL image and AGXAI commit.

## What it checks

- The resumed process sees the same assessment, run, question, and requirement
  IDs.
- The decision has at least two AGXAI evidence links, read through new
  connections.

## Limits

The archive is a test fixture, not a production adapter, and AGXAI's store is
an example. The test does not cover backups, failover, crash consistency, or
load. Use it as a template for testing your own stores; see
[Use durable storage](../guide/how-to/durable-storage.md).
