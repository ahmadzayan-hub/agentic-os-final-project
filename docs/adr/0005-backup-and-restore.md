# ADR 0005 — Backups, restore drills, and measured RPO/RTO

Date: 2026-08-12 · Status: Accepted

## Context

Sessions, transcripts, memory, runs, approvals, artifacts, published
vault notes, and datasets are all durable in one database (ADR 0001,
0004). That made a single failure — a dropped table, a deleted volume, a
wrong `DELETE` — able to destroy everything a user has done. A managed
provider's own backups are real where the plan includes them, but a
backup nobody has ever restored is a hope, not a control.

## Decision

**One dialect-neutral backup format.** `server/backup.py` exports every
row of every table in `storage.TABLES` into a single JSON document
(`version`, `taken_at`, `tables`). It contains no SQL and no driver
types, so a SQLite backup restores into PostgreSQL and back.

**Restore replaces; it never merges.** Recovering means the database ends
up exactly as the backup describes, with no survivors from the damaged
state. Rows are deleted child-first and inserted parent-first, so foreign
keys hold at every point.

**The table list has one owner.** `storage.TABLES` is the single source
of truth; backup, restore, and the PostgreSQL test teardown all derive
from it. A hand-maintained copy of that list went stale once and leaked
dataset rows between tests (ADR 0004) — this removes the class of bug
rather than the instance.

**Refuse rather than half-restore.** An unreadable document, an unknown
schema version, or an unknown table aborts *before* any delete runs. A
partial restore is worse than a failed one because it looks like it
worked.

**Two operator scripts.** `scripts/backup.py` writes a backup and prints
a JSON summary (path, bytes, seconds, rows per table).
`scripts/restore.py` restores one, requires an explicit `--yes`, and
offers `--dry-run` to inspect a file first. Both honour `DATABASE_URL`
and `--config`, so the same commands work locally and against hosted
PostgreSQL. `backups/` is git-ignored: a backup contains user data.

### Why JSON rather than `pg_dump`

`pg_dump` is the better tool for a PostgreSQL-only estate and remains
available — the Supabase project supports it, and nothing here replaces a
provider's point-in-time recovery where the plan offers it. It cannot,
however, restore
into SQLite, cannot run in an environment without the client binaries,
and cannot be exercised by the test suite on every push. The JSON format
is what makes the drill below run in CI against both dialects. For the
data volumes in scope (ADR 0004: 2 MB per dataset) the cost of holding a
backup in memory is acceptable; past a few hundred megabytes this format
should be replaced by streaming or `pg_dump`, and that limit is recorded
in docs/KNOWN_LIMITATIONS.md rather than discovered during an incident.

## The drill

`tests/test_backup.py` does not check that a backup file looks right. It
**destroys the database and rebuilds it**, then asserts the work
survived: the run, its eleven tasks, the report content, the validator's
quality checks, the approval decision, both published vault notes, the
session, the stored dataset. Specifically:

- a destroyed database is rebuilt through the operator scripts, run as
  real subprocesses — the drill exercises what a human would type;
- a restored run **continues**: it advances to approval and completes,
  because a recovery that restores rows but not the ability to work is
  not a recovery;
- a restored approval stays spent — recovery does not hand back a second
  chance to publish an already-published report (409 on replay);
- restore replaces rather than merges;
- an unreadable, future-versioned, or unknown-table backup is refused
  with the database untouched;
- a SQLite backup restores into PostgreSQL and the run completes there —
  which is also the supported way to move a local install to hosted mode.

The whole file runs twice in CI, against SQLite and against PostgreSQL 16
(`REQUIRE_PG=1`), so restore is proven on every push rather than
annually. Suite after this change: **156 Python tests** (both dialects,
run twice for hermeticity), 23 frontend unit tests, 36 end-to-end checks.

## Measured RPO and RTO

Drill executed 2026-08-12 in this environment: 25 completed analytics
runs, 600-row datasets, 426–427 rows, 2.65 MB backup file.

| Dialect | Backup | Restore | Verify (fresh app reads it back) |
| --- | --- | --- | --- |
| SQLite | 0.06 s | 0.15 s | 0.04 s |
| PostgreSQL 16 | 0.04 s | 0.18 s | 0.04 s |

**RTO** — restore plus verification is under a second at this volume, so
recovery time is dominated by human detection and decision, not by the
tooling. The honest target is **under 30 minutes**, and the mechanical
part of that is measured above, not estimated.

**RPO** — the loss window is exactly the interval between backups, and
**no scheduler is shipped**: nothing runs `scripts/backup.py` on a timer.
Until an operator schedules it, the effective RPO is "whenever someone
last ran the command". Stated plainly because the alternative is a table
of RPO numbers nobody is producing.

For hosted deployments the provider is *not* a substitute here. Supabase
backs up Pro, Team, and Enterprise projects daily, and offers
point-in-time recovery as a paid add-on with a worst-case RPO of about
two minutes; **free-plan projects get no dashboard-accessible automated
backups**, and Supabase's own guidance is that free projects should
export regularly and keep off-site copies
(https://supabase.com/docs/guides/platform/backups). This project's
Supabase instance is on the free plan, so `scripts/backup.py` is not a
convenience on top of provider backups — it is the only backup that
exists, and its RPO is whatever schedule the operator gives it.

### Why the schedule is not a GitHub Actions workflow

The obvious move — a nightly workflow that runs the script and uploads
the result — is wrong for **this** repository: it is public, and workflow
artifacts of a public repository can be downloaded by anyone. A nightly
job would publish every row of the database, including memory,
transcripts, and uploaded datasets. A private repository with the
destination credentials in secrets could do it; here the schedule belongs
somewhere the output stays private, for example a daily cron on a machine
the owner controls:

```
0 2 * * *  cd /srv/agentic-os && DATABASE_URL=... \
           python scripts/backup.py --out /secure/backups/agentic-$(date -u +\%FT\%TZ).json
```

Backups are written to a git-ignored `backups/` directory by default so
an accidental `git add -A` cannot commit one.

## Consequences

- Local mode keeps agent memory in `data/memory.json` (the original file
  contract), so a *database* backup does not contain it. Hosted mode
  keeps memory in the database and does. A test asserts the correct
  behaviour for each mode, and local operators must back up that file
  alongside the database.
- The vault directory on disk is a convenience copy; published notes live
  in the database and are restored from it (ADR 0001 amendment).
- Backups are unencrypted JSON containing user data. Storing them is the
  operator's responsibility; encryption at rest for backup files is not
  implemented here.
