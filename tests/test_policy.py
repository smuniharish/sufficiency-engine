from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sufficiency_engine.config import Limits
from sufficiency_engine.exceptions import DependencyError
from sufficiency_engine.models import (
    AnswerConstraints,
    AssessmentResult,
    AssessmentStatus,
    Assumption,
    AssumptionStatus,
    ProvenanceReferences,
    Requirement,
    RequirementClassification,
    RequirementLifecycle,
    RequirementStatus,
    RiskLevel,
)
from sufficiency_engine.policy import apply_blocking_policy, transition_requirement


def requirement(
    key="key",
    classification=RequirementClassification.MANDATORY,
    status=RequirementStatus.UNRESOLVED,
    **kwargs,
):
    evidence = (uuid4(),) if status is RequirementStatus.AVAILABLE else ()
    return Requirement(
        key=key,
        description=key,
        classification=classification,
        status=status,
        source_evidence_ids=evidence,
        **kwargs,
    )


@given(
    classification=st.sampled_from(list(RequirementClassification)),
    status=st.sampled_from(list(RequirementStatus)),
    require_optional=st.booleans(),
)
def test_blocking_table_without_approved_assumptions(classification, status, require_optional):
    item = requirement(classification=classification, status=status, blocking=True)
    (evaluated,) = apply_blocking_policy([item], require_optional=require_optional)
    required = classification is not RequirementClassification.OPTIONAL or require_optional
    assert evaluated.blocking is (required and status is not RequirementStatus.AVAILABLE)
    assert evaluated.id == item.id


@pytest.mark.parametrize(
    ("enabled", "approval", "risk", "reversible", "blocking"),
    [
        (True, AssumptionStatus.APPROVED, RiskLevel.LOW, True, False),
        (False, AssumptionStatus.APPROVED, RiskLevel.LOW, True, True),
        (True, AssumptionStatus.PROPOSED, RiskLevel.LOW, True, True),
        (True, AssumptionStatus.REJECTED, RiskLevel.LOW, True, True),
        (True, AssumptionStatus.APPROVED, RiskLevel.HIGH, True, True),
        (True, AssumptionStatus.APPROVED, RiskLevel.LOW, False, True),
    ],
)
def test_assumptions_require_approval_and_safe_policy(
    enabled, approval, risk, reversible, blocking
):
    item = requirement(status=RequirementStatus.ASSUMED)
    assumption = Assumption(
        requirement_id=item.id,
        description="A default",
        value=0,
        risk=risk,
        reversible=reversible,
        status=approval,
    )
    (evaluated,) = apply_blocking_policy([item], [assumption], allow_assumptions=enabled)
    assert evaluated.blocking is blocking


def test_transitive_optional_dependencies_block_without_reclassification():
    leaf = requirement("leaf", classification=RequirementClassification.OPTIONAL)
    middle = requirement(
        "middle",
        classification=RequirementClassification.OPTIONAL,
        status=RequirementStatus.AVAILABLE,
        dependencies=(leaf.id,),
    )
    root = requirement("root", status=RequirementStatus.AVAILABLE, dependencies=(middle.id,))
    result = apply_blocking_policy([root, middle, leaf])
    assert [item.key for item in result if item.blocking] == ["leaf"]
    assert result[-1].classification is RequirementClassification.OPTIONAL


def test_unrelated_optional_and_retired_requirements_do_not_block():
    optional = requirement("optional", classification=RequirementClassification.OPTIONAL)
    retired = requirement("retired", lifecycle=RequirementLifecycle.RETIRED, blocking=True)
    assert not any(item.blocking for item in apply_blocking_policy([optional, retired]))


def test_diamond_dependencies_are_not_cycles():
    leaf = requirement("leaf")
    left = requirement("left", dependencies=(leaf.id,))
    right = requirement("right", dependencies=(leaf.id,))
    root = requirement("root", dependencies=(left.id, right.id))
    assert len(apply_blocking_policy([root, left, right, leaf])) == 4


def test_cycles_unknown_and_inactive_dependencies_fail_closed():
    first = requirement("first")
    second = requirement("second", dependencies=(first.id,))
    cyclic = first.model_copy(update={"dependencies": (second.id,)})
    with pytest.raises(DependencyError, match="cycle"):
        apply_blocking_policy([cyclic, second])
    with pytest.raises(DependencyError, match="unknown or inactive"):
        apply_blocking_policy([second])
    retired = first.model_copy(update={"lifecycle": RequirementLifecycle.RETIRED})
    with pytest.raises(DependencyError, match="unknown or inactive"):
        apply_blocking_policy([retired, second])


def test_duplicate_ids_keys_edges_and_limits_are_rejected():
    item = requirement()
    with pytest.raises(DependencyError, match="duplicate requirement ID"):
        apply_blocking_policy([item, item])
    with pytest.raises(DependencyError, match="duplicate requirement key"):
        apply_blocking_policy([item, requirement()])
    duplicate_edge = requirement("other", dependencies=(item.id, item.id))
    with pytest.raises(DependencyError, match="duplicate dependency"):
        apply_blocking_policy([item, duplicate_edge])
    with pytest.raises(DependencyError, match="requirement limit"):
        apply_blocking_policy([item, requirement("other")], limits=Limits(max_requirements=1))
    with pytest.raises(DependencyError, match="dependency edge limit"):
        apply_blocking_policy([item, duplicate_edge], limits=Limits(max_dependency_edges=1))


def test_lifecycle_transitions_preserve_identity_and_reject_resurrection():
    original = requirement()
    satisfied = transition_requirement(original, RequirementLifecycle.SATISFIED)
    assert satisfied.id == original.id
    assert satisfied.updated_at >= original.updated_at
    assert transition_requirement(satisfied, RequirementLifecycle.SATISFIED) is satisfied
    active = transition_requirement(satisfied, RequirementLifecycle.ACTIVE)
    retired = transition_requirement(active, RequirementLifecycle.RETIRED)
    with pytest.raises(ValueError, match="invalid requirement lifecycle"):
        transition_requirement(retired, RequirementLifecycle.ACTIVE)


@given(
    st.lists(
        st.sampled_from([RequirementLifecycle.ACTIVE, RequirementLifecycle.SATISFIED]),
        max_size=30,
    ),
    st.sampled_from([RequirementLifecycle.SUPERSEDED, RequirementLifecycle.RETIRED]),
)
def test_generated_lifecycle_paths_preserve_identity_and_terminal_states(path, terminal):
    original = requirement(status=RequirementStatus.AVAILABLE)
    current = original
    for target in [*path, terminal]:
        previous = current
        current = transition_requirement(current, target)
        assert current.id == original.id
        assert current.source_evidence_ids == original.source_evidence_ids
        assert current.classification is original.classification
        assert current.status is original.status
        assert current.created_at == original.created_at
        assert current.updated_at >= previous.updated_at
    for target in RequirementLifecycle:
        if target is terminal:
            assert transition_requirement(current, target) is current
        else:
            with pytest.raises(ValueError, match="invalid requirement lifecycle"):
                transition_requirement(current, target)


def test_available_requires_evidence():
    with pytest.raises(ValidationError, match="need evidence"):
        Requirement(
            key="x",
            description="X",
            classification=RequirementClassification.MANDATORY,
            status=RequirementStatus.AVAILABLE,
        )


def test_sufficient_result_requires_audited_decision_and_consistent_blockers():
    item = requirement(status=RequirementStatus.AVAILABLE)
    common = {
        "assessment_id": uuid4(),
        "session_id": "session",
        "status": AssessmentStatus.SUFFICIENT,
        "sufficient": True,
        "requirements": (item,),
        "completion_reason": "Ready",
    }
    with pytest.raises(ValidationError, match="audited decision"):
        AssessmentResult(**common)
    result = AssessmentResult(
        **common, provenance=ProvenanceReferences(run_id=uuid4(), decision_ids=(uuid4(),))
    )
    assert result.sufficient
    with pytest.raises(ValidationError, match="sufficient must match"):
        AssessmentResult(**{**common, "sufficient": False})
    with pytest.raises(ValidationError, match="blocking requirements"):
        AssessmentResult(**{**common, "blocking_requirements": (item,)})
    unresolved = requirement()
    with pytest.raises(ValidationError, match="blocking policy"):
        AssessmentResult(
            **{**common, "requirements": (unresolved,)},
            provenance=ProvenanceReferences(run_id=uuid4(), decision_ids=(uuid4(),)),
        )


@pytest.mark.parametrize(
    "constraints",
    [{"min_length": 2, "max_length": 1}, {"minimum": 2, "maximum": 1}],
)
def test_contradictory_answer_constraints_are_rejected(constraints):
    with pytest.raises(ValidationError, match="exceeds"):
        AnswerConstraints(**constraints)


def test_equal_answer_constraint_bounds_are_valid():
    constraints = AnswerConstraints(min_length=2, max_length=2, minimum=1, maximum=1)
    assert constraints.min_length == constraints.max_length
    assert constraints.minimum == constraints.maximum


def test_requirement_cannot_be_updated_before_it_was_created():
    created = datetime.now(UTC)
    with pytest.raises(ValidationError, match="precedes"):
        requirement(created_at=created, updated_at=created - timedelta(seconds=1))


def test_sufficient_result_rejects_empty_inactive_and_invalid_dependencies():
    item = requirement(status=RequirementStatus.AVAILABLE)
    common = {
        "assessment_id": uuid4(),
        "session_id": "session",
        "status": AssessmentStatus.SUFFICIENT,
        "sufficient": True,
        "completion_reason": "Ready",
        "provenance": ProvenanceReferences(run_id=uuid4(), decision_ids=(uuid4(),)),
    }
    with pytest.raises(ValidationError, match="must have requirements"):
        AssessmentResult(**common)
    inactive = item.model_copy(update={"lifecycle": RequirementLifecycle.RETIRED})
    with pytest.raises(ValidationError, match="must have requirements"):
        AssessmentResult(**common, requirements=(inactive,))
    unknown_dependency = item.model_copy(update={"dependencies": (uuid4(),)})
    with pytest.raises(ValidationError, match="invalid dependencies"):
        AssessmentResult(**common, requirements=(unknown_dependency,))


def test_optional_assumption_cannot_enter_sufficient_result_without_approval():
    item = requirement(
        classification=RequirementClassification.OPTIONAL,
        status=RequirementStatus.ASSUMED,
    )
    common = {
        "assessment_id": uuid4(),
        "session_id": "session",
        "status": AssessmentStatus.SUFFICIENT,
        "sufficient": True,
        "requirements": (item,),
        "completion_reason": "Ready",
        "provenance": ProvenanceReferences(run_id=uuid4(), decision_ids=(uuid4(),)),
    }
    with pytest.raises(ValidationError, match="unapproved assumption"):
        AssessmentResult(**common)
    assumption = Assumption(
        requirement_id=item.id,
        description="A safe default",
        value="local",
        risk=RiskLevel.LOW,
        reversible=True,
        status=AssumptionStatus.APPROVED,
    )
    assert AssessmentResult(**common, allow_assumptions=True, assumptions=(assumption,)).sufficient
