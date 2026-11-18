# Validating the Sufficiency Engine skills

The `sufficiency-engine` and `sufficiency-engine-extend` skills are validated in
three ways: automated checks on every change, evaluations against real tasks,
and a review of every claim against its source.

## Automated checks

Run from the repository root:

```bash
uv run pytest tests/test_skills.py
uvx --from skills-ref agentskills validate sufficiency-engine-skills/skills/sufficiency-engine
uvx --from skills-ref agentskills validate sufficiency-engine-skills/skills/sufficiency-engine-extend
```

`tests/test_skills.py` runs offline in continuous integration. For both skills
it checks that:

- the frontmatter passes `skills-ref`, `name` matches the directory, and
  `metadata.version` equals the package version;
- `SKILL.md` links every reference, mentions every bundled script and asset,
  and every relative link resolves;
- `evals/evals.json` is well formed, every input file it lists exists and
  compiles, and every file under `evals/files/` belongs to an eval;
- `evals/trigger_queries.json` has 20 distinct queries, balanced between
  should-trigger and near misses in both the training and validation splits,
  and no query triggers both skills;
- `skills.sh.json` advertises the skill directory.

It also runs the bundled code:

- every script passes with `--json` and supports `--help`;
- `verify_setup.py --langgraph` completes a real LangGraph interrupt and resume;
- `check_extensions.py` passes `assets/sqlite_store.py`, which then completes an
  audited assessment with its sessions and AGXAI artifacts stored in SQLite;
- `check_extensions.py` rejects a store that corrupts state and reports only
  the error type, never backend details, for a failing factory.

## Evaluations

Each skill has an `evals/` folder, in the format described in
[Evaluating skills](https://agentskills.io/skill-creation/evaluating-skills):

- `evals.json`: realistic tasks with input files, an expected result, and
  assertions a grader can verify.
- `trigger_queries.json`: 10 requests that should load the skill and 10 near
  misses that should not, split 12/8 into training and validation.

To evaluate a change:

1. Copy each task's input files into fresh workspaces, one with the skill and
   one without.
2. Run each task in a new agent session. The session without the skill can
   read the installed package but not the skill, the docs, or the repository's
   source.
3. Grade every assertion as passed or failed, with the evidence. Record time
   and tool calls.
4. Compare the two variants. Change the skill where the agent went wrong with
   it, or where it did no better than without it, then run the evaluation
   again.

Keep workspaces and benchmark files out of the repository.

### Results

Run with a general-purpose coding agent, one run per variant, in fresh workspaces. The first round used sufficiency-engine 0.1.0; tasks `sufficiency-engine` #3, `sufficiency-engine-extend` #2, and the revised extension run used 1.0.0, which has the same API. The agent without the skill could read the installed package but not the skill, the docs, or this repository's source. Time and tool calls are as the agent reported them.

| Task | Variant | Assertions | Tool calls | Time |
| --- | --- | --- | --- | --- |
| `sufficiency-engine` #1: gate a deployment assistant | With skill | 2/3 | 17 | 128 s |
| | Without skill | 2/3 | 11 | 87 s |
| | With revised skill | 3/3 | 18 | 87 s |
| `sufficiency-engine` #2: readiness before a LangGraph supervisor | With skill | 3/3 | 14 | 151 s |
| | Without skill | 3/3 | 13 | 119 s |
| `sufficiency-engine` #3: unresolved region and failing AGXAI writes | With skill | 3/3 | 15 | 121 s |
| | Without skill | 3/3 | 15 | 141 s |
| `sufficiency-engine-extend` #1: SQLite `PersistenceABC` | With skill | 3/3 | 10 | 151 s |
| | Without skill | 3/3 | 9 | 137 s |
| `sufficiency-engine-extend` #2: durable AGXAI semantic archive | With skill | 3/3 | 12 | 162 s |
| | Without skill | 3/3 | 13 | 153 s |
| `sufficiency-engine-extend` #3: blocking local encoder | With skill | 3/3 | 13 | 86 s |
| | Without skill | 3/3 | 11 | 78 s |
| | With revised skill | 3/3 | 17 | 109 s |

Trigger routing was measured blind: an agent saw only the two skill names and descriptions and the 40 trigger queries, shuffled and unlabeled, and chose which skills to load for each.

| Skill | Train | Validation |
| --- | --- | --- |
| `sufficiency-engine` | 12/12 | 7/8 |
| `sufficiency-engine-extend` | 12/12 | 8/8 |

The one miss, "export sufficiency engine traces and metrics through opentelemetry", loaded neither skill. The `sufficiency-engine` description now names OpenTelemetry export, and `references/callbacks.md` covers `OpenTelemetryObserver`. A blind rerun on the train split scored 24/24. The validation split was not rerun after the change, so it was not used for tuning.

Findings:

- Without the skill, the agent still produced correct integrations, because it
  could read the installed package's source and docstrings. The skill did not
  change correctness on these tasks.
- With the skill, the agent ran `verify_setup.py` or `check_extensions.py`
  before and after its change, and ran the extension checker against its own
  SQLite factory. It usually made a few more tool calls, mostly reading the
  skill and running those checks.
- Neither first run of task #1 told the user that synchronous callbacks run
  in threads that a timeout cannot stop, or that `command_call` is dispatched
  at most once. Step 7 of the `sufficiency-engine` workflow now requires this.
  The revised skill passed all three assertions on a fresh run, and the task #3
  run with the skill reported the same callback semantics.
- With the extension skill, the first task #3 run ran `check_extensions.py`,
  which does not cover embeddings, and its tests imported a private module.
  The workflow now says what the checker covers and to test embeddings through
  the public `SufficiencyEngine(embedding_model=...)`. The revised run did
  exactly that and imported no private module.
- In task #3 of `sufficiency-engine`, both variants kept the unresolved region
  blocking, kept `AGXAIAudit` mandatory, and resumed the same session to replay
  the pending audit. In task #2 of the extension skill, both variants stored
  AGXAI's own `Evidence` and `Decision` in a durable `SemanticArchiveABC` next
  to the provenance store, and tested restart, idempotent replay, scope
  isolation, and deletion.
- One run per variant is a small sample. Treat these results as a smoke test of
  the skills, not as a measured effect size.

## Source review

Automated checks cannot tell whether guidance is correct. For every change,
check each snippet and claim against its source:

| Claim area | Source of truth |
| --- | --- |
| Public imports, signatures, and the package version | [`src/sufficiency_engine/__init__.py`](../../src/sufficiency_engine/__init__.py), [`pyproject.toml`](../../pyproject.toml), and the [API reference](../../docs/api/index.md) |
| Assessment lifecycle, callbacks, and failure results | [`src/sufficiency_engine/engine.py`](../../src/sufficiency_engine/engine.py), [configuration](../../docs/getting-started/configuration.md), and [troubleshooting](../../docs/guide/troubleshooting.md) |
| Readiness and blocking decisions | [`src/sufficiency_engine/policy.py`](../../src/sufficiency_engine/policy.py) and [readiness policy](../../docs/guide/concepts/readiness-policy.md) |
| LangGraph interrupts and checkpoints | [`src/sufficiency_engine/integrations/langgraph.py`](../../src/sufficiency_engine/integrations/langgraph.py) and the [LangGraph integration](../../docs/integrations/langgraph.md) |
| Session storage and its contract | [`src/sufficiency_engine/persistence.py`](../../src/sufficiency_engine/persistence.py), [persistence](../../docs/architecture/persistence.md), and [durable storage](../../docs/guide/how-to/durable-storage.md) |
| AGXAI provenance and the semantic archive | [`src/sufficiency_engine/provenance.py`](../../src/sufficiency_engine/provenance.py) and [provenance](../../docs/architecture/provenance.md) |
| Embeddings and duplicate questions | [`src/sufficiency_engine/embedding.py`](../../src/sufficiency_engine/embedding.py) and [semantic duplicates](../../docs/guide/how-to/semantic-duplicates.md) |
| Trust boundaries | [security](../../docs/security.md) |
| Working patterns | [`examples/`](../../examples/) and [`tests/`](../../tests/) |

If a behavior has no implementation, test, or documentation, leave it out of the
skill rather than infer it.

## Routing matrix

Check that the descriptions send each task to the right skill:

| Task | Skill | Route | Avoids |
| --- | --- | --- | --- |
| "Ask for missing details before our assistant deploys." | `sufficiency-engine` | `await engine.execute(input=task)` at task entry with the host's model and clarification callbacks. | Fabricating answers or proceeding while blockers remain. |
| "Gate our LangGraph supervisor on task readiness." | `sufficiency-engine` | `build_assessment_graph` with the host checkpointer and native `Command` resumes. | Reassessing every tool call or adding a second session store. |
| "The assessment failed with `provenance_error`." | `sufficiency-engine` | Repair AGXAI delivery and retry the same session. | Disabling audit or replacing it with a no-op sink. |
| "Store assessment sessions in our database." | `sufficiency-engine-extend` | `PersistenceABC`, the SQLite template, and `check_extensions.py`. | An in-process lock instead of backend atomicity. |
| "Keep AGXAI evidence and decisions across restarts." | `sufficiency-engine-extend` | `SemanticArchiveABC` storing actual AGXAI models. | A custom evidence schema or dropping the provenance store. |
| "Use our local encoder to merge duplicate questions." | `sufficiency-engine-extend` | `EmbeddingModelABC` with inference off the event loop. | Using similarity to decide readiness or drop distinct questions. |
| "Build an agent executor with its own conversation database." | Neither | Not this package's purpose. | Inventing capabilities. |