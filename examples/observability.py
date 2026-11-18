"""Export sanitized local traces and metrics, including cross-process propagation."""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import uuid4

from agxai import Evidence, ExecutionContext, OpenTelemetryObservability
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from prometheus_client import start_http_server

from sufficiency_engine import AGXAIAudit, AssessmentStatus, SufficiencyEngine
from sufficiency_engine.exceptions import TransientModelError
from sufficiency_engine.integrations.opentelemetry import OpenTelemetryObserver
from sufficiency_engine.provenance import InMemorySemanticArchive


class FailOnceArchive(InMemorySemanticArchive):
    """Illustrate recoverable audit failure without discarding provenance."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_once = True

    async def record(self, artifact):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("illustrative archive failure")
        await super().record(artifact)


async def assess(tracer_provider, meter_provider, role: str) -> None:
    observer = OpenTelemetryObserver(tracer_provider=tracer_provider, meter_provider=meter_provider)
    audit = AGXAIAudit(
        archive=FailOnceArchive(),
        observer=OpenTelemetryObservability(tracer_provider=tracer_provider),
    )
    attempts = 0

    async def model(_messages):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TransientModelError("illustrative transient failure")
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
    source_id = uuid4()
    failed = await engine.execute(
        input="Deploy on Linux.", session_id=f"telemetry-{role}", source_references=(source_id,)
    )
    assert failed.status is AssessmentStatus.FAILED
    recovered = await engine.execute(
        input="Deploy on Linux.", session_id=failed.session_id, resume=True
    )
    assert recovered.sufficient and recovered.provenance is not None
    context = ExecutionContext(
        application_id=engine.application_id,
        tenant_id=engine.tenant_id,
        graph_id="sufficiency-engine",
        run_id=recovered.provenance.run_id,
        thread_id=recovered.session_id,
    )
    decision_id = recovered.provenance.decision_ids[-1]
    parents = await audit.store.parents(str(decision_id), context=context)
    artifacts = await audit.archive.list_run(context=context)
    assert {link.source_id for link in parents} == {
        str(evidence_id) for evidence_id in recovered.provenance.evidence_ids
    }
    assert any(
        isinstance(artifact, Evidence) and str(artifact.source.source_id) == str(source_id)
        for artifact in artifacts
    )
    print(
        f"{role}: recovered audited assessment {recovered.assessment_id}; "
        f"decision {decision_id}; {len(parents)} AGXAI evidence links",
        flush=True,
    )


async def main(args) -> None:
    resource = Resource.create({"service.name": "sufficiency-engine-example"})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=args.otlp_endpoint, timeout=5))
    )
    readers = [] if args.child else [PrometheusMetricReader()]
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    server = None
    if not args.child:
        server, _thread = start_http_server(args.prometheus_port, addr=args.bind)
        print(f"METRICS_PORT={server.server_port}", flush=True)
    tracer = tracer_provider.get_tracer("sufficiency-example")
    propagator = TraceContextTextMapPropagator()
    context = propagator.extract({"traceparent": args.traceparent}) if args.traceparent else None
    try:
        with tracer.start_as_current_span(
            "example.child" if args.child else "example.parent", context=context
        ) as span:
            print(f"TRACE_ID={span.get_span_context().trace_id:032x}", flush=True)
            await assess(tracer_provider, meter_provider, "child" if args.child else "parent")
            if not args.child:
                carrier: dict[str, str] = {}
                propagator.inject(carrier)
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    __file__,
                    "--child",
                    "--otlp-endpoint",
                    args.otlp_endpoint,
                    "--traceparent",
                    carrier["traceparent"],
                )
                if await process.wait() != 0:
                    raise RuntimeError("telemetry child process failed")
        if not tracer_provider.force_flush(timeout_millis=10_000):
            raise RuntimeError("trace provider did not flush")
        if not args.child:
            await asyncio.sleep(args.wait)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        meter_provider.shutdown()
        tracer_provider.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otlp-endpoint", required=True, help="Explicit OTLP HTTP traces endpoint")
    parser.add_argument("--prometheus-port", type=int, default=0)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--wait", type=float, default=5.0)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--traceparent")
    asyncio.run(main(parser.parse_args()))
