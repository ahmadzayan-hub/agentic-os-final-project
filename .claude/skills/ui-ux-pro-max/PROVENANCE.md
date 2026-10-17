# Provenance: ui-ux-pro-max

Third-party skill, vendored so every teammate's Claude Code session has the same design intelligence. It is reviewed like any code in this repository.

| | |
| --- | --- |
| Source | <https://github.com/nextlevelbuilder/ui-ux-pro-max-skill>, folder `.claude/skills/ui-ux-pro-max/` |
| Commit | `56ea9cf174ed86786187daa9de0e6247cb0747e4` (2026-10-15), still the upstream HEAD when re-cloned on 2026-10-16 |
| Licence | MIT, copied unchanged into `LICENSE` here |
| Vendored | 2026-10-16 |

## What was reviewed

- The scripts (`search.py`, `core.py`, `design_system.py`, `reasoning_contract.py`, `validate_data.py`) use the Python standard library only. They read the bundled CSV and JSON files, make no network calls, and start no processes.
- They write files only with `--persist`, and only under the folder `--output-dir` names.
- The data is CSV and JSON guidance (styles, palettes, typography, UX rules, charts, stacks). It is advice, not instructions: where it conflicts with `CLAUDE.md`, `brain/Soul.md` or `docs/UI_PLAN.md`, those win.

## Local changes

- `SKILL.md`: commands use `${CLAUDE_SKILL_DIR}/scripts/search.py` instead of the upstream plugin path.
- `scripts/tests/` and their fixtures are not vendored.

## In this repository

- The persisted design system is `design-system/agentic-os/MASTER.md`. Its "Agentic OS decisions" section overrides the generated values: Arabic support, existing contrast results, the chart rules.
- How the UI is planned and built is in `docs/UI_PLAN.md`.

## The other skills from the same repository

Vendored on 2026-10-16 at the user's request, each with its own `PROVENANCE.md` and review notes: `banner-design`, `brand`, `design`, `design-system`, `slides` and `ui-styling`. Three of `design`'s scripts call third-party image services when given an API key, and `ui-styling` can run `npx shadcn`; neither applies to the app.

## Updating

Clone the upstream repository at a new commit, review the diff of the scripts and `SKILL.md` as code, copy the same folders, reapply the local changes, and update the commit above.
