# Callbacks, policy, and recovery

Use the public imports `SufficiencyEngine`, `InteractionResponse`, and
`AnswerSubmission`. The core has no provider SDK. `model_call(messages)` may
be synchronous or asynchronous and must return the discovery JSON described in
the engine's prompt, or a supported message with JSON text content.

A host interaction callback receives typed questions and assumptions:

```python
from sufficiency_engine import AnswerSubmission, InteractionResponse


async def interrupt_call(payload):
    question = payload.questions[0]
    # host_collect_values is application code; it returns requirement-ID keys.
    values = await host_collect_values(question)
    return InteractionResponse(answers=(AnswerSubmission(question_id=question.id, values=values),))
```

Combined questions have separate requirement answer slots. Return only known
IDs. Use `declined` or `ambiguous` slots explicitly, `corrections` when replacing
an accepted conflicting value, and `cancelled=True` for cancellation. Falsey
values such as `0` and `[]` are allowed when their declared constraints permit.
Malformed responses consume the clarification budget.

An available reassessment must cite an exact supplied task/answer quote again.
If it remains unresolved, do not force readiness by changing classification,
fabricating evidence, or rewriting a requirement under its old key.

`command_call(result)` is a terminal notification for standalone execution.
The host must use assessment/session IDs for its own idempotency. An ambiguous
notification is not automatically replayed.

For an ambiguous standalone interaction, resume with the same task/session,
`resume=True`, and an explicit `response`. For a required provenance failure,
repair the sink and resume the same session to replay its persisted stable
intent. Never create a new successful assessment merely to conceal the failure.
Durable recovery requires both durable session state and durable AGXAI
provenance and semantic storage. Task-level `source_references` are opaque
assessment references, not verified per-requirement source attribution.
