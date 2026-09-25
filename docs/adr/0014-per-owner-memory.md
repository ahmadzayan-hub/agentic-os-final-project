# ADR 0014 — Memory belongs to an owner

**Status:** Accepted
**Date:** 2026-09-12
**Severity:** this fixes a confidentiality and data-loss defect in hosted
mode. Anyone running a multi-tenant deployment from a commit before this
one should treat the memory table as shared between all users.

## What was wrong

Sessions and runs have carried an `owner` since ADR 0002, and every
endpoint checks it. Agent memory never did. `memory_kv` had no owner
column, and the two operations on it were:

```python
def memory_load(self):
    return {... for row in self._exec("SELECT * FROM memory_kv")}

def memory_save(self, payload):
    self._exec("DELETE FROM memory_kv")     # everybody's
    for key, entry in payload.items(): ...  # then the caller's
```

One `DbMemoryBackend` was built per process and handed to every session
regardless of who owned it. In hosted mode that produces two failures at
once, and the second is worse than the first:

1. **Every tenant reads every other tenant's memory.** A new user's very
   first session opens with somebody else's saved facts in it.
2. **Every save destroys everybody else's memory.** `memory_save` rewrites
   the whole table, so the second user to save anything deletes the
   first user's memory — silently, with no error and nothing in a log.

Reproduced against the real API on hosted PostgreSQL before the fix:

```
Alice saves  → memory_kv: [memory_1 "Alice salary 250000 AED"]
Bob's new session sees:   ["Alice salary 250000 AED"]
Bob saves    → memory_kv: [memory_1 "Alice salary...", memory_2 "Bob likes cricket"]
```

The same held with an identity provider and SQLite, where every tenant
shared one `memory.json` file.

This was not a subtle race. It was the plainest reading of the code, and
it survived because every test that touched memory used one user — the
shape of the tests matched the shape of the assumption.

## Decision

**Memory is per owner, in the same sense sessions and runs are.**

- `memory_kv` gains an `owner` column, and its primary key moves from
  `(key)` to `(owner, key)`. The composite key is not decoration: keys
  are handed out per owner, so the first thing two tenants save is
  `memory_1` for both, and a single-column key makes the second collide.
- `memory_load(owner)` and `memory_save(payload, owner)` are scoped. The
  `DELETE` is scoped for the same reason the `SELECT` is.
- `DbMemoryBackend(store, owner)` is bound to an owner and built per
  session rather than per process.

**Where memory lives** is now decided by two independent conditions,
either of which is sufficient:

- the store is PostgreSQL — the backend must not depend on local files,
  because a serverless filesystem is read-only (ADR 0001's amendment);
- an identity provider is configured — more than one owner exists.

The second is the new one, and it matters on its own: a small deployment
with JWTs and SQLite is exactly as multi-tenant as one with PostgreSQL,
and previously shared one memory file between everybody. With a single
owner the scoping is a no-op; with several it is the whole point.

Local mode is unchanged: one person, one machine, the documented
`data/memory.json` contract, and a test that fails if that stops being
true.

## The migration

This is the first migration in the project that could not be an
`ADD COLUMN`, because the primary key had to move. The table is renamed,
recreated, copied and dropped — the one shape both SQLite and PostgreSQL
accept — guarded by a `SELECT owner FROM memory_kv` probe so it runs
exactly once, and wrapped so that a failure leaves the old table in place
rather than deleting anything on the way out.

Existing rows are attributed to `local-owner`, the same assumption the
runs and sessions migrations made, and the right one: a database written
before ownership existed was written by a single-user install.

A backup taken before this change restores too — `import_all` fills in
the missing owner rather than failing on a NOT NULL column.

## Consequences

- Anyone upgrading a hosted deployment gets all existing memory
  attributed to `local-owner`, which means **no current user sees it**
  until it is reassigned by hand. That is the correct default: the
  alternative is guessing which tenant a shared row belonged to, and
  there is no honest way to guess.
- Backups now carry the owner, so a restore preserves the boundary.
- The new tests are written from the attacker's side of the boundary —
  a second authenticated user, doing nothing unusual — and run against
  both hosted shapes. Both halves of the fix were mutation-checked:
  unscoping the `DELETE` fails six tests, sharing one backend fails
  eight.

## What this does not fix

- **Nothing reassigns the migrated `local-owner` rows.** There is no
  admin surface for it, and inventing one to solve a one-off upgrade
  would be the wrong shape. Reassigning is a SQL `UPDATE` by someone who
  knows whose data it was.
- **Row-level security in the database is still deny-by-default rather
  than owner-aware** (ADR 0001). The application enforces the boundary;
  the database does not independently enforce it, so a defect in the
  application layer is not caught by a second one underneath.
- **There is no per-owner erasure command.** Deleting one tenant
  completely — sessions, runs, tasks, artifacts, datasets, vault notes,
  memory — is a coherent next piece of work and is not done here.
