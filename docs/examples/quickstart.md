# Quickstart example

An offline model and an `ask_user` callback walk one task through a full
clarification round: the platform is missing, the user answers, and the task
is reassessed as ready.

```bash
uv run python examples/quickstart.py
```

<!-- fmt: off -->
```python title="examples/quickstart.py"
--8<-- "examples/quickstart.py"
```
<!-- fmt: on -->

Output:

```text
Question: Which platform should the service be deployed on?
Status: sufficient
Sufficient: True
Clarification rounds: 1
  platform: available, blocking=False
Audited decisions: 2
```

The [Quickstart](../getting-started/quickstart.md) explains each step.
