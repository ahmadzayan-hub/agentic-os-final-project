# Provenance: slides

Third-party skill from the same repository as `ui-ux-pro-max`, vendored on 2026-10-16 at the user's request so every teammate's Claude Code session has it. It is reviewed like any code in this repository, and its advice never overrides `CLAUDE.md`, `brain/Soul.md` or `design-system/agentic-os/MASTER.md`.

| | |
| --- | --- |
| Source | <https://github.com/nextlevelbuilder/ui-ux-pro-max-skill>, folder `.claude/skills/slides/` |
| Commit | `56ea9cf174ed86786187daa9de0e6247cb0747e4` (2026-10-15), the repository's HEAD when cloned |
| Licence | MIT, copied unchanged into `LICENSE` here |
| Local changes | None to the skill. `scripts/tests/` folders are not vendored. |

## What was reviewed

- `SKILL.md` and five reference files. No scripts.
- The HTML it describes loads Chart.js from a public CDN.

## In this repository

- For HTML presentations, such as a capstone rehearsal deck. Not for the app, which makes no third-party requests and draws its charts as SVG (ADR 0023).

## Updating

Clone the upstream repository at a new commit, review the diff of `SKILL.md` and every script as code, copy the folder without its tests, and update the commit above. The steps are the same for all seven skills from that repository; see `../ui-ux-pro-max/PROVENANCE.md`.
