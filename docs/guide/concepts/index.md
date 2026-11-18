# Concepts

An assessment turns a task into a set of requirements, decides which of them
block, asks for what is missing, and records the outcome. Each page covers one
part of that process.

| Concept | Answers |
| --- | --- |
| [Requirements and evidence](requirements.md) | What a requirement is, and when information counts as available |
| [Readiness policy](readiness-policy.md) | Which requirements block, and when assumptions are allowed |
| [Clarification](clarification.md) | When the engine asks, how answers are validated, and how questions are deduplicated |
| [Persistence and recovery](persistence.md) | What a session stores, and how claims, revisions, and fencing protect it |
| [Provenance](provenance.md) | What is recorded in AGXAI, and what a failed audit means |

## Outcomes

Every assessment ends with one `AssessmentStatus`:

| Status | Meaning |
| --- | --- |
| `sufficient` | Every active required requirement is supported, and the decision was recorded in AGXAI |
| `insufficient` | Something still blocks, and no question or approved assumption can resolve it |
| `cancelled` | The application cancelled the assessment through its interaction response |
| `iteration_limit_reached` | The clarification budget, `max_iterations`, was used up |
| `failed` | The assessment could not be completed safely; see `errors` |

Only `sufficient` sets `sufficient=True`. Treat every other status as "do not
proceed yet".
