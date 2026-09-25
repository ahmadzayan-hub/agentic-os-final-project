# ADR 0004 — Content-addressed dataset storage and file upload

Date: 2026-08-10 · Status: Accepted

## Context

Datasets were inlined into each run row as text, capped at 250 KB and
5,000 rows, and could only be pasted into a textarea. Three problems:
running the same data twice stored it twice, the run table grew with
every analysis, and "business analytics" that cannot open a file is a
thin claim.

## Decision

A `datasets` table stores content **addressed by SHA-256 per owner**.
Uploading the same file twice stores one row; runs reference a
`dataset_id` instead of carrying a copy. Limits rise to **2 MB and
50,000 rows**, which is now safe because the data is stored once.

`GET /api/datasets` lists an owner's datasets, and a run can be started
from an existing `dataset_id` — re-analysing yesterday's upload costs a
single identifier rather than a re-upload.

The UI gains a real file picker. The file is read in the browser, its
row count is shown before sending, and oversize files are rejected
client-side with the actual size in the message. Pasting still works;
the file name becomes the dataset name so reports identify their source.

### Why not Supabase Storage / S3

Object storage is the textbook answer for large files, but it would add
a network hop, a credential, and a code path this environment cannot
exercise (outbound HTTPS to the provider is blocked here), in exchange
for benefits that begin well above a 2 MB CSV. Postgres handles content
of this size comfortably. If datasets grow past tens of megabytes, the
`store_dataset`/`get_dataset` pair is the single seam to swap — that is
a deliberately narrow interface, not an accident.

## Compatibility

`runs.dataset_id` is added by the same additive, repeatable migration
pattern as `owner`. Runs written before this change still carry their
text in `dataset_text`, and `_dataset_text()` falls back to it, so old
runs keep working and re-run identically.

## Evidence

- 141 Python tests (both dialects, suite run twice for hermeticity),
  including: identical uploads stored once while producing distinct
  runs, a run reusing a stored `dataset_id` and reporting the correct
  computed total, and an unknown `dataset_id` rejected with 404.
- 35 e2e checks including a full upload journey: a CSV file is picked,
  its row count confirmed in the browser, and the resulting report
  contains figures computed from the uploaded file (not the bundled
  sample) with the file name recorded as the source.

Fixing this also exposed a stale test-teardown list: the PostgreSQL
suite dropped every table except the new one, so dataset rows leaked
between tests. The list is now commented as needing every table.
