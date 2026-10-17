---
type: concept
aliases: [Design system v2, UI design system, ui-ux-pro-max]
tags: [interface, design]
status: active
updated: 2026-10-17
review_every_days: 30
sources: [docs/adr/0023-the-analytics-workspace-interface.md, docs/adr/0028-views-load-on-demand.md, docs/UI_PLAN.md, design-system/agentic-os/MASTER.md, frontend/src/shared/styles/tokens.css, .claude/skills/ui-ux-pro-max/PROVENANCE.md, .claude/skills/design/PROVENANCE.md]
---

# Design system

How the interface of [[Agentic OS]] looks and behaves, and where those choices come from. It turns the [[Analytics OS roadmap]] into screens a reader in either language can use.

## Facts

- Generated on 2026-10-16 by the vendored `ui-ux-pro-max` skill (MIT, commit `56ea9cf`) and kept in `design-system/agentic-os/MASTER.md`. The file's *Agentic OS decisions* section overrides the generated values (ADR 0023).
- Palette: navy and blue for actions (`#1e40af` light, `#2563eb` dark). Amber (`#b45309`, `#fbbf24`) is only a highlight, for example the tile showing runs waiting at the [[Approval gate]]. Every text pairing measures 4.5:1 or better and every control border 3:1 or better, in both themes.
- Type: Fira Sans for text and Fira Code for figures, bundled from `@fontsource` (OFL-1.1, Latin only, about 119 KB in five WOFF2 files). Arabic keeps the system stack, because Fira has no Arabic letters.
- Charts stay hand-drawn SVG: bars from a zero line, a marked forecast boundary, and a table of the numbers under each chart. Figures follow [[Weighted KPIs]].
- Navigation: the sidebar groups *Analyse* (Overview, Datasets, Runs) and *Work with* (Workspace, Memory, Activity). A phone's bar holds five places, the last being *More*.
- Budgets: JavaScript at most 100 KB gzipped on first load, 160 KB in all and 30 KB for any one view, because views load on demand (ADR 0028). CSS at most 10 KB (7.7 KB) and fonts at most 120 KB (119.4 KB).
- Phases 0 and 1 of `docs/UI_PLAN.md` shipped in `dea3b38`. Phases 2 to 6 wait on milestones A1 to A7.
- Six more skills from the same upstream repository were vendored in `b478983`: design-system, brand, ui-styling, design, banner-design and slides. For the app only ui-ux-pro-max and design-system's token rules apply. ui-styling's shadcn/Tailwind and slides' CDN Chart.js break ADR 0023, and design's logo, identity and icon generators call third-party image services.

## How to use it

Read the master file, then ask the skill one focused question with `python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<concern>" --domain ux`. Its advice never overrides [[Soul]]: no third-party requests, no fabricated screenshots, and every string in English and Arabic.

## Related

- [[Home]]
- [[Identity]], whose two languages the interface serves equally.
- [[Decision log]], for ADR 0023 and the ADR 0018 accessibility bar it keeps.
- [[House style]]: the look of the agents' outputs, kept separate from the interface.
