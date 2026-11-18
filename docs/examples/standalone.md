# Standalone

Three standalone assessments driven by a scripted `langchain-core` chat model:

1. A task that already contains everything it needs is ready immediately.
2. A task with a missing platform is clarified through `interrupt_call` and
   then reassessed.
3. A task with a low-risk, reversible assumption becomes ready only after the
   assumption is explicitly approved, with `allow_assumptions=True`.

```bash
uv sync --extra langgraph
uv run python examples/standalone.py
```

<!-- fmt: off -->
```python title="examples/standalone.py"
--8<-- "examples/standalone.py"
```
<!-- fmt: on -->

Output:

```text
Standalone: complete, clarified, and explicitly approved tasks are audited.
```

The scripted model stands in for a real one. Replace `scripted_model` with your
own `model_call`.
