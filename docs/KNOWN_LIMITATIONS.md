# Known Limitations

Honest boundaries of the current release. None of these are hidden behind
placeholder controls — absent capabilities have no UI.

## Intelligence

1. The chat understands and acts on plain language — save, recall,
   change a preference, start an analysis, report its status, explain a
   report, in English or Arabic — through a **rules-based vocabulary**
   that works with no model (ADR 0019). A configured model widens what
   is understood, not what can be done: it picks from the same ten
   actions, and only its `chat` phrasing is ever shown. Boundaries: a
   sentence outside the vocabulary gets an honest "not understood, here
   is what you can ask"; one action per sentence; "explain" quotes the
   report's verified headlines rather than reasoning over the report;
   and **no live model has handled a sentence from this environment**
   (the model path is tested against a fake), so the first real one is
   unverified and the rules fallback is what makes that safe.
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
     held-out periods. There is no probabilistic interval — the stated
     range comes from measured backtest error. A seasonal model, a
     regression, a classifier and a clustering are available as optional
     stages on the `models` profile (ADR 0033; see item 28). Fewer than 4 periods produces no
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
4. Which model narrates can be decided per report by an optional router
   (ADR 0017), and that too has edges. **LLMRouter is not installed by
   default** and is not in `requirements.txt`: its routers bring torch,
   transformers and CUDA wheels — 5.3 GB measured — so five tests skip on
   an ordinary install and in CI, which is the expected result rather
   than a gap. Importing one costs about **11 seconds of start-up**
   (torch, once); the routing decision itself is free for the heuristic
   routers. Only those two heuristic routers (`SmallestLLM`,
   `LargestLLM`) have been exercised here — LLMRouter's **KNN, MLP and
   graph routers need embedding models and checkpoints this environment's
   egress policy blocks**, so they are untested, and "it works with
   SmallestLLM" is not "it works with the MLP router". Nothing measures
   what a choice cost and nothing feeds that back: there is no online
   learning and no billing relationship to learn against (ADR 0008).
   There is one router per process, fixed at start-up, so a hosted
   install cannot give each tenant its own — the same limitation, for the
   same reason, as the metric glossary below. A choice the deployment
   cannot reach is refused rather than substituted, which means a router
   trained on a catalogue this install does not hold contributes nothing
   but a line in the report saying so.
5. There is no autonomous "improve forever" loop. Runs are bounded;
   lessons accumulate as vault run logs for human review. Permanent 100%
   accuracy cannot honestly be promised by any AI system; deterministic
   calculations are exact for the operations implemented.
6. Every classifying agent is measured on labelled **synthetic** cases
   (ADR 0027), and the numbers are only as good as those cases. On the
   newest blind holdout (v4, 17 October) the rules reach 72% macro recall
   for chat intent, 92% recall for jargon and 69% for causal wording
   (precision 92%). Hand-written rules generalise only so far: intent
   scored 80% on the previous blind set and 68% on this one before any
   change, and a round of fixes from the earlier set lifted causal wording
   by nothing here. A sentence the causal check passes may still claim a
   cause, and a chat sentence outside the vocabulary is answered as chat. The seeded reviewer memos were nearly too easy for the
   reviewer subagents: both scored at or near 100% with either prompt.
   So the prompt changes are justified on the dev memo, not proven on the
   held-out ones, and the subagents' run-to-run variation (zero to three
   false alarms on the same memo) is measured on one run per condition.
   Local Ollama models and the hosted narrators are **not measured**: the
   models could not be downloaded here, and no provider key was used. The
   figures checker cannot read a figure written in words ("one in five");
   the figures-auditor reads the text for those.

## Resolved since the first release

Sessions, transcripts, preferences, memory, and published knowledge are
now durable in the storage layer: a server restart no longer loses a
conversation, and in hosted mode (`DATABASE_URL`) the backend keeps no
required local files. Both behaviors are covered by tests
(`test_sessions_survive_an_application_restart`,
`test_hosted_mode_keeps_memory_in_the_database`).

## Platform

6. Authentication ships as an adapter (ADR 0002/0003): local mode is
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
7. The metric glossary (ADR 0011) is a file, not a table: it is
   process-wide, so a hosted install cannot give each tenant its own,
   and it is read once at server start, so an edit does not reach a
   running process until it restarts. Its formula language is one
   operation over column names — deliberately less than a metric layer,
   so a definition stays checkable by hand. No glossary ships with the
   repository; an unconfigured install analyses an undefined column and
   says so in every report.
8. Crash recovery is drilled, not assumed (ADR 0012): connection loss,
   a worker killed with SIGKILL mid-stage, and the engine rebuilt
   mid-run are automated against PostgreSQL in CI. A **full database
   outage** is not — CI's database is a service container the test
   process cannot stop — so that drill was executed by hand once, with
   its measurements recorded in the ADR. Not covered anywhere: network
   partition, failover (there is one database and no standby), and
   corruption as opposed to unavailability.
9. Supply-chain evidence stops at composition (ADR 0013): the SBOM
   says what this software is made of, and nothing signs it or attests
   to how it was built. Signed artifacts and SLSA provenance need a
   release process this project does not have. The licence gate blocks
   only strong copyleft in a **shipped** dependency; weak copyleft and
   undeclared licences are reported, not blocked. `pip-audit` remains
   advisory. The repository also has no LICENSE file of its own — what
   this project grants is the owner's decision.
10. Execution is client-stepped by default: runs advance while the Runs
    view is open. A background worker (`python scripts/worker.py`) can
    advance them server-side with no browser, using database leases with
    heartbeats (ADR 0006), but **nothing starts it automatically** and
    Vercel's serverless runtime has no process to run it in — hosted
    deployments there keep the client-stepped path. One worker advances
    one run at a time; parallelism means running more workers. A
    paused or interrupted run resumes from its durable state either way.
11. The repository is deployed to Vercel as a full-stack project (static
    frontend + Python function) at `agentic-os-final-project.vercel.app`,
    and `/api/health`, `/api/pipelines` and the interface were verified
    there by HTTP on 2026-10-02. What was **not** verified from the
    implementation environment: that the domain is reachable without a
    Vercel login (the project has Standard Protection on), a full run and
    approval in a browser there, and whether `DATABASE_URL` is set —
    without it a deployment keeps per-instance storage that a cold start
    wipes. No identity provider is configured, so the deployment is
    single-owner with no login, like a laptop. See
    docs/VERCEL_DEPLOYMENT.md for the exact state and the two things to
    tidy by hand.
12. Android support is a verified installable PWA; a native Capacitor
    project is documented but not shipped (no Android SDK available to
    build or test one honestly).
13. Obsidian integration is approval-gated write-back into a vault
    folder; reading/sync/retrieval from a vault is not implemented.
14. The interface is Arabic or English (ADR 0018), right-to-left in
    Arabic, and the agent's own replies follow the chosen language.
    Reports are written in the language a run was started in (ADR 0022),
    with the same figures, verified by the validator claim by claim.
    Boundaries: a report's language is fixed when its run starts, so the
    other language means a new run and a new approval; calculation names
    and methods, column and group names and period labels stay as the
    data and the evidence wrote them; a custom stage's text appears as its
    author wrote it; the choice is per browser and per session, so a
    hosted install has no organisation-wide default; and Arabic uses
    system fonts, so the face varies by operating system (no font is
    downloaded, because the app works offline). Digits are Western in
    both languages so a figure on screen matches the same figure in any
    report.
15. Backups are on-demand: `scripts/backup.py` produces a verified,
    restorable backup (the drill in `tests/test_backup.py` destroys the
    database and rebuilds it on every push), but **nothing schedules
    it**, so the recovery point objective is "whenever it was last run".
    A nightly GitHub Actions job is deliberately not shipped — this
    repository is public and workflow artifacts would expose user data
    (ADR 0005). Supabase's automated daily backups cover Pro plans and
    above, not the free plan this project uses. Backup files are
    unencrypted JSON, the whole database is held in memory while one is
    written (fine at the 10 MB dataset limit, not at hundreds of
    megabytes), and in local mode `data/memory.json` lives outside the
    database and must be backed up separately.
16. Usage is bounded per owner (runs/day, dataset count, dataset bytes)
    but **no cost in currency is tracked**: there is no billing
    relationship, model tokens are not counted, and serverless execution
    time is not measured. `/api/usage` names those gaps rather than
    hiding them. The daily window is calendar-based (midnight UTC), so a
    burst either side of midnight can exceed the intended daily rate.
17. Datasets come from a file (CSV, TSV, Excel `.xlsx`, JSON or JSON
    Lines) or pasted CSV (ADR 0024): up to 4 MB as uploaded, the limit
    of the platform the app is deployed to, 50,000 rows, and 10 MB once
    converted to CSV. They are held in the database rather than object
    storage. Not read: old `.xls` workbooks, OpenDocument, Parquet, CSV
    in any encoding but UTF-8 or UTF-16, and database connectors. A
    workbook gives one sheet per upload; the API can name another
    sheet, but the interface cannot yet. A formula with no saved result
    arrives empty, with a warning. Analysis is in-memory (no
    DuckDB/Polars), so larger-than-memory datasets are out of scope, and
    a dataset cannot yet be deleted from the interface.
18. Custom stages (ADR 0020) are **trusted Python in this process**, not
    a sandbox: the contract catches a malformed result, a mis-cited
    claim or a mutated context, and a plugin that wants to misbehave
    can still import anything. The operator decides what to register.
    The registry is per process and read at start-up — no per-tenant
    stages in a hosted install, and a new stage needs a restart, as
    with the glossary and the router. A custom stage cannot narrate (it
    gets no model gateway) and cannot chart; its figures are tables.
19. An agent runtime (ADR 0021) is optional and bounded, and both
    halves have edges. **No live model has driven either example
    runtime from this environment** — the LangGraph and Pydantic AI
    examples were exercised with scripted models, so the first real
    provider is unverified, and the rules path is what makes that safe.
    A runtime may call at most eight tools for one sentence, may never
    delete, and cannot approve or publish; its closing line is model
    text and is labelled as such. The MCP server is **stdio and local
    mode only** — no HTTP transport, no authentication, no resources or
    prompts — so a hosted deployment has no MCP surface. The frameworks
    are not in `requirements.txt` and CI does not install them; their
    tests skip there, and the versions verified are the ones in the
    ADR's table.
20. The Overview and Datasets views (ADR 0023) read existing endpoints
    and nothing more. The Overview's counts cover the 50 most recent
    analyses that `GET /api/runs` returns, and the view says so when
    the list is full; the Datasets view lists the 50 most recent
    datasets. Hash addresses now restore these views and an individual
    run (ADR 0029); browser back preserves the destination. On a phone the header has
    room for only the first letters of the agent's name.
21. Column mapping (ADR 0025) gives each column one role and analyses
    one measure, broken down by at most one dimension. The other
    measures are drivers, not subjects. There is no week grain, no
    fiscal year, no derived or computed column, and no unit per
    measure. A decimal comma is refused rather than read, and
    two-digit years follow the POSIX rule, so `70` is 1970. The
    suggestion reads an even sample of 10,000 rows of a larger table,
    while saving checks every row. A mapping belongs to one dataset:
    a changed file is new content, so it starts unmapped. Pasted CSV
    and the sample always use automatic detection. Unmapped data is
    still typed from column names, and its periods still sort as text.
22. Uneven periods are read per record (ADR 0026) only in the
    descriptive stage: its headline and a limitation claim give the
    per-record change when the quietest period holds under three
    quarters of the busiest's records. The segment, diagnostic,
    predictive and prescriptive stages still work on totals, so a
    forecast follows the record count, and "protect the leading group"
    can name the group with the most records rather than the largest
    loss per record. The dashboards skill shows per-record charts beside
    the totals; the app's report does not yet.
23. The agent team (`docs/AGENT_TEAM.md`) is tooling for this
    repository and its deliverables, not part of the app.
    - **Local models:** the free models behind `scripts/consult.py` are
      tested only against a stub server. This environment cannot
      download them, so no local model has answered a request here.
    - **Reviewers:** they are Claude subagents. Their findings are
      checked by recomputation before they are acted on, but a reviewer
      can miss what it was not asked about.
    - **Scores:** the loop's percentage counts gates, not findings.
    - **Claude Dashboards:** this is a hosted claude.ai feature. The
      skill reaches it only in a claude.ai session, and elsewhere writes
      an offline page. A new agent file loads at the next session start.
24. Views load on demand (ADR 0028). A reader who goes offline before
    the idle prefetch finishes, or whose browser asks to save data, can
    reach a view whose chunk was never fetched. That view says it could
    not be shown and offers a reload, which works once the reader is
    back online. The split did not make today's app measurably faster:
    Lighthouse mobile scored 98 against 99 before, with the same largest
    paint (2.13 s). What it saves is the unused script, which halved.
    Both dictionaries still ship on the first load.
25. Several datasets per run (ADR 0030) are joined, not stacked: up to
    four lookups, each on one to three key columns, onto one main
    dataset of the same owner. Keys match as trimmed text, as numbers
    when the main key is numeric, or as periods when it is the mapped
    date; there is no case-insensitive or fuzzy matching, so `north`
    and `North` do not match and the coverage figure is how the owner
    finds out. A lookup whose key repeats is refused rather than
    aggregated. The stages before cleaning (contract, profiling,
    quality, privacy) describe the main dataset only; joined datasets
    are screened for personal data by the merge stage itself.
26. A run's cleaned table (ADR 0031) downloads as CSV only, not Excel or
    Parquet, and is read-only. Its query language is deliberately small:
    named aggregates, eleven filter operators, at most two groupings and
    no expressions or joins at query time. A table is parsed into memory
    on first use and three are kept, so the first question asked of a
    50,000-row run is slower than the ones after it, and a server with
    several processes parses once per process.
27. Dashboards (ADR 0032) are one run's table, read-only, with a fixed
    set of pages chosen from its fields: no saved layouts, no choice of
    chart per page and no cross-filtering by dragging. The relationship
    page reads an even sample of at most 500 records, and a filter list
    offers a column only when it has at most 200 values, so an ID or
    free-text column cannot be filtered from the bar.
28. The modelling stages (ADR 0033) are four fixed, standard-library
    models: least squares, naive Bayes, k-means and an additive trend
    and season. There are no trees, ensembles or tuning, and nothing
    beyond the documented settings. The models are associations, not
    causes. A model cannot know which inputs were recorded after the
    outcome, so an input like that makes it look better than it is; every
    model says so, but none can check it. Fewer than 30 records, or fewer
    than three seasons for the seasonal forecast, is reported as a
    limitation and shows no card.
29. Live sources (ADR 0034) fetch public files over https only: no
    credentials, databases or APIs that need a key, and no proxy, so a
    server that reaches the internet only through one cannot refresh.
    Each refresh is a whole snapshot of at most 4 MB; ten sources per
    account, and "Refresh now" once a minute per source. Addresses that
    carry a credential in their query are refused. The cap of five event
    streams per owner is per server process. Scheduled refreshes need the
    background worker
    (`python scripts/worker.py`); a serverless deployment refreshes only
    when someone presses **Refresh now**. The event stream ends every 55
    seconds and the page reconnects, so a hosting platform that limits a
    request's length is fine; one that buffers responses delays events
    until the stream ends. A connector's error is stored in the
    language it was created in.
