# Optional duplicate-candidate embeddings

Subclass the public `EmbeddingModelABC` and implement:

```python
async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Return one nonempty, equal-dimension vector per input. Values must be numeric,
finite, and have a nonzero finite norm. The engine validates the shape and
cosine range. Do not truncate texts/vectors or silently replace errors with
plausible vectors.

Keep blocking inference off the event loop, for example with `asyncio.to_thread`.
Synchronous work cannot be forcibly stopped by cancelling its waiting task.
The application selects the model and owns its memory, privacy, and licensing.
Do not install/download a model implicitly. Core usage requires no embedding
library or vector database.

Failures yield a structured `embedding_unavailable` warning and conservative
lexical fallback. Similarity produces candidate warnings, not permission to
drop distinct answer slots or follow-ups. Use labeled domain-specific fixtures
and report false positives/negatives. The repository's BGE-M3 example supports
explicit local offline weights; it is not a mandatory inference service.
