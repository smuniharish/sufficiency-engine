# Architecture

Sufficiency Engine is a small library with one job: decide, at task entry,
whether a task has enough information to proceed. The application keeps
ownership of everything else: the model, the user conversation, agents,
tools, workflows, and storage.

![Sufficiency Engine architecture](../assets/diagrams/architecture-overview.png){ .diagram }

## Components

| Component | Responsibility |
| --- | --- |
| `SufficiencyEngine` | Runs an assessment through the application's callbacks |
| Discovery | Collects proposed requirements from the configured model |
| Readiness policy | Determines which requirements block the task |
| Clarification | Plans questions and validates the application's answers |
| Persistence | Saves standalone sessions for recovery |
| Audit | Records readiness decisions through AGXAI |
| Public models | Pydantic models and enums used by the API |
| Integrations | Optional LangGraph and OpenTelemetry adapters |

## Lifecycle

1. The application calls `execute` with a task. The engine claims the session
   and saves its initial state.
2. Discovery sends the task, prior requirements, and accepted answers to
   `model_call`, and validates the proposed requirements against the schema and
   the supplied text.
3. The policy computes which required requirements are still unavailable, and
   plans one decision for each: ask, assume, or block.
4. The readiness outcome is recorded through AGXAI before it is returned.
5. If questions remain and `interrupt_call` is configured, the engine asks,
   validates the answers, and goes back to step 2.
6. On a terminal outcome, the engine delivers the final audit record, calls
   `command_call` once if configured, and returns the `AssessmentResult`.

Each step is detailed in [Assessment lifecycle](assessment-lifecycle.md).

## Design principles

- **The model proposes, the policy decides.** A model can claim information is
  present only by quoting it. Blocking, dependencies, and assumptions are
  decided by deterministic code.
- **Fail closed.** A model error, an invalid answer, an exhausted budget, or a
  failed audit never produces a ready result.
- **Audit before acting.** A result is returned only after its AGXAI record is
  delivered.
- **Recover explicitly.** Interrupted assessments can be resumed without
  silently repeating an interaction or notification that might already have
  reached the application.
- **Own only readiness.** No agent execution, conversation storage, model
  hosting, or orchestration.
- **Explicit extension points.** Callbacks for application behavior, and
  abstract base classes for storage and embeddings.

## In this section

<div class="grid cards" markdown>

-   **[Assessment lifecycle](assessment-lifecycle.md)**

    ---

    Phases, budgets, and terminal outcomes.

-   **[Requirements and evidence](requirements-and-evidence.md)**

    ---

    Identity, evidence binding, lineage, and reassessment.

-   **[Persistence](persistence.md)**

    ---

    Claims, fencing, revisions, and the audit outbox.

-   **[Provenance](provenance.md)**

    ---

    How AGXAI records are shaped and delivered.

-   **[Extensibility](extensibility.md)**

    ---

    Callbacks, ABCs, and optional extras.

</div>
