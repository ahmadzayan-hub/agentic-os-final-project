# ADR 0003 — Sign-in flow and request rate limiting

Date: 2026-08-10 · Status: Accepted

## Context

ADR 0002 added token verification but left two gaps: no way for a user
to *obtain* a token, and no protection against a runaway or abusive
client.

## Decision — sign-in

Credentials never touch this application. The browser talks directly to
the deployment's identity provider (Supabase Auth) using its
**publishable** key, and Agentic OS only ever receives the resulting
access token.

- A new public endpoint `GET /api/auth/config` advertises the mode
  (`local` or `jwt`), the provider URL, the publishable key, and the
  supported flows. It is reachable without a token because the browser
  needs it *before* signing in, and it is asserted to contain no secret.
- In `local` mode it reports `flows: []` and the UI shows no sign-in at
  all — the offline single-user experience is untouched.
- In `jwt` mode the app renders a sign-in screen supporting password and
  magic-link flows against the provider's own endpoints.
- Any `401` from any API call clears the stored token and returns the
  user to sign-in, so an expired or revoked token cannot leave the UI in
  a broken half-authenticated state.
- Sign-out clears the token and the stored session id.

Tokens live in browser storage. The honest trade-off: this is vulnerable
to XSS, mitigated by strict headers and no third-party scripts, and is
the standard approach for a token-based SPA. Refresh-token rotation is
not implemented — an expired token means signing in again.

## Decision — rate limiting

A token-bucket limiter (`server/rate_limit.py`) applies to state-changing
methods on `/api/*`, keyed by token subject (or client address when
anonymous). Exceeding it returns `429` with `Retry-After`; remaining
budget is reported in `X-RateLimit-Remaining`.

Scope stated plainly: the bucket is **per process**. It protects the
single-instance deployment that is supported today. Multi-instance
deployments need a shared store — tracked in the roadmap, not assumed.

### Default chosen from measured behavior, not guesswork

The initial 120/min default was **wrong** and the test suite proved it:
a client-stepped analytics run issues roughly three advance calls per
second, which exceeds a 2/second refill rate, so a normal run throttled
itself mid-pipeline. The default is now 600/min (10/s), which clears the
application's own cadence with headroom while still stopping runaway
loops. The Runs view additionally treats `429` as retryable — it backs
off to 1.5 s and continues rather than abandoning a half-finished
pipeline.

## Evidence

- 133 Python tests (both database dialects), including token-attack
  cases, auth-config secret-leak checks, limiter unit tests (refill,
  per-caller isolation) and API 429 behavior.
- 23 frontend unit tests including the sign-in flow: credentials go to
  the provider URL with the publishable key, provider errors surface, a
  token-less response is rejected, magic-link confirmation, and the
  no-provider-configured warning.
- 34 e2e checks across desktop and mobile, including a second server
  instance with auth enabled: the sign-in wall blocks the workspace,
  keyboard operation, a valid token unlocks it and shows the role,
  sign-out returns to the wall, and a forged token is rejected and
  discarded. Three consecutive full-suite runs were green.

## Limitation

The live provider round-trip could **not** be executed from the
implementation environment — outbound HTTPS to `*.supabase.co` is
blocked by its proxy. The sign-in component is verified against a
controlled stub of the provider's documented contract. A real
email/password and magic-link sign-in must be confirmed once during the
first hosted deployment.
