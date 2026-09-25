# Vercel Deployment

The repository is deploy-ready as a **full-stack Vercel project**: the
React frontend as static assets and the FastAPI backend as a Python
serverless function.

## Why this is possible now

The original blocker was state, not the platform. The backend used to
require local disk (SQLite file, `data/memory.json`, vault folder).
Since ADR 0001 and its amendment, all durable state lives behind the
storage adapter, so the backend can run on an ephemeral filesystem.

## What is configured

| File | Purpose |
| --- | --- |
| `api/index.py` | ASGI entry point Vercel serves for `/api/*`; adds the repo root to `sys.path` and re-exports the unchanged FastAPI `app` |
| `vercel.json` | Builds the frontend, routes `/api/*` to the function, rewrites everything else to the SPA, sets security headers, `no-store` on the API and immutable caching on hashed assets |
| `requirements.txt` | Function dependencies (FastAPI, psycopg2, PyJWT) |
| `.python-version` | Pins the interpreter to 3.12 so the runtime cannot drift under the deployment |

**No custom runtime is pinned.** Vercel's Python support is native: a
`.py` file under `api/` exporting an ASGI `app` is a function, with
dependencies from `requirements.txt` and the interpreter from
`.python-version`. An earlier version of this file pinned
`@vercel/python@4.3.0` — legacy custom-runtime syntax whose version was
written from memory and never verified. A version that does not resolve
fails the build before anything else runs, so the pin was removed rather
than left as a trap for the first deploy.

Serverless hardening already in place:

- `PostgresStore` reconnects once on `OperationalError`, so a pooler or
  cold start dropping an idle connection does not fail a user request.
- `SQLiteStore` relocates to a writable temp directory when its target
  directory is read-only, instead of crashing at import (tested).

## Deploy it

1. In Vercel, **Add New → Project → import `ahmadzayan-hub/11`**.
   `vercel.json` supplies every build setting; if a framework preset is
   offered, "Other" is correct. Vercel makes the repository's **default
   branch** production — currently
   `claude/agentic-os-final-project-53j6ql`, which carries all the work.
   `main` is behind it, so switch the default only after merging.
2. Add environment variables (Project → Settings → Environment
   Variables) — all server-side, never exposed to the browser. **None is
   required for the first deploy**; without them the app runs in local
   mode (single owner, no login) on ephemeral storage, which is enough to
   see and use the interface:

   | Variable | Needed for |
   | --- | --- |
   | `DATABASE_URL` | **Durable state.** Supabase → Connect → *Transaction pooler* (port 6543, built for serverless), with your database password |
   | `AGENTIC_OS_ENV=production` | Fail closed unless auth is configured |
   | `SUPABASE_JWT_SECRET` *or* `AGENTIC_OS_JWKS_URL` | Token verification |
   | `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Browser sign-in (publishable) |
   | `ANTHROPIC_API_KEY` or `GROQ_API_KEY` | Optional model-phrased summaries. `OLLAMA_MODEL` is **not** useful here: a model on a laptop is unreachable from a serverless function |

3. Redeploy after setting the variables and check `/api/health` — it
   reports the model provider without revealing any secret.

The Supabase schema is already applied (project `agentic-os`,
migrations `agentic_os_run_engine` and
`agentic_os_sessions_memory_vault`, RLS deny-by-default).

## Without `DATABASE_URL`

The deployment still runs, but the store falls back to SQLite in the
function's temp directory: state survives only while an instance stays
warm and is lost on cold start. Acceptable for a first look, **not** for
real use. Set `DATABASE_URL` before treating the deployment as usable.

## Verification status — read this before claiming it works

No deployment has been performed from the implementation environment.
Two honest reasons:

1. **Credentials.** `DATABASE_URL` requires the Supabase database
   password and the JWT secret, which only the project owner holds.
   Setting them in the Vercel dashboard is a deliberate human step.
2. **Tooling limits.** The available deploy tool uploads an inline file
   tree; the built frontend bundle alone is ~280 KB, beyond what that
   interface can carry. Git import is the correct path anyway — it gives
   preview deployments per pull request.

So: the configuration is written and locally verified (the ASGI entry
imports and exposes all 22 API routes; the read-only fallback is
covered by a test), but **the deployed URL itself is unverified**. After
importing the project, confirm `/api/health`, sign-in, and one analytics
run before relying on it.

## Rollback

Vercel keeps every deployment. Project → Deployments → select the last
known-good build → **Promote to Production**. Database migrations are
additive (`ADD COLUMN` / `CREATE TABLE IF NOT EXISTS`), so an older
build keeps working against a newer schema.
