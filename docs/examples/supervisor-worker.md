# Supervisor and workers

A LangGraph host graph puts the readiness subgraph at task entry, in front of a
supervisor, a researcher, a developer, and a tester that fix a real defect in a
temporary project.

```bash
uv sync --extra langgraph
uv run python examples/supervisor_worker.py
```

The flow:

1. The task "Fix the calculation in the sample project." is missing the
   expected result, so the subgraph interrupts with a question.
2. The example answers `5` with `Command(resume=...)`, and the task is
   reassessed as ready.
3. The workers fix `add` and run the project's unit tests. The example checks
   that ordinary worker steps never trigger another assessment.
4. A separate, new task is assessed explicitly with `engine.execute`.

<!-- fmt: off -->
```python title="examples/supervisor_worker.py"
--8<-- "examples/supervisor_worker.py"
```
<!-- fmt: on -->

Output:

```text
Clarification: What should add(3, 2) return? Answer: 5
Supervisor: the requested arithmetic fix was verified.
A separately created independent task was assessed explicitly.
```

Scripted `langchain-core` chat models stand in for the discovery and worker
models. See [LangGraph](../integrations/langgraph.md) for the integration
contract.
