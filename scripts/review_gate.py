#!/usr/bin/env python3
"""Run a deliverable's review gates and keep the score, round by round.

    python scripts/review_gate.py plan.json            # run every gate, record the round
    python scripts/review_gate.py plan.json --reset    # start the count again; old rounds are archived
    python scripts/review_gate.py plan.json --json     # the scorecard as JSON

The deterministic half of the review loop (docs/AGENT_TEAM.md, section 3).
A plan names gates; this runs them, prints a scorecard, and says whether
the loop should continue or stop. Kinds of gate:

    command    {"run": "python scripts/verify.py --quick"}   passes on exit 0
    figures    {"register": "kpis.csv", "docs": [...], "reference": [...]}
    pdf_pages  {"file": "report.pdf", "min": 20, "max": 25}
    absent     {"files": [...], "patterns": ["Draft for review"]}   regexes that must not match
    present    {"files": [...], "patterns": ["Executive summary"]}  regexes that must match
    exists     {"files": [...]}

100% means every gate passes or is accepted in the plan by a named person
with a reason. The loop stops at 100%, after `max_rounds` (default 5), or
after two rounds in a row with no gain. Round history is kept in
.claude/state/reviews/, which Git ignores. Paths in a plan are relative to
the plan. Standard library only; figures and PDFs use figures_check.py.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figures_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".claude" / "state" / "reviews"
KINDS = ("command", "figures", "pdf_pages", "absent", "present", "exists")


def _paths(base, items):
    return [Path(p) if Path(p).is_absolute() else (base / p) for p in items]


def pdf_pages(path):
    if shutil.which("pdfinfo"):
        done = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True)
        match = re.search(r"^Pages:\s+(\d+)", done.stdout, re.M)
        if match:
            return int(match.group(1))
    raise RuntimeError("cannot count PDF pages: install poppler-utils (pdfinfo)")


def run_gate(gate, base):
    """(status, detail): status is 'pass' or 'fail'."""
    kind = gate["type"]
    if kind == "command":
        done = subprocess.run(gate["run"], shell=True, cwd=gate.get("cwd", ROOT),
                              capture_output=True, text=True, timeout=gate.get("timeout", 1800))
        tail = (done.stdout + done.stderr).strip().splitlines()[-3:]
        return ("pass" if done.returncode == 0 else "fail"), " / ".join(tail)[:400]
    if kind == "exists":
        missing = [p.name for p in _paths(base, gate["files"]) if not p.exists()]
        return ("fail", "missing: " + ", ".join(missing)) if missing else ("pass", "all present")
    if kind == "pdf_pages":
        pages = pdf_pages(_paths(base, [gate["file"]])[0])
        ok = gate.get("min", 0) <= pages <= gate.get("max", 10**6)
        return ("pass" if ok else "fail"), f"{pages} pages (allowed {gate.get('min', 0)}–{gate.get('max', '∞')})"
    if kind in ("absent", "present"):
        hits = []
        for path in _paths(base, gate["files"]):
            text = figures_check.read_text(path)
            for pattern in gate["patterns"]:
                count = len(re.findall(pattern, text))
                if (kind == "absent" and count) or (kind == "present" and not count):
                    hits.append(f"{path.name}: “{pattern}” {'×' + str(count) if count else 'not found'}")
        return ("fail", "; ".join(hits)[:600]) if hits else ("pass", "as required")
    if kind == "figures":
        register = figures_check.load_register(_paths(base, [gate["register"]])[0],
                                               gate.get("value_column", "Expected"),
                                               gate.get("label_columns", "Check,Filter").split(","))
        result = figures_check.check(register, _paths(base, gate["docs"]),
                                     _paths(base, gate.get("reference", [])),
                                     gate.get("sourcing_only", False))
        detail = f"{result['found']}/{result['register_values']} register values found"
        if result["missing"]:
            detail += "; missing: " + ", ".join(f"{m['label']} {m['value']}" for m in result["missing"][:8])
        if result["unsourced"]:
            detail += "; unsourced: " + ", ".join(f"{u['doc']} {u['number']}" for u in result["unsourced"][:8])
        return ("pass" if result["passed"] else "fail"), detail
    raise ValueError(f"unknown gate type “{kind}”; use one of {', '.join(KINDS)}")


def validate_plan(plan):
    problems = []
    ids = [g.get("id") for g in plan.get("gates", [])]
    if not plan.get("name") or not re.fullmatch(r"[\w.-]{1,64}", plan["name"]):
        problems.append("the plan needs a short `name` (letters, digits, - . _)")
    if not ids:
        problems.append("the plan has no gates")
    if len(set(ids)) != len(ids) or None in ids:
        problems.append("every gate needs a unique `id`")
    for gate in plan.get("gates", []):
        if gate.get("type") not in KINDS:
            problems.append(f"gate {gate.get('id')}: type must be one of {', '.join(KINDS)}")
    for item in plan.get("accepted", []):
        if item.get("gate") not in ids:
            problems.append(f"an acceptance names no gate: {item.get('gate')}")
        if not (item.get("by") and item.get("reason")):
            problems.append(f"accepting {item.get('gate')} needs `by` (a person) and a `reason`")
    return problems


def decide(rounds, max_rounds):
    """continue, or why to stop."""
    latest = rounds[-1]
    if latest["score"] >= 100:
        return "stop: 100% validated"
    if len(rounds) >= max_rounds:
        return f"stop: {max_rounds} rounds reached; report what is left and whose it is"
    if len(rounds) >= 3 and rounds[-1]["score"] <= rounds[-2]["score"] <= rounds[-3]["score"]:
        return "stop: no gain in two rounds; report what is left and whose it is"
    return "continue: fix the failing gates and the reviewers' findings, then run again"


def review(plan_path, reset=False, state_dir=STATE):
    plan_path = Path(plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    problems = validate_plan(plan)
    if problems:
        raise ValueError("; ".join(problems))
    base = plan_path.parent
    accepted = {a["gate"]: a for a in plan.get("accepted", [])}
    results = []
    for gate in plan["gates"]:
        started = time.monotonic()
        try:
            status, detail = run_gate(gate, base)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            status, detail = "fail", f"could not run: {error}"
        if status == "fail" and gate["id"] in accepted:
            status = "accepted"
            detail += f" · accepted by {accepted[gate['id']]['by']}: {accepted[gate['id']]['reason']}"
        results.append({"id": gate["id"], "type": gate["type"], "status": status, "detail": detail,
                        "owner": gate.get("owner"), "seconds": round(time.monotonic() - started, 1)})
    done = sum(r["status"] in ("pass", "accepted") for r in results)
    score = round(100 * done / len(results), 1)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{plan['name']}.json"
    if reset and state_file.exists():
        # Starting again never loses the record: the old rounds are kept beside it.
        state_file.rename(state_file.with_name(f"{plan['name']}.{time.strftime('%Y%m%dT%H%M%S')}.json"))
    rounds = [] if not state_file.exists() else json.loads(state_file.read_text())["rounds"]
    rounds.append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "score": score,
                   "failing": [r["id"] for r in results if r["status"] == "fail"]})
    state_file.write_text(json.dumps({"plan": str(plan_path), "rounds": rounds}, indent=2))
    return {"plan": plan["name"], "round": len(rounds), "score": score,
            "passed": sum(r["status"] == "pass" for r in results),
            "accepted": sum(r["status"] == "accepted" for r in results),
            "failed": sum(r["status"] == "fail" for r in results),
            "gates": results, "history": [r["score"] for r in rounds],
            "decision": decide(rounds, plan.get("max_rounds", 5))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("plan")
    parser.add_argument("--reset", action="store_true",
                        help="start the round count again; the old rounds are kept in a dated file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        card = review(args.plan, args.reset)
    except (OSError, ValueError) as error:
        print(f"review_gate: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(card, ensure_ascii=False, indent=2))
    else:
        print(f"{card['plan']} · round {card['round']} · {card['score']}% "
              f"({card['passed']} passed, {card['accepted']} accepted, {card['failed']} failed) "
              f"· history {' → '.join(f'{s}%' for s in card['history'])}")
        for gate in card["gates"]:
            owner = f" [{gate['owner']}]" if gate.get("owner") else ""
            print(f"  {gate['status'].upper():8} {gate['id']}{owner}: {gate['detail']}")
        print(card["decision"])
    return 0 if card["score"] >= 100 else 1


if __name__ == "__main__":
    raise SystemExit(main())
