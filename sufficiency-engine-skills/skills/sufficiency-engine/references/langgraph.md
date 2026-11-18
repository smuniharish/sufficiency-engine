# LangGraph integration

Import `build_assessment_graph` from
`sufficiency_engine.integrations.langgraph` only after installing the extra.
Compile the returned graph with a checkpointer, or embed the subgraph in a
parent graph whose checkpointer is authoritative. `InMemorySaver` is a demo
store; use a durable host checkpointer for restart recovery.

Inputs include `task` and an application-owned `session_id`. Consume the
`__interrupt__` payload and resume with `Command(resume=response)` using the
same configured `thread_id`. Validate `readiness` with `AssessmentResult`.

The adapter separates preparation, audit delivery, interruption, and answer
application so that native node restart does not repeat interaction-side
effects before `interrupt()`. Prepared AGXAI intents are checkpointed before
delivery. Recover a sink failure using its retained `assessment`, same task,
and same session; do not rediscover a replacement assessment.

There is no second standalone session copy. The adapter does not invoke
`command_call`; the host owns notifications and checkpoint deletion. Serialize
concurrent updates to a graph thread according to the host checkpointer's
contract. Separate stores are not a cross-system transaction.

Keep the readiness graph before the supervisor. Research, developer/tester
workers, tools, retries, and new findings inside the original task do not
trigger reassessment. Invoke another assessment only when the application
explicitly creates a genuinely independent task.
