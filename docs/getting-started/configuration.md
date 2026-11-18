# Configuration

All configuration is passed to the `SufficiencyEngine` constructor, in code.
Every argument is keyword-only, and invalid values raise `ConfigurationError`
immediately.

```python
from sufficiency_engine import AGXAIAudit, Limits, SufficiencyEngine

engine = SufficiencyEngine(
    model_call=model_call,
    interrupt_call=interrupt_call,
    command_call=command_call,
    max_iterations=5,
    max_model_retries=2,
    require_optional=False,
    allow_assumptions=False,
    limits=Limits(max_input_bytes=65_536),
    persistence=persistence,
    audit=AGXAIAudit(store=store, archive=archive),
    application_id="deployments",
    tenant_id="acme",
)
```

The callbacks, `persistence`, `store`, and `archive` are application-owned
objects.

## Policy and budgets

| Argument | Default | Meaning |
| --- | --- | --- |
| `max_iterations` | `5` | Clarification, validation, and reassessment cycles. Initial discovery is not counted. Between 0 and 100. |
| `max_model_retries` | `2` | Extra attempts after a model failure marked transient, or a timeout. Between 0 and 10. |
| `require_optional` | `False` | Make unresolved optional requirements block too. |
| `allow_assumptions` | `False` | Allow low-risk, reversible assumptions that the host explicitly approves. |

## Limits

`Limits` bounds untrusted input and callback execution. Exceeding a limit is
reported as an error; data is never silently truncated.

| Field | Default | Bounds |
| --- | ---: | --- |
| `max_input_bytes` | 65,536 | UTF-8 bytes of task text |
| `max_requirements` | 256 | Requirements per assessment |
| `max_dependency_edges` | 2,048 | Dependency edges across all requirements |
| `max_questions` | 64 | Pending clarification questions |
| `max_answer_bytes` | 16,384 | UTF-8 JSON bytes per answer |
| `callback_timeout_seconds` | 120 | Each model, interaction, notification, telemetry, and embedding call |

## Components

| Argument | Default | Purpose |
| --- | --- | --- |
| `model_call` | Required | Requirement discovery; see the [Quickstart](quickstart.md#1-connect-a-model) |
| `interrupt_call` | `None` | Collects answers and assumption approvals; see [Clarification](../guide/concepts/clarification.md) |
| `command_call` | `None` | Receives the terminal result once |
| `persistence` | `InMemoryPersistence()` | Session storage; see [Persistence](../guide/concepts/persistence.md) |
| `audit` | `AGXAIAudit()` | AGXAI provenance; see [Provenance](../guide/concepts/provenance.md) |
| `embedding_model` | `None` | Optional semantic duplicate candidates; see [Semantic duplicates](../guide/how-to/semantic-duplicates.md) |
| `telemetry_call` | `None` | Optional observer, such as [OpenTelemetry](../integrations/opentelemetry.md) |
| `application_id`, `tenant_id` | `"application"`, `"default"` | The scope every session and audit record belongs to |

The defaults keep everything in memory, which suits tests and examples but
does not survive a restart. Configure durable storage before production; see
[Use durable storage](../guide/how-to/durable-storage.md).

## Sync and async callbacks

Async callbacks are awaited. Sync callbacks run in a worker thread so they
never block the event loop. A timeout or cancellation cannot stop a sync
callback that is already running, so configure idempotency and timeouts in the
external systems it calls.
