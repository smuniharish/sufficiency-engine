"""Optional OpenTelemetry spans and low-cardinality metrics."""

from __future__ import annotations

import time

from opentelemetry.metrics import MeterProvider
from opentelemetry.trace import Status, StatusCode, TracerProvider

from ..telemetry import Observation


class OpenTelemetryObserver:
    """Record sanitized engine observations using application-owned providers.

    This class does not configure global providers, exporters, network access,
    or shutdown. Pass ``observe`` as the engine's ``telemetry_call`` and
    configure AGXAI's own observability provider separately on ``AGXAIAudit``.
    """

    def __init__(self, *, tracer_provider: TracerProvider, meter_provider: MeterProvider) -> None:
        self.tracer = tracer_provider.get_tracer("sufficiency_engine")
        meter = meter_provider.get_meter("sufficiency_engine")
        self.assessments = meter.create_counter(
            "sufficiency.assessments", description="Terminal assessment outcomes"
        )
        self.retries = meter.create_counter(
            "sufficiency.model.retries", description="Model retries"
        )
        self.audit_failures = meter.create_counter(
            "sufficiency.provenance.failures", description="Required AGXAI audit failures"
        )
        self.duration = meter.create_histogram(
            "sufficiency.assessment.duration", unit="s", description="Assessment duration"
        )

    def observe(self, event: Observation) -> None:
        """Create a span and applicable metrics without recording input or answers."""
        end = time.time_ns()
        start = max(0, end - int(event.duration_seconds * 1_000_000_000))
        attributes = {
            "sufficiency.operation": event.operation,
            "sufficiency.outcome": event.outcome,
            "sufficiency.assessment_id": str(event.assessment_id),
            "agxai.run_id": str(event.run_id),
        }
        span = self.tracer.start_span(
            f"sufficiency.{event.operation}", start_time=start, attributes=attributes
        )
        if event.decision_id is not None:
            span.set_attribute("agxai.decision_id", str(event.decision_id))
        if event.evidence_ids:
            span.set_attribute("agxai.evidence_ids", [str(item) for item in event.evidence_ids])
        if event.link_ids:
            span.set_attribute("agxai.link_ids", [str(item) for item in event.link_ids])
        if event.outcome == "failed":
            span.set_status(Status(StatusCode.ERROR))
        span.end(end_time=end)
        if event.operation == "assessment":
            self.assessments.add(1, {"outcome": event.outcome})
            self.duration.record(event.duration_seconds, {"outcome": event.outcome})
        elif event.operation == "model_retry":
            self.retries.add(1)
        elif event.operation == "provenance" and event.outcome == "failed":
            self.audit_failures.add(1)
