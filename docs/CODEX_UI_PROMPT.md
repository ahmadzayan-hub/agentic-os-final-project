# Codex prompt — design and build the agentic interface

This repository now has three interface prompts, for three kinds of tool:

| Tool | File |
| --- | --- |
| Drawing tools (Figma Make, Galileo, Uizard) | `UI_GENERATION_PROMPT.md` |
| Code generators that cannot see the repository (v0, Lovable, Bolt) | `UI_PROMPT_CODEGEN.md` |
| **A coding agent working inside the repository (OpenAI Codex, cloud task or CLI)** | **this file** |

**How to use it.** Start a Codex task at the repository root on the working branch. Paste the *Shared brief* below, then one *Task* from section 13. Run one task at a time and review each before starting the next. Codex reads `AGENTS.md` files on its own. This repository keeps its rules in `CLAUDE.md`, so the brief tells Codex to read that file first.

**What it is based on.** The patterns in section 5 come from a survey of agentic interface projects and specifications on GitHub, made on 16 October 2026. Section 14 lists the sources. These projects change monthly, so check the versions before relying on a detail.

---

## Shared brief

### 1. Role

You are a senior product designer and React engineer. You design by building: every design decision lands as working, tested code in this repository's React app, or as a written specification when the backend for it does not exist yet. You do not change what the backend does.

### 2. Goal

Make delegated, governed analytics work **legible and controllable**. At any moment a person should be able to see:

1. what the agents plan to do;
2. what they are doing now;
3. what they found, and why it is true;
4. what is waiting for a human decision;

and pause, cancel, approve or reject without hunting for the control. The product today is usable but reads as "a chat plus a run page". The goal is an agentic workspace built on the same backend.

### 3. Read these first, in this order

Where these files and this prompt disagree, the files win.

1. `CLAUDE.md` and `brain/Soul.md`: the rules. They override everything below.
2. `docs/UI_PLAN.md`, `docs/adr/0023-the-analytics-workspace-interface.md`, `docs/adr/0024-the-dataset-api.md`.
3. `design-system/agentic-os/MASTER.md`, starting with its *Agentic OS decisions* section, and `design-system/agentic-os/pages/dashboard.md`.
4. `frontend/src/shared/types.ts`, `frontend/src/shared/api.ts`, `frontend/src/shared/styles/tokens.css`, `frontend/src/i18n/en.ts`.
5. `frontend/src/app/App.tsx`, every folder in `frontend/src/features/`, and `frontend/e2e/`.
6. `project-progress.md` (what is planned and in what order) and `docs/KNOWN_LIMITATIONS.md` (what is not done).

### 4. The product, briefly

Agentic OS is a governed business-analytics assistant. A person gives it a goal and a dataset. **Hermes**, the orchestrator, runs **21 specialist stages** in a fixed order: planning, ingestion, the data contract, profiling, quality, privacy, cleaning, metric governance, preparation, segments, the four analytics types (descriptive, diagnostic, predictive, prescriptive), causal inference, anomalies, sensitivity, visuals, lineage, validation and reporting. A **22nd task is the publish gate**. Every claim in a report cites the calculations behind it. Nothing is published until a person approves the exact artifact, whose SHA-256 the approval is bound to. Reports are written in English or Arabic, chosen when the run starts.

Who uses it:

- An analyst who runs analyses and reads the evidence.
- A manager who approves publication and reads headlines.
- A teammate on a phone who checks status between meetings.

Every one of them may be reading in Arabic, right to left.

**What exists**, from `server/app.py` (do not invent beyond this):

| Area | Endpoints | Notes |
| --- | --- | --- |
| Runs | `POST /api/runs`, `GET /api/runs`, `GET /api/runs/{id}`, `POST …/advance`, `…/pause`, `…/resume`, `…/cancel`, `POST …/approvals/{approval_id}` | No streaming. The client advances a run one stage per request (350 ms ticks, slower on `429`). `RunDetail` holds tasks with states, quality checks and claims; reports with a plain-language `headline`; charts; approvals with risk, impact and reversibility |
| Datasets | `POST /api/datasets` (the file is the body), `GET /api/datasets` | CSV, TSV, XLSX, JSON, JSON Lines. The upload response includes `columns`, five `preview` rows, `warnings` and `sheets` |
| Pipelines | `GET /api/pipelines` | Custom stages and profiles (ADR 0020) |
| Assistant | `POST /api/sessions/{id}/messages` and the session routes | A rules-based vocabulary of ten actions, such as remember, recall, set a preference, start an analysis, report a run's status and explain a report. Replies carry `source`, `action`, `result.run_id`, and for an agent runtime the `steps` (tool, arguments, ok, text) |
| Usage, identity | `GET /api/usage`, `GET /api/identity`, `GET /api/auth/config` | Quotas per owner; roles owner, admin, analyst, viewer and auditor |
| Vault | `GET /api/vault`, `GET /api/vault/note` | Published reports |

Already built: the Overview (key figures, latest findings, approval queue), Datasets (upload of each format, stored-dataset picker), Runs (form, stage list, approval card, reports, SVG charts with data tables), Assistant chat, Memory, Activity and Preferences. They are bilingual, axe-clean, and have a phone bar of five places with *More*.

### 5. Agentic interfaces in October 2026, and what Agentic OS takes from them

The projects surveyed agree on one thing: **chat alone is not an interface for delegated work.** People need to see the plan, approve risky steps, watch progress and audit what happened. The table says what each pattern becomes here.

| Pattern in the field | Seen in | What it becomes in Agentic OS |
| --- | --- | --- |
| **An event stream for agent activity**: run lifecycle, steps, messages, tool calls, state snapshots and deltas, and an *interrupt* that pauses a run for a human | AG-UI (`RunStarted`, `StepStarted`/`StepFinished`, `ToolCall*`, `StateSnapshot`/`StateDelta`, `ActivitySnapshot`/`ActivityDelta`; an interrupt is a `RunFinished` whose outcome is `interrupt`, resumed by a new run) | A **client-side adapter** that turns successive `RunDetail` snapshots into events with this vocabulary, feeding one reducer that every run view renders from. The approval gate is the interrupt. If the server ever streams, only the transport changes. Do not add server endpoints |
| **Plan before execution**: show the steps and let the person approve them before work starts | Coding agents' plan modes; agent UX guides | Before *Start*, show the run's plan: the 22 tasks grouped into four bands (data, analytics, assurance, publish), including the custom stages the chosen profile adds |
| **Live activity timeline** with step states, and always-visible pause and cancel | Agent UX guides; AG-UI steps | The run cockpit's timeline. Bands collapse to a progress count; the current stage is announced politely; pause and cancel stay visible in a sticky header |
| **Tiered permission gates**, without approval fatigue | Agent UX guides; AI SDK `needsApproval`; workflow approval cards | Gate only what the server gates, which today is publishing. The approval card shows risk, impact, reversibility and target, and states that approval binds to the artifact's hash. An **approval inbox** collects every waiting run |
| **Receipts**: show the sources and evidence behind an answer | Agent UX guides; citation components | Every claim opens a **"Why is this true?"** panel listing the calculations it cites, with their methods and values. This is the product's strongest idea; make it effortless to reach |
| **Generative UI from a fixed catalog**: the agent picks pre-approved components and supplies data; it never writes markup | A2UI (v0.9.1, a declarative JSON catalog); assistant-ui's allowlisted JSON specs | The assistant's replies render as **typed cards from a fixed catalog**, keyed by `action` and `result`: a run card, a finding card, a memory card, a preference change. A model's text is shown as text, never as HTML |
| **Tool-call transparency** | AG-UI tool-call events; chat UI kits | The `steps` of an agent-runtime reply become collapsible tool cards showing the tool name, its arguments, whether it was allowed, and its result |
| **Embedded app UIs from tools** | MCP Apps (stable spec 2026-01-26: `ui://` resources rendered in sandboxed iframes) | Out of scope. The MCP server here is stdio-only (ADR 0021). Note it as future work only |

**What Agentic OS deliberately does not take:**

- **A reasoning or "thinking" display.** The product never exposes chain of thought (`brain/Soul.md`). Show *what* happened, not hidden reasoning.
- **Chat as the only surface.** The assistant is one door; the cockpit and the inbox are where work is supervised.
- **A UI kit dependency.** That covers CopilotKit, assistant-ui, AI Elements, shadcn/ui and Tailwind. ADR 0023 keeps the app free of UI libraries and third-party requests, and AI Elements itself announces deprecation at the end of November 2026 in favour of shadcn/ui. Take the patterns, not the packages. If you believe a library pays for itself, write it up as a proposal ADR with its measured bundle cost, and build nothing on it until the proposal is accepted.

### 6. Design direction

- **Use design system v2 as it stands.** Its tokens are in `tokens.css`. Navy and blue mark actions; amber marks only what waits on a person; there are no gradients, glow or glass. Body text is Fira Sans and figures are Fira Code with tabular numerals; Arabic uses the system stack. Do not introduce raw colours: every colour lives in `tokens.css`.
- **Feel:** a calm control room. The interface is dense where people read numbers and spacious where they decide. The approval card is the most deliberate object on the screen.
- **Motion:** CSS and React View Transitions only, under 200 ms. Everything still works and reads correctly with `prefers-reduced-motion`.
- **Bidirectional by construction:** use logical properties everywhere. Icons that point (arrows, chevrons) mirror in Arabic. Numbers keep Western digits in both languages (the `ar-u-nu-latn` locale). Text a person or a model wrote is wrapped with `dir="auto"`.

### 7. Screens

For each screen, design every state: loading (a skeleton), empty (with a next step), error (with a retry), offline, and the phone layout at 320 px with no sideways scroll.

1. **Run cockpit** (reworks *Runs*; the centre of this work).
    - A sticky header: goal, dataset, state, report language, and pause, resume and cancel.
    - When the run waits, the approval card comes first.
    - Then four headline cards, one per analytics type, with their claims.
    - Then the timeline in four bands, the charts with their tables, and the full report.
    - The "Why is this true?" panel opens from any claim.
    - Desktop: the timeline as a side column. Phone: one column, with the timeline collapsed to a progress bar.
2. **Plan preview** (in the run form): the stage list grouped by band, updated when the profile changes, shown before *Start*.
3. **Approval inbox** (new view, under *Analyse*).
    - Every run in `awaiting_approval`, oldest first, from `GET /api/runs`.
    - Each opens its approval card in place; the decision calls the existing endpoint.
    - Use optimistic UI, rolled back with an explanation if the server refuses.
4. **Overview** (exists): wire it to the inbox and the cockpit. Keep its counting rules.
5. **Assistant** (exists): typed result cards from the catalog in section 5 and tool cards for runtime steps. A run started from chat appears as a live run card that links to the cockpit.
6. **Datasets** (exists).
    - After an upload, show the server's `preview` and `columns` as a small table, with the `warnings`.
    - For a workbook, list its `sheets`. Choosing another sheet would need the API's `sheet` parameter; design it, and note that the interface does not offer it yet.
7. **Dashboards** (specification only).
    - Pages, global filters as wrapping chips, drill to rows, and a table under every chart, as in `pages/dashboard.md`.
    - The data needs milestones A4 and A5, which do not exist, so do not build it with invented numbers.
8. **Memory, Activity, Preferences**: restyle to the new layout only.

**Navigation.** Keep the grouped sidebar and the five-place phone bar. Add deep links with a small hash-based hook: `#/overview`, `#/runs/{id}`, `#/approvals`, `#/datasets` (UI_PLAN phase 2). No router library. The browser's back button must work.

### 8. React and front-end techniques

The repository pins React `^19.2.8`; the current release is 19.3.1. Upgrading within 19.x is allowed, in a commit of its own, with the full suite green.

- **One run store, fed by events.**
    - The adapter from section 5 produces events.
    - A reducer folds them into view state.
    - `useSyncExternalStore` exposes the state, and components subscribe to slices of it.
    - Polling lives in one place; use `useEffectEvent` (19.2) for its callbacks so the timer never restarts on re-render.
- **Optimistic actions:** `useOptimistic` for approve, reject, pause and resume. `useActionState` for forms: the run form and dataset upload.
- **Data loading:** `use()` with Suspense boundaries, and an error boundary per view, so one failed request never blanks the shell.
- **Keep work alive:** `<Activity>` (19.2) keeps the cockpit and the chat mounted while hidden, instead of unmounting and refetching on every tab switch.
- **Transitions:** `<ViewTransition>` (19.3) for changing views and for list items that change state. Disable it when reduced motion is set.
- **Code-splitting:** done (ADR 0028). Add a new view to `frontend/src/app/lazyViews.tsx`, not as a static import in `App.tsx`. The first load stays under 100 KB gzipped, all scripts under 160 KB and each view's chunk under 30 KB. CSS stays under 10 KB and fonts under 120 KB.
- **CSS:**
    - Container queries for cards that live in both the side column and the main column.
    - `:has()` for state-driven styling.
    - `@starting-style` for entry transitions.
    - `color-mix()` to derive tints from tokens rather than adding colours.
    - Use only features that are Baseline widely available, or ship a fallback.
- **Charts:** hand-drawn SVG with a data table, as the existing charts do (`frontend/src/shared/charts.ts`). No chart library.
- **Live regions:** at most one polite announcement per stage change, and never for every 350 ms tick.

### 9. Non-negotiables

From `CLAUDE.md` and `brain/Soul.md`:

- **Strings:** every user-facing string goes in both `en.ts` and `ar.ts`, with the same placeholders. The i18n tests enforce this.
- **Accessibility:** WCAG 2.2 AA in both languages and both themes. axe must stay clean in every view and dialog. Targets are at least 44 px; focus is visible; there are no keyboard traps, and Escape closes overlays.
- **Network:** no third-party requests from the app (no CDNs, no remote fonts, no analytics) and no secrets anywhere.
- **Data:** raw data never goes to a model. The interface sends datasets only to this app's own API.
- **Honesty:** never fabricate numbers, screenshots, URLs or test counts. A screenshot is a real capture from `frontend/e2e/screenshots.spec.ts`.
- **Backend:** do not change backend behaviour. If an interface need truly requires a backend change, stop and write it up as a proposal ADR at the next free number in `docs/adr/` (0025 is column mapping, A2, 0026 is uneven periods, 0027 is agent measurement, 0028 is views loading on demand and 0029 is the governed run workspace; the next free number is 0030, which A3 has reserved, so a new proposal takes 0031).
- **Git:** no force-push, no history rewriting, no new branches, and no pull request unless the person asks.

### 10. Tests that guard existing behaviour

- **Labels and classes.** End-to-end specs rely on visible labels and class names, for example *Start run*, *Approve and publish*, `.runtask--succeeded`, `.runchart__svg` and `.runreport--full`. Change one only deliberately, and update its spec in the same commit.
- **The shared end-to-end database.** Every spec and both viewports share one database, and datasets are stored once per owner by content. Give each new spec its own data, accept "already stored" where it can happen, and use `exact: true` for short button names that run goals may contain.
- **Screenshots.** The screenshot spec rewrites `docs/screenshots/`. Commit new captures only on purpose.

### 11. How to verify a task

The task is done when all of these pass and every check in the task itself holds:

```bash
npm --prefix frontend ci
npm --prefix frontend run typecheck && npm --prefix frontend test && npm --prefix frontend run build
npm --prefix frontend run e2e          # needs the build; Chromium may need PLAYWRIGHT_EXECUTABLE_PATH
python -m unittest discover tests      # the backend is unchanged and still green
```

Report the real counts these print. Measure the gzipped size of the built JavaScript and CSS, and state it.

### 12. What to hand back after each task

- A summary: what changed, and why.
- The files touched.
- The decisions made, with an ADR when behaviour changed.
- The test counts exactly as run.
- The bundle sizes.
- Real screenshots of the new screens in English and Arabic, desktop and phone.
- Open questions for the person.

---

### 13. Tasks (paste one after the shared brief)

**Task 1. The specification, no code.**

Write `docs/design/AGENTIC_UI_SPEC.md`:

- every screen in section 7, with ASCII wireframes for desktop and phone, in English and Arabic;
- a component inventory, reusing what exists;
- the run event model: the adapter's events, the reducer's state, and a table mapping `RunDetail` fields to events;
- the assistant's card catalog;
- the deep-link scheme;
- any token additions (none, if possible);
- per-screen accessibility notes;
- an execution plan for tasks 2 to 6.

*Done when* every screen has its five states specified, each catalog card names the `RunDetail` or reply fields it shows, and the open questions are listed. No code changes.

**Task 2. The run store and the cockpit.**

Build the adapter, the reducer and the store (section 8), then rebuild *Runs* as the cockpit with the plan preview.

*Done when*:

- unit tests cover the adapter: every state transition, a pause, a cancel, the approval interrupt, and a stage failure;
- the existing runs, keyboard and plugins specs pass, updated only where a label changed on purpose;
- a new spec opens a claim's "Why is this true?" panel and checks that it lists the cited calculations;
- axe is clean in both languages.

**Task 3. The approval inbox.**

Add the inbox view, its place in the sidebar (*Analyse*) and the drawer, and its links from the Overview.

*Done when* an end-to-end test approves one run and rejects another from the inbox, a refused decision rolls back with a message, and the phone bar still holds five places.

**Task 4. The assistant's cards.**

Build the catalog renderer and the tool cards.

*Done when*:

- a chat message that starts a run shows a live run card linking to the cockpit;
- the runtime spec shows tool cards;
- unit tests prove an unknown card type falls back to plain text and that model text is never rendered as HTML.

**Task 5. Dataset preview and deep links.**

Show the upload preview and its warnings, and add the hash deep links with a working back button.

*Done when* a spec uploads the workbook fixture and sees its preview and sheet names, opening `#/runs/{id}` directly loads that run, and the back button returns to the previous view.

**Task 6. The dashboard specification.**

Specify the dashboard against the A4 and A5 milestones in `project-progress.md`: the endpoints it would need, the pages, filters and drill paths, and every state. Specification only.

*Done when* the specification names every field it would need from an API that does not exist yet, and nothing is built with invented data.

---

### 14. Research basis (surveyed 16 October 2026)

- AG-UI protocol, the event types and interrupts: <https://github.com/ag-ui-protocol/ag-ui> (`docs/concepts/events.mdx`)
- A2UI, declarative agent-to-user interfaces with a trusted component catalog, v0.9.1 with 1.0 at release candidate: <https://github.com/google/A2UI>
- MCP Apps, interactive UIs from MCP servers, stable spec 2026-01-26: <https://github.com/modelcontextprotocol/ext-apps>, <https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp>
- CopilotKit's generative-UI examples for AG-UI, A2UI and MCP Apps: <https://github.com/CopilotKit/generative-ui>
- AI Elements, moving to shadcn/ui and deprecated at the end of November 2026: <https://github.com/vercel/ai-elements>
- assistant-ui, generative UI from allowlisted JSON specs: <https://www.assistant-ui.com/docs/tools/generative-ui.md>
- GitHub topic lists: <https://github.com/topics/generative-ui>, <https://github.com/topics/agent-ui>
- React releases: 19.3.0 (9 September 2026: `<ViewTransition>`, Fragment refs) and 19.3.1 (14 October 2026): <https://github.com/facebook/react/releases>
- Agent UX patterns (plans, gates, timelines, receipts), secondary sources: <https://www.setproduct.com/blog/ai-agent-ui-design-patterns>, <https://hatchworks.com/blog/ai-agents/agent-ux-patterns/>
- Codex prompting (goal, context, constraints, done when; `AGENTS.md`): <https://developers.openai.com/codex/learn/best-practices>
