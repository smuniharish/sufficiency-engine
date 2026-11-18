# Compatibility

Sufficiency Engine is stable and follows [semantic versioning](https://semver.org/)
from 1.0.0. This page states what may change between releases and how stored sessions are protected across upgrades.

## Supported versions

| Component | Supported |
| --- | --- |
| Python | 3.12, 3.13, 3.14, and 3.15, tested on Linux and Windows |
| AGXAI | `>=1.0.2,<2` |
| Pydantic | `>=2.14.3,<3` |
| LangGraph (optional) | `>=1.2.20,<2` |
| OpenTelemetry API (optional) | `>=1.45.2,<2` |

## Public API

The public API is everything in the [API reference](../api/index.md). Only a major
release (1.x to 2.0) removes or changes it incompatibly, and the
[changelog](changelog.md) lists every such change with what to update. Minor
releases only add to it; patch releases do not change it. Names that start with an underscore are private.

## Stored sessions

A paused standalone assessment is stored as a versioned envelope. LangGraph
hosts keep the same assessment state in their graph checkpoint.

| Field | Current value | Meaning |
| --- | --- | --- |
| `StoredSession.version` | `1` | The storage envelope format |
| `schema_version` in the assessment state | `1` | The assessment state format |

An unknown or invalid version is rejected when the session is resumed, with a
`SerializationError`, before any model call, callback, or write. A session is
never partially read or silently reinterpreted.

## Upgrading with active sessions

No release so far changes either version, and no migration exists. When a
release does change one:

1. The changelog states the change and whether earlier sessions can be read.
2. Finish or delete paused sessions before upgrading, unless the changelog
   provides a migration.
3. A migration, when provided, is an explicit step you run. The engine never
   rewrites stored sessions on its own.

Roll back by restoring the previous version together with its stored sessions;
sessions written by a newer version are rejected by an older one.

## AGXAI records

Assessment records are written through AGXAI's public API. Their format follows
AGXAI's own compatibility policy; see the
[AGXAI documentation](https://agxai.readthedocs.io/).