# Quickstart

This page builds the [quickstart example](../examples/quickstart.md) step by
step: a deployment task that does not name its platform. You connect a model
callback, collect the missing answer, and read the audited result.

## 1. Connect a model

The engine builds the prompt; your application calls the model. The callback
receives provider-neutral messages (`[{"role": ..., "content": ...}]`) and
returns a JSON mapping, JSON text, or a message object whose `content` is JSON.
Sync and async callables are both accepted.

```python
async def model_call(messages):
    return await chat_model.ainvoke(messages)
```

`chat_model` is any model your application is authorized to use. The prompt
contains the discovery schema, the task, and previously accepted answers, so
send it only to an approved provider.

To run offline, the example replaces the model with a deterministic callback.
It reports the platform as `unresolved` until the user's answer arrives, then
as `available`, quoting that answer:

```python
async def model_call(messages):
    prior = json.loads(messages[-1]["content"])["prior"]
    answered = bool(prior and prior[0]["answers"] == ["Linux"])
    return {
        "requirements": [
            {
                "key": "platform",
                "description": "Deployment platform",
                "classification": "mandatory",
                "status": "available" if answered else "unresolved",
                "evidence_quote": "Linux" if answered else None,
                "necessity": "must_ask",
                "reason": "The deployment steps depend on the platform.",
                "question": "Which platform should the service be deployed on?",
                "answer_type": "string",
            }
        ]
    }
```

Each requirement is a proposal. The engine checks that an `available`
requirement quotes text that was actually supplied, and its own policy decides
what blocks. See [Requirements and evidence](../guide/concepts/requirements.md).

## 2. Collect missing answers

When a blocking requirement needs a question, the engine calls your
`interrupt_call` with a `ClarificationPayload`. Ask the user however your
application does, and return an `InteractionResponse`:

```python
from sufficiency_engine import AnswerSubmission, InteractionResponse


async def ask_user(payload):
    question = payload.questions[0]
    print("Question:", question.text)
    return InteractionResponse(
        answers=(
            AnswerSubmission(
                question_id=question.id,
                values={question.requirement_ids[0]: "Linux"},
            ),
        )
    )
```

Each value is keyed by requirement ID, because one question can cover several
requirements. Without an `interrupt_call`, a task that needs a question ends as
`insufficient`.

## 3. Assess the task

```python
from sufficiency_engine import SufficiencyEngine

engine = SufficiencyEngine(model_call=model_call, interrupt_call=ask_user)
result = await engine.execute(input="Deploy the billing service.")
```

`execute` discovers requirements, asks, validates the answer, reassesses, and
returns only when the assessment is finished:

```text
Question: Which platform should the service be deployed on?
Status: sufficient
Sufficient: True
Clarification rounds: 1
  platform: available, blocking=False
Audited decisions: 2
```

## 4. Read the result

`AssessmentResult` is immutable and self-consistent: `sufficient` is `True`
only for status `sufficient`, which requires no blocking requirements, no
errors, and a recorded AGXAI decision.

| Field | Contains |
| --- | --- |
| `status` | `sufficient`, `insufficient`, `cancelled`, `iteration_limit_reached`, or `failed` |
| `requirements`, `blocking_requirements` | Every evaluated requirement, and the ones that still block |
| `questions`, `answers`, `assumptions` | The clarification history |
| `errors`, `warnings` | Structured diagnostics with a `code` and a `retryable` flag |
| `provenance` | AGXAI run, evidence, decision, and link IDs |

Only your application decides whether and how to run the task. Any status other
than `sufficient` never authorizes execution.

## Next steps

- Choose budgets and limits in [Configuration](configuration.md).
- Keep sessions across restarts with [durable storage](../guide/how-to/durable-storage.md).
- Put the check at a LangGraph task entry with the [LangGraph integration](../integrations/langgraph.md).
