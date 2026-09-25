# ADR 0001 — Run-engine persistence: SQLite locally, PostgreSQL hosted

Date: 2026-08-10 · Status: Accepted

## Context

Tier 2 of the roadmap requires a hosted, durable data plane so the
backend can run on stateless hosts. The local-first mode must keep
working with zero setup and zero credentials.

## Decision

A narrow storage adapter (`server/storage.py`) with two dialects behind
one interface:

- **SQLiteStore** (default): WAL-mode file database, unchanged behavior.
- **PostgresStore**: activated by `DATABASE_URL`, psycopg2 over the wire
  protocol, imported lazily so local installs need no driver.

Both share identical DDL and column names; rows cross the boundary as
plain dicts. The provisioned hosted instance is the Supabase project
`agentic-os` (`yinrbdlgphkvobipsqka`, ap-south-1, free tier), with the
schema applied as migration `agentic_os_run_engine` and **RLS enabled
deny-by-default** on all four tables so Supabase's public data API
cannot reach them — access is wire-protocol only, as the database owner.

## Evidence

- The full run-engine test suite executes against BOTH dialects
  (`tests/test_runs.py`: `RunEngineTestCase` + `RunEnginePostgresTestCase`),
  verified locally against PostgreSQL 16 and enforced in CI via a
  postgres:16 service container with `REQUIRE_PG=1` (an unreachable
  database fails the build — no silent skips).
- Supabase schema verified by query: 4 tables, `rowsecurity=true` each.

## Consequences

- The deployment host sets `DATABASE_URL` (Supabase session-pooler
  string, IPv4-compatible); the sandbox that authored this change cannot
  open wire-protocol connections (HTTPS-only egress), so the first
  end-to-end run against Supabase itself happens from the deployment
  host — the identical code path is what CI verifies against Postgres 16.
- Statements autocommit (parity with the previous SQLite behavior);
  multi-statement transactional grouping is a future hardening item.

## Amendment (2026-08-10): full state moved behind the store

The adapter now also carries `sessions`, `memory_kv`, and `vault_notes`
(migration `agentic_os_sessions_memory_vault`, RLS deny-by-default like
the rest). Consequences:

- Sessions, transcripts, and preferences are durable in **both** modes —
  a restart resumes the conversation instead of dropping it.
- In hosted mode the Agent's memory backend switches to the database
  (`DbMemoryBackend`), so no local memory file is required; local mode
  keeps the `data/memory.json` contract unchanged.
- Published vault notes are written to the store first (source of truth,
  served by `/api/vault`) and to the vault folder when the filesystem
  allows, so a read-only host degrades gracefully instead of failing the
  publish.
- The backend now needs no local disk. The remaining hosting constraint
  is connection style, not state: it must hold a TCP connection to
  PostgreSQL.
