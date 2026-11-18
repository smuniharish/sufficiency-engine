# Errors

Every exception the library raises derives from `SufficiencyError` and carries
a stable, machine-readable `code`. Import them from
`sufficiency_engine.exceptions`. Most failures during an assessment are returned
as a failed `AssessmentResult` with the same code rather than raised; see
[Troubleshooting](../guide/troubleshooting.md).

```python
from sufficiency_engine.exceptions import ConfigurationError, SufficiencyError

try:
    result = await engine.execute(input=task)
except ConfigurationError as exc:
    reject_request(exc.code)
```

| Exception | Code | Raised when |
| --- | --- | --- |
| `SufficiencyError` | `sufficiency_error` | Base class |
| `ConfigurationError` | `configuration_error` | The engine or its input is not configured correctly |
| `ModelInvocationError` | `model_invocation_error` | The model callback failed |
| `TransientModelError` | `transient_model_error` | Your model callback marks a failure as retryable |
| `ModelResponseError` | `model_response_error` | A model response failed normalization or schema validation |
| `CallbackError` | `callback_error` | An application callback failed |
| `ClarificationError` | `clarification_error` | An interaction or answer could not be processed |
| `PersistenceError` | `persistence_error` | Session persistence failed |
| `SessionConflictError` | `session_conflict` | A concurrent session change or revision conflict occurred |
| `SerializationError` | `serialization_error` | A stored session is invalid or has an unsupported version |
| `ProvenanceError` | `provenance_error` | A required audit operation failed |
| `DependencyError` | `invalid_dependencies` | A requirement graph has invalid references or cycles |

::: sufficiency_engine.exceptions
    options:
      show_root_heading: false
      members_order: source