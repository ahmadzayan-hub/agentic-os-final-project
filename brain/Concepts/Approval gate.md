---
type: concept
aliases: [Approval-gated publishing]
tags: [governance]
status: active
updated: 2026-10-16
review_every_days: 60
sources: [docs/OBSIDIAN_INTEGRATION.md, server/runs.py]
---

# Approval gate

A report is published only after a person approves it. The approval is bound to the exact hash of the report it was given for, so a report changed afterwards needs approving again. Rejected runs publish nothing.

On approval, the run writes two notes into the runtime `vault/` folder: the report, with provenance frontmatter, and its run log. That vault holds user data and is git-ignored. It is separate from this [[Second brain]], which is curated project knowledge committed to the repository.

The gate is the product's version of a rule in [[Soul]]: people approve consequential actions.

## Related

- [[Governed pipeline]]: the gate is its final task.
- [[Hermes orchestrator]]: it holds the gate.
- [[Agent runtimes and MCP]]: no tool, framework or editor agent can approve on a person's behalf.
