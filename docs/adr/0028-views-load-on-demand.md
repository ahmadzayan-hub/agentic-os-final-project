# ADR 0028: Views load on demand

**Status:** Accepted
**Date:** 2026-10-17
**Amends:** ADR 0023's JavaScript budget, which now applies to the first load
**Keeps:** the session opening on the assistant (ADR 0023), offline use of the installed app, every string in English and Arabic

## Context

The interface shipped as one script: 96.7 KB gzipped against a 100 KB budget. Every view, dialog and sign-in screen downloaded before the first paint, whichever one a reader opened. The next milestones add views: several datasets per run, dashboard pages and model cards. Under that rule each new view would have added to the first load, and the budget had 3.3 KB left.

## Decision

1. **The chat view and the shell ship in the first load; everything else loads when it is first shown.** The session opens on the assistant, so its view is needed at once. The other six views and four overlays are separate chunks (`frontend/src/app/lazyViews.tsx`): Overview, Datasets, Runs, Memory, Preferences, Activity, the command palette, Help, onboarding and sign-in.
2. **A view on its way shows a skeleton,** with `role="status"` and the label "Loading this view" or "جارٍ تحميل هذه الصفحة". Dialogs show nothing until they arrive.
3. **A view that cannot load says so.** This happens when a reader is offline and never opened that view. React keeps a failed import failed, so the message offers a page reload, in the reader's language. The boundary is keyed by view, so the failure clears when the reader moves to another view. A dialog that fails leaves the page as it was.
4. **The rest arrives in idle time.** Once the session is up, the remaining chunks are fetched when the browser is idle, so a later click is as quick as before. The service worker caches them, as it caches every hashed asset, for offline use. A browser set to save data skips this prefetch.
5. **The budget is measured as it is sent** (`scripts/verify.py`, `docs/UI_PLAN.md` §7):
    - **First load:** at most 100 KB. This counts the entry module and the modules `index.html` preloads.
    - **All scripts together:** at most 160 KB.
    - **The largest chunk loaded on demand:** at most 30 KB. This is the wait for one view.
    - **CSS and fonts:** unchanged, at 10 KB and 120 KB.

## Measured

Gzipped at level 9, as `scripts/verify.py` measures, on 2026-10-17:

| | Before | After |
| --- | --- | --- |
| First load | 96.7 KB, one script | 85.7 KB: the entry (68.2) and the React runtime it preloads (17.5) |
| All scripts | 96.7 KB | 105.6 KB |
| Largest on-demand chunk | none | 5.0 KB (Runs) |

- **React DOM is about 57 KB of the first load.** A build that splits each library into its own file showed this. The first load cannot fall much further without a smaller framework.
- **A reader who opens every view downloads 8.9 KB more than before.** Each chunk is compressed on its own, so gzip cannot share patterns across chunks. Most of that arrives in idle time, after the first paint.

Lighthouse 13.4.1, mobile, three runs on each build, served locally by `scripts/serve.py` (recipe: `.claude/skills/verify/SKILL.md`); medians:

| | Before | After |
| --- | --- | --- |
| Performance | 99 | 98 |
| First contentful paint | 1.37 s | 1.52 s (runs: 1.38 to 1.58 s) |
| Largest contentful paint | 2.13 s | 2.13 s |
| Total blocking time, layout shift | 0 ms, 0.000 | 0 ms, 0.001 |
| Unused JavaScript reported | 46.6 KB | 23.8 KB |
| Page weight | 163.6 KB | 148.8 KB |

At today's size, the split does not make the app faster on this machine. The largest paint is unchanged, the score moved by one point, and the first paint was 0.15 s slower at the median, perhaps because the first load is now two requests. What it does is halve the script that loads unused and keep future views off the first load. That is the reason for this decision, not speed today.

## Consequences

- New views add to the total and to their own chunk, not to the first load. The first-load headroom is now 14.3 KB, against 3.3 KB before.
- Speed did not improve measurably today (see Measured). If the first paint stays slower as views are added, inlining the React runtime into the entry, rather than preloading it, is the first thing to try.
- The first click on a view may show the skeleton for a moment if the idle prefetch has not finished. The end-to-end suite waits for each view as a reader would.
- An error inside a view now shows the reload message instead of blanking the whole page. That is a side effect of the boundary, and a better failure than before.
- Both dictionaries stay in the first load: about 15 KB gzipped together, measured on the source files, of which Arabic is 8.7 KB. Loading only the reader's language would save up to 8.7 KB. But switching language would then wait on a download, and the first paint would need the dictionary before it could start. They stay together for now.

## Tests

- `tests/test_verify.py`, `BudgetTests`:
    - a chunk loaded on demand is not first load, and a preloaded module is;
    - one heavy view fails the budget even when the first load is light;
    - a page with no script is a failure, not a pass;
    - the real build's `index.html` is read.
- `frontend/src/tests/lazy-views.test.tsx`:
    - a view says it is loading, then shows;
    - every chunk resolves;
    - a failure reads in Arabic and offers a reload;
    - a failed dialog leaves the page empty;
    - the prefetch waits for idle time, and is skipped when saving data.
- The end-to-end suite opens each view and dialog through its own chunk. `openTab` in `frontend/e2e/helpers.ts` waits for the loading skeleton to go, so the axe checks read the view and not its placeholder.
- `frontend/e2e/overview.spec.ts`, "a view that cannot load":
    - The Overview's chunk is refused, with the service worker blocked, as for a reader with nothing cached.
    - The view says so and offers a reload, with no axe violations.
    - The next view still opens.
