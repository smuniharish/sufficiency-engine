# Provenance and embeddings

`AGXAIAudit` records every assessment decision through AGXAI in strict mode.
Its semantic archive keeps the AGXAI evidence and decision models; implement
`SemanticArchiveABC` to keep them across restarts. `EmbeddingModelABC` is the
optional extension point for duplicate-question warnings. See
[Provenance](../architecture/provenance.md) and
[Detect semantic duplicates](../guide/how-to/semantic-duplicates.md).

```python
from sufficiency_engine import AGXAIAudit, SufficiencyEngine

engine = SufficiencyEngine(
    model_call=model_call,
    audit=AGXAIAudit(store=provenance_store, archive=semantic_archive),
)
```

::: sufficiency_engine.provenance.AGXAIAudit

::: sufficiency_engine.provenance.SemanticArchiveABC

::: sufficiency_engine.provenance.InMemorySemanticArchive

::: sufficiency_engine.embedding.EmbeddingModelABC