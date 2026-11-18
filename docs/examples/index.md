# Examples

Every example lives in the repository's
[`examples/`](https://github.com/smuniharish/sufficiency-engine/tree/main/examples)
directory and runs offline unless noted. The first three run in the test
suite, so their output stays current.

| Example | Shows | Needs |
| --- | --- | --- |
| [Quickstart](quickstart.md) | One clarification round, end to end | Core package |
| [Standalone](standalone.md) | Complete tasks, clarification, and approved assumptions | `langgraph` extra, for its scripted `langchain-core` chat model |
| [Supervisor and workers](supervisor-worker.md) | A LangGraph task-entry gate in front of a multi-agent flow | `langgraph` extra |
| [BGE-M3 duplicates](bge-m3.md) | A real local embedding model for duplicate candidates | `bge` group and a downloaded model |
| [Observability](observability.md) | OTLP traces, Prometheus metrics, and audit recovery | `observability` extra and `local-integration` group |
| [PostgreSQL recovery](postgres-recovery.md) | Checkpoints and provenance surviving a process restart | Podman or Docker, or your own PostgreSQL |
| [OpenAI-compatible models](openai-compatible.md) | A real model through the chat completions API, with a console clarification loop | `openai` and an API key; calls the network |

From a clone, install everything the examples need with:

```bash
uv sync --extra langgraph --extra observability --group local-integration
```
