# Custom frameworks

The engine is a plain async object, so any host can call it: a web handler, a
queue worker, a CLI, or your own agent loop. Call it **once when a task
arrives**, before you plan or run any work.

## Synchronous questions

When the user can answer right away, for example in a chat or a terminal,
provide `interrupt_call`. It receives a `ClarificationPayload` and returns an
`InteractionResponse` or an equivalent mapping:

```python
from sufficiency_engine import AnswerSubmission, InteractionResponse, SufficiencyEngine


async def ask_user(payload):
    answers = []
    for question in payload.questions:
        text = await chat.ask(question.text)
        answers.append(
            AnswerSubmission(
                question_id=question.id,
                values={requirement_id: text for requirement_id in question.requirement_ids},
            )
        )
    return InteractionResponse(answers=tuple(answers))


engine = SufficiencyEngine(model_call=model_call, interrupt_call=ask_user)
result = await engine.execute(input=task)
if result.sufficient:
    await run_task(task, result)
```

`chat` and `run_task` stand for your application.

## Deferred questions

When answers arrive later, for example over email or a ticket, you have two
options:

- **Pause and resume.** Use the [LangGraph integration](langgraph.md). Its
  interrupt keeps the assessment in a durable checkpoint until the answers
  arrive, in any process.
- **Assess again.** Omit `interrupt_call`. The engine finishes as
  `insufficient` and lists the open questions in `result.questions`. Send
  them, and when the answers arrive, start a new assessment whose task
  includes them:

```python
result = await engine.execute(input=task)
if not result.sufficient and result.questions:
    await send_questions(ticket_id, result.questions)

# Later, when the answers arrive:
result = await engine.execute(input=f"{task}\n\nAnswers:\n{answers_text}")
```

A finished standalone session cannot accept answers. Resuming it with
`response=` raises `ConfigurationError`.

## Terminal notification

`command_call` receives the final `AssessmentResult` once, after it is
audited. Use it to start the work or notify another service. It is never
repeated: if it fails, `execute` raises `CallbackError`, and your application
reconciles the outcome.

## Callback rules

- Callbacks can be `async def` or plain functions. Plain functions run in a
  worker thread so they do not block the event loop.
- Every callback is bounded by `Limits.callback_timeout_seconds`. A timed-out
  synchronous function cannot be stopped and may keep running in its thread.
- Callbacks receive sanitized, typed models. Keep credentials and provider
  clients in your callback, never in the task text.

See [Configuration](../getting-started/configuration.md#sync-and-async-callbacks)
for the full callback contract.
