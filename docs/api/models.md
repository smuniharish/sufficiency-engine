# Models

Immutable Pydantic models exchanged with the engine. `AssessmentResult` is what
`execute` returns; `ClarificationPayload` is what your `interrupt_call`
receives; `InteractionResponse` is what it returns. See
[Requirements](../guide/concepts/requirements.md) and
[Clarification](../guide/concepts/clarification.md) for how they fit together.

## Results

::: sufficiency_engine.models.AssessmentResult

::: sufficiency_engine.models.AssessmentStatus

::: sufficiency_engine.models.Decision

::: sufficiency_engine.models.Diagnostic

::: sufficiency_engine.models.ProvenanceReferences

## Requirements

::: sufficiency_engine.models.Requirement

::: sufficiency_engine.models.RequirementClassification

::: sufficiency_engine.models.RequirementStatus

::: sufficiency_engine.models.RequirementLifecycle

::: sufficiency_engine.models.RequirementLineage

::: sufficiency_engine.models.NecessityDecision

## Clarification

::: sufficiency_engine.models.ClarificationPayload

::: sufficiency_engine.models.ClarificationQuestion

::: sufficiency_engine.models.QuestionStatus

::: sufficiency_engine.models.AnswerType

::: sufficiency_engine.models.AnswerConstraints

## Answers and assumptions

::: sufficiency_engine.models.InteractionResponse

::: sufficiency_engine.models.AnswerSubmission

::: sufficiency_engine.models.Answer

::: sufficiency_engine.models.AnswerStatus

::: sufficiency_engine.models.Assumption

::: sufficiency_engine.models.AssumptionStatus

::: sufficiency_engine.models.RiskLevel