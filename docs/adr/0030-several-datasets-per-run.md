# ADR 0030 — Several datasets per run: declared joins, merged after cleaning

**Status:** Accepted
**Date:** 2026-10-17
**Milestone:** A3 in `project-progress.md`; phase 4 of `docs/UI_PLAN.md`
**Keeps:** content-addressed datasets (ADR 0024), the column mapping (ADR 0025), per-record reading of uneven groups (ADR 0026), tenancy, raw data never sent to a model, the standard-library core

## Context

A run analyses exactly one dataset. Real questions rarely live in one file:

- sales by product, with the product's category in a second table;
- maintenance records, with each asset class's budget in a lookup;
- monthly revenue, with the monthly target in a planning sheet.

Storage already keeps many datasets per owner (ADR 0024), and each can carry a mapping (ADR 0025). What was missing is a way to say how two of them fit together, and a stage that puts them together without changing the numbers the run is about.

A join is the easiest way to get a total wrong without noticing:

| What goes wrong | Effect on the report |
| --- | --- |
| The lookup has the same key twice | Every matching record is counted twice, so totals grow |
| Keys are spelled differently (`North` and `north `, `3` and `3.0`) | Rows find no match, and the joined columns are empty for them |
| Only matching rows are kept | Totals shrink to the rows that matched, silently |
| A joined column has the same name as an existing one | One silently overwrites the other |

## Decision

### 1. A run declares its joins when it is created

```json
{
  "goal": "Sales by category",
  "dataset_id": "sales-id",
  "joins": [
    {"dataset_id": "products-id", "alias": "products", "how": "left",
     "keys": [{"left": "product_code", "right": "code"}]}
  ],
  "breakdown": "category"
}
```

| Field | Rule |
| --- | --- |
| `dataset_id` | The main dataset: its rows are the rows the run is about |
| `joins` | Up to four other stored datasets of the same owner, applied in order |
| `keys` | One to three column pairs: a column of the table so far, and a column of the joined dataset |
| `how` | `left` (default) keeps every row; `inner` keeps only rows that found a match |
| `alias` | Names the joined dataset's columns when a name is already taken: `products.name`. Default: the file name, as a slug |
| `breakdown` | Optional: any text column of the merged table, used instead of the mapping's dimension |

Keys are compared as trimmed text. When a key column was read as a number on the main side, both sides are compared as numbers, so `3`, `3.0` and `003` match. When a key is the main dataset's mapped date, the joined values are read as dates at the same grain and order, so a daily table joins a monthly target table by month.

The run keeps its own copy of the join declaration and of each joined dataset's mapping, as it already does for the main mapping: changing either later never changes a run already made.

### 2. The merge is a stage after cleaning

A new stage, the **Data Merge Agent** (`merge`), runs right after the Data Cleaning Agent, and only in runs that declare joins. A run without joins has exactly the stages and figures it had before.

For each joined dataset it:

1. cleans the joined table the way the main one is cleaned: trimmed cells, empty and exact-duplicate rows removed, measures read as numbers by its own mapping or, without one, by the same 90% rule;
2. **refuses a lookup whose key is not unique**. One-to-many joins multiply the main rows, and a refusal is the only honest outcome. The message names how many keys repeat and the first few;
3. joins, keeping every main row (`left`) or only the matched ones (`inner`);
4. records, for each join: rows in, rows out, rows matched, rows unmatched with the first unmatched keys, lookup rows that matched nothing, columns added and columns renamed.

Every later stage reads the merged table. The stages before cleaning (contract, profiling, quality, privacy) still describe the main dataset as it arrived.

### 3. Join correctness is checked, not assumed

- **Row count:** a left join returns exactly the rows it was given; an inner join returns exactly the matched rows. The stage checks this, and the Validation Expert recounts it independently (`joins_keep_the_row_count`). A broken count rejects the run.
- **Key coverage:** each join reports the share of rows that found a match, as a claim with its calculation. Coverage below 100% is a failed quality check on the stage and a limitation in the report, so a reader sees how many rows have empty joined values.
- **Inner joins:** the report states how many rows were left out, and that totals cover matched rows only.
- **Personal data:** each joined dataset is screened with the Privacy Agent's own patterns, and a finding becomes a warning that reaches the approver.
- **Provenance:** the merge stage names every joined snapshot by its hash, and the Provenance Agent roots the report in all of them.

### 4. A preview before the run

`POST /api/joins/preview` takes the same declaration and answers with the merged columns, the first five rows, and every join's counts, without creating a run. It runs the real collection, profiling, cleaning and merge stages, so the preview and the run cannot disagree. A refused join is a 422 with every problem by field, in the reader's language, the shape a refused mapping already has (ADR 0025). `POST /api/runs` makes the same checks and refuses a run that would fail at its merge stage.

### 5. Limits

| Limit | Value | Why |
| --- | --- | --- |
| Joined datasets per run | 4 | Enough for a fact table and its lookups; the merge cost stays below the cleaning cost |
| Key pairs per join | 3 | Composite keys beyond three columns are almost always a modelling problem |
| Columns after merging | 500 | The same ceiling a single dataset has (ADR 0024) |
| Rows | The main dataset's | A refused duplicate key means a join can never add rows |

## Consequences

- A run can now be about a fact table and its lookups, and group by an attribute that lives only in a lookup.
- The figures a joined run reports are the main dataset's figures: a left join cannot change a total, and an inner join says what it removed.
- Many-to-many and one-to-many joins are refused, not supported. Aggregating a lookup first, or choosing the finer table as the main one, is the owner's decision.
- Runs, task results and backups gain one column (`runs.joins_json`), added by the same repeatable migration as before.
- The interface gains a join builder in the new-analysis form: pick a dataset, pick the key columns, choose whether to keep unmatched rows, and preview the merge.

## Not done here

- Unions (stacking datasets with the same columns) and joins across owners.
- Fuzzy or case-insensitive key matching. Coverage tells the owner when spelling differs; normalising keys is a cleaning decision they make in the file.
- Joining a lookup on its own date grain other than the main dataset's.
