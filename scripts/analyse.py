#!/usr/bin/env python3
"""Deep analysis of one file through the governed pipeline, exported as
verified figures: the input to a dashboard, a deck or a review.

    python scripts/analyse.py sales.xlsx --out analysis.json
    python scripts/analyse.py data.csv --mapping mapping.json --goal "Why did margin fall?"
    python scripts/analyse.py data.csv --suggest --language ar --out analysis.json --csv-dir aggregates/

It runs the same pipeline as the app: the reader from ADR 0024, the column
mapping from ADR 0025, and every specialist stage up to the approval
gate. It uses a throwaway SQLite database and deterministic narration, so
no model is called and it costs nothing. The export holds calculations
(each with its method), claims (each with the calculations behind it),
quality checks, charts and headlines: never the rows. --csv-dir also
writes the aggregates (totals by group, the trend, the KPIs) as small CSV
files a dashboard can use as datasets. Tier 0 of docs/AGENT_TEAM.md.
"""

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import datasets as reader  # noqa: E402
from server.model_gateway import ModelGateway  # noqa: E402
from server.runs import RunEngine  # noqa: E402
from server.storage import open_store  # noqa: E402

OWNER = "analyst"
# Stage outputs that hold rows; only their calculations and claims leave.
ROW_STAGES = {"collector", "cleaner"}
KEEP_FROM_PREPARER = ("measure", "group_col", "date_col", "date_grain", "groups", "group_counts",
                      "trend", "trend_counts", "total")


def analyse(path, goal=None, mapping=None, suggest=False, language="en", glossary=None):
    path = Path(path)
    parsed = reader.read(path.read_bytes(), path.name)
    with tempfile.TemporaryDirectory() as tmp:
        store = open_store(sqlite_path=str(Path(tmp) / "analysis.db"))
        engine = RunEngine(store, Path(tmp) / "vault", ModelGateway(env={}),
                           glossary=glossary or {"metrics": [], "problems": []})
        dataset, _ = engine.store_upload(parsed, path.name, OWNER)
        used = None
        if mapping or suggest:
            chosen = mapping or engine.dataset_detail(dataset["id"], OWNER)["suggestion"]
            used = engine.save_mapping(dataset["id"], OWNER, chosen)["mapping"]
        run = engine.create_run(goal or f"Analyse {path.name} and produce a business report",
                                owner=OWNER, dataset_id=dataset["id"], language=language)
        for _ in range(200):
            run = engine.advance(run["id"])
            if run["state"] not in ("queued", "running"):
                break
        tasks = store.get_tasks(run["id"])
        calculations, claims, checks, stages, prepared = [], [], [], [], {}
        for task in tasks:
            result = json.loads(task["result_json"]) if task["result_json"] else {}
            stages.append({"role": task["role"], "state": task["state"], "summary": task["summary"]})
            for calc in result.get("calculations", []):
                calculations.append({"ref": f"{task['role']}.{calc['id']}", "stage": task["role"], **calc})
            for claim in result.get("claims", []):
                claims.append({"stage": task["role"], **claim})
            for check in result.get("quality_checks", []):
                checks.append({"stage": task["role"], **check})
            if task["role"] == "preparer":
                output = result.get("output", {})
                prepared = {k: output.get(k) for k in KEEP_FROM_PREPARER}
        return {
            "dataset": {"name": path.name, "format": parsed.source_format, "rows": len(parsed.rows),
                        "columns": parsed.columns, "sha256": dataset["sha256"]},
            "goal": run["goal"], "language": language, "state": run["state"], "error": run.get("error"),
            "mapping": used, "prepared": prepared,
            "headlines": [{"type": r["type"], "title": r["title"], "headline": r["headline"]}
                          for r in run.get("reports", [])],
            "charts": run.get("charts", []),
            "stages": stages, "calculations": calculations, "claims": claims,
            "failed_checks": [c for c in checks if not c.get("passed", True)],
        }


def write_aggregates(analysis, folder):
    """Small CSV files of aggregates, each fit to be a dashboard dataset."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    prepared, written = analysis["prepared"], []
    # Each total travels with its record count and per-record value, so a
    # dashboard can compare groups or periods of different sizes (ADR 0026).
    for key, counts_key, label, name in (("groups", "group_counts", "group_col", "by_group.csv"),
                                         ("trend", "trend_counts", "date_col", "trend.csv")):
        totals = prepared.get(key)
        if not totals:
            continue
        counts = prepared.get(counts_key) or {}
        items = sorted(totals.items(), key=lambda kv: -kv[1]) if key == "groups" else totals.items()
        target = folder / name
        with target.open("w", newline="", encoding="utf-8") as handle:
            out = csv.writer(handle)
            out.writerow([prepared[label], prepared["measure"], "records", "per_record"])
            for label_value, total in items:
                n = counts.get(label_value)
                out.writerow([label_value, total, n if n else "", round(total / n, 2) if n else ""])
        written.append(target)
    target = folder / "calculations.csv"
    with target.open("w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow(["ref", "stage", "name", "value", "method"])
        for calc in analysis["calculations"]:
            if isinstance(calc.get("value"), (int, float)) and not isinstance(calc.get("value"), bool):
                out.writerow([calc["ref"], calc["stage"], calc["name"], calc["value"], calc.get("method", "")])
    written.append(target)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("file", help="CSV, TSV, XLSX, JSON or JSON Lines")
    parser.add_argument("--goal")
    parser.add_argument("--mapping", help="a column mapping JSON (ADR 0025)")
    parser.add_argument("--suggest", action="store_true", help="accept the suggested mapping")
    parser.add_argument("--language", default="en", choices=("en", "ar"))
    parser.add_argument("--out", help="write the analysis JSON here (default: standard output)")
    parser.add_argument("--csv-dir", help="also write aggregate CSV files here")
    args = parser.parse_args(argv)
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
    try:
        analysis = analyse(args.file, args.goal, mapping, args.suggest, args.language)
    except reader.DatasetError as error:
        print(f"analyse: {error.message(args.language)}", file=sys.stderr)
        return 2
    except Exception as error:  # a mapping refusal names every problem
        detail = getattr(error, "detail", None)
        print(f"analyse: {json.dumps(detail(args.language), ensure_ascii=False) if callable(detail) else error}",
              file=sys.stderr)
        return 2
    text = json.dumps(analysis, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.csv_dir:
        for path in write_aggregates(analysis, args.csv_dir):
            print(f"wrote {path}", file=sys.stderr)
    print(f"analyse: {analysis['state']} · {len(analysis['calculations'])} calculations · "
          f"{len(analysis['claims'])} claims · {len(analysis['failed_checks'])} failed checks", file=sys.stderr)
    return 0 if analysis["state"] in ("awaiting_approval", "completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
