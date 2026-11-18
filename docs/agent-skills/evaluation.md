# Evaluation

The skills are checked automatically on every change and are designed to be
evaluated against real tasks. Automated checks prove that the files are well
formed and the bundled code works. Only an agent evaluation can show whether a
skill helps.

## Automated checks

`tests/test_skills.py` runs offline in continuous integration. For both skills
it checks that:

- the frontmatter passes the `skills-ref` validator, and `metadata.version`
  equals the package version;
- `SKILL.md` links every reference, mentions every script and asset, and every
  relative link resolves;
- every eval's input files exist and compile, and no input file is unused;
- the trigger queries are balanced, split into training and validation sets,
  and no query should trigger both skills;
- `skills.sh.json` advertises the skill directory.

It also runs the bundled code: both scripts with `--help` and `--json`, the
setup check with a real LangGraph interrupt and resume, the contract checker
against the SQLite template, an audited assessment stored through that
template, and the checker's rejection of a store that corrupts state.

Run the same checks locally:

```bash
uv run pytest tests/test_skills.py
```

## Evaluation data

Each skill has an `evals/` folder in the format described in
[Evaluating skills](https://agentskills.io/skill-creation/evaluating-skills):

| File | Contents |
| --- | --- |
| `evals.json` | Three realistic tasks per skill, each with an expected result, gradable assertions, and the input files it starts from |
| `trigger_queries.json` | 10 requests that should load the skill and 10 near misses that should not, split 12/8 into training and validation |
| `files/` | Small starting projects, such as a deployment assistant, a LangGraph supervisor, an application database, and a blocking local encoder |

## Evaluating a change

1. Copy each task's input files into fresh workspaces, one with the skill and
   one without.
2. Run each task in a new agent session. The session without the skill can read
   the installed package but not the skill, the docs, or the repository's
   source.
3. Grade every assertion as passed or failed, with the evidence. Record time and
   tool calls.
4. Compare the two variants. Change the skill where the agent went wrong with
   it, or where it did no better than without it, then evaluate again.

## Results

Run with sufficiency-engine 0.1.0, a general-purpose coding agent, one run per variant, in fresh workspaces. The agent without the skill could read the installed package but not the skill, the docs, or this repository's source. Time and tool calls are as the agent reported them.

| Task | Variant | Assertions | Tool calls | Time |
| --- | --- | --- | --- | --- |
| `sufficiency-engine` #1: gate a deployment assistant | With skill | 2/3 | 17 | 128 s |
| | Without skill | 2/3 | 11 | 87 s |
| | With revised skill | 3/3 | 18 | 87 s |
| `sufficiency-engine` #2: readiness before a LangGraph supervisor | With skill | 3/3 | 14 | 151 s |
| | Without skill | 3/3 | 13 | 119 s |
| `sufficiency-engine-extend` #1: SQLite `PersistenceABC` | With skill | 3/3 | 10 | 151 s |
| | Without skill | 3/3 | 9 | 137 s |
| `sufficiency-engine-extend` #3: blocking local encoder | With skill | 3/3 | 13 | 86 s |
| | Without skill | 3/3 | 11 | 78 s |

Findings:

- Without the skill, the agent still produced correct integrations, because it
  could read the installed package's source and docstrings. The skill did not
  change correctness on these tasks.
- With the skill, the agent ran `verify_setup.py` or `check_extensions.py`
  before and after its change, and ran the extension checker against its own
  SQLite factory. It made one to six more tool calls and took 8 to 41 seconds
  longer, mostly reading the skill and running those checks.
- Neither first run of task #1 told the user that synchronous callbacks run
  in threads that a timeout cannot stop, or that `command_call` is dispatched
  at most once. Step 7 of the `sufficiency-engine` workflow now requires this.
  The revised skill passed all three assertions on a fresh run.
- With the extension skill, task #3 ran `check_extensions.py`, which does not
  cover embeddings, and its tests imported a private module. The workflow now
  says what the checker covers and to test embeddings through the public
  `SufficiencyEngine(embedding_model=...)`. This change has not been
  re-evaluated.
- Tasks `sufficiency-engine` #3 and `sufficiency-engine-extend` #2 were not
  run. Trigger queries were not run either, so routing accuracy is unmeasured.
