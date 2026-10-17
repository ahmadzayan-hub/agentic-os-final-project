# Reviewer benchmark

Synthetic memos with planted defects, for measuring the review loop's reviewers (ADR 0027). Nothing here is real data.

| Memo | Subject | Paragraphs | Defects | Role |
| --- | --- | --- | --- | --- |
| `A/` | A retail chain's year | 16 | 10 | Dev: its misses chose the fixes |
| `B/` | A light-rail fleet's year | 14 | 9 | Held out. The same author wrote A and B |
| `C/` | An outpatient department's year | 15 | 9 | Blind: an independent agent wrote it from the category definitions only |

Each folder holds the memo (`memo.md`, paragraphs `[P01]`…), the register a figure must come from (`register.csv`, columns `Check` and `Expected`), and the labels (`labels.json`). The labels give one category per defective paragraph:

- `unsourced_figure`
- `arithmetic`
- `causal_claim`
- `denominator`
- `overclaim`

## Runs

A run is a reviewer's reply, saved as `runs/<reviewer>-<memo>-<tag>.txt`. The reviewer is `figures-auditor`, `analytics-expert-reviewer` or `figures-tool` (the Tier 0 checker). Tags:

- `named-v1`, `named-repeat`, `named-newtool`: the project subagent as the session loaded it, in its first run, a repeat run, and a run after the checker changed.
- `ctl-v1`, `ctl-v2`: a general-purpose agent on the reviewer's model, given the v1 or the v2 instructions, with everything else the same. This is the controlled comparison, because a subagent's edited instructions only load in a new session.
- `v1`, `v2`: the checker before and after its fixes.

Each run is told to put the paragraph id on the FINDING line and add a `Category:` line, and to open only the memo and its register.

```bash
python scripts/score_review.py --summary [--json evals/reviewers/summary.json]
python scripts/score_review.py --bench evals/reviewers/C --findings reply.txt --categories causal_claim,denominator,overclaim
python scripts/score_review.py --bench evals/reviewers/C --figures-tool --categories unsourced_figure,arithmetic
```

To add a memo, have an agent that has not seen these write it from the category definitions, then recompute its register and labels before use. Never change a label after seeing a reviewer's results.
