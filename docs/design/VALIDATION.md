# Interface validation record

Date: 2026-10-17. Design previews, executable checks and human usability observations are recorded separately.

## Runtime evidence

Final run: [39019826211](https://github.com/ahmadzayan-hub/agentic-os-final-project/actions/runs/39019826211), source `972f581813187abc48e6ae76bdb7b579d47956ad`. Status: **passed**, completed 17 October 2026 at 09:14 UTC.

This run verifies the real sample journey, report review and publishing, recovered drafts, delayed-response recovery, report-language preservation, evidence-dialog focus and rendered phone touch targets. Current test counts and expected skips are maintained only in [README](../../README.md#testing).

The CI workflow runs the Python suite with PostgreSQL, frontend unit tests, TypeScript and Vite build, strict brain/snapshot contracts, Playwright, axe and the existing interface-budget function. It retains the production bundle, actual browser screenshots and any failure traces in `agentic-ui-evidence`.

Earlier runs exposed misplaced translation keys, selectors that assumed inactive views were unmounted, cancellation masked by a retained pause flag, dataset draft context, and drawer focus restoration. These were corrected; assertions about actual backend behavior were retained. Source reviews also corrected exact-artifact review, Arabic table headers, bounded dialogs, install-event capture, language-of-parts tags and lazy-load recovery.

## Measured budget

Final source `972f581`, [CI measurement](https://github.com/ahmadzayan-hub/agentic-os-final-project/actions/runs/39019826211), gzip level 9, decimal KB:

| Shipped resource | Measured | Existing limit |
| --- | ---: | ---: |
| First-load JavaScript | 92.0 KB | 100 KB |
| All JavaScript | 117.4 KB | 160 KB |
| Largest deferred JavaScript chunk | 7.4 KB | 30 KB |
| CSS | 9.3 KB | 10 KB |
| Fonts | 119.4 KB | 120 KB |

The first-load, total and deferred-chunk limits come from the existing ADR 0028; this implementation did not raise them. New views, translations and recovery behavior add shipped code. The generated decorative WebP adds 53,592 bytes independently of JavaScript and is cached with the shell. No new runtime dependency or font weight was added.

Final-source LCP, CLS and INP were not measured. A separate Claude Code environment recorded the earlier `d53397d` build below. Neither those laboratory results nor historical ADR 0028 results measure the final source or real-user INP. A fresh final-source performance run remains open.

## Earlier independent local verification

The concurrent Claude Code session recorded `python scripts/verify.py --e2e` with PostgreSQL on `d53397d` in [commit 6e8f254](https://github.com/ahmadzayan-hub/agentic-os-final-project/commit/6e8f2546f7109d7bfa632a75684769697155f713). Its environment had npm, PostgreSQL 16 and pre-installed Chromium. All verification steps passed, including browser and axe checks. Its local optional-library skips differ from CI; current CI counts are maintained in README.

That build measured 91.9 KB first-load JavaScript, 117.2 KB total JavaScript, 7.3 KB largest deferred chunk, 9.2 KB CSS and 119.4 KB fonts. Lighthouse 13.4.1 mobile, median of three runs against the local server: Performance 99, Accessibility 100, first and largest contentful paint 1.55 s, total blocking time 38 ms, layout shift 0.000 and 25.2 KB JavaScript unused at load. These are laboratory observations reported by that session, not measurements repeated in the Codex sandbox or real-user Web Vitals. Later changes include the publication action, evidence initial focus and larger touch targets.

## Acceptance observations

| Target | Observed result and remaining work |
| --- | --- |
| Manager identifies finding and next action within ten seconds | Not observed with a representative manager. The finding, state and decision are explicit; a timed human task is still required. |
| Evidence within two interactions | The browser journey opens returned claims, references and calculation tables directly from a finding. Evidence initially shows its heading; Escape restores the triggering control. |
| Keyboard approval | The real inbox journey activates Review and the exact report with Enter, tabs to Approve and publish, and waits for server confirmation and its publication path. |
| Interrupted text recovered | Component checks cover refused sends and remount recovery; browser checks cover navigation/reload of composer and question drafts. A held start response preserves the new destination and the durable analysis can be reopened. |
| Arabic phone journey | A real Arabic report, evidence table and axe scan pass at 390 px, with the bounded dialog and no page overflow also checked at 320 px. Stored English report parts retain English after switching the interface to Arabic. |
| 44 × 44 px targets | The Arabic-phone browser regression measures every visible button in the run cockpit and passes the minimum dimensions. Shared styles enlarge compact controls; switches preserve their visual track inside a larger touch area. This task is not a complete real-device target audit. |
| Responsive layouts and themes | The retained suite covers desktop and phone, 320/768/1024 px layouts, light/dark, English/Arabic, and reduced motion. Larger text, broader landscape use and assistive-technology testing remain human review tasks. |
| Windows, Android and iOS | PWA manifest, install-event handling, safe-area layout and bilingual browser installation guidance are delivered. Actual installation on those operating systems was not observed; signed native packages are outside this delivery. |

Question and composer drafts stay in sessionStorage for this tab/session. Pasted CSV and selected File objects require re-selection after reload; raw data is excluded from draft storage. API responses are never service-worker cached, so a cold offline launch can recover the shell but cannot fetch private reports.

Repeated clicks are guarded and consequential failed POSTs are reconciled by reading state, without automatic replay. An uncertain run-creation response still needs review of recent analyses: server idempotency keys for creation are a separate API proposal. Same-analysis multi-tab behavior is specified against authoritative server snapshots and leases; a separate two-tab browser task was not performed.

## Design and local evidence

[Figma](https://www.figma.com/design/nLdKZ5cVOtRMTWEvhCJSEK) contains native editable components and representative English/Arabic, light/dark, desktop/phone frames. They were rendered and visually inspected. They are design previews, not application screenshots.

Actual browser captures from the final source are copied into [docs/screenshots](../screenshots/). Provenance: workflow `39019826211`, artifact `12096442428` (`agentic-ui-evidence`, ZIP SHA-256 `735bf912abe13e461817bfd9bc845a067e33c6cc34f5f4c20f82e23cdfd1ebf3`). The desktop evidence dialog, Arabic phone cockpit, dark welcome and light Overview captures were visually inspected. The evidence heading is visible on opening. The bilingual Overview intentionally displays a stored Arabic report within an English interface; changing the interface language does not translate that report. Screenshots contain sample/generated test records and the backend's actual returned figures, not customer data.

In the Codex workspace, strict brain, documentation and dependency-free snapshot checks passed. npm access was blocked by the command sandbox, and full API attempts stalled in TestClient's AnyIO portal; no full-suite pass in this sandbox is claimed. The independent local session above and GitHub Actions supply runtime evidence. The first Codex deterministic scorecard was 40% because package-dependent gates could not execute; it is not a product-quality score or an accepted exception.

Open human, native-device and performance observations remain unaccepted until evidence or an explicit named-owner decision resolves them.
