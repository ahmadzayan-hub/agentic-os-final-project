# ADR 0025 — Column mapping: the owner says what each column is

**Status:** Accepted
**Date:** 2026-10-16
**Milestone:** A2 in `project-progress.md`; part of phase 2 of `docs/UI_PLAN.md`
**Keeps:** content-addressed datasets (ADR 0024), the metric glossary (ADR 0011), tenancy, raw data never sent to a model, the standard-library core

## Context

A run decides three things about its data before any analysis:

- which number it is about (the measure);
- what to break that number down by (the dimension);
- what time is (the date).

Until now it guessed each of them:

| Decision | How it was guessed | How the guess goes wrong |
| --- | --- | --- |
| Measure | A glossary metric, else a column named revenue, sales, amount, value or total, else the first numeric column (`server/metrics.resolve`) | Without a glossary, `store_id` or `year` can be the "first numeric column" |
| Numbers | A column is numeric when 90% of its values parse after removing commas | `$1,200`, `(300)`, `١٢٠٠` and `12%` do not parse, so a currency column is analysed as text, or not at all |
| Date | A column named exactly month, date, period, week or year | `order_date`, `Record_Date` and `التاريخ` are never found, so there is no trend and no forecast |
| Period order | Labels sorted as text | `03/2025` sorts before `11/2024`, and `Jan`, `Feb`, `Mar` sort alphabetically |
| Dimension | The first column that is neither numeric nor the date | An ID or a free-text note becomes the breakdown |

The capstone dataset shows the cost. Its date column is called `Record_Date`, so the pipeline would see no time axis, and its first text column is the record ID.

A1 gave datasets a life before any run (ADR 0024). That makes the fix possible: the person who owns a dataset can say once what each column is, and every run of it can follow that.

## Decision

### 1. A mapping gives every column one role

```json
{
  "roles": {"month": "date", "region": "dimension", "revenue": "measure",
            "units": "measure", "notes": "ignore"},
  "measure": "revenue",
  "dimension": "region",
  "date_order": "auto",
  "grain": "auto"
}
```

| Field | Values | Meaning |
| --- | --- | --- |
| `roles` | `measure`, `dimension`, `date`, `ignore`, one per column | Every column is named, so nothing is mapped by omission |
| `measure` | A column whose role is `measure` | The number the run is about. Other measures become candidate drivers in the diagnostic stage |
| `dimension` | A column whose role is `dimension`, or `null` | What totals are broken down by. `null` means no breakdown |
| `date_order` | `auto`, `day-first`, `month-first` | How to read `03/04/2025`. `auto` decides from the data, and asks when it cannot |
| `grain` | `auto`, `day`, `month`, `quarter`, `year` | The period a trend is summed over. `auto` keeps the data's own precision, then coarsens until there are at most 36 periods |

The mapping is saved with the dataset, per owner, and is the same for every run of that dataset until the owner changes it.

Several alternatives were rejected:

- **Measures, dimensions and the date as three lists.** These can overlap, and they say nothing about the remaining columns.
- **Mapping inside each run request.** The owner would have to repeat it for every run, and two runs of the same data could disagree.
- **A separate mappings table.** A dataset has one owner, so one mapping per dataset row is enough, and it is backed up with the row.

### 2. The server validates against the data, and explains in the reader's language

`PUT /api/datasets/{id}/mapping` checks the mapping against every row, not just the preview:

- every column has exactly one role, and no unknown column is named;
- there is at least one measure, `measure` names one of them, and at most one column is the date;
- each measure parses as a number in at least half of its filled cells, using the number reading in §4;
- the date parses as a date at the chosen grain in at least half of its filled cells;
- when `date_order` is `auto` and the values cannot tell day from month (every part is 12 or less), the server asks rather than guesses.

A refusal is `422`, and its `detail` holds a summary message and a list of errors, each naming its field or column. The interface shows the summary at the top and each error beside its field. Every message is in English or Arabic, as the request asks.

### 3. The server suggests; the owner decides

`GET /api/datasets/{id}` returns the first five rows, a profile of each column, the saved mapping, and a suggested one.

- **The profile** gives each column's type (number, date, text or empty), how many cells are filled, the share that read as numbers and as dates, the number of distinct values, and three examples.
- **The suggestion** has a reason for each column:
    - a column that reads as dates, or is named like one, becomes the date;
    - a column that is a number in nine cells out of ten becomes a measure, unless it is a whole number unique in every row, which looks like an identifier and is suggested as `ignore`;
    - text with few distinct values becomes a dimension, and text that is nearly unique, such as names and notes, is suggested as `ignore`;
    - the measure is chosen in the glossary's order (ADR 0011), and the first dimension becomes the breakdown.

A suggestion is never applied silently. The owner saves it, edits it, or leaves the dataset unmapped. `DELETE /api/datasets/{id}/mapping` returns the dataset to automatic detection.

### 4. Reading numbers and dates

A mapped measure is read more generously than an unmapped column, because the owner has said it is a number:

- currency symbols and codes are removed ($, €, £, ¥, ₹, ﷼, USD, EUR, GBP, SAR, AED, EGP, ر.س, د.إ, ج.م);
- thousands separators and spaces are removed;
- `(300)` is −300;
- Arabic-Indic digits and the Arabic decimal and thousands signs (٫ and ٬) are read;
- a trailing `%` is removed and the number kept as it is, so `12%` is 12. A sum of percentages means nothing, so a percentage column should be mapped as a measure only to be averaged or compared.

A mapped date reads:

- ISO dates, with or without a time;
- year and month;
- the year alone;
- quarters (`2025-Q1`, `Q1 2025`);
- day, month and year with `/`, `-` or `.` separators, in the order `date_order` sets;
- English and Arabic month names, in either order with the year.

Periods become sortable labels: `2025-03-14`, `2025-03`, `2025-Q1` and `2025`. A trend is ordered by time, not alphabetically. A value that cannot be read is left out of the trend and counted in the report, never placed in a guessed period. Forecast labels continue the same calendar, so the period after `2025-Q4` is `2026-Q1`.

### 5. A run takes a copy of the mapping

`POST /api/runs` with a `dataset_id` copies the dataset's mapping into the run (`runs.mapping_json`). Changing the mapping later does not change a run that has already happened, so its report stays reproducible. The stages use the copy:

- **Profiler and cleaner:** the measures are the numeric columns, read as in §4. A numeric ID mapped as `dimension` or `ignore` is no longer a number.
- **Governance:** the measure comes from the mapping, with the source "column mapping". A glossary definition of that column is still applied and checked. When a certified metric is mapped but not chosen, it is still named as present and not analysed.
- **Preparer:** the breakdown and the date come from the mapping, at the grain chosen. The summary says how many dates could not be read.
- **Diagnostic and experiment detection:** drivers are the other measures, and only dimension columns are considered as experiment arms. Ignored columns take no part.

Contract, quality and privacy still describe every column, ignored ones included. Ignoring a column takes it out of the analysis, not out of the data.

### 6. Unmapped data runs exactly as before

A dataset with no saved mapping, pasted CSV and the sample all run with the existing detection, so earlier reports reproduce. Tests check that a run of the sample is unchanged. The one change for every run is that forecast labels now continue `YYYY`, `YYYY-Qn` and `YYYY-MM-DD` as calendars, where they used to read "next period +1".

### 7. Storage

The `datasets` table gains `mapping_json` and `mapping_updated_at`, and the `runs` table gains `mapping_json`. Both are added by the same repeatable migration as earlier columns, in SQLite and PostgreSQL. `GET /api/datasets` reports whether each dataset is mapped.

### 8. The interface

In the Datasets view, each dataset has a *Columns* action, and a new upload opens it straight away. It shows:

- the first rows, in a table that scrolls inside its own frame;
- one row per column: its detected type and reason, and a role chosen from four;
- the choice of measure and breakdown, and the date options when a date is mapped;
- *Save mapping*, *Use automatic detection* and *Analyse*.

Errors follow the error-summary pattern: a summary at the top that links to each field, and the message beside the field. Every string is in English and Arabic.

## Verification

On 2026-10-16, with `python scripts/verify.py --e2e` against SQLite and PostgreSQL:

- **The reading rules and validation:** 50 tests in `tests/test_mapping.py`.
    - Numbers: currency, `(300)`, Arabic digits and separators, and the refused decimal comma.
    - Dates: every format above, with the ambiguity rule, the grains, and calendar labels.
    - Suggestions: the sample, identifiers, codes, free text, personal data, a second date, and the glossary's order.
    - Every validation error, reported together and in both languages.
- **The API and runs,** on both databases:
    - detail, save, refusal and clear;
    - a mapped run that orders a year-end by time and counts the date it could not read;
    - a run keeping its copy of the mapping;
    - a mapping that matches the old guesses giving the same figures;
    - unmapped, pasted and cleared data running as before;
    - quarterly forecasts.

  Another owner gets a 404, and a viewer can read but not map.
- **The interface:**
    - 60 frontend unit tests, including the panel's error summary, its links to each field, and the date options.
    - 72 end-to-end checks, of which 69 run and pass and 3 are skipped by design, including three new mapping checks on desktop and phone:
        - a suggested mapping is adjusted, saved and followed by a run;
        - a refused mapping is summarised, with focus moved to the summary and each link leading to its field;
        - the Arabic panel.
    - Axe reports nothing in English or Arabic, and nothing scrolls sideways at 320 px.
- **The whole suite:** 769 Python tests, 16 of them skipped for optional libraries. JavaScript is 96.7 of the 100 KB gzipped budget, so code-splitting views is due before phase 3.

## What is still absent

- Weeks as a grain, fiscal years, and two-digit years before 1970.
- Derived columns (a measure computed from two others) and units per measure.
- More than one dimension in a breakdown, and more than one measure analysed in a run. The other measures are drivers, not subjects.
- Applying a saved mapping to a re-upload of changed data. A new file is new content, so it is a new dataset.
- Deep links to a dataset's mapping (the rest of phase 2).
