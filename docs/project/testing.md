# Testing

The default test run needs no model, no network service, and no API key. Model
and clarification callbacks are deterministic test doubles, so every readiness
decision in the suite is reproducible.

## Everyday commands

```bash
uv sync --extra langgraph --extra observability --group docs --group local-integration
uv run pytest                     # the full offline suite
uv run ruff check .               # lint
uv run ruff format --check .      # formatting, including Markdown code blocks
uv run pyrefly check              # type checking
```

pytest runs with `--strict-config --strict-markers` and `asyncio_mode = "auto"`,
so async tests need no decorator.

## Coverage

Continuous integration requires 100% line and branch coverage of the readiness
policy and the public models:

```bash
uv run pytest --cov=sufficiency_engine.models --cov=sufficiency_engine.policy \
    --cov-branch --cov-fail-under=100
```

Run `uv run pytest --cov=sufficiency_engine --cov-branch` to see coverage of the
whole package.

## Layout

| File | Covers |
| --- | --- |
| `tests/test_policy.py` | Blocking rules, assumptions, lifecycle transitions, dependency graphs, limits, and result invariants |
| `tests/test_engine.py` | The assessment lifecycle, clarification, lineage, reassessment, stale answers, recovery, concurrency, deletion, and failure results |
| `tests/test_discovery_clarification.py` | Answer validation, model response normalization, retries, timeouts, and question deduplication |
| `tests/test_persistence_provenance.py` | State round trips, scoped revision-checked storage, claims, and AGXAI records and replay |
| `tests/test_langgraph.py` | The LangGraph node: interrupts, resumes, malformed resumes, and checkpointed state |
| `tests/test_observability.py` | Observations and the OpenTelemetry observer with the real SDK |
| `tests/test_examples.py` | The offline example scripts and the documented quickstart |
| `tests/test_evaluations.py` | The labeled readiness and deduplication evaluations |
| `tests/test_skills.py` | Both Agent Skills: format, links, scripts, eval datasets, trigger queries, and the SQLite template |
| `tests/test_postgres_recovery.py` | Process-restart recovery against a real PostgreSQL checkpointer and AGXAI store |
| `tests/test_live_model.py` | A complete task, a blocked task, and a clarification loop against a real OpenAI-compatible model |

## Property-based tests

[Hypothesis](https://hypothesis.readthedocs.io) checks invariants over
generated inputs, including:

- every combination of classification, status, and `require_optional` blocks
  exactly when a required requirement is not available;
- generated lifecycle paths keep requirement identity and never leave a
  terminal state;
- a follow-up question is never merged with the question it follows up, for
  any text;
- assessment state survives a JSON round trip with its identifiers unchanged,
  for any task text.

## PostgreSQL recovery

`tests/test_postgres_recovery.py` carries the `postgres` marker. With Podman or
Docker, one command runs it end to end against a disposable container from the
same pinned image and AGXAI commit as CI, and removes the container afterwards:

```bash
uv run python scripts/run_postgres_recovery.py
```

To use your own isolated, disposable database instead, set both variables; the
test is skipped without them.

| Variable | Value |
| --- | --- |
| `SUFFICIENCY_TEST_POSTGRES_DSN` | A connection string for the isolated database |
| `AGXAI_POSTGRES_EXAMPLE` | The path to `examples/postgres_store.py` in an AGXAI checkout |

```bash
uv run pytest tests/test_postgres_recovery.py
```

A separate CI job runs it against a PostgreSQL service container.

## Live model

`tests/test_live_model.py` carries the `live` marker and is skipped unless a
model is configured. It sends task text to that provider.

| Variable | Value |
| --- | --- |
| `SUFFICIENCY_TEST_LLM_API_KEY` | The API key; keep it in your environment or secret store |
| `SUFFICIENCY_TEST_LLM_MODEL` | A model that supports JSON mode |
| `SUFFICIENCY_TEST_LLM_BASE_URL` | Optional; an OpenAI-compatible endpoint |

```bash
uv sync --group live
uv run pytest -m live
uv run python scripts/run_live_evaluation.py --repeats 3
```

The CI `live` job runs both on pushes when repository secrets with these names
are configured, and skips with a notice otherwise. TLS is verified against the
operating system's trust store, so the tests also work behind a TLS-inspecting
proxy.

## Evaluations and benchmarks

```bash
uv run python scripts/evaluate_readiness.py
uv run python scripts/evaluate_deduplication.py
uv run python scripts/benchmark.py
```

The evaluations use small labeled fixtures. They guard behavior; they do not
measure a discovery model. See [Benchmarks](../benchmarks.md) and
[Evaluate discovery](../guide/how-to/evaluate-discovery.md).

## Documentation and diagrams

```bash
uv run zensical build --strict          # fails on broken links and references
node scripts/render-diagrams.mjs        # re-render after editing diagrams/*.mmd
node scripts/render-diagrams.mjs --check
```

Diagrams are rendered with Mermaid CLI 12.2.0, installed globally
(`npm install --global --allow-scripts=puppeteer @mermaid-js/mermaid-cli@12.2.0`,
Node.js 22.13 or later). The check needs only Node.js and fails when a rendered
image is missing, stale, or has no source.

## Package

```bash
uv lock --check
uv build
uv run python scripts/check_distribution.py
```

`check_distribution.py` compares the built wheel and source distribution with
`pyproject.toml`: name, version, Python range, author, license, dependencies,
and the files each archive must contain.