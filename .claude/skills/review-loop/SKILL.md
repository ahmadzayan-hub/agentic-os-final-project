---
name: review-loop
description: Run a deliverable or a change through review rounds until it is 100% validated, meaning every gate passes or is accepted by a named person, or until the loop must stop and say why. Deterministic gates first, then specialist reviewer subagents in parallel, then fixes, then gates again. Use before submitting a report, deck, dashboard or clip, before a release, or when the user says "review until it passes", "validate everything" or "make sure it is 100%".
---

# Review loop

The main session runs this loop, because a subagent cannot start another subagent. The rules are in `docs/AGENT_TEAM.md` §3. In short:

- 100% means every gate passes or is accepted in writing by a named person.
- The loop is bounded: at most five rounds, and it stops after two rounds in a row with no gain.
- It never reports a score it did not measure.

## 1. Write the plan (once)

Write a JSON plan beside the deliverable; for course or client work, keep it outside the repository. Choose gates from these kinds; `scripts/review_gate.py` documents each one.

```json
{
  "name": "capstone-deliverables",
  "max_rounds": 5,
  "reviewers": ["figures-auditor", "brief-compliance-reviewer", "analytics-expert-reviewer",
                "accessibility-i18n-reviewer", "security-privacy-reviewer"],
  "brief": "path/to/brief.pdf",
  "gates": [
    {"id": "report-length", "type": "pdf_pages", "file": "Report.pdf", "min": 20, "max": 25},
    {"id": "report-figures", "type": "figures", "register": "kpis.csv", "docs": ["Report.pdf"]},
    {"id": "deck-sourced", "type": "figures", "register": "kpis.csv", "docs": ["Deck.pptx"],
     "reference": ["Report.pdf"]},
    {"id": "no-draft-markers", "type": "absent", "files": ["Report.pdf"], "patterns": ["Draft for review"]},
    {"id": "team-items", "type": "absent", "files": ["Report.pdf"], "patterns": ["\\[Add"], "owner": "team"},
    {"id": "all-files", "type": "exists", "files": ["Report.pdf", "Deck.pptx", "Dashboard.pbix"]}
  ],
  "accepted": []
}
```

- For a code change, the main gate is `{"type": "command", "run": "python scripts/verify.py"}`.
- An `owner` on a gate marks items only that person or team can supply. The loop lists them for their owner and never fills them in.

## 2. Each round

1. **Score:** run `python scripts/review_gate.py <plan>`. Read the scorecard. It costs no tokens.
    - Use `--reset` only to start a new review; it archives the old rounds in a dated file.
    - A `figures` gate also fails on arithmetic that does not hold, such as "24.4 h − 16.9 h = 6.5 h". A result whose working is shown counts as sourced by its inputs.
2. **Review:** start the reviewers the plan lists **in one message, in parallel**. Give each the scorecard, the paths and the brief, not the documents' text. Each returns findings in this form:

    ```
    FINDING <id> · <blocker|major|minor> · <file and place>
    Evidence: <quoted text, figure or check output>
    Fix: <the change that resolves it, or "owner: <who> must supply …">
    ```

3. **Verify the findings** before acting on them. Recompute a reviewer's figures with a script, from the data, and use your own numbers where they differ. Reviewers are usually right and occasionally not, and their numbers may reach other people.
4. **Fix** in the main session, or with the maker agent for that output (`motion-designer`, `dashboard-analyst`). Fix what is fixable and sourced.
    - Text someone else owns, such as a team's shared report, is theirs to change. Give them the verified figures and the exact replacement wording, not a silent edit.
    - Turn each finding a pattern can check into a new gate, with its `owner`. The next round then checks the fix without a reviewer.
    - Never invent a figure, weaken a gate, or delete a finding to pass.
    - An item only a person can resolve goes to `accepted` only when that person says so. Record their name and reason. Otherwise it stays open and is reported.
5. **Rescore** with `review_gate.py`. Then follow its last line:
    - `continue` means another round. A later round may send only the reviewers whose findings were fixed, to confirm them: one inexpensive reviewer is enough to confirm build fixes.
    - `stop: 100% validated` means report done.
    - `stop: … rounds reached` or `stop: no gain` means report what is left.

## 3. Cheaper second opinions

Before spending a Claude reviewer on prose, translation or summarising, try a free local model:

```bash
python scripts/consult.py --task prose-review --input section.md
python scripts/consult.py --task translate-check --input en-and-ar.md
```

- If it exits 3, no local model is installed. Carry on without it.
- Never send it raw data; it refuses table rows anyway.

## 4. The report

End with:

- the score history (`50% → 83% → 100%`);
- what was fixed, with evidence;
- what was accepted, by whom and why;
- what is still open, and whose it is.

Do not call anything validated that the scorecard did not pass.
