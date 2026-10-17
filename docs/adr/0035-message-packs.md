# ADR 0035 — A view's strings ship with the view

**Status:** Accepted
**Date:** 2026-10-17
**Amends:** ADR 0028 (views load on demand)
**Keeps:** every user-facing string in English and Arabic, checked for the same keys and placeholders; the first-load budget of 100 KB of JavaScript

## Context

ADR 0028 moved each view's code into a chunk fetched when the view is shown. The strings did not move: `en.ts` and `ar.ts` load with the shell, and each new view added its sentences in both languages to every first load. The dashboard (ADR 0032), the join builder (ADR 0030) and the model cards (ADR 0033) took the first load from 93.7 to 97.9 KB of the 100 KB budget, before live data (ADR 0034) had added anything.

## Decision

A view whose code loads on demand keeps its strings in a **message pack** beside it (`features/<view>/messages.ts`), so they arrive with its chunk.

- `definePack(en, ar)` takes both tables. Its type makes the Arabic table name exactly the English one's keys, as `Record<MessageKey, string>` does for the main dictionaries, so a missing or extra translation fails the type check.
- `usePack(pack)` returns what `useI18n()` returns, with `t` reading the pack first and the main dictionary for every other key. A component swaps one hook for the other and keeps its calls.
- The unit tests hold every pack to the main dictionaries' rules: the same keys and placeholders in both languages, nothing blank or left in English, and no key that the main dictionary also defines.
- Strings the shell needs (navigation, the run form, status labels) stay in the main dictionaries.

The first packs are the dashboard's, the join builder's and the model cards'.

## Consequences

- The first load fell from 97.9 to 92.8 KB with the model cards in place. A new view's strings no longer cost the first load anything.
- A translator now looks in two places: `en.ts`/`ar.ts`, and the `messages.ts` beside each view that has one. Each pack holds both languages in one file, which makes a missing translation easy to see.
- `translate()` outside React reads only the main dictionaries. A pack's strings are for its view's components.
