"""Strict integration with AGXAI's actual storage and semantic-artifact APIs."""

from __future__ import annotations

import asyncio
import threading
from abc import abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid5

from agxai import (
    CanonicalEvent,
    DecisionType,
    Evidence,
    EvidenceType,
    Execution,
    ExecutionContext,
    ExecutionStatus,
    FailureMode,
    InMemoryProvenanceStore,
    ObservabilityProvider,
    ProvenanceLink,
    ProvenanceStore,
    Run,
    SemanticArtifact,
    SourceReference,
    XAIConfig,
    XAIPlugin,
    XAIRuntime,
)
from agxai import (
    Decision as XAIDecision,
)
from agxai.core.models import (
    ExceptionEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionStartedEvent,
)
from pydantic import BaseModel, ConfigDict

from .exceptions import ProvenanceError
from .models import Diagnostic, Requirement
from .persistence import SessionScope


class SemanticArchiveABC(XAIPlugin):
    """An idempotent, scoped archive for the AGXAI semantic artifacts it receives.

    A production implementation must provide durable upserts and reads by
    application, tenant, run, artifact type, and artifact ID.
    """

    @abstractmethod
    async def get(self, artifact_id: UUID, *, context: ExecutionContext) -> SemanticArtifact | None:
        """Read one artifact in its run scope."""

    @abstractmethod
    async def list_run(self, *, context: ExecutionContext) -> Sequence[SemanticArtifact]:
        """Read the semantic artifacts in one run."""

    @abstractmethod
    async def delete_run(self, context: ExecutionContext) -> None:
        """Idempotently delete the semantic artifacts in one run."""


class InMemorySemanticArchive(SemanticArchiveABC):
    """Copy-isolated AGXAI semantic archive for ephemeral use."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str, UUID, str, UUID], SemanticArtifact] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _prefix(context: ExecutionContext) -> tuple[str, str, UUID]:
        return context.application_id, context.tenant_id, context.run_id

    async def record(self, artifact: SemanticArtifact) -> None:
        key = (*self._prefix(artifact.context), type(artifact).__name__, artifact.id)
        with self._lock:
            self._items[key] = artifact.model_copy(deep=True)

    async def get(self, artifact_id: UUID, *, context: ExecutionContext) -> SemanticArtifact | None:
        prefix = self._prefix(context)
        with self._lock:
            matches = [
                artifact
                for key, artifact in self._items.items()
                if key[:3] == prefix and key[4] == artifact_id
            ]
            if len(matches) > 1:
                raise LookupError("artifact ID is ambiguous in this run")
            return None if not matches else matches[0].model_copy(deep=True)

    async def list_run(self, *, context: ExecutionContext) -> Sequence[SemanticArtifact]:
        prefix = self._prefix(context)
        with self._lock:
            return tuple(
                artifact.model_copy(deep=True)
                for key, artifact in self._items.items()
                if key[:3] == prefix
            )

    async def delete_run(self, context: ExecutionContext) -> None:
        prefix = self._prefix(context)
        with self._lock:
            keys = [key for key in self._items if key[:3] == prefix]
            for key in keys:
                del self._items[key]


class AuditIntent(BaseModel):
    """A serializable outbox item with stable AGXAI records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution: Execution
    evidence: tuple[Evidence, ...]
    decision: XAIDecision
    links: tuple[ProvenanceLink, ...]
    events: tuple[CanonicalEvent, ...] = ()


class AGXAIAudit:
    """Deliver stable, sanitized assessment records through real AGXAI APIs."""

    def __init__(
        self,
        *,
        store: ProvenanceStore | None = None,
        archive: SemanticArchiveABC | None = None,
        observer: ObservabilityProvider | None = None,
        operation_timeout: float = 10.0,
    ) -> None:
        if operation_timeout <= 0:
            raise ValueError("operation_timeout must be positive")
        self.store = store if store is not None else InMemoryProvenanceStore()
        self.archive = archive if archive is not None else InMemorySemanticArchive()
        if observer is not None and not isinstance(observer, ObservabilityProvider):
            raise TypeError("observer must be an AGXAI observability provider")
        self.observer = observer
        if not isinstance(self.store, ProvenanceStore) or not isinstance(
            self.archive, SemanticArchiveABC
        ):
            raise TypeError("AGXAI requires a provenance store and semantic archive")
        self.operation_timeout = operation_timeout
        self.runtime = XAIRuntime(
            XAIConfig(failure_mode=FailureMode.STRICT, operation_timeout_seconds=operation_timeout),
            plugins=(self.archive,),
        )
        self.runtime.register(ProvenanceStore, self.store)

    def prepare(
        self,
        *,
        scope: SessionScope,
        run_id: UUID,
        assessment_id: UUID,
        started_at: datetime,
        step: int,
        action: str,
        requirements: Sequence[Requirement],
        terminal: bool,
        source_references: tuple[UUID, ...] = (),
    ) -> AuditIntent:
        """Prepare replayable AGXAI models without raw task or answer contents."""
        if action not in {
            "pending",
            "sufficient",
            "insufficient",
            "cancelled",
            "iteration_limit_reached",
            "failed",
        }:
            raise ValueError("unsupported audit action")
        context = ExecutionContext(
            application_id=scope.application_id,
            tenant_id=scope.tenant_id,
            graph_id="sufficiency-engine",
            run_id=run_id,
            thread_id=scope.session_id,
        )
        status = ExecutionStatus.RUNNING
        if terminal:
            status = (
                ExecutionStatus.FAILED
                if action == "failed"
                else ExecutionStatus.CANCELLED
                if action == "cancelled"
                else ExecutionStatus.COMPLETED
            )
        execution = Execution(
            id=uuid5(run_id, "execution"),
            context=context,
            status=status,
            started_at=started_at,
            ended_at=datetime.now(UTC) if terminal else None,
        )
        input_id = uuid5(assessment_id, "task-input")
        evidence_ids = {input_id}
        source_by_evidence = {
            uuid5(assessment_id, f"source:{source_id}"): source_id
            for source_id in source_references
        }
        evidence_ids.update(source_by_evidence)
        for requirement in requirements:
            evidence_ids.update(requirement.source_evidence_ids)
        evidence = tuple(
            Evidence(
                id=evidence_id,
                evidence_type=EvidenceType.STATE,
                context=context,
                source=SourceReference(
                    source_id=source_by_evidence.get(evidence_id, evidence_id),
                    source_type=(
                        "application_reference"
                        if evidence_id in source_by_evidence
                        else "supplied_information"
                    ),
                ),
            )
            for evidence_id in sorted(evidence_ids, key=str)
        )
        decision_id = uuid5(assessment_id, f"decision:{step}:{action}")
        decision = XAIDecision(
            id=decision_id,
            context=context,
            decision_type=DecisionType.CUSTOM,
            selected_action=action,
            evidence_ids=list(sorted(evidence_ids, key=str)),
            metadata={
                "assessment_id": str(assessment_id),
                "step": step,
                "requirement_count": len(requirements),
                "blocking_count": sum(requirement.blocking for requirement in requirements),
            },
        )
        links = tuple(
            ProvenanceLink(
                id=uuid5(assessment_id, f"link:{evidence_id}:{decision_id}"),
                source_id=evidence_id,
                target_id=decision_id,
                relation="considered",
                context=context,
            )
            for evidence_id in sorted(evidence_ids, key=str)
        )
        events: list[CanonicalEvent] = [
            ExecutionStartedEvent(
                id=uuid5(run_id, "execution.started"),
                context=context,
                timestamp=started_at,
                sequence=0,
            )
        ]
        if terminal:
            event_id = uuid5(run_id, f"execution.finished:{step}:{action}")
            if status in {ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}:
                error = ExceptionEvent(
                    id=uuid5(event_id, "error"),
                    context=context,
                    exception_type="AssessmentFailed"
                    if status is ExecutionStatus.FAILED
                    else "AssessmentCancelled",
                    message="Assessment failed"
                    if status is ExecutionStatus.FAILED
                    else "Cancelled",
                )
                events.append(
                    ExecutionFailedEvent(
                        id=event_id, context=context, sequence=step * 2 + 1, error=error
                    )
                )
            else:
                events.append(
                    ExecutionCompletedEvent(id=event_id, context=context, sequence=step * 2 + 1)
                )
        return AuditIntent(
            execution=execution,
            evidence=evidence,
            decision=decision,
            links=links,
            events=tuple(events),
        )

    async def commit(self, intent: AuditIntent, *, scope: SessionScope) -> tuple[Diagnostic, ...]:
        """Deliver an outbox item; replay is safe only with conforming stores.

        A failure can happen after a write has committed. The caller must keep
        the intent and reconcile or retry it; no cross-system transaction is
        implied.
        """
        context = intent.execution.context
        if (
            context.application_id != scope.application_id
            or context.tenant_id != scope.tenant_id
            or context.thread_id != scope.session_id
            or any(
                item.context != context
                for item in (*intent.evidence, intent.decision, *intent.links, *intent.events)
            )
        ):
            raise ProvenanceError("audit intent does not match the session scope")
        try:
            run = Run(intent.execution)
            async with asyncio.timeout(self.operation_timeout):
                await self.store.write(intent.execution)
                for event in intent.events:
                    await self.store.write(event)
                for evidence in intent.evidence:
                    await self.runtime.record_artifact(evidence, run=run)
                await self.runtime.record_artifact(intent.decision, run=run)
                for link in intent.links:
                    await self.store.write(link)
        except Exception as exc:
            raise ProvenanceError("required AGXAI provenance write failed") from exc
        if self.observer is not None:
            try:
                async with asyncio.timeout(self.operation_timeout):
                    for event in intent.events:
                        await self.observer.emit(event)
            except Exception:
                return (
                    Diagnostic(
                        code="telemetry_error",
                        message="An AGXAI observability provider failed to emit an event.",
                    ),
                )
        return ()

    async def delete_run(self, context: ExecutionContext) -> None:
        """Delete both AGXAI store and archive records for one run."""
        try:
            async with asyncio.timeout(self.operation_timeout):
                await self.store.delete_run(context)
                await self.archive.delete_run(context)
        except Exception as exc:
            raise ProvenanceError("AGXAI provenance deletion failed") from exc
