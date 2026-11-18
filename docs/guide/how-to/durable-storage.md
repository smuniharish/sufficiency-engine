# Use durable storage

The defaults keep sessions and provenance in memory. To survive a restart and
keep an audit trail, configure three application-owned stores:

| Store | Contract | Keeps |
| --- | --- | --- |
| Session store | `PersistenceABC` | Standalone assessment sessions |
| AGXAI provenance store | AGXAI `ProvenanceStore` | Executions, canonical events, and links |
| Semantic archive | `SemanticArchiveABC` | AGXAI evidence and decision artifacts |

```python
from sufficiency_engine import AGXAIAudit, SufficiencyEngine

engine = SufficiencyEngine(
    model_call=model_call,
    interrupt_call=interrupt_call,
    persistence=MySessionStore(pool),
    audit=AGXAIAudit(store=MyProvenanceStore(pool), archive=MySemanticArchive(pool)),
    application_id="deployments",
    tenant_id=tenant_id,
)
```

`MySessionStore`, `MyProvenanceStore`, and `MySemanticArchive` are your
implementations. For LangGraph, use a durable checkpointer instead of a session
store, together with the two AGXAI stores.

## Implement the session store

Subclass `PersistenceABC` and implement its six methods; the contract is in
[Persistence and recovery](../concepts/persistence.md#storage). In a SQL
database, that usually means:

- One row per `(application_id, tenant_id, session_id)`, with the JSON state,
  the envelope `version`, an integer `revision`, the claim owner, a fencing
  token, and a lease expiry.
- `acquire` takes the claim in one atomic statement when there is no claim or
  the lease has expired, and increments the fencing token.
- `save` and `delete` use compare-and-swap on the revision **and** the fencing
  token, inside one transaction, and raise `SessionConflictError` on mismatch.
- `load` returns a copy and never reads across scopes.

## Implement the semantic archive

Subclass `SemanticArchiveABC`. It is an AGXAI plugin: `record(artifact)`
receives each evidence and decision artifact, and `get`, `list_run`, and
`delete_run` read and delete them within an AGXAI `ExecutionContext`. Writes
must be idempotent by artifact ID and scoped by application, tenant, and run.

## Check the adapters

The `sufficiency-engine-extend` [Agent Skill](../../agent-skills/sufficiency-engine-extend.md)
includes a contract checker. Point it at zero-argument factories that create
adapters for an **isolated test database**:

```bash
uv run python sufficiency-engine-skills/skills/sufficiency-engine-extend/scripts/check_extensions.py \
  --path . \
  --persistence myapp.storage:make_test_store \
  --archive myapp.storage:make_test_archive \
  --json
```

It checks scope isolation, revision conflicts, exclusive claims, fencing of
expired and stale writers, copy isolation, idempotent archive replay, and
deletion. It deletes only its own test records, but a broken adapter could
violate that, so never point it at production. Passing it does not prove crash
or hardware durability.

## Test a restart

The repository's [PostgreSQL recovery test](../../examples/postgres-recovery.md)
shows the full pattern across two processes: a durable LangGraph checkpointer,
AGXAI's example PostgreSQL store, and a test-only semantic archive. Run the
same kind of test against your own stores, then work through
[Validate a deployment](validate-deployment.md).
