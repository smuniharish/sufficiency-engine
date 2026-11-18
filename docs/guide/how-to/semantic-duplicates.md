# Detect semantic duplicates

Without an embedding model, the engine removes only exact duplicate questions
for the same requirement slot. An optional `EmbeddingModelABC` adds semantic
duplicate **candidates**: they are reported as warnings so you can review
them, and questions are never removed on similarity alone.

## Implement the model

Return one finite, non-zero vector per text. Run blocking encoders in a worker
thread so they do not block the event loop:

```python
import asyncio

from sufficiency_engine import EmbeddingModelABC, SufficiencyEngine


class LocalEmbedding(EmbeddingModelABC):
    def __init__(self, encoder):
        self.encoder = encoder

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = await asyncio.to_thread(self.encoder.encode, texts)
        return [[float(value) for value in vector] for vector in vectors]


engine = SufficiencyEngine(model_call=model_call, embedding_model=LocalEmbedding(encoder))
```

`encoder` is any local or hosted embedding model your application is allowed
to use. The call is bounded by `callback_timeout_seconds`.

## What the engine does with the vectors

| Situation | Result |
| --- | --- |
| Two questions for compatible slots have similar wording and vectors | A `potential_duplicate` warning; both questions are kept |
| The model raises, times out, or returns empty, non-finite, zero, or mismatched vectors | An `embedding_unavailable` warning; lexical matching continues |
| Two questions are exactly the same after normalization, for the same slot | The duplicate is removed, with or without embeddings |

Similar wording is not the same meaning: "deploy to production" and "do not
deploy to production" are close in both text and vector space, which is why
candidates are only reported.

## Try a real model

The [BGE-M3 example](../../examples/bge-m3.md) runs a local BGE-M3 model on
the CPU, offline, and shows the lexical fallback. Evaluate your own model on
the labeled fixture before relying on its warnings; see
[Evaluate a discovery model](evaluate-discovery.md#evaluate-question-deduplication).
