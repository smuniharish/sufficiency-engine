"""Deterministic readiness, dependency, and lifecycle policy."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from .config import Limits
from .exceptions import DependencyError
from .models import (
    Assumption,
    AssumptionStatus,
    Requirement,
    RequirementClassification,
    RequirementLifecycle,
    RequirementStatus,
    RiskLevel,
)

_INACTIVE = frozenset({RequirementLifecycle.SUPERSEDED, RequirementLifecycle.RETIRED})
_TRANSITIONS = {
    RequirementLifecycle.ACTIVE: frozenset(
        {
            RequirementLifecycle.SATISFIED,
            RequirementLifecycle.SUPERSEDED,
            RequirementLifecycle.RETIRED,
        }
    ),
    RequirementLifecycle.SATISFIED: frozenset(
        {
            RequirementLifecycle.ACTIVE,
            RequirementLifecycle.SUPERSEDED,
            RequirementLifecycle.RETIRED,
        }
    ),
    RequirementLifecycle.SUPERSEDED: frozenset(),
    RequirementLifecycle.RETIRED: frozenset(),
}


def transition_requirement(
    requirement: Requirement, lifecycle: RequirementLifecycle
) -> Requirement:
    """Move a requirement through the allowed lifecycle without changing its ID.

    Raises:
        ValueError: If the transition is not permitted.
    """
    if lifecycle is requirement.lifecycle:
        return requirement
    if lifecycle not in _TRANSITIONS[requirement.lifecycle]:
        raise ValueError("invalid requirement lifecycle transition")
    return requirement.model_copy(update={"lifecycle": lifecycle, "updated_at": datetime.now(UTC)})


def _validate_graph(requirements: Sequence[Requirement], limits: Limits) -> dict[UUID, Requirement]:
    if len(requirements) > limits.max_requirements:
        raise DependencyError("requirement limit exceeded")
    by_id = {requirement.id: requirement for requirement in requirements}
    if len(by_id) != len(requirements):
        raise DependencyError("duplicate requirement ID")
    if len({requirement.key for requirement in requirements}) != len(requirements):
        raise DependencyError("duplicate requirement key")
    if (
        sum(len(requirement.dependencies) for requirement in requirements)
        > limits.max_dependency_edges
    ):
        raise DependencyError("dependency edge limit exceeded")

    for requirement in requirements:
        if requirement.lifecycle in _INACTIVE:
            continue
        if len(set(requirement.dependencies)) != len(requirement.dependencies):
            raise DependencyError("duplicate dependency")
        for dependency_id in requirement.dependencies:
            dependency = by_id.get(dependency_id)
            if dependency is None or dependency.lifecycle in _INACTIVE:
                raise DependencyError("dependency is unknown or inactive")

    visited: set[UUID] = set()
    visiting: set[UUID] = set()
    for requirement in requirements:
        if requirement.lifecycle in _INACTIVE or requirement.id in visited:
            continue
        stack: list[tuple[UUID, bool]] = [(requirement.id, False)]
        while stack:
            current, leaving = stack.pop()
            if leaving:
                visiting.remove(current)
                visited.add(current)
                continue
            if current in visited:
                continue
            if current in visiting:
                raise DependencyError("requirement dependency cycle")
            visiting.add(current)
            stack.append((current, True))
            stack.extend((dependency, False) for dependency in by_id[current].dependencies)
    return by_id


def apply_blocking_policy(
    requirements: Sequence[Requirement],
    assumptions: Sequence[Assumption] = (),
    *,
    require_optional: bool = False,
    allow_assumptions: bool = False,
    limits: Limits | None = None,
) -> tuple[Requirement, ...]:
    """Compute blocking deterministically, including required prerequisites.

    An assumption satisfies a requirement only when assumptions are enabled,
    the application explicitly approved it, and its risk is low and reversible.
    Model-provided blocking values are always replaced.

    Raises:
        DependencyError: If the requirement graph or its bounds are invalid.
    """
    by_id = _validate_graph(requirements, limits or Limits())
    required: set[UUID] = set()
    pending = [
        requirement.id
        for requirement in requirements
        if requirement.lifecycle not in _INACTIVE
        and (
            require_optional or requirement.classification is not RequirementClassification.OPTIONAL
        )
    ]
    while pending:
        current = pending.pop()
        if current not in required:
            required.add(current)
            pending.extend(by_id[current].dependencies)

    approved = {
        assumption.requirement_id
        for assumption in assumptions
        if allow_assumptions
        and assumption.status is AssumptionStatus.APPROVED
        and assumption.risk is RiskLevel.LOW
        and assumption.reversible
    }
    evaluated = []
    for requirement in requirements:
        available = requirement.status is RequirementStatus.AVAILABLE or (
            requirement.status is RequirementStatus.ASSUMED and requirement.id in approved
        )
        evaluated.append(
            requirement.model_copy(
                update={"blocking": requirement.id in required and not available}
            )
        )
    return tuple(evaluated)
