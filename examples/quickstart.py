"""Assess a task, ask one clarification question, and reassess it offline."""

import asyncio
import json

from sufficiency_engine import AnswerSubmission, InteractionResponse, SufficiencyEngine


async def model_call(messages):
    # Replace with your own model, e.g. `return await chat_model.ainvoke(messages)`.
    prior = json.loads(messages[-1]["content"])["prior"]
    answered = bool(prior and prior[0]["answers"] == ["Linux"])
    return {
        "requirements": [
            {
                "key": "platform",
                "description": "Deployment platform",
                "classification": "mandatory",
                "status": "available" if answered else "unresolved",
                "evidence_quote": "Linux" if answered else None,
                "necessity": "must_ask",
                "reason": "The deployment steps depend on the platform.",
                "question": "Which platform should the service be deployed on?",
                "answer_type": "string",
            }
        ]
    }


async def ask_user(payload):
    question = payload.questions[0]
    print("Question:", question.text)
    return InteractionResponse(
        answers=(
            AnswerSubmission(
                question_id=question.id,
                values={question.requirement_ids[0]: "Linux"},
            ),
        )
    )


async def main():
    engine = SufficiencyEngine(model_call=model_call, interrupt_call=ask_user)
    result = await engine.execute(input="Deploy the billing service.")
    print("Status:", result.status.value)
    print("Sufficient:", result.sufficient)
    print("Clarification rounds:", result.iteration_count)
    for requirement in result.requirements:
        print(f"  {requirement.key}: {requirement.status.value}, blocking={requirement.blocking}")
    print("Audited decisions:", len(result.provenance.decision_ids))


if __name__ == "__main__":
    asyncio.run(main())
