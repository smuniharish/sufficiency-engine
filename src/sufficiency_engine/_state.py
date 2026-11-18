"""Versioned internal assessment state shared by standalone and graph execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ._discovery import RequirementProposal
from .models import (
    Answer,
    AssessmentResult,
    AssessmentStatus,
    Assumption,
    ClarificationQuestion,
    Decision,
    Diagnostic,
    Requirement,
    RequirementLineage,
)
from .persistence import SessionScope
from .provenance import AuditIntent


class AssessmentState(BaseModel):
    """Serializable state; host checkpoints or persistence own its storage."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: Literal[1] = 1
    scope: SessionScope
    task: str
    source_references: tuple[UUID, ...] = ()
    assessment_id: UUID = Field(default_factory=uuid4)
    run_id: UUID = Field(default_factory=uuid4)
    started_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    phase: Literal["discover", "waiting", "finished"] = "discover"
    iterations: int = Field(default=0, ge=0)
    requirements: list[Requirement] = Field(default_factory=list)
    proposals: list[RequirementProposal] = Field(default_factory=list)
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    answers: list[Answer] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    lineage: list[RequirementLineage] = Field(default_factory=list)
    warnings: list[Diagnostic] = Field(default_factory=list)
    errors: list[Diagnostic] = Field(default_factory=list)
    pending_audit: AuditIntent | None = None
    pending_question_ids: list[UUID] = Field(default_factory=list)
    pending_assumption_ids: list[UUID] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    decision_ids: list[UUID] = Field(default_factory=list)
    link_ids: list[UUID] = Field(default_factory=list)
    terminal_status: AssessmentStatus | None = None
    interaction_dispatched: bool = False
    deleting: bool = False
    notification: Literal["not_started", "dispatched", "done"] = "not_started"
    result: AssessmentResult | None = None
