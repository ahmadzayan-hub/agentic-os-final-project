# Provenance: design

Third-party skill from the same repository as `ui-ux-pro-max`, vendored on 2026-10-16 at the user's request so every teammate's Claude Code session has it. It is reviewed like any code in this repository, and its advice never overrides `CLAUDE.md`, `brain/Soul.md` or `design-system/agentic-os/MASTER.md`.

| | |
| --- | --- |
| Source | <https://github.com/nextlevelbuilder/ui-ux-pro-max-skill>, folder `.claude/skills/design/` |
| Commit | `56ea9cf174ed86786187daa9de0e6247cb0747e4` (2026-10-15), the repository's HEAD when cloned |
| Licence | MIT, copied unchanged into `LICENSE` here |
| Local changes | None to the skill. `scripts/tests/` folders are not vendored. |

## What was reviewed

- `scripts/logo/search.py`, `scripts/cip/search.py` and their `core.py` are standard-library BM25 search over the bundled CSV files, with no network calls.
- **`scripts/logo/generate.py`, `scripts/cip/generate.py` and `scripts/icon/generate.py` call third-party image services** (Google Gemini; for logos also AtlasCloud and MuAPI). They send the prompt, and for identity mockups the logo image, to those services, and need `GEMINI_API_KEY`, `ATLASCLOUD_API_KEY` or `MUAPI_API_KEY`. They read keys from the environment or from `.env` files, including `.claude/skills/design/.env`. Without a key they stop with an error. They also need `google-genai` and `pillow`, which `requirements.txt` does not include.
- `scripts/cip/render-html.py` writes an HTML page from images already on disk.

## In this repository

- `.env` is git-ignored at every level, so a key placed there is never committed. A key belongs in the environment or that ignored file, and a key once pasted into a chat must be rotated first.
- Never send a dataset, a report or anyone's personal data to the image services. A generated image is an illustration, never a screenshot of the app (`brain/Soul.md`).
- The app's icons stay the hand-drawn set in `frontend/src/shared/components/Icon.tsx` (ADR 0023).

## Updating

Clone the upstream repository at a new commit, review the diff of `SKILL.md` and every script as code, copy the folder without its tests, and update the commit above. The steps are the same for all seven skills from that repository; see `../ui-ux-pro-max/PROVENANCE.md`.
