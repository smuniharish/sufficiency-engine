# Clarification

Missing information is not automatically a question. The engine asks only for
blocking requirements whose proposal includes a question, and zero questions is
a valid outcome.

![Clarification flow](../../assets/diagrams/clarification-flow.png){ .diagram }

## The interaction callback

When questions or assumptions are pending, the engine calls your
`interrupt_call` with a `ClarificationPayload`:

| Field | Contains |
| --- | --- |
| `questions` | Pending `ClarificationQuestion` objects, each with `text`, `reason`, `requirement_ids`, `expected_type`, and `constraints` |
| `assumptions` | Proposed assumptions awaiting approval |
| `requirements` | The current requirements, for context |
| `assessment_id`, `session_id` | Identifiers for correlating the interaction |

Return an `InteractionResponse`:

```python
from sufficiency_engine import AnswerSubmission, InteractionResponse


async def interrupt_call(payload):
    question = payload.questions[0]
    requirement_id = question.requirement_ids[0]
    value = await ask_the_user(question.text)
    return InteractionResponse(
        answers=(
            AnswerSubmission(
                question_id=question.id,
                values={requirement_id: value},
            ),
        )
    )
```

`ask_the_user` is your application's code. An `AnswerSubmission` holds, per
requirement ID, a value, or the ID in `declined` or `ambiguous`. Set
`cancelled=True` on the response to end the assessment as `cancelled`.

## Combined questions

Requirements whose questions have the same text, reason, and compatible answer
constraints are combined into one question with several requirement IDs.
Answer each slot separately. Valid partial answers are kept, and unanswered
slots get targeted follow-up questions.

## Answer validation

Each value is checked against the question's `expected_type` and
`constraints` (`nullable`, `min_length`, `max_length`, `minimum`, `maximum`,
`choices`) and the `max_answer_bytes` limit. Values such as `0`, `False`,
`"no"`, `"none"`, and `[]` are valid answers; they are not rejected for being
falsy.

Replacing a previously accepted answer that conflicts with a new one requires
listing its requirement ID in `corrections`. Declined questions are never asked
again.

## Reassessment

A valid answer is not proof that the task is now ready. After each round, the
model reassesses with the accepted answers, and a requirement becomes
`available` only if the model quotes an answer bound to that requirement.

If reassessment still reports the requirement unresolved, its previous
availability is cleared, and the answer history is marked `ambiguous`, or
`contradictory` when the model reports conflicting quotes. Approved
assumptions and explicit declines keep their meaning.

## Malformed responses

A response that fails validation, such as an unknown question ID or an invalid
slot, accepts no answers and consumes one iteration. Before the budget runs
out, a standalone assessment returns a retryable `failed` result with
`clarification_error` and keeps its pending questions, so you can
[resume with a corrected response](../how-to/recover-interrupted.md). A
LangGraph assessment interrupts again. Once `max_iterations` is reached, both
end as `iteration_limit_reached`.

## Deduplication

Exact duplicate questions for the same requirement slot, after normalization,
are removed. Similar wording alone never suppresses a question, because
"deploy to production" and "do not deploy to production" are similar text.
An optional [`EmbeddingModelABC`](../how-to/semantic-duplicates.md) reports
semantic duplicate candidates as warnings; it does not remove questions.

## Terminal notification

An optional `command_call(result)` receives the terminal result once. If it
fails after it was dispatched, the engine raises `CallbackError` and does not
call it again, because its side effect may already have happened. The
LangGraph integration does not call it; the host handles the terminal result.
