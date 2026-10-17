# Provenance: design-system

Third-party skill from the same repository as `ui-ux-pro-max`, vendored on 2026-10-16 at the user's request so every teammate's Claude Code session has it. It is reviewed like any code in this repository, and its advice never overrides `CLAUDE.md`, `brain/Soul.md` or `design-system/agentic-os/MASTER.md`.

| | |
| --- | --- |
| Source | <https://github.com/nextlevelbuilder/ui-ux-pro-max-skill>, folder `.claude/skills/design-system/` |
| Commit | `56ea9cf174ed86786187daa9de0e6247cb0747e4` (2026-10-15), the repository's HEAD when cloned |
| Licence | MIT, copied unchanged into `LICENSE` here |
| Local changes | None to the skill. `scripts/tests/` folders are not vendored. |

## What was reviewed

- `generate-tokens.cjs`, `validate-tokens.cjs` and `embed-tokens.cjs` are Node standard library; the validator only reads (its `--fix` prints suggestions).
- `search-slides.py`, `slide_search_core.py`, `html-token-validator.py` and `slide-token-validator.py` are Python standard library; the slide validator runs the HTML validator as a subprocess.
- `fetch-background.py` returns image URLs (Pexels) and search links; it does not download anything.
- `generate-slide.py` writes slide HTML that loads Google Fonts and Chart.js from public CDNs.

## In this repository

- Its token advice (three layers, no raw hex in components) matches ADR 0023. Its slide output fetches third-party fonts and scripts, so it is for decks, never for the app.
- The skill's name is not the same thing as the folder `design-system/agentic-os/`, which holds this project's own design system.
- First use, 2026-10-16: `validate-tokens.cjs --dir frontend/src` reported no hardcoded colours; a direct search found four it cannot see (three `rgb(5 8 18 / 0.62)` scrims and one `#fff` switch thumb in `app.css`). They became the tokens `--scrim` and `--switch-thumb` the same day, so no raw colour remains in `frontend/src` outside `tokens.css`. The validator misses space-separated `rgb()` and allows `#fff` by design, so check with a search as well.

## Updating

Clone the upstream repository at a new commit, review the diff of `SKILL.md` and every script as code, copy the folder without its tests, and update the commit above. The steps are the same for all seven skills from that repository; see `../ui-ux-pro-max/PROVENANCE.md`.
