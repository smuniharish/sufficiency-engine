# Integrations

Optional integrations, imported from their own modules. Install them with the
`langgraph` and `observability` extras. See [LangGraph](../integrations/langgraph.md)
and [OpenTelemetry](../integrations/opentelemetry.md).

```python
from sufficiency_engine.integrations.langgraph import build_assessment_graph
from sufficiency_engine.integrations.opentelemetry import OpenTelemetryObserver
```

## LangGraph

::: sufficiency_engine.integrations.langgraph.build_assessment_graph

::: sufficiency_engine.integrations.langgraph.AssessmentGraphState

## OpenTelemetry

::: sufficiency_engine.integrations.opentelemetry.OpenTelemetryObserver

::: sufficiency_engine.telemetry.Observation