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

::: sufficiency_engine.engine.SufficiencyEngine

::: sufficiency_engine.config.EngineConfig

::: sufficiency_engine.config.Limits