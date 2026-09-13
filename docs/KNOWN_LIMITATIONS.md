# Known Limitations

Honest boundaries of the current release. None of these are hidden behind
placeholder controls — absent capabilities have no UI.

## Intelligence

1. The conversational agent is deterministic (command recognition +
   tone-styled acknowledgements); it is not an LLM chat.
2. The analytics pipeline covers all four types (descriptive,
   diagnostic, predictive, prescriptive) deterministically, and each has
   a boundary worth knowing:
   - **Diagnostic** decomposes change by segment (exact arithmetic) and
     measures which columns move together. It does **not** establish
     cause. The separate Experiment and Causal Inference agent
     (ADR 0010) decides whether a causal claim is available at all: it
     compares recorded control/treatment groups and refuses the claim
     otherwise. It estimates nothing from observational data — no
     propensity scores, difference-in-differences, instrumental
     variables, or synthetic control. Where an experiment *is* recorded,
     the range carrying the verdict is always-valid (ADR 0016), so
     checking a running test repeatedly does not inflate the error rate;
     it is about 1.55× wider than the fixed-horizon reading, which is
     printed beside it. Small samples now decline to conclude — eight
     observations are eight observations.
   - **Predictive** fits a straight-line trend to the historical periods
     and extends it, with accuracy measured by backtesting against
     held-out periods. There is no seasonality model, no machine
     learning, and no probabilistic interval — the stated range comes
     from measured backtest error. Fewer than 4 periods produces no
     forecast; fewer than 6 produces a forecast explicitly marked as
     having unmeasured accuracy.
   - **Prescriptive** ranks options the dataset itself supplies, scoring
     each with the same 10% improvement assumption. That ranks where the
     leverage is; it is not an optimizer and knows nothing about cost,
     capacity, or feasibility.
   - Comparison between recorded experiment groups reports a range and
     whether it includes no-change (ADR 0010, 0016). No test is applied
     anywhere else: the descriptive, diagnostic, predictive and
     prescriptive stages are arithmetic, not inference. Nothing
     recommends when to stop a test — that is a decision about cost and
     risk, not a statistic.
3. The optional narrator (Ollama, Anthropic, or Groq) only phrases
   already-verified facts and never receives the dataset. The wire
   contract for each provider is tested against a local HTTP server —
   including a reasoning model's `<think>` scratchpad, which is stripped
   and never reaches a report — but **no live provider call has been made
   from this environment** (its egress policy blocks `ollama.com`,
   `registry.ollama.ai`, and the model APIs), so first use against a real
   endpoint is unconfirmed. A local Ollama must be reachable from the
   machine running the server: a model on a laptop is invisible to a
   hosted deployment. Any failure falls
   back to the deterministic narrator, and the report always names which
   one wrote the summary.
4. There is no autonomous "improve forever" loop. Runs are bounded;
   lessons accumulate as vault run logs for human review. Permanent 100%
   accuracy cannot honestly be promised by any AI system; deterministic
   calculations are exact for the operations implemented.

## Resolved since the first release

Sessions, transcripts, preferences, memory, and published knowledge are
now durable in the storage layer: a server restart no longer loses a
conversation, and in hosted mode (`DATABASE_URL`) the backend keeps no
required local files. Both behaviors are covered by tests
(`test_sessions_survive_an_application_restart`,
`test_hosted_mode_keeps_memory_in_the_database`).

## Platform

5. Authentication ships as an adapter (ADR 0002/0003): local mode is
   single-owner with no login; hosted mode verifies managed-provider
   JWTs with server-side roles, per-owner isolation, a sign-in screen,
   and per-caller rate limiting. Caveats: the live provider round-trip
   was never executed (this environment blocks HTTPS to the provider),
   so first-deployment sign-in must be confirmed once by hand; tokens
   are stored in browser storage without refresh rotation; and the rate
   limiter is per process, so multi-instance deployments need a shared
   store. There is no admin UI for granting roles — roles come from
   token claims or `AGENTIC_OS_DEFAULT_ROLE`. Agent memory is scoped to
   its owner as of ADR 0014 — before that commit a hosted deployment
   shared one memory store between every tenant, so an upgrade
   attributes all existing memory to `local-owner` and **nothing
   reassigns it**; that is a SQL `UPDATE` by someone who knows whose
   data it was. The application enforces the owner boundary; the
   database's row-level security is deny-by-default rather than
   owner-aware, so there is no second line of defence underneath it, and
   erasing one owner is an operator command (`scripts/erase.py`,
   ADR 0015), not an endpoint: it deletes the rows and the published
   files but cannot reach backups, and it names them in every report
   rather than implying completeness. A consequence worth
   stating plainly: `python scripts/serve.py` binds to the local network
   so a phone can reach it, and because local mode has no login, every
   device on that network can read and change the saved memory. The
   launcher prints this at start-up and `--local-only` opts out, but
   nothing enforces it — a laptop on café Wi-Fi is an open app.
6. The metric glossary (ADR 0011) is a file, not a table: it is
   process-wide, so a hosted install cannot give each tenant its own,
   and it is read once at server start, so an edit does not reach a
   running process until it restarts. Its formula language is one
   operation over column names — deliberately less than a metric layer,
   so a definition stays checkable by hand. No glossary ships with the
   repository; an unconfigured install analyses an undefined column and
   says so in every report.
7. Crash recovery is drilled, not assumed (ADR 0012): connection loss,
   a worker killed with SIGKILL mid-stage, and the engine rebuilt
   mid-run are automated against PostgreSQL in CI. A **full database
   outage** is not — CI's database is a service container the test
   process cannot stop — so that drill was executed by hand once, with
   its measurements recorded in the ADR. Not covered anywhere: network
   partition, failover (there is one database and no standby), and
   corruption as opposed to unavailability.
8. Supply-chain evidence stops at composition (ADR 0013): the SBOM
   says what this software is made of, and nothing signs it or attests
   to how it was built. Signed artifacts and SLSA provenance need a
   release process this project does not have. The licence gate blocks
   only strong copyleft in a **shipped** dependency; weak copyleft and
   undeclared licences are reported, not blocked. `pip-audit` remains
   advisory. The repository also has no LICENSE file of its own — what
   this project grants is the owner's decision.
9. Execution is client-stepped by default: runs advance while the Runs
   view is open. A background worker (`python scripts/worker.py`) can
   advance them server-side with no browser, using database leases with
   heartbeats (ADR 0006), but **nothing starts it automatically** and
   Vercel's serverless runtime has no process to run it in — hosted
   deployments there keep the client-stepped path. One worker advances
   one run at a time; parallelism means running more workers. A
   paused or interrupted run resumes from its durable state either way.
10. The repository is configured to deploy to Vercel as a full-stack
    project (static frontend + Python function). **No deployment has been
    performed or verified** — importing the repo and setting the
    credentials are owner steps. Without `DATABASE_URL` a deployment
    falls back to ephemeral per-instance storage. See
    docs/VERCEL_DEPLOYMENT.md.
11. Android support is a verified installable PWA; a native Capacitor
    project is documented but not shipped (no Android SDK available to
    build or test one honestly).
12. Obsidian integration is approval-gated write-back into a vault
    folder; reading/sync/retrieval from a vault is not implemented.
13. Interface language is English; the `language` preference is recorded
    but does not translate the UI. No RTL support yet.
14. Backups are on-demand: `scripts/backup.py` produces a verified,
    restorable backup (the drill in `tests/test_backup.py` destroys the
    database and rebuilds it on every push), but **nothing schedules
    it**, so the recovery point objective is "whenever it was last run".
    A nightly GitHub Actions job is deliberately not shipped — this
    repository is public and workflow artifacts would expose user data
    (ADR 0005). Supabase's automated daily backups cover Pro plans and
    above, not the free plan this project uses. Backup files are
    unencrypted JSON, the whole database is held in memory while one is
    written (fine at the 2 MB dataset limit, not at hundreds of
    megabytes), and in local mode `data/memory.json` lives outside the
    database and must be backed up separately.
15. Usage is bounded per owner (runs/day, dataset count, dataset bytes)
    but **no cost in currency is tracked**: there is no billing
    relationship, model tokens are not counted, and serverless execution
    time is not measured. `/api/usage` names those gaps rather than
    hiding them. The daily window is calendar-based (midnight UTC), so a
    burst either side of midnight can exceed the intended daily rate.
16. Dataset ingestion is CSV only — uploaded as a file or pasted, up to
    2 MB and 50,000 rows, held in the database rather than object
    storage. XLSX, JSON, Parquet, and database connectors are not
    implemented, and analysis is in-memory (no DuckDB/Polars), so
    larger-than-memory datasets are out of scope.
