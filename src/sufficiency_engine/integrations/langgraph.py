"""Checkpoint-safe task-entry integration for LangGraph 1.x."""

from __future__ import annotations

import time
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from .._state import AssessmentState
from ..engine import SufficiencyEngine
from ..exceptions import ClarificationError, ConfigurationError, ProvenanceError, SufficiencyError
from ..models import AssessmentStatus, Diagnostic, InteractionResponse


class AssessmentGraphState(BaseModel):
    """Input and output shared by the assessment subgraph and its host."""

    model_config = ConfigDict(extra="forbid")

    task: str
    session_id: str | None = None
    source_references: list[str] = Field(default_factory=list)
    assessment: dict[str, JsonValue] | None = None
    response: JsonValue = None
    readiness: dict[str, JsonValue] | None = None


def build_assessment_graph(
    engine: SufficiencyEngine, *, checkpointer: BaseCheckpointSaver | None = None
):
    """Build a task-entry subgraph using LangGraph's authoritative checkpoints.

    The host owns the checkpointer and must resume with the same thread ID.
    No standalone session snapshot is written. The host consumes ``readiness``
    and owns terminal notification; ``command_call`` is not invoked by this
    adapter because a restarted graph node could replay external side effects.

    Args:
        engine: Engine providing model, policy, and AGXAI capabilities.
        checkpointer: A saver for standalone use; a parent graph may instead
            supply its own checkpointer to the compiled subgraph.
    """

    async def prepare(state: AssessmentGraphState) -> dict[str, JsonValue]:
        task = state.task
        if not isinstance(task, str):
            raise ConfigurationError("graph state must include a task")
        saved = state.assessment
        if saved is None:
            scope = engine._scope(state.session_id or uuid4().hex)
            try:
                references = tuple(UUID(item) for item in state.source_references)
            except ValueError as exc:
                raise ConfigurationError("source references must be UUIDs") from exc
            assessment = engine._new_state(task, scope, references)
        else:
            try:
                assessment = AssessmentState.model_validate(saved)
            except ValidationError as exc:
                raise ConfigurationError("graph assessment state is invalid") from exc
            expected_scope = engine._scope(state.session_id or assessment.scope.session_id)
            if assessment.scope != expected_scope or assessment.task != task:
                raise ConfigurationError("graph assessment does not match task or session scope")
        if assessment.phase == "discover" and assessment.pending_audit is None:
            try:
                await engine._discover_and_plan(assessment)
            except SufficiencyError as exc:
                assessment.errors.append(
                    Diagnostic(code=exc.code, message=str(exc), retryable=exc.retryable)
                )
                engine._prepare_terminal(assessment, AssessmentStatus.FAILED)
        return {
            "session_id": assessment.scope.session_id,
            "assessment": assessment.model_dump(mode="json"),
            "readiness": None,
        }

    async def audit(state: AssessmentGraphState) -> dict[str, JsonValue]:
        assessment = AssessmentState.model_validate(state.assessment)
        if assessment.pending_audit is not None:
            try:
                await engine._commit_audit(assessment)
            except ProvenanceError:
                failed = engine._failed_result(
                    assessment,
                    "provenance_error",
                    "Required provenance could not be committed; retry the checkpointed intent.",
                    retryable=True,
                )
                return {
                    "assessment": assessment.model_dump(mode="json"),
                    "readiness": failed.model_dump(mode="json"),
                }
        return {
            "assessment": assessment.model_dump(mode="json"),
            "readiness": assessment.result.model_dump(mode="json") if assessment.result else None,
        }

    def route(graph_state: AssessmentGraphState) -> str:
        if graph_state.readiness is not None:
            return "done"
        return "interrupt"

    def interrupt_node(state: AssessmentGraphState) -> dict[str, JsonValue]:
        assessment = AssessmentState.model_validate(state.assessment)
        value = interrupt(engine._payload(assessment).model_dump(mode="json"))
        return {"response": value}

    async def apply_response(state: AssessmentGraphState) -> dict[str, JsonValue]:
        assessment = AssessmentState.model_validate(state.assessment)
        try:
            started = time.perf_counter()
            response = InteractionResponse.model_validate(state.response)
            engine._apply_response(assessment, response)
            await engine._observe(
                assessment,
                "clarification",
                "cancelled" if response.cancelled else "ok",
                time.perf_counter() - started,
            )
        except (ValidationError, ClarificationError):
            engine._reject_response(assessment)
        return {"assessment": assessment.model_dump(mode="json"), "response": None}

    builder = StateGraph(AssessmentGraphState)
    builder.add_node("prepare", prepare)
    builder.add_node("audit", audit)
    builder.add_node("interrupt", interrupt_node)
    builder.add_node("apply_response", apply_response)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "audit")
    builder.add_conditional_edges("audit", route, {"done": END, "interrupt": "interrupt"})
    builder.add_edge("interrupt", "apply_response")
    builder.add_edge("apply_response", "prepare")
    return builder.compile(checkpointer=checkpointer, name="sufficiency_assessment")
