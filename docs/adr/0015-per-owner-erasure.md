# ADR 0015 — Erasing one owner, and saying what survived

**Status:** Accepted
**Date:** 2026-09-12

## Context

ADR 0014 gave every row an owner. The obvious next question is the one a
data-subject request asks: *delete everything you hold about me.* There
was no way to answer it except by hand, across eight tables and a
directory of markdown files, in an order foreign keys would accept.

Doing that by hand is how the interesting failure happens. Someone
deletes the rows, the published report stays on disk, and the answer
given is "deleted" — which is now a false statement rather than a
missing feature. UAE PDPL's erasure right, like the GDPR article it
resembles, is not satisfied by a query that returns nothing.

## Decision

`scripts/erase.py --owner <id>` surveys; `--yes` deletes. The survey is
the default because the operation is irreversible and the owner
identifier is a string somebody typed.

What it removes, children before parents so foreign keys hold at every
step: `tasks`, `approvals`, `artifacts`, `vault_notes`, `runs`,
`datasets`, `sessions`, `memory_kv` — the first four resolved through
the owner's runs, the last four owned directly. Then the published
markdown **files**, because a report exists in two places and deleting
one of them is exactly the mistake above. In local mode it also clears
`data/memory.json`, which lives outside the database entirely.

Every report ends with `not_reached` — the copies this command cannot
touch:

- **Database backups.** Every backup taken before the erasure still
  contains the rows, and restoring one restores them.
- **Obsidian vaults synced elsewhere**, including a git repository or a
  cloud folder.
- **Exports the owner downloaded**, and anything a reader saved.
- **Operational logs and CI artifacts** that may quote a goal in
  passing.

That list is printed whether or not anything was found, because "nothing
here" and "nothing anywhere" are different answers and only one of them
is true.

## Why a command and not an endpoint

An erasure endpoint is a destructive operation reachable over the
network, and getting it right means deciding who may erase whom, what
confirmation the interface demands, and what happens to a run in flight.
Those are product decisions, and shipping the network surface before
making them would put the dangerous half in place first. The operator
command answers the request today; the endpoint can follow when the
questions above have answers.

## What the drills found worth keeping

**Content-addressed datasets.** Identical uploads are deduplicated, and
if the dedupe were global, erasing one owner would silently delete
another owner's data. It is not — `find_dataset` matches on
`(sha256, owner)`, so each owner holds their own row. That is now
asserted rather than assumed: the test uploads the same bytes as two
tenants, erases one, and checks the other's row survives with its
content intact.

**The local memory file belongs to the single-user install.** Clearing
it while erasing a hosted tenant would delete a different person's data
on the way past, so it is cleared only for `local-owner`.

**Naming the database in the report.** A relative `database_file`
resolves against the working directory, so running the command from the
wrong place finds an empty database and reports, accurately and
uselessly, that the owner has nothing. This happened while the command
was being written. The report now names the database it acted on —
with any password stripped, because a DSN in a terminal is a credential
in a scrollback buffer — which turns a puzzling result into an obvious
mistake.

## Consequences

- A data-subject request has a procedure: survey, verify the counts look
  like the right person, erase, then deal with the backups the report
  names.
- Erasure is irreversible and has no undo. That is the point, and the
  survey-first default is the mitigation.
- 23 tests across both dialects, because a DELETE that respects foreign
  keys in SQLite but not in PostgreSQL is a deletion that stops halfway.
  Mutation-checked: skipping the vault files fails two tests, deleting
  datasets globally instead of per owner fails six.

## What this does not do

- **No endpoint, no interface.** See above.
- **Nothing touches the backups.** The command names them; rotating or
  editing them is an operator decision, and a tool that silently edited
  a backup would destroy the property that makes backups worth having.
- **No certificate of erasure.** The report is JSON on stdout; capturing
  it as evidence is the operator's business.
- **No anonymisation option.** Erasure here is deletion. Keeping
  aggregate figures while removing their owner is a different feature
  with different arguments, and pretending deletion covers it would be
  the same class of overclaim this ADR exists to avoid.
