# UI generation prompt — code-first tools

There are two prompts in this repository, for two different jobs:

| Use | File |
| --- | --- |
| Mockups and visual exploration (Figma Make, Galileo, Uizard) | `UI_GENERATION_PROMPT.md` |
| **Working React that connects to the real API** (v0, Lovable, Bolt, Subframe, Magic Patterns, and similar) | **this file** |

A code-first tool does not need adjectives; it needs the contract. This
prompt carries the actual API surface, the actual TypeScript types, the
actual design tokens, and the actual state machine, so the generated
interface can be pointed at the running backend instead of being a
beautiful thing full of `lorem ipsum` and invented numbers.

**How to use it:** paste everything below the rule. Then ask for one
screen at a time — most tools produce markedly better output for
"build §7.3 Runs" than for "build the app". If the tool accepts file
attachments, attach `frontend/src/shared/types.ts` and
`frontend/src/shared/styles/tokens.css` instead of relying on §4 and §5.

---

Build the interface for **Agentic OS**, an existing product with a
working, tested backend. Do not design new features, invent data, or add
controls the API below cannot serve. Every endpoint, type, and token here
is real.

## 1. What it does

A person states a business goal in plain language and uploads a CSV. A
governed pipeline of specialist agents turns it into a decision: four
analytics reports and a recommendation, where **every claim links to the
calculation behind it**, and **nothing is published without human
approval**. There is also a conversational assistant with durable memory,
sharing the same shell.

## 2. Who it is for

A business analyst or manager who will be asked "where did that number
come from?" in a meeting and must answer in one tap. Numerate, not a
statistician, frequently on a phone, accountable for the claim.

## 3. Three product laws the UI must obey

1. **The answer precedes the working.** Every analysis leads with one
   plain sentence. The method is reachable, never in the way. No
   statistical vocabulary in any headline — "Revenue is up 45% over the
   period", never "the mean increased by 2.3 standard deviations". The
   backend *fails validation* if a headline contains jargon, so the UI
   must not reintroduce it in labels either.
2. **Uncertainty is displayed, not hidden.** A forecast carries the error
   measured by backtesting. With too little history the API returns no
   forecast and says why — design that state as confidently as the happy
   path, because it appears whenever a dataset has fewer than four
   periods.
3. **Approval is a moment.** Publishing is server-gated and bound to a
   content hash. The approval card names action, target, risk, impact,
   and reversibility, and offers exactly two choices.

## 4. Design tokens (verbatim — these are the product's real values)

```json
{
  "color": {
    "light": {
      "bg": "#f7f8fc", "surface": "#ffffff", "surface-sunken": "#e9ecf5",
      "border": "#dde2ee", "border-strong": "#c3cadd",
      "text": "#14161f", "text-muted": "#4c5468", "text-faint": "#5c647a",
      "accent": "#5646e0", "accent-solid": "#5b4bf0",
      "accent-solid-hover": "#4a39e2", "accent-soft": "#eceafe",
      "on-accent": "#ffffff",
      "success": "#0f7a55", "warning": "#8a6100", "danger": "#b3323f"
    },
    "dark": {
      "bg": "#0b1020", "surface": "#111827", "surface-raised": "#18213a",
      "surface-sunken": "#070b16", "border": "#232c42",
      "border-strong": "#35415f",
      "text": "#f0f2fa", "text-muted": "#a7b0c7", "text-faint": "#929cb4",
      "accent": "#9a92ff", "accent-solid": "#5b4bf0",
      "accent-solid-hover": "#6d5dfc", "accent-soft": "#221e4d",
      "on-accent": "#ffffff",
      "success": "#34d399", "warning": "#fbbf24", "danger": "#fb7185"
    }
  },
  "radius": { "s": "8px", "m": "12px", "l": "16px" },
  "space": { "1": "4px", "2": "8px", "3": "12px", "4": "16px", "5": "24px", "6": "32px" },
  "fontSize": { "xs": "0.75rem", "s": "0.8125rem", "m": "0.9375rem",
                "l": "1.0625rem", "xl": "1.5rem", "display": "2rem" },
  "motion": { "fast": "140ms ease", "medium": "220ms ease" }
}
```

Emit these as CSS custom properties on `:root` and `[data-theme='dark']`,
with the dark set repeated under `@media (prefers-color-scheme: dark)`
for the unset "system" case. Dark is the primary aesthetic. System font
stack; monospace only for identifiers, hashes, and report bodies.

## 5. The API you are building against

Base path `/api`, same origin, JSON, bearer token only in hosted mode.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | provider status |
| GET | `/auth/config` | `mode: 'local' \| 'jwt'` — local mode has **no login** |
| GET | `/identity` | current principal, role, permissions |
| POST | `/sessions` | start a conversation → `SessionState` |
| GET/DELETE | `/sessions/{id}` | restore / end |
| POST | `/sessions/{id}/messages` | send a message |
| DELETE | `/sessions/{id}/history` | clear history |
| PUT | `/sessions/{id}/preferences` | `{key, value}` |
| POST/PUT/DELETE | `/sessions/{id}/memory[/{key}]` | add / edit / delete |
| GET | `/sessions/{id}/export` | full JSON export |
| POST | `/runs` | `{goal, dataset_text?, dataset_id?, dataset_name?}` → `RunDetail` |
| GET | `/runs` · `/runs/{id}` | list · detail |
| POST | `/runs/{id}/advance` | execute exactly one pipeline task |
| POST | `/runs/{id}/pause` · `/resume` · `/cancel` | durable, server-side |
| POST | `/runs/{id}/approvals/{approvalId}` | `{decision: 'approve' \| 'reject'}` |
| GET | `/datasets` · `/usage` | stored datasets · quota usage |
| GET | `/vault` · `/vault/note?path=` | published notes |

Status codes that need designed states: **401** (token expired → sign-in),
**404** (also returned for another tenant's resource, deliberately),
**409** (illegal transition, e.g. advancing a run that awaits approval),
**429** (rate limit *or* quota — the message says which and when it
clears; keep working, do not abandon the run).

**Runs advance by polling `advance`.** The client calls it about every
350 ms while the run is active; each call executes one task and returns
the whole updated `RunDetail`. On 429, back off to ~1500 ms and keep
going. If a background worker holds the run, `advance` returns current
state unchanged and the client is effectively a poller — the UI must look
identical either way.

## 6. Types (verbatim from the product)

```ts
type RunState = 'queued' | 'running' | 'awaiting_approval'
  | 'completed' | 'partially_completed' | 'failed' | 'cancelled'

interface RunTask {
  id: string; role: string; title: string
  state: 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped'
       | 'awaiting_approval' | 'cancelled'
  summary: string | null
  quality_checks: Array<{ name: string; passed: boolean; detail: string }>
  claims: Array<{ id: string; text: string; type: string
                  evidence: string[]; status: string }>
}

interface RunApproval {
  id: string; action: string; target: string; risk: string
  impact: string; reversibility: string; state: string
  created_at: string; decided_at: string | null
}

interface ChartSpec {
  id: string; type: 'bar' | 'line'; title: string
  labels: string[]; values: number[]; alt: string
}

interface RunDetail {
  id: string; goal: string; dataset_name: string
  state: RunState; error: string | null
  created_at: string; updated_at: string
  paused: boolean
  tasks: RunTask[]                       // 22 of them, in order
  reports: Array<{ type: 'descriptive' | 'diagnostic' | 'experiment'
                         | 'predictive' | 'prescriptive'
                   question: string; title: string
                   headline: string      // the one sentence that leads the panel
                   content: string }>    // markdown
  approvals: RunApproval[]
  charts: ChartSpec[]
  report: { id: string; name: string; version: number
            content: string; published_path: string | null } | null
}

interface Usage {
  runs_today: { used: number; limit: number; remaining: number; resets_at: string }
  datasets: { used: number; limit: number; remaining: number }
  dataset_bytes: { used: number; limit: number; remaining: number }
  not_tracked: string[]   // render this: it says what is NOT measured
}
```

## 7. Screens

### 7.1 Shell

60px header: mark + wordmark, centred command trigger ("Search or run a
command", `Ctrl K`), status pill (Ready / Working / Offline / Error /
Session ended), theme toggle, help. Desktop ≥1024px: 236px sidebar with
Workspace · Runs · Memory · Activity · Preferences (active item = soft
accent fill + accent left border), footer with New session / End session
and an identity card. ≥1280px: 280px context rail. Below 1024px: bottom
tab bar, session actions in a drawer, 44px minimum targets, no horizontal
scroll at 320px.

### 7.2 Workspace

Greeting hero with suggested actions when empty; then messages with
timestamps, copy on agent replies, auto-scroll that pauses when the
reader scrolls up plus a "Latest" affordance. Composer: Enter sends,
Shift+Enter newlines, a failed message keeps its text and offers Retry.
Command palette on `Ctrl/⌘K` listing `/help`, `/remember`, `/recall`,
`/forget`, `/set`, `/preferences`, `/history`, `/clear`, `/exit`.

### 7.3 Runs — the centre of the product

**Setup:** goal field; dataset as a segmented control (bundled sample /
upload / paste). On file select, show name and row count *before*
starting ("quarterly-sales.csv · 4 data rows"). Limits 2 MB and 50,000
rows; reject oversize client-side with the actual size.

**Pipeline:** 22 task rows with state marks and summaries filling in
live — design for that length, not for five. The panel is headed by the
orchestrator, **Hermes**, which sequences the stages, holds the approval
gate and recovers an interrupted run; it analyses nothing itself, and no
task row belongs to it. Pause / Resume / Cancel — all server-side and
durable, so reflect `paused` from the response rather than local state.

**The four analytics agents** are the product's spine. Real headlines
they emit, for sizing your layout:

- Descriptive — *What happened?* — "Revenue is up 45% over the period, at 3,583,440 in total. "North" is the biggest region."
- Diagnostic — *Why did it happen?* — "The movement is concentrated in "North", which accounts for 54% of the change. It moves closely with units, which is where to look first."
- Predictive — *What will happen?* — "We expect revenue of about 361,505 in 2026-01, down 1% on the latest period — this method has been off by about 6% when tested on past data."
- Prescriptive — *What should I do?* — "We recommend: Protect the leading region: "North". It is worth about 193,506 in revenue — more than any other option we compared."

They are a ladder (each consumes the one before), not four peers — make
the progression legible.

**Reports:** a tabbed region, one tab per type showing the type name and
its question. Panel = headline callout, then markdown body, then a
"How each figure was calculated" table. Below, the comprehensive report
containing all four.

**Tabs must implement the full WAI-ARIA pattern**: roving tabindex (the
tablist is one tab stop), Left/Right with wrap, Home/End, selection
follows focus. The report body scrolls, so it needs `tabindex="0"` and an
accessible name — a scrollable region no keyboard can reach is a wall.

**Charts** (zero-based axes, alt text on each): total by segment (bar);
measure over time (line); change by segment with negatives below the axis
(bar); history + forecast on one axis, where the projected portion is
visually distinct from measured history. That last distinction is the
point of the chart, not a flourish.

**Approval card:** warning-outlined, "Approval required", rows for
Action / Target / Risk / Impact / Reversibility, then Reject and
"Approve and publish". After approval, show the published path.

### 7.4 Memory · 7.5 Activity · 7.6 Preferences

**Memory:** searchable, category-filterable list (General, Profile, Work,
Projects, Preferences), each entry with text, category chip, updated
date, in-place edit, delete. A Data controls card: Export my data, Clear
history, Delete all memory — each confirmed, naming what is lost.

**Activity:** timestamped real events, filterable System / Memory /
Preferences / Errors; a Session health card; and a **Usage card** showing
each allowance as a meter (`role="meter"` with aria-valuenow/min/max),
amber past 90%, plus a line naming what is *not* measured from
`usage.not_tracked`.

**Preferences:** tone (Friendly / Concise / Formal), display name,
language label, history recording; separate Interface card for theme
(Dark / Light / System) and reduced motion.

### 7.7 Sign-in — hosted mode only

One centred card, one provider button. When `auth/config.mode === 'local'`
there is no sign-in at all. Do not render a login for local mode.

## 8. States, required everywhere

Loading (skeletons shaped like the content), empty (says what will appear
and offers the action that creates it), error (what failed + retry),
offline (banner, queued action), success. Rate-limited: "Slowing down to
stay within the request limit…" while continuing.

## 9. Accessibility — non-negotiable

WCAG 2.2 AA in both themes. Visible focus ring on every control; skip
link to the composer; dialogs trap focus and close on Escape; polite live
regions for status; alt text on every chart; colour never the sole
carrier of meaning. `prefers-reduced-motion` removes transforms and
fades rather than shortening them.

## 10. Voice

Plain, specific, unhedged. Say what happened and what it means. No
"Oops!", no blaming the user, no dressing an absence as a feature. When
something cannot be done, one sentence saying so plus the nearest thing
that can.

## 11. Do not

Do not invent KPI tiles, sample dashboards, or numbers — every figure
comes from the API. Do not add controls the endpoint list cannot serve.
No AI sparkle animations, no glassmorphism, no gradient washes, no
stock photography, no decorative charts. No dark patterns near the
destructive actions or the approval gate. If a control would do nothing,
leave it out — a dead control is worse than a missing one.

## 12. Stack

React 19 + TypeScript (strict) + Vite. CSS custom properties from §4 —
no CSS framework, no component library, no state library, no router
(five panels toggle inside one shell). Inline SVG icons; system fonts;
no external network requests of any kind. Charts hand-rolled as inline
SVG from `ChartSpec` — no charting dependency.

---

Deliver, in this order: the shell; Runs (setup → running → four report
tabs → approval → published); Workspace with its empty state; Memory;
Activity including the usage meters; Preferences. Dark and light, at
1440 / 768 / 390px.
