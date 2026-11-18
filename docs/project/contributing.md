# Contributing

Contributions are welcome. The full guide, including what to discuss before a
change and what a pull request needs, is
[CONTRIBUTING.md](https://github.com/smuniharish/sufficiency-engine/blob/main/CONTRIBUTING.md)
in the repository.

## Scope

Sufficiency Engine decides whether a task has enough information to proceed. It
is not an agent framework, a workflow engine, or a hosted service. Changes keep
the core free of any model provider or agent framework: LangGraph and
OpenTelemetry support stays in optional extras, extension points are abstract
base classes, and AGXAI remains the only provenance implementation.

## Set up

Python 3.12 or later and [uv](https://docs.astral.sh/uv/) are required.

```bash
git clone https://github.com/smuniharish/sufficiency-engine.git
cd sufficiency-engine
uv sync --extra langgraph --extra observability --group docs --group local-integration
```

## Check a change

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run pytest
uv run zensical build --strict
node scripts/render-diagrams.mjs --check
```

See [Testing](testing.md) for the test layout, coverage, the optional
PostgreSQL suite, evaluations, and diagrams.

## Pull requests

- Describe the user-visible impact, including any effect on readiness
  decisions, stored sessions, or recorded provenance.
- Add or update tests for every behavior change.
- Update the affected documentation pages and the [changelog](changelog.md).
- Update the [Agent Skills](../agent-skills/index.md) with any related API or
  behavior change.
- Open an issue first for changes to the public API, callback payloads,
  stored state, the readiness policy, or an integration.

## Security reports

Do not report vulnerabilities in public issues. See [Security](../security.md).