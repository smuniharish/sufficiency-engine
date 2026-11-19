# Engine

`SufficiencyEngine` runs an assessment: it discovers requirements through your
model, applies the readiness policy, asks for clarification, and records every
decision through AGXAI. Settings are validated into an `EngineConfig`, and
`Limits` bounds untrusted input. See [Configuration](../getting-started/configuration.md)
for every option.

```python
from sufficiency_engine import Limits, SufficiencyEngine

engine = SufficiencyEngine(
    model_call=model_call,
    interrupt_call=ask_user,
    max_iterations=3,
    limits=Limits(max_questions=8),
)
result = await engine.execute(input="Deploy the billing service.")
```

For a non-interactive snapshot, use `await engine.execute(input=task,
preview_only=True)`. It returns the same `AssessmentResult`, including readiness,
blocking questions, and useful optional questions with their reasons. Neither
interaction nor terminal callbacks run, and no resumable session is saved.
Keep `result.preview_run_id` and `result.session_id` for explicit
`delete_preview_audit` cleanup, even when audit delivery fails.
See [Question previews](../guide/concepts/clarification.md#preview-questions-without-requesting-answers)
for policy consequences, failure handling, and remaining I/O.

::: sufficiency_engine.engine.SufficiencyEngine

::: sufficiency_engine.config.EngineConfig

::: sufficiency_engine.config.Limits