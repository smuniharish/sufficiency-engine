# Storage promises

Implement `PersistenceABC`'s async `acquire`, `renew`, `release`, `load`,
revision-checked `save`, and revision-checked `delete`. Acquire an expiring
exclusive claim atomically. Reject writes with expired/superseded fencing
tokens or stale revisions, in the same transaction as the write. A process-local
lock is not distributed atomicity.

Keys include trusted application, tenant, and session scope. Return copy-isolated
JSON-safe `StoredSession` values. Validate envelope/schema versions; do not
silently coerce an unknown version or use pickle. `load` absence is distinct
from a storage failure. Make connection/statement deadlines finite.

`SemanticArchiveABC` extends AGXAI's `XAIPlugin`, including `record`, `get`,
`list_run`, and `delete_run`. Persist AGXAI semantic model payloads and their
type. Upsert by application, tenant, run, artifact type, and stable artifact ID.
Reads and deletion must use the same scope and be isolated from returned-object
mutation. Retry the same stable IDs after ambiguous writes.

The archive alone is not the whole audit: configure a durable AGXAI provenance
store for executions, canonical events, and links. Required recording failures
must remain explicit recoverable failures. There is no cross-system
exactly-once guarantee.

The extension checker verifies local contract behavior. A real durability test
must terminate and restart processes and read the records back using new
connections. Use an isolated backend, not production user data. The repository
contains a PostgreSQL checkpoint/archive recovery test; it deliberately uses
optional database dependencies and a pinned AGXAI example store.
