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

**Deployed on 2026-10-02** to the Vercel project `agentic-os-final-project`
(team `celia2026-3923s-projects`), production domain
`https://agentic-os-final-project.vercel.app`, from commit `2aeb9fd` of
`claude/agentic-os-final-project-53j6ql`.

What the first import got wrong, and the fix: the import dialog
auto-detected the **FastAPI** preset. Under that preset, as the build log
warns, an internal rewrite routes the request *using the rewritten
destination path*, so every `/api/*` request reached the function as
`/api/index`, FastAPI had no such route, and its SPA fallback answered
`index.html`. The site rendered; every API call returned HTML.
`vercel.json` now carries `"framework": null` (the "Other" preset), which
Vercel's configuration reference documents as overriding the project
setting, and the next build routed correctly. Keep that line.

Verified against the live production domain, by HTTP:

- `GET /api/health` → JSON (`status: ok`, deterministic narrator, no
  router, no stages, no runtime).
- `GET /api/pipelines` → JSON.
- `GET /` and `GET /runs` → the SPA's `index.html` with the configured
  security headers.

Not verified, in each case because the implementation environment could
not reach it rather than because it failed:

- **Whether the production domain is public.** The project has Vercel
  Authentication set to *Standard Protection*
  (`all_except_custom_domains`); the checks above went through an
  authenticated bypass. Open the domain in a private window to confirm;
  Project → Settings → Deployment Protection changes it.
- **A browser session, a run and an approval** on the deployment. Only
  GET requests were exercised.
- **Environment variables.** The deploying token could not list them, so
  whether `DATABASE_URL` is set is unknown. The health response does not
  say. Without it, state is per-instance and lost on cold start, as the
  section above describes.
- **Sign-in.** No identity provider is configured, so the deployment runs
  in local mode: one owner, no login, same as a laptop.
- **The Python version.** The "Other" build installed dependencies under
  CPython 3.14 despite `.python-version` saying 3.12; the function
  served, but the pin is evidently not what selects the runtime under
  this preset.

Two things in the Vercel project to tidy by hand:

- A second project, `agentic-os-final-project-frontend`, was created by
  the same import with `frontend` as its root directory. Its builds fail
  (`cd frontend` inside `frontend`) and it serves nothing. Delete it.
- A push to the branch produced a **preview** deployment, not a
  production one: the project's Production Branch is not this branch.
  The fixed build was promoted by creating a production deployment
  explicitly. Set Project → Settings → Git → Production Branch to the
  branch you deploy from, or merge into it, so that pushes update
  production.

## Rollback

Vercel keeps every deployment. Project → Deployments → select the last
known-good build → **Promote to Production**. Database migrations are
additive (`ADD COLUMN` / `CREATE TABLE IF NOT EXISTS`), so an older
build keeps working against a newer schema.
