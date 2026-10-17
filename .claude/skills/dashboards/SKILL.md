---
name: dashboards
description: Deep analysis of a dataset through the governed pipeline (scripts/analyse.py), then a dashboard where every figure shows its source. In claude.ai cloud sessions it builds a real Claude Dashboard with the Dashboard artifact type; anywhere else, or offline, it writes a free self-contained HTML dashboard (render.py). Use for KPI pages, scorecards, management dashboards, capstone or client dashboards, and "analyse this file and show me".
---

# Dashboards

Claude Dashboards, announced by Anthropic on 8 October 2026, is a hosted claude.ai feature in beta on paid plans. It turns questions about data into a dashboard that stays current, and clicking a number shows its query. It has no package to install. This skill reaches it where it exists and gives the same standard everywhere else: **every figure comes from a calculation you can point to.**

## Step 1: analyse with the governed pipeline

```bash
python scripts/analyse.py data.xlsx --suggest --out analysis.json --csv-dir aggregates/
python scripts/analyse.py data.csv --mapping mapping.json --goal "Why did margin fall?" --language ar --out analysis.json
```

- **What it runs:** the app's own pipeline: reading (ADR 0024), the column mapping (ADR 0025, or `--suggest` to accept the suggested one), and every specialist stage up to the approval gate.
- **Cost:** it calls no model and costs nothing. The sample analyses in a quarter of a second.
- **`analysis.json`:**
    - every calculation, with a `ref` such as `preparer.c_total` and its method;
    - every claim, with the calculations behind it;
    - the failed quality checks;
    - the charts, and a headline for each analytics type;
    - the prepared aggregates.

  It never holds rows.
- **`--csv-dir`:** writes `by_group.csv`, `trend.csv` and `calculations.csv`, small aggregate files fit to be dashboard datasets. Each total carries its record count and per-record value.

Read `failed_checks` and the claims marked `limitation` or `warning` before choosing what to show. A dashboard must not hide them.

**Per record before totals (ADR 0026).** When periods or groups hold different numbers of records, totals move with the count. On the capstone data, monthly loss "fell 39%" only because 2026 months hold 83 records against 167. Per record it was flat, and the criticality level with the largest total was not the one with the largest loss per record. The pipeline names this in a `cl_uneven_periods` limitation, and the default page adds per-record charts.

## Step 2a: a Claude Dashboard (claude.ai cloud sessions)

When the `Artifact` tool is available and lists the **Dashboard** type (`Artifact` `action: "list"`, `scope: "types"`):

1. Create it with that type's `type_url` and a title, then follow the instructions the create result returns. They are the authority.
2. **Data:**
    - Attach the aggregate CSVs from step 1 as file datasets. Upload with `asset: true`, and attach aggregates, never the raw file, unless the person asks for it.
    - If the data lives in a connected warehouse, use a live query instead, so the dashboard stays current.
3. **Marks:** every figure, chart and table on the page is marked with its dataset (`data-source`, `data-field`). That is how a reader clicks through to where a number came from.
4. **Hand-over:** say what it shows and what was assumed. Name any limitation from the analysis.

## Step 2b: an offline dashboard (free, anywhere)

```bash
python .claude/skills/dashboards/render.py --analysis analysis.json --out dashboard.html --write-spec spec.json
python .claude/skills/dashboards/render.py --spec spec.json --check     # validate an edited spec
python .claude/skills/dashboards/render.py --spec spec.json --out dashboard.html
```

- **The default page:** from an analysis, `render.py` builds the following. Edit `spec.json` to choose and order what matters for the audience.
    - Key figures.
    - A "Read with care" section of limitations and failed checks, before any chart.
    - The trend and the breakdown, with per-record versions when sizes differ.
    - The headlines.
    - A table of every claim with its evidence.
- **The spec:**
    - sections of type `kpis`, `bars`, `line` (with `forecast_from`), `table` and `text`;
    - every KPI and bar item needs a `source`, and so does every line and table. The renderer refuses one without.
- **The output:**
    - one HTML file with SVG charts drawn in Python: no scripts, no network;
    - numbered sources at the foot, and each chart's numbers in a table;
    - English or Arabic, light or dark, printable.

## Rules

1. Figures come from `analysis.json`, a KPI register or another verified source, and nothing else. Cite each one: a calculation `ref` or a register row.
2. Raw data never goes to a model. The analysis is deterministic; only aggregates are attached to a dashboard.
3. Course and client dashboards are written outside the repository. Only sample-data examples belong here.
4. Before handing over, check that every number on the page is sourced:

    ```bash
    python scripts/figures_check.py --register aggregates/calculations.csv --value-column value \
        --label-columns ref,name --doc dashboard.html --reference analysis.json \
        --reference aggregates/trend.csv --reference aggregates/by_group.csv --sourcing-only
    ```

    Run the `review-loop` skill for anything that will be submitted.
