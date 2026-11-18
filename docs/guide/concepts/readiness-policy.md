# Readiness policy

The model proposes; Python decides. After every discovery and reassessment,
`apply_blocking_policy` recomputes the `blocking` flag of every requirement
from scratch. A blocking value supplied by the model is always replaced.

## Which requirements block

A requirement blocks when it is **required** and its information is **not
available**.

Required
:   Every active `mandatory` or `minimum` requirement. An `optional`
    requirement is required only when `require_optional=True`, or when a
    required requirement depends on it. Dependencies are followed transitively.

Available
:   Status `available`, or status `assumed` with an
    [approved assumption](#assumptions).

So an unresolved optional requirement does not block by default, a declined
mandatory requirement keeps blocking, and a missing prerequisite blocks
everything that depends on it.

## Dependencies fail closed

The requirement graph is validated before blocking is computed. Each of these
fails the assessment with `invalid_dependencies` instead of being ignored:

- A dependency on an unknown, superseded, or retired requirement.
- A duplicate dependency, a duplicate requirement ID, or a duplicate key.
- A dependency cycle.
- More requirements or dependency edges than the configured
  [limits](../../getting-started/configuration.md#limits).

## From blockers to an outcome

| Situation | Outcome |
| --- | --- |
| No active requirements were discovered | `insufficient`, with an `empty_discovery` warning |
| Nothing blocks | `sufficient` |
| The clarification budget is used up | `iteration_limit_reached` |
| A blocker can be resolved by a question or an assumption | The engine asks, then reassesses |
| Something blocks, and nothing can resolve it | `insufficient` |

Discovering no requirements is never treated as success. For each blocker, the
engine records a `Decision` with the action it took: `must_ask`, `may_assume`,
or `must_block`. A blocker whose proposal says `may_defer` or `not_needed`, or
that the user declined, is recorded as `must_block` and is not asked again.

## Assumptions

An assumption lets a default value satisfy a requirement. It is accepted only
when **all** of these hold:

1. The engine was created with `allow_assumptions=True`.
2. The model proposed `may_assume` with a low-risk, reversible assumption whose
   value passes the requirement's answer type and constraints.
3. The application explicitly approved it in
   `InteractionResponse.assumption_approvals`.

An unapproved, medium- or high-risk, or irreversible assumption never satisfies
a requirement. If the proposal also has a question, the engine asks instead.

```python
async def interrupt_call(payload):
    approvals = {
        assumption.id: assumption.risk == "low" and assumption.reversible
        for assumption in payload.assumptions
    }
    return InteractionResponse(assumption_approvals=approvals)
```

Approval is your application's decision; the example approves every low-risk,
reversible proposal only for illustration.
