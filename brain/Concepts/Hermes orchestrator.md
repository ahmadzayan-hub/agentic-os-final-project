---
type: concept
aliases: [Hermes]
tags: [architecture]
status: active
updated: 2026-10-16
review_every_days: 60
sources: [server/analytics.py, docs/adr/0009-hermes-and-the-specialist-roster.md]
---

# Hermes orchestrator

Hermes sequences the stages of the [[Governed pipeline]] and holds the [[Approval gate]]. It analyses nothing itself.

That separation is structural, not a convention. Because the orchestrator computes no result, no stage ever approves its own work. Validation is a separate stage, and publication waits for a person.

## Related

- [[Agentic OS]]: the product it runs inside.
- [[Custom stages]]: Hermes places plugin stages before provenance, validation and reporting, never after them.
- [[Decision log]]: decision 0009 named Hermes and fixed the roster.
