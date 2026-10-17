---
name: verify
description: Run every check Agentic OS has (Python suite, brain check, typecheck, frontend unit tests, production build, interface budget, and optionally the Playwright suite) with one command, and report the real counts. Use before saying a change works, before a commit that touches behaviour, before the session-end skill logs results, or when the user says "verify", "run the checks" or "is it green?".
---

# Verify

`scripts/verify.py` runs the same commands as CI, plus the brain check and the interface budget from `docs/UI_PLAN.md` §7. It prints one line per step with the counts the tools reported. Those lines are the only test numbers you may quote.

## Choose the run

| When | Command | Time here |
| --- | --- | --- |
| While iterating | `python scripts/verify.py --quick` | about a minute |
| Before a commit | `python scripts/verify.py` | adds the build and the budget |
| Interface changes | `python scripts/verify.py --e2e` | adds Playwright, several minutes |

- Add `PG_TEST_URL=… REQUIRE_PG=1` (the URL is in `CLAUDE.md`) to run the PostgreSQL tests as well. Without it they skip, and the summary shows how many.
- The end-to-end step uses the pre-installed Chromium at `/opt/pw-browsers/chromium` when it exists.
- The e2e run rewrites `docs/screenshots/`. Restore them with `git checkout -- docs/screenshots` unless the change is meant to update them.

## Report

- Quote the PASS and FAIL lines as printed, with their counts, in the form "Python tests: N tests, K skipped".
- If a step failed, show the failing test from the output tail, and fix it or say plainly why not.
- Never round a count, carry one over from an earlier session, or call a skipped step passed.
- When a count changes, update `README.md`, the one place test counts are kept. `tests/test_docs.py` checks other numeric claims.

## Performance

Lighthouse is not part of the script, because it needs a running server. To measure:

1. Run `python scripts/serve.py --local-only --port 8011` in the background.
2. In `frontend/`, run `CHROME_PATH=/opt/pw-browsers/chromium npx lighthouse http://127.0.0.1:8011/ --quiet --output=json --output-path=<scratch>/lh.json --chrome-flags="--headless=new --no-sandbox"`. Run it three times and quote the median.
3. Quote the scores and LCP, CLS and TBT as measured, with the date. The targets are in `docs/UI_PLAN.md` §7.
