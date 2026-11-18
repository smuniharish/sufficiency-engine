# Provenance

Sufficiency Engine uses AGXAI for every provenance responsibility: evidence,
decisions, attribution, lineage relationships, and explainability. It adds
only the mapping from an assessment to AGXAI's public models. For the
user-facing guide, see [Provenance](../guide/concepts/provenance.md).

![Provenance delivery through the audit outbox](../assets/diagrams/provenance-flow.png){ .diagram }

## Mapping

| Assessment | AGXAI |
| --- | --- |
| Session scope | `ExecutionContext` with the application, tenant, `graph_id="sufficiency-engine"`, the run ID, and the session ID as the thread |
| Assessment run | `Execution`, plus `ExecutionStartedEvent` and `ExecutionCompletedEvent` or `ExecutionFailedEvent` |
| Task input, accepted answers, approvals, source references | `Evidence` of type `STATE`, with an opaque `SourceReference` |
| Pending or terminal outcome | `Decision` of type `CUSTOM` with the selected action and counts |
| Evidence considered for the decision | `ProvenanceLink` with relation `considered` |

The executions, events, and links are written to the AGXAI `ProvenanceStore`.
The evidence and decision are recorded through `XAIRuntime.record_artifact`,
which delivers them to the registered `SemanticArchiveABC` plugin.

## Guarantees

- **Strict.** The runtime runs in AGXAI's `STRICT` failure mode, with a
  timeout per operation. Any failure raises `ProvenanceError`, and no ready
  result is returned without a delivered audit record.
- **Sanitized.** Records contain IDs, statuses, and counts. Raw task text,
  answers, and questions are never written to AGXAI.
- **Scoped.** Each intent is checked against the session scope before it is
  written; a mismatch is rejected.
- **Replayable.** IDs are stable, so the outbox can deliver an intent again
  after a crash or outage.

## What is deliberately not done

- No separate provenance or lineage store. Requirement lineage is part of the
  assessment result; AGXAI owns provenance relationships.
- No per-requirement source attribution. Source references are linked to the
  assessment decision, because a model quote cannot show which source supports
  a requirement.
- No exactly-once delivery across systems. The outbox gives at-least-once
  delivery; idempotent stores make it effectively once.
- No use of telemetry as audit. An optional AGXAI observer emits events for
  correlation, and its failures produce only a `telemetry_error` warning.
