# ADR 0029: A governed run workspace with reusable review surfaces

Date: 2026-10-17

Status: Accepted for the React implementation; additional backend and native packaging work remains proposed.

## Context

The analytics pipeline, column mapping and server-bound approval already exist. The interface needs to connect a question, dataset, observed progress, evidence and an exact report to the user's publication decision. The UI must preserve the current client-stepped execution model and accommodate custom stages.

## Decision

- Keep the existing shell, token system, bundled Fira fonts, SVG icons and bilingual dictionaries. Add no package dependencies.
- Use hash addresses for destinations and individual runs. Retain views with React Activity so navigation preserves local state while hidden views stop their effects. Reuse the existing ADR 0028 lazy loaders, save-data-aware idle prefetch and error boundary with reload recovery. Previously visited views stay mounted in Activity; unvisited views are not rendered in the background.
- Centralize run snapshots and scheduling in a small external store. Multiple observers share a scheduler; only a visible Runs view drives execution. Assistant cards and the approval inbox read state. A mutation waits for an in-flight read/step and blocks a duplicate submission. Reconcile an uncertain mutation using GET, without replaying the POST.
- Derive a bounded local observation history from actual snapshots. These are client observations, not an AG-UI wire protocol or a durable server event log. Never fabricate transitions that occurred between snapshots.
- Group returned tasks into Data, Analytics, Assurance and Publish. A plan preview describes the configured stages; actual progress uses the returned task list and stable task IDs.
- Show the first returned finding in the cockpit header. Reuse ApprovalCard for the cockpit and inbox, with the exact returned report content, identity/version, target, risk, impact, reversibility and server-confirmed actions.
- Make claim references, stage checks and report calculation tables available in a keyboard-accessible evidence dialog. The API does not expose a structured reference-to-calculation resolver; display the identifiers and tables separately, without inventing a relationship.
- Render only recognized assistant result types. Unknown content remains ordinary escaped text. Tool disclosures show returned actions and results, never private reasoning.
- Preserve question and composer drafts in sessionStorage scoped to the current session and tab. Dataset text is excluded. Durable runs recover from their server address. Raw pasted CSV stays in component memory and must be pasted again after a reload.
- Deliver an installable PWA with browser-specific Windows, Android and iOS instructions. Native wrappers, signing, stores and operating-system integrations require a separate decision.

## Consequences

Leaving Runs stops this tab's future advance requests. An already submitted step may complete; another tab or an optional server worker may continue. A reader must refresh/reopen a run to reconcile uncertain outcomes. UI language changes do not rewrite a stored report.

The pending approval is bound to the artifact by the server. An old client view cannot grant approval for a modified artifact. The client never reports publishing success without a returned publication path.

New views and translations consume some of the existing bundle budget. CI measures first-load, aggregate and per-chunk JavaScript, CSS and fonts with the existing ADR 0028 budget function. A passing source review is insufficient to claim that budget or usability targets passed.

## Verification

Snapshot/store and component tests cover observed transitions, custom stages, duplicate mutations, uncertain responses, safe card fallbacks and draft recovery. Playwright covers the real sample journey, exact-report review, deep-link recovery, keyboard focus, Arabic phone layouts and axe scans. CI retains screenshots and the production build. See [the implementation specification](../design/AGENTIC_UI_SPEC.md) and [validation record](../design/VALIDATION.md) for actual results and open items.
