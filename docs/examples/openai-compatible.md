# OpenAI-compatible models

Connect the engine to any endpoint that implements the OpenAI chat completions
API: OpenAI, a gateway, or a self-hosted server. The adapter is ten lines; the
engine itself never imports a provider.

Install the client next to the package:

```bash
pip install sufficiency-engine openai
```

## The adapter

The callback sends the engine's messages unchanged and asks for JSON mode, so
the reply parses as discovery JSON. Connection, timeout, rate-limit, and server
errors become `TransientModelError`, which the engine retries up to
`max_model_retries` times; other errors fail the assessment without a retry.

<!-- fmt: off -->
```python
--8<-- "examples/openai_compatible.py"
```
<!-- fmt: on -->

## Run it

```bash
export OPENAI_API_KEY=...                       # never commit it
export OPENAI_BASE_URL=https://api.example.com/v1   # omit for OpenAI itself
export OPENAI_MODEL=your-model
python examples/openai_compatible.py "Translate 'Good morning' into the language my customer speaks."
```

The engine asks which language, waits for your answer in the console, and
reassesses. Example output; the model's wording varies between runs:

```text
What language does your customer speak?
  (The customer's language is not identified, so the correct translation cannot be produced.)
> French

Status: sufficient
Sufficient: True
  target_language: available, blocking=False
```

## Behind a TLS-inspecting proxy

If your network re-signs TLS traffic with a corporate certificate authority,
the OpenAI client's bundled certificates reject it with
`CERTIFICATE_VERIFY_FAILED`. Verify against the operating system's trust store
with [truststore](https://pypi.org/project/truststore/) instead:

```python
import ssl

import httpx
import truststore
from openai import AsyncOpenAI

client = AsyncOpenAI(
    http_client=httpx.AsyncClient(verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
)
```

## Measure it before production

Discovery quality depends on the model. The repository's live evaluation runs
labeled tasks against your endpoint; see
[Evaluate a discovery model](../guide/how-to/evaluate-discovery.md#evaluate-a-live-model)
and the [measured results](../benchmarks.md#live-model-readiness).
