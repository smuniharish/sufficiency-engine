---
name: sufficiency-engine
description: >-
  Use this skill when integrating the sufficiency-engine Python library to
  determine whether a task has enough information, collect necessary
  clarification, validate supplied answers, approve safe assumptions, recover
  assessments, or place readiness before a LangGraph supervisor. Also use it
  to troubleshoot unexpected readiness or failed mandatory AGXAI recording.
  Do not use it to execute tasks, manage conversations, instrument every
  model/tool call, or implement a storage/embedding extension; use
  sufficiency-engine-extend for extension contracts.
license: Apache-2.0
compatibility: >-
  Python 3.12+. Requires sufficiency-engine 1.x and its mandatory AGXAI
  dependency. LangGraph integration requires the langgraph extra. The setup
  script is offline and imports LangGraph only with --langgraph.
metadata:
  version: "1.0.0"
---

# Integrate task readiness

Sufficiency Engine assesses readiness; the application executes the task.
Model output is untrusted. Deterministic policy owns blocking, and AGXAI owns
provenance. Readiness is relative to discovered requirements, not proof that
discovery is complete or that execution is authorized.

## Workflow

1. Run `python scripts/verify_setup.py --json` from this skill directory using
   the application's Python environment. Add `--langgraph` only when that
   integration is required. Resolve failures rather than disabling audit.
2. Supply `model_call(messages)` to `SufficiencyEngine`. Return schema-valid
   JSON data or text; the engine builds the prompt. Async callbacks are
   awaited; sync callbacks run in worker threads.
3. Call `await engine.execute(input=task)` once at the application's explicit
   task-entry boundary, before the supervisor or workers. Never install
   automatic assessment hooks around ordinary model calls or tools.
4. Provide `interrupt_call(payload)` when the host can collect answers and
   approvals. Return `InteractionResponse` using the question and requirement
   IDs in the payload. Keep valid partial answers; do not invent missing ones.
5. Consume the full terminal result. Only the host decides whether/how to
   execute. A false result, iteration limit, or required audit failure never
   authorizes execution.
6. Run project tests and the setup check again. Verify production storage and
   the actual discovery model separately; offline checks do not certify them.
7. Before finishing, tell the user how their callbacks run: sync callbacks
   run in worker threads that a timeout cannot stop, and `command_call` is
   dispatched at most once, so a failed or ambiguous notification raises
   `CallbackError` instead of replaying. Its handler should be idempotent and
   keyed by `assessment_id`.

## Read as needed

| Concern | Reference |
| --- | --- |
| Callbacks, evidence, assumptions, and failure recovery | [callbacks.md](references/callbacks.md) |
| Checkpoint-safe interrupt/resume and task boundaries | [langgraph.md](references/langgraph.md) |

## Safety rules

- Keep requirement descriptions and answer contracts stable under a key.
  A changed meaning needs a new key and explicit superseding lineage.
- On reassessment, `unresolved` remains blocking for required information.
  A structurally valid answer is not automatically semantically sufficient.
- Preserve explicit declines. Assumptions require enabled policy, low risk,
  reversibility, and host approval; do not use them to hide mandatory blockers.
- Do not infer requirement-level support from every task-level source UUID.
- Keep raw inputs/answers out of logs and telemetry. They do exist in session
  state and must be protected by the application.
- Do not substitute telemetry for durable AGXAI records or a no-op archive.
- Cancelling or timing out a synchronous callback cannot stop its thread.
  Do not replay ambiguous interaction/notification side effects automatically.
