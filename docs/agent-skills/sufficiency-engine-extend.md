# The sufficiency-engine-extend skill

The `sufficiency-engine-extend` skill teaches a coding agent to implement the
package's extension points against your own infrastructure. It covers:

- a durable `PersistenceABC` session store with atomic claims, fencing tokens,
  and revision checks;
- a `SemanticArchiveABC` that keeps AGXAI evidence and decisions across
  restarts;
- an optional `EmbeddingModelABC` for detecting duplicate clarification
  questions.

[:material-github: View on GitHub](https://github.com/smuniharish/sufficiency-engine/tree/main/sufficiency-engine-skills/skills/sufficiency-engine-extend){ .md-button }
[:material-download: Install](index.md#agentic-installation){ .md-button }

## When the agent uses it

The agent loads the skill when the task is to implement or review one of those
three contracts, or to fix an adapter that breaks them, such as a store that
accepts writes with a stale fencing token.

For ordinary integration, it hands over to
[sufficiency-engine](sufficiency-engine.md). It does not replace AGXAI
provenance, add a model provider, or build an agent executor or conversation
database.

## Workflow

```text
1. Read the contract reference: storage.md or embeddings.md
2. Implement the exported ABC with its exact signatures,
   starting from assets/sqlite_store.py for storage
3. check_extensions.py passes against an isolated test backend
4. Restart, ambiguous-write, backup, deletion, and concurrency tests
   pass against the real backend
5. Project tests and check_extensions.py pass again
```

When a promise fails, the agent reports it. It does not weaken a claim, drop an
audit, or fall back to memory to make a check pass.

## What's inside

```text
sufficiency-engine-extend/
├── SKILL.md                  # workflow and boundaries
├── references/
│   ├── storage.md            # session store and semantic archive promises
│   └── embeddings.md         # embedding model contract
├── scripts/
│   └── check_extensions.py   # contract checks for any store and archive
├── assets/
│   └── sqlite_store.py       # SQLite session store and semantic archive
└── evals/                    # task evals, input files, trigger queries
```

## The SQLite template

`assets/sqlite_store.py` implements both storage contracts with the Python
standard library. Every operation runs in one `BEGIN IMMEDIATE` transaction in
a worker thread, so claims, fencing tokens, and revisions are checked in the
same transaction as each write, across processes. The archive stores each AGXAI
artifact's model type with its JSON and rebuilds the real AGXAI model on read.

The template passes every contract check, and the repository's tests also run
an audited assessment through it. Adapt it to your database rather than
shipping it unchanged, and keep the hosts' clocks synchronized, since leases
use wall-clock time.

## The contract checker

`scripts/check_extensions.py` imports zero-argument factories you name and
checks seven promises against unique, disposable scopes:

| Check | Promise |
| --- | --- |
| `copy_and_tenant_isolation` | Sessions are copy-isolated and scoped by application, tenant, and session |
| `exclusive_claim_and_revision` | A second claim and a stale revision conflict |
| `stale_fence_and_revision_rejected` | A superseded claim and a stale revision cannot write |
| `expiry_recovery_and_deletion` | An expired claim is fenced off, and deletion works |
| `semantic_retention_and_replay` | AGXAI artifacts are kept, and replay is idempotent |
| `archive_copy_and_scope` | Archived artifacts are copy-isolated and scoped |
| `archive_deletion` | Deleting a run is complete and idempotent |

| Option | Effect |
| --- | --- |
| `--path` | Directory added to the import path for the factories |
| `--persistence MODULE:FACTORY` | Session store to check; defaults to the in-memory store |
| `--archive MODULE:FACTORY` | Semantic archive to check; defaults to the in-memory archive |
| `--json` | Print one JSON object; on failure it contains only the error type |

It exits with `0` when every check passes and `1` otherwise. Run it only
against isolated test storage. The factories are trusted application code, and
passing the checks does not prove production durability.