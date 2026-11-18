# Agent Skills

Sufficiency Engine publishes two [Agent Skills](https://agentskills.io). They
give a coding agent the instructions, references, scripts, templates, and
evaluations it needs to use Sufficiency Engine correctly. They work in Claude
Code, Codex, Cursor, GitHub Copilot, and any other agent that reads the open
Agent Skills format.

<div class="se-agentic" markdown>

## Agentic installation

Install the skills so your coding agent knows how to:

- place a readiness assessment at your application's task entry;
- collect clarification through your own interface or a LangGraph interrupt;
- keep AGXAI provenance mandatory and recover failed assessments;
- implement durable storage and embeddings at the supported extension points.

=== "Ask your coding agent"

    Give your coding agent the repository and let it install the skills it
    needs.

    ```text title="Agent instruction"
    Install the Agent Skills from https://github.com/smuniharish/sufficiency-engine
    (sufficiency-engine-skills/skills/sufficiency-engine and
    sufficiency-engine-skills/skills/sufficiency-engine-extend) into this
    project, run the sufficiency-engine skill's scripts/verify_setup.py, then
    add a task-readiness assessment to this application, following the skill's
    workflow and safety rules.
    ```

=== "skills CLI"

    The [skills CLI](https://github.com/vercel-labs/skills) finds both skills
    in the repository and installs them for the agents in your project. It
    needs Node.js 22.20 or later.

    ```bash
    npx skills add smuniharish/sufficiency-engine
    ```

    To install a single skill, add `--skill sufficiency-engine` or
    `--skill sufficiency-engine-extend`. Add `-g` to install it for every
    project.

=== "Manual installation"

    Copy the skill directories into your agent's skills directory, for
    example:

    ```bash
    git clone --depth 1 https://github.com/smuniharish/sufficiency-engine.git
    cp -r sufficiency-engine/sufficiency-engine-skills/skills/sufficiency-engine .agents/skills/
    cp -r sufficiency-engine/sufficiency-engine-skills/skills/sufficiency-engine-extend .agents/skills/
    ```

    [Install in your agent](install.md) lists the directory each agent reads.

</div>

## The skills

<div class="grid cards" markdown>

-   :material-check-decagram-outline:{ .lg .middle } __[sufficiency-engine](sufficiency-engine.md)__

    ---

    Adds a readiness gate to an application. Covers the model and
    clarification callbacks, task-entry placement, LangGraph interrupt and
    resume, AGXAI provenance, recovery, and troubleshooting.

    Includes an offline setup check.

-   :material-puzzle-outline:{ .lg .middle } __[sufficiency-engine-extend](sufficiency-engine-extend.md)__

    ---

    Extends the package. Use it to write a durable session store, an archive
    for AGXAI evidence and decisions, or an embedding model for duplicate
    clarification questions.

    Includes a SQLite template and a contract checker.

</div>

Each skill tells the agent when to use the other one, so you can install both
and the agent picks the right one. If your application only consumes
assessments, `sufficiency-engine` alone is enough.

## Use them

Once installed, describe the task. The agent loads a skill when the task
matches it:

| You ask | Skill |
| --- | --- |
| "Ask for missing details before our assistant deploys anything." | `sufficiency-engine` |
| "Gate our LangGraph supervisor on task readiness and resume after the user answers." | `sufficiency-engine` |
| "The assessment failed with `provenance_error`. Recover it without disabling audit." | `sufficiency-engine` |
| "Store assessment sessions in our database, safely across workers." | `sufficiency-engine-extend` |
| "Keep AGXAI evidence and decisions across restarts." | `sufficiency-engine-extend` |
| "Use our local encoder to detect duplicate clarification questions." | `sufficiency-engine-extend` |

You can also invoke a skill by name: `/sufficiency-engine` or
`/sufficiency-engine-extend` in Claude Code, Cursor, and GitHub Copilot, and
`$sufficiency-engine` or `$sufficiency-engine-extend` in Codex.

Both skills teach the agent the rules that keep an integration correct:

- assess at the task entry, never around every model or tool call;
- never invent answers or treat a structurally valid answer as sufficient;
- keep AGXAI provenance mandatory instead of replacing it with a no-op;
- never weaken a storage contract to make a test pass.

## Next steps

<div class="grid cards" markdown>

-   :material-download:{ .lg .middle } __[Install in your agent](install.md)__

    ---

    Where each agent looks for skills, and how to verify and update an
    installation.

-   :material-clipboard-check-outline:{ .lg .middle } __[Evaluation](evaluation.md)__

    ---

    How the skills are tested in CI and how to evaluate them against real
    tasks.

</div>