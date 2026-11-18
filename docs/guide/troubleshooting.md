# Troubleshooting

Problems surface in two ways. Recoverable assessment problems are returned as a
result with `status="failed"` and a diagnostic in `result.errors`. Invalid
calls and storage failures raise an exception. Every diagnostic and exception
has a stable `code` and a `retryable` flag; branch on the code, not the
message.

## Failed results

| `errors[].code` | Cause | Fix |
| --- | --- | --- |
| `provenance_error` | An AGXAI store or archive write failed | Restore the store, then resume with `resume=True`; the same records are retried |
| `clarification_callback_error` | `interrupt_call` raised or timed out after dispatch | Collect the answer yourself and resume with `response=` |
| `interaction_ambiguous` | Resumed without a response while a dispatched question was unanswered | Resume with `response=` |
| `clarification_error` | The response had unknown IDs, duplicates, or invalid values, and no answers were accepted; or discovery produced more than `Limits.max_questions` questions | Resume with a corrected `response=`; for the question limit, start a new session with a narrower task or a higher limit |
| `model_invocation_error` | `model_call` failed and the retry budget was exhausted | Check the provider; start a new session |
| `model_response_error` | The model output was not a valid discovery proposal | Review your prompt adapter and model; start a new session |
| `invalid_dependencies` | The proposal had a cycle, an unknown or inactive dependency, or exceeded a limit | Review the model output; start a new session |

See [Recover an interrupted assessment](how-to/recover-interrupted.md) for the
resume calls.

## Warnings

Warnings in `result.warnings` do not change the outcome.

| Code | Meaning |
| --- | --- |
| `empty_discovery` | The model found no requirements, so the task is `insufficient` |
| `potential_duplicate` | Similar questions were kept because equivalence is uncertain |
| `embedding_unavailable` | The embedding model failed; exact matching was used |
| `telemetry_error` | A telemetry callback or AGXAI observer failed; the assessment is unaffected |
| `clarification_error` | An earlier response was rejected |

## Exceptions

All exceptions inherit from `SufficiencyError` in
`sufficiency_engine.exceptions`.

| Exception | Code | Typical cause |
| --- | --- | --- |
| `ConfigurationError` | `configuration_error` | Invalid engine options or `execute` arguments; see below |
| `SessionConflictError` | `session_conflict` | A session with this ID already exists, or another writer holds the claim |
| `SerializationError` | `serialization_error` | Stored state has an invalid or unsupported schema version |
| `PersistenceError` | `persistence_error` | The session store failed, or the session is being deleted |
| `CallbackError` | `callback_error` | `command_call` failed or its outcome is ambiguous; it is never repeated |
| `ProvenanceError` | `provenance_error` | AGXAI deletion failed during `delete_session` |

## Common messages

| Message | Fix |
| --- | --- |
| `resuming requires a session ID` | Pass the `session_id` of the session you are resuming |
| `an explicit response requires resume=True` | Add `resume=True` when passing `response=` |
| `session does not exist` | Check the ID, application, and tenant; the default in-memory store loses sessions on restart |
| `session already exists` | Use a new session ID, or pass `resume=True` |
| `resume input or session scope does not match` | Resume with the exact original task text and the same scope |
| `cannot submit a response to a finished assessment` | Resume without `response=` to read the result |
| `task input exceeds the configured size limit` | Shorten the input or raise `Limits.max_input_bytes` |
| `session deletion is pending; retry delete_session` | Call `delete_session` again to finish the deletion |

## The task is never ready

- **Questions are pending but there is no `interrupt_call`.** The engine cannot
  ask, so it returns `insufficient`. Add a callback or handle the questions
  yourself.
- **Assumptions are never applied.** Assumptions need
  `allow_assumptions=True`, an explicit approval, and must be low-risk and
  reversible.
- **The status is `iteration_limit_reached`.** The user did not resolve the
  blockers within `max_iterations` rounds. Raise the limit or simplify the
  task.
