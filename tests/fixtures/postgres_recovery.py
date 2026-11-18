"""Subprocess fixture for real PostgreSQL checkpoint and AGXAI recovery."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path

from agxai import (
    AttributionResult,
    Decision,
    Evidence,
    ExecutionContext,
    Explanation,
    PolicyDecision,
    StoreFilter,
)
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool

from sufficiency_engine import AGXAIAudit, AssessmentResult, SufficiencyEngine
from sufficiency_engine._state import AssessmentState
from sufficiency_engine.integrations.langgraph import build_assessment_graph
from sufficiency_engine.provenance import SemanticArchiveABC

_MODELS = {
    model.__name__: model
    for model in (AttributionResult, Decision, Evidence, Explanation, PolicyDecision)
}


class PostgresArchive(SemanticArchiveABC):
    """Test-only durable archive of actual AGXAI semantic models."""

    def __init__(self, pool):
        self.pool = pool

    async def setup(self):
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sufficiency_test_artifacts (
                    application_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                    run_id UUID NOT NULL, record_type TEXT NOT NULL,
                    record_id UUID NOT NULL, payload JSONB NOT NULL,
                    PRIMARY KEY (application_id, tenant_id, run_id, record_type, record_id)
                )
                """
            )

    async def record(self, artifact):
        context = artifact.context
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO sufficiency_test_artifacts
                    (application_id, tenant_id, run_id, record_type, record_id, payload)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (application_id, tenant_id, run_id, record_type, record_id)
                DO UPDATE SET payload = EXCLUDED.payload
                """,
                (
                    context.application_id,
                    context.tenant_id,
                    context.run_id,
                    type(artifact).__name__,
                    artifact.id,
                    artifact.model_dump_json(),
                ),
            )

    async def get(self, artifact_id, *, context):
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT record_type, payload FROM sufficiency_test_artifacts
                    WHERE application_id = %s AND tenant_id = %s AND run_id = %s AND record_id = %s
                    LIMIT 2
                    """,
                    (context.application_id, context.tenant_id, context.run_id, artifact_id),
                )
            ).fetchall()
        if len(rows) > 1:
            raise LookupError("ambiguous artifact")
        return None if not rows else _MODELS[rows[0][0]].model_validate(rows[0][1])

    async def list_run(self, *, context):
        async with self.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT record_type, payload FROM sufficiency_test_artifacts
                    WHERE application_id = %s AND tenant_id = %s AND run_id = %s
                    ORDER BY record_type, record_id
                    """,
                    (context.application_id, context.tenant_id, context.run_id),
                )
            ).fetchall()
        return tuple(_MODELS[kind].model_validate(payload) for kind, payload in rows)

    async def delete_run(self, context):
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                DELETE FROM sufficiency_test_artifacts
                WHERE application_id = %s AND tenant_id = %s AND run_id = %s
                """,
                (context.application_id, context.tenant_id, context.run_id),
            )


def load_agxai_store(path: Path):
    spec = importlib.util.spec_from_file_location("agxai_postgres_example", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("AGXAI PostgreSQL example is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PostgresProvenanceStore


async def main(args):
    dsn = os.environ["SUFFICIENCY_TEST_POSTGRES_DSN"]
    store_type = load_agxai_store(Path(os.environ["AGXAI_POSTGRES_EXAMPLE"]))
    pool = AsyncConnectionPool(dsn, open=False, min_size=1, max_size=2)
    store = store_type(dsn, pool=pool)
    await store.open()
    archive = PostgresArchive(pool)
    await archive.setup()
    item = {
        "key": "platform",
        "description": "Deployment platform",
        "classification": "mandatory",
        "status": "unresolved",
        "necessity": "must_ask",
        "reason": "The platform affects deployment.",
        "question": "Which platform?",
        "answer_type": "string",
    }
    if args.phase == "resume":
        item.update(status="available", evidence_quote="Linux")
    model = GenericFakeChatModel(
        messages=iter([AIMessage(content=json.dumps({"requirements": [item]}))])
    )

    async def model_call(messages):
        return await model.ainvoke(messages)

    engine = SufficiencyEngine(
        model_call=model_call,
        audit=AGXAIAudit(store=store, archive=archive),
        application_id="sufficiency-test",
        tenant_id="tenant-a",
    )
    try:
        async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer:
            await checkpointer.setup()
            graph = build_assessment_graph(engine, checkpointer=checkpointer)
            config = {"configurable": {"thread_id": "sufficiency-postgres-recovery"}}
            if args.phase == "prepare":
                result = await graph.ainvoke({"task": "Deploy", "session_id": "recovery"}, config)
                payload = result["__interrupt__"][0].value
                state = AssessmentState.model_validate(result["assessment"])
                question = payload["questions"][0]
                print(
                    json.dumps(
                        {
                            "assessment_id": str(state.assessment_id),
                            "run_id": str(state.run_id),
                            "question_id": question["id"],
                            "requirement_id": question["requirement_ids"][0],
                        }
                    )
                )
            else:
                before = await graph.aget_state(config)
                state = AssessmentState.model_validate(before.values["assessment"])
                response = {
                    "answers": [
                        {
                            "question_id": args.question_id,
                            "values": {args.requirement_id: "Linux"},
                        }
                    ]
                }
                result = await graph.ainvoke(Command(resume=response), config)
                readiness = AssessmentResult.model_validate(result["readiness"])
                if not readiness.sufficient or readiness.provenance is None:
                    raise RuntimeError("durable assessment did not complete successfully")
                context = ExecutionContext(
                    application_id="sufficiency-test",
                    tenant_id="tenant-a",
                    graph_id="sufficiency-engine",
                    run_id=state.run_id,
                    thread_id="recovery",
                )
                parents = await store.parents(
                    str(readiness.provenance.decision_ids[-1]), context=context
                )
                artifacts = await archive.list_run(context=context)
                pending = engine.audit.prepare(
                    scope=state.scope,
                    run_id=state.run_id,
                    assessment_id=state.assessment_id,
                    started_at=state.started_at,
                    step=99,
                    action="sufficient",
                    requirements=readiness.requirements,
                    terminal=True,
                )
                query = StoreFilter(
                    application_id=context.application_id,
                    tenant_id=context.tenant_id,
                    run_id=context.run_id,
                    limit=1000,
                )
                await engine.audit.commit(pending, scope=state.scope)
                first_artifacts = await archive.list_run(context=context)
                first_records = [item async for item in store.query(query)]
                await engine.audit.commit(pending, scope=state.scope)
                second_artifacts = await archive.list_run(context=context)
                second_records = [item async for item in store.query(query)]
                assert {item.id for item in first_artifacts} == {
                    item.id for item in second_artifacts
                }
                assert {(type(item), item.id) for item in first_records} == {
                    (type(item), item.id) for item in second_records
                }
                other_tenant = context.model_copy(update={"tenant_id": "tenant-b"})
                if await archive.list_run(context=other_tenant):
                    raise RuntimeError("semantic archive leaked across tenants")
                if await store.parents(
                    str(readiness.provenance.decision_ids[-1]), context=other_tenant
                ):
                    raise RuntimeError("provenance store leaked across tenants")
                print(
                    json.dumps(
                        {
                            "assessment_id": str(readiness.assessment_id),
                            "run_id": str(readiness.provenance.run_id),
                            "question_id": str(readiness.questions[0].id),
                            "requirement_id": str(readiness.requirements[0].id),
                            "parents": len(parents),
                            "artifacts": len(artifacts),
                        }
                    )
                )
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("prepare", "resume"), required=True)
    parser.add_argument("--question-id")
    parser.add_argument("--requirement-id")
    asyncio.run(main(parser.parse_args()), loop_factory=asyncio.SelectorEventLoop)
