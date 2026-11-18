# Evaluate a discovery model

The engine's policy is deterministic, but requirement discovery is only as good
as your model. Before production, measure how often your model makes the
engine say **ready when it is not** (false ready) and **not ready when it is**
(false not ready), on cases from your own domain.

## Run the seed fixtures

From the repository:

```bash
uv run python scripts/evaluate_readiness.py
```

In fixture mode, each case's scripted `response` is fed into the real engine.
The seeds check supplied and missing evidence, empty discovery, a policy
injection attempt, optional information, unapproved assumptions, and
transitive prerequisites. This mode tests the engine, **not** a model.

## Evaluate your model

Point the evaluator at your `model_call` and your own labeled cases:

```bash
uv run python scripts/evaluate_readiness.py \
  --callback myapp.evaluation:model_call \
  --path . \
  --fixtures my_cases.json
```

The callable uses the same sync or async `model_call(messages)` contract as the
engine. The evaluator adds no provider dependency and makes no network call of
its own; your module may read credentials from your approved configuration,
never from the fixtures.

The output contains only case IDs, statuses, error codes, and the aggregate
false-ready and false-not-ready counts, so keep case IDs free of sensitive
data. The exit status is nonzero for any mismatch or setup failure. In model
mode, the fixtures' scripted `response` fields are ignored, and a failed
assessment fails the evaluation even when its outcome matches a negative label.

## Evaluate a live model

`scripts/run_live_evaluation.py` runs labeled tasks through the
[OpenAI-compatible adapter](../../examples/openai-compatible.md) against a real
endpoint, repeats each case to expose variance, and also checks clarification:
a case with an `answer` must ask at least one question and become sufficient
after that answer.

```bash
uv sync --group live
export SUFFICIENCY_TEST_LLM_API_KEY=...       # never commit it
export SUFFICIENCY_TEST_LLM_BASE_URL=https://api.example.com/v1
export SUFFICIENCY_TEST_LLM_MODEL=your-model
uv run python scripts/run_live_evaluation.py --repeats 5 --fixtures my_live_cases.json
```

Each case has an `id`, an `input`, and `expected_sufficient`; a clarification
case adds `answer` and `expected_sufficient_after_answer`. The script writes
JSON and Markdown reports to the git-ignored `reports/live-evaluation/`
directory. Reports hold model-derived requirement keys, not credentials, but
review them before sharing. See the [measured results](../../benchmarks.md#live-model-readiness).

## Build a useful case set

Use the seed file's format, and decide the acceptance thresholds **before**
measuring. Include:

- Your domain's real task phrasing, languages, and ambiguity.
- Contradictory and partial answers, and paraphrased requirements.
- Prompt-injection attempts inside task text and answers.
- Weighting for the cost of a false-ready outcome, which is usually far higher
  than a false-not-ready one.

Inspect every false-ready case individually rather than relying on aggregate
accuracy. The seed fixtures are too small to accept a deployment.

## Evaluate question deduplication

```bash
uv run python scripts/evaluate_deduplication.py
uv run python scripts/evaluate_deduplication.py --embedding-factory myapp.embeddings:make_model --path .
```

The labeled fixture has separate calibration and validation splits covering
identical text, paraphrases, negation, numeric changes, constraints, different
slots, and follow-ups. See [Benchmarks](../../benchmarks.md#deduplication-quality)
for the measured results and their limits.
