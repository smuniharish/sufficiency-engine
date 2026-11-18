# Integrations

The core package has no framework dependency. Integrations are optional extras
that adapt the engine to a host without changing its decisions.

<div class="grid cards" markdown>

-   :material-graph-outline: **[LangGraph](langgraph.md)**

    ---

    A checkpoint-safe task-entry subgraph that asks clarifying questions with
    LangGraph interrupts.

-   :material-chart-timeline-variant: **[OpenTelemetry](opentelemetry.md)**

    ---

    Sanitized spans and low-cardinality metrics through your own providers.

-   :material-puzzle-outline: **[Custom frameworks](custom-frameworks.md)**

    ---

    Call the engine from any async host: a web handler, a queue worker, or
    your own agent loop.

</div>

| Integration | Install | Import |
| --- | --- | --- |
| LangGraph | `sufficiency-engine[langgraph]` | `sufficiency_engine.integrations.langgraph` |
| OpenTelemetry | `sufficiency-engine[observability]` | `sufficiency_engine.integrations.opentelemetry` |
| Custom | Core package | `sufficiency_engine` |
