# Sufficiency Engine Agent Skills

This directory distributes two Agent Skills that teach coding agents to use the
`sufficiency-engine` package correctly. They are not part of the Python package
and add no runtime behavior.

| Skill | Use it to |
| --- | --- |
| [`sufficiency-engine`](skills/sufficiency-engine/SKILL.md) | Add a readiness gate to an application: supply model and clarification callbacks, place the assessment at task entry or in a LangGraph graph, keep AGXAI provenance, recover failed assessments, and troubleshoot |
| [`sufficiency-engine-extend`](skills/sufficiency-engine-extend/SKILL.md) | Extend the package: write a durable `PersistenceABC` session store, a `SemanticArchiveABC` for AGXAI artifacts, or an `EmbeddingModelABC` for duplicate-question detection |

Install both with the [skills CLI](https://github.com/vercel-labs/skills), which
finds them through [`skills.sh.json`](../skills.sh.json):

```bash
npx skills add smuniharish/sufficiency-engine                                 # both
npx skills add smuniharish/sufficiency-engine --skill sufficiency-engine      # one
```

From a local checkout, use `npx skills add . --skill sufficiency-engine`. Other
ways to install are in the [documentation](../docs/agent-skills/install.md).

## Layout

Each skill follows the [Agent Skills specification](https://agentskills.io/specification):

```text
skills/<skill>/
├── SKILL.md      # frontmatter, workflow, boundaries, links to every file
├── references/   # focused documents, read only when a task needs them
├── scripts/      # offline checks with --help, --json, and meaningful exit codes
├── assets/       # templates the agent copies into the project
└── evals/        # evals.json, trigger_queries.json, and the input files they use
```

| Skill | Scripts | Assets |
| --- | --- | --- |
| `sufficiency-engine` | `verify_setup.py`: an offline assessment, clarification, and AGXAI audit check; `--langgraph` adds a real interrupt and resume | — |
| `sufficiency-engine-extend` | `check_extensions.py`: runs the persistence and archive contract checks against any factory | `sqlite_store.py`: a standard-library SQLite session store and semantic archive that passes those checks |

Every Agent Skills host reads the same directories, so there is no separate copy
for Claude Code, Codex, Cursor, or GitHub Copilot. The skills ship in the source
archive, not in the Python wheel.

## Format

- `name` matches the directory. The `description` starts with "Use this skill
  when", names near misses, and hands over to the other skill where they meet.
- `license`, `compatibility`, and `metadata.version` are set. The version equals
  the `sufficiency-engine` release the skill describes.
- `SKILL.md` stays short and links every reference with the task that needs it.
  Scripts and assets are referenced by paths relative to the skill directory.

## Maintaining the skills

When the public API or documented behavior changes:

1. Update the affected skill, and `metadata.version` in both skills with each
   release.
2. Check every changed snippet and claim against the code, tests, or
   documentation. Leave out anything that is not implemented.
3. Add or update an eval when the change affects what an agent should do.
4. Run the checks in [`validation/README.md`](validation/README.md).

The skills are covered by the repository's Apache License 2.0; see
[LICENSE](../LICENSE).