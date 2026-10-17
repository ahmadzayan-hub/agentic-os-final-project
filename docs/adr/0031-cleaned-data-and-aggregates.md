# ADR 0031 — A run's cleaned table: download, fields, aggregates and records

**Status:** Accepted
**Date:** 2026-10-17
**Milestone:** A4 in `project-progress.md`; serves phase 3 of `docs/UI_PLAN.md` (dashboards, ADR 0032)
**Keeps:** tenancy (another owner's run is missing, never forbidden), raw data never sent to a model, ratios of sums for rates (`brain/Concepts/Weighted KPIs.md`), the standard-library core

## Context

A run cleans its data, and from ADR 0030 merges it, but the table it then analyses never leaves the server. Two needs follow:

1. **The owner wants the cleaned table.** The report says "1,204 rows kept, 13 removed"; the owner should be able to check that in a spreadsheet, and reuse the cleaned, merged table elsewhere (Power BI, for one).
2. **A dashboard needs to ask questions of the table.** Filtering to one region and totalling by month is a question the pipeline did not ask. Sending the whole table to the browser does not scale to 50,000 rows and puts every row on every device that opens the dashboard.

## Decision

### 1. One table per run: the analysis table

The table is the one every analysis stage after cleaning reads (`analytics._rows`): the Data Merge Agent's output when the run joins datasets, otherwise the Data Cleaning Agent's. It is available as soon as that stage has succeeded; before then the endpoints answer 409, saying the table is not ready, in the reader's language. Its columns are typed as the run typed them: measures are numbers, everything else is text, and a mapped date is the period label the cleaner wrote (`2025-03`, `2025-Q1`).

The table is read from the stored task result, so it is exactly what the run analysed, and it never changes: a run's results are written once.

### 2. Download: `GET /api/runs/{id}/data.csv`

- UTF-8 with a byte-order mark, so Excel reads Arabic correctly, and RFC 4180 quoting.
- Numbers are written plainly: `1200`, not `1200.0`; an empty measure is an empty cell.
- **Formula injection is neutralised.** A text cell starting with `=`, `+`, `-`, `@`, a tab or a carriage return gets a leading apostrophe, the OWASP advice for CSV opened in a spreadsheet. Measures are numbers and are never altered.
- `Content-Disposition: attachment`, named after the run, with an RFC 5987 UTF-8 file name.

### 3. Fields: `GET /api/runs/{id}/fields`

Each column with its type (`number` or `text`), its role in the run (measure, breakdown, date, joined), how many values are filled, and:

- for a number: the minimum and maximum;
- for text with at most 200 distinct values: the values, sorted (time order for period labels);
- for wider text: the distinct count only.

This is what a filter control needs, without the rows.

### 4. Aggregates: `POST /api/runs/{id}/query`

```json
{
  "group_by": ["region", {"column": "revenue", "bins": 10}],
  "measures": [{"agg": "sum", "column": "revenue"}, {"agg": "count"},
               {"agg": "ratio", "numerator": "profit", "denominator": "revenue"}],
  "filters": [{"column": "region", "op": "in", "values": ["North", "South"]},
              {"column": "month", "op": "between", "values": ["2025-01", "2025-06"]}],
  "sort": {"by": "sum:revenue", "desc": true},
  "limit": 100
}
```

| Part | What is allowed |
| --- | --- |
| `group_by` | Up to two columns; a measure column may be cut into 2 to 50 equal-width bins |
| `measures` | One to eight of `sum`, `mean` (per record with a value), `min`, `max`, `count` (records), `distinct`, and `ratio`, which is the sum of the numerator over the sum of the denominator, never an average of row rates |
| `filters` | Up to twelve: `eq`, `ne`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`, `between` (inclusive), `empty`, `not_empty`. A filter on a measure compares numbers; on text, text, which is time order for period labels |
| `sort` | A group column or a measure key; groups come in key order otherwise |
| `limit` | 1 to 1,000 groups; the answer says how many groups there were in all |

The answer carries every group's keys and values, the number of records each group holds (ADR 0026: a reader can always compare per record), how many records matched the filters and how many the table has. Every refusal is a 422 with each problem by field, in the reader's language, the shape mappings and joins already use.

### 5. Records: `POST /api/runs/{id}/records`

The rows behind a figure, for drilling down: the same filters, a sort, and a page of at most 100 rows from an offset, with the total. `sample` returns at most that many rows evenly spaced through the matching ones, for a scatter chart that needs points, not pages.

### 6. Isolation, cost and caching

- Every endpoint checks ownership first, as the run endpoints do: another owner's run is a 404. A viewer may read all four; none writes anything.
- The table is parsed from the stored result once and kept, as rows of tuples, in a small cache of the three most recently read runs, keyed by the stage's task and its update time. A 50,000-row table is answered without parsing it again.
- Queries run outside the server's lock, so a large aggregate does not hold up other requests.

## Consequences

- An owner can check and reuse the cleaned, merged table, and a dashboard can ask the table its own questions without receiving it.
- The query language is deliberately small: no expressions, no joins at query time, no SQL. What a dashboard needs that it cannot express is a reason for a new, reviewed operation, not a free-text query.
- A rate is computed one way everywhere: a ratio of sums.

## Not done here

- Parquet or Excel downloads; the CSV is the interchange format.
- Writing back: the table is the run's record and is read-only.
- Querying across runs; a dashboard reads one run.
