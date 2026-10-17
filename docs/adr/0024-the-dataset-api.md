# ADR 0024 — The dataset API: several formats, one canonical table

**Status:** Accepted
**Date:** 2026-10-16
**Milestone:** A1 in `project-progress.md`; unlocks phase 2 of `docs/UI_PLAN.md`
**Keeps:** content-addressed datasets, per-owner quotas (ADR 0008), tenancy, raw data never sent to a model, the CLI's standard-library promise

## Context

A dataset could reach the pipeline one way: CSV text inside `POST /api/runs`, read in the browser, at most 2 MB. Three things were wrong with that.

- **Business data is not only CSV.** It arrives as Excel workbooks and as JSON exported from other systems. Asking people to convert first loses them at the first step.
- **The limit was too small for real work.** The capstone's maintenance file (5,000 records, 60 variables) is 2.1 MB, just over it.
- **A dataset had no life of its own.** It existed only as the side effect of starting a run, so nothing could be uploaded, checked or chosen before an analysis began.

Measured before deciding, on this machine with synthetic data, one stage per request as the engine runs them:

| Rows × columns | CSV size | Whole pipeline | Slowest stage |
| --- | --- | --- | --- |
| 5,000 × 60 | 1.6 MB | 9 s | 1.0 s |
| 20,000 × 20 | 2.1 MB | 13 s | 1.2 s |
| 50,000 × 10 | 2.6 MB | 16 s | 1.5 s |
| 50,000 × 20 | 5.3 MB | 33 s | 2.9 s |

The production deployment runs on Vercel, whose functions refuse a request body over 4.5 MB and stop after the 30 seconds `vercel.json` allows.

## Decision

### 1. `POST /api/datasets` takes the file as the request body

The browser sends the file itself (`fetch(url, { body: file })`), and the query string carries `name` (the file name), optionally `format` and `sheet`, and `language` for the error text. One file per request.

Multipart was the milestone's first idea. It needs `python-multipart`, a new dependency, to carry one file plus fields that fit in a query string. A raw body needs nothing, streams, and is what `fetch` sends anyway.

The response holds the stored dataset and what was read from it: `columns`, the first five rows as `preview`, `warnings`, and the workbook's `sheets`. It is `201` when the data is new and `200` when identical data was already stored, which costs nothing and says so with `created: false`. Errors are `413` for size, `415` for a format it does not read, `422` for a file it cannot read, and `429` for quota. Each message is written in the reader's language.

### 2. Four formats, read with the standard library, written as one canonical CSV

| Format | Recognised by | Read as |
| --- | --- | --- |
| CSV and TSV | `.csv`, `.tsv`, `.txt`, or anything that is not one of the others | UTF-8 (with or without a BOM) or UTF-16 with a BOM. The delimiter is detected among comma, semicolon, tab and pipe, because Excel in many locales saves semicolons. Any other encoding is refused with "save it as CSV UTF-8", rather than guessed: guessing between Windows-1252 and Windows-1256 turns Arabic into nonsense without an error |
| Excel workbook | `.xlsx`, or a ZIP signature | `zipfile` and `xml.etree`, streamed with `iterparse`. First sheet unless `sheet` names another. Shared and inline strings, numbers, booleans, cached formula results, and dates, recognised from the cell's number format and converted from Excel serial numbers (1900 and 1904 systems) to ISO dates. Error cells (`#N/A`, `#DIV/0!`) and formulas with no cached value become empty cells, and a warning says how many |
| JSON | `.json`, or a first character of `[` or `{` | An array of objects; an array of arrays whose first row is the header; an object holding one such array (for example `{"data": [...]}`); or `{"columns": [...], "data": [[...]]}`. Nested objects are flattened to dotted column names, and lists are kept as JSON text |
| JSON Lines | `.jsonl`, `.ndjson` | One object per line; an error names the line |

Old binary `.xls` files are refused with a request to save as `.xlsx` or CSV.

Every format becomes the same thing: a header and rows, written out as comma-separated UTF-8 CSV. The first non-blank row is the header, and blank rows are dropped. Header names are trimmed, an empty one becomes `column_N`, and a repeated one gets `_2`, `_3` and so on. A row with more values than the header keeps them in new columns, with a warning. The pipeline did not change, because it still reads CSV.

The canonical text is what is hashed, so the same table uploaded as `.xlsx` and as `.csv` is stored once.

**No new dependency.** `openpyxl` and `pandas` were the obvious choices. Installed here they measure 2.1 MB (with `et_xmlfile`) and 114 MB (with `numpy`), to read a format whose data part is a ZIP of XML, and the core is standard-library only by promise. When `openpyxl` happens to be installed, one test writes workbooks with it and reads them back with this parser; CI does not install it, and that test skips there.

### 3. Limits sized by measurement

| Limit | Value | Why |
| --- | --- | --- |
| File as uploaded | 4 MB | Under Vercel's 4.5 MB request limit. Twice the old limit, and covers the capstone file |
| Canonical CSV | 10 MB | A 4 MB workbook can expand. At 50,000 rows and 20 columns the slowest stage took 2.9 s, well inside 30 s |
| Rows | 50,000 | Unchanged |
| Columns | 500 | A sheet that touches column `XFD` would otherwise allocate 16,384 columns for every row |
| Workbook XML read | 200 MB | A decompression bomb stops at the cap. Declared sizes in a ZIP can lie, so bytes are counted as they are read |

The size is checked from `Content-Length` before anything is read, and again while the body streams in.

### 4. XML is treated as hostile

A workbook part containing a `DOCTYPE` is refused before it is parsed, so entity expansion has nothing to expand. The installed expat (2.6.1) also limits amplification. Only the parts the workbook's own relationships name are opened, and a path that leaves the archive is refused.

### 5. Datasets record what they are

`datasets` gains `source_format`, `row_count` and `column_count`, added by the same repeatable `ALTER TABLE` migration as earlier columns, in SQLite and PostgreSQL. `GET /api/datasets` returns them. Rows stored before this change have the counts filled in from their CSV the next time they are stored again; until then the interface shows a dash.

### 6. The interface uploads through the API

- **Runs view:** the dataset switch becomes *Sample*, *Stored* and *Upload*. *Stored* is a picker of the owner's datasets. *Upload* sends a file to `POST /api/datasets`, shows what the server found, and starts the run by `dataset_id`; pasting CSV still works as before. A preset from the Datasets view selects *Stored*. On a phone the three choices stack.
- **Datasets view:** *Add a dataset* uploads the file there and then, and the list shows each dataset's format and row count. The list refreshes in place, without flashing back to a loading state.

## Verification

On 2026-10-16:

- **The reader:** 53 tests in `tests/test_datasets.py`.
    - Delimiters, encodings, headers, blank and long rows, and every limit.
    - Each JSON shape, and JSON Lines named either way.
    - Workbooks built part by part by `tests/xlsx_builder.py`: shared, inline and rich strings, phonetic runs, booleans, errors, formulas with and without a saved result, the 1900 and 1904 date systems including the days around Excel's 29 February 1900, built-in and custom date formats, hidden and named sheets, strict OOXML namespaces, a `DOCTYPE` entity bomb, a decompression bomb, a relationship pointing outside the archive, and a cell at column `XFD`.
    - The same table in five forms produces byte-identical canonical CSV.
    - When `openpyxl` is installed, a workbook it writes reads back correctly. It was installed here, so that test ran.
- **The API:** the same tests run against SQLite and PostgreSQL.
    - Each format stored with its shape; repeat uploads across formats stored once.
    - The size cap from the header and while streaming.
    - Errors in Arabic.
    - A run from an uploaded workbook reaches the approval gate.
    - Quotas never charge a repeat.
    - Another owner can neither list nor use a dataset.
    - A viewer cannot upload.
    - A database from before this change migrates, and its rows learn their shape.
- **The interface:** 54 frontend unit tests, and 66 end-to-end checks, of which 63 run and pass and 3 are skipped by design. In the browser: a semicolon CSV, a two-sheet workbook and a nested JSON file are added in the Datasets view and listed with format and rows; a repeat upload is recognised; an old `.xls` is explained and not stored; a workbook uploaded in the Runs view is analysed to the approval gate; axe reports nothing; and no view scrolls sideways at 320 px.
- **The whole suite:** see `README.md` for the Python count at this commit.

## Consequences

- A dataset now exists before any run, which is what column mapping (A2) and dashboards (A4, A5) need.
- The browser no longer reads a file's contents; it sends the file. The 2 MB check in the browser goes, and the server decides.
- Larger datasets make every stage slower in proportion: the 33 s whole pipeline above is twelve times the sample's.
- The 4 MB limit is the platform's, not the code's. A self-hosted server could accept more by raising one constant; Vercel cannot.

## What is still absent

- Parquet, `.xls`, OpenDocument and database connectors (A7 is where connectors belong).
- Choosing a sheet in the interface. The API takes `sheet` and returns the sheet names; the picker comes with phase 2.
- Previewing and mapping columns before analysis (A2 and phase 2).
- Deleting a dataset from the interface.
