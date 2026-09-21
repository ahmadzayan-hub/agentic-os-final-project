# Release Roadmap and Scope Control

The greatest project risk is uncontrolled scope, not a missing agent.
This roadmap fixes three release tiers with measurable gates, based on an
independent architecture review of the V2 specification. Nothing in a
later tier may be presented as shipped before its gate passes.

## Tier 1 — Academic MVP (SHIPPED, evidence in docs/UI_UX_AUDIT.md)

Deterministic assistant (CLI + web), durable analytics run engine with a
governed ten-specialist pipeline, claim–evidence validation, approval-
gated Obsidian vault publishing, provider-neutral model gateway
(deterministic default, optional Groq narration), mobile-first PWA,
security hardening, CI gates. Evidence at the time of that gate: 88
Python + 18 unit + 23 e2e tests green in CI; Lighthouse 95/100/100/100;
clean npm audit. (Tier 2 work has since grown the suite well past that;
the current counts live in README.md, which is the one place they are
maintained.)

Standing rule already enforced and carried forward: **raw datasets are
never sent to a model provider** — only deterministic, already-verified
facts reach the narrator.

## Tier 2 — Production MVP (next; each item needs an ADR + release gate)

1. Managed authentication (OIDC adapter) with Owner/Admin/Analyst/Viewer
   roles; fail-closed in production mode.
   **Done:** identity adapter with local and JWT (shared-secret or JWKS)
   providers, server-side role permissions on every endpoint, per-owner
   isolation for sessions and runs, fail-closed production startup, an
   attack-focused test suite (ADR 0002), plus a provider-direct sign-in
   screen, 401 recovery, sign-out, and per-caller rate limiting
   (ADR 0003). **Remaining:** confirm the live provider round-trip on
   first deployment, refresh-token rotation, a shared-store limiter for
   multi-instance, and an admin surface for granting roles.
2. PostgreSQL adapter behind the existing `RunEngine`/memory interfaces,
   plus object storage for datasets and artifacts; migration tooling,
   backups, and restore drills (documented RPO/RTO).
   **Done:** run-engine Postgres adapter shipped and CI-enforced against
   Postgres 16; Supabase project `agentic-os` provisioned, RLS
   deny-by-default; sessions, memory, and published vault notes all moved
   behind the store, so the backend requires no local disk (ADR 0001 and
   its amendment), plus content-addressed dataset storage (ADR 0004), and
   backups with an executed restore drill — the suite destroys the
   database and rebuilds it through the operator scripts on every push,
   against both dialects, with measured times (ADR 0005).
   **Remaining:** a scheduled off-site backup job, which cannot live in
   this public repository without publishing user data (ADR 0005), and
   external object storage, which only becomes worthwhile above tens of
   megabytes.
3. Durable workflow execution: evaluate **Vercel Workflows for Python**
   directly against the run-engine contract (pause/resume/recovery)
   before committing to the abstraction; otherwise database-backed jobs
   with leases and heartbeats.
   **Done:** evaluated and declined in favour of database leases with
   heartbeats — a background worker advances runs with no browser open,
   crash recovery is lease expiry rather than a cleanup path, clients and
   workers can never execute the same task, and pause became durable
   server-side state so the control means the same thing in both modes
   (ADR 0006). **Remaining:** nothing starts the worker automatically,
   and Vercel's serverless runtime cannot host it, so hosted deployments
   there stay client-stepped.
4. Scalable analytics data plane: DuckDB or Polars for bounded local
   analysis, resumable uploads, dataset size/memory limits, partitioning
   and sampling, restricted-data egress controls.
   **Done:** content-addressed dataset storage (identical uploads stored
   once), file upload with client-side validation, dataset reuse by id,
   limits raised to 2 MB / 50,000 rows (ADR 0004). **Remaining:**
   DuckDB/Polars for larger-than-memory analysis, resumable uploads,
   partitioning and sampling.
5. Verified Vercel deployment against the hosted API; preview
   deployments per PR; rollback documented.
   **Done:** full-stack Vercel configuration (`api/index.py` ASGI entry
   + `vercel.json`), serverless hardening (Postgres reconnect,
   read-only-filesystem fallback), and a documented deploy/rollback
   procedure. **Remaining:** the import itself and the environment
   variables, which need the owner's credentials — no deployment has
   been made or claimed (see docs/VERCEL_DEPLOYMENT.md).
6. Tenant quotas, usage budgets, and cost tracking (FinOps foundation).
   **Done:** three per-owner limits — runs per day, datasets stored, and
   total dataset bytes — counted from the durable rows rather than a
   parallel tally, enforced before the resource is created, refused with
   a 429 that names the limit and when it resets, and shown in the
   interface as meters (ADR 0008). Re-uploading a stored dataset is not
   charged. **Deliberately not done:** currency figures. There is no
   billing relationship, no token accounting, and no execution-time
   measurement here, so a cost column would be fabricated; the response
   names what it does not measure instead.
7. Per-report model selection, so the narrator is a decision rather than
   a start-up default.
   **Done:** an optional router chosen by two environment variables,
   behind a one-method contract (`route_single`) that every
   [LLMRouter](https://github.com/ulab-uiuc/LLMRouter) router satisfies
   and a four-line class also satisfies (ADR 0017). The report prints
   which model narrated **and why that one**; a choice this deployment
   cannot reach is refused and reported as refused rather than quietly
   swapped; the router receives the verified facts and never the dataset;
   a router that fails to load leaves the application unchanged and says
   so in `/api/health`. **Deliberately not done:** LLMRouter as a
   dependency — 5.3 GB of torch and CUDA wheels, measured, against a CLI
   that otherwise needs only the standard library. **Not done:** cost or
   latency feedback to the router, per-tenant routers, and any exercise
   of LLMRouter's learned (KNN/MLP/graph) routers, whose checkpoints this
   environment cannot download.

## Tier 3 — Enterprise Release (scoped, not started)

- **Metric governance:** business glossary, certified KPI workflow with
  ownership, fiscal calendars, slowly changing dimensions, schema
  evolution and impact analysis, row/column-level security, entity
  resolution. **Partly done (ADR 0011):** a file-based glossary gives
  each metric a definition, a named owner, a certification flag and
  optionally the arithmetic it must satisfy; the glossary decides which
  column a run analyses, the choice and its reason are reported, every
  row is checked against a formula whose inputs are present, and
  validation fails a run whose measure is uncertified and unsaid.
  **Remaining:** per-tenant glossaries and an editing surface (the file
  is process-wide and read at startup), fiscal calendars, slowly changing
  dimensions, schema-evolution impact analysis, row/column-level
  security, and entity resolution.
- **Experimentation and causal inference:** power analysis, A/B and
  sequential testing, multiple-testing control, sample-ratio-mismatch
  detection, explicit confounding and counterfactual limitations.
  **Partly done (ADR 0010):** the Experiment and Causal Inference Agent
  ships fixed-horizon A/B comparison with an uncertainty range,
  Bonferroni control across arms, sample-ratio-mismatch detection, power
  and minimum-detectable-effect arithmetic, and a refusal path that
  prices the experiment when the data is observational. **Also done
  (ADR 0016):** always-valid inference — a normal-mixture confidence
  sequence now carries the verdict, so checking a running test repeatedly
  and stopping when it looks good does not inflate the error rate
  (simulated: 31.5% false alarms under peeking becomes 1.0%), with the
  fixed-horizon reading kept beside it and labelled with the assumption
  it needs. **Remaining:** an early-stopping recommendation, which is a
  decision about cost and risk rather than a statistic, and any method
  for estimating an effect from observational data (propensity scores,
  difference-in-differences, instrumental variables, synthetic control) —
  each of which is a research decision, not a missing function.
- **UAE PDPL compliance:** data-residency decisions, cross-border
  transfer controls, processor registers, consent evidence, privacy
  impact assessments, deletion across primary storage, embeddings,
  telemetry, and backups. **Partly done (ADR 0015):** deletion across
  primary storage — one command erases an owner's rows in every table
  and the published markdown files on disk, surveys before it deletes,
  and names in every report what it could not reach (backups first).
  **Remaining:** everything that is a decision rather than code —
  residency, transfer controls, processor registers, consent evidence,
  impact assessments — plus deletion inside backups, which a tool must
  not do silently, and an erasure endpoint, which needs the product
  questions in ADR 0015 answered first.
- **Business continuity:** SLOs and error budgets, point-in-time
  recovery, incident classification and on-call ownership, load/soak/
  failover/chaos testing, provider-exit procedures. **Partly done
  (ADR 0012):** failure injection in CI — connection loss on the lease
  path in both of its forms, a worker killed with SIGKILL mid-stage, and
  the engine rebuilt mid-run — plus a hand-executed database-outage
  drill with measured recovery times, and service levels stated from
  those measurements. It found three real defects, including a crash
  during a stage silently producing a broken run. **Remaining:** error
  budgets (which need production traffic and a measurement pipeline
  that does not exist here), point-in-time recovery and a standby,
  incident classification and on-call ownership, load and soak testing,
  and provider-exit procedures.
- **Supply chain:** SBOM, signed artifacts, build provenance, license
  scanning, pinned actions/packages, vendor registers and contingency.
  **Partly done (ADR 0013):** every third-party action pinned to a
  commit SHA with the release named and a test that keeps it that way;
  a CycloneDX SBOM generated on every build from the npm lock file and
  the Python dependency closure, kept as a CI artifact; and a licence
  gate that fails the build on a shipped strong-copyleft dependency
  while naming weak-copyleft and undeclared ones. Packages were already
  pinned by lock file and `requirements.txt`. **Remaining:** signed
  artifacts and build provenance (both need a release process this
  project does not have — it has a branch), a signed SBOM, and vendor
  registers and contingency, which are documents about an organisation
  rather than about this code.
- **Android release lifecycle:** Capacitor project, Play App Signing,
  developer verification (regional from 2026-09-30), testing tracks,
  Data Safety declaration, Play Integrity, crash/ANR monitoring,
  real-device matrix. (The PWA remains the supported mobile path until
  this gate passes.)
- **Collaboration and accountability:** comments, mentions, delegated
  approvals, artifact permissions, notifications, and an explicit RACI.
- **Obsidian privacy lifecycle:** local-only mode, zero-server-copy
  option, key ownership, embedding/backup deletion, sync diagnostics,
  plugin release review.

## Additional governed capabilities (no decorative agents)

Seven specialists were added in ADR 0009 — data contract, data quality,
privacy, segment concentration, anomaly, sensitivity, and provenance — an
eighth in ADR 0010 (experiment and causal inference) and a ninth in ADR
0011 (metric governance). Each was admitted on the test that it computes
something no other stage computes. The roster is twenty-one stages plus
the publish gate, orchestrated by **Hermes**, which analyses nothing
itself. The rule was
never "few agents"; it was "no agent that only rephrases another".

The typed contracts below remain outstanding:

1. Data Platform Agent (the *Data Contract* half shipped in ADR 0009)
2. Pluggable Domain Expert Agent
3. Reliability and Incident Management Agent

The Experiment and Causal Inference Agent left this list in ADR 0010
with its typed contract in `docs/AGENT_CATALOG.md`, including the
explicit statement of what it does not attempt.

Each enters the catalog only with the full typed contract
(entry/exit criteria, budgets, quality checks, evaluation suite) defined
in `docs/AGENT_CATALOG.md`.

## Decision records

Key decisions to date are recorded in `docs/ARCHITECTURE.md`. From Tier 2
onward, every choice listed above (database, object storage, workflow
engine, identity provider, analytics engine, Obsidian sync, Android
approach) requires a versioned ADR under `docs/adr/`.
