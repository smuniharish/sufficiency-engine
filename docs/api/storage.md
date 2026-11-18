# Storage

Session storage for assessments that pause for clarification. The engine uses
`InMemoryPersistence` by default; implement `PersistenceABC` to keep sessions
across processes. LangGraph hosts use their checkpointer instead. See
[Persistence](../architecture/persistence.md) and
[Use durable storage](../guide/how-to/durable-storage.md).

```python
from sufficiency_engine import SufficiencyEngine

engine = SufficiencyEngine(model_call=model_call, persistence=MyDatabasePersistence(pool))
```

::: sufficiency_engine.persistence.PersistenceABC

::: sufficiency_engine.persistence.InMemoryPersistence

::: sufficiency_engine.persistence.SessionScope

::: sufficiency_engine.persistence.SessionClaim

::: sufficiency_engine.persistence.StoredSession