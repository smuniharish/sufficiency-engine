# Installation

Sufficiency Engine requires Python 3.12 or later. Its runtime dependencies are
[AGXAI](https://agxai.readthedocs.io/), Pydantic v2, and RapidFuzz. No model
provider, agent framework, vector database, or network service is installed or
selected for you.

## From PyPI

The distribution is `sufficiency-engine` and the import is `sufficiency_engine`:

```bash
pip install sufficiency-engine
```

With [uv](https://docs.astral.sh/uv/):

```bash
uv add sufficiency-engine
```

## From source

To run the examples and tests, install from a clone of the repository:

```bash
git clone https://github.com/smuniharish/sufficiency-engine.git
cd sufficiency-engine
uv sync
uv run python examples/quickstart.py
```

## Optional extras

| Extra | Adds | Use it for |
| --- | --- | --- |
| `langgraph` | `langgraph` | A checkpointed readiness subgraph at a graph's task entry; see [LangGraph](../integrations/langgraph.md) |
| `observability` | `agxai[otel]`, `opentelemetry-api` | Engine spans and metrics through your OpenTelemetry providers; see [OpenTelemetry](../integrations/opentelemetry.md) |

```bash
pip install "sufficiency-engine[langgraph]"
pip install "sufficiency-engine[langgraph,observability]"
```

To call a hosted model, install its client yourself, for example
`pip install openai`. See [OpenAI-compatible models](../examples/openai-compatible.md).

## Development groups

These groups exist only in the repository. They support the examples and tests
and are never runtime dependencies.

| Group | Contents |
| --- | --- |
| `dev` | Test, lint, and type-check tools; installed by default |
| `docs` | Zensical and mkdocstrings for this site |
| `bge` | `FlagEmbedding` for the local [BGE-M3 example](../examples/bge-m3.md) |
| `local-integration` | PostgreSQL, OTLP, and Prometheus clients for the [observability](../examples/observability.md) and [PostgreSQL recovery](../examples/postgres-recovery.md) examples |
| `live` | `openai` and `truststore` for the [OpenAI-compatible example](../examples/openai-compatible.md) and the live model tests |

## Check the installation

```bash
python -c "import sufficiency_engine; print(sufficiency_engine.SufficiencyEngine)"
```

Continue with the [Quickstart](quickstart.md).
