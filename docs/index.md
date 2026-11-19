---
hide:
  - navigation
  - toc
---

<div class="se-hero" markdown>

# Sufficiency Engine

<p class="se-tagline">Decide whether a task has enough information to proceed,
before your agent starts work. Sufficiency Engine finds the requirements a task
depends on, asks only the questions that matter, and records every readiness
decision with AGXAI provenance.</p>

[Get started](getting-started/index.md){ .md-button .md-button--primary }
[Browse examples](examples/index.md){ .md-button }
[API reference](api/index.md){ .md-button }

</div>

## Why Sufficiency Engine

Agents usually start a task with whatever the user typed. When the platform,
the account, or the deadline is missing, the agent guesses, or asks a string of
loosely related questions. Sufficiency Engine answers one question first:
**does this task have enough information to proceed safely and correctly?**
A model proposes the requirements, deterministic Python policy decides what
blocks, and the outcome is recorded as evidence and decisions.

<div class="grid cards" markdown>

-   :material-scale-balance:{ .lg .middle } __Model proposes, policy decides__

    ---

    The model suggests requirements, evidence quotes, and whether to ask.
    Python validates every proposal and alone sets the blocking flag.

-   :material-text-search:{ .lg .middle } __Evidence, not guesses__

    ---

    An `available` requirement must quote the task or an accepted answer for
    that requirement. Unsupported quotes are rejected, never trusted.

-   :material-comment-question-outline:{ .lg .middle } __Only the questions that matter__

    ---

    Questions are combined, deduplicated, and never repeated after a decline.
    Zero questions is a valid outcome.

-   :material-file-certificate-outline:{ .lg .middle } __Audited with AGXAI__

    ---

    Every terminal outcome records evidence, decisions, and links in AGXAI.
    A failed audit is a failed assessment, never a silent success.

-   :material-backup-restore:{ .lg .middle } __Recoverable by design__

    ---

    Claims, revisions, and fencing protect sessions. An interrupted
    interaction or audit resumes without rediscovery or replayed side effects.

-   :material-puzzle-outline:{ .lg .middle } __Provider- and framework-neutral__

    ---

    Bring any model through one callback. LangGraph and OpenTelemetry are
    optional extras; storage and embeddings plug in through ABCs.

</div>

## Thirty-second tour

```bash
pip install sufficiency-engine
```

A deployment task names no platform. The engine asks one question, reassesses
with the answer, and returns an audited result. The model callback is
deterministic here so the example runs offline; in your application it calls
your own model:

<!-- fmt: off -->
```python
--8<-- "examples/quickstart.py"
```
<!-- fmt: on -->

Output:

```text
Question: Which platform should the service be deployed on?
Status: sufficient
Sufficient: True
Clarification rounds: 1
  platform: available, blocking=False
Audited decisions: 2
```

Your application keeps the model, the conversation, and the work itself.
Sufficiency Engine only decides readiness:

![Sufficiency Engine architecture](assets/diagrams/architecture-overview.png){ .diagram }

## Let your coding agent integrate it

Install the [Sufficiency Engine Agent Skills](agent-skills/index.md) and your
coding agent learns the workflow and safety rules for adding readiness checks to
your application, and for implementing durable storage and embeddings:

```text title="Agent instruction"
Install the Agent Skills from https://github.com/smuniharish/sufficiency-engine
(sufficiency-engine-skills/skills/sufficiency-engine and
sufficiency-engine-skills/skills/sufficiency-engine-extend) into this project,
run the sufficiency-engine skill's scripts/verify_setup.py, then add a task
readiness check at this application's task entry, following the skill's
workflow and safety rules.
```

## Downloads

<p>
  <a href="https://clickpy.clickhouse.com/dashboard/sufficiency-engine"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527sufficiency-engine%2527%2520FORMAT%2520JSON&query=%24.data%5B0%5D.v&label=downloads&color=blue&cacheSeconds=3600" alt="Total downloads"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/sufficiency-engine"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527sufficiency-engine%2527%2520AND%2520date%2520%253E%253D%2520toStartOfWeek%2528today%2528%2529%252C%25201%2529%2520FORMAT%2520JSON&query=%24.data%5B0%5D.v&label=this%20week&color=blue&cacheSeconds=3600" alt="Downloads this week"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/sufficiency-engine"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527sufficiency-engine%2527%2520AND%2520date%2520%253E%253D%2520toStartOfMonth%2528today%2528%2529%2529%2520FORMAT%2520JSON&query=%24.data%5B0%5D.v&label=this%20month&color=blue&cacheSeconds=3600" alt="Downloads this month"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/sufficiency-engine"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527sufficiency-engine%2527%2520AND%2520date%2520%253E%253D%2520toStartOfYear%2528today%2528%2529%2529%2520FORMAT%2520JSON&query=%24.data%5B0%5D.v&label=this%20year&color=blue&cacheSeconds=3600" alt="Downloads this year"></a>
</p>
<p>
  <a href="https://clickpy.clickhouse.com/dashboard/sufficiency-engine"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528groupArray%2528concat%2528toString%2528y%2529%252C%2520%2527%253A%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520toYear%2528date%2529%2520y%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527sufficiency-engine%2527%2520GROUP%2520BY%2520y%2520ORDER%2520BY%2520y%2529%2520FORMAT%2520JSON&query=%24.data%5B0%5D.v&label=by%20year&color=blue&cacheSeconds=3600" alt="Downloads by year"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/sufficiency-engine"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527sufficiency-engine%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%2520LIMIT%25205%2529%2520FORMAT%2520JSON&query=%24.data%5B0%5D.v&label=top%20countries&color=blue&cacheSeconds=3600" alt="Top download countries"></a>
</p>

The counts are fetched live from the
[ClickHouse public PyPI dataset](https://clickpy.clickhouse.com/dashboard/sufficiency-engine)
each time the badges load. The dataset refreshes daily and badge images are
cached for up to an hour. Weeks start on Monday (UTC). Daily, monthly, version,
and country charts are on the
[ClickPy dashboard](https://clickpy.clickhouse.com/dashboard/sufficiency-engine).

## Where to go next

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } __[Quickstart](getting-started/quickstart.md)__

    ---

    Connect a model, collect a missing answer, and read the result.

-   :material-book-open-variant:{ .lg .middle } __[User guide](guide/index.md)__

    ---

    Requirements, readiness policy, clarification, persistence, and
    provenance, plus how-to guides.

-   :material-connection:{ .lg .middle } __[Integrations](integrations/index.md)__

    ---

    LangGraph task entry, OpenTelemetry, and any other framework.

-   :material-code-braces:{ .lg .middle } __[Examples](examples/index.md)__

    ---

    Complete programs, run in the test suite, with their real output.

-   :material-sitemap-outline:{ .lg .middle } __[Architecture](architecture/index.md)__

    ---

    Components, the assessment lifecycle, and every extension point.

-   :material-api:{ .lg .middle } __[API reference](api/index.md)__

    ---

    Every public class and method, generated from the source.

</div>

!!! warning "Readiness is not a safety guarantee"
    A model can miss or misclassify requirements, and the engine sees only the
    supplied task and answers. Your application remains responsible for
    authorization, task execution, and independent safety checks.
