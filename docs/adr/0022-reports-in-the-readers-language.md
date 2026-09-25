# ADR 0022 — Reports in the reader's language

**Status:** Accepted
**Date:** 2026-09-25
**Completes:** ADR 0018, whose "What is still absent" named this slice
**Keeps:** the provenance chain (ADR 0009), the approval gate bound to an
artifact hash, the narrator's "phrase, never calculate" rule (ADR 0017)

## Context

ADR 0018 put the interface and the agent in Arabic and left the reports
in English, on purpose. A reader who switched to Arabic got an Arabic
workspace wrapped around a report they could not hand to an Arabic-reading
executive. That was the honest state, and it was the largest gap between
the product and the people it is for.

It was left for its own slice because of what a report is here. Every
figure is arithmetic a reader can redo from the method beside it; every
claim cites calculation ids; the validator reads claim text to check the
work; a person approves the exact bytes that get published. A report in a
second language is a second chance to misstate a number, and a translation
done after the fact would sit outside every one of those checks.

## Decision

### A run is written in one language, chosen when it starts

`POST /api/runs` takes `language` (`en` or `ar`, default `en`), stored on
the run. The interface sends the reader's language; the assistant sends
the language of the conversation. It never changes afterwards, because the
approval binds to the hash of one artifact. Switching the interface later
does not rewrite a report someone may already have approved; a report in
the other language is a new run. Runs written before this ADR have no
language recorded and read as English.

### English stays the audited record

Every claim keeps its English `text`, byte for byte what it was. An Arabic
run adds `text_ar` beside it. Calculations (ids, names, values, methods)
are not touched at all. So the record the validator audits and the
provenance chain walks is the same whichever language the reader reads,
and the tests prove it: for ten datasets that exercise every narrative
branch, an Arabic run's claims with `text_ar` removed equal the English
run's claims exactly, and the calculations are the same JSON.

The English report is unchanged too. Before merging, the English output of
all 21 stages was compared with the previous release on six datasets:
identical apart from one new field, `language`, on the reporter's output.

### The translation is checked, not trusted

Two new validator checks run on every non-English report:

- **both_languages_cite_the_same_figures.** For every claim, the figures
  in `text_ar` must equal the figures in `text` as a multiset (digits with
  their separators, decimals and percent signs; grouping commas and signs
  ignored). A translation that drops, rounds or mistypes a figure fails
  the run. It is rejected, not published.
- **every_builtin_claim_is_in_the_report_language.** A built-in claim with
  no Arabic fails the run, so a stage added later in English only cannot
  slip an English sentence into an Arabic report unnoticed. Custom stages
  (ADR 0020) are exempt: an operator's plugin may speak English only, and
  its claims are shown as written.

The jargon check (`claims_avoid_statistical_jargon`) now reads the Arabic
too, with the Arabic forms of the same vocabulary (القيمة الاحتمالية،
دلالة إحصائية، فترة الثقة، الانحراف المعياري، …).

Tests go further than the validator can at run time: headlines, stage
summaries, every section report, the governance notes and the full report
cite the same figures in both languages, for every dataset.

### What is translated, and what is left as written

Translated: every headline, claim, stage summary, section report, table
header, chart title and alt text, quality-check detail, the executive
summary's facts, the task titles, the comprehensive report's frame, and
the approval request (action, impact, reversibility), because the person
who approves is the person who reads. The approval's `risk` stays the
enum `high`, which the interface labels in either language.
Each sentence is written out in full in both languages at the place it is
produced (`_say(ctx, english, arabic)`), so a reviewer reads a sentence,
not a template with holes. None is machine-translated.

Left as written, deliberately:

- **Calculation names and methods.** They are identifiers the claims
  cite. The Arabic report says once, under each table, that they keep
  their original notation.
- **The data.** Column names, group names, the goal a person typed,
  glossary definitions and owners. They are the reader's own words.
- **Period labels that name a calculation.** "next period +1" is part of
  a calculation name, so it stays; it is shown as «الفترة التالية +1»
  only where a sentence reads it.
- **Digits.** Western in both languages (ADR 0018), and the model narrator
  is told to copy every figure exactly, with the same digits.

### Arabic counts follow Arabic grammar

"3 rows", "11 rows" and "100 rows" take three different noun forms in
Arabic, and one and two are carried by the noun itself (صف واحد، صفان).
`_ar_n` applies the same six CLDR categories the interface uses. Because
one and two are then words, not digits, the figure comparison ignores a
bare 1 or 2. That is a narrow, stated hole: a translation that changed a
1 to a 2 would not be caught by the check, and nothing else in it is
relaxed.

### The narrator writes in the report's language

`ModelGateway.narrate` and the router take `language`. For Arabic the
facts are already Arabic, the system prompt adds one instruction (formal
Gulf business register, copy every number exactly), and the deterministic
fallback is Arabic. English prompts are unchanged; gateways and test fakes
that predate the parameter keep working because it is only passed for
Arabic.

### On screen and in the vault

The run carries `report_language`, and both report blocks take their
`lang` and `dir` from it, not from the interface: an Arabic report is
right-to-left and read by a screen reader as Arabic even in an English
interface, and the reverse. The published note's frontmatter records
`lang: ar`.

## Defects found on the way

Writing the parity tests found two places where the first draft leaked
Arabic into the English record, which is exactly the failure this design
exists to prevent: the contract stage built its English claim from a list
it had already localised, and the governance stage did the same with the
"nobody named" owner. Both now build each language from its own parts,
and the test that strips `text_ar` and compares with an English run would
catch a third.

## Verification

- 32 Python tests in `tests/test_report_language.py`: identical
  calculations and English record across ten datasets and two glossary
  cases; figure parity for every claim, headline, summary and report;
  the validator rejecting a drifted figure, an untranslated claim and
  Arabic jargon; noun forms; the narrator's prompt and fallback; the API
  from creation to an Arabic vault note; the assistant starting an Arabic
  run from an Arabic conversation.
- End-to-end, desktop and mobile: a run started from the Arabic interface
  shows Arabic reports marked `lang="ar" dir="rtl"` that pass the same
  WCAG 2.2 AA scan, and the full report lists the parity check; an
  English run's report stays `lang="en" dir="ltr"`.
- The existing suites pass with no assertion edited except the one that
  pinned the old behaviour (an Arabic run's report marked English).

## Consequences

- A person who works in Arabic gets an Arabic report, with the same
  figures, the same evidence and the same approval gate as English.
- Every new sentence a stage writes needs its Arabic beside it, or the
  validator fails the run. That is the cost, and it is intended.
- Adding a third language means a third branch in `_say`, a third set of
  report frames, and a third noun table. The checks already generalise.

## What is still absent

- **Only Arabic and English.**
- **Dates.** Period labels are shown as the data wrote them (2025-01), not
  as Arabic month names.
- **Custom stages speak their own language.** A plugin's claims and report
  appear as its author wrote them; nothing translates them.
- **No live model narration was run from this environment.** The Arabic
  prompt is tested for what it sends, not for what a model returns; a
  model that rewrote a figure would be visible in the executive summary,
  which is labelled with its source, and is not covered by the claim
  parity check because the summary is not a claim.
- **A report cannot be re-rendered in the other language.** That is a
  new run and a new approval, by design.
