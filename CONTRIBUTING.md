# Contributing

Thank you for improving Sufficiency Engine. Contributions should keep its
focus: a library that decides whether a task has enough information to proceed,
not an agent framework, workflow engine, or hosted service.

Keep the core provider- and framework-neutral. LangGraph and OpenTelemetry
support belongs in optional extras, and extension points are abstract base
classes. AGXAI is the only provenance implementation; do not add a second one.

## Before opening a change

1. Read the [architecture overview](docs/architecture/index.md).
2. Open an issue first for changes to the public API, callback payloads,
   persisted state, readiness policy, or an integration.
3. Keep each change focused, with tests and documentation for anything a user
   can observe.

## Development setup

Python 3.12 or later and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync --extra langgraph --extra observability --group docs --group local-integration
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run pytest
```

The default test run needs no model, service, or API key. The PostgreSQL
recovery test runs only when its isolated database and the AGXAI example store
are configured; see [Testing and validation](docs/project/testing.md).

Never commit credentials, local environments, model weights, or generated
reports.

## Documentation and diagrams

```bash
uv run zensical build --strict
uv run zensical serve
```

Diagrams are Mermaid sources under [`diagrams/`](diagrams), rendered to PNG
with Mermaid CLI 12.2.0. Install it globally; it needs Node.js 22.13 or later.
`--allow-scripts=puppeteer` lets Puppeteer download the headless browser the
CLI renders with:

```bash
npm install --global --allow-scripts=puppeteer @mermaid-js/mermaid-cli@12.2.0
node scripts/render-diagrams.mjs
node scripts/render-diagrams.mjs --check
```

Commit a changed diagram source together with its rendered image and the
updated `docs/assets/diagrams/manifest.json`. The `--check` mode needs no
browser and runs in CI.

## Evaluations and benchmarks

```bash
uv run python scripts/evaluate_deduplication.py
uv run python scripts/evaluate_readiness.py
uv run python scripts/benchmark.py
```

The evaluations use small labeled seed fixtures. They guard behavior; they do
not measure a discovery model. See [Benchmarks](docs/benchmarks.md) before
quoting any number.

## Agent Skills

Update the [Agent Skills](sufficiency-engine-skills/README.md) together with
any related API or behavior change, and keep `metadata.version` equal to the
package version. Their tests check format, links, scripts, and eval datasets;
they do not measure coding-agent performance.

## Pull requests

- Describe the user-visible impact, including any effect on readiness
  decisions, stored state, or recorded provenance.
- Add or update tests for every behavior change.
- Update the affected pages under [`docs/`](docs) and the
  [changelog](CHANGELOG.md).
- Make sure formatting, lint, type checks, tests, the strict docs build, and
  the diagram check pass.

## Releases

Releases are manual and performed by the maintainer. There is no publishing
workflow. The checklist is in [Releasing](docs/project/releasing.md).

## Security reports

Do not report vulnerabilities in public issues. Follow [SECURITY.md](SECURITY.md).
