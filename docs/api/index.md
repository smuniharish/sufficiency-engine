# API reference

Generated from the docstrings of the public API. The classes you use day to day
are importable from the top-level `sufficiency_engine` package. Exceptions,
supporting record types, and the optional integrations are imported from their
own modules. Each entry below shows the module where the class is defined.

| Page | Contents |
| --- | --- |
| [Engine](engine.md) | `SufficiencyEngine`, `EngineConfig`, `Limits` |
| [Models](models.md) | Assessment results, requirements, clarification payloads, answers, assumptions, and enumerations |
| [Storage](storage.md) | `PersistenceABC`, `InMemoryPersistence`, `SessionScope`, `SessionClaim`, `StoredSession` |
| [Provenance and embeddings](provenance.md) | `AGXAIAudit`, `SemanticArchiveABC`, `InMemorySemanticArchive`, `EmbeddingModelABC` |
| [Integrations](integrations.md) | Optional `build_assessment_graph`, `AssessmentGraphState`, `OpenTelemetryObserver`, and the `Observation` record |
| [Errors](errors.md) | `SufficiencyError` and its subclasses, each with a stable `code` |

## Stability

- The public API is everything listed in this reference. Modules and names that
  start with an underscore are private and may change at any time.
- Session snapshots are versioned contracts. See
  [Compatibility](../project/compatibility.md) for how versions and migrations
  are handled.
- Breaking changes are listed in the [changelog](../project/changelog.md).