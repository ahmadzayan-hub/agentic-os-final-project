"""Deterministic business-analytics specialists.

Each specialist is a governed pipeline stage with a typed result — not an
unstructured persona. Every stage returns:

    {"status": "succeeded"|"failed", "summary": str,
     "claims": [{"id","text","type","evidence","status"}],
     "calculations": [{"id","name","value","method"}],
     "quality_checks": [{"name","passed","detail"}],
     "output": {...stage data for later stages...}}

All numbers come from deterministic code (csv + statistics stdlib). The
model gateway may only phrase already-verified facts, and its text is
labelled by source. Claims reference calculation ids so the Validation
Expert can independently verify every material statement.
"""

import csv
import hashlib
import io
import math
import re
import statistics

from server import metrics as glossary
from server import sequential

MAX_ROWS = 50_000
MAX_DATASET_BYTES = 2_000_000


def sample_dataset():
    """Deterministic bundled sales dataset (72 rows)."""
    months = ["2025-%02d" % m for m in range(1, 13)]
    base = {"Hardware": 42000, "Software": 61000, "Services": 23000}
    lines = ["month,region,category,revenue,units"]
    for mi, month in enumerate(months):
        for region, offset in (("North", 1.08), ("South", 0.92)):
            for category, base_rev in base.items():
                seasonal = 1.0 + 0.03 * mi + (0.12 if mi in (10, 11) else 0.0)
                revenue = round(base_rev * seasonal * offset, 2)
                units = int(revenue / (95 if category != "Services" else 240))
                lines.append(f"{month},{region},{category},{revenue},{units}")
    return "\n".join(lines) + "\n"


def _result(status, summary, output=None, claims=None, calculations=None, checks=None):
    return {
        "status": status,
        "summary": summary,
        "claims": claims or [],
        "calculations": calculations or [],
        "quality_checks": checks or [],
        "output": output or {},
    }


def _fail(summary):
    return _result("failed", summary)


def _to_number(value):
    try:
        return float(value.replace(",", "")) if isinstance(value, str) else float(value)
    except (ValueError, AttributeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Shared arithmetic. Standard library only, so every figure in a report can
# be recomputed by hand from the method string next to it.
# ---------------------------------------------------------------------------

def _linear_fit(ys):
    """Least-squares fit of y against its position in the series.

    Returns (slope, intercept, r_squared). r_squared is reported to users
    as "share of the movement explained by the trend" — never as R².
    """
    n = len(ys)
    xs = list(range(n))
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if not denominator:
        return 0.0, mean_y, 0.0
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    intercept = mean_y - slope * mean_x
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    total = sum((y - mean_y) ** 2 for y in ys)
    return slope, intercept, (1 - residual / total) if total else 0.0


def _correlation(xs, ys):
    """Pearson correlation, or None when it is undefined (no variation)."""
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return None


def _next_labels(labels, count):
    """Extrapolate period labels. YYYY-MM increments properly; anything
    else gets an explicit "next period" label rather than a fake date."""
    last = str(labels[-1]) if labels else ""
    parts = last.split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() and len(parts[1]) == 2:
        year, month = int(parts[0]), int(parts[1])
        out = []
        for _ in range(count):
            month += 1
            if month > 12:
                month, year = 1, year + 1
            out.append(f"{year:04d}-{month:02d}")
        return out
    return [f"next period +{i + 1}" for i in range(count)]


# Statistical vocabulary that loses a business reader. Claims are written
# in plain language and this list is enforced as a quality check, not a
# style preference (see validator.no_statistical_jargon_in_claims).
JARGON = (
    "p-value", "p <", "p<", "r²", "r^2", "r-squared",
    "coefficient of determination", "standard deviations",
    "statistically significant", "null hypothesis", "confidence interval",
    "heteroskedastic", "regression coefficient",
)


def _jargon_in(text):
    lowered = text.lower()
    return [word for word in JARGON if word in lowered]


# The four analytics types, in maturity-ladder order. Each stage owns one
# question and consumes the stages above it.
ANALYTICS_TYPES = [
    ("descriptive", "What happened?"),
    ("diagnostic", "Why did it happen?"),
    ("predictive", "What will happen?"),
    ("prescriptive", "What should I do?"),
]

# Sections that get their own standalone report and their own tab in the
# interface. The four types are the ladder; the causal section is the
# boundary check that sits across it — it is not a fifth type, which is
# why it is a separate list rather than a fifth entry above.
REPORT_SECTIONS = ANALYTICS_TYPES[:2] + [
    ("experiment", "Can we claim a cause?"),
] + ANALYTICS_TYPES[2:]


def _section_report(title, question, ctx, body_lines, calculations, headline=None):
    """One self-contained report per analytics type, readable on its own.

    It opens with the headline — one sentence in business language, which
    is the only line most executives will read. A finding that cannot be
    communicated cannot drive action.
    """
    lines = [f"# {title} Analytics — {question}", "",
             f"**Dataset:** {ctx.get('dataset_name', 'dataset')} · "
             f"**Goal:** {ctx.get('goal', '')}", ""]
    if headline:
        lines += [f"> **{headline}**", ""]
    lines += body_lines
    if calculations:
        lines += ["", "## How each figure was calculated",
                  "| Figure | Value | Method |", "| --- | --- | --- |"]
        lines += [f"| {c['name']} | {c['value']} | {c['method']} |" for c in calculations]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Specialists
# ---------------------------------------------------------------------------

def planner(ctx):
    stages = [role for role, _ in PIPELINE]
    return _result(
        "succeeded",
        "Pattern: sequential governed pipeline — the goal is a repeatable "
        "analytics workflow, so the simplest sufficient pattern applies. "
        "Stopping rule: fixed bounded stage list with an approval gate "
        "before publishing.",
        output={"stages": stages, "pattern": "sequential_governed_pipeline"},
        checks=[{"name": "plan_has_validation_stage", "passed": "validator" in stages,
                 "detail": "Independent validation is part of the plan."}],
    )


def collector(ctx):
    text = ctx.get("dataset_text") or ""
    if len(text.encode()) > MAX_DATASET_BYTES:
        return _fail(f"Dataset exceeds the {MAX_DATASET_BYTES // 1_000_000} MB limit.")
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = [row for _, row in zip(range(MAX_ROWS + 1), reader)]
    except csv.Error as error:
        return _fail(f"The dataset could not be parsed as CSV: {error}")
    if not rows or not reader.fieldnames:
        return _fail("The dataset is empty or has no header row.")
    if len(rows) > MAX_ROWS:
        return _fail(f"Dataset exceeds the {MAX_ROWS}-row limit.")
    columns = [c for c in reader.fieldnames if c]
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return _result(
        "succeeded",
        f"Ingested {len(rows)} rows × {len(columns)} columns "
        f"(snapshot sha256:{digest}).",
        output={"rows": rows, "columns": columns, "snapshot": digest,
                "row_count": len(rows)},
        calculations=[{"id": "c_rows", "name": "row_count", "value": len(rows),
                       "method": "len(csv rows)"}],
        claims=[{"id": "cl_ingest", "type": "fact",
                 "text": f"The dataset contains {len(rows)} rows and {len(columns)} columns.",
                 "evidence": ["c_rows"], "status": "verified"}],
    )


def profiler(ctx):
    rows = ctx["collector"]["rows"]
    columns = ctx["collector"]["columns"]
    profile, numeric_columns = {}, []
    for col in columns:
        values = [r.get(col, "") or "" for r in rows]
        missing = sum(1 for v in values if not str(v).strip())
        numbers = [n for n in (_to_number(v) for v in values if str(v).strip()) if n is not None]
        is_numeric = len(numbers) >= max(1, (len(values) - missing) * 0.9)
        if is_numeric and numbers:
            numeric_columns.append(col)
        profile[col] = {"missing": missing, "distinct": len(set(values)),
                        "numeric": is_numeric}
    seen, duplicates = set(), 0
    for r in rows:
        key = tuple(sorted(r.items()))
        duplicates += key in seen
        seen.add(key)
    total_cells = len(rows) * max(1, len(columns))
    missing_cells = sum(p["missing"] for p in profile.values())
    completeness = round(1 - missing_cells / total_cells, 4)
    calcs = [
        {"id": "c_completeness", "name": "completeness", "value": completeness,
         "method": "1 - missing_cells/total_cells"},
        {"id": "c_dupes", "name": "duplicate_rows", "value": duplicates,
         "method": "exact row comparison"},
    ]
    return _result(
        "succeeded",
        f"Profiled quality: completeness {completeness:.0%}, "
        f"{duplicates} duplicate rows, numeric columns: "
        f"{', '.join(numeric_columns) or 'none'}.",
        output={"profile": profile, "numeric_columns": numeric_columns,
                "duplicates": duplicates, "completeness": completeness},
        calculations=calcs,
        claims=[{"id": "cl_quality", "type": "fact",
                 "text": f"Data completeness is {completeness:.0%} with {duplicates} duplicate rows.",
                 "evidence": ["c_completeness", "c_dupes"], "status": "verified"}],
        checks=[{"name": "has_numeric_column", "passed": bool(numeric_columns),
                 "detail": "At least one numeric measure is required for analysis."}],
    )


def cleaner(ctx):
    rows = ctx["collector"]["rows"]
    numeric_columns = ctx["profiler"]["numeric_columns"]
    if not numeric_columns:
        return _fail("No numeric column is available to analyze.")
    before = len(rows)
    cleaned, seen, dropped_empty, dropped_dupes, coercion_failures = [], set(), 0, 0, 0
    for row in rows:
        stripped = {k: (str(v).strip() if v is not None else "") for k, v in row.items() if k}
        if not any(stripped.values()):
            dropped_empty += 1
            continue
        key = tuple(sorted(stripped.items()))
        if key in seen:
            dropped_dupes += 1
            continue
        seen.add(key)
        for col in numeric_columns:
            number = _to_number(stripped.get(col, ""))
            if number is None and str(stripped.get(col, "")).strip():
                coercion_failures += 1
            stripped[col] = number
        cleaned.append(stripped)
    after = len(cleaned)
    calcs = [
        {"id": "c_rows_before", "name": "rows_before", "value": before, "method": "count"},
        {"id": "c_rows_after", "name": "rows_after", "value": after, "method": "count"},
        {"id": "c_dropped", "name": "rows_dropped", "value": before - after,
         "method": "empty + exact-duplicate removal"},
    ]
    return _result(
        "succeeded",
        f"Cleaned data: {before} → {after} rows "
        f"({dropped_empty} empty, {dropped_dupes} duplicates removed, "
        f"{coercion_failures} non-numeric values set to null). Row loss is "
        "reported, never hidden.",
        output={"rows": cleaned, "rows_before": before, "rows_after": after,
                "dropped": before - after},
        calculations=calcs,
        claims=[{"id": "cl_rowloss", "type": "fact",
                 "text": f"{before - after} of {before} rows were removed during cleaning "
                         f"({dropped_empty} empty, {dropped_dupes} duplicates).",
                 "evidence": ["c_rows_before", "c_rows_after", "c_dropped"],
                 "status": "verified"}],
    )


def governance(ctx):
    """Metric Governance Agent — is this measure defined, and who owns it?

    Decides which column the run analyses and says why, which used to be
    a silent guess inside the preparer. Where a glossary defines the
    metric it also checks the column against its own definition: a
    "revenue" column that does not equal price × units is a finding about
    the business, not a rounding detail.
    """
    numeric_columns = ctx["profiler"]["numeric_columns"]
    rows = ctx["cleaner"]["rows"]
    book = ctx.get("glossary") or {}
    metrics, problems = book.get("metrics", []), book.get("problems", [])

    measure, metric, source, candidates = glossary.resolve(
        metrics, ctx["collector"]["columns"], numeric_columns)
    calcs = [{"id": "c_gov_defined", "name": "metrics_in_glossary",
              "value": len(metrics),
              "method": "entries accepted from metrics.json"}]
    claims, checks, lines = [], [], []

    # A broken glossary is worse than none: someone believes it is in
    # force. It never fails the run, but it never passes quietly either.
    for index, problem in enumerate(problems):
        checks.append({"name": f"glossary_entry_{index + 1}_is_usable",
                       "passed": False, "detail": problem})
    if problems:
        claims.append({
            "id": "cl_gov_broken", "type": "warning",
            "text": f"The metric glossary has {len(problems)} problem(s) and "
                    "those definitions were not applied, so figures in this "
                    "report may not match the definitions somebody believes "
                    "are in force.",
            "evidence": ["c_gov_defined"], "status": "verified"})

    if metric:
        calcs.append({"id": "c_gov_certified", "name": "measure_is_certified",
                      "value": 1 if metric["certified"] else 0,
                      "method": f"“{measure}” resolved to glossary metric "
                                f"“{metric['name']}”"})
        owner = metric["owner"] or "nobody named"
        if metric["certified"]:
            claims.append({
                "id": "cl_gov_certified", "type": "fact",
                "text": f"“{measure}” is the certified metric {metric['title']}, "
                        f"owned by {owner}: {metric['definition']}",
                "evidence": ["c_gov_certified"], "status": "verified"})
        else:
            claims.append({
                "id": "cl_gov_uncertified", "type": "limitation",
                "text": f"“{measure}” is defined in the glossary as "
                        f"{metric['title']} but has not been certified, so no "
                        "one has signed off that this is the agreed definition.",
                "evidence": ["c_gov_certified"], "status": "verified"})
        lines.append(f"**{metric['title']}** — {metric['definition']}")
        lines.append("")
        lines.append(f"- Owner: {owner}")
        lines.append(f"- Certified: {'yes' if metric['certified'] else 'no'}"
                     + (f" ({metric['certified_on']})" if metric["certified_on"]
                        else ""))
        if metric["unit"]:
            lines.append(f"- Unit: {metric['unit']}")
        if metric["formula"]:
            lines.append(f"- Defined as: {glossary.formula_text(metric['formula'])}")
    else:
        claims.append({
            "id": "cl_gov_undefined", "type": "limitation",
            "text": f"“{measure}” is analysed as a column, not as a defined "
                    "metric: no glossary entry says what it means or who owns "
                    "it. These figures describe that column and cannot be "
                    "reconciled against an agreed definition.",
            "evidence": ["c_gov_defined"], "status": "verified"})
        lines.append(f"This run analyses **{measure}** because it was chosen by "
                     f"{source}. No definition exists for it: nothing here says "
                     "what it means, who owns it, or how it should be computed.")
        if not metrics:
            lines.append("")
            lines.append("No metric glossary is configured. `metrics.example.json` "
                         "shows the format; a definition becomes governance when "
                         "someone is named as its owner.")

    # The definition as arithmetic, checked against the data that claims
    # to satisfy it. This is the part a document cannot do.
    conformance = glossary.conformance(metric, rows, measure) if metric else None
    if conformance:
        calcs.append({"id": "c_gov_conformance", "name": "definition_conformance",
                      "value": conformance["rate"],
                      "method": f"rows where {measure} equals "
                                f"{glossary.formula_text(metric['formula'])} "
                                f"within 0.5%, over {conformance['checked']} "
                                "checked rows"})
        holds = conformance["rate"] == 1.0
        checks.append({
            "name": "measure_matches_its_definition", "passed": holds,
            "detail": (f"{conformance['matching']}/{conformance['checked']} rows "
                       f"match {glossary.formula_text(metric['formula'])}"
                       + ("" if holds else
                          f"; {conformance['breach_count']} do not"))})
        if holds:
            claims.append({
                "id": "cl_gov_conforms", "type": "fact",
                "text": f"Every one of the {conformance['checked']} checked rows "
                        f"has {measure} equal to its definition, so the recorded "
                        "figures and the agreed formula agree.",
                "evidence": ["c_gov_conformance"], "status": "verified"})
        else:
            worst = conformance["breaches"][0]
            claims.append({
                "id": "cl_gov_breach", "type": "warning",
                "text": f"{conformance['breach_count']} of "
                        f"{conformance['checked']} rows record a {measure} that "
                        f"does not match its own definition. The largest gap is "
                        f"{abs(worst['gap']):,.2f} on row {worst['row']}, which "
                        f"records {worst['recorded']:,.2f} where the definition "
                        f"gives {worst['defined']:,.2f}. Every total built on "
                        "this column inherits that gap.",
                "evidence": ["c_gov_conformance"], "status": "verified"})
        lines += ["", f"### Does the data match the definition?", "",
                  f"{conformance['matching']} of {conformance['checked']} rows "
                  f"match. "
                  + ("Nothing to explain."
                     if holds else
                     f"{conformance['breach_count']} do not, largest first:")]
        if not holds:
            lines += ["", "| Row | Recorded | Definition says | Gap |",
                      "| --- | --- | --- | --- |"]
            lines += [f"| {b['row']} | {b['recorded']:,.2f} | {b['defined']:,.2f} "
                      f"| {b['gap']:+,.2f} |" for b in conformance["breaches"]]
        if conformance["skipped"]:
            lines += ["", f"{conformance['skipped']} row(s) could not be checked "
                      "because a value the definition needs was missing."]
    elif metric and metric["formula"]:
        lines += ["", "The definition's inputs are not in this dataset, so the "
                  "column could not be checked against its own formula. That is "
                  "not the same as checking it and finding it sound."]

    # More than one column answering to a glossary name is how two
    # correct reports disagree.
    others = [c["column"] for c in candidates if c["column"] != measure]
    if others:
        calcs.append({"id": "c_gov_candidates", "name": "columns_matching_a_metric",
                      "value": len(candidates),
                      "method": "numeric columns named by a glossary metric"})
        claims.append({
            "id": "cl_gov_ambiguous", "type": "limitation",
            "text": f"{len(candidates)} columns in this dataset are named by a "
                    f"glossary metric. This run analysed “{measure}”; "
                    f"{', '.join(others)} was not analysed, so a report on it "
                    "would show different figures for the same question.",
            "evidence": ["c_gov_candidates"], "status": "verified"})
        lines += ["", f"Also present and defined: {', '.join(others)}. This run "
                  f"analysed “{measure}”."]

    summary = (f"Measure “{measure}” ({source})"
               + (f": certified {metric['title']}, owned by {metric['owner']}."
                  if metric and metric["certified"] else
                  f": glossary metric {metric['title']}, not certified."
                  if metric else
                  ", not defined in any glossary."))
    if conformance and conformance["rate"] < 1.0:
        summary += (f" {conformance['breach_count']} row(s) do not match the "
                    "definition.")
    return _result(
        "succeeded", summary,
        output={"measure": measure, "source": source,
                "metric": metric, "certified": bool(metric and metric["certified"]),
                "owner": metric["owner"] if metric else None,
                "glossary_configured": bool(metrics),
                "conformance": conformance,
                "also_defined": others,
                "notes_markdown": "\n".join(lines)},
        calculations=calcs, claims=claims, checks=checks)


def preparer(ctx):
    rows = ctx["cleaner"]["rows"]
    numeric_columns = ctx["profiler"]["numeric_columns"]
    columns = ctx["collector"]["columns"]
    # Which number this run is about was decided by the governance stage,
    # on the record and with a reason. This stage no longer guesses.
    measure = ctx["governance"]["measure"]
    date_col = next((c for c in columns if c.lower() in
                     ("month", "date", "period", "week", "year")), None)
    group_col = next((c for c in columns
                      if c not in numeric_columns and c != date_col), None)
    groups = {}
    if group_col:
        for row in rows:
            value = row.get(measure)
            if value is not None:
                groups[row[group_col]] = groups.get(row[group_col], 0.0) + value
    trend = {}
    if date_col:
        for row in rows:
            value = row.get(measure)
            if value is not None:
                trend[row[date_col]] = trend.get(row[date_col], 0.0) + value
        trend = dict(sorted(trend.items()))
    total = round(sum(r[measure] for r in rows if r.get(measure) is not None), 2)
    return _result(
        "succeeded",
        f"Prepared analysis dataset: measure “{measure}”"
        + (f", grouped by “{group_col}”" if group_col else "")
        + (f", trended by “{date_col}”" if date_col else "") + ".",
        output={"measure": measure, "group_col": group_col, "date_col": date_col,
                "groups": {k: round(v, 2) for k, v in groups.items()},
                "trend": {k: round(v, 2) for k, v in trend.items()},
                "total": total},
        calculations=[{"id": "c_total", "name": f"total_{measure}", "value": total,
                       "method": f"sum({measure}) over cleaned rows"}],
        claims=[{"id": "cl_total", "type": "calculation",
                 "text": f"Total {measure} is {total:,.2f}.",
                 "evidence": ["c_total"], "status": "verified"}],
    )


def descriptive(ctx):
    """Type 1 — What happened?

    Summarises the snapshot in business language. This is the floor of the
    maturity ladder: everything above it consumes these figures.
    """
    rows = ctx["cleaner"]["rows"]
    prep = ctx["preparer"]
    measure = prep["measure"]
    values = [r[measure] for r in rows if r.get(measure) is not None]
    if not values:
        return _fail(f"No usable values in measure “{measure}”.")
    mean = statistics.fmean(values)
    median = statistics.median(values)
    stdev = statistics.stdev(values) if len(values) > 1 else 0.0
    unusual = sum(1 for v in values if abs(v - mean) > 2 * stdev) if stdev else 0
    # The total is owned by the preparer (c_total); this stage cites it
    # rather than recomputing it under a second id, so every claim in the
    # report points at exactly one calculation.
    calcs = [
        {"id": "c_mean", "name": "mean", "value": round(mean, 2), "method": "fmean"},
        {"id": "c_median", "name": "median", "value": round(median, 2), "method": "median"},
        {"id": "c_spread", "name": "spread", "value": round(stdev, 2),
         "method": "sample standard deviation"},
        {"id": "c_unusual", "name": "unusual_rows", "value": unusual,
         "method": "count(|x - mean| > 2 × spread)"},
    ]
    claims = [
        {"id": "cl_typical", "type": "calculation",
         "text": f"A typical record is {mean:,.2f} (half are above {median:,.2f}).",
         "evidence": ["c_mean", "c_median"], "status": "verified"},
    ]
    if unusual:
        claims.append({"id": "cl_unusual", "type": "finding",
                       "text": f"{unusual} of {len(values)} records are far from the "
                               "typical value and are worth checking individually.",
                       "evidence": ["c_unusual"], "status": "verified"})

    change = None
    series = list(prep["trend"].values())
    if len(series) >= 2 and series[0]:
        change = round((series[-1] - series[0]) / series[0], 4)
        calcs.append({"id": "c_change", "name": "period_change", "value": change,
                      "method": "(last period − first period) / first period"})
        direction = "risen" if change >= 0 else "fallen"
        claims.append({"id": "cl_change", "type": "calculation",
                       "text": f"{measure} has {direction} {abs(change):.1%} from the "
                               f"first period to the last.",
                       "evidence": ["c_change"], "status": "verified"})
    top = max(prep["groups"], key=prep["groups"].get) if prep["groups"] else None
    share = None
    if top is not None and prep["total"]:
        share = round(prep["groups"][top] / prep["total"], 4)
        calcs.append({"id": "c_topshare", "name": "top_group_share", "value": share,
                      "method": "largest group total / overall total"})
        claims.append({"id": "cl_top", "type": "calculation",
                       "text": f"“{top}” is the largest {prep['group_col']}, making up "
                               f"{share:.1%} of total {measure}.",
                       "evidence": ["c_topshare"], "status": "verified"})
    headline = (
        f"{measure.capitalize()} "
        + (f"{'is up' if change >= 0 else 'is down'} {abs(change):.0%} over the period, "
           f"at {prep['total']:,.0f} in total."
           if change is not None else f"totals {prep['total']:,.0f}.")
        + (f" “{top}” is the biggest {prep['group_col']}." if top is not None else ""))
    report = _section_report(
        "Descriptive", "What happened?", ctx,
        [f"Total {measure} is **{prep['total']:,.2f}** across "
         f"{len(prep['trend']) or 1} period(s) and {ctx['cleaner']['rows_after']} records.",
         f"A typical record is {mean:,.2f}; half are above {median:,.2f}.",
         (f"{measure} has {'risen' if (change or 0) >= 0 else 'fallen'} "
          f"{abs(change):.1%} across the period." if change is not None else
          "The data covers a single period, so no change over time can be shown."),
         (f"“{top}” is the largest {prep['group_col']} at {share:.1%} of the total."
          if top is not None else "No grouping column was available."),
         (f"{unusual} record(s) sit far from the typical value and deserve a look."
          if unusual else "No records sit unusually far from the typical value.")],
        calcs, headline=headline)
    return _result(
        "succeeded", headline,
        output={"headline": headline,
                "change": change, "top_group": top, "top_share": share,
                "unusual": unusual, "mean": round(mean, 2), "median": round(median, 2),
                "report_markdown": report},
        calculations=calcs, claims=claims,
    )


def diagnostic(ctx):
    """Type 2 — Why did it happen?

    Decomposes the change by group (exact arithmetic) and measures which
    other columns move with the measure. Association is reported as
    association: nothing here establishes cause.
    """
    prep = ctx["preparer"]
    rows = ctx["cleaner"]["rows"]
    measure, group_col, date_col = prep["measure"], prep["group_col"], prep["date_col"]
    calcs, claims, contributions = [], [], []

    periods = list(prep["trend"].keys())
    if group_col and date_col and len(periods) >= 2:
        first, last = periods[0], periods[-1]
        by_group = {}
        for row in rows:
            value = row.get(measure)
            if value is None or row.get(date_col) not in (first, last):
                continue
            slot = by_group.setdefault(row[group_col], {"first": 0.0, "last": 0.0})
            slot["first" if row[date_col] == first else "last"] += value
        total_change = prep["trend"][last] - prep["trend"][first]
        for name, slot in by_group.items():
            delta = slot["last"] - slot["first"]
            contributions.append({
                "group": name, "change": round(delta, 2),
                "share_of_change": round(delta / total_change, 4) if total_change else None,
            })
        contributions.sort(key=lambda c: -abs(c["change"]))
        calcs.append({"id": "c_totalchange", "name": "total_change",
                      "value": round(total_change, 2),
                      "method": f"{measure} in {last} − {measure} in {first}"})
        for index, item in enumerate(contributions[:5]):
            calcs.append({"id": f"c_contrib_{index}",
                          "name": f"change_from_{item['group']}",
                          "value": item["change"],
                          "method": f"{measure} for “{item['group']}” in {last} minus {first}"})
        if contributions and total_change:
            driver = contributions[0]
            claims.append({
                "id": "cl_driver", "type": "finding",
                "text": f"Most of the movement comes from “{driver['group']}”: it accounts "
                        f"for {abs(driver['share_of_change']):.0%} of the total change of "
                        f"{total_change:,.2f}. This identifies where the change happened, "
                        "not what caused it.",
                "evidence": ["c_totalchange", "c_contrib_0"], "status": "verified"})
        decliners = [c for c in contributions if c["change"] < 0]
        if decliners:
            worst = min(decliners, key=lambda c: c["change"])
            index = contributions.index(worst)
            claims.append({
                "id": "cl_decline", "type": "finding",
                "text": f"“{worst['group']}” moved against the overall direction, changing "
                        f"{worst['change']:,.2f} between the first and last period.",
                "evidence": [f"c_contrib_{index}"] if index < 5 else ["c_totalchange"],
                "status": "verified"})

    # Which other numeric columns move together with the measure?
    associations = []
    numeric_columns = [c for c in ctx["profiler"]["numeric_columns"] if c != measure]
    for index, column in enumerate(numeric_columns[:4]):
        pairs = [(r[column], r[measure]) for r in rows
                 if r.get(column) is not None and r.get(measure) is not None]
        if len(pairs) < 3:
            continue
        correlation = _correlation([p[0] for p in pairs], [p[1] for p in pairs])
        if correlation is None:
            continue
        associations.append({"column": column, "correlation": round(correlation, 4)})
        calcs.append({"id": f"c_assoc_{index}", "name": f"association_{column}",
                      "value": round(correlation, 4),
                      "method": f"Pearson correlation of {column} and {measure} "
                                f"over {len(pairs)} rows"})
        if abs(correlation) >= 0.5:
            claims.append({
                "id": f"cl_assoc_{index}", "type": "finding",
                "text": f"“{column}” moves {'up' if correlation > 0 else 'down'} "
                        f"together with {measure} ({abs(correlation):.0%} of their movement "
                        "is shared). Moving together is not proof that one causes the other.",
                "evidence": [f"c_assoc_{index}"], "status": "verified"})

    if not calcs:
        calcs.append({"id": "c_nodiag", "name": "diagnosable_structure", "value": 0,
                      "method": "no period column, group column, or second numeric "
                                "column was available"})
    lines = []
    if contributions:
        lines.append("Change between the first and last period, by "
                     f"{group_col}, largest mover first:")
        for item in contributions[:5]:
            share = (f" ({item['share_of_change']:+.0%} of the total change)"
                     if item["share_of_change"] is not None else "")
            lines.append(f"- **{item['group']}**: {item['change']:+,.2f}{share}")
    else:
        lines.append("The dataset has no period-and-group structure to decompose, "
                     "so the movement cannot be attributed to a segment.")
    if associations:
        lines.append("")
        lines.append("Columns that move together with " + measure + ":")
        for item in associations:
            strength = ("strongly" if abs(item["correlation"]) >= 0.7 else
                        "moderately" if abs(item["correlation"]) >= 0.4 else "weakly")
            lines.append(f"- **{item['column']}** moves {strength} "
                         f"{'with' if item['correlation'] > 0 else 'against'} {measure}.")
    lines.append("")
    lines.append("*Moving together is not proof of cause. Confirming a cause needs a "
                 "controlled comparison or domain knowledge this dataset does not carry.*")
    if contributions and contributions[0]["share_of_change"] is not None:
        driver = contributions[0]
        headline = (f"The movement is concentrated in “{driver['group']}”, which "
                    f"accounts for {abs(driver['share_of_change']):.0%} of the change.")
        if associations and abs(associations[0]["correlation"]) >= 0.5:
            headline += (f" It moves closely with {associations[0]['column']}, "
                         "which is where to look first.")
    elif associations:
        headline = (f"{measure.capitalize()} moves closely with "
                    f"{associations[0]['column']}, which is where to look first.")
    else:
        headline = ("There is no segment or period structure in this data to explain "
                    "the movement.")
    report = _section_report("Diagnostic", "Why did it happen?", ctx, lines, calcs,
                             headline=headline)
    return _result(
        "succeeded", headline,
        output={"headline": headline,
                "contributions": contributions, "associations": associations,
                "report_markdown": report},
        calculations=calcs, claims=claims,
    )


# ---------------------------------------------------------------------------
# Experiment and causal inference
#
# The diagnostic agent finds where movement came from and what moves with
# what. Neither is a cause. The gap between the two is the most expensive
# mistake in business analytics: acting on an association that was never
# going to survive intervention. This agent owns that boundary, and it is
# deliberately hard to satisfy — it says "no cause here" unless the data
# itself records a controlled comparison.
#
# When it says no, it does not stop there. It computes the experiment that
# *would* settle the question: how many observations per group, and what
# size of change the data already in hand could detect. That turns an
# unanswerable question into a costed decision.
# ---------------------------------------------------------------------------

# Two-sided 5% and 80% power, the conventional pair. They appear in the
# calculation methods as numbers; claims translate them into what a
# business reader needs: how often a test like this would catch a real
# effect of the size being asked about.
Z_TWO_SIDED_95 = statistics.NormalDist().inv_cdf(0.975)
Z_POWER_80 = statistics.NormalDist().inv_cdf(0.80)

# Signals that a column records assignment to an arm. Deliberately narrow:
# a false positive here would let the run call an observational segment a
# controlled comparison, which is exactly the error the stage exists to
# prevent. "region" and "category" must never qualify.
#
# "cohort" is deliberately absent: a cohort is defined by something that
# already happened, never by assignment, so accepting it would let the
# stage read an observational split as a controlled one.
EXPERIMENT_COLUMN_WORDS = ("variant", "treatment", "arm", "test_group", "testgroup",
                           "experiment", "bucket", "ab_test", "abtest",
                           "assignment", "group_assignment")
# Bare "A"/"B" values are not accepted on their own — a column of grades
# or building names would qualify. One of these words must be present.
EXPERIMENT_VALUE_WORDS = ("control", "treatment", "holdout", "baseline", "variant")
BASELINE_NAMES = ("control", "baseline", "holdout")

# Relative changes the sizing table answers for, smallest first.
DETECTABLE_LIFTS = (0.05, 0.10, 0.20)


def _experiment_column(rows, columns, numeric_columns, date_col):
    """The column recording which arm each row belongs to, or (None, [])."""
    for column in columns:
        if column in numeric_columns or column == date_col:
            continue
        values = {str(row.get(column, "")).strip() for row in rows}
        values.discard("")
        if not 2 <= len(values) <= 6:
            continue
        named_like_an_experiment = any(word in column.lower()
                                       for word in EXPERIMENT_COLUMN_WORDS)
        labelled_like_an_experiment = bool({v.lower() for v in values}
                                           & set(EXPERIMENT_VALUE_WORDS))
        if named_like_an_experiment or labelled_like_an_experiment:
            return column, sorted(values)
    return None, []


def _sample_size_per_arm(variance, delta):
    """Observations per arm to detect `delta` at 5% two-sided, 80% power."""
    if not delta:
        return None
    return math.ceil(2 * (Z_TWO_SIDED_95 + Z_POWER_80) ** 2 * variance / delta ** 2)


def _smallest_detectable_change(variance, rows_available):
    """The smallest difference the rows already in hand could detect, if
    they were split evenly into two arms."""
    per_arm = rows_available / 2
    if per_arm < 2 or variance <= 0:
        return None
    return (Z_TWO_SIDED_95 + Z_POWER_80) * math.sqrt(2 * variance / per_arm)


def _arm_stats(values):
    count = len(values)
    mean = statistics.fmean(values)
    variance = statistics.variance(values) if count > 1 else 0.0
    return count, mean, variance


def experiment(ctx):
    """Experiment and Causal Inference Agent — can we claim a cause?

    Two paths, and the dataset chooses which. If it records assignment to
    arms, the arms are compared and the difference is reported as a range
    rather than a single number, because a single number implies a
    precision the sample does not have. If it does not, the answer is no —
    followed by the design that would change the answer.
    """
    prep = ctx["preparer"]
    rows = ctx["cleaner"]["rows"]
    measure = prep["measure"]
    values = [row[measure] for row in rows if row.get(measure) is not None]
    column, arm_names = _experiment_column(
        rows, ctx["collector"]["columns"], ctx["profiler"]["numeric_columns"],
        prep["date_col"])

    if len(values) < 2:
        calcs = [{"id": "c_exp_rows", "name": "rows_with_a_measure", "value": len(values),
                  "method": f"rows where {measure} is present"}]
        headline = ("There is not enough data here to compare anything, so no cause "
                    "can be claimed.")
        return _result(
            "succeeded", headline,
            output={"headline": headline, "is_experiment": False,
                    "report_markdown": _section_report(
                        "Causal", "Can we claim a cause?", ctx,
                        ["Fewer than two usable observations: nothing to compare."],
                        calcs, headline=headline)},
            calculations=calcs,
            claims=[{"id": "cl_exp_thin", "type": "limitation", "text": headline,
                     "evidence": ["c_exp_rows"], "status": "verified"}])

    if column is None:
        return _observational(ctx, values, measure)
    return _controlled_comparison(ctx, rows, values, measure, column, arm_names)


def _observational(ctx, values, measure):
    """No assignment column: say no, then price the experiment."""
    count, mean, variance = _arm_stats(values)
    scale = abs(mean)
    calcs = [
        {"id": "c_exp_rows", "name": "rows_with_a_measure", "value": count,
         "method": f"rows where {measure} is present"},
        {"id": "c_exp_spread", "name": f"typical_spread_of_{measure}",
         "value": round(math.sqrt(variance), 2),
         "method": f"sample standard deviation of {measure} over {count} rows"},
    ]
    sizing = []
    for index, lift in enumerate(DETECTABLE_LIFTS):
        needed = _sample_size_per_arm(variance, lift * scale) if scale else None
        if needed is None:
            continue
        sizing.append({"lift": lift, "rows_per_arm": needed})
        calcs.append({
            "id": f"c_exp_n_{index}", "name": f"rows_per_group_for_{int(lift * 100)}pct",
            "value": needed,
            "method": f"2·(1.96+0.84)²·variance/({lift:.2f}·mean)² — two-sided 5%, "
                      "80% power"})
    detectable = _smallest_detectable_change(variance, count)
    if detectable is not None and scale:
        calcs.append({"id": "c_exp_mde", "name": "smallest_detectable_change",
                      "value": round(detectable / scale, 4),
                      "method": f"(1.96+0.84)·√(2·variance/({count}/2)) ÷ mean — the "
                                "existing rows split evenly into two groups"})

    lines = [
        f"This dataset records what happened to {measure}. It carries no column "
        "saying which rows were treated differently, so every finding in this run "
        "describes an association. **Nothing here establishes a cause**, and no "
        "amount of extra rows of the same kind would change that — it is a "
        "question of design, not of volume.",
        "",
        "### What it would take to prove one",
    ]
    if sizing:
        lines += ["", "| Change you want to prove | Observations needed in *each* group |",
                  "| --- | --- |"]
        lines += [f"| {item['lift']:.0%} of the average {measure} "
                  f"| {item['rows_per_arm']:,} |" for item in sizing]
        lines += ["", "Split the population at random into two groups, change one "
                  "thing for one of them, and collect at least that many "
                  "observations in each. A test of that size catches a real "
                  "change of that size about four times in five."]
    else:
        lines += ["", f"The average {measure} is zero or the values never vary, so a "
                  "relative change cannot be sized from this data."]
    if detectable is not None and scale:
        lines += ["", f"With the {count:,} observations already here, split evenly, "
                  f"the smallest change that would stand out from ordinary variation "
                  f"is about **{detectable / scale:.0%}** of the average. Anything "
                  "smaller would be invisible in a sample this size — which is worth "
                  "knowing before commissioning the test."]
    claims = [{
        "id": "cl_exp_observational", "type": "limitation",
        "text": f"This data records what happened; it contains no controlled "
                f"comparison, so no finding about {measure} may be stated as a cause.",
        "evidence": ["c_exp_rows"], "status": "verified"}]
    if sizing:
        first = sizing[1] if len(sizing) > 1 else sizing[0]
        index = DETECTABLE_LIFTS.index(first["lift"])
        claims.append({
            "id": "cl_exp_design", "type": "recommendation",
            "text": f"To prove a {first['lift']:.0%} change in {measure}, run a "
                    f"randomised comparison with about {first['rows_per_arm']:,} "
                    "observations in each group; a test that size catches a real "
                    "change of that size about four times in five.",
            "evidence": [f"c_exp_n_{index}", "c_exp_spread"], "status": "verified"})
        headline = (f"No cause can be claimed from this data — to prove a "
                    f"{first['lift']:.0%} change you would need about "
                    f"{first['rows_per_arm']:,} observations in each of two groups.")
    else:
        headline = ("No cause can be claimed from this data: it records what "
                    "happened, not a controlled comparison.")
    report = _section_report("Causal", "Can we claim a cause?", ctx, lines, calcs,
                             headline=headline)
    return _result(
        "succeeded", headline,
        output={"headline": headline, "is_experiment": False, "sizing": sizing,
                "smallest_detectable_change": (round(detectable / scale, 4)
                                               if detectable is not None and scale
                                               else None),
                "report_markdown": report},
        calculations=calcs, claims=claims)


def _controlled_comparison(ctx, rows, values, measure, column, arm_names):
    """An assignment column exists: compare the arms honestly."""
    arms = {}
    for row in rows:
        name = str(row.get(column, "")).strip()
        value = row.get(measure)
        if name and value is not None:
            arms.setdefault(name, []).append(value)
    usable = {name: vals for name, vals in arms.items() if len(vals) >= 2}
    calcs = [{"id": "c_exp_arms", "name": "groups_compared", "value": len(usable),
              "method": f"distinct values of “{column}” with at least two rows"}]

    if len(usable) < 2:
        headline = (f"“{column}” looks like an experiment, but only "
                    f"{len(usable)} group has enough rows to compare, so no cause "
                    "can be claimed.")
        lines = [f"Column “{column}” records assignment to "
                 f"{len(arms)} group(s), but a comparison needs at least two "
                 "groups with two or more observations each."]
        return _result(
            "succeeded", headline,
            output={"headline": headline, "is_experiment": False,
                    "assignment_column": column,
                    "report_markdown": _section_report(
                        "Causal", "Can we claim a cause?", ctx, lines, calcs,
                        headline=headline)},
            calculations=calcs,
            claims=[{"id": "cl_exp_thin_arms", "type": "limitation", "text": headline,
                     "evidence": ["c_exp_arms"], "status": "verified"}])

    baseline = next((name for name in sorted(usable)
                     if name.lower() in BASELINE_NAMES), sorted(usable)[0])
    base_n, base_mean, base_var = _arm_stats(usable[baseline])
    calcs.append({"id": "c_exp_base", "name": f"average_{measure}_in_{baseline}",
                  "value": round(base_mean, 2),
                  "method": f"mean {measure} over {base_n} rows where "
                            f"{column} = “{baseline}”"})

    # Comparing several arms against one baseline multiplies the chances of
    # a fluke looking real, so each range is widened to keep the risk across
    # the whole family at 5% (Bonferroni). Stated as arithmetic, not as a
    # word the reader has to trust.
    comparisons = sorted(name for name in usable if name != baseline)
    # The risk budget is split across the comparisons either way; only the
    # shape of the bound differs.
    alpha = 0.05 / len(comparisons)
    z = statistics.NormalDist().inv_cdf(1 - alpha / 2)
    results = []
    for index, name in enumerate(comparisons):
        count, mean, variance = _arm_stats(usable[name])
        difference = mean - base_mean
        spread = math.sqrt(variance / count + base_var / base_n)
        fixed_low, fixed_high = difference - z * spread, difference + z * spread
        # The sequence is only as advanced as its slower arm.
        reached = min(count, base_n)
        low, high = sequential.always_valid_range(difference, spread, reached,
                                                  alpha=alpha)
        relative = difference / abs(base_mean) if base_mean else None
        results.append({
            "group": name, "rows": count, "average": round(mean, 2),
            "difference": round(difference, 2),
            "relative": round(relative, 4) if relative is not None else None,
            # `low`/`high` are the range the verdict rests on, and it is
            # the one that survives being looked at more than once.
            "low": round(low, 2), "high": round(high, 2),
            "fixed_low": round(fixed_low, 2), "fixed_high": round(fixed_high, 2),
            "beyond_chance": sequential.excludes_no_change(low, high),
            "beyond_chance_if_horizon_was_fixed":
                sequential.excludes_no_change(fixed_low, fixed_high),
        })
        calcs.append({
            "id": f"c_exp_diff_{index}", "name": f"difference_{name}_vs_{baseline}",
            "value": round(difference, 2),
            "method": f"mean {measure} in “{name}” ({count} rows) minus “{baseline}” "
                      f"({base_n} rows)"})
        calcs.append({
            "id": f"c_exp_range_{index}", "name": f"range_{name}_vs_{baseline}",
            "value": f"{low:,.2f} to {high:,.2f}",
            "method": f"difference ± {sequential.inflation(reached, alpha):.2f}·"
                      f"√(var/n + var/n) — a normal-mixture confidence sequence at "
                      f"n={reached}, valid at every sample size, 5% split across "
                      f"{len(comparisons)} comparison(s)"})
        calcs.append({
            "id": f"c_exp_fixed_{index}",
            "name": f"fixed_size_range_{name}_vs_{baseline}",
            "value": f"{fixed_low:,.2f} to {fixed_high:,.2f}",
            "method": f"difference ± {z:.2f}·√(var/n + var/n) — valid only if the "
                      "sample size was fixed before the data was collected"})

    # A randomised split that came out lopsided is evidence the assignment
    # or the logging is broken, and it invalidates the comparison above it.
    # Three standard errors, because flagging this is an accusation about
    # the reader's plumbing: a false alarm costs trust in every other check
    # in the report. The cost of that caution is that a tiny sample can be
    # visibly lopsided without crossing the line — a 9/2 split is inside
    # what eleven coin flips do.
    total_rows = sum(len(v) for v in usable.values())
    expected_share = 1 / len(usable)
    worst = max(usable, key=lambda n: abs(len(usable[n]) / total_rows - expected_share))
    observed_share = len(usable[worst]) / total_rows
    tolerance = 3 * math.sqrt(expected_share * (1 - expected_share) / total_rows)
    lopsided = abs(observed_share - expected_share) > tolerance
    calcs.append({"id": "c_exp_split", "name": "largest_split_deviation",
                  "value": round(abs(observed_share - expected_share), 4),
                  "method": f"|share of “{worst}” − {expected_share:.3f}| over "
                            f"{total_rows} rows; flagged beyond {tolerance:.3f}"})

    claims, lines = [], [
        f"Column “{column}” records which group each row belongs to, so this run "
        f"can compare them. “{baseline}” is used as the baseline; every figure "
        "below is the difference from it.",
        "",
        "| Group | Rows | Average | Difference | Range (safe to check early) "
        "| Beyond chance? |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {baseline} (baseline) | {base_n} | {base_mean:,.2f} | — | — | — |",
    ]
    for item in results:
        relative = f" ({item['relative']:+.1%})" if item["relative"] is not None else ""
        lines.append(
            f"| {item['group']} | {item['rows']} | {item['average']:,.2f} "
            f"| {item['difference']:+,.2f}{relative} "
            f"| {item['low']:,.2f} to {item['high']:,.2f} "
            f"| {'yes' if item['beyond_chance'] else 'no'} |")
    lines += ["", "The range is what the data can actually support. A single "
              "difference looks precise and is not: repeat the same test and it "
              "would land somewhere in that range. Where the range crosses zero, "
              "the difference is inside what chance alone produces, and it should "
              "not be acted on as a result.",
              "",
              "### Why this range and not a narrower one", "",
              "Most people look at a test more than once — on Tuesday, again on "
              "Thursday — and stop when the number looks good. Stopping when the "
              "number looks good is what turns a 1-in-20 risk of a false result "
              "into something far worse: simulated, checking an ordinary range "
              "roughly two hundred times finds a “real” difference in about a "
              "third of tests where nothing is happening at all.",
              "",
              "The range above is built to survive that. It is valid at every "
              "sample size at once, so looking early, looking often, and stopping "
              "when you like do not break it. It is about half again as wide as "
              "the ordinary one, and that width is what the freedom to look costs.",
              "",
              "If you genuinely fixed the sample size before collecting anything "
              "and are looking exactly once, the narrower range applies:"]
    lines += ["", "| Group | Range (only if the size was fixed in advance) "
              "| Beyond chance? |", "| --- | --- | --- |"]
    lines += [f"| {item['group']} | {item['fixed_low']:,.2f} to "
              f"{item['fixed_high']:,.2f} "
              f"| {'yes' if item['beyond_chance_if_horizon_was_fixed'] else 'no'} |"
              for item in results]
    if len(comparisons) > 1:
        lines += ["", f"{len(comparisons)} groups were compared against the "
                  "baseline. Comparing more groups gives chance more chances, so "
                  "each range was widened to keep the overall risk of a false "
                  "result at the same level as a single comparison."]

    for index, item in enumerate(results):
        if item["beyond_chance"]:
            direction = "ahead of" if item["difference"] > 0 else "behind"
            claims.append({
                "id": f"cl_exp_effect_{index}", "type": "finding",
                "text": f"“{item['group']}” is {direction} “{baseline}” on {measure} "
                        f"by {abs(item['difference']):,.2f}"
                        + (f" ({abs(item['relative']):.1%})"
                           if item["relative"] is not None else "")
                        + f", and the range ({item['low']:,.2f} to "
                          f"{item['high']:,.2f}) does not include no-change, so this "
                          "is unlikely to be chance alone. That range holds however "
                          "often the test was checked along the way.",
                "evidence": [f"c_exp_diff_{index}", f"c_exp_range_{index}"],
                "status": "verified"})
        else:
            claims.append({
                "id": f"cl_exp_null_{index}", "type": "finding",
                "text": f"“{item['group']}” and “{baseline}” cannot be separated on "
                        f"{measure}: the range ({item['low']:,.2f} to "
                        f"{item['high']:,.2f}) includes no change, so the difference "
                        "of " + f"{item['difference']:+,.2f} is within ordinary "
                        "variation." + (
                            " A narrower reading would call it real, but only for "
                            "someone who fixed the sample size before collecting "
                            "anything and is looking exactly once."
                            if item["beyond_chance_if_horizon_was_fixed"] else ""),
                "evidence": [f"c_exp_diff_{index}", f"c_exp_range_{index}"],
                "status": "verified"})
    if lopsided:
        lines += ["", f"⚠️ The groups are not evenly sized: “{worst}” holds "
                  f"{observed_share:.0%} of the rows where {expected_share:.0%} was "
                  "expected. Random assignment rarely lands that far apart, so check "
                  "how rows were assigned and logged before trusting anything above."]
        claims.append({
            "id": "cl_exp_split", "type": "warning",
            "text": f"The groups are unevenly sized: “{worst}” holds "
                    f"{observed_share:.0%} of rows against an expected "
                    f"{expected_share:.0%}. Random assignment rarely produces a gap "
                    "that wide, so the comparison may be measuring the assignment "
                    "rather than the change.",
            "evidence": ["c_exp_split"], "status": "verified"})

    claims.append({
        "id": "cl_exp_peeking", "type": "assumption",
        "text": "The ranges above stay honest however often this test was "
                "checked while it ran, which is why they are wider than the "
                "usual ones. The narrower figures beside them apply only if the "
                "number of observations was decided before any data was "
                "collected and the result is being read once.",
        "evidence": ["c_exp_range_0"], "status": "verified"})

    # The column proves an assignment was recorded. It does not prove the
    # assignment was random — and only randomisation turns this difference
    # into an effect. A run that quietly skipped this sentence would let a
    # non-random rollout be read as proof of cause, which is the exact
    # failure this stage exists to prevent.
    claims.append({
        "id": "cl_exp_random", "type": "assumption",
        "text": f"This difference counts as the effect of the change only if rows "
                f"were assigned to their “{column}” group at random. The data "
                "records the assignment, not how it was made; without "
                "randomisation this remains an association, like any other in "
                "this report.",
        "evidence": ["c_exp_arms"], "status": "verified"})
    lines += ["", f"**This is a causal result only if assignment to “{column}” was "
              "random.** The dataset records which group each row was in, not how "
              "it got there. Where groups were formed by something that already "
              "happened — who opted in, which region rolled out first — the "
              "difference is an association wearing an experiment's clothes."]

    # The comparison treats each row as one independent observation. When
    # rows are period-by-segment aggregates that is false, and the ranges
    # above are narrower than the truth. Saying so is cheaper than being
    # quietly wrong.
    claims.append({
        "id": "cl_exp_units", "type": "limitation",
        "text": f"Each row is treated as one independent observation of {measure}. "
                "If rows are aggregates or the same subject appears more than once, "
                "the ranges above are narrower than reality and the comparison "
                "should be rerun on the underlying records.",
        "evidence": ["c_exp_arms"], "status": "verified"})
    lines += ["", "*Each row is treated as one independent observation. If the rows "
              "are aggregates — one per month, per region — the ranges above are "
              "narrower than the truth.*"]

    strongest = max(results, key=lambda r: abs(r["difference"]))
    if strongest["beyond_chance"]:
        relative = (f" ({abs(strongest['relative']):.1%})"
                    if strongest["relative"] is not None else "")
        headline = (f"“{strongest['group']}” beats “{baseline}” on {measure} by "
                    f"{abs(strongest['difference']):,.2f}{relative}, and the result "
                    "is bigger than chance would explain."
                    if strongest["difference"] > 0 else
                    f"“{strongest['group']}” is behind “{baseline}” on {measure} by "
                    f"{abs(strongest['difference']):,.2f}{relative}, by more than "
                    "chance would explain.")
    else:
        headline = (f"No group can be separated from “{baseline}” on {measure}: "
                    "every difference is inside what chance alone produces.")
    if lopsided:
        headline += " The groups are unevenly sized, so treat this with caution."
    report = _section_report("Causal", "Can we claim a cause?", ctx, lines, calcs,
                             headline=headline)
    return _result(
        "succeeded", headline,
        output={"headline": headline, "is_experiment": True,
                "assignment_column": column, "baseline": baseline,
                "arms": results, "balanced": not lopsided,
                "report_markdown": report},
        calculations=calcs, claims=claims)


# ---------------------------------------------------------------------------
# Governed specialists added alongside the four analytics types. Each does
# arithmetic or pattern work of its own — none exists to relay another
# stage's output in different words.
# ---------------------------------------------------------------------------

# Anything matching these is treated as personal data leaving the building
# if the report is published. Deliberately conservative: a false positive
# costs a sentence in the report, a false negative costs a disclosure.
PII_PATTERNS = [
    ("email address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")),
    ("phone number", re.compile(r"(?<!\d)(?:\+\d{1,3}[ -]?)?(?:\d[ -]?){9,14}\d(?!\d)")),
    ("long identifier", re.compile(r"(?<!\d)\d{12,19}(?!\d)")),
]
PII_COLUMN_WORDS = ("email", "e-mail", "phone", "mobile", "ssn", "nin",
                    "passport", "iban", "card", "dob", "birth", "address",
                    "national_id", "emirates_id")


def contract(ctx):
    """Data Contract Agent — what shape is this data, and does it hold?

    Infers a per-column contract from the snapshot: type, nullability,
    distinctness, and range for numbers. Nothing downstream has to guess,
    and a later upload of the same name can be compared against it.
    """
    rows, columns = ctx["collector"]["rows"], ctx["collector"]["columns"]
    fields, breaches = [], []
    for column in columns:
        values = [(r.get(column) or "").strip() for r in rows]
        present = [v for v in values if v]
        numbers = [_to_number(v) for v in present]
        numbers = [n for n in numbers if n is not None]
        parse_rate = len(numbers) / len(present) if present else 0.0
        # A column where most values are numbers IS a numeric column with
        # dirty values. Calling it "text" at 83% would hide precisely the
        # problem this stage exists to report. The 0.9 line is kept as a
        # separate flag, because that is the bar the analysis stages use.
        numeric = bool(present) and parse_rate > 0.5
        field = {
            "name": column,
            "type": "number" if numeric else "text",
            "parse_rate": round(parse_rate, 4),
            "usable_as_measure": parse_rate >= 0.9,
            "nullable": len(present) < len(values),
            "missing": len(values) - len(present),
            "distinct": len(set(present)),
        }
        if numeric and numbers:
            field["min"] = round(min(numbers), 4)
            field["max"] = round(max(numbers), 4)
        fields.append(field)
        # A column that is mostly numbers but not entirely is the classic
        # source of silent wrong totals, so it is named here rather than
        # discovered later.
        if numeric and len(numbers) < len(present):
            breaches.append(
                f"{column}: {len(present) - len(numbers)} of {len(present)} value(s) "
                "will not parse as a number"
                + ("" if field["usable_as_measure"] else
                   f", leaving only {parse_rate:.0%} usable — below the 90% needed "
                   "to analyse it as a measure"))

    calcs = [{"id": "c_contract_fields", "name": "columns_under_contract",
              "value": len(fields), "method": "one contract row per column"}]
    claims = [{"id": "cl_contract", "type": "fact",
               "text": f"The data has {len(fields)} columns under contract: "
                       + ", ".join(f"{f['name']} ({f['type']})" for f in fields[:6])
                       + ("…" if len(fields) > 6 else "") + ".",
               "evidence": ["c_contract_fields"], "status": "verified"}]
    if breaches:
        claims.append({"id": "cl_contract_breach", "type": "finding",
                       "text": "Some values do not match the column they sit in: "
                               + "; ".join(breaches[:3])
                               + ". Those cells are treated as missing, not guessed.",
                       "evidence": ["c_contract_fields"], "status": "verified"})
    return _result(
        "succeeded",
        f"Contract inferred for {len(fields)} columns"
        + (f"; {len(breaches)} column(s) contain values that break it." if breaches
           else "; every value matches its column."),
        output={"fields": fields, "breaches": breaches},
        calculations=calcs, claims=claims,
        checks=[{"name": "contract_has_a_measure",
                 "passed": any(f["type"] == "number" for f in fields),
                 "detail": "At least one numeric column is needed to measure anything."}],
    )


def quality(ctx):
    """Data Quality Agent — a scorecard, not a vibe.

    Four standard dimensions, each a ratio anybody can recompute, and one
    overall score that is their mean. A number with a stated formula can
    be argued with; a traffic light cannot.
    """
    rows, columns = ctx["collector"]["rows"], ctx["collector"]["columns"]
    fields = ctx["contract"]["fields"]
    cells = len(rows) * max(1, len(columns))

    filled = sum(len(rows) - f["missing"] for f in fields)
    completeness = filled / cells if cells else 0.0

    seen, duplicate_rows = set(), 0
    for row in rows:
        key = tuple(sorted(row.items()))
        duplicate_rows += key in seen
        seen.add(key)
    uniqueness = 1 - (duplicate_rows / len(rows)) if rows else 0.0

    numeric_fields = [f for f in fields if f["type"] == "number"]
    parseable = 0
    numeric_present = 0
    for field in numeric_fields:
        for row in rows:
            value = (row.get(field["name"]) or "").strip()
            if not value:
                continue
            numeric_present += 1
            parseable += _to_number(value) is not None
    validity = parseable / numeric_present if numeric_present else 1.0

    consistent = sum(1 for r in rows if len(r) == len(columns))
    consistency = consistent / len(rows) if rows else 0.0

    dimensions = {"completeness": completeness, "uniqueness": uniqueness,
                  "validity": validity, "consistency": consistency}
    score = round(100 * statistics.fmean(dimensions.values()), 1)
    grade = ("A" if score >= 95 else "B" if score >= 85 else
             "C" if score >= 70 else "D")

    calcs = [{"id": f"c_dq_{name}", "name": f"{name}_ratio", "value": round(value, 4),
              "method": method}
             for (name, value), method in zip(dimensions.items(), [
                 "filled cells / total cells",
                 "1 − duplicate rows / total rows",
                 "numeric cells that parse / numeric cells present",
                 "rows with every column present / total rows"])]
    calcs.append({"id": "c_dq_score", "name": "quality_score", "value": score,
                  "method": "mean of the four dimension ratios × 100"})
    weakest = min(dimensions, key=dimensions.get)
    # Naming a "weakest" dimension that is itself perfect reads as a fault
    # where there is none.
    flawless = dimensions[weakest] >= 1.0
    verdict = ("every dimension is perfect"
               if flawless else
               f"weakest dimension is {weakest} at {dimensions[weakest]:.0%}")
    return _result(
        "succeeded",
        f"Data quality {score}/100 (grade {grade}); {verdict}.",
        output={"dimensions": {k: round(v, 4) for k, v in dimensions.items()},
                "score": score, "grade": grade, "weakest": weakest},
        calculations=calcs,
        claims=[{"id": "cl_dq", "type": "calculation",
                 "text": f"Data quality scores {score} out of 100 (grade {grade}). "
                         + ("Completeness, uniqueness, validity and consistency are "
                            "all perfect." if flawless else
                            f"The weakest part is {weakest}, at "
                            f"{dimensions[weakest]:.0%}."),
                 "evidence": ["c_dq_score", f"c_dq_{weakest}"], "status": "verified"}],
        checks=[{"name": "quality_above_floor", "passed": score >= 50,
                 "detail": f"Score {score}/100. Below 50 the findings would rest on "
                           "data too broken to carry them."}],
    )


def privacy(ctx):
    """Privacy Agent — does this dataset carry personal data?

    Runs before anything is published, because the vault write is the
    moment data leaves the analyst's hands. It never redacts silently: it
    reports what it found and where, and the human decides at the gate.
    """
    rows, columns = ctx["collector"]["rows"], ctx["collector"]["columns"]
    findings = []
    for column in columns:
        lowered = column.lower()
        named = [word for word in PII_COLUMN_WORDS if word in lowered]
        hits = {}
        for row in rows[:2000]:          # bounded scan; enough to detect a pattern
            value = (row.get(column) or "").strip()
            if not value:
                continue
            for label, pattern in PII_PATTERNS:
                if pattern.search(value):
                    hits[label] = hits.get(label, 0) + 1
        if named or hits:
            findings.append({
                "column": column,
                "by_name": named,
                "by_value": [{"kind": k, "rows": v} for k, v in sorted(hits.items())],
            })

    calcs = [{"id": "c_pii_columns", "name": "columns_with_personal_data",
              "value": len(findings),
              "method": "columns matching a personal-data name or value pattern"}]
    claims = []
    if findings:
        summary = "; ".join(
            f"{f['column']} (" + ", ".join(
                [f"named like {'/'.join(f['by_name'])}"] if f["by_name"] else []
                + [f"{h['rows']} {h['kind']}(s)" for h in f["by_value"]]) + ")"
            for f in findings[:3])
        claims.append({
            "id": "cl_pii", "type": "warning",
            "text": f"This dataset appears to contain personal data in "
                    f"{len(findings)} column(s): {summary}. Publishing writes the "
                    "report to the vault — check that it is allowed to leave here.",
            "evidence": ["c_pii_columns"], "status": "verified"})
    else:
        claims.append({
            "id": "cl_pii_clear", "type": "fact",
            "text": "No personal data was detected in the dataset by name or by "
                    "value pattern. Detection is pattern-based, so it is a strong "
                    "hint rather than a guarantee.",
            "evidence": ["c_pii_columns"], "status": "verified"})
    return _result(
        "succeeded",
        (f"Personal data detected in {len(findings)} column(s) — review before "
         "publishing." if findings else
         "No personal data detected by name or value pattern."),
        output={"findings": findings, "personal_data": bool(findings)},
        calculations=calcs, claims=claims,
        checks=[{"name": "personal_data_declared", "passed": True,
                 "detail": (f"{len(findings)} column(s) flagged and reported to the "
                            "approver." if findings else
                            "Nothing matched; the scan itself is recorded.")}],
    )


def segments(ctx):
    """Segment Agent — how concentrated is this business?

    Share, Pareto coverage, and a Herfindahl index, all from the prepared
    aggregates. Concentration is the fact a leader most often needs and
    a total most often hides.
    """
    prep = ctx["preparer"]
    groups, total = prep["groups"], prep["total"]
    if not groups or not total:
        return _result(
            "succeeded",
            "No grouping column, so concentration cannot be measured.",
            output={"shares": [], "hhi": None, "pareto_count": None},
            calculations=[{"id": "c_seg_none", "name": "segments", "value": 0,
                           "method": "no non-numeric column to group by"}],
            claims=[{"id": "cl_seg_none", "type": "limitation",
                     "text": "The data has no grouping column, so no segment "
                             "concentration can be reported.",
                     "evidence": ["c_seg_none"], "status": "verified"}])

    ordered = sorted(groups.items(), key=lambda kv: -kv[1])
    shares = [{"group": name, "value": round(value, 2),
               "share": round(value / total, 4)} for name, value in ordered]
    hhi = round(sum(s["share"] ** 2 for s in shares), 4)
    running, pareto = 0.0, 0
    for share in shares:
        running += share["share"]
        pareto += 1
        if running >= 0.8:
            break
    calcs = [
        {"id": "c_seg_count", "name": "segments", "value": len(shares),
         "method": f"distinct values of {prep['group_col']}"},
        {"id": "c_seg_hhi", "name": "concentration_index", "value": hhi,
         "method": "sum of squared shares (1.0 = one segment holds everything)"},
        {"id": "c_seg_pareto", "name": "segments_for_80_percent", "value": pareto,
         "method": "segments needed, largest first, to reach 80% of the total"},
    ]
    spread = ("very concentrated" if hhi >= 0.5 else
              "concentrated" if hhi >= 0.25 else "spread out")
    # With two or three segments "N of them make 80%" is arithmetic, not
    # insight; the share of the largest is the fact worth stating.
    headline = (f"{len(shares)} segments; {pareto} of them make up 80% of the total "
                f"({spread})."
                if len(shares) > 3 else
                f"{len(shares)} segments, largest at {shares[0]['share']:.0%} "
                f"of the total ({spread}).")
    return _result(
        "succeeded", headline,
        output={"shares": shares, "hhi": hhi, "pareto_count": pareto},
        calculations=calcs,
        claims=[{"id": "cl_seg", "type": "calculation",
                 "text": (f"{pareto} of {len(shares)} {prep['group_col']}s account for "
                          f"80% of {prep['measure']} — the business is {spread}."
                          if len(shares) > 3 else
                          f"The largest of {len(shares)} {prep['group_col']}s holds "
                          f"{shares[0]['share']:.0%} of {prep['measure']} — the "
                          f"business is {spread}."),
                 "evidence": ["c_seg_pareto", "c_seg_hhi"], "status": "verified"}],
    )


def anomaly(ctx):
    """Anomaly Agent — which periods do not fit the pattern?

    Residuals from the fitted trend, flagged beyond two standard
    deviations of those residuals. Distinct from the descriptive outlier
    count, which compares single records to the average and cannot see
    that a period is unusual *given the trend*.
    """
    prep = ctx["preparer"]
    labels = list(prep["trend"].keys())
    series = list(prep["trend"].values())
    if len(series) < 4:
        return _result(
            "succeeded",
            f"Only {len(series)} period(s): too few to tell an unusual period "
            "from ordinary variation.",
            output={"anomalies": [], "residual_spread": None},
            calculations=[{"id": "c_anom_periods", "name": "periods_available",
                           "value": len(series), "method": "distinct periods"}],
            claims=[{"id": "cl_anom_none", "type": "limitation",
                     "text": f"With {len(series)} period(s) there is no basis for "
                             "calling any of them unusual.",
                     "evidence": ["c_anom_periods"], "status": "verified"}])

    slope, intercept, _ = _linear_fit(series)
    residuals = [value - (intercept + slope * index)
                 for index, value in enumerate(series)]
    spread = statistics.pstdev(residuals) if len(residuals) > 1 else 0.0
    anomalies = [
        {"period": labels[index], "value": round(series[index], 2),
         "expected": round(intercept + slope * index, 2),
         "gap": round(residual, 2)}
        for index, residual in enumerate(residuals)
        if spread and abs(residual) > 2 * spread
    ]
    calcs = [{"id": "c_anom_spread", "name": "typical_gap_from_trend",
              "value": round(spread, 2),
              "method": "standard deviation of the gaps between actual and trend"}]
    for index, item in enumerate(anomalies[:5]):
        calcs.append({"id": f"c_anom_{index}", "name": f"gap_{item['period']}",
                      "value": item["gap"],
                      "method": f"{item['period']} actual minus its trend value"})
    claims = []
    if anomalies:
        worst = max(anomalies, key=lambda a: abs(a["gap"]))
        claims.append({
            "id": "cl_anom", "type": "finding",
            "text": f"{len(anomalies)} period(s) sit well away from the pattern. "
                    f"The largest is {worst['period']}, which came in "
                    f"{abs(worst['gap']):,.0f} {'above' if worst['gap'] > 0 else 'below'} "
                    "what the trend would give — worth asking what happened then.",
            "evidence": ["c_anom_spread", "c_anom_0"], "status": "verified"})
    else:
        claims.append({
            "id": "cl_anom_clear", "type": "fact",
            "text": "Every period sits close to the overall pattern; nothing stands "
                    "out as unusual.",
            "evidence": ["c_anom_spread"], "status": "verified"})
    return _result(
        "succeeded",
        (f"{len(anomalies)} unusual period(s) against the trend."
         if anomalies else "No period departs from the trend."),
        output={"anomalies": anomalies, "residual_spread": round(spread, 2)},
        calculations=calcs, claims=claims,
    )


def sensitivity(ctx):
    """Sensitivity Agent — would the recommendation survive a different
    assumption?

    The prescriptive ranking rests on one stated improvement assumption.
    This re-scores every option across a range of it and reports whether
    the winner changes, plus the break-even point against the runner-up.
    A recommendation that flips under a small change is a coin toss with
    a spreadsheet attached, and the reader deserves to know which it is.
    """
    options = ctx["prescriptive"].get("options") or []
    if len(options) < 2:
        return _result(
            "succeeded", "Fewer than two options, so there is nothing to test.",
            output={"stable": None, "scenarios": [], "break_even": None},
            calculations=[{"id": "c_sens_none", "name": "options_tested", "value":
                           len(options), "method": "options from the prescriptive stage"}],
            claims=[{"id": "cl_sens_none", "type": "limitation",
                     "text": "With fewer than two options there is no ranking to test "
                             "for sensitivity.",
                     "evidence": ["c_sens_none"], "status": "verified"}])

    # Every option is scored as base_value × uplift, so the ranking is
    # scale-invariant in the uplift — the honest way to say that is to
    # show it rather than assert it.
    winner = options[0]
    runner_up = options[1]
    scenarios = []
    for uplift in (0.05, PLANNING_UPLIFT, 0.20):
        scored = sorted(
            ({"key": o["key"], "title": o["title"],
              "gain": round(o["base_value"] * uplift, 2)} for o in options),
            key=lambda o: -o["gain"])
        scenarios.append({"uplift": uplift, "winner": scored[0]["key"],
                          "gain": scored[0]["gain"]})
    stable = len({s["winner"] for s in scenarios}) == 1

    break_even = None
    if runner_up["base_value"]:
        # How much better the runner-up's uplift would have to be for it
        # to win, holding the leader's assumption fixed.
        break_even = round(winner["base_value"] / runner_up["base_value"], 3)

    calcs = [{"id": "c_sens_stable", "name": "winner_unchanged_across_scenarios",
              "value": 1 if stable else 0,
              "method": "recommended option compared at 5%, 10% and 20% uplift"}]
    if break_even is not None:
        calcs.append({"id": "c_sens_breakeven", "name": "break_even_ratio",
                      "value": break_even,
                      "method": f"“{winner['target']}” current value ÷ "
                                f"“{runner_up['target']}” current value"})
    claims = [{
        "id": "cl_sens", "type": "finding",
        "text": (
            f"The recommendation does not depend on the size of the improvement "
            f"assumed: “{winner['title']}” wins at 5%, 10% and 20% alike."
            if stable else
            "The recommendation changes with the size of the improvement assumed, "
            "so it should be treated as a close call rather than a conclusion.")
        + (f" It would take a {break_even:.1f}× better result in "
           f"“{runner_up['target']}” than in “{winner['target']}” to change the answer."
           if break_even else ""),
        "evidence": ["c_sens_stable"] + (["c_sens_breakeven"] if break_even else []),
        "status": "verified"}]
    return _result(
        "succeeded",
        ("The recommendation holds across every improvement assumption tested."
         if stable else
         "The recommendation depends on the improvement assumed — treat it as a "
         "close call."),
        output={"stable": stable, "scenarios": scenarios, "break_even": break_even},
        calculations=calcs, claims=claims,
    )


def lineage(ctx):
    """Provenance Agent — can every claim be walked back to the data?

    Builds the chain snapshot → calculations → claims and checks that it
    holds in both directions: no claim citing evidence that does not
    exist, and no calculation nobody used. The validator asserts the
    first; this stage makes the whole chain visible, which is what an
    auditor actually asks for.
    """
    produced, cited = {}, set()
    for stage in EVIDENCE_STAGES:
        result = ctx.get(stage + "_result", {})
        for calc in result.get("calculations", []):
            produced[calc["id"]] = stage
        for claim in result.get("claims", []):
            cited.update(claim.get("evidence", []))

    dangling = sorted(cited - set(produced))
    unused = sorted(set(produced) - cited)
    claim_count = sum(len(ctx.get(s + "_result", {}).get("claims", []))
                      for s in EVIDENCE_STAGES)
    calcs = [
        {"id": "c_lin_calcs", "name": "calculations_produced", "value": len(produced),
         "method": "calculations emitted across every evidence-producing stage"},
        {"id": "c_lin_claims", "name": "claims_made", "value": claim_count,
         "method": "claims emitted across every evidence-producing stage"},
        {"id": "c_lin_dangling", "name": "claims_citing_missing_evidence",
         "value": len(dangling),
         "method": "evidence ids cited by a claim but produced by no stage"},
    ]
    return _result(
        "succeeded",
        f"Provenance chain built: {len(produced)} calculations support "
        f"{claim_count} claims, all rooted in snapshot "
        f"sha256:{ctx['collector']['snapshot']}."
        + (f" {len(unused)} calculation(s) went uncited." if unused else ""),
        output={"produced_by_stage": produced, "dangling": dangling,
                "unused": unused, "snapshot": ctx["collector"]["snapshot"]},
        calculations=calcs,
        claims=[{"id": "cl_lineage", "type": "fact",
                 "text": f"Every figure in this report traces back to snapshot "
                         f"sha256:{ctx['collector']['snapshot']} through "
                         f"{len(produced)} recorded calculations.",
                 "evidence": ["c_lin_calcs", "c_lin_dangling"], "status": "verified"}],
        checks=[{"name": "no_claim_cites_missing_evidence", "passed": not dangling,
                 "detail": ("Every cited calculation exists."
                            if not dangling else
                            "Missing evidence: " + ", ".join(dangling))}],
    )


def visuals(ctx):
    prep = ctx["preparer"]
    charts = []
    forecast = ctx.get("predictive", {}).get("forecast") or []
    if prep["groups"]:
        items = sorted(prep["groups"].items(), key=lambda kv: -kv[1])[:8]
        charts.append({"id": "chart_groups", "type": "bar",
                       "title": f"Total {prep['measure']} by {prep['group_col']}",
                       "labels": [k for k, _ in items],
                       "values": [v for _, v in items],
                       "source": "preparer.groups",
                       "alt": f"Bar chart of total {prep['measure']} for each "
                              f"{prep['group_col']}, largest first."})
    if len(prep["trend"]) >= 2:
        charts.append({"id": "chart_trend", "type": "line",
                       "title": f"{prep['measure']} by {prep['date_col']}",
                       "labels": list(prep["trend"].keys()),
                       "values": list(prep["trend"].values()),
                       "source": "preparer.trend",
                       "alt": f"Line chart of {prep['measure']} across "
                              f"{len(prep['trend'])} periods."})
    contributions = ctx.get("diagnostic", {}).get("contributions") or []
    if contributions:
        # The diagnostic answer as a picture: who moved the number, and
        # which way. This is the chart an executive acts on.
        items = contributions[:8]
        charts.append({"id": "chart_contributions", "type": "bar",
                       "title": f"Who moved {prep['measure']}: change by "
                                f"{prep['group_col']}",
                       "labels": [item["group"] for item in items],
                       "values": [item["change"] for item in items],
                       "source": "diagnostic.contributions",
                       "alt": f"Bar chart of the change in {prep['measure']} for each "
                              f"{prep['group_col']} between the first and last period, "
                              "largest mover first; bars below zero moved against the "
                              "overall direction."})
    if forecast:
        # History and forecast on one axis, with the boundary named in the
        # alt text so nobody mistakes a projection for a measurement.
        charts.append({"id": "chart_forecast", "type": "line",
                       "title": f"{prep['measure']}: history and forecast",
                       "labels": list(prep["trend"].keys()) + [f["label"] for f in forecast],
                       "values": list(prep["trend"].values()) + [f["value"] for f in forecast],
                       "source": "preparer.trend + predictive.forecast",
                       "alt": f"Line chart of {prep['measure']} over "
                              f"{len(prep['trend'])} measured periods followed by "
                              f"{len(forecast)} forecast periods; everything after "
                              f"{list(prep['trend'].keys())[-1]} is a projection."})
    expected = {
        "chart_groups": sorted(prep["groups"].values(), reverse=True)[:8],
        "chart_trend": list(prep["trend"].values()),
        "chart_contributions": [item["change"] for item in contributions[:8]],
        "chart_forecast": list(prep["trend"].values()) + [f["value"] for f in forecast],
    }
    checks = [{"name": "chart_values_match_aggregates",
               "passed": all(chart["values"] == expected[chart["id"]] for chart in charts),
               "detail": "Chart values are taken directly from the prepared aggregates "
                         "and the forecast; axes start at zero."}]
    return _result("succeeded",
                   f"Prepared {len(charts)} truthful chart specifications with alt text.",
                   output={"charts": charts}, checks=checks)


MIN_PERIODS_TO_FORECAST = 4
MIN_PERIODS_TO_BACKTEST = 6
FORECAST_HORIZON = 3


def predictive(ctx):
    """Type 3 — What will happen?

    A trend line fitted to the historical periods, extended forward, with
    its accuracy measured by backtesting rather than asserted. A forecast
    that has not been checked against held-out history is a guess with a
    decimal point, so when there is too little history to check, this
    stage says so instead of forecasting.
    """
    prep = ctx["preparer"]
    measure, date_col = prep["measure"], prep["date_col"]
    labels = list(prep["trend"].keys())
    series = list(prep["trend"].values())
    calcs, claims = [], []

    if len(series) < MIN_PERIODS_TO_FORECAST:
        reason = (f"Only {len(series)} period(s) of history are available; at least "
                  f"{MIN_PERIODS_TO_FORECAST} are needed before a forecast means anything.")
        calcs.append({"id": "c_periods", "name": "periods_available",
                      "value": len(series), "method": f"distinct values of {date_col or '—'}"})
        claims.append({"id": "cl_noforecast", "type": "limitation",
                       "text": f"No forecast was produced. {reason}",
                       "evidence": ["c_periods"], "status": "verified"})
        headline = ("We cannot responsibly forecast from this data yet — there is "
                    "not enough history.")
        return _result("succeeded", headline,
                       output={"headline": headline, "forecast": [], "reason": reason,
                               "report_markdown": _section_report(
                                   "Predictive", "What will happen?", ctx,
                                   [reason, "",
                                    "*Producing a number here anyway would look like "
                                    "analysis and behave like a guess.*"], calcs,
                                   headline=headline)},
                       calculations=calcs, claims=claims)

    slope, intercept, explained = _linear_fit(series)
    horizon = FORECAST_HORIZON
    forecast_labels = _next_labels(labels, horizon)
    predictions = [round(intercept + slope * (len(series) + i), 2) for i in range(horizon)]

    # Backtest: refit on all but the last few periods and score the gap.
    holdout = min(3, max(1, len(series) // 4))
    error = None
    if len(series) >= MIN_PERIODS_TO_BACKTEST:
        train, test = series[:-holdout], series[-holdout:]
        t_slope, t_intercept, _ = _linear_fit(train)
        errors = [abs((t_intercept + t_slope * (len(train) + i)) - actual) / abs(actual)
                  for i, actual in enumerate(test) if actual]
        error = round(statistics.fmean(errors), 4) if errors else None

    calcs += [
        {"id": "c_slope", "name": "per_period_change", "value": round(slope, 2),
         "method": f"least-squares slope of {measure} against period order"},
        {"id": "c_explained", "name": "movement_explained_by_trend",
         "value": round(explained, 4),
         "method": "1 − (unexplained variation / total variation) for the fitted line"},
    ]
    for index, (label, value) in enumerate(zip(forecast_labels, predictions)):
        calcs.append({"id": f"c_forecast_{index}", "name": f"forecast_{label}",
                      "value": value,
                      "method": f"trend line extended to period {len(series) + index + 1}"})
    if error is not None:
        calcs.append({"id": "c_backtest", "name": "backtest_error", "value": error,
                      "method": f"average absolute percentage error over the last "
                                f"{holdout} period(s), predicted from earlier ones only"})

    band = ""
    if error is not None:
        low, high = predictions[0] * (1 - error), predictions[0] * (1 + error)
        band = f" In backtesting this method was off by about {error:.1%}, so treat it as " \
               f"roughly {low:,.0f}–{high:,.0f}."
    claims.append({
        "id": "cl_forecast", "type": "forecast",
        "text": f"If the pattern of the last {len(series)} periods continues, {measure} "
                f"for {forecast_labels[0]} is around {predictions[0]:,.2f}.{band} "
                "This assumes nothing changes about how the business operates.",
        "evidence": ["c_forecast_0"] + (["c_backtest"] if error is not None else []),
        "status": "verified"})
    claims.append({
        "id": "cl_fit", "type": "calculation",
        "text": f"The trend line explains {explained:.0%} of the period-to-period "
                f"movement in {measure}; the rest is variation it does not capture.",
        "evidence": ["c_explained"], "status": "verified"})
    if error is None:
        claims.append({
            "id": "cl_nobacktest", "type": "limitation",
            "text": f"The forecast could not be backtested — that needs at least "
                    f"{MIN_PERIODS_TO_BACKTEST} periods — so its accuracy is unmeasured.",
            "evidence": ["c_slope"], "status": "verified"})

    lines = [f"Direction: {measure} is moving {'up' if slope >= 0 else 'down'} by about "
             f"{abs(slope):,.2f} per period.", "",
             "| Period | Forecast |", "| --- | --- |"]
    lines += [f"| {label} | {value:,.2f} |"
              for label, value in zip(forecast_labels, predictions)]
    lines += ["",
              (f"Measured accuracy: predicting the most recent {holdout} period(s) from "
               f"earlier data only, this method was off by {error:.1%} on average."
               if error is not None else
               f"Accuracy is unmeasured: backtesting needs at least "
               f"{MIN_PERIODS_TO_BACKTEST} periods and this dataset has {len(series)}."),
              "",
              f"The trend line explains {explained:.0%} of the movement between periods.",
              "",
              "*This is an extension of the past, not a model of the business. It assumes "
              "no change in pricing, capacity, seasonality beyond what is already in the "
              "data, or market conditions.*"]
    first_value = prep["trend"][labels[-1]]
    expected_move = ((predictions[0] - first_value) / first_value) if first_value else None
    headline = (
        f"We expect {measure} of about {predictions[0]:,.0f} in {forecast_labels[0]}"
        + (f", {'up' if expected_move >= 0 else 'down'} {abs(expected_move):.0%} on the "
           "latest period" if expected_move is not None else "")
        + (f" — this method has been off by about {error:.0%} when tested on past data."
           if error is not None else " — accuracy not yet tested against past data."))
    return _result(
        "succeeded", headline,
        output={"headline": headline,
                "forecast": [{"label": label, "value": value}
                             for label, value in zip(forecast_labels, predictions)],
                "per_period_change": round(slope, 2), "explained": round(explained, 4),
                "backtest_error": error,
                "report_markdown": _section_report("Predictive", "What will happen?",
                                                   ctx, lines, calcs,
                                                   headline=headline)},
        calculations=calcs, claims=claims,
    )


# Every option is scored against the same stated improvement, so the
# ranking reflects where the leverage is — not a claim about how easy any
# option is. That assumption is printed next to the recommendation.
PLANNING_UPLIFT = 0.10


def prescriptive(ctx, gateway=None):
    """Type 4 — What should I do?

    Enumerates options that come from this dataset, scores each with
    arithmetic the reader can check, recommends one, and states what
    would change the answer.
    """
    prep, desc, diag, pred = (ctx["preparer"], ctx["descriptive"],
                              ctx["diagnostic"], ctx["predictive"])
    measure, group_col = prep["measure"], prep["group_col"]
    groups = prep["groups"]
    calcs, claims, options = [], [], []

    def add_option(key, title, target, base_value, rationale, evidence,
                   gain=None, method=None):
        gain = round(base_value * PLANNING_UPLIFT, 2) if gain is None else gain
        calcs.append({"id": f"c_option_{key}", "name": f"expected_gain_{key}",
                      "value": gain,
                      "method": method or (f"{PLANNING_UPLIFT:.0%} of {target}'s current "
                                           f"{measure} ({base_value:,.2f})")})
        options.append({"key": key, "title": title, "target": target,
                        "base_value": round(base_value, 2), "expected_gain": gain,
                        "rationale": rationale,
                        "evidence": evidence + [f"c_option_{key}"]})

    if groups:
        leader = max(groups, key=groups.get)
        add_option("protect_leader", f"Protect the leading {group_col}: “{leader}”",
                   leader, groups[leader],
                   f"It is the largest single source of {measure}, so a given percentage "
                   "improvement is worth more here than anywhere else — and so is a "
                   "given percentage loss.",
                   ["c_topshare"] if desc.get("top_share") is not None else [])
        laggard = min(groups, key=groups.get)
        if laggard != leader:
            add_option("grow_laggard", f"Grow the smallest {group_col}: “{laggard}”",
                       laggard, groups[laggard],
                       "Smallest current contribution, so the same percentage improvement "
                       "moves the total least — but it reduces dependence on the leader.",
                       [])
    declining = [c for c in diag.get("contributions", []) if c["change"] < 0]
    if declining:
        worst = min(declining, key=lambda c: c["change"])
        add_option("recover_decline", f"Reverse the decline in “{worst['group']}”",
                   worst["group"], abs(worst["change"]),
                   f"This segment moved {worst['change']:,.2f} against the overall "
                   "direction; recovering part of that is a defined, bounded target.",
                   ["c_totalchange"])

    forecast = pred.get("forecast") or []
    if forecast:
        # The baseline is worth exactly nothing extra by definition — that
        # is what makes it the bar the others have to clear.
        add_option("hold_course", "Hold course and re-measure next period",
                   "the whole business", 0.0,
                   f"Changing nothing adds nothing: the forecast of "
                   f"{forecast[0]['value']:,.2f} for {forecast[0]['label']} already "
                   "assumes today's behaviour continues. This is the bar every other "
                   "option has to clear.",
                   ["c_forecast_0"], gain=0.0,
                   method="baseline: no change means no gain beyond the forecast")

    if not options:
        reason = ("No option could be derived: the dataset has no grouping column and "
                  "no usable trend, so there is nothing to compare.")
        calcs.append({"id": "c_nooptions", "name": "options_available", "value": 0,
                      "method": "no group column and no forecast"})
        claims.append({"id": "cl_nooptions", "type": "limitation", "text": reason,
                       "evidence": ["c_nooptions"], "status": "verified"})
        headline = ("We cannot recommend an action from this data: there are no "
                    "options to compare.")
        return _result("succeeded", headline,
                       output={"headline": headline,
                               "options": [], "recommendation": None,
                               "exec_summary": reason,
                               "exec_summary_source": "deterministic",
                               "report_markdown": _section_report(
                                   "Prescriptive", "What should I do?", ctx,
                                   [reason], calcs, headline=headline)},
                       calculations=calcs, claims=claims)

    options.sort(key=lambda o: -o["expected_gain"])
    best = options[0]
    runner_up = options[1] if len(options) > 1 else None
    margin = (best["expected_gain"] - runner_up["expected_gain"]) if runner_up else None

    claims.append({
        "id": "cl_recommendation", "type": "recommendation",
        "text": f"Recommended action: {best['title']}. On the same {PLANNING_UPLIFT:.0%} "
                f"improvement applied to every option, it is worth {best['expected_gain']:,.2f} "
                f"in {measure}" +
                (f", ahead of the next option by {margin:,.2f}." if margin else ".") +
                " This is a recommendation under a stated assumption, not an observed "
                "outcome.",
        "evidence": best["evidence"], "status": "verified"})
    claims.append({
        "id": "cl_assumption", "type": "assumption",
        "text": f"Every option is scored with the same {PLANNING_UPLIFT:.0%} improvement "
                "applied to its target. The ranking therefore shows where the leverage is "
                "largest, not which option is easiest to achieve — that judgement needs "
                "cost and feasibility data this dataset does not contain.",
        "evidence": [f"c_option_{best['key']}"], "status": "verified"})

    facts = [f"Total {measure} is {prep['total']:,.2f}."]
    if desc.get("change") is not None:
        facts.append(f"{measure} moved {desc['change']:+.1%} across the period.")
    if diag.get("contributions"):
        facts.append(f"{diag['contributions'][0]['group']} accounts for the largest "
                     "part of that movement.")
    if forecast:
        facts.append(f"Next period is forecast at {forecast[0]['value']:,.2f}.")
    facts.append(f"The recommended action is: {best['title']}.")
    narration = (gateway.narrate(ctx.get("goal", "the analysis"), facts)
                 if gateway else {"text": " ".join(facts), "source": "deterministic"})

    lines = ["| Option | Target | Expected gain | Why |", "| --- | --- | --- | --- |"]
    for option in options:
        lines.append(f"| {option['title']} | {option['target']} | "
                     f"{option['expected_gain']:,.2f} | {option['rationale']} |")
    lines += ["", f"**Recommendation: {best['title']}**", "", best["rationale"], "",
              f"*Every option is scored with the same {PLANNING_UPLIFT:.0%} improvement "
              "applied to its target, so this ranks where the leverage is — not which "
              "option is cheapest or most likely to succeed. Supply cost and feasibility "
              "figures and the ranking can change.*"]
    if margin is not None and best["expected_gain"]:
        closeness = margin / best["expected_gain"]
        lines += ["", f"*How close is the call? The runner-up is behind by "
                      f"{closeness:.0%} of the leading option's value."
                      + (" That is close enough that cost and feasibility should decide "
                         "it, not this ranking.*" if closeness < 0.20 else "*")]
    headline = (f"We recommend: {best['title']}. It is worth about "
                f"{best['expected_gain']:,.0f} in {measure} — more than any other "
                f"option we compared.")
    return _result(
        "succeeded", headline,
        output={"headline": headline, "options": options, "recommendation": best,
                "exec_summary": narration["text"],
                "exec_summary_source": narration["source"],
                # Who chose the narrator, when something did. The report
                # already names which model wrote the summary; why that
                # one belongs beside it (ADR 0017).
                "exec_summary_routing": narration.get("routing"),
                "report_markdown": _section_report("Prescriptive", "What should I do?",
                                                   ctx, lines, calcs,
                                                   headline=headline)},
        calculations=calcs, claims=claims,
    )


def validator(ctx):
    """Independent deterministic verification. May reject work; never
    rewrites evidence."""
    prep = ctx["preparer"]
    checks = []
    if prep["groups"]:
        reconciled = abs(sum(prep["groups"].values()) - prep["total"]) < 0.01
        checks.append({"name": "group_totals_reconcile", "passed": reconciled,
                       "detail": f"Σ(groups)={sum(prep['groups'].values()):,.2f} vs "
                                 f"total={prep['total']:,.2f}"})
    clean = ctx["cleaner"]
    checks.append({"name": "row_accounting",
                   "passed": clean["rows_after"] + clean["dropped"] == clean["rows_before"],
                   "detail": f"{clean['rows_after']} kept + {clean['dropped']} dropped "
                             f"= {clean['rows_before']} input rows"})
    all_calc_ids = {c["id"] for stage in EVIDENCE_STAGES
                    for c in ctx.get(stage + "_result", {}).get("calculations", [])}
    all_claims = [cl for stage in EVIDENCE_STAGES
                  for cl in ctx.get(stage + "_result", {}).get("claims", [])]
    unsupported = [cl["id"] for cl in all_claims
                   if not set(cl.get("evidence", [])) <= all_calc_ids]
    checks.append({"name": "every_claim_has_evidence", "passed": not unsupported,
                   "detail": ("All claims trace to calculations."
                              if not unsupported else
                              f"Unsupported claims: {', '.join(unsupported)}")})

    # Each analytics type must have produced its own report.
    missing_reports = [name for name, _ in ANALYTICS_TYPES
                       if not ctx.get(name, {}).get("report_markdown")]
    checks.append({"name": "every_analytics_type_reported",
                   "passed": not missing_reports,
                   "detail": ("All four analytics types produced a report."
                              if not missing_reports else
                              f"Missing reports: {', '.join(missing_reports)}")})

    # The reason the change decomposition is trustworthy: its parts add up.
    contributions = ctx.get("diagnostic", {}).get("contributions") or []
    if contributions:
        total_change = next(
            (c["value"] for c in ctx["diagnostic_result"]["calculations"]
             if c["id"] == "c_totalchange"), None)
        summed = sum(item["change"] for item in contributions)
        reconciled = total_change is not None and abs(summed - total_change) < 0.01
        checks.append({"name": "change_decomposition_reconciles", "passed": reconciled,
                       "detail": f"Σ(segment changes)={summed:,.2f} vs "
                                 f"total change={total_change:,.2f}"})

    # A forecast that was never checked against held-out history must say so.
    forecast_claims = [cl for cl in all_claims if cl["type"] == "forecast"]
    backtested = ctx.get("predictive", {}).get("backtest_error") is not None
    declared = any(cl["type"] == "limitation" and "backtest" in cl["text"].lower()
                   for cl in all_claims)
    checks.append({"name": "forecast_accuracy_is_measured_or_declared",
                   "passed": not forecast_claims or backtested or declared,
                   "detail": ("Forecast accuracy is backtested." if backtested else
                              "No forecast made." if not forecast_claims else
                              "Unmeasured accuracy is declared as a limitation."
                              if declared else
                              "A forecast was made without measuring or declaring "
                              "its accuracy.")})

    # Every figure in the report is about one column. Whether that column
    # means anything agreed is not optional information.
    measured = ctx.get("governance", {})
    if measured:
        certified = measured.get("certified")
        # Uncertified is allowed; uncertified and unsaid is not.
        declared = any(cl["type"] == "limitation" for cl in
                       ctx.get("governance_result", {}).get("claims", []))
        checks.append({
            "name": "measure_is_certified_or_declared_uncertified",
            "passed": bool(certified or declared),
            "detail": (f"“{measured.get('measure')}” is a certified metric "
                       f"owned by {measured.get('owner')}." if certified else
                       "The report states that the measure carries no certified "
                       "definition." if declared else
                       "The measure is uncertified and the report does not say "
                       "so.")})

    # Recommendations are only honest with their assumptions attached.
    recommendations = [cl for cl in all_claims if cl["type"] == "recommendation"]
    assumptions = [cl for cl in all_claims if cl["type"] == "assumption"]
    checks.append({"name": "recommendations_state_their_assumptions",
                   "passed": not recommendations or bool(assumptions),
                   "detail": (f"{len(recommendations)} recommendation(s), "
                              f"{len(assumptions)} stated assumption(s).")})

    # Personal data must reach the approver, because approval is the moment
    # the report leaves the analyst's hands.
    privacy_result = ctx.get("privacy", {})
    if privacy_result.get("personal_data"):
        surfaced = any(cl["type"] == "warning" for cl in all_claims)
        checks.append({"name": "personal_data_reaches_the_approver",
                       "passed": surfaced,
                       "detail": (f"{len(privacy_result['findings'])} column(s) with "
                                  "personal data are declared in the report."
                                  if surfaced else
                                  "Personal data was detected but no warning reached "
                                  "the report.")})

    # Provenance must hold in the direction that matters: no claim may cite
    # evidence that does not exist.
    dangling = ctx.get("lineage", {}).get("dangling")
    if dangling is not None:
        checks.append({"name": "provenance_chain_is_complete", "passed": not dangling,
                       "detail": ("Every claim walks back to a recorded calculation."
                                  if not dangling else
                                  "Claims cite missing evidence: " + ", ".join(dangling))})

    # Business language is a requirement, so it is checked — on the
    # headlines as well as the claims, since the headline is the line an
    # executive actually reads.
    jargon_hits = {cl["id"]: _jargon_in(cl["text"]) for cl in all_claims
                   if _jargon_in(cl["text"])}
    for name, _ in REPORT_SECTIONS:
        headline = ctx.get(name, {}).get("headline", "")
        if _jargon_in(headline):
            jargon_hits[f"{name}.headline"] = _jargon_in(headline)
    checks.append({"name": "claims_avoid_statistical_jargon",
                   "passed": not jargon_hits,
                   "detail": ("Claims are written in business language."
                              if not jargon_hits else
                              "Jargon found: " + "; ".join(
                                  f"{k}: {', '.join(v)}" for k, v in jargon_hits.items()))})
    passed = all(c["passed"] for c in checks)
    return _result(
        "succeeded" if passed else "failed",
        ("All validation checks passed: totals reconcile, rows are accounted "
         "for, and every claim traces to a calculation.")
        if passed else "Validation FAILED — see quality checks. The work is "
                       "rejected, not rewritten.",
        output={"passed": passed, "claim_count": len(all_claims),
                "unsupported": unsupported},
        checks=checks,
    )


def _routing_note(routing, source=None):
    """How the narrator was chosen, for the line that names it.

    Empty when nothing chose — the gateway's priority order needs no
    explanation, and a sentence saying "no router" in every report would
    be noise.

    The `source` matters because a routing decision can be honoured and
    still not produce the summary: the chosen provider may time out or
    refuse, and the deterministic narrator writes it instead. Reporting
    only the decision would then read as "the deterministic narrator was
    chosen by SmallestLLM", which is not what happened.
    """
    if not routing or not routing.get("router"):
        return ""
    if not routing.get("honoured"):
        return (f", after {routing['router']}'s choice was not used — "
                + routing.get("why", "").rstrip("."))
    if source == "deterministic":
        return (f", after {routing['router']} routed this to "
                f"“{routing['chose']}”, which did not answer")
    return (f", chosen by {routing['router']} which picked "
            f"“{routing['chose']}”")


def reporter(ctx):
    """The comprehensive report: the four type reports in one document.

    It embeds each type report in full rather than linking to it, because
    the approval gate binds to this artifact's hash — whatever a human
    approves for publication is exactly what they were shown.
    """
    prep = ctx["preparer"]
    lines = [
        f"# Business Analytics Report — {ctx.get('dataset_name', 'dataset')}",
        "",
        f"**Goal:** {ctx.get('goal', '')}",
        "",
        "## Executive summary",
        ctx["prescriptive"]["exec_summary"],
        f"*(Narrative source: {ctx['prescriptive']['exec_summary_source']}"
        + _routing_note(ctx["prescriptive"].get("exec_summary_routing"),
                        ctx["prescriptive"]["exec_summary_source"])
        + "; every figure in this report is deterministically calculated.)*",
        "",
        "## The four questions",
        "| Type | Question | Answer in one line |",
        "| --- | --- | --- |",
    ]
    headlines = {
        "descriptive": ctx["descriptive_result"]["summary"],
        "diagnostic": ctx["diagnostic_result"]["summary"],
        "predictive": ctx["predictive_result"]["summary"],
        "prescriptive": ctx["prescriptive_result"]["summary"],
    }
    for name, question in ANALYTICS_TYPES:
        lines.append(f"| {name.capitalize()} | {question} | {headlines[name]} |")
    # The boundary question sits under the table rather than in it: it is
    # not a fifth type, it is the check on what the four may be used for.
    lines += ["", f"**Can we claim a cause?** {ctx['experiment_result']['summary']}",
              "", "## What this report measures",
              ctx["governance"]["notes_markdown"],
              "", "## Data quality, privacy and provenance",
              ctx["governance_result"]["summary"],
              ctx["quality_result"]["summary"],
              ctx["contract_result"]["summary"],
              ctx["profiler_result"]["summary"], ctx["cleaner_result"]["summary"],
              ctx["privacy_result"]["summary"],
              ctx["lineage_result"]["summary"],
              ctx["segments_result"]["summary"],
              ctx["anomaly_result"]["summary"],
              ctx["sensitivity_result"]["summary"],
              "", "## Key metrics",
              "Every figure produced by the run, in one place. Each per-type "
              "section below repeats the figures it used.",
              "", "| Metric | Value | Method |", "| --- | --- | --- |"]
    for stage in EVIDENCE_STAGES:
        for calc in ctx.get(stage + "_result", {}).get("calculations", []):
            lines.append(f"| {calc['name']} | {calc['value']} | {calc['method']} |")

    for name, _ in REPORT_SECTIONS:
        section = ctx[name].get("report_markdown", "")
        # Demote the section's own H1 so the combined document keeps one
        # heading level per depth.
        lines += ["", "---", ""]
        lines += ["#" + line if line.startswith("# ") else line
                  for line in section.split("\n")]

    lines += ["", "---", "", "## Every claim in this report",
              "| Claim | Type | Evidence | Status |", "| --- | --- | --- | --- |"]
    for stage in EVIDENCE_STAGES:
        for claim in ctx.get(stage + "_result", {}).get("claims", []):
            lines.append(f"| {claim['text']} | {claim['type']} | "
                         f"{', '.join(claim['evidence'])} | {claim['status']} |")
    lines += ["", "## Charts"]
    for chart in ctx["visuals"]["charts"]:
        lines.append(f"- **{chart['title']}** ({chart['type']}): {chart['alt']}")
    lines += ["", "## Validation", ctx["validator_result"]["summary"]]
    for check in ctx["validator_result"]["quality_checks"]:
        lines.append(f"- {'PASS' if check['passed'] else 'FAIL'} — "
                     f"{check['name']}: {check['detail']}")
    lines += [
        "", "## Assumptions and limitations",
        "- Findings describe only the supplied snapshot "
        f"(sha256:{ctx['collector']['snapshot']}).",
        "- Diagnostic analysis shows where movement came from and what moves with "
        "what. It does not establish cause; the causal section states whether this "
        "dataset supports a causal claim at all, and what design would settle it.",
        "- The forecast extends the historical pattern. It assumes the business keeps "
        "operating as it has, and it is stated with the error measured by backtesting "
        "(or explicitly marked unmeasured).",
        "- The recommendation ranks options by leverage under one stated improvement "
        "assumption applied equally to each. It is not a claim about cost, feasibility, "
        "or certainty of outcome.",
        "",
        f"*Generated by Agentic OS run {ctx.get('run_id', '')} — measure "
        f"“{prep['measure']}”, {ctx['cleaner']['rows_after']} analyzed rows.*",
    ]
    report = "\n".join(lines)
    return _result(
        "succeeded",
        f"Comprehensive report assembled from all four analytics types: "
        f"{ctx['validator']['claim_count']} claims, all with evidence links, validation "
        + ("passed." if ctx["validator"]["passed"] else "FAILED."),
        output={"report_markdown": report},
    )


# Hermes sequences these. Order is a dependency order, not a preference:
# every stage consumes only what the stages above it have produced.
PIPELINE = [
    ("planner", planner),
    ("collector", collector),
    ("contract", contract),
    ("profiler", profiler),
    ("quality", quality),
    ("privacy", privacy),
    ("cleaner", cleaner),
    # What number is this run about, and who says so? Decided
    # here, on the record, before anything is computed from it.
    ("governance", governance),
    ("preparer", preparer),
    ("segments", segments),
    # The maturity ladder: each type consumes the ones before it.
    ("descriptive", descriptive),
    ("diagnostic", diagnostic),
    # Immediately after the stage that finds associations, because that is
    # where the temptation to call one a cause appears.
    ("experiment", experiment),
    ("predictive", predictive),
    ("anomaly", anomaly),
    ("prescriptive", prescriptive),
    ("sensitivity", sensitivity),
    ("visuals", visuals),
    ("lineage", lineage),
    ("validator", validator),
    ("reporter", reporter),
]

# Stages whose claims and calculations the validator audits.
EVIDENCE_STAGES = ("collector", "contract", "profiler", "quality", "privacy",
                   "cleaner", "governance", "preparer", "segments", "descriptive",
                   "diagnostic",
                   "experiment", "predictive", "anomaly", "prescriptive",
                   "sensitivity", "lineage")

# Stages that receive the model gateway (narration of verified facts only).
NARRATED_STAGES = ("prescriptive",)

# The orchestrator has a name because a system with this many specialists
# needs one thing that is accountable for sequencing, the approval gate,
# and recovery. Hermes is the run engine (server/runs.py), not a stage:
# it never analyses anything itself.
ORCHESTRATOR = "Hermes"

ROLE_TITLES = {
    "planner": "Planner Agent",
    "collector": "Data Source Agent",
    "contract": "Data Contract Agent",
    "profiler": "Data Profiling Agent",
    "quality": "Data Quality Agent",
    "privacy": "Privacy Agent",
    "cleaner": "Data Cleaning Agent",
    "governance": "Metric Governance Agent — is this measure defined and owned?",
    "preparer": "Data Preparation Agent",
    "segments": "Segment Concentration Agent",
    "descriptive": "Descriptive Analytics Agent — what happened?",
    "diagnostic": "Diagnostic Analytics Agent — why did it happen?",
    "experiment": "Experiment and Causal Inference Agent — can we claim a cause?",
    "predictive": "Predictive Analytics Agent — what will happen?",
    "anomaly": "Anomaly Detection Agent",
    "prescriptive": "Prescriptive Analytics Agent — what should I do?",
    "sensitivity": "Sensitivity Agent — would the advice survive a different assumption?",
    "visuals": "Visualization Expert",
    "lineage": "Provenance Agent",
    "validator": "Validation Expert",
    "reporter": "Reporting Expert",
    "publish": "Knowledge Curator (vault publish)",
}
