# UI plan: the analytics workspace

How the Agentic OS interface grows from a chat-and-runs app into an analytics workspace: several datasets, analyses, dashboards and findings, in English and Arabic. The visual direction comes from the `ui-ux-pro-max` skill (`.claude/skills/ui-ux-pro-max/`). Its output is persisted in `design-system/agentic-os/MASTER.md`, with this project's overrides on top. The decision is recorded in `docs/adr/0023-the-analytics-workspace-interface.md`.

Phases 0 and 1 below are built. Each later phase waits on the backend milestone it needs (`project-progress.md`, A1 to A7) and ships only when its gate passes.

## 1. Principles

Kept from the existing design brief (`docs/UI_GENERATION_PROMPT.md`), and sharpened:

1. **The answer before the working.** Every screen opens with what a manager needs to decide: a headline, a number, a state. The evidence is one step away, never in front.
2. **Evidence is always reachable.** A figure links to its calculation, a finding to its run, a chart to a table of the same numbers.
3. **Approval is a moment.** Publishing waits for a person, and the screen makes that wait visible: what will be published, at what risk, and whether it can be undone.
4. **Uncertainty is shown, not hidden.** Ranges, provisional labels and "could not be tested" are part of the design, not footnotes.
5. **Two languages, one product.** Arabic is first-class: right-to-left layout through logical properties, its own font stack, Western digits.
6. **Works offline, sends nothing out.** No third-party requests: fonts are bundled, icons are inline SVG, and there are no analytics scripts.

## 2. Who it is for

| Person | Comes to | Leaves with |
| --- | --- | --- |
| Analyst | Load datasets, map columns, run analyses, check the evidence | A validated report, ready for approval |
| Manager or executive | See where things stand and what is waiting for them | A decision: approve, reject or ask |
| Planner or operator | A ranked list of what to act on next | The next action, with its reason |
| Teammate on a phone | A quick check between meetings | The state and the headline |

## 3. Design system v2

The `ui-ux-pro-max` design-system query (an enterprise analytics dashboard; variance 3, motion 3, density 8) recommended:

- **Style:** Minimalism and Swiss: clean, grid-based, high contrast, functional.
- **Palette:** navy and blue data, with an amber highlight.
- **Typography:** Fira Sans, with Fira Code for figures.
- **Spacing:** a dense dashboard scale.

The overrides below make it fit this product, and they win wherever they differ. Every text pairing was verified at 4.5:1 or better, and every control border at 3:1 or better.

### Colour

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--bg` | `#F8FAFC` | `#0B1220` | Page |
| `--surface` | `#FFFFFF` | `#111A2E` | Cards, panels |
| `--surface-raised` | `#FFFFFF` | `#17223A` | Menus, dialogs |
| `--surface-sunken` | `#E9EEF6` | `#070C18` | Wells, inputs, code |
| `--border` | `#DCE3EE` | `#24304A` | Dividers (decorative) |
| `--border-strong` | `#7C8BA1` | `#5B6B8C` | Inputs and controls, 3:1 or better |
| `--text` | `#0F172A` | `#F1F5F9` | Body, 17:1 |
| `--text-muted` | `#475569` | `#A9B6CC` | Secondary, 6.5:1 or better |
| `--text-faint` | `#5B6779` | `#94A3B8` | Metadata, 4.9:1 or better |
| `--accent` | `#1E40AF` | `#8DB0FF` | Links, icons, outlines, focus ring |
| `--accent-solid` | `#1E40AF` | `#2563EB` | Primary buttons (white text: 8.7 and 5.2) |
| `--accent-soft` | `#DBEAFE` | `#16244A` | Selected and active backgrounds |
| `--highlight` | `#B45309` | `#FBBF24` | Attention text: "waiting for you", provisional |
| `--highlight-soft` | `#FEF3C7` | `#2E2208` | Attention backgrounds |
| `--success`, `--warning`, `--danger` | unchanged | unchanged | Semantic states, always paired with a word |

Amber is the highlight, not the primary action. The recommendation put the call to action in amber, which suits a marketing page; in a workspace, the primary action is the calm blue, and amber means "this needs a person".

### Typography

- **Latin:** Fira Sans 400, 500 and 600 for interface text and headings.
- **Figures:** Fira Code 500, with tabular numerals, for KPI values, tables, IDs and code.
- **Arabic:** the existing system stack (Segoe UI, Tahoma, Noto Sans Arabic, …), because Fira has no Arabic letters. Leading 1.65, and no tracking, which would break the joins of a connected script.
- The fonts are bundled from `@fontsource` (Latin subsets only), cached by the service worker, and use `font-display: swap`. There is no Google Fonts request.
- The recommendation set headings in Fira Code. Monospaced headings read as code to a manager, so headings stay in Fira Sans, and Fira Code is kept for numbers.

### Space, shape, motion

- Spacing keeps the existing 8-point scale (4 to 32 px). Dashboards use the dense end, 8 to 16 px between related items.
- Radius: 8, 12 and 16 px. No gradients, no glow, no glass. Shadows only for things that float: menus, dialogs, the bottom bar.
- Motion is CSS only: 140 ms for state changes and 220 ms for panels. No motion library. Both the system and in-app reduced-motion settings stop it.
- Icons are the inline SVG set in `shared/components/Icon`, never emoji. Every icon-only button has a label.

### Charts

Hand-drawn SVG, with no chart library, following the skill's chart guidance:

| Need | Chart | Rules |
| --- | --- | --- |
| A KPI against a target | Bullet chart | The number and the target as text beside it; colour supplementary |
| A trend over time | Line | No more than 6 series; dashed after the history–forecast boundary; a table fallback |
| Comparing categories | Horizontal bar | Bars measured from zero; negative bars drawn to the left of zero |
| Parts of a whole | Stacked bar | Never pie for more than 3 parts |
| Two measures across groups | Heatmap matrix | The value printed in each cell |
| Over 1,000 points | Aggregate first | The SVG budget is about 1,000 marks |

Every chart has a title that states the finding, an `aria-label`, and the same numbers available as a table.

## 4. Information architecture

```
Desktop sidebar                      Phone bottom bar (5 at most)
  ANALYSE                              Overview · Datasets · Analyses · Assistant · More
    Overview          (new)            "More" opens the drawer: Dashboards, Memory,
    Datasets          (new)            Activity, Preferences
    Analyses          (Runs)
    Dashboards        (phase 3)
  WORK WITH
    Assistant         (Chat)
    Memory
    Activity
  Preferences
```

- **Overview** comes first in the navigation and in the phone bar. The session still opens on the assistant, which greets a newcomer; the Overview is one click away.
- Names change only where the vision needs them. "Runs" keeps its route and becomes "Analyses" in phase 3, when dashboards make the distinction matter. Until then, labels the tests rely on stay stable.
- **Deep links** (phase 2): each view gets a `#/view` address so that the browser's back button and shared links work. This needs no router library.

## 5. Screens

### Overview (phase 1)

```
┌──────────────────────────────────────────────────────────────────┐
│ Overview                                    [Start an analysis]  │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│ │ 3        │ │ 1        │ │ 2        │ │ 4 of 20  │              │
│ │ analyses │ │ waiting  │ │ datasets │ │ runs     │              │
│ │ complete │ │ approval │ │ stored   │ │ today    │              │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘              │
│ Latest findings · from "Why did revenue …" (completed)           │
│  • Descriptive: Revenue is up 45% over the period          →    │
│  • Diagnostic:  Software drove most of the change           →    │
│ Waiting for you                                                  │
│  • Publish "Q4 review" · risk medium            [Review]         │
│ Recent analyses                                                  │
│  goal · dataset · state · updated                         →     │
└──────────────────────────────────────────────────────────────────┘
```

Empty state, before any analysis: one sentence on what the workspace does, and two actions, *Try the sample data* and *Add a dataset*.

### Datasets (phase 1, extended in phase 2)

- **Phase 1:** a list of stored datasets with name, size and date added. "Analyse" opens Runs with that dataset chosen and its goal ready to edit; nothing is uploaded twice.
- **Phase 2 (A1 and A2):** add CSV, XLSX and JSON files, preview the first rows, and map columns to measure, dimension, date or ignore, saved with the dataset. Errors appear next to the field, with an error summary at the top.

### Analysis (Runs; reworked in phase 3)

The approval card comes first when a run is waiting. Then the findings: four headline cards, one per analytics type. Then the stage timeline, with the 22 tasks grouped into four bands: data, analytics, assurance, publish. The full report follows.

### Dashboards (phase 3: A4 and A5)

```
┌ Dashboard: <dataset> ──────────── updated 14:02 · [Live ●] ─────┐
│ Filters: [Quarter ▾] [Region ▾] [Category ▾]  (chips wrap)      │
│ Pages:  Summary | Trends | Drivers | Forecast & risk | Quality  │
│ ┌ KPI bullets ─────────────┐ ┌ Trend (line + forecast) ───────┐ │
│ └──────────────────────────┘ └────────────────────────────────┘ │
│ ┌ Contribution (± bars) ───┐ ┌ Segment heatmap ───────────────┐ │
│ └──────────────────────────┘ └────────────────────────────────┘ │
│ Selecting a mark filters the page; "Drill to rows" opens a table │
└──────────────────────────────────────────────────────────────────┘
```

- Pages are generated from a run's charts and the aggregates API, never computed in the browser.
- Filters apply to every page and appear as chips that wrap.
- Every chart has a "View as table" toggle.

### Live data (phase 6: A7)

- A "Live" badge, the time of the last update, and a pause control.
- Updates are announced politely (`aria-live="polite"`), at most once a minute.
- A failed refresh keeps the last good data and says so.

## 6. Interaction rules

From the skill's UX guidelines, applied here:

- **Targets** at least 44 × 44 px on touch and 8 px apart. Hover is never the only way to reach something.
- **Every view has four states:** skeleton while loading, empty with a next step, error with a retry, and offline.
- **Forms:** visible labels, errors beside the field, a focusable error summary on submit.
- **Filters:** chips wrap and never clip; a "Clear all" control; the active filters are always visible.
- **Tables:** sticky header and right-aligned figures in tabular numerals; horizontal scroll inside the card on phones, never across the page.
- **Navigation:** the active item is marked with `aria-current`; at most 5 items in the bottom bar; back always works.

## 7. Accessibility, language and performance

| Bar | Target |
| --- | --- |
| WCAG | 2.2 AA in both languages and both themes; axe clean on every view and dialog |
| Keyboard | Every action reachable; visible focus ring; no keyboard traps; Escape closes overlays |
| Layout | No horizontal page scroll from 320 to 1440 px |
| Lighthouse (mobile) | Performance at least 95; Accessibility 100; Best Practices at least 95 |
| Budget | JavaScript on first load at most 100 KB gzipped, all scripts at most 160 KB, and no view's chunk over 30 KB (ADR 0028: 85.7, 105.6 and 5.0 KB after views moved to chunks loaded on demand; a view's strings ship with its chunk, ADR 0035). CSS on the first load at most 10 KB gzipped and all CSS at most 16 KB, since a view's styles ship with its chunk (ADR 0032); fonts at most 120 KB (7.7 and 119.4 KB) |
| Core Web Vitals | LCP under 2.5 s, CLS under 0.1, INP under 200 ms |

## 8. Phases

| Phase | What ships | Needs | Gate | Status |
| --- | --- | --- | --- | --- |
| 0 Foundation | Design system v2 tokens, bundled Fira fonts, flat brand mark, chart fixes (negative bars, forecast boundary) | — | Unit, end-to-end and axe green; contrast verified; budget kept | Done, 16 Oct 2026 |
| 1 Overview and Datasets | Two new views on existing APIs; analyse a stored dataset | — | New end-to-end and axe checks in both languages; no overflow at 320 px | Done, 16 Oct 2026 |
| 2 Add data | Upload of several formats, preview, column mapping; deep links | A1, A2 | ADR; API and UI tests per format; error-summary behaviour tested | Upload, stored-dataset picker, preview and mapping shipped in ADRs 0024–0025. Hash deep links and upload-result previews added in ADR 0029; workbook sheet selection remains proposed. See docs/design/VALIDATION.md for verification status. |
| 3 Dashboards | Dashboard pages, filters, drill to rows, chart-to-table toggle; "Analyses" naming | A4, A5 | Every chart has a table; filter state survives reload; axe on every page | Done, 17 Oct 2026 (ADR 0032): six pages over a run's cleaned table, filters and choices in the address, drill-down to records from every group, axe and no sideways scrolling on every page at desktop and phone width, in both languages. "Analyses" naming not changed |
| 4 Several datasets | Join builder: pick datasets, declare keys, preview the merge | A3 | Join-correctness tests; key-coverage warnings shown | Done, 17 Oct 2026 (ADR 0030): join builder in the run form, preview with match counts and unmatched keys, refusal of repeated lookup keys, end-to-end and axe in both languages |
| 5 Models | Model cards: metric against baseline, calibration, importance, "not used" models | A6 | Every model shows its baseline; weak models labelled | Done, 17 Oct 2026 (ADR 0033): a card per model under the run's charts, verdict first, the metric against its named baseline, what it predicts, from what and how it was tested; a weak model says not to use it. Calibration and importance are in the report section, not the card. Strings ship with the view (ADR 0035) |
| 6 Live | Connectors, schedules, live badge, polite announcements | A7 | Reconnect and stale-data states tested | Done, 17 Oct 2026 (ADR 0034): live sources in the Datasets view, a Live / Reconnecting / Offline badge with the time of the last update, a polite "newer snapshot" notice on dashboards; reconnecting and offline tested end-to-end in Arabic, and by unit tests of the client |

## 9. How to build a screen

1. Read `design-system/agentic-os/MASTER.md`, starting with its *Agentic OS decisions* section, then any page override in `design-system/agentic-os/pages/`.
2. Ask the skill one focused question: `python .claude/skills/ui-ux-pro-max/scripts/search.py "<concern>" --domain ux`. Use `--stack react` for implementation questions.
3. Use tokens, never raw hex values, in components. Add every string in both `en.ts` and `ar.ts`, or, for a view that loads on demand, in its `messages.ts` pack (ADR 0035).
4. Add the states, the keyboard path and the end-to-end and axe checks before calling the screen done.
5. Run the skill's pre-delivery checklist in the master file.
