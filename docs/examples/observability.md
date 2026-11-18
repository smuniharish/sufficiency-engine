# Observability

Exports engine spans over OTLP and metrics to Prometheus, propagates trace
context to a child process, and shows a transient model failure and an audit
failure being recovered.

Each process:

1. Retries a transient model failure once.
2. Fails one AGXAI archive write, so the first `execute` returns `failed` with
   `provenance_error`.
3. Resumes the session, which delivers the same audit records, and checks the
   AGXAI evidence links and the source reference in the archive.

```bash
uv sync --extra observability --group local-integration
uv run python examples/observability.py \
  --otlp-endpoint http://127.0.0.1:4318/v1/traces \
  --prometheus-port 19464
```

`--otlp-endpoint` is required and must point to an OTLP HTTP traces receiver
that you run, such as an OpenTelemetry Collector or Jaeger. The parent process
serves metrics on `--prometheus-port`, bound to `127.0.0.1` by default, for
`--wait` seconds. The repository's `examples/prometheus.yml` scrapes port
19464.

The output reports the trace ID, the metrics port, and, for the parent and the
child, the recovered assessment and its number of AGXAI evidence links.

<!-- fmt: off -->
```python title="examples/observability.py"
--8<-- "examples/observability.py"
```
<!-- fmt: on -->

See [OpenTelemetry](../integrations/opentelemetry.md) for the attributes and
metrics.
