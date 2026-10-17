#!/usr/bin/env python3
"""Score a reviewer agent's findings against a seeded benchmark.

    python scripts/score_review.py --bench evals/reviewers/A --findings run.txt [--categories causal_claim,overclaim]

The benchmarks in evals/reviewers/ are synthetic memos with numbered
paragraphs and planted defects (labels.json). A reviewer returns findings in
the agent team's format, naming the paragraph and a category:

    FINDING F1 · major · P05
    Category: causal_claim

Each (paragraph, category) pair is one item: a planted defect the reviewer
names is a true positive and one it misses a false negative. `--categories`
limits the score to the categories an agent is responsible for (its lane).

Three views, because one number hides how a reviewer goes wrong:

- lane recall: planted (paragraph, category) pairs named exactly;
- detection: is a defective paragraph flagged at all, and is every flagged
  paragraph defective? A finding on a correct paragraph is a false alarm;
- the category confusion matrix: for each planted defect in the lane, the
  category the reviewer gave it ("missed" when it gave none).

The memos plant one category per paragraph, but a paragraph can be wrong in
two ways (an unsourced figure inside a causal claim). A finding of another
category on a defective paragraph is listed as secondary, not as a false
alarm. Standard library only (ADR 0027).
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_agents as ev  # noqa: E402


def findings_in(text):
    """[(paragraphs, category)] from FINDING blocks."""
    out = []
    blocks = re.split(r"(?=^\s*\**FINDING\b)", text, flags=re.M)
    for block in blocks:
        if not re.match(r"\s*\**FINDING\b", block):
            continue
        header = block.splitlines()[0]
        paragraphs = set(re.findall(r"\bP\d{2}\b", header)) or set(re.findall(r"\bP\d{2}\b", block[:400]))
        category = re.search(r"Category:\s*\**\s*([a-z_]+)", block)
        out.append((paragraphs, category.group(1) if category else "uncategorised"))
    return out


def figures_tool_findings(bench):
    """The Tier 0 checker as a reviewer: figures_check's sourcing and
    arithmetic passes over the memo, as FINDING blocks by paragraph."""
    import figures_check
    bench = Path(bench)
    memo = bench / "memo.md"
    register = figures_check.load_register(bench / "register.csv", "Expected", ["Check"])
    result = figures_check.check(register, [memo], sourcing_only=True)
    paragraphs = dict(re.findall(r"\[(P\d{2})\]\s*(.+)", memo.read_text(encoding="utf-8")))
    out = []
    for item in result["unsourced"]:
        for pid, text in paragraphs.items():
            if item["number"] in figures_check.numbers_in(figures_check.normalise(text)):
                out.append(f"FINDING T{len(out) + 1:02d} · major · {pid}\nCategory: unsourced_figure\n"
                           f"Evidence: {item['number']} is not in the register.")
    for item in result["wrong_arithmetic"]:
        for pid, text in paragraphs.items():
            if item["result"] in figures_check.normalise(text):
                out.append(f"FINDING T{len(out) + 1:02d} · major · {pid}\nCategory: arithmetic\n"
                           f"Evidence: “{item['shown']}” computes to {item['computed']}.")
    return "\n\n".join(out) + "\n"


def score(bench, text, categories=None):
    labels = json.loads((Path(bench) / "labels.json").read_text(encoding="utf-8"))
    categories = categories or labels["categories"]
    defects = labels["defects"]
    found = findings_in(text)
    named = {(p, c) for ps, c in found for p in ps}
    flagged = {p for ps, _ in found for p in ps}
    given = {}
    for ps, c in found:
        for p in ps:
            given.setdefault(p, []).append(c)
    per_category = {}
    for category in categories:
        pairs = []
        for paragraph in labels["paragraphs"]:
            truth = category in defects.get(paragraph, [])
            # Another category on a defective paragraph is secondary, not a false alarm.
            if not truth and paragraph in defects and (paragraph, category) in named:
                continue
            pairs.append((truth, (paragraph, category) in named, f"{paragraph} · {category}"))
        all_labels, matrix = ev.confusion(pairs, [True, False])
        per_category[category] = {"matrix": {str(t): {str(p): n for p, n in row.items()} for t, row in matrix.items()},
                                  **ev.scores(all_labels, matrix, positive=True),
                                  "misses": [w for t, p, w in pairs if t and not p],
                                  "false_alarms": [w for t, p, w in pairs if p and not t]}
    # Detection: a lane defect flagged at all; a flag on a correct paragraph is a false alarm.
    lane = {p for p, cs in defects.items() if set(cs) & set(categories)}
    pairs = [(p in lane, p in flagged, p) for p in labels["paragraphs"] if p in lane or p not in defects]
    all_labels, matrix = ev.confusion(pairs, [True, False])
    # Category confusion: what the reviewer called each planted defect in its lane.
    planted = [(c, p) for p, cs in defects.items() for c in cs if c in categories]
    called = [(c, c if c in given.get(p, []) else (given[p][0] if p in given else "missed"), p) for c, p in planted]
    confusion_labels, confusion_matrix = ev.confusion(called, list(categories) + ["missed"])
    secondary = sorted(f"{p} · {c}" for p, c in named if p in defects and c not in defects[p])
    tp = sum(1 for c, p in planted if (p, c) in named)
    return {"bench": str(bench), "categories": categories, "findings": len(found),
            "recall": tp / len(planted) if planted else None,
            "detection": ev.scores(all_labels, matrix, positive=True),
            "false_alarms": sorted(f"{p} · {c}" for p, c in named if p not in defects),
            "secondary": secondary,
            "category_confusion": {"labels": confusion_labels,
                                   "matrix": {t: dict(row) for t, row in confusion_matrix.items()}},
            "per_category": per_category}


# What each reviewer is responsible for. The team is scored on every category.
LANES = {"figures-tool": ["unsourced_figure", "arithmetic"],
         "figures-auditor": ["unsourced_figure", "arithmetic"],
         "analytics-expert-reviewer": ["causal_claim", "denominator", "overclaim"]}
RUN = re.compile(r"^(?P<agent>%s)-(?P<bench>[A-Z])-(?P<tag>[\w-]+)\.txt$" % "|".join(LANES))
REVIEWERS = Path(__file__).resolve().parent.parent / "evals" / "reviewers"


def summary(folder=REVIEWERS):
    """Every saved run in evals/reviewers/runs, scored in its lane, plus the
    team (both reviewers' findings together) wherever both ran under one tag."""
    rows, texts = [], {}
    for path in sorted((folder / "runs").glob("*.txt")):
        match = RUN.match(path.name)
        if not match:
            continue
        agent, bench, tag = match["agent"], match["bench"], match["tag"]
        text = path.read_text(encoding="utf-8")
        texts.setdefault((bench, tag), {})[agent] = text
        rows.append({**score(folder / bench, text, LANES[agent]), "agent": agent, "bench": bench, "tag": tag})
    for (bench, tag), by_agent in sorted(texts.items()):
        if {"figures-auditor", "analytics-expert-reviewer"} <= set(by_agent):
            text = by_agent["figures-auditor"] + "\n\n" + by_agent["analytics-expert-reviewer"]
            rows.append({**score(folder / bench, text), "agent": "team", "bench": bench, "tag": tag})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bench")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--summary", action="store_true", help="score every saved run in evals/reviewers/runs")
    source.add_argument("--findings", help="the reviewer's reply, as text")
    source.add_argument("--figures-tool", action="store_true",
                        help="score scripts/figures_check.py itself, the Tier 0 reviewer")
    parser.add_argument("--categories", help="comma-separated; default all")
    parser.add_argument("--json", help="also write the score here")
    args = parser.parse_args(argv)
    if args.summary:
        rows = summary()
        for r in rows:
            print(f"{r['agent']:26} {r['bench']} {r['tag']:14} lane recall {ev.pct(r['recall']):>5} · "
                  f"detection {ev.pct(r['detection']['recall']):>5} / precision {ev.pct(r['detection']['precision']):>5}"
                  f" · false alarms {len(r['false_alarms'])}")
        if args.json:
            Path(args.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")
        return 0
    if not args.bench:
        parser.error("--bench is needed with --findings or --figures-tool")
    text = (figures_tool_findings(args.bench) if args.figures_tool
            else Path(args.findings).read_text(encoding="utf-8"))
    result = score(args.bench, text, args.categories.split(",") if args.categories else None)
    print(f"{result['bench']}: {result['findings']} findings · category recall {ev.pct(result['recall'])} · "
          f"paragraph detection recall {ev.pct(result['detection']['recall'])}, "
          f"precision {ev.pct(result['detection']['precision'])}")
    for name, c in result["per_category"].items():
        print(f"  {name:18} recall {ev.pct(c['recall'])} precision {ev.pct(c['precision'])}"
              f"  misses {c['misses'] or '–'}  false alarms {c['false_alarms'] or '–'}")
    labels = result["category_confusion"]["labels"]
    print("  confusion (planted → called): " + "; ".join(
        f"{t} → " + ", ".join(f"{p} {n}" for p, n in row.items() if n)
        for t, row in result["category_confusion"]["matrix"].items() if any(row.values())))
    print(f"  false alarms on correct paragraphs: {result['false_alarms'] or '–'}")
    print(f"  secondary (another true problem on a defective paragraph): {result['secondary'] or '–'}")
    del labels
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
