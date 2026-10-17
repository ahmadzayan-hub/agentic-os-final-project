---
type: concept
aliases: [Custom agents, Stage plugins]
tags: [architecture, extension]
status: active
updated: 2026-10-16
review_every_days: 60
sources: [server/stages.py, docs/adr/0020-custom-agents-as-plugins.md, examples/stages/target_attainment.py]
---

# Custom stages

A domain stage is a file: a class with a role, a title, a place in the [[Governed pipeline]] and a `run(ctx)` method, registered by dotted path.

- It runs on a copy of the context, before provenance, validation and reporting, so its claims face the same validator as a built-in stage.
- Its result shape is checked before anything is recorded, and its IDs must carry its role prefix.
- Profiles choose which custom stages a run includes, and `/api/pipelines` lists what loaded and why anything did not.
- A plugin is trusted Python, not a sandbox.

This is the planned route for the new modelling methods in the [[Analytics OS roadmap]]: classification, regression, clustering and seasonal forecasting.

## Related

- [[Hermes orchestrator]]: it places custom stages in the run.
- [[Agent runtimes and MCP]]: the other extension seams.
- [[Decision log]]: decision 0020.
