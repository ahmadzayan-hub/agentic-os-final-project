# ADR 0018 — The interface in the reader's language

**Status:** Accepted
**Date:** 2026-09-23
**Amends:** the `language` preference, which since the first release was
recorded and then ignored

## Context

The preference existed. `/set language Arabic` was accepted, stored,
echoed back by `/preferences`, shown in the context rail — and changed
nothing. The interface held 188 English strings in its components, the
stylesheet had 30 rules that said *left* or *right*, and the agent's
templates were English regardless. A person who set the preference got a
label that said "Arabic" above an interface that was not.

That is a worse state than not having the preference. A control that
does nothing teaches the reader that controls do nothing.

The people this project is for read Arabic. That is not a localisation
nicety to schedule after launch; it is the difference between the
product being usable by its intended readers and being a demo for
someone else.

## Decision

### The choice lives on `<html>`

`lang` and `dir` on the root element are where CSS (`:lang()`,
logical properties), the bidi algorithm, screen readers and `Intl` all
read from, so that is the single source of truth. An inline script in
`index.html` stamps the saved choice before first paint — an Arabic
reader must never see a left-to-right flash while React loads — and
`useI18n()` keeps components in step with the element through
`useSyncExternalStore`, the same mechanism `useTheme` uses for
`data-theme`.

### Two dictionaries, typed against each other

`i18n/en.ts` is the source of truth; `i18n/ar.ts` is typed as
`Record<MessageKey, string>`, so a string added to English and forgotten
in Arabic is a compile error, not a blank label in production. A runtime
test repeats the check and adds two more: no Arabic value is empty or
accidentally still English, and both languages use the same placeholders.
Every string was written by hand in the register of a business
application; none is machine-translated.

Plurals go through `Intl.PluralRules`, because Arabic has six categories
(zero, one, two, few, many, other) and "{n} messages" is wrong in four of
them.

### Direction is a property of the layout, not of the stylesheet

Every `left`/`right` rule became its logical equivalent
(`inset-inline-start`, `margin-inline-end`, `border-start-start-radius`,
`text-align: start`). The layout mirrors under `dir="rtl"` with no
second stylesheet; the two transforms that slide something in from an
edge get one mirrored rule each. Letter-spacing goes through tokens that
Arabic zeroes, because tracking — negative or positive — breaks the joins
of a connected script. The send icon flips, because it points in the
writing direction.

Content that arrives from the server carries its own direction:
`dir="auto"` on anything a person typed or the agent said, so an English
reply in an Arabic interface (or the reverse) orients by its content;
`dir="ltr"` on commands, paths, CSV and charts, which are the same in
either language.

### The agent answers in the language it was asked in

An Arabic interface over an agent that says *"Happy to help!"* would be
a coat of paint. `agent.py` now carries its replies in both languages —
welcome, help, every confirmation and error, the three tone templates —
and phrases each from the `language` preference. The interface seeds
that preference when it creates a session and updates it when the reader
switches, so the welcome message arrives in Arabic on the first response
with no second request to correct it. The command catalogue the palette
shows follows the same preference.

### Reports stay English, and say so

The narrative in `server/analytics.py` is some 2,400 lines of English,
and a report's numbers, evidence ids and calculation names must be
byte-identical across languages for the provenance chain to hold. That
is a separate slice with its own design (ADR to follow), not a switch.
Until then every report block is marked `lang="en" dir="ltr"`, so a
screen reader changes voice rather than reading English with Arabic
rules, and the preferences screen says in Arabic that reports are
written in English.

### Digits stay Western

`ar-u-nu-latn`: numbers on screen are formatted for Arabic (grouping,
month names) but with 0–9, because the same figure appears in an English
report and must read as the same figure. A reader who sees ٤٢٣٬٩٨٠ on
screen and 423,980 in the published markdown has been given a puzzle.

### No web font

System fonts with full Arabic coverage, ordered so Latin glyphs come from
the same face as the Arabic around them. The app is a PWA that works
offline and makes no third-party requests; a font CDN would break both.
The cost is that the Arabic face varies by operating system.

## Verification

- 14 unit tests: dictionary parity, placeholder parity, six Arabic
  plural categories, Western digits, `<html>` stamping, a component
  re-rendering on switch, React nodes inside a translated sentence.
- 4 end-to-end tests in Arabic, on desktop and mobile: right-to-left on
  first paint, the agent replying in Arabic to a session born in Arabic,
  every view translated and passing the same WCAG 2.2 AA scan as English,
  no horizontal overflow, the header switch changing interface and agent
  together and surviving a reload.
- 16 Python tests: every reply the agent can give, in Arabic; the
  spellings a person types (`العربية`, `ar`, `Arabic`); switching
  mid-session with the confirmation already in the new language; an
  unknown language kept as typed and answered in English; the API
  creating a session in Arabic and the command catalogue following.
- English is pinned unchanged: the existing 38 end-to-end checks and the
  agent suite pass with no assertion edited except one tab name (below).

**A defect found on the way.** The causal report tab was labelled with
its stage role, `experiment`, capitalised by CSS. Naming it for the
reader ("Causal — Can we claim a cause?") is right in both languages and
was the only English-facing change; the keyboard test that looked for
the role now looks for the label.

## Consequences

- The interface is Arabic or English, per browser, switchable in one
  click from the header or the sign-in screen, and the agent follows.
- Components contain no user-facing strings. Adding a screen means
  adding keys to two files, and the compiler refuses one without the
  other.
- The activity log records event *codes*, not sentences, so it re-reads
  in the new language after a switch instead of being half-and-half.
- 457 Python tests, 37 unit tests, 46 end-to-end checks.

## What is still absent

- **Arabic reports** — the analytics narrative. Separate slice.
- **Only two languages.** The mechanism takes a third dictionary; nothing
  else needs to change. No third is planned.
- **No per-tenant default.** A hosted install starts every new browser in
  English until the reader switches; the choice is per browser and per
  session, not per organisation.
- **Dates and numbers follow ICU's Arabic defaults** (Egyptian month
  names). Gulf readers may prefer different ones; nothing selects a
  region.
