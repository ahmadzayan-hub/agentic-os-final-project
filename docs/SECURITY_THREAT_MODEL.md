# Security Threat Model

Scope: local-first, single-user application (CLI + web UI + FastAPI on
localhost). There is no authentication layer — adding one is the first
step before any multi-user or hosted deployment (see limitations).

## Assets

User memory (`data/memory.json`), run data and reports (`data/agentic.db`,
`vault/`), settings (`config.json`), the optional `GROQ_API_KEY`.

## Trust boundaries and controls

| Threat (OWASP LLM/Agentic aligned) | Control implemented | Verified by |
| --- | --- | --- |
| Prompt/goal injection via dataset content | Analytics stages are deterministic code; dataset text is data, never instructions; the model narrator receives only computed facts | design + tests |
| Unapproved side effects (excessive agency) | The only side-effecting stage (vault publish) is server-enforced behind an approval bound to the artifact SHA-256; a changed artifact invalidates approval | `tests/test_runs.py` |
| Lost updates / data loss | Cross-session memory reload under a server lock; honest failure messages on failed writes; SQLite WAL transactions | `tests/test_api.py`, `tests/test_utils.py` |
| Path traversal | Resolved-path `is_relative_to` containment for static files | `tests/test_api.py` |
| Sensitive data caching | `Cache-Control: no-store` on all `/api/*` responses | `tests/test_api.py` |
| Clickjacking / MIME sniffing | `X-Frame-Options: DENY`, `nosniff`, referrer & permissions policies (server + Vercel headers) | header test |
| Secret exposure | No secrets in the repo; provider keys are env-only, never logged or sent to the browser; `.env.example` has placeholders only | repo scan, code review |
| Unbounded loops / cost | Runs have a fixed bounded stage list; datasets capped (2 MB / 50,000 rows); model calls capped (1 per run, 220 tokens, 12 s timeout) | code + tests |
| Stack-trace disclosure | Global exception handler returns a generic message | `server/app.py` |
| Privacy in git history | Runtime data (`memory.json`, `agentic.db`, `vault/`) untracked and ignored; note: `data/memory.json` existed in history as `{}` only — no personal data was ever committed | git log |

## Identity and access control (ADR 0002)

| Threat | Control | Verified by |
| --- | --- | --- |
| Unauthenticated access in a hosted deployment | Production declares auth or startup fails closed; every endpoint except `/api/health` requires a principal | `tests/test_auth.py` |
| Forged / replayed / downgraded tokens | Managed-provider JWT verification with pinned algorithms — HS256 for shared secrets, RS256/ES256 for JWKS — rejecting `alg: none`, bad signatures, expiry, and audience mismatch | 8 attack tests |
| Privilege escalation via token claims | Roles come from a server-side permission table; unknown role claims fall back to least privilege (`viewer`) | role-forgery test |
| Cross-tenant access | `owner` on sessions, runs, datasets **and agent memory**; reads filtered, writes ownership-checked before any state change; other owners' resources answer 404 (no existence oracle) | isolation tests, `tests/test_tenancy.py` |
| Cross-tenant memory (found and fixed, ADR 0014) | `memory_kv` keyed by `(owner, key)`; load and save both scoped, so one tenant can neither read nor overwrite another's. Until that commit a hosted deployment shared one memory store: every tenant read everybody's memory, and every save deleted everybody else's | `tests/test_tenancy.py`, both hosted shapes, mutation-checked |
| Credential leakage in errors | Auth failures return fixed messages; token content never echoed | leak test |

| Model/resource denial of service, runaway loops | Per-caller token bucket on all state-changing API calls; `429` with `Retry-After`; default sized above the app's own cadence (ADR 0003) | limiter + API tests |
| Credential handling by this app | Sign-in posts directly to the identity provider with its publishable key; Agentic OS never receives a password | sign-in unit tests |

## Known gaps (explicit)

0. The owner boundary is enforced by the application only. Row-level
   security in the database is deny-by-default rather than owner-aware
   (ADR 0001), so an application-layer defect is not caught by a second
   line underneath it — which is how the memory gap in ADR 0014 stayed
   open. There is also no command that erases one owner completely.
1. The live provider sign-in round-trip is unverified (this environment
   blocks HTTPS to the provider); confirm once on first deployment.
2. Tokens sit in browser storage without refresh rotation — an expired
   token requires signing in again. XSS would expose a token; mitigated
   by strict headers and no third-party scripts.
3. The rate limiter is per process; multi-instance needs a shared store.
4. No CSRF tokens (tokens travel in the Authorization header, not
   cookies; CORS is restricted).
5. No admin UI for granting roles.
4. Groq path could not be live-tested here (no key); its failure handling
   is defensive-by-construction and falls back deterministically.
