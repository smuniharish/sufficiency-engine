# Dependency audit

Direct dependencies declared in `pyproject.toml` were checked against PyPI and
the upstream project metadata on **2026-11-18**. The lockfile was refreshed
after the audit with `uv lock --upgrade`. Versions below describe direct
dependencies only; `uv.lock` records their resolved transitive dependencies.

All packages with a stable release were selected at the latest stable version
allowed by the existing compatibility bounds, except where noted. PyPI project
pages link to each distribution's metadata and source repository.

## Build and runtime dependencies

| Distribution | Role | Before | Latest stable on PyPI | Selected | Decision |
| --- | --- | ---: | ---: | ---: | --- |
| [`uv-build`](https://pypi.org/project/uv-build/) | Build backend | `>=0.12,<0.14` | 0.13.9 | 0.13.9 | Raise the minimum to the latest compatible stable release. |
| [`agxai`](https://pypi.org/project/agxai/) | Core provenance | 1.0.2 | 1.0.3 | 1.0.3 | Upgrade; Python 3.12+ and compatible 1.x API. |
| [`pydantic`](https://pypi.org/project/pydantic/) | Core models | 2.14.3 | 2.14.3 | 2.14.3 | Already current within `<3`. |
| [`rapidfuzz`](https://pypi.org/project/rapidfuzz/) | Core matching | 3.14.6 | 3.14.6 | 3.14.6 | Already current within `<4`. |
| [`langgraph`](https://pypi.org/project/langgraph/) | Optional integration and dev | 1.2.22 | 1.2.22 | 1.2.22 | Raise the supported minimum to the current compatible release. |
| [`opentelemetry-api`](https://pypi.org/project/opentelemetry-api/) | Optional observability | 1.45.2 | 1.45.2 | 1.45.2 | Already current within `<2`. |

## Optional examples and integrations

| Distribution | Role | Before | Latest stable on PyPI | Selected | Decision |
| --- | --- | ---: | ---: | ---: | --- |
| [`FlagEmbedding`](https://pypi.org/project/FlagEmbedding/) | Local BGE example | 1.4.2 | 1.4.2 | 1.4.2 | Already current; PyPI does not specify `Requires-Python`, so this optional model stack is not part of the core Python support claim. |
| [`langgraph-checkpoint-postgres`](https://pypi.org/project/langgraph-checkpoint-postgres/) | PostgreSQL integration checks | 3.2.1 | 3.2.1 | 3.2.1 | Already current within `<4`. |
| [`opentelemetry-exporter-otlp-proto-http`](https://pypi.org/project/opentelemetry-exporter-otlp-proto-http/) | Local observability integration | 1.45.2 | 1.45.2 | 1.45.2 | Already current within `<2`. |
| [`opentelemetry-exporter-prometheus`](https://pypi.org/project/opentelemetry-exporter-prometheus/) | Local Prometheus example | 0.66b2 | No stable release | 0.66b2 | Retained as an optional OpenTelemetry beta; PyPI classifies the exporter as Beta. |
| [`prometheus-client`](https://pypi.org/project/prometheus-client/) | Local Prometheus example | 0.26.0 | 0.26.0 | 0.26.0 | Already current. |
| [`psycopg`](https://pypi.org/project/psycopg/) | PostgreSQL recovery checks | 3.3.9 | 3.3.9 | 3.3.9 | Already current within `<4`. |
| [`openai`](https://pypi.org/project/openai/) | Optional live examples | 2.54.0 | 3.55.0 | 2.54.0 | Keep `<3`: OpenAI's [3.0.0 release](https://github.com/openai/openai-python/releases/tag/v3.0.0) changes the default HTTP client to HTTPX2 and removes the implicit `httpx` install. The examples use the v2 HTTP client behavior. |
| [`truststore`](https://pypi.org/project/truststore/) | Optional TLS example | 0.10.5 | 0.10.5 | 0.10.5 | Already current within `<1`. |

## Documentation and development dependencies

| Distribution | Role | Before | Latest stable on PyPI | Selected | Decision |
| --- | --- | ---: | ---: | ---: | --- |
| [`griffe-pydantic`](https://pypi.org/project/griffe-pydantic/) | API docs | 1.3.2 | 1.3.2 | 1.3.2 | Already current within `<2`. |
| [`mkdocstrings-python`](https://pypi.org/project/mkdocstrings-python/) | API docs | 2.0.11 | 2.0.11 | 2.0.11 | Raise the supported minimum to the current compatible release. |
| [`zensical`](https://pypi.org/project/zensical/) | Documentation site | 0.1.2 | 0.1.2 | 0.1.2 | Already current within `<0.2`. |
| [`hypothesis`](https://pypi.org/project/hypothesis/) | Property tests | 6.170.15 | 6.170.15 | 6.170.15 | Already current. |
| [`langchain-core`](https://pypi.org/project/langchain-core/) | Integration tests | 1.8.1 | 1.8.2 | 1.8.2 | Raise the supported minimum and lock to the current compatible release. |
| [`opentelemetry-sdk`](https://pypi.org/project/opentelemetry-sdk/) | Observability checks | 1.45.2 | 1.45.2 | 1.45.2 | Already current within `<2`. |
| [`packaging`](https://pypi.org/project/packaging/) | Distribution checks | 26.3 | 26.3 | 26.3 | Already current. |
| [`pyrefly`](https://pypi.org/project/pyrefly/) | Type checking | 1.4.1 | 1.4.1 | 1.4.1 | Already current. |
| [`pytest`](https://pypi.org/project/pytest/) | Test runner | 9.2.0 | 9.2.0 | 9.2.0 | Already current. |
| [`pytest-asyncio`](https://pypi.org/project/pytest-asyncio/) | Async tests | 1.5.0 | 1.5.0 | 1.5.0 | Already current. |
| [`pytest-cov`](https://pypi.org/project/pytest-cov/) | Coverage checks | 7.1.0 | 7.1.0 | 7.1.0 | Already current. |
| [`ruff`](https://pypi.org/project/ruff/) | Lint and format | 0.17.5 | 0.17.5 | 0.17.5 | Already current. |
| [`skills-ref`](https://pypi.org/project/skills-ref/) | Skill validation | 0.1.1 | 0.1.1 | 0.1.1 | Already current within `<1`. |

## Maintenance and compatibility notes

- PyPI reports stable releases for all direct packages except the Prometheus
  exporter, which remains a beta release in the OpenTelemetry project. Its
  dependency is confined to the optional local-integration group.
- Comparing the official AGXAI 1.0.2 and 1.0.3 wheels showed no runtime API or
  behavior changes; the Python-source differences were docstring-only.
- The reviewed PyPI metadata and project release histories show recent
  maintenance for the declared dependencies. Release recency is evidence of
  publication activity, not a guarantee of support or security.
- The optional BGE example depends on a large model/runtime stack. `FlagEmbedding`
  has no PyPI `Requires-Python` metadata; verify PyTorch and platform support
  separately before using that example on a particular Python version.
- The OpenAI SDK's latest stable major release is outside the declared `<3`
  range. The existing cap is intentional until the documented custom-client
  example and live integration are migrated to HTTPX2.
- Core runtime compatibility remains Python 3.12+; none of the optional
  documentation, testing, live-model, or database groups is a core runtime
  dependency.
