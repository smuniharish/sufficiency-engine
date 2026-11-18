# Persistence

Standalone sessions are saved through `PersistenceABC` after every step. The
design goal is that **no two processes can advance the same assessment**, and
that a crash at any point leaves a state that can be resumed or reported
explicitly. For the user-facing guide, see
[Persistence and recovery](../guide/concepts/persistence.md).

![Session claims, fencing, and recovery](../assets/diagrams/persistence-recovery.png){ .diagram }

## Concurrency contract

`execute` holds an exclusive, expiring claim while it advances a standalone
session. The persistence implementation must reject concurrent ownership,
expired or superseded claims, and writes based on stale state. This prevents
one worker from silently overwriting another worker's assessment.

## Audit delivery

An audit failure can occur after AGXAI accepted some records. A resumed
assessment may therefore deliver the same records again. Configure AGXAI
stores to handle repeated records with the same identifiers idempotently; the
library does not promise a distributed, exactly-once transaction.

## Interrupted callbacks

If an interaction or terminal notification may already have reached the
application, the engine reports the ambiguity and does not replay the callback
automatically. Resume with an explicit response or handle the terminal result
as described in the recovery guide.

## Versioning

The stored envelope has `version=1`, and the assessment state has
`schema_version=1`. A resume with an unknown version is rejected before any
model call or write. See [Compatibility](../project/compatibility.md).

## Failure scenarios

| Scenario | Result |
| --- | --- |
| Store unavailable | `PersistenceError`; nothing is acted on |
| Crash after preparing the audit intent | Resume delivers it |
| Crash after dispatching a question | Resume reports `interaction_ambiguous` |
| Lease expires mid-step | The next save is fenced off |
| Corrupt or unknown stored state | `SerializationError` |
