# Benchmarks

Sufficiency Engine runs inside your application's process, before the task
starts, so its cost is the latency it adds to task entry. In practice the
model call dominates that latency. This page shows the library's own overhead,
measured on one machine, how well it detects duplicate questions, and how to
measure both on yours.

## Overhead

`scripts/benchmark.py` measures each scenario with a deterministic local model
and in-memory AGXAI, in one process with no network. It excludes model, network,
and storage time, which depend on your deployment.

| Scenario | Samples | p50 ms | p95 ms |
| --- | ---: | ---: | ---: |
| Audited assessment of a complete task | 40 | 16.77 | 21.52 |
| Readiness policy, 256 requirements and 2,012 dependency edges | 40 | 10.58 | 15.77 |
| Lexical deduplication of 64 questions | 10 | 37.88 | 50.05 |
| Vector deduplication of 64 questions, 1,024 dimensions | 10 | 1,049.97 | 1,691.48 |

Peak Python allocation across all scenarios was 2.43 MiB. Measured with
Python 3.14.7 on Windows AMD64.

- **An audited assessment costs milliseconds.** Discovery parsing, policy, and
  AGXAI recording together add about 17 ms at p50, small next to a model call.
- **The policy scales to the default limits.** The largest dependency graph the
  default [`Limits`](api/engine.md) allow evaluates in about 11 ms.
- **Vector comparison is the expensive step.** It is pure Python and compares
  every pair of questions, so it grows with the square of the question count and
  with the vector size. It runs only when you supply an `embedding_model`.

## Deduplication quality

`scripts/evaluate_deduplication.py` runs the clarification pipeline over 14
labeled question pairs in `tests/fixtures/deduplication.json`, split into
calibration and validation sets. Each pair is labeled as equivalent or not.

| Stage | Split | Precision | Recall |
| --- | --- | ---: | ---: |
| Lexical candidates | calibration | 0.67 | 0.67 |
| Lexical candidates | validation | 0.67 | 0.67 |
| Questions actually merged | calibration | 1.00 | 0.33 |
| Questions actually merged | validation | 1.00 | 0.33 |

- **Candidates are never merged.** A lexical candidate is a pair of questions
  for the same answer slot whose normalized text scores at least 90, but less
  than 100, with RapidFuzz. The evaluation reports how well that rule finds
  duplicates; the engine never merges on it.
- **Only identical questions merge.** The pipeline merges a question only when
  its normalized text and answer slot match exactly. That is why its precision
  is 1.0: it never dropped a distinct question, including near negations,
  different numbers, and follow-ups.
- **The cost is recall.** Polite rewordings and paraphrases are asked twice.
  The design prefers asking a duplicate question to losing a distinct one.
- **Embeddings add warnings, not merges.** With an embedding model, such as
  BGE-M3 through the [optional example](examples/bge-m3.md), a lexical
  candidate whose cosine similarity is at least 0.98 adds a
  `potential_duplicate` warning. Both questions are still asked. On these
  fixtures, BGE-M3 added no warnings.

The fixtures are small and hand-written. Label examples from your own domain
before relying on these figures; see
[Evaluate discovery](guide/how-to/evaluate-discovery.md).

## Live model readiness

`scripts/run_live_evaluation.py` runs the eight labeled tasks in
`tests/fixtures/live_readiness.json` through the real engine and a real model,
using the [OpenAI-compatible adapter](examples/openai-compatible.md). A run
passes only when the readiness outcome matches its label, the assessment did not
fail, and AGXAI recorded its decisions. Clarification cases must also ask at
least one question and become sufficient after a scripted answer.

Measured against `gpt-5.6-luna` through an OpenAI-compatible gateway, five
repeats of each case, four in parallel:

| Case | Expected | Passed | Questions | p50 s | Max s |
| --- | --- | ---: | ---: | ---: | ---: |
| Complete: Python function | Sufficient | 5/5 | 0 | 4.68 | 6.57 |
| Complete: translation | Sufficient | 5/5 | 0 | 3.65 | 5.17 |
| Complete: arithmetic | Sufficient | 5/5 | 0 | 4.77 | 9.38 |
| Missing flight details | Not ready | 5/5 | 0 | 11.25 | 12.14 |
| Missing email recipient | Not ready | 5/5 | 0 | 4.36 | 5.47 |
| Prompt injection claiming readiness | Not ready | 5/5 | 0 | 5.68 | 6.85 |
| Unknown language, then answered | Ready after one answer | 5/5 | 1 | 7.72 | 8.13 |
| Unknown season, then answered | Ready after one answer | 5/5 | 1 | 6.86 | 9.90 |

All 40 runs passed, with no false-ready outcome and no failed assessment. The
latency is almost entirely the model call; one clarification round costs a
second model call.

- **The first measurement found two prompt weaknesses.** Before the discovery
  prompt said which details are optional and when to ask rather than block,
  21 of 24 runs passed. The model marked a function name or empty-list
  behavior as mandatory in two of three code-task runs, and once blocked on an
  unknown season without proposing a question. The current prompt fixes both.
- **Not-ready cases block without asking** because the evaluation supplies no
  clarification callback for them; with one, they would ask.

Eight hand-written tasks and one model are a smoke test, not an acceptance
benchmark. Label tasks from your own domain and measure your own model before
relying on it; see [Evaluate a discovery model](guide/how-to/evaluate-discovery.md#evaluate-a-live-model).

## Reproduce

```bash
uv run python scripts/benchmark.py --runs 40
uv run python scripts/evaluate_deduplication.py
```

Both print one JSON object. To include a real embedding model, pass a trusted
factory with `--embedding-factory MODULE:FACTORY`.

The live evaluation needs a model endpoint and sends the fixture tasks to it:

```bash
uv sync --group live
export SUFFICIENCY_TEST_LLM_API_KEY=...       # never commit it
export SUFFICIENCY_TEST_LLM_BASE_URL=https://api.example.com/v1
export SUFFICIENCY_TEST_LLM_MODEL=your-model
uv run python scripts/run_live_evaluation.py --repeats 5
```

It writes JSON and Markdown reports to the git-ignored `reports/live-evaluation/`
directory and exits nonzero when any run fails.