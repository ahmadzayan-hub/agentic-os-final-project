# ADR 0032 — Dashboard pages: one run's table, filtered everywhere, drilled to rows

**Status:** Accepted
**Date:** 2026-10-17
**Milestone:** A5 in `project-progress.md`; phase 3 of `docs/UI_PLAN.md`
**Keeps:** hand-drawn SVG charts and no chart library (ADR 0023), views that load on demand (ADR 0028), per-record reading of uneven groups (ADR 0026), ratios of sums for rates, every interface string in English and Arabic

## Context

A run ends in a report: one measure, one breakdown, up to four charts fixed when it ran. A reader who wants the same numbers for one region, a different breakdown, or the rows behind a bar has had to start another run. ADR 0031 gave each run's cleaned table a small query API; this decision is the interface that uses it.

## Decision

### 1. A dashboard is a view of one run's table

The Dashboard view opens on a run whose table is ready. Its address carries everything a reader chose:

```
#/dashboard/{run}/{page}?f.region=North|South&from=2025-01&to=2025-06&by=channel
```

so a filtered page survives a reload and can be sent to a colleague who has access to the run. Without a run in the address it lists the runs whose tables are ready. The Runs view links to it from a finished run.

### 2. Pages follow the table, not a template

| Page | Shown when | What it holds |
| --- | --- | --- |
| Overview | always | Records matched, the analysed measure's total and its value per record, and the size of the largest group; the trend and the top groups |
| Breakdown | a text column exists | The measure by any text column, as totals or per record (ADR 0026), largest first, with each group's records one step away |
| Trend | the run has a date | Total and per record by period, so uneven periods are read correctly |
| Distribution | always | The measure in twelve equal-width bins |
| Relationship | a second measure exists | The measure against another, from an even sample of at most 500 rows |
| Records | always | The rows behind every page, 25 at a time, sortable |

Every figure comes from `POST /api/runs/{id}/query`; rows from `/records`. Nothing on a page is computed from a sample except the relationship chart, which says so.

### 3. Filters apply to every page

A filter bar holds a value list for each text column with at most 200 values, and a from–to range on the date. A filter set on one page holds on all of them, and on the Records page. Each page says how many of the table's records it covers. **Drilling down** from a group (a bar, a period or a table row) sets that group as a filter and opens the Records page, so the rows behind any figure are one step away, by keyboard as well as by pointer.

### 4. Charts

Bars, lines, a histogram and a scatter, drawn as SVG from design tokens, with bars from a zero line, axes that read left to right in both languages, and labels shortened only where the full text is in the table beside them. **Every chart has its numbers as a table**, and the table's rows are where keyboard and screen-reader users drill down. A chart is an image with a text alternative that states what it shows; it holds no focusable element.

### 5. Budget

The dashboard is its own chunk, and its styles ship in their own stylesheet, fetched with the chunk. The CSS budget is redefined the way ADR 0028 redefined the script budget: the stylesheet on the first load stays at most 10 KB gzipped, and all stylesheets together at most 16 KB. `scripts/verify.py` measures both.

## Consequences

- A reader can slice a run's figures without starting another run, and every slice is a ratio of sums over the same cleaned table the report used.
- A dashboard is per run: comparing two runs is two dashboards.
- The pages are chosen from the table's fields and roles, so a dataset with no date simply has no Trend page.

## Not done here

- Saving a named layout, choosing chart types per page, or pinning a dashboard; the address is the saved state.
- Cross-filtering by dragging over a chart.
- Live refresh, which belongs to A7 (ADR 0034).
