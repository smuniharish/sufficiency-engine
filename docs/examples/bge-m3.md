# BGE-M3 duplicates

Runs the [BAAI BGE-M3](https://huggingface.co/BAAI/bge-m3) embedding model
locally on the CPU, through FlagEmbedding, as an `EmbeddingModelABC`. It
embeds two similar questions, checks that both are kept, and shows the
lexical fallback when the model fails.

!!! note "Setup"

    The model is not downloaded by the example. Download the BGE-M3 files to a
    local directory first, following the model's license and your
    organization's policy. The example sets the Hugging Face offline variables
    and loads the model with `trust_remote_code=False`.

```bash
uv sync --group bge
uv run python examples/bge_m3.py --model-dir /path/to/bge-m3
```

The output has this form, where `N` is the number of candidate warnings and
depends on the model files and runtime:

```text
BGE-M3: 2 x 1024 finite CPU embeddings; N candidate warnings.
Lexical fallback retained both questions and reported the model failure.
```

The first run loads a large model and can take minutes on a CPU.

<!-- fmt: off -->
```python title="examples/bge_m3.py"
--8<-- "examples/bge_m3.py"
```
<!-- fmt: on -->

See [Detect semantic duplicates](../guide/how-to/semantic-duplicates.md) for how
candidates are reported.
