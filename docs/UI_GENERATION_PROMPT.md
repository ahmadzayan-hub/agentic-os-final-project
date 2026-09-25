# UI generation prompt — Agentic OS

Paste everything below the line into a design-generation tool (v0, Figma
Make, Lovable, Galileo, Uizard, or similar). It is self-contained: it
does not assume the tool can see this repository.

**Which prompt?** This one is for tools that draw (Figma Make, Galileo,
Uizard) — it describes the interface in prose. For tools that generate
working React (v0, Lovable, Bolt, Subframe), use
`UI_PROMPT_CODEGEN.md` instead: it carries the real API contract,
TypeScript types, and design tokens as JSON, so the output can be wired
to the running backend.

Two notes before you paste:

- **Trim to fit.** Some tools cap prompt length. Sections 1–5 are the
  irreducible core; 6–9 improve fidelity; drop from the bottom if needed.
- **One screen at a time works better** than "build the whole app" in most
  tools. Paste sections 1–5 as context, then ask for one screen from
  section 5 per generation.

---

You are designing the interface for **Agentic OS**, a working product. Do
not invent features: everything below already exists and is backed by a
tested backend. Your job is the visual and interaction design, not the
scope.

## 1. What the product is

A business-analytics workspace where a person states a goal in plain
language and a governed pipeline of specialist agents turns a CSV into a
decision. It has two halves that share one screen shell:

1. **A conversational assistant** with durable memory (it remembers facts
   between sessions), preferences, and a command surface.
2. **Analytics runs**: a goal plus a dataset becomes a sequence of agent
   stages that produce four reports and require the human to approve
   before anything is published.

"Operating system" here means an assistant environment, not a desktop OS.

## 2. Who uses it

A business analyst or manager who needs an answer they can defend in a
meeting. They are numerate but not statisticians, they are often on a
phone, and they are accountable for what the analysis claims. Design for
someone who will be asked "where did that number come from?" and must be
able to answer in one tap.

## 3. The idea the design must carry

**Every claim traces to a calculation, and the machine never publishes
without permission.** Three consequences that are design problems, not
copy problems:

- **The answer comes before the working.** Each analysis leads with one
  plain sentence — "Revenue is up 45% over the period, at 3,583,440 in
  total" — and the method sits below it, reachable but not in the way.
  Never surface statistical vocabulary in a headline. "Costs are rising",
  never "the mean increased by 2.3 standard deviations".
- **Uncertainty is shown, not hidden.** A forecast displays the error
  measured when the method was tested against past data. When there is
  too little history, the interface says so instead of showing a number.
  Design a confident way to say "we don't know yet".
- **Approval is a moment, not a checkbox.** Publishing is gated. The
  approval card must feel consequential: it names the action, the target,
  the risk level, the impact, and whether it can be undone.

## 4. Design system (use these exact values)

Dark is the primary aesthetic; light is a first-class variant, not an
afterthought. Every text/background pairing must reach WCAG 2.2 AA
(4.5:1 for body text, 3:1 for large text and UI boundaries).

**Dark palette** — background `#0b1020`, surface `#111827`, raised
surface `#18213a`, sunken `#070b16`, border `#232c42`, strong border
`#35415f`, text `#f0f2fa`, muted text `#a7b0c7`, faint text `#929cb4`.
Accent for text and outlines `#9a92ff`; filled controls `#5b4bf0` with
hover `#6d5dfc`; soft accent fill `#221e4d`; text on accent `#ffffff`.
Success `#34d399`, warning `#fbbf24`, danger `#fb7185`.

**Light palette** — background `#f7f8fc`, surface `#ffffff`, sunken
`#e9ecf5`, border `#dde2ee`, strong border `#c3cadd`, text `#14161f`,
muted `#4c5468`, faint `#5c647a`. Accent `#5646e0`, filled `#5b4bf0`,
soft `#eceafe`. Success `#0f7a55`, warning `#8a6100`, danger `#b3323f`.

**Type** — system sans stack; monospace only for identifiers, hashes,
and report bodies. Scale: 12px, 13px, 15px, 17px, 24px, 32px. Body is
15px. Never use monospace for prose a business reader must scan.

**Spacing** — strict 8-point grid: 4, 8, 12, 16, 24, 32.

**Shape** — radii 8px (controls), 12px (cards), 16px (panels).

**Elevation** — near-flat. Dark: `0 1px 2px rgb(0 0 0 / .4)`,
`0 4px 14px rgb(0 0 0 / .45)`, `0 18px 48px rgb(0 0 0 / .6)`. Shadow is
for layering, never decoration.

**Motion** — 140ms for state changes, 220ms for entrances, ease. Respect
`prefers-reduced-motion`: no transforms, no fades, instant states.

## 5. Screens to design

### 5.1 Application shell

A 60px header: product mark and name at the left; a centred search field
reading "Search or run a command" with a `Ctrl K` chip; at the right a
live status pill (Ready / Working / Offline / Error / Session ended), a
theme toggle, and help.

Below it, on desktop (≥1024px): a 236px left sidebar with WORKSPACE as a
section label and five destinations — Workspace, Runs, Memory, Activity,
Preferences. The active item gets a soft accent fill, an accent left
border, and accent text. Memory carries a count badge. The sidebar
footer holds "New session", "End session", and an identity card showing
the product name and `v1.0.0 · local` in monospace.

On ≥1280px a 280px right rail shows session facts and recent activity.

Below 1024px the sidebar becomes a **bottom tab bar** with the same five
destinations, and session actions move into a drawer opened from a menu
button. Minimum touch target 44px. The layout must not scroll
horizontally at 320px.

### 5.2 Workspace (conversation)

Empty state: a large greeting hero ("Good afternoon" plus the person's
name if set) with three or four suggested actions as cards.

In conversation: user and agent messages with timestamps, a copy button
on agent replies, auto-scroll that pauses when the reader scrolls up,
and a "Latest" button to jump back down. The composer is a growing
textarea; Enter sends, Shift+Enter breaks the line. A failed message
keeps its text and offers Retry — never silently discards.

Design the command palette too: opened with Ctrl/⌘K, a searchable list
of `/help`, `/remember`, `/recall`, `/forget`, `/set`, `/preferences`,
`/history`, `/clear`, `/exit`, each with a one-line description; picking
one inserts it into the composer.

### 5.3 Runs — the centrepiece

**Setup**: a goal field (pre-filled with a sensible example), and a
dataset choice as a segmented control — bundled sample / upload a CSV /
paste CSV. When a file is chosen, show its name and row count *before*
the run starts ("quarterly-sales.csv · 4 data rows"). Limits are 2 MB
and 50,000 rows; an oversize file is rejected with its actual size.

**Running**: a "Specialist pipeline" list, one row per agent, each with a
state mark (pending · running · succeeded · failed · skipped) and a
one-line summary that fills in as it completes. **Twenty-two rows**, so the
list needs to stay scannable at that length rather than assuming five:
Planner, Data Source, Data Contract, Data Profiling, Data Quality,
Privacy, Data Cleaning, Metric Governance, Data Preparation, Segment
Concentration, then
the four analytics agents with Experiment and Causal Inference among
them, then Anomaly, Prescriptive's Sensitivity check, Visualization,
Provenance, Validation, Reporting, and the gated Publish. The panel names its orchestrator — **Hermes** — which sequences
them, holds the approval gate, and analyses nothing itself. Controls:
Pause, Resume, Cancel.

**The four analytics agents are the heart of it.** Each answers one
question and writes its own report:

| Agent | Question | Example headline it produces |
| --- | --- | --- |
| Descriptive | What happened? | "Revenue is up 45% over the period, at 3,583,440 in total. 'North' is the biggest region." |
| Diagnostic | Why did it happen? | "The movement is concentrated in 'North', which accounts for 54% of the change. It moves closely with units, which is where to look first." |
| Predictive | What will happen? | "We expect revenue of about 361,505 in 2026-01, down 1% on the latest period — this method has been off by about 6% when tested on past data." |
| Prescriptive | What should I do? | "We recommend: Protect the leading region: 'North'. It is worth about 193,506 in revenue — more than any other option we compared." |

They form a ladder — each uses the one before it — and the design should
make that progression legible rather than presenting four peers.

**Reports**: five tabs — one per analytics type, plus **Experiment**
("Can we claim a cause?") sitting between Diagnostic and Predictive.
Each tab shows its name and its question. The selected panel leads with
the headline as a prominent callout, then the body, then a "How each
figure was calculated" table (figure · value · method). Below them sits
the comprehensive report containing all five.

The Experiment tab is the one that most often says no — "no cause can be
claimed from this data" — followed by the size of experiment that would
settle it. Design it as a first-class answer, not as an error state: a
refusal with a costed alternative is the most useful thing on the page,
and styling it like a warning would teach people to skip it.

**Charts** (four, all zero-based axes, all with alt text): total by
segment (bar); the measure over time (line); **change by segment** with
negative bars below the axis, showing who moved the number; and
**history plus forecast** on one axis, where the projected portion must
be visually distinct from measured history — this distinction is the
whole point of the chart.

**Approval card**: outlined in warning colour, headed "Approval
required", listing Action, Target, Risk (high), Impact, Reversibility,
with "Reject" and "Approve and publish". After approval, show the
published path with a success mark.

### 5.4 Memory

A searchable, category-filterable list. Each entry: its text, a category
chip (General, Profile, Work, Projects, Preferences), a last-updated
date, and edit and delete actions. Editing happens in place. A "Data
controls" card offers Export my data, Clear conversation history, and
Delete all memory. Every destructive action needs confirmation naming
exactly what will be lost.

### 5.5 Activity

A timestamped timeline of real events — session started or restored,
memory saved, preference changed, request failed, connection changed —
filterable by System / Memory / Preferences / Errors. Alongside it, a
"Session health" card: connection state, whether memory persistence is
active, entry counts, time of last successful response.

### 5.6 Preferences

Response tone (Friendly / Concise / Formal), the person's name, language
label, and a history-recording switch. A separate "Interface" card holds
theme (Dark / Light / System) and a reduced-motion switch.

### 5.7 Sign-in (hosted mode only)

A single centred card: product mark, one line explaining that this
deployment requires sign-in, and a provider button. Local mode has no
sign-in at all — do not design a fake login for it.

## 6. States you must design (not optional)

For every view: **loading** (skeletons shaped like the content, never a
spinner alone), **empty** (explains what will appear and offers the
action that creates it), **error** (says what failed and offers retry),
**offline** (a clear banner and a queued-action affordance), and
**success**. A rate-limited request shows "Slowing down to stay within
the request limit…" and keeps working rather than failing.

## 7. Accessibility requirements

Full keyboard operation with a visible focus ring on every control. A
skip link to the composer. Dialogs trap focus and close on Escape. The
report tabs follow the tab/tabpanel pattern with arrow-key movement.
Status changes are announced politely to screen readers. Charts carry
descriptive alt text, and colour is never the only carrier of meaning —
pair it with a mark or a label. Contrast must hold in both themes.

## 8. Voice

Plain, specific, unhedged. Say what happened and what it means. Never
"Oops!", never blame the user, never dress an absence up as a feature.
When the system cannot do something, it says so in one sentence and
offers the nearest thing it can do. Numbers appear with their units and
their source.

## 9. What NOT to design

No placeholder controls for features that do not exist. No fake AI
sparkle animations. No dashboards of invented KPIs. No dark patterns
around the destructive actions or the approval gate. No stock-photo
imagery. No gradients or glassmorphism beyond the single accent glow on
the product mark. If a control would not do anything, leave it out.

---

Deliver: the shell, then Runs (setup / running / four report tabs /
approval / published), Workspace with its empty state, Memory, Activity,
and Preferences — each in dark and light, at 1440px, 768px, and 390px.
