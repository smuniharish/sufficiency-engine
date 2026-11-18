"""Typed, framework-independent assessment contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    model_validator,
)


class FrozenModel(BaseModel):
    """A version-independent immutable public value."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RequirementClassification(StrEnum):
    """How necessary a requirement is for the task."""

    MANDATORY = "mandatory"
    MINIMUM = "minimum"
    OPTIONAL = "optional"


class RequirementStatus(StrEnum):
    """What is known about the information for a requirement."""

    AVAILABLE = "available"
    MISSING = "missing"
    ASSUMED = "assumed"
    UNRESOLVED = "unresolved"
    DECLINED = "declined"


class RequirementLifecycle(StrEnum):
    """Whether a requirement participates in the current assessment."""

    ACTIVE = "active"
    SATISFIED = "satisfied"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class QuestionStatus(StrEnum):
    """The state of a clarification question."""

    PENDING = "pending"
    ANSWERED = "answered"
    PARTIALLY_ANSWERED = "partially_answered"
    INVALID = "invalid"
    SUPERSEDED = "superseded"
    DECLINED = "declined"


class AnswerStatus(StrEnum):
    """The outcome of validating one answer."""

    VALID = "valid"
    INVALID = "invalid"
    AMBIGUOUS = "ambiguous"
    CONTRADICTORY = "contradictory"
    DECLINED = "declined"


class AssumptionStatus(StrEnum):
    """An application's decision about a proposed assumption."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class NecessityDecision(StrEnum):
    """A proposed or enforced action for missing information."""

    MUST_ASK = "must_ask"
    MAY_ASSUME = "may_assume"
    MAY_DEFER = "may_defer"
    MUST_BLOCK = "must_block"
    NOT_NEEDED = "not_needed"


class AssessmentStatus(StrEnum):
    """Terminal outcome of an assessment."""

    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    CANCELLED = "cancelled"
    ITERATION_LIMIT_REACHED = "iteration_limit_reached"
    FAILED = "failed"


class AnswerType(StrEnum):
    """Supported JSON answer types."""

    ANY = "any"
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class RiskLevel(StrEnum):
    """Coarse risk metadata for an assumption."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AnswerConstraints(FrozenModel):
    """Declarative constraints checked without executing model-supplied code."""

    nullable: bool = False
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[JsonValue, ...] | None = None

    @model_validator(mode="after")
    def check_ranges(self) -> AnswerConstraints:
        """Reject contradictory limits."""
        if self.min_length is not None and self.max_length is not None:
            if self.min_length > self.max_length:
                raise ValueError("min_length exceeds max_length")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("minimum exceeds maximum")
        return self


def _now() -> datetime:
    return datetime.now(UTC)


class Requirement(FrozenModel):
    """One stable, independently classified requirement.

    Availability must reference evidence from the supplied task or a validated
    answer; a model assertion by itself is not evidence.
    """

    id: UUID = Field(default_factory=uuid4)
    key: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")]
    description: Annotated[str, Field(min_length=1, max_length=2_048)]
    classification: RequirementClassification
    status: RequirementStatus = RequirementStatus.UNRESOLVED
    lifecycle: RequirementLifecycle = RequirementLifecycle.ACTIVE
    blocking: bool = False
    source_evidence_ids: tuple[UUID, ...] = ()
    dependencies: tuple[UUID, ...] = ()
    parent_ids: tuple[UUID, ...] = ()
    related_ids: tuple[UUID, ...] = ()
    confidence: float | None = Field(default=None, ge=0, le=1)
    created_at: AwareDatetime = Field(default_factory=_now)
    updated_at: AwareDatetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def check_evidence(self) -> Requirement:
        """Do not accept an evidence-free availability assertion."""
        if self.status is RequirementStatus.AVAILABLE and not self.source_evidence_ids:
            raise ValueError("available requirements need evidence")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at precedes created_at")
        return self


class ClarificationQuestion(FrozenModel):
    """A question tied to one or more stable requirement answer slots."""

    id: UUID = Field(default_factory=uuid4)
    requirement_ids: tuple[UUID, ...] = Field(min_length=1)
    text: Annotated[str, Field(min_length=1, max_length=2_048)]
    reason: Annotated[str, Field(min_length=1, max_length=2_048)]
    expected_type: AnswerType = AnswerType.ANY
    constraints: AnswerConstraints = Field(default_factory=AnswerConstraints)
    required: bool = True
    status: QuestionStatus = QuestionStatus.PENDING
    answer_slot: Annotated[str, Field(min_length=1, max_length=128)] = "value"
    follow_up_to: UUID | None = None


class Answer(FrozenModel):
    """A submitted answer and its validation outcome."""

    question_id: UUID
    requirement_id: UUID
    value: JsonValue = None
    status: AnswerStatus
    reason: str | None = Field(default=None, max_length=2_048)


class Assumption(FrozenModel):
    """A proposed value that requires explicit application approval."""

    id: UUID = Field(default_factory=uuid4)
    requirement_id: UUID
    description: Annotated[str, Field(min_length=1, max_length=2_048)]
    value: JsonValue
    risk: RiskLevel
    reversible: bool
    status: AssumptionStatus = AssumptionStatus.PROPOSED


class Decision(FrozenModel):
    """A domain decision referencing the requirements it concerns."""

    id: UUID = Field(default_factory=uuid4)
    requirement_ids: tuple[UUID, ...] = ()
    action: NecessityDecision
    reason: Annotated[str, Field(min_length=1, max_length=2_048)]


class RequirementLineage(FrozenModel):
    """A relationship between prior and successor requirements."""

    operation: Literal["update", "split", "merge", "supersede", "retire"]
    parent_ids: tuple[UUID, ...] = Field(min_length=1)
    successor_ids: tuple[UUID, ...] = ()


class Diagnostic(FrozenModel):
    """A safe, structured warning or error."""

    code: Annotated[str, Field(min_length=1, max_length=128)]
    message: Annotated[str, Field(min_length=1, max_length=2_048)]
    retryable: bool = False


class ProvenanceReferences(FrozenModel):
    """Opaque references to records owned by AGXAI."""

    run_id: UUID
    evidence_ids: tuple[UUID, ...] = ()
    decision_ids: tuple[UUID, ...] = ()
    link_ids: tuple[UUID, ...] = ()


class ClarificationPayload(FrozenModel):
    """Complete input to an application-owned interaction callback."""

    assessment_id: UUID
    session_id: str
    questions: tuple[ClarificationQuestion, ...]
    requirements: tuple[Requirement, ...]
    assumptions: tuple[Assumption, ...] = ()


class AnswerSubmission(FrozenModel):
    """Values and declines for the requirement slots in one question."""

    question_id: UUID
    values: dict[UUID, JsonValue] = Field(default_factory=dict)
    declined: tuple[UUID, ...] = ()
    ambiguous: tuple[UUID, ...] = ()
    corrections: tuple[UUID, ...] = ()


class InteractionResponse(FrozenModel):
    """The host's answers, explicit assumption approvals, or cancellation."""

    answers: tuple[AnswerSubmission, ...] = ()
    assumption_approvals: dict[UUID, StrictBool] = Field(default_factory=dict)
    cancelled: StrictBool = False


class AssessmentResult(FrozenModel):
    """A terminal assessment with an explicit audited readiness outcome."""

    assessment_id: UUID
    session_id: str
    status: AssessmentStatus
    sufficient: bool
    require_optional: bool = False
    allow_assumptions: bool = False
    requirements: tuple[Requirement, ...] = ()
    blocking_requirements: tuple[Requirement, ...] = ()
    questions: tuple[ClarificationQuestion, ...] = ()
    answers: tuple[Answer, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    decisions: tuple[Decision, ...] = ()
    iteration_count: int = Field(default=0, ge=0)
    warnings: tuple[Diagnostic, ...] = ()
    errors: tuple[Diagnostic, ...] = ()
    provenance: ProvenanceReferences | None = None
    lineage: tuple[RequirementLineage, ...] = ()
    completion_reason: Annotated[str, Field(min_length=1, max_length=2_048)]

    @model_validator(mode="after")
    def check_consistency(self) -> AssessmentResult:
        """Reject success-shaped failures and inconsistent blockers."""
        if self.sufficient != (self.status is AssessmentStatus.SUFFICIENT):
            raise ValueError("sufficient must match the terminal status")
        expected = tuple(requirement for requirement in self.requirements if requirement.blocking)
        if self.blocking_requirements != expected:
            raise ValueError("blocking requirements do not match evaluated requirements")
        if self.sufficient:
            if (
                not any(
                    item.lifecycle in {RequirementLifecycle.ACTIVE, RequirementLifecycle.SATISFIED}
                    for item in self.requirements
                )
                or self.blocking_requirements
                or self.errors
            ):
                raise ValueError(
                    "a sufficient result must have requirements and no blockers or errors"
                )
            if self.provenance is None or not self.provenance.decision_ids:
                raise ValueError("a sufficient result requires an audited decision")
            from .config import Limits
            from .exceptions import DependencyError
            from .policy import apply_blocking_policy

            try:
                evaluated = apply_blocking_policy(
                    self.requirements,
                    self.assumptions,
                    require_optional=self.require_optional,
                    allow_assumptions=self.allow_assumptions,
                    limits=Limits(
                        max_requirements=max(256, len(self.requirements)),
                        max_dependency_edges=max(
                            2_048, sum(len(item.dependencies) for item in self.requirements)
                        ),
                    ),
                )
            except DependencyError as exc:
                raise ValueError("a sufficient result has invalid dependencies") from exc
            if any(item.blocking for item in evaluated):
                raise ValueError("a sufficient result violates blocking policy")
            approved = {
                item.requirement_id
                for item in self.assumptions
                if self.allow_assumptions
                and item.status is AssumptionStatus.APPROVED
                and item.risk is RiskLevel.LOW
                and item.reversible
            }
            if any(
                item.status is RequirementStatus.ASSUMED and item.id not in approved
                for item in self.requirements
                if item.lifecycle in {RequirementLifecycle.ACTIVE, RequirementLifecycle.SATISFIED}
            ):
                raise ValueError("a sufficient result contains an unapproved assumption")
        return self
