# The sufficiency-engine skill

The `sufficiency-engine` skill teaches a coding agent to add a readiness
assessment to an application and work with it once it is there. It covers:

- supplying the model, clarification, and notification callbacks;
- calling the engine once, at the application's task entry;
- collecting answers through the host interface or a LangGraph interrupt;
- keeping AGXAI provenance mandatory;
- recovering failed assessments and troubleshooting unexpected results.

[:material-github: View on GitHub](https://github.com/smuniharish/sufficiency-engine/tree/main/sufficiency-engine-skills/skills/sufficiency-engine){ .md-button }
[:material-download: Install](index.md#agentic-installation){ .md-button }

## When the agent uses it

The agent loads the skill when the task involves deciding whether a task has
enough information to proceed: collecting clarification, validating answers,
approving safe assumptions, resuming an assessment, or placing a readiness gate
before a LangGraph supervisor. It also loads it to troubleshoot an unexpected
result or a failed AGXAI recording.

For a storage backend or an embedding model of your own, it hands over to
[sufficiency-engine-extend](sufficiency-engine-extend.md). It does not execute
tasks, manage conversations, or assess every model and tool call.

## Workflow

The skill gives the agent six steps:

```text
1. verify_setup.py passes in the application's environment
2. model_call is supplied; the engine builds the prompt
3. engine.execute(input=task) runs once, at the task entry
4. interrupt_call returns answers using the payload's IDs
5. the full terminal result is consumed; only the host executes
6. project tests and verify_setup.py pass again
```

Production storage and the real discovery model are verified separately.
Offline checks do not certify them.

## What's inside

```text
sufficiency-engine/
├── SKILL.md                 # workflow, references, safety rules
├── references/
│   ├── callbacks.md         # callbacks, evidence, assumptions, recovery
│   └── langgraph.md         # checkpoint-safe interrupt and resume
├── scripts/
│   └── verify_setup.py      # offline setup and behavior check
└── evals/                   # task evals, input files, trigger queries
```

The agent always sees the skill's name and description. It reads `SKILL.md`
when a task matches, and opens a reference only when the task needs it.

## The setup check

`scripts/verify_setup.py` runs offline in the project's Python environment. It
checks that:

- the package and AGXAI import, and their versions;
- a complete task is ready without questions;
- a missing value is asked, answered, and reassessed;
- the result carries AGXAI provenance;
- deleting the session also deletes its AGXAI run;
- with `--langgraph`, a real LangGraph interrupt is answered and resumed.

| Option | Effect |
| --- | --- |
| `--langgraph` | Also check the LangGraph adapter; needs the `langgraph` extra |
| `--json` | Print one JSON object, `{"ok", "version", "checks"}`, for the agent to parse |

It exits with `0` when every check passes and `1` otherwise. Sample output is
on the [install page](install.md#verify).

## Safety rules the agent follows

- **Keep meanings stable.** A requirement key keeps its description and answer
  contract; a changed meaning needs a new key.
- **Keep blockers blocking.** An unresolved required value stays blocking on
  reassessment, and a structurally valid answer is not automatically sufficient.
- **Respect the user.** Preserve explicit declines. Assumptions need an enabled
  policy, low risk, reversibility, and host approval.
- **Keep provenance real.** Never replace AGXAI with telemetry or a no-op
  archive.
- **Protect raw input.** Keep task text and answers out of logs and telemetry.
- **Never replay side effects.** Do not automatically repeat an ambiguous
  interaction or notification.