"""Run offline standalone readiness, clarification, and assumption examples."""

import asyncio
import json

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from sufficiency_engine import AnswerSubmission, InteractionResponse, SufficiencyEngine


def scripted_model(*responses):
    model = GenericFakeChatModel(
        messages=iter(AIMessage(content=json.dumps(response)) for response in responses)
    )

    async def call(messages):
        return await model.ainvoke(messages)

    return call


def requirement(**updates):
    return {
        "key": "platform",
        "description": "Deployment platform",
        "classification": "mandatory",
        "status": "unresolved",
        "necessity": "must_ask",
        "reason": "The platform affects the deployment.",
        "question": "Which platform?",
        "answer_type": "string",
        **updates,
    }


async def main():
    complete = SufficiencyEngine(
        model_call=scripted_model(
            {
                "requirements": [
                    requirement(status="available", evidence_quote="Linux", necessity="not_needed")
                ]
            }
        )
    )
    complete_result = await complete.execute(input="Deploy the service on Linux.")
    assert complete_result.sufficient

    item = requirement()

    def answer(payload):
        question = payload.questions[0]
        return InteractionResponse(
            answers=(
                AnswerSubmission(
                    question_id=question.id, values={question.requirement_ids[0]: "Linux"}
                ),
            )
        )

    incomplete = SufficiencyEngine(
        model_call=scripted_model(
            {"requirements": [item]},
            {"requirements": [requirement(status="available", evidence_quote="Linux")]},
        ),
        interrupt_call=answer,
    )
    clarified = await incomplete.execute(input="Deploy the service.")
    assert clarified.sufficient and clarified.iteration_count == 1

    assumption = requirement(
        key="replicas",
        description="Replica count",
        necessity="may_assume",
        question=None,
        answer_type="integer",
        assumption={"description": "One replica", "value": 1, "risk": "low", "reversible": True},
    )

    async def approve(payload):
        return InteractionResponse(assumption_approvals={payload.assumptions[0].id: True})

    with_assumption = SufficiencyEngine(
        model_call=scripted_model({"requirements": [assumption]}, {"requirements": [assumption]}),
        interrupt_call=approve,
        allow_assumptions=True,
    )
    approved = await with_assumption.execute(input="Deploy the service.")
    assert approved.sufficient and approved.assumptions[0].status == "approved"
    print("Standalone: complete, clarified, and explicitly approved tasks are audited.")


if __name__ == "__main__":
    asyncio.run(main())
