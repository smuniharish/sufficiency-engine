# OpenTelemetry

`OpenTelemetryObserver` turns engine observations into OpenTelemetry spans and
metrics using providers you configure. It never configures global providers,
exporters, or network access.

```bash
pip install "sufficiency-engine[observability]"
```

## Configure

```python
from sufficiency_engine import AGXAIAudit, SufficiencyEngine
from sufficiency_engine.integrations.opentelemetry import OpenTelemetryObserver

observer = OpenTelemetryObserver(
    tracer_provider=tracer_provider,
    meter_provider=meter_provider,
)
engine = SufficiencyEngine(
    model_call=model_call,
    telemetry_call=observer.observe,
    audit=AGXAIAudit(observer=agxai_observability),
)
```

`tracer_provider` and `meter_provider` are your OpenTelemetry SDK providers.
`agxai_observability` is optional: an AGXAI observability provider, such as
AGXAI's `OpenTelemetryObservability`, that emits AGXAI's own execution events.

## What is recorded

Each observation becomes a span named `sufficiency.<operation>`, for the
`assessment`, `model`, `model_retry`, `policy`, `clarification`, and
`provenance` operations. Spans carry:

| Attribute | Value |
| --- | --- |
| `sufficiency.operation` | The operation |
| `sufficiency.outcome` | `ok`, `failed`, `retry`, or the terminal status |
| `sufficiency.assessment_id` | The assessment ID |
| `agxai.run_id` | The AGXAI run ID |
| `agxai.decision_id`, `agxai.evidence_ids`, `agxai.link_ids` | AGXAI record IDs, when present |

Failed operations set the span status to `ERROR`.

| Metric | Type | Attributes |
| --- | --- | --- |
| `sufficiency.assessments` | Counter | `outcome` |
| `sufficiency.assessment.duration` | Histogram, seconds | `outcome` |
| `sufficiency.model.retries` | Counter | None |
| `sufficiency.provenance.failures` | Counter | None |

Task text, answers, questions, and evidence quotes are never recorded.
Assessment and AGXAI IDs appear only on spans, never as metric attributes,
which keeps metric cardinality low.

## Failure behavior

A failing `telemetry_call` or AGXAI observer adds a `telemetry_error` warning
and never changes the assessment outcome. Telemetry is for correlation and
operations; it is not the audit record. See [Provenance](../guide/concepts/provenance.md).

## Example

The [observability example](../examples/observability.md) exports traces over
OTLP and metrics to Prometheus, propagates trace context to a child process,
and recovers from an illustrative audit failure.
