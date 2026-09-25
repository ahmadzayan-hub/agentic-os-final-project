# Maturity Assessment

**Date:** 2026-09-23 · **Basis:** the code as it stands at this commit,
read end to end for this document — not release notes, not memory.
**Question asked:** is this a real, customisable *Agentic OS* that a team
could point at its own projects and get usable output from?

## The verdict in one paragraph

As a **governed business-analytics assistant it is mature and usable
today**: a goal and a CSV become a 22-task run through 21 pipeline stages
plus an approval gate, every claim in the report links to a calculation,
an independent validator can reject the run, the whole thing is durable
across crashes, and 441 Python tests, 23 unit tests and 38 end-to-end
checks run green in CI. That part is real, and it was exercised live
while writing this. As an **"Agentic OS"** it is not yet what the name
promises, in two specific ways. First, the conversational agent is a
command router with templated replies — it recognises `/remember` and
`/set`, and answers everything else with *"Happy to help! I received your
request"*. It does not understand language, reason, or act. Second,
there is no customisation surface: the pipeline is a hard-coded Python
list, so pointing the system at a new domain means editing
`server/analytics.py`. A third gap — the interface was English-only and
left-to-right only — is being closed in the slice this document ships
with.

## Area by area

| Area | Status | Evidence | The gap, precisely |
| --- | --- | --- | --- |
| Analytics pipeline (four types + causal, anomaly, sensitivity, provenance, validation) | **Mature** | `server/analytics.py`; live runs this week; `docs/AGENT_CATALOG.md` | Deterministic by design. Forecast is a straight line with backtested error; prescriptive is a ranking under one assumption. Both say so. |
| Orchestration (Hermes), durability, crash recovery | **Mature** | ADR 0006, 0012; SIGKILL and connection-loss drills in CI | Full database outage drilled by hand only; no standby. |
| Governance: metric glossary, privacy scan, causal-claim refusal, always-valid ranges | **Mature for what it claims** | ADR 0010, 0011, 0016 | Glossary is one file per process — no per-tenant glossary, no editing screen. |
| Model gateway + per-report routing | **Mature, one caveat** | ADR 0007, 0017; LLMRouter integrated and exercised | No live hosted-model call has been made from this environment; LLMRouter's learned routers untested here. |
| Security, tenancy, erasure, supply chain | **Mature for hosted mode** | ADR 0002–0005, 0013–0015 | IdP round-trip unverified live; no row-level security under the application boundary; no signed artifacts. |
| **Conversational agent** | **Partial → ADR 0019, shipped after this assessment** | Was: `generate_response` returned a tone template. Now: `assistant.py` + `server/assistant.py` turn a sentence into one of ten typed actions, by rules or a model, and act | Rules are a vocabulary, not language understanding; one action per sentence; no live model verified from here. The floor is real and the ceiling is the model. |
| **Customisation / extensibility** | **Partial → ADR 0020, shipped after this assessment** | Was: `analytics.PIPELINE` a literal list. Now: `server/stages.py` loads stages by dotted path, validates the contract, places them before the auditors; profiles per run; `examples/stages/target_attainment.py` | A plugin is trusted Python, not sandboxed; the registry is per process; a custom stage cannot narrate or chart. |
| **Frameworks and interoperability** | **Shipped after this assessment → ADR 0021** | No agent framework in the core, by decision; an optional agent runtime behind the chat with LangGraph and Pydantic AI examples; an MCP server in the standard library; a stage built as a graph | Neither runtime has been driven by a live model from this environment; MCP is stdio and local only. |
| Interface: accessibility, performance, responsive, PWA | **Mature** | WCAG 2.2 AA by axe on every view; Lighthouse 96/100/100/100; 320 px up | — |
| **Interface: languages and direction** | **Missing → this slice** | 188 hard-coded English strings; 30 physical-direction CSS rules; `language` preference recorded and ignored | Arabic/English UI, RTL, and agent replies in the chosen language ship with this document. |
| **Report language** | **Shipped after this assessment → ADR 0022** | Was: English only, ~2,400 lines of narrative in `analytics.py`. Now: a run is written in Arabic or English; English stays the audited record; a validator check holds every Arabic claim to its English figures | Fixed per run; identifiers, data and custom stages stay as written; no live model narration verified in Arabic. |
| Data ingestion | **Partial** | CSV, 2 MB, 50,000 rows, in-memory | No XLSX/JSON/Parquet, no database connectors, no larger-than-memory. |
| Scheduling and automation | **Missing** | Runs start from a click or an API call | No "re-run every Monday", no "when this file changes". The lease worker is the right base for it. |
| Obsidian | **Partial** | Approval-gated write-back with provenance frontmatter | Write-only; nothing reads a vault. |
| Cost and usage | **Partial** | Per-owner quotas (ADR 0008) | No currency, no token counts — deliberately, because it would be fabricated. |
| Deployment | **Missing** | `vercel.json` + `api/index.py` ready | No public URL. The import needs the owner's credentials; this environment cannot open tunnels. |

## What "a real Agentic OS" needs next, in the order I would build it

1. **A bilingual, direction-neutral interface** — *shipping with this
   document.* Arabic and English, right-to-left layout, the agent's own
   replies in the chosen language, and the same accessibility bar in both.

2. **A conversational agent that understands and acts** — *shipped as
   ADR 0019 after this assessment was written.* A small, typed set of
   actions: start a run from a sentence ("analyse quarterly_sales by
   team"), answer from memory, explain a section of a report, change a
   preference. A rules-based understander in both languages is the
   no-key default, so tests and CI need no credentials; a model picks
   from the same actions and only its chat phrasing is shown. Every
   write passes the same approval gate; deletion is confirmed first;
   nothing the model says becomes a number. What remains is what a
   model adds — breadth of phrasing — and it is unverified live from
   this environment.

3. **Custom agents as plugins** — *shipped as ADR 0020 after this
   assessment was written.* The stage contract the pipeline already used
   internally is a registry: a project registers a stage by dotted path,
   as a router is, and chooses a pipeline profile per run. The validator,
   the provenance chain and the approval gate apply to a custom stage
   unchanged because there is no placement after them. What remains is
   what a registry cannot give — a sandbox, per-tenant stages, hot
   reload.

4. **Frameworks, where they earn their place** — *shipped as ADR 0021
   after this assessment was written.* The core stays framework-free;
   the assistant takes an optional runtime that may call several tools
   for one sentence but cannot widen what a caller may do; the workspace
   is served as MCP tools; a framework may live inside a custom stage.

5. **Arabic reports** — *shipped as ADR 0022 after this assessment was
   written.* Every sentence a stage writes carries its Arabic beside it;
   calculations and the English claims the validator audits are
   unchanged; a new check rejects any Arabic claim whose figures differ
   from its English twin. What remains is what a translation layer cannot
   give: Arabic month names, and custom stages in a language their
   author did not write.

6. **More inputs** — XLSX and JSON first (they are parsing); database
   connectors later (they are credentials, scheduling and governance).

7. **Scheduling** — a schedule table the existing worker polls, so a run
   can recur. Small, and it is what makes the output arrive without a
   person clicking.

8. **Deployment** — an owner action: import at vercel.com/new with
   Framework Preset *Other*, set `DATABASE_URL`, confirm the sign-in
   round-trip once by hand.

## Two things not to do

- **Do not put a model inside the pipeline stages.** The reason the
  reports can be trusted is that every figure is arithmetic that a
  reader can recompute from the method string. A model narrates; it never
  calculates. Item 2 above keeps that line.
- **Do not fake customisation.** A configuration file that renames
  stages or hides them is not extensibility. The bar for item 3 is that
  a stage written outside this repository runs under the same validator
  and appears in the same provenance chain.

## How this document was produced

Every row above was checked against a file, a test or a live run during
the session that wrote it. Where the evidence is an ADR, the ADR's own
"what is still absent" section was read rather than its title. Counts
(stages, tasks, tests) are the ones `tests/test_docs.py` enforces against
the code, so they cannot drift silently.
