"""Sanitized observations emitted to an explicitly configured callback."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from .models import FrozenModel


class Observation(FrozenModel):
    """Low-cardinality operation data and opaque trace correlation IDs."""

    operation: Literal[
        "assessment", "model", "model_retry", "policy", "clarification", "provenance"
    ]
    outcome: Literal[
        "ok",
        "failed",
        "retry",
        "sufficient",
        "insufficient",
        "cancelled",
        "iteration_limit_reached",
    ]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    assessment_id: UUID
    run_id: UUID
    evidence_ids: tuple[UUID, ...] = ()
    decision_id: UUID | None = None
    link_ids: tuple[UUID, ...] = ()
