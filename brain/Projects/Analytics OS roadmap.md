---
type: project
aliases: [Analytics roadmap, Dashboard roadmap]
tags: [project, roadmap]
status: active
updated: 2026-10-17
review_every_days: 14
sources: [project-progress.md, server/analytics.py, server/runs.py, server/joins.py, server/query.py, server/modelling.py, server/connectors.py, server/live.py, frontend/src/app/App.tsx, docs/UI_PLAN.md]
---

# Analytics OS roadmap

The [[User]]'s goal for [[Agentic OS]]: a system that digests several datasets with dynamic inputs and carries them through preparation, cleaning and modelling to a multi-page interactive dashboard with live data. The milestone board and status live in `project-progress.md`; this note keeps the reasoning.

## Where it stands (2026-10-17: all seven milestones built)

| Capability | Today | Gap |
| --- | --- | --- |
| Ingestion | A1 (ADR 0024): CSV, TSV, Excel, JSON and JSON Lines through `POST /api/datasets`, 4 MB uploaded and 10 MB as CSV, 50,000 rows, stored once in any format | `.xls`, Parquet; choosing a sheet in the interface |
| Several datasets | A3 (ADR 0030): up to four lookups joined on declared keys right after cleaning, with key coverage and a row recount | Unions; fuzzy keys |
| Dynamic inputs | A2 (ADR 0025): a [[Column mapping]] per dataset, with suggested roles and every-row validation | Weeks and fiscal years; derived columns; more than one breakdown |
| Preparation and cleaning | Trim, dedupe, null non-numbers; the cleaned, merged table downloads and answers queries (A4, ADR 0031) | Imputation, outlier treatment |
| Modelling | Trend with backtest and the analytic stages; on the `models` profile, a regression, a classifier, a clustering and a seasonal forecast, each against a baseline (A6, ADR 0033) | Trees, ensembles, tuning |
| Visualisation | A six-page dashboard per run with filters in the address and drill-down to records (A5, ADR 0032) | Saved layouts; cross-filtering by clicking a chart |
| Live data | Live sources that snapshot into datasets, scheduled refreshes by the worker, and a resumable event stream with a connection badge (A7, ADR 0034) | Sources needing credentials; incremental loads |

## Order of work

1. A dataset API and a dataset picker. Done on 2026-10-16.
2. Column mapping, so the user chooses measures, dimensions and the date. Done on 2026-10-16.
3. Several datasets per run, with declared join keys and a merge stage. Done on 2026-10-17.
4. A cleaned-data download and an aggregates query endpoint. Done on 2026-10-17.
5. Dashboard pages with filters and drill-down. Done on 2026-10-17.
6. New modelling stages, built as [[Custom stages]]. Done on 2026-10-17.
7. Live data: connectors, scheduled re-runs and push updates. Done on 2026-10-17.

A real fetch from a public host is still unexercised: this environment reaches the internet only through a proxy, which connectors refuse by design. Each step kept the tests in `README.md` green; the counts live there.

The interface follows the same order in `docs/UI_PLAN.md`, built to the [[Design system]]: phases 0 and 1 (foundation, Overview and Datasets) shipped on 2026-10-16, and each later phase waits on its milestone.

Each step keeps the [[Governed pipeline]] and the [[Approval gate]], and each needs a decision record in the [[Decision log]] before it ships. Measures follow [[Weighted KPIs]].

## Related

- [[Team 3 Capstone]]: a real multi-page dashboard brief that shows what users will expect.
- [[Soul]]: no feature is presented as shipped before its tests pass.
