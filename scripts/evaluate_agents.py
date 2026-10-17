#!/usr/bin/env python3
"""Measure every classifying agent: confusion matrix, precision, recall and F1.

    python scripts/evaluate_agents.py                     # every suite, dev and holdout
    python scripts/evaluate_agents.py --suite intent --misses   # what the dev cases got wrong
    python scripts/evaluate_agents.py --json out.json --html report.html
    python scripts/evaluate_agents.py --check             # exit 1 when a suite falls below its floor

Tier 0 of docs/AGENT_TEAM.md: no model, no tokens. Each suite in `evals/`
holds labelled cases in two splits:

- `dev`: cases used to find and fix misses;
- `holdout`: cases written at the same time, scored before and after the
  fixes but never used to choose them.

So the holdout recall says how well a fix generalises, not how well it was
fitted. `--misses` shows dev cases only. The floors in `evals/floors.json`
are the recall each suite must keep; `tests/test_evals.py` enforces them
(ADR 0027). Standard library only.
"""

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
EVALS = ROOT / "evals"
THEME = ROOT / ".claude" / "skills" / "rta-style" / "tokens.css"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def confusion(pairs, labels):
    """{truth: {predicted: count}} over the given labels, plus any label a
    predictor produced that the suite does not list."""
    labels = list(labels)
    for _, predicted, _ in pairs:
        if predicted not in labels:
            labels.append(predicted)
    matrix = {t: {p: 0 for p in labels} for t in labels}
    for truth, predicted, _ in pairs:
        matrix[truth][predicted] += 1
    return labels, matrix


def scores(labels, matrix, positive=None):
    """Per-class precision, recall, F1 and support; accuracy; macro recall
    over the classes that occur. For a detector, `positive` names the class
    whose recall is the headline: the share of real cases it catches."""
    per_class, total, right = {}, 0, 0
    for label in labels:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        predicted = sum(matrix[t][label] for t in labels)
        precision = tp / predicted if predicted else None
        recall = tp / support if support else None
        f1 = (2 * precision * recall / (precision + recall)
              if precision and recall else (0.0 if support else None))
        per_class[str(label)] = {"precision": precision, "recall": recall, "f1": f1,
                                 "support": support, "predicted": predicted}
        total += support
        right += tp
    recalls = [c["recall"] for c in per_class.values() if c["support"]]
    out = {"per_class": per_class, "accuracy": right / total if total else None,
           "macro_recall": sum(recalls) / len(recalls) if recalls else None, "cases": total}
    if positive is not None:
        out["positive"] = str(positive)
        out["recall"] = per_class[str(positive)]["recall"]
        out["precision"] = per_class[str(positive)]["precision"]
    return out


# ---------------------------------------------------------------------------
# Predictors: each returns [(truth, predicted, what)] for a split
# ---------------------------------------------------------------------------

def _intent(cases):
    import assistant
    return [(c["label"], assistant.understand(c["text"])["action"], c["text"]) for c in cases]


def _tables(cases):
    from server import mapping
    for case in cases:
        columns, rows = mapping.table(case["csv"])
        yield case, columns, rows


def _roles(cases):
    from server import mapping
    out = []
    for case, columns, rows in _tables(cases):
        roles = mapping.suggest(columns, rows)["roles"]
        out += [(case["roles"][c], roles.get(c), f"{case['name']} · {c}") for c in columns]
    return out


def _personal(cases):
    from server import analytics
    out = []
    for case, columns, rows in _tables(cases):
        flagged = {f["column"] for f in analytics.personal_data_findings(columns, rows)}
        out += [(case["personal"][c], c in flagged, f"{case['name']} · {c}") for c in columns]
    return out


def _router(cases):
    from server import routing
    every = [{"provider": p} for p in ("ollama", "anthropic", "groq", "deterministic")]
    return [(c["label"], routing.provider_for(c["text"], every) or "none", c["text"] or "(empty)")
            for c in cases]


def _raw(cases):
    import consult
    return [(c["label"], consult.looks_like_raw_rows(c["text"]), c["text"][:60].replace("\n", " ⏎ "))
            for c in cases]


def _jargon(cases):
    from server import analytics
    return [(c["label"], bool(analytics._jargon_in(c["text"])), c["text"]) for c in cases]


def _causal(cases):
    try:
        import claims_lint
    except ImportError:
        return None   # no zero-cost causal check existed before ADR 0027
    return [(c["label"], bool(claims_lint.causal_phrases(c["text"])), c["text"]) for c in cases]


def _figures(cases):
    """Each figure in a document is one item: bad ones should be flagged."""
    import figures_check as fc
    out = []
    for i, case in enumerate(cases):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            doc, ref = Path(tmp) / "doc.md", Path(tmp) / "ref.md"
            doc.write_text(case["doc"], encoding="utf-8")
            ref.write_text(case["reference"], encoding="utf-8")
            register = [{"label": k, "value": v} for k, v in case["register"].items()]
            result = fc.check(register, [doc], [ref], sourcing_only=True)
            text = fc.read_text(doc)
            flagged = {u["number"] for u in result["unsourced"]}
            flagged |= {w["result"] for w in result.get("wrong_arithmetic", [])}
            normal = {fc.normalise(b) for b in case["bad"]}
            universe = set(fc.numbers_in(text)) | normal
            for token in sorted(universe):
                truth = token in normal
                out.append((truth, token in flagged, f"case {i + 1} · {token}"))
    return out


SUITES = {
    "intent": {"file": "intent.json", "predict": _intent, "agent": "Assistant: what a chat sentence asks for",
               "module": "assistant.understand"},
    "column_roles": {"file": "datasets.json", "predict": _roles, "agent": "Column mapping: each column's role",
                     "module": "server/mapping.suggest"},
    "personal_data": {"file": "datasets.json", "predict": _personal, "positive": True,
                      "labels": [True, False], "agent": "Privacy Agent: columns holding personal data",
                      "module": "server/analytics.personal_data_findings"},
    "router": {"file": "router.json", "predict": _router, "agent": "Model router: which provider a model name means",
               "module": "server/routing.provider_for"},
    "raw_guard": {"file": "raw_guard.json", "predict": _raw, "positive": True,
                  "agent": "Raw-data guard: rows that must not reach a model", "module": "scripts/consult.looks_like_raw_rows"},
    "jargon": {"file": "jargon.json", "predict": _jargon, "positive": True,
               "agent": "Validator: statistical jargon in claims", "module": "server/analytics._jargon_in"},
    "causal": {"file": "causal.json", "predict": _causal, "positive": True,
               "agent": "Claims lint: causal wording in deliverables", "module": "scripts/claims_lint.causal_phrases"},
    "figures": {"file": "figures.json", "predict": _figures, "positive": True, "labels": [True, False],
                "agent": "Figures check: unsourced or wrong figures", "module": "scripts/figures_check.check"},
}


def run_suite(name):
    spec = SUITES[name]
    data = json.loads((EVALS / spec["file"]).read_text(encoding="utf-8"))
    labels = spec.get("labels") or data["labels"]
    result = {"suite": name, "agent": spec["agent"], "module": spec["module"], "about": data.get("about", "")}
    for split in ("dev", "holdout"):
        pairs = spec["predict"](data[split])
        if pairs is None:
            result[split] = None
            continue
        all_labels, matrix = confusion(pairs, labels)
        result[split] = {"labels": [str(l) for l in all_labels],
                         "matrix": {str(t): {str(p): n for p, n in row.items()} for t, row in matrix.items()},
                         **scores(all_labels, matrix, spec.get("positive")),
                         "misses": [{"item": what, "truth": str(t), "predicted": str(p)}
                                    for t, p, what in pairs if t != p]}
    return result


def headline(split):
    """The recall a suite is judged by: positive-class recall for a
    detector, macro recall for a multi-class agent."""
    if not split:
        return None
    return split.get("recall") if "positive" in split else split.get("macro_recall")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def pct(value):
    return "–" if value is None else f"{value:.0%}"


def print_results(results, misses):
    for r in results:
        print(f"\n{r['suite']} · {r['agent']} ({r['module']})")
        for split in ("dev", "holdout"):
            s = r[split]
            if s is None:
                print(f"  {split:8} not available")
                continue
            kind = f"recall {pct(s['recall'])}, precision {pct(s['precision'])}" if "positive" in s \
                else f"macro recall {pct(s['macro_recall'])}"
            print(f"  {split:8} {s['cases']:3} cases · accuracy {pct(s['accuracy'])} · {kind}")
        if misses and r["dev"]:
            for m in r["dev"]["misses"]:
                print(f"    MISS  {m['item']}: expected {m['truth']}, got {m['predicted']}")


BENCHES = {"A": "A · dev", "B": "B · held out", "C": "C · blind"}


def matrix_table(labels, matrix, caption):
    peak = max([max(row.values()) for row in matrix.values()] + [1])
    head = "".join(f"<th scope='col'>{html.escape(str(p))}</th>" for p in labels)
    body = ""
    for t in labels:
        if t not in matrix or not sum(matrix[t].values()):
            continue
        cells = "".join(f"<td class='{'hit' if t == p else ('miss' if n else '')}' style='--w:{n / peak:.2f}'>{n}</td>"
                        for p, n in matrix[t].items())
        body += f"<tr><th scope='row'>{html.escape(str(t))}</th>{cells}</tr>"
    return (f"<div class='scroll'><table class='cm'><caption>{html.escape(caption)}</caption>"
            f"<thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table></div>")


def render_reviewers(rows):
    """The reviewer benchmark (evals/reviewers): every saved run, and the
    category confusion of each controlled run."""
    if not rows:
        return ""
    table = "".join(
        f"<tr><td>{html.escape(r['agent'])}</td><td>{BENCHES.get(r['bench'], r['bench'])}</td>"
        f"<td>{html.escape(r['tag'])}</td><td class='num'>{pct(r['recall'])}</td>"
        f"<td class='num'>{pct(r['detection']['recall'])}</td><td class='num'>{pct(r['detection']['precision'])}</td>"
        f"<td class='num'>{len(r['false_alarms'])}</td></tr>" for r in rows)
    cards = "".join(
        f"<div class='card'><h3>{html.escape(r['agent'])} · {BENCHES.get(r['bench'], r['bench'])} · {r['tag']}</h3>"
        f"<p class='kpi'>Lane recall <b>{pct(r['recall'])}</b> · false alarms {len(r['false_alarms'])}</p>"
        + matrix_table(r["category_confusion"]["labels"], r["category_confusion"]["matrix"],
                       "Rows: the planted defect. Columns: what the reviewer called it.") + "</div>"
        for r in rows if r["tag"].startswith("ctl-") or r["agent"] == "figures-tool")
    return f"""<section><h2>Reviewers on seeded memos</h2>
<p class="muted">Three synthetic memos with planted defects (<code>evals/reviewers/</code>): A was used to choose fixes, B is held out
(same author), C was written blind by an independent agent. <b>ctl</b> runs give a model of the reviewer's tier the v1 or v2
instructions, with nothing else changed; <b>named</b> runs are the project subagents as loaded. Scored by <code>scripts/score_review.py</code>.</p>
<div class="scroll"><table class="cm runs"><thead><tr><th>Reviewer</th><th>Memo</th><th>Run</th><th>Lane recall</th>
<th>Detection recall</th><th>Detection precision</th><th>False alarms</th></tr></thead><tbody>{table}</tbody></table></div>
<div class="grid">{cards}</div></section>"""


def _pill(value):
    """A recall as a status pill: 90% and over good, 75% and over fair, else weak."""
    if value is None:
        return "–"
    kind, word = (("good", "good") if value >= 0.9 else ("warn", "fair") if value >= 0.75 else ("bad", "weak"))
    return f"<span class='pill pill--{kind}'>{pct(value)} · {word}</span>"


def render_glance(results):
    rows = "".join(
        f"<tr><th scope='row'>{html.escape(r['agent'])}</th><td><code>{html.escape(r['module'])}</code></td>"
        f"<td>{_pill(headline(r['dev']))}</td><td>{_pill(headline(r['holdout']))}</td>"
        f"<td class='num'>{r['holdout']['cases'] if r['holdout'] else '–'}</td></tr>" for r in results)
    return f"""<section><h2>At a glance</h2>
<p class="muted">Headline recall: the share of real cases each agent gets right (macro recall for agents with several labels).
Dev cases were used to find fixes; holdout cases were not, and the text classifiers' holdouts were written blind.</p>
<div class="scroll"><table class="cm runs"><thead><tr><th>Agent</th><th>Module</th><th>Dev</th><th>Holdout</th>
<th>Holdout cases</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""


def render_html(results, reviewers=None):
    """The report as one page, in the house style (.claude/skills/rta-style)."""
    css = THEME.read_text(encoding="utf-8") if THEME.exists() else ""
    parts = [render_glance(results)]
    for r in results:
        cards = []
        for split in ("dev", "holdout"):
            s = r[split]
            if s is None:
                cards.append(f'<div class="card"><h3>{split}</h3><p class="muted">Not available before ADR 0027.</p></div>')
                continue
            labels = s["labels"]
            peak = max(max(row.values()) for row in s["matrix"].values()) or 1
            head = "".join(f"<th scope='col'>{html.escape(p)}</th>" for p in labels)
            body = ""
            for t in labels:
                if not sum(s["matrix"][t].values()) and not any(s["matrix"][x][t] for x in labels):
                    continue
                cells = "".join(
                    f"<td class='{'hit' if t == p else ('miss' if n else '')}' style='--w:{n / peak:.2f}'>{n}</td>"
                    for p, n in s["matrix"][t].items())
                rec = s["per_class"][t]["recall"]
                body += f"<tr><th scope='row'>{html.escape(t)}</th>{cells}<td class='num'>{pct(rec)}</td></tr>"
            kind = (f"Recall <b>{pct(s['recall'])}</b> · precision {pct(s['precision'])}" if "positive" in s
                    else f"Macro recall <b>{pct(s['macro_recall'])}</b>")
            cards.append(f"""<div class="card"><h3>{split} · {s['cases']} cases</h3>
<p class="kpi">{kind} · accuracy {pct(s['accuracy'])}</p>
<div class="scroll"><table class="cm"><caption>Rows: true label. Columns: predicted. Last column: recall.</caption>
<thead><tr><th></th>{head}<th scope='col'>Recall</th></tr></thead><tbody>{body}</tbody></table></div></div>""")
        parts.append(f"""<section><h2>{html.escape(r['agent'])}</h2>
<p class="muted"><code>{html.escape(r['module'])}</code> · {html.escape(r['about'])}</p>
<div class="grid">{''.join(cards)}</div></section>""")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Agentic OS evaluation</title>
<style>{css}
.cm{{border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:.85rem}}
.cm th,.cm td{{border:1px solid var(--border);padding:.3rem .5rem;text-align:center}}
.cm caption{{caption-side:bottom;font-size:.75rem;color:var(--muted);text-align:start;padding-top:.3rem}}
.cm td.hit{{background:color-mix(in srgb,var(--status-good) calc(var(--w)*45%),transparent)}}
.cm td.miss{{background:color-mix(in srgb,var(--brand) calc(20% + var(--w)*40%),transparent);color:var(--text)}}
.scroll{{overflow-x:auto}} .kpi b{{font-size:1.2rem}}
.cm.runs td{{text-align:start}} .cm.runs td.num{{text-align:end}}
</style></head><body><header class="brandbar"><div class="page"><p class="org">Agentic OS · agent evaluation</p>
<h1>Confusion matrices and recall</h1><p class="period">Every classifying agent, on labelled dev and holdout cases. Synthetic data only.</p></div></header>
<main class="page">{''.join(parts)}{render_reviewers(reviewers)}</main></body></html>"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--suite", action="append", choices=sorted(SUITES), help="one suite (repeatable)")
    parser.add_argument("--misses", action="store_true", help="list the dev cases each suite got wrong")
    parser.add_argument("--json", help="write the full results here")
    parser.add_argument("--html", help="write the report page here")
    parser.add_argument("--check", action="store_true", help="exit 1 when a suite is below its floor")
    args = parser.parse_args(argv)
    results = [run_suite(name) for name in (args.suite or SUITES)]
    print_results(results, args.misses)
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if args.html:
        import score_review
        Path(args.html).write_text(render_html(results, score_review.summary()), encoding="utf-8")
    if args.check:
        floors = json.loads((EVALS / "floors.json").read_text(encoding="utf-8"))
        broken = [f"{r['suite']} {split}: {pct(headline(r[split]))} < {pct(floors[r['suite']][split])}"
                  for r in results for split in ("dev", "holdout")
                  if r["suite"] in floors and (headline(r[split]) or 0) + 1e-9 < floors[r["suite"]][split]]
        for line in broken:
            print(f"BELOW FLOOR  {line}", file=sys.stderr)
        return 1 if broken else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
