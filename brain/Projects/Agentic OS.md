---
type: project
aliases: [Agentic OS project]
tags: [project]
status: active
updated: 2026-10-17
review_every_days: 14
sources: [README.md, docs/ROADMAP.md, docs/VERCEL_DEPLOYMENT.md, project-progress.md, docs/adr/0023-the-analytics-workspace-interface.md, docs/adr/0024-the-dataset-api.md, docs/adr/0028-views-load-on-demand.md, scripts/verify.py]
---

# Agentic OS

The product in this repository, described in [[Identity]]: a governed business-analytics assistant with a web workspace and a command-line interface.

## Where it lives

- **Repository:** `ahmadzayan-hub/agentic-os-final-project`, public. The old name `ahmadzayan-hub/11` redirects.
- **Default and working branch:** `claude/agentic-os-final-project-53j6ql`. `main` is behind it, and it stays the default until after submission.
- **Production:** a Vercel deployment behind Vercel Authentication. It is verified for a signed-in owner only, and auth and the database are unverified there.

## What it does today

- Chat in English or Arabic that maps a sentence to a typed action.
- Analyses through the [[Governed pipeline]], sequenced by the [[Hermes orchestrator]], of a dataset in CSV, TSV, Excel, JSON or JSON Lines (ADR 0024), joined with up to four others on declared keys (ADR 0030).
- A six-page dashboard per analysis over its cleaned table (ADRs 0031, 0032), optional models each tested against a baseline (ADR 0033), and live sources that refresh on a schedule and push changes to open pages (ADR 0034).
- Reports with claims linked to calculations, published through the [[Approval gate]].
- Optional narration through the [[Model gateway]]; extension through [[Custom stages]] and [[Agent runtimes and MCP]].
- The bundled [[Sample sales data]] works without an upload.
- An Overview of key figures, the latest findings and the approval queue, and a Datasets view that analyses a stored dataset again by reference. Both follow the [[Design system]].

## Verified state on 2026-10-17

- After views began loading on demand (ADR 0028): `python scripts/verify.py --e2e` with PostgreSQL passed 863 Python tests (16 skipped), the brain check, the type check, 66 frontend unit tests, the build and the budget. First-load JavaScript was 85.7 of 100 KB. End-to-end: 69 passed and 3 skipped by design; the 2 new checks passed after a fix to the test. Lighthouse mobile scored 98, against 99 before.
- `python scripts/verify.py` with PostgreSQL passed all six steps. That run had 851 Python tests; the suite has since grown to 856, all passing with PostgreSQL and the same 16 optional-library skips. It also passed the brain check, the type check, 60 frontend unit tests, the build, and the interface budget (JavaScript 96.7 of 100 KB). The end-to-end suite was not run on this date.
- Every classifying agent is measured ([[Agent evaluation]]).

## Verified state on 2026-10-16

- `python scripts/verify.py --e2e`, with PostgreSQL, passed all seven steps: 719 Python tests with 16 optional-library skips, the brain check, the type check, 54 frontend unit tests, the build, the interface budget (JavaScript 92.9 of 100 KB gzipped, fonts 119.4 of 120 KB), and 63 of 66 end-to-end checks, with 3 skipped by design.
- Lighthouse on the self-hosted server: Performance 99 on mobile in each of three runs and 100 on desktop, with Accessibility, Best Practices and SEO at 100. Before the server compressed and cached the build, mobile Performance was 86 to 88 (ADR 0023, amendment).

These counts go stale fast; `README.md` is the one place where they are maintained.

## Direction

The [[Analytics OS roadmap]]'s seven milestones were built by 17 October 2026: several datasets, dynamic inputs, a dashboard, models and live data. Decisions are in the [[Decision log]].

## Related

- [[User]], who owns it.
- [[Agent team]], the subagents and review loop that check this project's work and deliverables.
- [[Team collaboration]], for how teammates contribute.
- [[Session lifecycle]], for how work on it is run.
