from agxai import ObservabilityProvider, OpenTelemetryObservability
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, Sum
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sufficiency_engine import AGXAIAudit, SufficiencyEngine
from sufficiency_engine.exceptions import TransientModelError
from sufficiency_engine.integrations.opentelemetry import OpenTelemetryObserver


async def test_real_otel_spans_metrics_agxai_events_and_sanitized_correlation():
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    observer = OpenTelemetryObserver(tracer_provider=tracer_provider, meter_provider=meter_provider)
    audit = AGXAIAudit(observer=OpenTelemetryObservability(tracer_provider=tracer_provider))
    attempts = 0

    async def model(_messages):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TransientModelError("private transport detail")
        return {
            "requirements": [
                {
                    "key": "platform",
                    "description": "Deployment platform",
                    "classification": "mandatory",
                    "status": "available",
                    "evidence_quote": "Linux",
                    "necessity": "not_needed",
                    "reason": "The input states the platform.",
                }
            ]
        }

    engine = SufficiencyEngine(model_call=model, audit=audit, telemetry_call=observer.observe)
    tracer = tracer_provider.get_tracer("test-host")
    with tracer.start_as_current_span("host-task"):
        result = await engine.execute(input="Deploy Linux; token: veryprivate-secret")
    assert result.sufficient
    spans = exporter.get_finished_spans()
    names = {span.name for span in spans}
    assert {
        "host-task",
        "execution.started",
        "execution.completed",
        "sufficiency.model_retry",
        "sufficiency.model",
        "sufficiency.policy",
        "sufficiency.provenance",
        "sufficiency.assessment",
    }.issubset(names)
    host = next(span for span in spans if span.name == "host-task")
    assert host.context is not None
    for span in spans:
        assert span.context is not None
        assert span.context.trace_id == host.context.trace_id
    audit_span = next(span for span in spans if span.name == "sufficiency.provenance")
    assert audit_span.attributes is not None
    assert result.provenance is not None
    assert audit_span.attributes["agxai.decision_id"] == str(result.provenance.decision_ids[-1])
    assert "veryprivate-secret" not in repr([span.attributes for span in spans])
    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None
    metrics = {
        metric.name: metric
        for resource in metrics_data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }
    assessments = metrics["sufficiency.assessments"].data
    retries = metrics["sufficiency.model.retries"].data
    assert isinstance(assessments, Sum)
    assert isinstance(retries, Sum)
    assert assessments.data_points[0].value == 1
    assert retries.data_points[0].value == 1
    for metric in metrics.values():
        for point in metric.data.data_points:
            assert all("id" not in key for key in (point.attributes or {}))
    meter_provider.shutdown()
    tracer_provider.shutdown()


class FailingObserver(ObservabilityProvider):
    async def emit(self, event):
        raise RuntimeError("sensitive exporter details")


async def test_optional_telemetry_failure_is_a_warning_and_does_not_invalidate_audit():
    def broken_telemetry(_event):
        raise RuntimeError("sensitive callback details")

    async def model(_messages):
        return {
            "requirements": [
                {
                    "key": "platform",
                    "description": "Platform",
                    "classification": "mandatory",
                    "status": "available",
                    "evidence_quote": "Linux",
                    "reason": "Specified",
                }
            ]
        }

    result = await SufficiencyEngine(
        model_call=model,
        telemetry_call=broken_telemetry,
        audit=AGXAIAudit(observer=FailingObserver()),
    ).execute(input="Linux")
    assert result.sufficient
    assert result.provenance is not None
    assert any(warning.code == "telemetry_error" for warning in result.warnings)
    assert "sensitive" not in repr(result.warnings)
