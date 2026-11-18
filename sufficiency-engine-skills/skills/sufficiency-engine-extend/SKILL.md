---
name: sufficiency-engine-extend
description: >-
  Use this skill when implementing or reviewing a PersistenceABC session
  backend, a SemanticArchiveABC for durable AGXAI artifacts, or an optional
  EmbeddingModelABC used by sufficiency-engine. Covers atomic claims, fencing,
  revision conflicts, scoped isolation, replay, and extension conformance.
  Do not use it for ordinary task-readiness integration (use sufficiency-engine),
  to replace AGXAI provenance, to add provider detection, or to build an agent
  executor or conversation database.
license: Apache-2.0
compatibility: >-
  Python 3.12+. Requires sufficiency-engine 1.x. Contract checks are offline
  with default in-memory factories. Explicit custom factories execute trusted
  application code and may access the configured isolated test backend.
metadata:
  version: "1.0.1"
---

# Extend application-owned storage and embeddings

Reuse existing host checkpointing and AGXAI implementations. Do not introduce
a second context store, default database, no-op provenance, or a provider SDK.
Use ABCs only at the existing extension boundaries.

## Workflow

1. Read the relevant contract reference before implementing:
   [storage.md](references/storage.md) or [embeddings.md](references/embeddings.md).
2. Implement the actual exported ABC, with the exact installed signatures.
   Keep application/tenant/session authorization in the host. To start from a
   working durable example, copy `assets/sqlite_store.py`: a standard-library
   SQLite `PersistenceABC` and `SemanticArchiveABC` with transactional claims,
   fencing, revision checks, and scoped AGXAI artifact storage. Adapt it to the
   application's database rather than shipping it unchanged.
3. For storage extensions, run `python scripts/check_extensions.py --json`
   from this skill directory. It checks `PersistenceABC` and
   `SemanticArchiveABC` only; test an `EmbeddingModelABC` through the public
   `SufficiencyEngine(embedding_model=...)` instead of private modules.
   Defaults exercise the real in-memory implementations. To test custom
   factories, select trusted zero-argument constructors explicitly:

   ```shell
   python scripts/check_extensions.py --path . --persistence myapp.storage:make_test_store --archive myapp.storage:make_test_archive --json
   ```

   The template passes the same checks:
   `python scripts/check_extensions.py --path assets --persistence sqlite_store:make_test_store --archive sqlite_store:make_test_archive`.

   Run against isolated test storage only. The checker creates unique scoped
   records and deletes them. It does not configure or certify production.
4. Test restart recovery, ambiguous writes, backups, deletion, and concurrent
   writers against the real backend as well. In-process conformance cannot
   prove durability or distributed atomicity.
5. Run project tests and the checker again. Report failed promises rather than
   weakening claims, dropping audits, or falling back to memory.

## Boundaries

- `PersistenceABC` stores versioned assessment snapshots, not provenance.
  LangGraph-owned sessions use the host checkpointer instead.
- `SemanticArchiveABC` stores actual AGXAI semantic models, not a replacement
  evidence/decision schema. A separate durable AGXAI `ProvenanceStore` is
  also required; consult AGXAI's extension guidance for that contract.
- `EmbeddingModelABC` is optional and proposes duplicate candidates only.
  Similarity cannot authorize readiness or discard legitimate follow-ups.
- Imported factories and callbacks are trusted executable application code;
  never select them from untrusted model output.
