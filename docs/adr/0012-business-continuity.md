# ADR 0012 — Failure injection, and what it found

**Status:** Accepted
**Date:** 2026-09-10

## Context

The project has claimed since ADR 0006 that a run survives interruption:
state is durable, a worker that dies stops renewing its lease, and the
next worker picks the run up. That claim was tested with a frozen clock,
an in-process worker, and a fake — which proves the *logic* is right and
says nothing about whether the *system* behaves that way.

Every serious continuity claim in this repository rested on reasoning
rather than on an executed drill. Backup and restore was the exception
(ADR 0005 destroys the database and rebuilds it on every push); crash
recovery was not.

So: break it on purpose and see.

## What was drilled

Four failures, chosen because each is ordinary rather than exotic:

1. **The connection object is dead** — this process closed it, or the
   driver marked it closed after a fatal error.
2. **The server hangs up** — `pg_terminate_backend`, which is what a
   connection pooler, a failover, or a restart looks like from the
   client. Supabase's pooler drops idle connections as a matter of
   routine, so a worker that has been polling meets this regularly.
3. **A worker killed with SIGKILL mid-run**, leaving a lease nobody will
   ever renew.
4. **The database stopped hard** (`pg_ctl stop -m immediate`) in the
   middle of a run, then restarted.

The first three are automated in `tests/test_recovery.py` and run in CI
against PostgreSQL. The fourth cannot be: CI's database is a service
container the test process does not control. It was executed by hand and
its measurements are below, labelled as such.

## What it found

**Two defects, both in the path the drills were aimed at.**

**1. The lease statements never reconnected.** `PostgresStore._exec`
reconnects on a dropped connection — that was the serverless hardening.
But `_exec_rowcount` is a different method, and it had no such
protection. Every lease statement goes through it: `claim_run`,
`renew_lease`. So a worker whose connection had been dropped while idle —
the normal state of a worker — would raise on the statement it woke up to
run, while the identical failure on a read recovered silently.

**2. The reconnect caught only half the failures.** It caught
`OperationalError` (the server hung up) but not `InterfaceError` (the
connection object is closed). Both are routine; only one was handled.

Fixed by hoisting the retry into one `_retrying` helper that both
statement methods use and that catches both exceptions.

**3. A crash *during* a stage silently broke the run.** This is the
serious one. A worker killed between tasks leaves nothing behind and
recovery worked exactly as claimed. A worker killed *during* a task
leaves that task marked `running` forever — and the engine walked
straight past it to the next pending task. The run then continued
**without a stage its successors depend on**, and failed several stages
later with an error naming the wrong thing entirely.

In other words, the one failure durability was supposed to rule out — a
crash producing a quietly broken run — was exactly what a crash produced,
about half the time, depending on whether the kill landed inside a stage.
The SIGKILL drill was intermittently red before this was understood,
which is what a flaky drill usually means: not a flaky test, a flaky
system.

Fixed in `RunEngine._reclaim_orphaned_tasks`: reaching the point where a
task is chosen means nobody holds a live lease, so a task marked
`running` is not being executed by anyone — it is debris. It is reset to
pending, along with any half-written summary or result, and run again.
Re-running is safe because a stage is a pure function of the results
before it and a task's result is written once, at the end.

## Measurements

From the hand-executed database-outage drill on the development machine
(PostgreSQL 16, local socket, the bundled 72-row sample dataset):

| | |
| --- | --- |
| Stages completed before the outage | 6 of 21 |
| Behaviour during the outage | `advance` refuses with `OperationalError` after one failed reconnection — no partial write, no corrupt state |
| Database restart to accepting connections | 0.54 s |
| Run resumed to the approval gate after restart | 0.09 s |
| Work lost to the outage | none — the 6 completed stages were kept, 15 recomputed |
| Recovery in the *same* process (no restart) | same result: the store reconnects, the run finishes |

That last row matters more than it looks. A drill that only proves a
*fresh* process can resume proves the database is durable, not that the
server survives. The running process recovers too.

Worker-death recovery is bounded by the lease, not measured: a successor
cannot claim until the dead worker's lease expires, which is
`--lease` seconds (default 30). That is a deliberate floor, not latency
to optimise — shortening it trades recovery time against the risk of two
workers executing the same task when one is merely slow.

## Service levels

Stated as what the drills support, not as aspiration:

- **Durability of accepted work:** a stage that reports success is
  durable at that moment. No completed stage was lost in any drill.
- **Recovery from a database outage:** bounded by database restart time;
  no operator action, no run restart, no lost stages.
- **Recovery from a worker crash:** bounded by the lease duration
  (default 30 s). The interrupted stage is re-run, not skipped.
- **Recovery point objective for the database as a whole:** whenever
  `scripts/backup.py` last ran — see ADR 0005. Nothing schedules it.

There is no error budget here, and inventing one would be theatre: an
error budget needs production traffic and a measurement pipeline, and
this system has neither. What it has instead is a set of drills that run
on every push, and the number that matters — how much work an outage
costs — measured rather than assumed.

## What is not covered

- **The hand-run outage drill is not in CI.** CI's PostgreSQL is a
  service container the test process cannot stop. The automated tests
  cover connection loss, which is the same code path; the full outage was
  executed once, here, and is reported above with its numbers.
- **Two workers on one run** is prevented by the conditional-update lease
  (ADR 0006) and tested under real thread contention, but not under a
  network partition, which this environment cannot produce.
- **Corruption**, as opposed to unavailability, is out of scope: a
  database that returns wrong answers rather than no answers would defeat
  every check here.
- **No failover**: one database, one instance. Point-in-time recovery and
  a standby remain on the Tier 3 list.

## A note on the retry

Repeating a statement after a lost connection is safe under autocommit
because each statement stands alone. The exception is a conditional
UPDATE whose acknowledgement was lost: the repeat then fails its own
guard, because the first attempt already succeeded and the row no longer
matches. For the lease claim that would mean a worker discarding a run it
had actually won, which would sit untouched until the lease expired.

`claim_run` therefore checks directly: after a zero-row result it asks
whether it holds the lease with the exact expiry it tried to write.
Losing a race and winning one invisibly are different things, and only
the first should end quietly.
