# Provenance: ui-styling

Third-party skill from the same repository as `ui-ux-pro-max`, vendored on 2026-10-16 at the user's request so every teammate's Claude Code session has it. It is reviewed like any code in this repository, and its advice never overrides `CLAUDE.md`, `brain/Soul.md` or `design-system/agentic-os/MASTER.md`.

| | |
| --- | --- |
| Source | <https://github.com/nextlevelbuilder/ui-ux-pro-max-skill>, folder `.claude/skills/ui-styling/` |
| Commit | `56ea9cf174ed86786187daa9de0e6247cb0747e4` (2026-10-15), the repository's HEAD when cloned |
| Licence | MIT, copied unchanged into `LICENSE` here |
| Local changes | None to the skill. `scripts/tests/` folders are not vendored. |

## What was reviewed

- `tailwind_config_gen.py` writes a Tailwind config file; standard library only.
- `shadcn_add.py` runs `npx shadcn@<version> add …` in a project folder, which downloads packages and changes that project. It has a `--dry-run`.
- `canvas-fonts/`: 54 font files in 29 families for canvas posters, with 27 SIL Open Font License files. Two families have no licence file of their own upstream: IBM Plex Serif and Instrument Serif. Both are published under the OFL by their foundries, alongside IBM Plex Mono and Instrument Sans, whose licence files are here.

## In this repository

- **Its shadcn/ui and Tailwind guidance does not apply to the app**, which has no UI library by decision (ADR 0023). Use it for posters, canvas designs or other projects.
- Never run `shadcn_add.py` or `npx shadcn` against `frontend/`.

## Updating

Clone the upstream repository at a new commit, review the diff of `SKILL.md` and every script as code, copy the folder without its tests, and update the commit above. The steps are the same for all seven skills from that repository; see `../ui-ux-pro-max/PROVENANCE.md`.
