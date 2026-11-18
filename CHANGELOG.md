# Changelog

## Unreleased

- Add async task-readiness assessment, deterministic policy, clarification,
  session recovery, and strict AGXAI provenance.
- Add optional LangGraph and OpenTelemetry integrations and offline examples.
- Fix stale-answer readiness on unresolved reassessment; require explicit
  superseding lineage for changed requirement meaning or answer contracts.
- Bound malformed standalone/LangGraph responses by the clarification budget.
- Keep task-level source references without asserting per-requirement support.
- Add repository-distributed usage/extension Agent Skills, labeled evaluation
  tools, lifecycle properties, storage conformance checks, and PostgreSQL CI.
- Document pre-1.0 API/state compatibility and deployment acceptance boundaries.
- Add Mermaid diagram sources under `diagrams/` with rendered images, a
  renderer, and a CI staleness check.
- Restructure the documentation into getting started, user guide (concepts,
  how-to guides, troubleshooting), integrations, examples, architecture, Agent
  Skills, security, benchmarks, API reference, and project pages.
- Add `examples/quickstart.py`, kept identical to the README and documentation
  quickstarts by tests, and `scripts/benchmark.py`.
- Add an SQLite storage template to the extension skill, eval starting
  projects, balanced trigger queries, and a skills validation guide.
- Add `examples/openai_compatible.py`, an adapter for any OpenAI-compatible
  chat completions endpoint, opt-in live model tests (`pytest -m live`), and
  `scripts/run_live_evaluation.py`, with an optional CI job keyed on secrets.
- Tighten the discovery prompt: conventional details are optional, and missing
  information the user can supply is asked rather than blocked. Measured live
  readiness rose from 21/24 to 40/40 runs.
- Add `scripts/run_postgres_recovery.py`, which runs the PostgreSQL recovery
  test locally against a disposable Podman or Docker container.
- Record coding-agent evaluations of both Agent Skills, with and without the
  skill.
- Add the author email, keywords, classifiers, and documentation, changelog,
  and issue URLs to the package metadata; document installation from PyPI.
