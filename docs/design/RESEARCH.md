# Agent interface reference review

Research cutoff: **16 October 2026, 23:59 UTC**. Retrieved through the connected GitHub tools on 17 October 2026. Each source below was read at the latest default-branch commit returned by GitHub with that cutoff; these are implementation references, not a ranking or a claim about all GitHub trends.

| Source snapshot | Observed pattern | Agentic OS decision |
| --- | --- | --- |
| [assistant-ui/assistant-ui](https://github.com/assistant-ui/assistant-ui/blob/16f5c3b10617eba40298de41892f8f536f7401e9/README.md) · `16f5c3b` | Composable conversations and rich tool results | Keep Composer/MessageBubble and add ResultCard/ToolCards; preserve readable text and recovery. |
| [CopilotKit/CopilotKit](https://github.com/CopilotKit/CopilotKit/blob/ff1178a6a08ec9cc55dd2cce678e27d07e26a27a/README.md) · `ff1178a` | Shared context and explicit human decisions | Use actual dataset/run context and exact-report ApprovalCard. Do not add a parallel orchestration runtime. |
| [ag-ui-protocol/ag-ui](https://github.com/ag-ui-protocol/ag-ui/blob/89cedd3fd549feeee41e50e1d7c6d373e549241a/README.md) · `89cedd3` | Event-based agent/user state | Derive a typed local observation history from snapshots. SSE/AG-UI transport needs backend support. |
| [a2ui-project/a2ui](https://github.com/a2ui-project/a2ui/blob/c68db100a9aeac9aa276ac226644b3b7f377717e/README.md) · `c68db10` | A controlled component catalog for declarative UI | Recognize known action/result shapes and render trusted React components; unknown results stay escaped text. |
| [vercel/ai-elements](https://github.com/vercel/ai-elements/blob/ca8be600bfd01b3131f9bf6134b51602a71f4374/README.md) · `ca8be60` | Reusable conversation/task building blocks | Use patterns only; avoid a new Next.js/shadcn/Tailwind stack and migration dependency. |

## Changes to account for

The original Google A2UI URL redirects to **a2ui-project/a2ui** (the same repository ID). Its cutoff README identifies v0.9.1 in the v0.9 family and a v1.0 release candidate, with an evolving specification. No A2UI wire-format integration is claimed by a local typed card catalog.

The cutoff AI Elements README announces a move to shadcn/ui and planned deprecation of that repository at the end of November 2026. Its documented prerequisites also include a different application stack. This makes a new direct integration a poor fit for this existing Vite application and its offline/bundle constraints. Reusable conversation and action patterns remain useful.

AG-UI describes an event protocol that can use several transports; adding a status label or a local snapshot adapter does not mean the application streams AG-UI. A genuine integration would need authenticated subscriptions, event ordering, resume/reconnect and authoritative state reconciliation.

## Design method and dependency decision

Applied the repository's vendored UI/UX Pro Max workflow, its focused keyboard/focus and React searches, and its critical/high-priority quick reference and professional rules. The connected RMD UI/UX Pro Max package is specialized to RMD V2; its domain-specific instructions are not imported into Agentic OS. The repository's Agentic OS overrides and tokens win over generated generic examples.

Figma was used for native editable design frames and a component inventory. The built-in image generator produced an original decorative image; see [asset provenance](ASSET_PROVENANCE.md). A React best-practices review checked shared subscriptions, inactive effects, lazy views, explicit async state and stable identities. No new UI kit, animation package, chart library, protocol dependency or native wrapper was installed.

These choices preserve the existing API contracts and the governed publishing gate while giving the interface richer, source-backed results. Future dependency adoption requires a measured bundle/offline/accessibility evaluation and an ADR.

