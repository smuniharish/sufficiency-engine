# Security

Sufficiency Engine decides whether a task may proceed, so a wrong answer can let
an application act on incomplete information. Its session state also holds the
task and the user's answers. This page lists what the library protects by
default and what a deployment must still decide.

## Built in

- **Model output is untrusted.** Every model response is validated against a
  strict schema. A requirement can be marked available only with a quote of
  the supporting evidence, and the prompt tells the model to treat the task
  and answers as data, never as instructions.
- **Deterministic blocking.** The [readiness policy](guide/concepts/readiness-policy.md),
  not the model, decides what blocks. An unresolved required value stays
  blocking, and a failed, cancelled, or iteration-limited assessment is never
  sufficient.
- **Bounded input.** [`Limits`](api/engine.md) caps task and answer size,
  requirements, dependency edges, questions, and callback time. Oversized input
  is rejected rather than truncated.
- **Mandatory provenance.** Every decision is recorded through AGXAI in strict
  mode. If recording fails, the result fails with `provenance_error`; it is
  never silently dropped.
- **Content-free provenance and telemetry.** AGXAI records and telemetry carry
  IDs, counts, statuses, and durations. They never contain the task text or
  answers.
- **Scoped state.** Sessions and AGXAI records are keyed by application, tenant,
  and session, and writes require a current claim, fencing token, and revision.
- **No ambient configuration.** The library reads no environment variables,
  makes no network calls of its own, and never uses `pickle`.

## Your responsibilities

| Area | What to do |
| --- | --- |
| Authentication | Authenticate the caller and choose `application_id`, `tenant_id`, and `session_id` from trusted data. The library trusts the scope it is given. |
| Session data | Session snapshots and LangGraph checkpoints contain the task and answers. Restrict access, encrypt at rest, and apply your retention period; `delete_session` erases a session and its AGXAI run. |
| Model providers | `model_call` sends the task and answers to your model. Use a provider and region your data agreements permit. |
| Readiness | A sufficient result means no known blocker remains. It does not authorize the task or prove that discovery found every requirement; your application decides whether to act. |
| Callbacks | Callbacks are trusted application code. A timed-out synchronous callback keeps running in its thread, so make side effects idempotent. |
| Storage extensions | Run custom stores through the [contract checks](guide/how-to/durable-storage.md) and test recovery against the real backend; see [Validate a deployment](guide/how-to/validate-deployment.md). |
| Telemetry | Do not add task text or answers to span attributes or logs of your own. |
| Dependencies | Install only the extras you use, and pin versions in your application. |

## Reporting a vulnerability

Report vulnerabilities privately, as described in the repository's
[security policy](https://github.com/smuniharish/sufficiency-engine/blob/main/SECURITY.md).
Do not open a public issue.