# ADR 0008 — Per-tenant quotas and usage, without inventing costs

Date: 2026-08-13 · Status: Accepted

## Context

Authentication made the system multi-tenant (ADR 0002): runs, sessions
and datasets belong to an owner. Nothing bounded what one owner could
consume. A runaway client loop, an enthusiastic demo, or a script in a
retry loop could fill the database and spend a shared budget, and the
first anyone would know is a bill or an outage.

The Tier 2 item was written as "tenant quotas, usage budgets, and cost
tracking (FinOps foundation)". Two thirds of that is straightforward.
The third is a trap.

## Decision

**Three limits, each bounding a resource this system can actually
exhaust:** runs started per day (compute), datasets stored (rows), and
total dataset bytes (database size). Per owner, so one tenant cannot
spend another's allowance.

**Usage is counted from the durable rows, not a parallel tally.**
`count_runs_since` and `dataset_usage` are queries over `runs` and
`datasets`. A separate counter would be faster and would eventually be
wrong — after a restore, a manual delete, or a failed write — and a
quota that disagrees with reality is worse than no quota, because it
refuses work the tenant has not done.

**Enforced before the resource exists.** `check_run` runs before any row
is written, and `check_dataset` before the dataset row is inserted, so a
refusal leaves nothing behind. Tested explicitly: after a refused run the
run list is unchanged.

**Refusals are 429 with a message that says what to do.** The request is
well formed and the caller is entitled to make it — just not now, or not
this much. The message names the limit, the current usage, when it
resets, and what still works: *"Daily run limit reached (3/3). It resets
at 2026-08-14 00:00 UTC. Existing runs can still be advanced, approved,
and read."* A limit that strands work already in progress would be a
worse failure than the one it prevents, so it doesn't.

**Re-uploading a file you already have costs nothing.** Datasets are
content-addressed (ADR 0004), so a repeat upload consumes no new space
and is not charged against the byte allowance. The quota check sits
*after* the deduplication lookup, not before it.

**The limits are visible.** The Activity view shows each allowance as a
meter with the real numbers, turning amber past 90%. An enforced limit
the interface never mentions is a trap whose first appearance is a
refusal.

### Why there are no currency figures

"Cost tracking" invites a dollar column. There is no honest way to
produce one here: the deployment has no billing relationship, the default
model provider is deterministic and free, token usage is not counted, and
serverless execution time is not measured. A number in that column would
be fabricated, and a fabricated cost is worse than a blank one — it gets
put in a slide.

So usage is reported in the units the system genuinely measures, and the
response names what it does **not** measure — model tokens, function
execution time, currency — as a field rather than omitting them silently.
Converting usage into money needs the bill, and whoever holds the bill
can do the multiplication.

## Defaults

200 runs/day, 100 datasets, 50 MB per owner, overridable by
`AGENTIC_OS_QUOTA_RUNS_PER_DAY`, `AGENTIC_OS_QUOTA_DATASETS`,
`AGENTIC_OS_QUOTA_DATASET_BYTES`. These exist to stop a runaway loop, not
to ration ordinary use — a normal session does not approach them.

A malformed or negative value falls back to the default rather than
failing startup: a typo in a limit must not take the deployment down.
Zero is honoured as a deliberate stop, because it is a setting somebody
might mean.

## Consequences

- The daily window is calendar-based (midnight UTC), not a rolling
  window. Simpler to explain and to display, at the cost of allowing a
  burst either side of midnight. Acceptable for a runaway-loop guard.
- The bundled sample dataset counts against a tenant's storage. It is
  stored per owner like any other dataset; exempting it would mean a
  special case in the accounting for a few kilobytes.
- Quotas are per process only in the sense that limits are read from the
  environment at startup; the *usage* they compare against is in the
  database, so multiple instances enforce consistently. This is unlike
  the rate limiter (ADR 0003), which is genuinely per process.
- `RunEngine(limits=None)` disables enforcement, which is what the CLI
  and the non-quota test suites use.

## Evidence

- 240 Python tests (both dialects, suite run twice), 20 of them in
  `tests/test_quota.py`: each limit enforced, a refused run leaving no
  rows, existing runs still advancing and approving at the limit,
  re-upload not charged, usage per tenant, and the boundary conditions on
  configuration (typo, zero, missing).
- The enforcement tests were checked against a build with the run check
  removed: three of them fail, so they are testing the server rather than
  restating the client.
- 23 frontend unit tests, 36 e2e checks; the usage meter verified in a
  real browser against real numbers.
