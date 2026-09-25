# ADR 0002 — Managed identity, roles, and tenant isolation

Date: 2026-08-10 · Status: Accepted

## Context

Authentication was the last blocker to hosted multi-user operation. The
governing constraint (master prompt §13/§20) is explicit: use a
standards-based managed provider behind an adapter, never a homemade
password system, and **fail closed** in production when identity is not
configured.

## Decision

`server/auth.py` provides one interface with two implementations:

- **LocalIdentity** (default): every request is the single local owner.
  No login, no credentials, no behavior change for the local-first and
  CLI experience. This is what the test suite and CI exercise.
- **JwtIdentity** (production): verifies a Bearer JWT from a managed
  provider — Supabase Auth or any OIDC issuer — via a shared secret
  (HS256, `AGENTIC_OS_JWT_SECRET` / `SUPABASE_JWT_SECRET`) or a JWKS
  endpoint (RS256/ES256, `AGENTIC_OS_JWKS_URL`). PyJWT is imported
  lazily, so local installs need no new dependency.

Roles and permissions are a server-side table
(`owner`/`admin` → read+write+approve+admin, `analyst` →
read+write+approve, `viewer`/`auditor` → read). Every endpoint declares
the permission it needs as a FastAPI dependency; the UI is never the
enforcement point.

Ownership: `runs` and `sessions` carry an `owner` column (added by an
additive, repeatable migration that backfills pre-auth rows to
`local-owner`). Reads are filtered by owner and writes check ownership
*before* any state change. A resource owned by another user answers
**404, not 403**, so the API is not an existence oracle. Admins may act
across owners.

## Security properties tested

`tests/test_auth.py` covers the attacks, not just the happy path:
forged signature, expired token, `"alg": "none"` downgrade, audience
mismatch, non-Bearer scheme, missing header, role-claim forgery
(unknown roles fall back to least privilege), error messages that never
echo the token, cross-tenant read/write/cancel on both sessions and
runs, and admin cross-owner access. Fail-closed startup is asserted for
both `AGENTIC_OS_ENV=production` and `AGENTIC_OS_REQUIRE_AUTH=1`.

## Consequences

- Least privilege by default: an authenticated user with no role claim
  gets `viewer`. Operators grant more via a role claim in the token or
  `AGENTIC_OS_DEFAULT_ROLE`.
- `/api/health` stays public (load-balancer probes); everything else
  requires a principal.
- The frontend attaches `Authorization: Bearer` when a token is present
  in browser storage and omits it in local mode. **A sign-in UI is not
  yet built** — a hosted deployment obtains tokens through its own
  Supabase Auth front door today. That UI is the next slice, tracked in
  the roadmap; nothing in the app pretends it exists.
- Row-level security in the database remains deny-by-default; the
  backend is the only path to data.
