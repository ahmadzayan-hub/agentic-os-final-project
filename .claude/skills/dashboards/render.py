#!/usr/bin/env python3
"""Render a dashboard spec to one self-contained HTML file, offline.

    python .claude/skills/dashboards/render.py --spec spec.json --out dashboard.html
    python .claude/skills/dashboards/render.py --analysis analysis.json --out dashboard.html \\
        [--write-spec spec.json]          # a default dashboard from scripts/analyse.py
    python .claude/skills/dashboards/render.py --spec spec.json --check

The free route of the dashboards skill. No network, no scripts, no CDN: the
charts are SVG drawn here. Every figure carries a numbered source, listed at
the foot of the page, as Claude Dashboards shows the query behind a number.
Each chart has its numbers in a table beneath it. English or Arabic (right
to left), light or dark by the reader's setting, and it prints. Standard
library only.
"""

import argparse
import html
import json
import sys
from pathlib import Path

MAX_SECTIONS, MAX_KPIS, MAX_BARS, MAX_POINTS, MAX_ROWS = 16, 8, 24, 160, 60
TYPES = ("kpis", "bars", "line", "table", "text")


# ---------------------------------------------------------------------------
# Validation: a figure without a source is refused, as in the motion skill.
# ---------------------------------------------------------------------------

def validate(spec):
    problems = []

    def need(ok, message):
        if not ok:
            problems.append(message)

    need(isinstance(spec, dict), "The spec must be a JSON object.")
    if problems:
        return problems
    need(bool(spec.get("title")), "The dashboard needs a title.")
    need(spec.get("language", "en") in ("en", "ar"), "language must be en or ar.")
    need(spec.get("theme", "default") in THEMES, f"theme must be one of {', '.join(THEMES)}.")
    sections = spec.get("sections") or []
    need(0 < len(sections) <= MAX_SECTIONS, f"Use 1 to {MAX_SECTIONS} sections.")
    for index, section in enumerate(sections, 1):
        where = f"section {index}"
        kind = section.get("type")
        need(kind in TYPES, f"{where}: type must be one of {', '.join(TYPES)}.")
        if kind in ("kpis", "bars"):
            items = section.get("items") or []
            limit = MAX_KPIS if kind == "kpis" else MAX_BARS
            need(0 < len(items) <= limit, f"{where}: 1 to {limit} items.")
            for i, item in enumerate(items, 1):
                need(isinstance(item.get("value"), (int, float)) and not isinstance(item.get("value"), bool),
                     f"{where}, item {i}: value must be a number.")
                need(bool(item.get("label")), f"{where}, item {i}: needs a label.")
                need(bool(str(item.get("source", "")).strip()),
                     f"{where}, item {i}: every figure needs a source.")
        if kind == "line":
            labels, values = section.get("labels") or [], section.get("values") or []
            need(1 < len(labels) == len(values) <= MAX_POINTS,
                 f"{where}: labels and values must match, 2 to {MAX_POINTS} points.")
            need(all(isinstance(v, (int, float)) for v in values), f"{where}: values must be numbers.")
            need(bool(str(section.get("source", "")).strip()), f"{where}: a chart needs a source.")
        if kind == "table":
            columns, rows = section.get("columns") or [], section.get("rows") or []
            need(bool(columns) and all(len(r) == len(columns) for r in rows) and len(rows) <= MAX_ROWS,
                 f"{where}: rows must match the columns, at most {MAX_ROWS} rows.")
            need(bool(str(section.get("source", "")).strip()), f"{where}: a table needs a source.")
        if kind == "text":
            need(bool(section.get("body") or section.get("items")), f"{where}: text needs a body or items.")
    return problems


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fmt(item, language="en"):
    value = item["value"]
    decimals = item.get("decimals", 0 if float(value).is_integer() or abs(value) >= 100 else 1)
    text = f"{value:,.{decimals}f}"
    if item.get("format") == "currency":
        code = item.get("currency", "USD")
        symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(code)
        if language == "ar":
            text = f"{text} {code if not symbol else 'US$' if code == 'USD' else symbol}"
        else:
            text = f"{symbol}{text}" if symbol else f"{code} {text}"
    return f"{item.get('prefix', '')}{text}{item.get('suffix', '')}"


class Sources:
    """Numbered sources, in the order they first appear."""

    def __init__(self):
        self.items = []

    def ref(self, text):
        text = str(text).strip()
        if text not in self.items:
            self.items.append(text)
        n = self.items.index(text) + 1
        return f'<sup class="ref"><a href="#src-{n}" aria-label="source {n}">[{n}]</a></sup>'


def esc(value):
    return html.escape(str(value), quote=True)


# ---------------------------------------------------------------------------
# Charts, drawn as SVG here
# ---------------------------------------------------------------------------

def bar_svg(items, language):
    width, row, label_w, value_w = 640, 30, 170, 110
    height = row * len(items) + 8
    top = max(abs(i["value"]) for i in items) or 1
    span = width - label_w - value_w - 16
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-hidden="true" class="chart">']
    for index, item in enumerate(items):
        y = 4 + index * row
        length = max(1.0, span * abs(item["value"]) / top)
        cls = "bar bar--hi" if item.get("highlight") else "bar"
        parts.append(f'<text x="{label_w - 8}" y="{y + 19}" text-anchor="end" class="label">{esc(item["label"])}</text>')
        parts.append(f'<rect x="{label_w}" y="{y + 5}" width="{length:.1f}" height="{row - 10}" rx="3" class="{cls}"/>')
        parts.append(f'<text x="{label_w + length + 8:.1f}" y="{y + 19}" class="value">{esc(fmt(item, language))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def line_svg(labels, values, forecast_from=None):
    width, height, pad_l, pad_r, pad_t, pad_b = 640, 260, 64, 16, 16, 40
    low, high = min(0, min(values)), max(values) or 1
    span_y = (high - low) or 1
    step = (width - pad_l - pad_r) / max(1, len(values) - 1)
    x = lambda i: pad_l + i * step
    y = lambda v: pad_t + (height - pad_t - pad_b) * (1 - (v - low) / span_y)
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-hidden="true" class="chart">']
    for k in range(5):
        v = low + span_y * k / 4
        parts.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="tick">{v:,.0f}</text>')
    cut = forecast_from if forecast_from is not None else len(values)
    measured = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values[:cut]))
    parts.append(f'<polyline points="{measured}" class="line"/>')
    if cut < len(values):
        ahead = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in list(enumerate(values))[cut - 1:])
        parts.append(f'<polyline points="{ahead}" class="line line--forecast"/>')
    # About six labels, always the last; the edge labels anchor inwards.
    every = max(1, -(-len(labels) // 6))
    shown = [i for i in range(len(labels)) if i % every == 0 and len(labels) - 1 - i >= every]
    for i in shown + [len(labels) - 1]:
        anchor = "start" if i == 0 else "end" if i == len(labels) - 1 else "middle"
        parts.append(f'<text x="{x(i):.1f}" y="{height - 14}" text-anchor="{anchor}" class="tick">{esc(labels[i])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def data_table(headers, rows, caption_text):
    head = "".join(f'<th scope="col">{esc(h)}</th>' for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return (f'<details class="numbers"><summary>{esc(caption_text)}</summary>'
            f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></details>')


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

WORDS = {
    "en": {"sources": "Sources", "numbers": "The numbers in this chart", "label": "Label", "value": "Value",
           "forecast": "forecast", "made": "Every figure is numbered to its source below."},
    "ar": {"sources": "المصادر", "numbers": "أرقام هذا المخطط", "label": "التسمية", "value": "القيمة",
           "forecast": "توقع", "made": "كل رقم مرقّم إلى مصدره في الأسفل."},
}

CSS = """
:root{--bg:#f6f5f1;--panel:#fbfbf8;--fg:#17252f;--muted:#5b6770;--line:#dce2e5;--accent:#2f6690;--accent-soft:#dbe7f0;--hi:#a35a14}
@media (prefers-color-scheme:dark){:root{--bg:#0f1a24;--panel:#152331;--fg:#eef2f5;--muted:#9aa8b4;--line:#2a3b4a;--accent:#7fb2dc;--accent-soft:#1d3346;--hi:#f0b46e}}
*{box-sizing:border-box}html{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Arabic",sans-serif}
body{margin:0 auto;max-width:1100px;padding:24px 16px 48px}
header h1{font-size:1.9rem;line-height:1.2;margin:0 0 .3rem}header p{margin:0;color:var(--muted)}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-top:16px}
h2{font-size:1.15rem;margin:0 0 .8rem}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.kpi{border:1px solid var(--line);border-top:4px solid var(--accent);border-radius:8px;padding:12px 14px}
.kpi__value{font-size:1.7rem;font-weight:700;font-variant-numeric:tabular-nums;unicode-bidi:isolate}.kpi__label{color:var(--muted);font-size:.95rem}
.chart{display:block;max-width:100%;height:auto}.chart text{fill:var(--fg);font:12px system-ui,sans-serif}.chart .tick{fill:var(--muted);font-size:11px}
.chart .bar{fill:var(--accent)}.chart .bar--hi{fill:var(--hi)}.chart .value{font-weight:600}
.chart .grid{stroke:var(--line)}.chart .line{fill:none;stroke:var(--accent);stroke-width:2.5}.chart .line--forecast{stroke-dasharray:6 5}
.note{color:var(--muted);font-size:.95rem;margin:.6rem 0 0}
details.numbers{margin-top:.6rem}details.numbers summary{cursor:pointer;color:var(--accent)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:.95rem}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:start}th{color:var(--muted);font-weight:600}
.table-wrap{overflow-x:auto}
sup.ref a{color:var(--muted);text-decoration:none;font-size:.75em}
footer ol{padding-inline-start:1.4em;color:var(--muted);font-size:.92rem}footer h2{margin-top:24px}
a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media print{section{break-inside:avoid}details.numbers{display:block}details.numbers[open] summary{display:none}}
"""

# The user's house style (.claude/skills/rta-style): its colours and type over
# this page's layout. Colours, type and motifs only; no logo, name or data.
STYLE_TOKENS = Path(__file__).resolve().parent.parent / "rta-style" / "tokens.json"
THEMES = ("default", "rta")


def theme_css(theme):
    if theme != "rta":
        return ""
    tokens = json.loads(STYLE_TOKENS.read_text(encoding="utf-8"))

    def palette(p):
        return (f"--bg:{p['bg']};--panel:{p['surface']};--fg:{p['text']};--muted:{p['muted']};--line:{p['border']};"
                f"--accent:{p['accent']};--accent-soft:{p['accent-tint']};--hi:{p['brand']};--brand:{p['brand']};"
                f"--bar:{p['bar']};--bar-edge:{p['bar-edge']};--on-bar:{p['on-brand']}")
    return (f":root{{{palette(tokens['light'])}}}"
            f"@media (prefers-color-scheme:dark){{:root{{{palette(tokens['dark'])}}}}}"
            f"html{{font-family:{tokens['font']['family']}}}.chart text{{font-family:{tokens['font']['family']}}}"
            f"header{{background:var(--bar);color:var(--on-bar);border-bottom:4px solid var(--bar-edge);"
            f"border-radius:{tokens['radius']};padding:16px 20px}}header p{{color:var(--on-bar)}}"
            f"section{{border-radius:{tokens['radius']}}}"
            "h2{padding-inline-start:.6rem;border-inline-start:4px solid var(--brand)}footer h2{border:0;padding:0}"
            ".kpi{border-top:1px solid var(--line);border-inline-start:5px solid var(--accent)}"
            ".kpi:first-child{border-inline-start-color:var(--brand)}"
            "@media print{header{-webkit-print-color-adjust:exact;print-color-adjust:exact}}")


def render(spec, theme=None):
    theme = theme or spec.get("theme", "default")
    language = spec.get("language", "en")
    words = WORDS[language]
    sources = Sources()
    blocks = []
    for section in spec["sections"]:
        kind, title = section["type"], section.get("title", "")
        inner = []
        if kind == "kpis":
            cards = "".join(
                f'<div class="kpi"><div class="kpi__value"><bdi>{esc(fmt(i, language))}</bdi>{sources.ref(i["source"])}</div>'
                f'<div class="kpi__label">{esc(i["label"])}</div></div>' for i in section["items"])
            inner.append(f'<div class="kpis">{cards}</div>')
        elif kind == "bars":
            refs = "".join(sorted({sources.ref(i["source"]) for i in section["items"]}))
            inner.append(f'<figure dir="ltr">{bar_svg(section["items"], language)}</figure>')
            inner.append(data_table([words["label"], words["value"]],
                                    [[i["label"], fmt(i, language)] for i in section["items"]], words["numbers"]))
            title += refs
        elif kind == "line":
            labels, values = section["labels"], section["values"]
            cut = section.get("forecast_from")
            inner.append(f'<figure dir="ltr">{line_svg(labels, values, cut)}</figure>')
            rows = [[f"{l} ({words['forecast']})" if cut is not None and k >= cut else l,
                     fmt({**section, "value": v}, language)] for k, (l, v) in enumerate(zip(labels, values))]
            inner.append(data_table([words["label"], words["value"]], rows, words["numbers"]))
            title += sources.ref(section["source"])
        elif kind == "table":
            head = "".join(f'<th scope="col">{esc(c)}</th>' for c in section["columns"])
            body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in section["rows"])
            inner.append(f'<div class="table-wrap" tabindex="0" role="region" aria-label="{esc(section.get("title", ""))}">'
                         f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
            title += sources.ref(section["source"])
        elif kind == "text":
            if section.get("body"):
                inner.append(f'<p>{esc(section["body"])}</p>')
            if section.get("items"):
                inner.append("<ul>" + "".join(f"<li>{esc(i)}</li>" for i in section["items"]) + "</ul>")
            if section.get("source"):
                title += sources.ref(section["source"])
        if section.get("note"):
            inner.append(f'<p class="note">{esc(section["note"])}</p>')
        heading = f"<h2>{title if '<sup' in title else esc(title)}</h2>" if title else ""
        if "<sup" in title:
            heading = f"<h2>{esc(section.get('title', ''))}{title[len(section.get('title', '')):]}</h2>"
        blocks.append(f"<section>{heading}{''.join(inner)}</section>")
    listed = "".join(f'<li id="src-{n}">{esc(s)}</li>' for n, s in enumerate(sources.items, 1))
    direction = "rtl" if language == "ar" else "ltr"
    return (f'<!doctype html><html lang="{language}" dir="{direction}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(spec["title"])}</title><style>{CSS}{theme_css(theme)}</style></head><body>'
            f'<header><h1>{esc(spec["title"])}</h1><p>{esc(spec.get("subtitle", words["made"]))}</p></header>'
            f'<main>{"".join(blocks)}</main>'
            f'<footer><h2>{words["sources"]}</h2><ol>{listed}</ol>'
            f'<p class="note">{esc(spec.get("footer", ""))}</p></footer></body></html>')


# ---------------------------------------------------------------------------
# A default dashboard from scripts/analyse.py
# ---------------------------------------------------------------------------

# Matches server/analytics.UNEVEN_PERIODS (ADR 0026).
UNEVEN_PERIODS = 0.75


def spec_from_analysis(analysis, language=None):
    language = language or analysis.get("language", "en")
    prep = analysis.get("prepared") or {}
    calcs = {c["ref"]: c for c in analysis.get("calculations", [])}
    measure = prep.get("measure") or "measure"
    kpis = []
    for ref, label, extra in (
            ("preparer.c_total", f"Total {measure}", {}),
            ("collector.c_rows", "Rows analysed", {}),
            ("profiler.c_completeness", "Completeness", {"scale": 100, "suffix": "%", "decimals": 1})):
        calc = calcs.get(ref)
        if calc and isinstance(calc.get("value"), (int, float)):
            value = calc["value"] * extra.pop("scale", 1)
            kpis.append({"label": label, "value": round(value, 4), **extra,
                         "source": f"{ref} · {calc.get('method', '')}"})
    sections = []
    if kpis:
        sections.append({"type": "kpis", "title": "Key figures", "items": kpis})
    # What a reader must see before trusting the figures: limitations,
    # warnings and failed checks come first, never only in a table at the end.
    cautions = [c["text"] for c in analysis.get("claims", []) if c.get("type") in ("limitation", "warning")]
    cautions += [f"Check failed: {c.get('name', '')}: {c.get('detail', '')}" for c in analysis.get("failed_checks", [])]
    if cautions:
        sections.append({"type": "text", "title": "Read with care", "items": cautions[:MAX_ROWS],
                         "source": "governed pipeline · limitation and warning claims, failed quality checks"})
    if prep.get("trend") and len(prep["trend"]) > 1:
        grain = prep.get("date_grain")
        suffix = f" ({grain})" if grain and grain != prep.get("date_col") else ""
        sections.append({"type": "line", "title": f"{measure} by {prep.get('date_col')}{suffix}",
                         "labels": list(prep["trend"]), "values": list(prep["trend"].values()),
                         "source": f"preparer · sum({measure}) by {prep.get('date_col')}"})
        counts = prep.get("trend_counts") or {}
        if counts and min(counts.values()) < UNEVEN_PERIODS * max(counts.values()):
            # Periods of different sizes: the total moves with the number of
            # records, so the per-record line is the one to read (ADR 0026).
            sections.append({"type": "line", "title": f"{measure} per record, by {prep.get('date_col')}{suffix}",
                             "labels": list(prep["trend"]),
                             "values": [round(v / counts[k], 2) for k, v in prep["trend"].items()],
                             "source": f"preparer · sum({measure}) ÷ records, by {prep.get('date_col')} "
                                       f"(periods hold {min(counts.values()):,} to {max(counts.values()):,} records)"})
    if prep.get("groups"):
        top = sorted(prep["groups"].items(), key=lambda kv: -kv[1])[:MAX_BARS]
        sections.append({"type": "bars", "title": f"{measure} by {prep.get('group_col')}",
                         "items": [{"label": k, "value": v, "highlight": n == 0,
                                    "source": f"preparer · sum({measure}) by {prep.get('group_col')}"}
                                   for n, (k, v) in enumerate(top)]})
        counts = prep.get("group_counts") or {}
        if counts and min(counts.values()) < UNEVEN_PERIODS * max(counts.values()):
            # Groups of different sizes: the biggest total may just be the
            # biggest group. Per record, the ranking can change.
            rates = sorted(((k, round(v / counts[k], 2)) for k, v in prep["groups"].items() if counts.get(k)),
                           key=lambda kv: -kv[1])[:MAX_BARS]
            sections.append({"type": "bars", "title": f"{measure} per record, by {prep.get('group_col')}",
                             "items": [{"label": k, "value": v, "highlight": n == 0,
                                        "source": f"preparer · sum({measure}) ÷ records in each {prep.get('group_col')}"}
                                       for n, (k, v) in enumerate(rates)]})
    headlines = [h["headline"] for h in analysis.get("headlines", []) if h.get("headline")]
    if headlines:
        sections.append({"type": "text", "title": "What the analysis found", "items": headlines,
                         "source": "governed pipeline · validated claims, one per analytics type"})
    claims = [c for c in analysis.get("claims", []) if c.get("evidence")][:MAX_ROWS]
    if claims:
        sections.append({"type": "table", "title": "Claims and the calculations behind them",
                         "columns": ["Stage", "Claim", "Evidence"],
                         "rows": [[c["stage"], c.get("text", ""), ", ".join(c["evidence"])] for c in claims],
                         "source": "governed pipeline · claims checked by the validator stage"})
    dataset = analysis.get("dataset", {})
    return {"title": f"{dataset.get('name', 'Dataset')}: {measure}", "language": language,
            "subtitle": analysis.get("goal", ""),
            "footer": f"{dataset.get('name', '')} · {dataset.get('rows', '?')} rows · "
                      f"analysed by the governed pipeline (scripts/analyse.py), state {analysis.get('state')}",
            "sections": sections}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec", help="a dashboard spec JSON")
    source.add_argument("--analysis", help="an export from scripts/analyse.py")
    parser.add_argument("--out", help="the HTML file to write")
    parser.add_argument("--write-spec", help="with --analysis: also save the spec it made")
    parser.add_argument("--check", action="store_true", help="validate only")
    parser.add_argument("--theme", choices=THEMES, help="override the spec's theme (rta: the user's house style)")
    args = parser.parse_args(argv)
    if args.spec:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    else:
        spec = spec_from_analysis(json.loads(Path(args.analysis).read_text(encoding="utf-8")))
        if args.write_spec:
            Path(args.write_spec).write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    problems = validate(spec)
    if problems:
        print(f"{len(problems)} problem(s):\n- " + "\n- ".join(problems), file=sys.stderr)
        return 1
    figures = sum(len(s.get("items", [])) for s in spec["sections"] if s["type"] in ("kpis", "bars"))
    if args.check or not args.out:
        print(f"OK: {len(spec['sections'])} sections, {figures} figures, each with a source.")
        return 0
    Path(args.out).write_text(render(spec, args.theme), encoding="utf-8")
    print(f"Wrote {args.out}: {len(spec['sections'])} sections, {figures} figures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
