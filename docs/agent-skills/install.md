# Install in your agent

Each skill is one directory with `SKILL.md` at its root: `sufficiency-engine`
and `sufficiency-engine-extend`. Every agent that supports the
[Agent Skills format](https://agentskills.io/specification) reads the same
directories, so there is no separate copy per agent.

## With the skills CLI

The [skills CLI](https://github.com/vercel-labs/skills) finds both skills in the
repository through `skills.sh.json`, detects the agents in your project, and
installs the skills into each agent you choose. It needs Node.js 22.20 or later.

```bash
npx skills add smuniharish/sufficiency-engine                                     # choose interactively
npx skills add smuniharish/sufficiency-engine --skill sufficiency-engine          # only the core skill
npx skills add smuniharish/sufficiency-engine --skill sufficiency-engine-extend   # only the extension skill
```

From a local checkout of the repository, replace
`smuniharish/sufficiency-engine` with `.`.

| Option | Effect |
| --- | --- |
| `-g` | Install for every project instead of the current one |
| `-a claude-code` | Install for one agent; see the CLI's [agent list](https://github.com/vercel-labs/skills/blob/main/docs/agents.md) |

## Manually

Copy each complete skill directory, including `SKILL.md`, `references/`,
`scripts/`, and `assets/`, into one of the locations for your agent. The
[`sufficiency-engine`](https://github.com/smuniharish/sufficiency-engine/tree/main/sufficiency-engine-skills/skills/sufficiency-engine)
and [`sufficiency-engine-extend`](https://github.com/smuniharish/sufficiency-engine/tree/main/sufficiency-engine-skills/skills/sufficiency-engine-extend)
directories are in the repository. Their `evals/` folders only test the
skills, so you can leave them out.

=== "Claude Code"

    | Scope | Destination |
    | --- | --- |
    | Current repository | `.claude/skills/<skill>/` |
    | All local projects | `~/.claude/skills/<skill>/` |

    Restart Claude Code. It selects a skill when the task matches, or invoke it
    with `/sufficiency-engine` or `/sufficiency-engine-extend`. See
    [Claude Code Skills](https://code.claude.com/docs/en/skills).

=== "Codex"

    | Scope | Destination |
    | --- | --- |
    | Current repository | `.agents/skills/<skill>/` |
    | All local projects | `~/.agents/skills/<skill>/` |

    Codex detects new skills automatically; restart it if a skill does not
    appear. Invoke one with `$sufficiency-engine` or
    `$sufficiency-engine-extend`, or list skills with `/skills`.

=== "Cursor"

    | Scope | Destination |
    | --- | --- |
    | Current repository | `.agents/skills/<skill>/` or `.cursor/skills/<skill>/` |
    | All local projects | `~/.agents/skills/<skill>/` or `~/.cursor/skills/<skill>/` |

    Restart Cursor. In Agent chat, type `/` and select the skill, or let Cursor
    activate it from its description. See
    [Cursor Agent Skills](https://cursor.com/docs/skills).

=== "GitHub Copilot"

    | Scope | Destination |
    | --- | --- |
    | Current repository | `.agents/skills/<skill>/`, `.github/skills/<skill>/` or `.claude/skills/<skill>/` |
    | All local projects | `~/.agents/skills/<skill>/` or `~/.copilot/skills/<skill>/` |

    In Copilot CLI, start a new session or run `/skills reload`, then check
    with `/skills info sufficiency-engine`. Invoke a skill with
    `/sufficiency-engine` or `/sufficiency-engine-extend`. See
    [Adding agent skills for GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills).

=== "Other agents"

    Copy the skill folders into the skills directory your agent documents. The
    skills use only standard `SKILL.md` frontmatter, so they need no
    agent-specific adapter.

    If an agent needs a manifest or registry entry, add only a thin adapter
    that points to these directories. Do not copy the instructions.

## Verify

1. Each installed directory is named after its skill and contains `SKILL.md`.
2. Your agent lists the skills, if it has a skill list.
3. From your project's Python environment, the setup check passes:

    ```bash
    python <skills directory>/sufficiency-engine/scripts/verify_setup.py --langgraph
    ```

    ```text
    PASS  sufficiency-engine 1.0.0, agxai 1.0.2
    PASS  a complete task is ready without questions
    PASS  a missing value is asked, answered, and reassessed
    PASS  the result has AGXAI provenance
    PASS  the session and its AGXAI run are deleted
    PASS  a LangGraph interrupt is answered and resumed
    All checks passed.
    ```

    Without `--langgraph`, the LangGraph check is reported as `SKIP` and the
    core checks still run. Add `--json` to print one JSON object.

4. If you installed `sufficiency-engine-extend`, the SQLite template passes the
   contract checks:

    ```bash
    cd <skills directory>/sufficiency-engine-extend
    python scripts/check_extensions.py --path assets --persistence sqlite_store:make_test_store --archive sqlite_store:make_test_archive
    ```

    The last line is `All 7 contract checks passed.`

## Update

Run `npx skills update`, or replace the installed folders with the latest
directories from the repository, then restart or reload your agent. Each
skill's `metadata.version` matches the Sufficiency Engine release it describes.