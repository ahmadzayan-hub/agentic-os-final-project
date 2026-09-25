# ADR 0006 — Durable execution: database leases, not a workflow engine

Date: 2026-08-12 · Status: Accepted

## Context

Runs were client-stepped: each `POST /api/runs/{id}/advance` executed one
bounded task. That gave honest pause, cancel, and resume semantics with
no infrastructure, and it is still the right default for local use. It
has one plain limitation — **close the tab and the work stops**. A run
left at task 6 stays at task 6 until somebody opens the Runs view again.

The roadmap named two candidates: evaluate Vercel Workflows for Python
against the run-engine contract, or database-backed jobs with leases and
heartbeats.

## Decision

**Database-backed leases.** A worker claims a run by conditionally
setting `lease_owner` and `lease_expires_at` on the run row, advances it
one task at a time, renews the expiry after each task, and releases the
lease when the run stops being runnable.

The claim is a single conditional `UPDATE` whose `WHERE` repeats the
guard used to find the candidate. Two workers that select the same
candidate cannot both win: the loser changes zero rows and moves to the
next one. The candidate `SELECT` is a read, not a claim, and is not
relied on for correctness.

Crash recovery needs no cleanup path. A worker that dies stops renewing;
the expiry passes; the next worker claims the run from its durable state.
There is no lock to release, no heartbeat table to reconcile, and no
"is that worker really dead?" question — the expiry answers it.

**Clients and workers never execute the same task.** `advance()` treats a
live lease held by someone else as a no-op that returns current state, so
an open browser degrades into a poller while a worker owns the run. When
the lease expires, clients resume stepping it themselves — the system
works with a worker, without one, and while one is dying.

### Why not Vercel Workflows for Python

Evaluated against the contract this engine already meets — durable state
after every transition, pause, cancel, resume from an arbitrary point,
and a human approval gate that binds to an artifact hash. Adopting it
would mean a second execution model with a second failure mode, hosting
lock-in for the part of the system that is most valuable to keep
portable, and no test that could run in CI here. The lease is roughly
sixty lines against an interface that already existed, runs identically
on SQLite and PostgreSQL, and is exercised on every push. If a hosted
workflow engine is adopted later, `RunWorker` is the seam to replace.

### Pause had to become server-side

Pause was a client-side toggle: the browser stopped calling `advance`.
With a worker, that button would have kept its label and lost its
meaning. Pause is now a durable `paused` flag on the run that the worker
honours (paused runs are not claimable) and that `advance` refuses with
409. The button now means the same thing whoever is executing the run,
and the state survives a restart.

## What the worker does not do

It never decides an approval. It advances a run to the gate and stops
there, exactly like a client-stepped run, and waits for a human. An
autonomous publisher would defeat the point of the gate, so the property
is a test, not a convention.

## Evidence

- `python scripts/worker.py [--once]` against a live server on this
  machine: a run created over HTTP with no browser open reached
  `awaiting_approval` with all ten specialists succeeded, a report
  produced, and its approval still `pending`.
- 189 Python tests (both dialects, suite run twice), including 33 in
  `tests/test_worker.py`: crash recovery via expired lease, a client
  refusing to advance a leased run, a client resuming when the lease goes
  stale, lease release, and a **six-thread race on six PostgreSQL
  connections** asserting no run is ever claimed twice. That race test
  was checked against a deliberately weakened claim (guard removed from
  the `UPDATE`), which produces 36–45 claims for 12 runs — the sequential
  tests pass in that state, so the concurrent one is what holds the
  invariant.
- 23 frontend unit tests, 36 e2e checks.

### A bug the live run found

Running the worker for real against the API surfaced a defect the unit
tests had not: pausing a run **while a worker was mid-pipeline** raised
out of `advance` and killed the worker process. Two fixes, both now with
regression tests: a run that stops being ours to advance ends the
worker's turn rather than its process, and `run_forever` reports a failed
run on stderr and continues instead of exiting. The first test was
verified to fail with the fix removed.

## Consequences

- The worker is **opt-in**: nothing starts it automatically. Without it
  the system behaves exactly as before. On Vercel's serverless runtime
  there is no process to run it in, so hosted deployments there keep the
  client-stepped path; a persistent host can run
  `python scripts/worker.py`.
- The rate limiter is per process, so a worker's writes are not counted
  against a browser's budget. That is correct here and worth revisiting
  when the limiter becomes shared.
- One worker advances one run at a time. Parallelism is more workers, not
  threads — the lease already makes that safe.
