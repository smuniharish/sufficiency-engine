# Recover an interrupted assessment

A standalone assessment saves its state after every step, so a failure leaves
a session you can resume. Resume with the **same task text and session ID**
and `resume=True`. A changed task, or different source references, is
rejected.

## The interaction callback failed

If `interrupt_call` raises or times out after it was dispatched, the engine
cannot tell whether the user already saw the question. It returns a retryable
`failed` result with `clarification_callback_error` and never calls the
callback again by itself. Collect the answer through your own channel, then
resume with an explicit response:

```python
result = await engine.execute(
    input=task,
    session_id=session_id,
    resume=True,
    response=interaction_response,
)
```

Resuming without a response returns `interaction_ambiguous` for the same
reason.

## The response was malformed

A response with an unknown question ID, a duplicate answer, or invalid slots
accepts no answers, consumes one iteration, and returns a retryable `failed`
result with `clarification_error`. The pending questions are kept. Resume with
a corrected `response` as shown above. When the iteration budget runs out, the
assessment ends as `iteration_limit_reached`.

## AGXAI was unavailable

A failed provenance write returns a retryable `failed` result with
`provenance_error`. The audit intent is already saved with the session. After
the store or archive is healthy again, resume without a response:

```python
result = await engine.execute(input=task, session_id=session_id, resume=True)
```

The same records are delivered with the same IDs, and the model is not called
again.

## The notification callback failed

If `command_call` fails after dispatch, `execute` raises `CallbackError`. The
notification may already have had its effect, so the engine never repeats it;
a later resume raises `CallbackError` again. Reconcile the notification in your
application. The terminal result is unchanged.

## What is never recovered automatically

- A terminal model or validation failure is not turned into a new assessment.
  Start a new session.
- A session being deleted cannot be resumed. Call `delete_session` again to
  finish deleting it.
- In LangGraph, resume the graph thread instead; see
  [LangGraph](../../integrations/langgraph.md#recovery).
