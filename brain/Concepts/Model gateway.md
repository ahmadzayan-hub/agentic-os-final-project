---
type: concept
aliases: [Narrator, Provider-neutral gateway]
tags: [architecture, ai]
status: active
updated: 2026-10-16
review_every_days: 60
sources: [server/model_gateway.py, server/routing.py, docs/adr/0017-choosing-the-narrator.md, .env.example]
---

# Model gateway

Language models in [[Agentic OS]] phrase facts that have already been verified. They never see a dataset row and never produce a number.

- **Default:** deterministic templates, so tests and CI need no credentials.
- **Optional narrators, all configured server-side:** a local Ollama model, which is preferred when set because nothing leaves the machine; Claude; or Groq.
- **Routing:** an optional router picks the narrator for each report, and the report prints why. A choice the deployment cannot reach is refused and reported, never silently swapped.
- **Keys** stay on the server, never in a client bundle, log or screenshot.

This is where two rules in [[Soul]] are enforced in code: raw data never goes to a model, and secrets stay out.

## Related

- [[Agent runtimes and MCP]]: the chat's optional agent loop uses this gateway as its model.
- [[Decision log]]: decisions 0017 and 0019.
