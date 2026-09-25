# ADR 0019 — A conversational agent that understands and acts

**Status:** Accepted
**Date:** 2026-09-23
**Amends:** the chat's free-text reply, which since the first release was
a template

## Context

Every sentence in the chat that was not a slash command got the same
answer: *"Happy to help! I received your request: '…'. Enter /help to see
everything I can do."* In three tones. That is not an agent; it is an
acknowledgement pretending to have understood. The maturity assessment
(docs/MATURITY_ASSESSMENT.md) named it the single largest gap between
the product and its name, and it was: a model gateway existed, a run
engine existed, a memory existed, and the sentence "analyse last
quarter's sales" reached none of them.

Two constraints from the project's own decisions shape what could be
built. Tests and CI need no credentials, so whatever understands a
sentence must work with no model at all (ADR 0007). And a model may
phrase but never calculate: nothing it writes may become a number, and
it never sees a row of data (ADR 0007, 0017). An assistant that violated
either would have bought conversation at the price of the reports' one
property worth having.

## Decision

### An intent is one dict, and everything meets at the executor

A sentence becomes an **intent**:

    {"action": "remember", "arguments": {"information": "…"},
     "reply": None, "source": "rules"}

from one of two understanders — rules or a model — and then a single
executor runs it. What an action *does* therefore never depends on who
understood the sentence, and a test of the executor is a test of both
paths.

The action catalogue is deliberately small and typed, in
`assistant.py`: `chat`, `help`, `remember`, `recall`, `forget`,
`clear_history`, `set_preference`, `start_run`, `run_status`,
`explain_report`. A person can read that list and know exactly what a
sentence can cause. An action a model names that is not on it is
refused; an argument not listed is dropped.

### The rules are the floor, and the floor is real

`assistant.understand()` is a rules-based understander in English and
Arabic, standard library only, that the command-line interface uses
too. It is not a stub for the model: "remember that the Q4 review is on
Monday", "what do you remember about coffee?", "forget everything", "be
concise", "reply in Arabic", "call me Ahmad", "analyse the sample sales
data", "is it done?", "why did revenue move?" — and their Arabic
equivalents — all resolve to the right action with the right
arguments, by rule, offline. A sentence the rules cannot place gets an
honest answer in the chosen tone: *not understood, here is what can be
asked.* Never an acknowledgement.

Order matters and is documented in the code. Two cases found by writing
the tests: "remember to delete all the old files" is a note, not a
deletion, so the anchored remember rule decides before any forget rule
can; and "is the analysis done?" names the analysis and asks about it, so
the status question wins over the noun.

### What the model may decide

With a provider configured, `server/assistant.py` asks the gateway for
**one JSON object** — action, arguments, reply — over a context of
verified sentences and settings: memory entries, preferences, the last
six turns, the names of stored datasets, and the *headlines* of the
latest report. The answer is parsed, the action checked against the
catalogue, the arguments validated (a tone must be one of three; a
memory key must look like one), and anything that fails hands over to
the rules, with the reason recorded.

The model may decide which action a sentence asks for. It may phrase a
`chat` reply — **and that is the only text of its writing a person ever
sees.** Every action's confirmation is the Agent's own deterministic
sentence: when the model says *"Saved! You're all set"* about a
`remember`, the person sees *"Information saved."*, which is true by
construction and would have said otherwise had the write failed. For
`explain_report` the assistant quotes the report's headlines verbatim
rather than asking the model to rephrase them, because a paraphrase of a
verified sentence is no longer a verified sentence.

### What the model may never decide

- **A number.** It never sees a row, and nothing it writes reaches a
  report. A test builds a run on the sample dataset, asks the assistant
  something, and asserts that no line of that dataset appears in what
  the model was sent — and the test fails when the context is made to
  leak one.
- **A deletion.** `forget` and `clear_history` are confirmed in the next
  message — *"Reply 'yes' to confirm or 'no' to keep it"* — by rule,
  whoever understood the sentence. A "yes" executes; a "no" keeps
  everything; any other sentence drops the pending request rather than
  executing it on the strength of an unrelated reply. The pending
  request lives on the transcript entry, so it survives a restart and a
  change of server instance, and it is consumed on use so a later "yes"
  means nothing. Removing the guard fails six tests.
- **An action outside the catalogue**, or one with a bad argument. The
  whole intent is refused and the rules decide instead.

### Starting a run from a sentence

`start_run` creates a run through the same engine, quota and approval
gate as the Runs screen — the chat is not a way around any of them. The
interface opens the run it started, so the person watches the pipeline
rather than being told where to find it. A dataset named in the sentence
("analyse quarterly_sales by team") is matched against the person's
stored datasets; otherwise the sample data is used and the reply says so.

### Honesty about who understood

Each agent reply records its source — `command`, `rules`, or `model`
with the provider — and the interface labels a model's phrasing as such,
the way a report names its narrator. In the default deployment every
reply is `rules`, and it says so.

## Verification

- 49 tests in `tests/test_assistant.py`: twenty rule cases across both
  languages; the executor through the Agent alone (the CLI's path); the
  server assistant with a real engine — a sentence starts a run, names a
  stored dataset, reports status, quotes headlines verbatim, confirms
  before deleting, drops a pending deletion on an unrelated sentence;
  the model path with a fake gateway — the action is the model's, the
  confirmation is the Agent's, an invalid or forbidden answer hands over
  to the rules, a deletion still needs a yes, and no row reaches the
  model; and the API, where a pending confirmation survives between
  requests.
- One end-to-end test in the browser, desktop and mobile: save, recall,
  start an analysis and land on its approval gate, explain, refuse to
  delete without a yes, delete with one.
- Two mutations run by hand: removing the confirmation guard fails the
  confirmation tests; leaking the dataset into the model's context fails
  the no-rows test.
- Three assertions that pinned the placeholder were updated, and the
  original tone templates survive as `Agent.acknowledge()` for the tone
  preference's documentation.

## Consequences

- The chat does what it is asked, in either language, with no model. A
  model widens what it understands; it does not widen what it can do.
- `assistant.py` is a fourth standard-library module the CLI depends on.
  The CLI now saves memories and changes preferences from sentences; for
  an analysis it says to use the web interface.
- 506 Python tests, 37 unit tests, 48 end-to-end checks.

## What is still absent

- **No live model has understood a sentence here.** The model path is
  tested against a fake gateway; this environment cannot reach a
  provider. The first sentence a real model handles is unverified, and
  the fallback to rules is what makes that safe rather than what makes
  it good.
- **The rules are a vocabulary, not language understanding.** A sentence
  phrased outside them gets the honest fallback. The list of phrasings
  will grow from real use; a model is the way past the ceiling.
- **Actions are one per sentence.** "Remember X and then analyse Y" does
  the first. Multi-step plans are the next design, not a patch to this
  one.
- **Explain quotes headlines, not answers.** "Why did revenue move?"
  returns the diagnostic section's verified sentence. A conversation
  that reasons over the full report is a different contract, and one
  that must not let a model restate a figure.
