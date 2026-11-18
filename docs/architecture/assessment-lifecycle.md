# Assessment lifecycle

An assessment discovers task requirements, may request clarification, and
returns a readiness result after recording the outcome through AGXAI.

![Assessment lifecycle](../assets/diagrams/assessment-flow.png){ .diagram }

## Lifecycle

| Step | What happens |
| --- | --- | --- |
| Discovery | The model proposes requirements; the engine validates them and applies its readiness policy. |
| Clarification | If configured and needed, the engine asks through `interrupt_call`, validates the response, and reassesses. |
| Result | The engine records the outcome with AGXAI, calls `command_call` once if configured, and returns the result. |

Standalone assessments can be persisted and resumed. LangGraph assessments use
the graph's checkpointer. A result is never returned as ready if its required
audit record could not be delivered.

## Outcomes

| Situation | Outcome |
| --- | --- |
| No requirements were discovered | `insufficient`, with an `empty_discovery` warning |
| No required information is blocking | `sufficient` |
| Required information is missing and can be requested | Ask, then reassess |
| A blocker cannot be resolved, or no interaction callback is configured | `insufficient` |
| The clarification budget is used up | `iteration_limit_reached` |

Assumptions require the feature to be enabled and the application to approve
them. A model proposal alone cannot make a task ready.

## Bounded work

- `max_iterations` bounds clarification rounds. Applied and malformed
  responses both consume the budget.
- `max_model_retries` bounds retries after transient model errors and
  timeouts.
- Callbacks have configurable timeouts. Standalone persistence uses expiring
  claims to prevent concurrent work on the same session.

## Failure handling

| Failure | Outcome |
| --- | --- |
| Model error, invalid proposal, invalid dependencies, too many questions | Terminal `failed` with the error code, audited |
| AGXAI write fails | Retryable `failed`; the intent stays pending for resume |
| `interrupt_call` fails after dispatch | Retryable `failed`; resume with an explicit response |
| Malformed response | One iteration used; retryable `failed` with the questions still pending |
| `command_call` fails after dispatch | `CallbackError`; never repeated |
| Storage fails | `PersistenceError`; the claim is released when possible |

## Recovery and side effects

When a callback or audit operation may have reached the application before a
failure, the engine reports the ambiguity instead of calling it again
automatically. Resume with an explicit response or retry the pending audit as
described in [Recover an interrupted assessment](../guide/how-to/recover-interrupted.md).
