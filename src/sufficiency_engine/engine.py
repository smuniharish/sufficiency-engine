"""Async-first, provider-independent task readiness assessment."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID, uuid4, uuid5

from pydantic import JsonValue, ValidationError

from ._callbacks import invoke
from ._clarification import combine_related_questions, deduplicate_questions, validate_answer
from ._discovery import DiscoveryResponse, RequirementProposal, discover
from ._state import AssessmentState
from .config import EngineConfig, Limits
from .embedding import EmbeddingModelABC
from .exceptions import (
    CallbackError,
    ClarificationError,
    ConfigurationError,
    ModelResponseError,
    PersistenceError,
    ProvenanceError,
    SerializationError,
    SessionConflictError,
    SufficiencyError,
)
from .models import (
    Answer,
    AnswerStatus,
    AnswerSubmission,
    AssessmentResult,
    AssessmentStatus,
    Assumption,
    AssumptionStatus,
    ClarificationPayload,
    ClarificationQuestion,
    Decision,
    Diagnostic,
    InteractionResponse,
    NecessityDecision,
    ProvenanceReferences,
    QuestionStatus,
    Requirement,
    RequirementClassification,
    RequirementLifecycle,
    RequirementLineage,
    RequirementStatus,
    RiskLevel,
)
from .persistence import InMemoryPersistence, PersistenceABC, SessionClaim, SessionScope
from .policy import apply_blocking_policy, transition_requirement
from .provenance import AGXAIAudit
from .telemetry import Observation

_COMPLETION_REASONS = {
    AssessmentStatus.SUFFICIENT: "All discovered required information is supported and audited.",
    AssessmentStatus.INSUFFICIENT: "The supplied information does not establish readiness.",
    AssessmentStatus.CANCELLED: "The application cancelled the assessment.",
    AssessmentStatus.ITERATION_LIMIT_REACHED: "The clarification iteration limit was reached.",
    AssessmentStatus.FAILED: "The assessment could not be completed safely.",
}
_T = TypeVar("_T")


class SufficiencyEngine:
    """Assess one task without executing it or managing the host's context.

    Args:
        model_call: Sync or async callback accepting provider-neutral messages.
        interrupt_call: Optional sync or async clarification callback.
        command_call: Optional sync or async terminal-result callback.
        max_iterations: Maximum interaction/reassessment cycles.
        max_model_retries: Retries for explicitly transient model failures.
        require_optional: Whether optional requirements also block readiness.
        allow_assumptions: Whether safe, explicitly approved assumptions may satisfy requirements.
        limits: Resource and callback timeout limits.
        persistence: Application-owned session store; defaults to isolated in-memory storage.
        audit: Strict AGXAI integration; defaults to real in-memory AGXAI stores.
        embedding_model: Optional application-owned duplicate-candidate model.
        telemetry_call: Optional callback receiving sanitized engine observations.
        application_id: Trusted opaque application scope.
        tenant_id: Trusted opaque tenant scope.

    Synchronous callbacks run in a worker thread. Timeout or cancellation cannot
    forcibly stop an already running synchronous callback. The host must enforce
    authorization for session and tenant identifiers.
    """

    def __init__(
        self,
        *,
        model_call: Callable[..., object],
        interrupt_call: Callable[..., object] | None = None,
        command_call: Callable[..., object] | None = None,
        max_iterations: int = 5,
        max_model_retries: int = 2,
        require_optional: bool = False,
        allow_assumptions: bool = False,
        limits: Limits | None = None,
        persistence: PersistenceABC | None = None,
        audit: AGXAIAudit | None = None,
        embedding_model: EmbeddingModelABC | None = None,
        telemetry_call: Callable[..., object] | None = None,
        application_id: str = "application",
        tenant_id: str = "default",
    ) -> None:
        if not callable(model_call):
            raise ConfigurationError("model_call must be callable")
        if interrupt_call is not None and not callable(interrupt_call):
            raise ConfigurationError("interrupt_call must be callable")
        if command_call is not None and not callable(command_call):
            raise ConfigurationError("command_call must be callable")
        if telemetry_call is not None and not callable(telemetry_call):
            raise ConfigurationError("telemetry_call must be callable")
        try:
            self.config = EngineConfig(
                max_iterations=max_iterations,
                max_model_retries=max_model_retries,
                require_optional=require_optional,
                allow_assumptions=allow_assumptions,
                limits=limits or Limits(),
            )
            SessionScope(
                application_id=application_id, tenant_id=tenant_id, session_id="validation"
            )
        except ValidationError as exc:
            raise ConfigurationError("invalid engine configuration") from exc
        self.model_call = model_call
        self.interrupt_call = interrupt_call
        self.command_call = command_call
        self.telemetry_call = telemetry_call
        self.persistence = persistence if persistence is not None else InMemoryPersistence()
        self.audit = audit if audit is not None else AGXAIAudit()
        if not isinstance(self.persistence, PersistenceABC):
            raise ConfigurationError("persistence must implement PersistenceABC")
        if not isinstance(self.audit, AGXAIAudit):
            raise ConfigurationError("audit must be an AGXAIAudit")
        if embedding_model is not None and not isinstance(embedding_model, EmbeddingModelABC):
            raise ConfigurationError("embedding_model must implement EmbeddingModelABC")
        self.embedding_model = embedding_model
        self.application_id = application_id
        self.tenant_id = tenant_id
        self._lease_seconds = max(60.0, self.config.limits.callback_timeout_seconds * 3)

    def _scope(self, session_id: str) -> SessionScope:
        try:
            return SessionScope(
                application_id=self.application_id, tenant_id=self.tenant_id, session_id=session_id
            )
        except ValidationError as exc:
            raise ConfigurationError("session ID must be an opaque identifier") from exc

    def _new_state(
        self, task: str, scope: SessionScope, source_references: tuple[UUID, ...]
    ) -> AssessmentState:
        self._validate_task(task)
        if len(source_references) > self.config.limits.max_requirements:
            raise ConfigurationError("source reference limit exceeded")
        if any(not isinstance(reference, UUID) for reference in source_references):
            raise ConfigurationError("source references must be UUIDs")
        if len(set(source_references)) != len(source_references):
            raise ConfigurationError("source references must be unique")
        return AssessmentState(scope=scope, task=task, source_references=source_references)

    def _validate_task(self, task: str) -> None:
        if not isinstance(task, str) or not task.strip():
            raise ConfigurationError("task input must be nonempty text")
        try:
            size = len(task.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ConfigurationError("task input must be valid UTF-8") from exc
        if size > self.config.limits.max_input_bytes:
            raise ConfigurationError("task input exceeds the configured size limit")

    async def execute(
        self,
        *,
        input: str,
        session_id: str | None = None,
        resume: bool = False,
        response: InteractionResponse | Mapping[str, object] | None = None,
        source_references: tuple[UUID, ...] = (),
        preview_only: bool = False,
    ) -> AssessmentResult:
        """Assess a task or resume an existing session.

        A previously dispatched interaction is never automatically replayed after
        failure or interruption. Supply ``response`` explicitly when resuming an
        ambiguous interaction. A failed audit remains pending and is retried
        using the same stable identifiers on resume.

        With ``preview_only=True``, return an audited readiness snapshot with
        missing required and useful optional questions. No interaction or terminal
        callback is dispatched, and no session is read or saved. The snapshot
        cannot accept answers or be resumed; a later assessment starts separately.

        Raises:
            ConfigurationError: If input, resume options, or identifiers are invalid.
            PersistenceError: If session state cannot be safely loaded or saved.
            CallbackError: If terminal notification fails or has an ambiguous outcome.
        """
        self._validate_task(input)
        if not isinstance(preview_only, bool):
            raise ConfigurationError("preview_only must be a boolean")
        if preview_only and (resume or response is not None):
            raise ConfigurationError("preview_only cannot be combined with resume or response")
        if resume and session_id is None:
            raise ConfigurationError("resuming requires a session ID")
        if response is not None and not resume:
            raise ConfigurationError("an explicit response requires resume=True")
        scope = self._scope(session_id or uuid4().hex)
        if preview_only:
            return await self._preview(self._new_state(input, scope, source_references))
        owner = uuid4()
        claim = await self._persistence_call(
            self.persistence.acquire(scope, owner, self._lease_seconds)
        )
        try:
            stored = await self._persistence_call(self.persistence.load(scope))
            if resume:
                if stored is None:
                    raise ConfigurationError("session does not exist")
                try:
                    state = AssessmentState.model_validate(stored.state)
                except ValidationError as exc:
                    raise SerializationError(
                        "session state has an invalid or unsupported schema"
                    ) from exc
                if state.scope != scope or state.task != input:
                    raise ConfigurationError("resume input or session scope does not match")
                if state.deleting:
                    raise PersistenceError("session deletion is pending; retry delete_session")
                if source_references and source_references != state.source_references:
                    raise ConfigurationError("resume source references do not match")
                revision: int | None = stored.revision
            else:
                if stored is not None:
                    raise SessionConflictError("session already exists")
                state = self._new_state(input, scope, source_references)
                revision = None
                revision = await self._save(state, revision, claim)

            supplied = response
            while True:
                await self._persistence_call(
                    self.persistence.renew(scope, claim, self._lease_seconds)
                )
                if state.pending_audit is not None:
                    try:
                        await self._commit_audit(state)
                    except ProvenanceError:
                        return self._failed_result(
                            state,
                            "provenance_error",
                            "Required provenance could not be committed; "
                            "the session can be resumed.",
                            retryable=True,
                        )
                    revision = await self._save(state, revision, claim)
                    continue
                if state.phase == "finished":
                    if supplied is not None:
                        raise ConfigurationError(
                            "cannot submit a response to a finished assessment"
                        )
                    if state.result is None:
                        raise SerializationError("finished session has no result")
                    if self.command_call is not None and state.notification == "dispatched":
                        raise CallbackError(
                            "terminal notification outcome is ambiguous and will not be replayed"
                        )
                    if self.command_call is not None and state.notification == "not_started":
                        state.notification = "dispatched"
                        revision = await self._save(state, revision, claim)
                        try:
                            await invoke(
                                self.command_call,
                                state.result,
                                self.config.limits.callback_timeout_seconds,
                            )
                        except Exception as exc:
                            raise CallbackError(
                                "terminal notification failed; it may have run "
                                "and will not be replayed"
                            ) from exc
                        state.notification = "done"
                        revision = await self._save(state, revision, claim)
                    return state.result
                if state.phase == "discover":
                    try:
                        await self._discover_and_plan(state)
                    except SufficiencyError as exc:
                        state.errors.append(
                            Diagnostic(code=exc.code, message=str(exc), retryable=exc.retryable)
                        )
                        self._prepare_terminal(state, AssessmentStatus.FAILED)
                    revision = await self._save(state, revision, claim)
                    continue

                if supplied is None:
                    if state.interaction_dispatched:
                        return self._failed_result(
                            state,
                            "interaction_ambiguous",
                            "The prior interaction may have run; resume with an explicit response.",
                            retryable=True,
                        )
                    if self.interrupt_call is None:
                        self._prepare_terminal(state, AssessmentStatus.INSUFFICIENT)
                        revision = await self._save(state, revision, claim)
                        continue
                    state.interaction_dispatched = True
                    revision = await self._save(state, revision, claim)
                    try:
                        supplied = await invoke(
                            self.interrupt_call,
                            self._payload(state),
                            self.config.limits.callback_timeout_seconds,
                        )
                    except Exception:
                        return self._failed_result(
                            state,
                            "clarification_callback_error",
                            "Clarification callback failed; resume with an explicit response.",
                            retryable=True,
                        )
                try:
                    started = time.perf_counter()
                    parsed = InteractionResponse.model_validate(supplied)
                    self._apply_response(state, parsed)
                    await self._observe(
                        state,
                        "clarification",
                        "cancelled" if parsed.cancelled else "ok",
                        time.perf_counter() - started,
                    )
                except (ValidationError, ClarificationError):
                    self._reject_response(state)
                    revision = await self._save(state, revision, claim)
                    if state.phase == "finished":
                        supplied = None
                        continue
                    return self._failed_result(
                        state,
                        "clarification_error",
                        "Clarification response is invalid; resume with a corrected response.",
                        retryable=True,
                    )
                supplied = None
                revision = await self._save(state, revision, claim)
        finally:
            await self._persistence_call(self.persistence.release(scope, claim))

    async def delete_session(self, session_id: str) -> None:
        """Delete a saved session and its AGXAI run; previews and checkpoints are separate."""
        scope = self._scope(session_id)
        claim = await self._persistence_call(
            self.persistence.acquire(scope, uuid4(), self._lease_seconds)
        )
        try:
            stored = await self._persistence_call(self.persistence.load(scope))
            if stored is None:
                return
            try:
                state = AssessmentState.model_validate(stored.state)
            except ValidationError as exc:
                raise SerializationError(
                    "session state has an invalid or unsupported schema"
                ) from exc
            if state.scope != scope:
                raise SerializationError("stored session scope does not match")
            state.deleting = True
            revision = await self._save(state, stored.revision, claim)
            from agxai import ExecutionContext

            context = ExecutionContext(
                application_id=scope.application_id,
                tenant_id=scope.tenant_id,
                graph_id="sufficiency-engine",
                run_id=state.run_id,
                thread_id=scope.session_id,
            )
            await self.audit.delete_run(context)
            await self._persistence_call(
                self.persistence.delete(scope, expected_revision=revision, claim=claim)
            )
        finally:
            await self._persistence_call(self.persistence.release(scope, claim))

    async def delete_preview_audit(self, *, session_id: str, run_id: UUID) -> None:
        """Delete one preview's AGXAI run in this engine's application and tenant.

        Use the session ID and preview_run_id returned by execute. No session is
        read or modified. The host must authorize the run ID: AGXAI deletion is
        scoped by application, tenant, and run, not by session ID or run type.
        Repeating a completed or partially failed deletion is safe.

        Raises:
            ConfigurationError: If either identifier is invalid.
            ProvenanceError: If deletion fails or its outcome is ambiguous; retry.
        """
        scope = self._scope(session_id)
        if not isinstance(run_id, UUID):
            raise ConfigurationError("preview run ID must be a UUID")
        from agxai import ExecutionContext

        context = ExecutionContext(
            application_id=scope.application_id,
            tenant_id=scope.tenant_id,
            graph_id="sufficiency-engine",
            run_id=run_id,
            thread_id=scope.session_id,
        )
        await self.audit.delete_run(context)

    @staticmethod
    async def _persistence_call(operation: Awaitable[_T]) -> _T:
        try:
            return await operation
        except PersistenceError:
            raise
        except Exception as exc:
            raise PersistenceError("session persistence operation failed") from exc

    async def _save(self, state: AssessmentState, revision: int | None, claim: SessionClaim) -> int:
        saved = await self._persistence_call(
            self.persistence.save(
                state.scope,
                state.model_dump(mode="json"),
                expected_revision=revision,
                claim=claim,
            )
        )
        return saved.revision

    def _prior(self, state: AssessmentState) -> list[dict[str, JsonValue]]:
        proposals = {proposal.key: proposal for proposal in state.proposals}
        if any(item.key not in proposals for item in state.requirements):
            raise SerializationError("a stored requirement has no discovery contract")
        return [
            {
                "key": item.key,
                "description": item.description,
                "classification": item.classification.value,
                "status": item.status.value,
                "lifecycle": item.lifecycle.value,
                "answer_type": proposals[item.key].answer_type.value,
                "answer_slot": proposals[item.key].answer_slot,
                "constraints": proposals[item.key].constraints.model_dump(mode="json"),
                "answers": [
                    answer.value
                    for answer in state.answers
                    if answer.requirement_id == item.id and answer.status is AnswerStatus.VALID
                ],
            }
            for item in state.requirements
        ]

    def _evidence_for_quote(
        self, state: AssessmentState, quote: str, requirement_ids: frozenset[UUID]
    ) -> tuple[UUID, ...]:
        """Resolve a quote to the task or to answers owned by ``requirement_ids``.

        Answers are bound to the requirement they were given for, so a quote can never borrow
        another requirement's answer unless explicit lineage names that requirement as a parent.
        """
        if not quote.strip():
            raise ModelResponseError("available requirement has an empty evidence quote")
        if quote in state.task:
            return (uuid5(state.assessment_id, "task-input"),)
        for answer in state.answers:
            if answer.status is AnswerStatus.VALID and answer.requirement_id in requirement_ids:
                text = json.dumps(answer.value, ensure_ascii=False, allow_nan=False)
                if quote in text:
                    return (
                        uuid5(
                            state.assessment_id,
                            f"answer:{answer.question_id}:{answer.requirement_id}",
                        ),
                    )
        raise ModelResponseError("model cited evidence that was not supplied")

    def _reconcile(self, state: AssessmentState, response: DiscoveryResponse) -> None:
        existing = {item.key: item for item in state.requirements}
        prior_proposals = {proposal.key: proposal for proposal in state.proposals}
        prior_keys = set(existing)
        ids = {key: item.id for key, item in existing.items()}
        for proposal in response.requirements:
            ids.setdefault(proposal.key, uuid5(state.assessment_id, f"requirement:{proposal.key}"))
        inherited: dict[str, set[UUID]] = {}
        for change in response.lineage:
            if change.operation == "retire":
                continue
            parent_ids = {existing[key].id for key in change.parent_keys if key in existing}
            for key in change.successor_keys:
                if key not in existing:
                    inherited.setdefault(key, set()).update(parent_ids)
        for proposal in response.requirements:
            previous = existing.get(proposal.key)
            owners = frozenset({ids[proposal.key], *inherited.get(proposal.key, ())})
            if previous is not None and previous.classification is not proposal.classification:
                raise ModelResponseError("an existing requirement changed classification")
            if previous is not None:
                prior = prior_proposals[proposal.key]
                if (
                    previous.description != proposal.description
                    or prior.answer_type is not proposal.answer_type
                    or prior.answer_slot != proposal.answer_slot
                    or prior.constraints != proposal.constraints
                    or previous.lifecycle
                    in {RequirementLifecycle.SUPERSEDED, RequirementLifecycle.RETIRED}
                ):
                    raise ModelResponseError(
                        "requirement identity changed; use explicit superseding lineage"
                    )
            try:
                dependencies = tuple(ids[key] for key in proposal.dependencies)
            except KeyError as exc:
                raise ModelResponseError("model proposed an unknown dependency") from exc
            if proposal.conflicts:
                for quote in proposal.conflicts:
                    self._evidence_for_quote(state, quote, owners)
            if previous is None:
                evidence = ()
                status = RequirementStatus.UNRESOLVED
                if proposal.status == "available" and not proposal.conflicts:
                    evidence = self._evidence_for_quote(
                        state, proposal.evidence_quote or "", owners
                    )
                    status = RequirementStatus.AVAILABLE
                item = Requirement(
                    id=ids[proposal.key],
                    key=proposal.key,
                    description=proposal.description,
                    classification=proposal.classification,
                    status=status,
                    source_evidence_ids=evidence,
                    dependencies=dependencies,
                )
            else:
                evidence = previous.source_evidence_ids
                status = previous.status
                if status is not RequirementStatus.DECLINED:
                    if proposal.conflicts:
                        status = RequirementStatus.UNRESOLVED
                    elif proposal.status == "available":
                        evidence = self._evidence_for_quote(
                            state, proposal.evidence_quote or "", owners
                        )
                        status = RequirementStatus.AVAILABLE
                    elif status is not RequirementStatus.ASSUMED:
                        status = RequirementStatus.UNRESOLVED
                    if status is RequirementStatus.UNRESOLVED:
                        evidence = ()
                        state.answers = [
                            answer.model_copy(
                                update={
                                    "status": AnswerStatus.CONTRADICTORY
                                    if proposal.conflicts
                                    else AnswerStatus.AMBIGUOUS,
                                    "reason": "Reassessment did not establish this requirement.",
                                }
                            )
                            if answer.requirement_id == previous.id
                            and answer.status is AnswerStatus.VALID
                            else answer
                            for answer in state.answers
                        ]
                merged_dependencies = tuple(dict.fromkeys((*previous.dependencies, *dependencies)))
                changed = (
                    previous.description != proposal.description
                    or previous.status is not status
                    or previous.dependencies != merged_dependencies
                )
                item = Requirement.model_validate(
                    {
                        **previous.model_dump(),
                        "description": proposal.description,
                        "status": status,
                        "lifecycle": (
                            RequirementLifecycle.ACTIVE
                            if status is RequirementStatus.UNRESOLVED
                            else previous.lifecycle
                        ),
                        "source_evidence_ids": evidence,
                        "dependencies": merged_dependencies,
                        "updated_at": datetime.now(UTC) if changed else previous.updated_at,
                    }
                )
                if changed:
                    state.lineage.append(
                        RequirementLineage(
                            operation="update", parent_ids=(item.id,), successor_ids=(item.id,)
                        )
                    )
            existing[proposal.key] = item
        self._apply_lineage(state, existing, prior_keys, response)
        state.requirements = list(existing.values())
        proposals = {proposal.key: proposal for proposal in state.proposals}
        proposals.update({proposal.key: proposal for proposal in response.requirements})
        state.proposals = list(proposals.values())

    @staticmethod
    def _apply_lineage(
        state: AssessmentState,
        requirements: dict[str, Requirement],
        prior_keys: set[str],
        response: DiscoveryResponse,
    ) -> None:
        severity = {
            RequirementClassification.OPTIONAL: 0,
            RequirementClassification.MINIMUM: 1,
            RequirementClassification.MANDATORY: 2,
        }
        used_parents: set[str] = set()
        used_successors: set[str] = set()
        replacements: dict[UUID, tuple[UUID, ...]] = {}
        for change in response.lineage:
            parents = set(change.parent_keys)
            successors = set(change.successor_keys)
            if (
                not parents.issubset(prior_keys)
                or not successors.issubset(requirements)
                or successors & prior_keys
                or parents & used_parents
                or successors & used_successors
            ):
                raise ModelResponseError("ambiguous or unknown requirement lineage")
            parent_items = [requirements[key] for key in change.parent_keys]
            successor_items = [requirements[key] for key in change.successor_keys]
            if any(
                item.lifecycle not in {RequirementLifecycle.ACTIVE, RequirementLifecycle.SATISFIED}
                for item in parent_items
            ):
                raise ModelResponseError("lineage parent is inactive")
            if change.operation == "retire":
                parent = parent_items[0]
                if parent.status is not RequirementStatus.AVAILABLE or any(
                    parent.id in item.dependencies
                    for item in requirements.values()
                    if item.lifecycle
                    in {RequirementLifecycle.ACTIVE, RequirementLifecycle.SATISFIED}
                ):
                    raise ModelResponseError(
                        "an unresolved or referenced requirement cannot be retired"
                    )
            elif any(
                severity[successor.classification] < severity[parent.classification]
                for successor in successor_items
                for parent in parent_items
            ):
                raise ModelResponseError("lineage cannot weaken requirement classification")
            parent_ids = tuple(item.id for item in parent_items)
            successor_ids = tuple(item.id for item in successor_items)
            for item in parent_items:
                lifecycle = (
                    RequirementLifecycle.RETIRED
                    if change.operation == "retire"
                    else RequirementLifecycle.SUPERSEDED
                )
                requirements[item.key] = transition_requirement(item, lifecycle)
                replacements[item.id] = successor_ids
            for item in successor_items:
                requirements[item.key] = item.model_copy(
                    update={"parent_ids": tuple(dict.fromkeys((*item.parent_ids, *parent_ids)))}
                )
            state.lineage.append(
                RequirementLineage(
                    operation=change.operation, parent_ids=parent_ids, successor_ids=successor_ids
                )
            )
            used_parents.update(parents)
            used_successors.update(successors)
        if replacements:
            for key, item in tuple(requirements.items()):
                if item.lifecycle in {
                    RequirementLifecycle.SUPERSEDED,
                    RequirementLifecycle.RETIRED,
                }:
                    continue
                dependencies = tuple(
                    dict.fromkeys(
                        replacement
                        for dependency in item.dependencies
                        for replacement in replacements.get(dependency, (dependency,))
                    )
                )
                if dependencies != item.dependencies:
                    requirements[key] = item.model_copy(update={"dependencies": dependencies})

    async def _preview(self, state: AssessmentState) -> AssessmentResult:
        try:
            await self._discover_and_plan(state, preview_only=True)
        except SufficiencyError as exc:
            state.errors.append(
                Diagnostic(code=exc.code, message=str(exc), retryable=exc.retryable)
            )
            self._prepare_terminal(state, AssessmentStatus.FAILED)
        try:
            await self._commit_audit(state)
        except ProvenanceError:
            result = self._failed_result(
                state,
                "provenance_error",
                "Required preview provenance could not be committed. "
                "The preview was not saved; a new call starts a separate assessment.",
                retryable=False,
            )
            return result.model_copy(update={"preview_run_id": state.run_id})
        if state.result is None:
            raise SerializationError("preview has no result")
        return state.result.model_copy(update={"preview_run_id": state.run_id})

    async def _discover_and_plan(
        self, state: AssessmentState, *, preview_only: bool = False
    ) -> None:
        async def on_retry(_attempt: int) -> None:
            await self._observe(state, "model_retry", "retry", 0)

        started = time.perf_counter()
        try:
            response = await discover(
                self.model_call,
                state.task,
                self._prior(state),
                self.config,
                on_retry,
                preview_only=preview_only,
            )
            self._reconcile(state, response)
        except SufficiencyError:
            await self._observe(state, "model", "failed", time.perf_counter() - started)
            raise
        await self._observe(state, "model", "ok", time.perf_counter() - started)
        started = time.perf_counter()
        try:
            state.requirements = list(
                apply_blocking_policy(
                    state.requirements,
                    state.assumptions,
                    require_optional=self.config.require_optional,
                    allow_assumptions=self.config.allow_assumptions,
                    limits=self.config.limits,
                )
            )
        except SufficiencyError:
            await self._observe(state, "policy", "failed", time.perf_counter() - started)
            raise
        await self._observe(state, "policy", "ok", time.perf_counter() - started)
        if not any(
            item.lifecycle in {RequirementLifecycle.ACTIVE, RequirementLifecycle.SATISFIED}
            for item in state.requirements
        ):
            state.warnings.append(
                Diagnostic(
                    code="empty_discovery",
                    message="No requirements were discovered; readiness cannot be established.",
                )
            )
            self._prepare_terminal(state, AssessmentStatus.INSUFFICIENT)
            return
        if preview_only:
            await self._plan_preview_questions(state)
            return
        blockers = [item for item in state.requirements if item.blocking]
        if not blockers:
            self._prepare_terminal(state, AssessmentStatus.SUFFICIENT)
            return
        if state.iterations >= self.config.max_iterations:
            self._prepare_terminal(state, AssessmentStatus.ITERATION_LIMIT_REACHED)
            return
        proposals = {proposal.key: proposal for proposal in state.proposals}
        pending: list[ClarificationQuestion] = []
        pending_assumptions: list[Assumption] = []
        for item in blockers:
            proposal = proposals.get(item.key)
            action = NecessityDecision.MUST_BLOCK
            if proposal is not None and item.status is not RequirementStatus.DECLINED:
                action, question, assumption = self._question_or_assumption(state, item, proposal)
                if question is not None:
                    pending.append(question)
                if assumption is not None:
                    pending_assumptions.append(assumption)
            state.decisions.append(
                Decision(
                    id=uuid5(state.assessment_id, f"necessity:{state.iterations}:{item.id}"),
                    requirement_ids=(item.id,),
                    action=action,
                    reason=proposal.reason
                    if proposal is not None
                    else "The requirement is unresolved.",
                )
            )
        pending_questions = await self._retain_questions(state, pending)
        old_assumptions = {assumption.id for assumption in state.assumptions}
        state.assumptions.extend(
            assumption for assumption in pending_assumptions if assumption.id not in old_assumptions
        )
        state.pending_question_ids = [question.id for question in pending_questions]
        state.pending_assumption_ids = [assumption.id for assumption in pending_assumptions]
        if not pending_questions and not pending_assumptions:
            self._prepare_terminal(state, AssessmentStatus.INSUFFICIENT)
            return
        state.phase = "waiting"
        self._prepare_audit(state, "pending", terminal=False)

    async def _plan_preview_questions(self, state: AssessmentState) -> None:
        proposals = {proposal.key: proposal for proposal in state.proposals}
        pending: list[ClarificationQuestion] = []
        for item in state.requirements:
            if item.lifecycle is not RequirementLifecycle.ACTIVE or item.status not in {
                RequirementStatus.MISSING,
                RequirementStatus.UNRESOLVED,
            }:
                continue
            proposal = proposals.get(item.key)
            action = NecessityDecision.MUST_BLOCK if item.blocking else NecessityDecision.NOT_NEEDED
            if (
                proposal is not None
                and proposal.question is not None
                and proposal.necessity
                in {
                    NecessityDecision.MUST_ASK,
                    NecessityDecision.MAY_ASSUME,
                    NecessityDecision.MAY_DEFER,
                    NecessityDecision.NOT_NEEDED,
                }
            ):
                pending.append(self._make_question(state, item, proposal, proposal.question))
                action = (
                    NecessityDecision.MUST_ASK if item.blocking else NecessityDecision.MAY_DEFER
                )
            state.decisions.append(
                Decision(
                    id=uuid5(state.assessment_id, f"necessity:{state.iterations}:{item.id}"),
                    requirement_ids=(item.id,),
                    action=action,
                    reason=proposal.reason
                    if proposal is not None
                    else "The requirement is unresolved.",
                )
            )
        await self._retain_questions(state, pending)
        self._prepare_terminal(
            state,
            AssessmentStatus.INSUFFICIENT
            if any(item.blocking for item in state.requirements)
            else AssessmentStatus.SUFFICIENT,
        )

    async def _retain_questions(
        self, state: AssessmentState, pending: list[ClarificationQuestion]
    ) -> tuple[ClarificationQuestion, ...]:
        pending_questions, warnings = await deduplicate_questions(
            combine_related_questions(pending, state.assessment_id),
            self.embedding_model,
            timeout=self.config.limits.callback_timeout_seconds,
        )
        state.warnings.extend(warnings)
        if len(pending_questions) > self.config.limits.max_questions:
            raise ClarificationError("pending question limit exceeded")
        old_ids = {question.id for question in state.questions}
        state.questions.extend(
            question for question in pending_questions if question.id not in old_ids
        )
        return pending_questions

    def _question_or_assumption(
        self, state: AssessmentState, item: Requirement, proposal: RequirementProposal
    ) -> tuple[NecessityDecision, ClarificationQuestion | None, Assumption | None]:
        if proposal.necessity is NecessityDecision.MAY_ASSUME and proposal.assumption is not None:
            candidate = proposal.assumption
            assumption_id = uuid5(
                state.assessment_id,
                f"assumption:{item.id}:{json.dumps(candidate.value, sort_keys=True)}",
            )
            previous = next((a for a in state.assumptions if a.id == assumption_id), None)
            safe = (
                self.config.allow_assumptions
                and candidate.risk is RiskLevel.LOW
                and candidate.reversible
                and validate_answer(
                    candidate.value,
                    proposal.answer_type,
                    proposal.constraints,
                    self.config.limits.max_answer_bytes,
                )
                is None
            )
            if safe and (previous is None or previous.status is AssumptionStatus.PROPOSED):
                assumption = previous or Assumption(
                    id=assumption_id,
                    requirement_id=item.id,
                    description=candidate.description,
                    value=candidate.value,
                    risk=candidate.risk,
                    reversible=candidate.reversible,
                )
                return NecessityDecision.MAY_ASSUME, None, assumption
        should_ask = proposal.necessity is NecessityDecision.MUST_ASK or (
            proposal.necessity is NecessityDecision.MAY_ASSUME and proposal.question is not None
        )
        if not should_ask or proposal.question is None:
            return NecessityDecision.MUST_BLOCK, None, None
        return (
            NecessityDecision.MUST_ASK,
            self._make_question(state, item, proposal, proposal.question),
            None,
        )

    def _make_question(
        self,
        state: AssessmentState,
        item: Requirement,
        proposal: RequirementProposal,
        text: str,
    ) -> ClarificationQuestion:
        previous_question = next(
            (
                question
                for question in reversed(state.questions)
                if item.id in question.requirement_ids
                and question.answer_slot == proposal.answer_slot
            ),
            None,
        )
        follow_up = (
            previous_question.id
            if previous_question is not None
            and previous_question.status
            in {
                QuestionStatus.INVALID,
                QuestionStatus.PARTIALLY_ANSWERED,
                QuestionStatus.ANSWERED,
            }
            else None
        )
        question_id = uuid5(
            state.assessment_id,
            f"question:{item.id}:{proposal.answer_slot}:{follow_up or 'initial'}",
        )
        if (
            follow_up is not None
            and previous_question is not None
            and len(previous_question.requirement_ids) > 1
            and text == previous_question.text
        ):
            prefix = "Please provide or clarify: "
            text = (
                f"{prefix}{item.description}"
                if len(prefix) + len(item.description) <= 2_048
                else item.description
            )
        return ClarificationQuestion(
            id=question_id,
            requirement_ids=(item.id,),
            text=text,
            reason=proposal.reason,
            expected_type=proposal.answer_type,
            constraints=proposal.constraints,
            required=item.blocking,
            answer_slot=proposal.answer_slot,
            follow_up_to=follow_up,
        )

    def _prepare_audit(self, state: AssessmentState, action: str, *, terminal: bool) -> None:
        state.pending_audit = self.audit.prepare(
            scope=state.scope,
            run_id=state.run_id,
            assessment_id=state.assessment_id,
            started_at=state.started_at,
            step=state.iterations,
            action=action,
            requirements=state.requirements,
            terminal=terminal,
            source_references=state.source_references,
        )

    def _prepare_terminal(self, state: AssessmentState, status: AssessmentStatus) -> None:
        state.phase = "finished"
        state.terminal_status = status
        self._prepare_audit(state, status.value, terminal=True)

    async def _commit_audit(self, state: AssessmentState) -> None:
        intent = state.pending_audit
        # Both callers (execute and the LangGraph audit node) check pending_audit first.
        if intent is None:  # pragma: no cover
            raise SerializationError("session has no pending audit intent")
        started = time.perf_counter()
        try:
            state.warnings.extend(await self.audit.commit(intent, scope=state.scope))
        except ProvenanceError:
            await self._observe(state, "provenance", "failed", time.perf_counter() - started)
            await self._observe(
                state,
                "assessment",
                "failed",
                max(0.0, (datetime.now(UTC) - state.started_at).total_seconds()),
            )
            raise
        await self._observe(
            state,
            "provenance",
            "ok",
            time.perf_counter() - started,
            evidence_ids=tuple(item.id for item in intent.evidence),
            decision_id=intent.decision.id,
            link_ids=tuple(item.id for item in intent.links),
        )
        state.evidence_ids = list(
            dict.fromkeys((*state.evidence_ids, *(e.id for e in intent.evidence)))
        )
        state.decision_ids = list(dict.fromkeys((*state.decision_ids, intent.decision.id)))
        state.link_ids = list(dict.fromkeys((*state.link_ids, *(link.id for link in intent.links))))
        state.pending_audit = None
        if state.phase == "finished":
            if state.terminal_status is None:
                raise SerializationError("finished session has no terminal status")
            await self._observe(
                state,
                "assessment",
                state.terminal_status.value,
                max(0.0, (datetime.now(UTC) - state.started_at).total_seconds()),
            )
            state.result = self._result(state, state.terminal_status)

    async def _observe(
        self,
        state: AssessmentState,
        operation: str,
        outcome: str,
        duration: float,
        *,
        evidence_ids: tuple[UUID, ...] = (),
        decision_id: UUID | None = None,
        link_ids: tuple[UUID, ...] = (),
    ) -> None:
        if self.telemetry_call is None:
            return
        event = Observation.model_validate(
            {
                "operation": operation,
                "outcome": outcome,
                "duration_seconds": duration,
                "assessment_id": state.assessment_id,
                "run_id": state.run_id,
                "evidence_ids": evidence_ids,
                "decision_id": decision_id,
                "link_ids": link_ids,
            }
        )
        try:
            await invoke(self.telemetry_call, event, self.config.limits.callback_timeout_seconds)
        except Exception:
            if not any(warning.code == "telemetry_error" for warning in state.warnings):
                state.warnings.append(
                    Diagnostic(
                        code="telemetry_error",
                        message="An optional telemetry callback failed.",
                    )
                )

    def _payload(self, state: AssessmentState) -> ClarificationPayload:
        return ClarificationPayload(
            assessment_id=state.assessment_id,
            session_id=state.scope.session_id,
            questions=tuple(
                question
                for question in state.questions
                if question.id in state.pending_question_ids
                and question.status in {QuestionStatus.PENDING, QuestionStatus.PARTIALLY_ANSWERED}
                and any(
                    requirement.id in question.requirement_ids and requirement.blocking
                    for requirement in state.requirements
                )
            ),
            requirements=tuple(state.requirements),
            assumptions=tuple(
                assumption
                for assumption in state.assumptions
                if assumption.id in state.pending_assumption_ids
                and assumption.status is AssumptionStatus.PROPOSED
            ),
        )

    def _apply_response(self, state: AssessmentState, response: InteractionResponse) -> None:
        if response.cancelled:
            state.interaction_dispatched = False
            self._prepare_terminal(state, AssessmentStatus.CANCELLED)
            return
        payload = self._payload(state)
        questions = {question.id: question for question in payload.questions}
        assumptions = {assumption.id: assumption for assumption in payload.assumptions}
        if len({answer.question_id for answer in response.answers}) != len(response.answers):
            raise ClarificationError("duplicate question response")
        if any(answer.question_id not in questions for answer in response.answers):
            raise ClarificationError("unknown question response")
        if not set(response.assumption_approvals).issubset(assumptions):
            raise ClarificationError("unknown assumption approval")
        for answer in response.answers:
            valid_ids = set(questions[answer.question_id].requirement_ids)
            if not valid_ids.issubset({item.id for item in state.requirements}):
                raise ClarificationError("question references an unknown requirement")
            provided = set(answer.values)
            declined = set(answer.declined)
            ambiguous = set(answer.ambiguous)
            if (
                not (provided | declined | ambiguous).issubset(valid_ids)
                or provided & declined
                or declined & ambiguous
                or len(declined) != len(answer.declined)
                or len(ambiguous) != len(answer.ambiguous)
                or not set(answer.corrections).issubset(provided)
            ):
                raise ClarificationError("invalid answer slots")
        for answer in response.answers:
            self._apply_submission(state, questions[answer.question_id], answer)
        for assumption_id, approved in response.assumption_approvals.items():
            assumption = assumptions[assumption_id]
            updated = assumption.model_copy(
                update={
                    "status": AssumptionStatus.APPROVED if approved else AssumptionStatus.REJECTED
                }
            )
            state.assumptions = [
                updated if item.id == assumption_id else item for item in state.assumptions
            ]
            if approved:
                self._set_requirement(
                    state,
                    assumption.requirement_id,
                    RequirementStatus.ASSUMED,
                    evidence_id=uuid5(state.assessment_id, f"approval:{assumption.id}"),
                )
        state.iterations += 1
        state.interaction_dispatched = False
        state.phase = "discover"

    def _reject_response(self, state: AssessmentState) -> None:
        state.iterations += 1
        state.warnings.append(
            Diagnostic(
                code="clarification_error",
                message="The submitted response was invalid; no answers were accepted.",
            )
        )
        if state.iterations >= self.config.max_iterations:
            self._prepare_terminal(state, AssessmentStatus.ITERATION_LIMIT_REACHED)

    def _apply_submission(
        self, state: AssessmentState, question: ClarificationQuestion, submission: AnswerSubmission
    ) -> None:
        outcomes: list[AnswerStatus] = []
        for requirement_id in question.requirement_ids:
            if requirement_id in submission.declined:
                status, value, reason = AnswerStatus.DECLINED, None, None
                self._set_requirement(state, requirement_id, RequirementStatus.DECLINED)
            elif requirement_id in submission.ambiguous:
                status, value, reason = (
                    AnswerStatus.AMBIGUOUS,
                    submission.values.get(requirement_id),
                    "Answer is ambiguous.",
                )
                self._set_requirement(state, requirement_id, RequirementStatus.UNRESOLVED)
            elif requirement_id in submission.values:
                value = submission.values[requirement_id]
                reason = validate_answer(
                    value,
                    question.expected_type,
                    question.constraints,
                    self.config.limits.max_answer_bytes,
                )
                status = AnswerStatus.INVALID if reason else AnswerStatus.VALID
                previous = [
                    answer
                    for answer in state.answers
                    if answer.requirement_id == requirement_id
                    and answer.status is AnswerStatus.VALID
                ]
                if (
                    status is AnswerStatus.VALID
                    and previous
                    and json.dumps(previous[-1].value, sort_keys=True)
                    != json.dumps(value, sort_keys=True)
                ):
                    if requirement_id not in submission.corrections:
                        status, reason = (
                            AnswerStatus.CONTRADICTORY,
                            "Answer conflicts with a prior answer.",
                        )
                        self._set_requirement(state, requirement_id, RequirementStatus.UNRESOLVED)
                    else:
                        state.answers = [
                            answer.model_copy(update={"status": AnswerStatus.CONTRADICTORY})
                            if answer in previous
                            else answer
                            for answer in state.answers
                        ]
                if status is AnswerStatus.VALID:
                    evidence_id = uuid5(
                        state.assessment_id, f"answer:{question.id}:{requirement_id}"
                    )
                    self._set_requirement(
                        state,
                        requirement_id,
                        RequirementStatus.AVAILABLE,
                        evidence_id=evidence_id,
                        replace_evidence=requirement_id in submission.corrections,
                    )
            else:
                continue
            outcomes.append(status)
            state.answers.append(
                Answer(
                    question_id=question.id,
                    requirement_id=requirement_id,
                    value=value,
                    status=status,
                    reason=reason,
                )
            )
        if any(
            status in {AnswerStatus.INVALID, AnswerStatus.AMBIGUOUS, AnswerStatus.CONTRADICTORY}
            for status in outcomes
        ):
            question_status = QuestionStatus.INVALID
        elif len(outcomes) < len(question.requirement_ids):
            question_status = QuestionStatus.PARTIALLY_ANSWERED
        elif outcomes and all(status is AnswerStatus.DECLINED for status in outcomes):
            question_status = QuestionStatus.DECLINED
        else:
            question_status = QuestionStatus.ANSWERED
        state.questions = [
            item.model_copy(update={"status": question_status}) if item.id == question.id else item
            for item in state.questions
        ]

    @staticmethod
    def _set_requirement(
        state: AssessmentState,
        requirement_id: UUID,
        status: RequirementStatus,
        *,
        evidence_id: UUID | None = None,
        replace_evidence: bool = False,
    ) -> None:
        updated = []
        for item in state.requirements:
            if item.id != requirement_id:
                updated.append(item)
                continue
            evidence = item.source_evidence_ids
            if evidence_id is not None:
                evidence = (
                    (evidence_id,)
                    if replace_evidence
                    else tuple(dict.fromkeys((*evidence, evidence_id)))
                )
            updated.append(
                Requirement.model_validate(
                    {
                        **item.model_dump(),
                        "status": status,
                        "source_evidence_ids": evidence,
                        "lifecycle": (
                            RequirementLifecycle.SATISFIED
                            if status in {RequirementStatus.AVAILABLE, RequirementStatus.ASSUMED}
                            else RequirementLifecycle.ACTIVE
                        ),
                        "updated_at": datetime.now(UTC),
                    }
                )
            )
        state.requirements = updated

    def _result(self, state: AssessmentState, status: AssessmentStatus) -> AssessmentResult:
        provenance = (
            ProvenanceReferences(
                run_id=state.run_id,
                evidence_ids=tuple(state.evidence_ids),
                decision_ids=tuple(state.decision_ids),
                link_ids=tuple(state.link_ids),
            )
            if state.decision_ids
            else None
        )
        return AssessmentResult(
            assessment_id=state.assessment_id,
            session_id=state.scope.session_id,
            status=status,
            sufficient=status is AssessmentStatus.SUFFICIENT,
            require_optional=self.config.require_optional,
            allow_assumptions=self.config.allow_assumptions,
            requirements=tuple(state.requirements),
            blocking_requirements=tuple(item for item in state.requirements if item.blocking),
            questions=tuple(state.questions),
            answers=tuple(state.answers),
            assumptions=tuple(state.assumptions),
            decisions=tuple(state.decisions),
            iteration_count=state.iterations,
            warnings=tuple(state.warnings),
            errors=tuple(state.errors),
            provenance=provenance,
            lineage=tuple(state.lineage),
            completion_reason=_COMPLETION_REASONS[status],
        )

    def _failed_result(
        self, state: AssessmentState, code: str, message: str, *, retryable: bool
    ) -> AssessmentResult:
        result = self._result(state, AssessmentStatus.FAILED)
        return result.model_copy(
            update={
                "errors": (
                    *result.errors,
                    Diagnostic(code=code, message=message, retryable=retryable),
                )
            }
        )
