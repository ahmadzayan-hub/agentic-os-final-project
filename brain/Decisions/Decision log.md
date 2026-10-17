---
type: decision
aliases: [ADR index, Architecture decisions]
tags: [decisions]
status: active
updated: 2026-10-17
review_every_days: 30
sources: [docs/adr]
---

# Decision log

Every architecture decision record in `docs/adr/`, one line each. A record states what was true and what was decided on its date. It is never edited to fit later facts; a superseded record points forward instead. A new behaviour change gets a new record, as [[Soul]] requires.

| ADR | Decision | Shapes |
| --- | --- | --- |
| 0001 | SQLite locally, PostgreSQL hosted, for run-engine persistence | [[Agentic OS]] |
| 0002 | Managed identity, roles and tenant isolation | [[Agentic OS]] |
| 0003 | Sign-in flow and request rate limiting | [[Agentic OS]] |
| 0004 | Content-addressed dataset storage and upload | [[Analytics OS roadmap]] |
| 0005 | Backups, restore drills, measured RPO and RTO | [[Agentic OS]] |
| 0006 | Durable execution with database leases, not a workflow engine | [[Governed pipeline]] |
| 0007 | The four business-analytics types as governed agents | [[Governed pipeline]] |
| 0008 | Per-tenant quotas and usage, without inventing costs | [[Agentic OS]] |
| 0009 | Hermes and the size of the specialist roster | [[Hermes orchestrator]] |
| 0010 | Experiment and causal inference as a governed stage | [[Governed pipeline]] |
| 0011 | A metric glossary that can be wrong out loud | [[Weighted KPIs]] |
| 0012 | Failure injection, and what it found | [[Agentic OS]] |
| 0013 | Supply chain: pinned actions and a bill of materials | [[Agentic OS]] |
| 0014 | Memory belongs to an owner | [[Agentic OS]] |
| 0015 | Erasing one owner, and saying what survived | [[Agentic OS]] |
| 0016 | A range that survives being looked at (always-valid ranges) | [[Governed pipeline]] |
| 0017 | Choosing the narrator, and saying who chose it | [[Model gateway]] |
| 0018 | The interface in the reader's language | [[Identity]] |
| 0019 | A conversational agent that understands and acts | [[Model gateway]] |
| 0020 | Custom agents as plugins | [[Custom stages]] |
| 0021 | Agent frameworks: measured, adapted, not adopted | [[Agent runtimes and MCP]] |
| 0022 | Reports in the reader's language | [[Identity]] |
| 0023 | The analytics workspace interface | [[Design system]] |
| 0024 | The dataset API: several formats, one canonical table | [[Analytics OS roadmap]] |
| 0025 | Column mapping: the owner says what each column is | [[Column mapping]] |
| 0026 | Uneven periods are read per record | [[Weighted KPIs]] |
| 0027 | Agents are measured: confusion matrices, recall floors, blind holdouts, seeded reviewer memos | [[Agent evaluation]] |

| 0028 | Views load on demand, idle prefetch and measured first-load budget | [[Design system]] |
| 0029 | Governed run workspace, exact-artifact review and hash navigation | [[Design system]] |
| 0030 | Several datasets per run: declared joins and a merge stage | [[Analytics OS roadmap]] |
| 0031 | The cleaned table: download, fields, totals and records | [[Analytics OS roadmap]] |
| 0032 | Dashboard pages with filters in the address and drill-down | [[Design system]] |
| 0033 | Modelling stages as plugins, each against its baseline | [[Custom stages]] |
| 0034 | Live data: connectors, scheduled refreshes, pushed updates | [[Analytics OS roadmap]] |
| 0035 | A view's strings ship with the view | [[Design system]] |

All seven [[Analytics OS roadmap]] milestones have their records.
