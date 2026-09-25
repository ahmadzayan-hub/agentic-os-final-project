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


# ---------------------------------------------------------------------------
# The report's language (ADR 0022). A run is written in one language, chosen
# when it is created, because the approval gate binds to the hash of one
# artifact. English stays the audited record: every claim keeps its English
# `text`, and an Arabic run adds `text_ar` beside it. Numbers, evidence ids,
# calculation names and methods are the same bytes in both, and the
# validator checks that they are.
# ---------------------------------------------------------------------------

REPORT_LANGUAGES = ("en", "ar")


def report_language(ctx):
    language = ctx.get("report_language") or "en"
    return language if language in REPORT_LANGUAGES else "en"


def _say(ctx, en, ar):
    """The reader's sentence. Both are written out in full at the call
    site, so each can be read, and reviewed, as a sentence."""
    return ar if report_language(ctx) == "ar" else en


def _claim(ctx, claim_id, kind, en, ar, evidence):
    claim = {"id": claim_id, "type": kind, "text": en,
             "evidence": evidence, "status": "verified"}
    if report_language(ctx) == "ar":
        claim["text_ar"] = ar
    return claim


# Arabic counts take the noun form their number asks for: one, two, three
# to ten, eleven to ninety-nine, and the rest. The same six CLDR categories
# the interface uses (ADR 0018), applied to the report's nouns. One and two
# are carried by the noun itself ("صفان", two rows), as the grammar asks,
# which is why the parity check below does not look for a bare 1 or 2.
AR_NOUNS = {
    "row": ("صف واحد", "صفان", "صفوف", "صفاً", "صف"),
    "column": ("عمود واحد", "عمودان", "أعمدة", "عموداً", "عمود"),
    "period": ("فترة واحدة", "فترتان", "فترات", "فترة", "فترة"),
    "record": ("سجل واحد", "سجلان", "سجلات", "سجلاً", "سجل"),
    "group": ("مجموعة واحدة", "مجموعتان", "مجموعات", "مجموعة", "مجموعة"),
    "segment": ("شريحة واحدة", "شريحتان", "شرائح", "شريحة", "شريحة"),
    "observation": ("مشاهدة واحدة", "مشاهدتان", "مشاهدات", "مشاهدة", "مشاهدة"),
    "value": ("قيمة واحدة", "قيمتان", "قيم", "قيمة", "قيمة"),
    "calculation": ("عملية حسابية واحدة", "عمليتان حسابيتان", "عمليات حسابية",
                    "عملية حسابية", "عملية حسابية"),
    "claim": ("استنتاج واحد", "استنتاجان", "استنتاجات", "استنتاجاً", "استنتاج"),
    "problem": ("مشكلة واحدة", "مشكلتان", "مشكلات", "مشكلة", "مشكلة"),
    "comparison": ("مقارنة واحدة", "مقارنتان", "مقارنات", "مقارنة", "مقارنة"),
    "recommendation": ("توصية واحدة", "توصيتان", "توصيات", "توصية", "توصية"),
    "assumption": ("افتراض واحد", "افتراضان", "افتراضات", "افتراضاً", "افتراض"),
    "chart": ("مخطط واحد", "مخططان", "مخططات", "مخططاً", "مخطط"),
    "unusual_period": ("فترة واحدة غير اعتيادية", "فترتان غير اعتياديتين",
                       "فترات غير اعتيادية", "فترة غير اعتيادية",
                       "فترة غير اعتيادية"),
}


def _ar_n(count, noun, grouped=False):
    one, two, few, many, other = AR_NOUNS[noun]
    count = int(count)
    if count == 1:
        return one
    if count == 2:
        return two
    shown = f"{count:,}" if grouped else str(count)
    tail = count % 100
    if 3 <= tail <= 10:
        return f"{shown} {few}"
    if 11 <= tail <= 99:
        return f"{shown} {many}"
    return f"{shown} {other}"


# A figure is a run of digits with its separators, sign and percent sign.
# Two sentences cite the same figures when these multisets are equal.
_FIGURE = re.compile(r"[-+−]?\d[\d,]*(?:\.\d+)?%?")


def figures(text):
    """The figures a sentence cites, in a form two languages can share.
    A bare 1 or 2 is left out: Arabic says it with the noun (see AR_NOUNS)."""
    found = (token.lstrip("+-−").rstrip(",").replace(",", "")
             for token in _FIGURE.findall(text or ""))
    return sorted(token for token in found if token not in ("1", "2"))


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


def _period_label(ctx, label):
    """A period label as the reader sees it. The label itself is an
    identifier (it names a calculation), so only its display changes."""
    if report_language(ctx) == "ar" and str(label).startswith("next period +"):
        return "الفترة التالية +" + str(label)[len("next period +"):]
    return label


# Statistical vocabulary that loses a business reader. Claims are written
# in plain language and this list is enforced as a quality check, not a
# style preference (see validator.no_statistical_jargon_in_claims).
JARGON = (
    "p-value", "p <", "p<", "r²", "r^2", "r-squared",
    "coefficient of determination", "standard deviations",
    "statistically significant", "null hypothesis", "confidence interval",
    "heteroskedastic", "regression coefficient",
    # The same vocabulary as an Arabic report would carry it.
    "القيمة الاحتمالية", "دلالة إحصائية", "دال إحصائياً", "دالة إحصائياً",
    "فرضية العدم", "فترة الثقة", "فاصل الثقة", "معامل التحديد",
    "الانحراف المعياري", "انحرافات معيارية", "معامل الانحدار",
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


# Section titles and questions as an Arabic report states them. The
# interface's own labels (frontend/src/i18n/ar.ts) use the same words.
SECTION_TITLES_AR = {
    "Descriptive": ("التحليل الوصفي", "ماذا حدث؟"),
    "Diagnostic": ("التحليل التشخيصي", "لماذا حدث؟"),
    "Causal": ("التحليل السببي", "هل يمكننا ادعاء سبب؟"),
    "Predictive": ("التحليل التنبؤي", "ماذا سيحدث؟"),
    "Prescriptive": ("التحليل التوجيهي", "ماذا ينبغي أن أفعل؟"),
}

# Said once under every calculation table in an Arabic report, because the
# table is deliberately left as the evidence record wrote it.
AR_METHODS_NOTE = ("*تبقى أسماء الأرقام وطرق حسابها بصيغتها الأصلية، لأنها "
                   "المعرّفات التي تستند إليها كل جملة في التقرير.*")


def _section_report(title, question, ctx, body_lines, calculations, headline=None):
    """One self-contained report per analytics type, readable on its own.

    It opens with the headline — one sentence in business language, which
    is the only line most executives will read. A finding that cannot be
    communicated cannot drive action.
    """
    if report_language(ctx) == "ar":
        title_ar, question_ar = SECTION_TITLES_AR[title]
        lines = [f"# {title_ar}: {question_ar}", "",
                 f"**البيانات:** {ctx.get('dataset_name', 'dataset')} · "
                 f"**الهدف:** {ctx.get('goal', '')}", ""]
    else:
        lines = [f"# {title} Analytics — {question}", "",
                 f"**Dataset:** {ctx.get('dataset_name', 'dataset')} · "
                 f"**Goal:** {ctx.get('goal', '')}", ""]
    if headline:
        lines += [f"> **{headline}**", ""]
    lines += body_lines
    if calculations:
        lines += ["", _say(ctx, "## How each figure was calculated",
                           "## كيف حُسب كل رقم"),
                  _say(ctx, "| Figure | Value | Method |", "| الرقم | القيمة | الطريقة |"),
                  "| --- | --- | --- |"]
        lines += [f"| {c['name']} | {c['value']} | {c['method']} |" for c in calculations]
        if report_language(ctx) == "ar":
            lines += ["", AR_METHODS_NOTE]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Specialists
# ---------------------------------------------------------------------------

def planner(ctx):
    stages = [role for role, _ in PIPELINE]
    return _result(
        "succeeded",
        _say(ctx,
             "Pattern: sequential governed pipeline — the goal is a repeatable "
             "analytics workflow, so the simplest sufficient pattern applies. "
             "Stopping rule: fixed bounded stage list with an approval gate "
             "before publishing.",
             "النمط: خط متسلسل خاضع للحوكمة، لأن الهدف سير عمل تحليلي قابل "
             "للتكرار، فيكفي أبسط نمط يؤدي الغرض. قاعدة التوقف: قائمة مراحل "
             "محددة ومحدودة، وبوابة موافقة قبل النشر."),
        output={"stages": stages, "pattern": "sequential_governed_pipeline"},
        checks=[{"name": "plan_has_validation_stage", "passed": "validator" in stages,
                 "detail": _say(ctx, "Independent validation is part of the plan.",
                                "التحقق المستقل جزء من الخطة.")}],
    )


def collector(ctx):
    text = ctx.get("dataset_text") or ""
    if len(text.encode()) > MAX_DATASET_BYTES:
        limit = MAX_DATASET_BYTES // 1_000_000
        return _fail(_say(ctx, f"Dataset exceeds the {limit} MB limit.",
                          f"تتجاوز البيانات الحد المسموح به وهو {limit} ميغابايت."))
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = [row for _, row in zip(range(MAX_ROWS + 1), reader)]
    except csv.Error as error:
        return _fail(_say(ctx, f"The dataset could not be parsed as CSV: {error}",
                          f"تعذّرت قراءة البيانات بصيغة CSV: {error}"))
    if not rows or not reader.fieldnames:
        return _fail(_say(ctx, "The dataset is empty or has no header row.",
                          "البيانات فارغة أو لا تحتوي على صف عناوين."))
    if len(rows) > MAX_ROWS:
        return _fail(_say(ctx, f"Dataset exceeds the {MAX_ROWS}-row limit.",
                          f"تتجاوز البيانات الحد المسموح به وهو {MAX_ROWS} صف."))
    columns = [c for c in reader.fieldnames if c]
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return _result(
        "succeeded",
        _say(ctx,
             f"Ingested {len(rows)} rows × {len(columns)} columns "
             f"(snapshot sha256:{digest}).",
             f"استُلمت البيانات: {_ar_n(len(rows), 'row')} "
             f"و{_ar_n(len(columns), 'column')} (لقطة البيانات sha256:{digest})."),
        output={"rows": rows, "columns": columns, "snapshot": digest,
                "row_count": len(rows)},
        calculations=[{"id": "c_rows", "name": "row_count", "value": len(rows),
                       "method": "len(csv rows)"}],
        claims=[_claim(ctx, "cl_ingest", "fact",
                       f"The dataset contains {len(rows)} rows and {len(columns)} columns.",
                       f"تحتوي البيانات على {_ar_n(len(rows), 'row')} "
                       f"و{_ar_n(len(columns), 'column')}.",
                       ["c_rows"])],
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
        _say(ctx,
             f"Profiled quality: completeness {completeness:.0%}, "
             f"{duplicates} duplicate rows, numeric columns: "
             f"{', '.join(numeric_columns) or 'none'}.",
             f"فُحصت الجودة: الاكتمال {completeness:.0%}، والصفوف المكررة "
             f"{duplicates}، والأعمدة الرقمية: "
             f"{'، '.join(numeric_columns) or 'لا يوجد'}."),
        output={"profile": profile, "numeric_columns": numeric_columns,
                "duplicates": duplicates, "completeness": completeness},
        calculations=calcs,
        claims=[_claim(ctx, "cl_quality", "fact",
                       f"Data completeness is {completeness:.0%} with {duplicates} duplicate rows.",
                       f"اكتمال البيانات {completeness:.0%}، وعدد الصفوف المكررة "
                       f"{duplicates}.",
                       ["c_completeness", "c_dupes"])],
        checks=[{"name": "has_numeric_column", "passed": bool(numeric_columns),
                 "detail": _say(ctx,
                                "At least one numeric measure is required for analysis.",
                                "يلزم مقياس رقمي واحد على الأقل لإجراء التحليل.")}],
    )


def cleaner(ctx):
    rows = ctx["collector"]["rows"]
    numeric_columns = ctx["profiler"]["numeric_columns"]
    if not numeric_columns:
        return _fail(_say(ctx, "No numeric column is available to analyze.",
                          "لا يوجد عمود رقمي يمكن تحليله."))
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
        _say(ctx,
             f"Cleaned data: {before} → {after} rows "
             f"({dropped_empty} empty, {dropped_dupes} duplicates removed, "
             f"{coercion_failures} non-numeric values set to null). Row loss is "
             "reported, never hidden.",
             f"نُظّفت البيانات: عدد الصفوف من {before} إلى {after} "
             f"(حُذف {dropped_empty} فارغ و{dropped_dupes} مكرر، وعُدّت "
             f"{coercion_failures} قيمة غير رقمية فارغة). يُذكر كل صف محذوف "
             "ولا يُخفى."),
        output={"rows": cleaned, "rows_before": before, "rows_after": after,
                "dropped": before - after},
        calculations=calcs,
        claims=[_claim(ctx, "cl_rowloss", "fact",
                       f"{before - after} of {before} rows were removed during cleaning "
                       f"({dropped_empty} empty, {dropped_dupes} duplicates).",
                       f"حُذف {before - after} من أصل {_ar_n(before, 'row')} أثناء التنظيف "
                       f"({dropped_empty} فارغ و{dropped_dupes} مكرر).",
                       ["c_rows_before", "c_rows_after", "c_dropped"])],
    )


# Why the run analyses the column it does (server/metrics.resolve), as an
# Arabic report says it.
MEASURE_SOURCES_AR = {
    "certified glossary metric": "مؤشر معتمد في مسرد المؤشرات",
    "glossary metric, not certified": "مؤشر في مسرد المؤشرات غير معتمد",
    "column name": "اسم العمود",
    "first numeric column": "أول عمود رقمي",
}


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
        claims.append(_claim(
            ctx, "cl_gov_broken", "warning",
            f"The metric glossary has {len(problems)} problem(s) and "
            "those definitions were not applied, so figures in this "
            "report may not match the definitions somebody believes "
            "are in force.",
            f"في مسرد المؤشرات {_ar_n(len(problems), 'problem')} ولم تُطبَّق "
            "تلك التعريفات، لذلك قد لا تطابق أرقام هذا التقرير التعريفات "
            "التي يظن أحدهم أنها سارية.",
            ["c_gov_defined"]))

    if metric:
        calcs.append({"id": "c_gov_certified", "name": "measure_is_certified",
                      "value": 1 if metric["certified"] else 0,
                      "method": f"“{measure}” resolved to glossary metric "
                                f"“{metric['name']}”"})
        owner_en = metric["owner"] or "nobody named"
        owner_ar = metric["owner"] or "لم يُسمَّ أحد"
        owner = _say(ctx, owner_en, owner_ar)
        if metric["certified"]:
            claims.append(_claim(
                ctx, "cl_gov_certified", "fact",
                f"“{measure}” is the certified metric {metric['title']}, "
                f"owned by {owner_en}: {metric['definition']}",
                f"«{measure}» هو المؤشر المعتمد {metric['title']}، ومالكه "
                f"{owner_ar}: {metric['definition']}",
                ["c_gov_certified"]))
        else:
            claims.append(_claim(
                ctx, "cl_gov_uncertified", "limitation",
                f"“{measure}” is defined in the glossary as "
                f"{metric['title']} but has not been certified, so no "
                "one has signed off that this is the agreed definition.",
                f"«{measure}» معرَّف في المسرد بأنه {metric['title']} لكنه غير "
                "معتمد، أي لم يُقرّ أحد بأن هذا هو التعريف المتفق عليه.",
                ["c_gov_certified"]))
        lines.append(f"**{metric['title']}** — {metric['definition']}")
        lines.append("")
        lines.append(_say(ctx, f"- Owner: {owner}", f"- المالك: {owner}"))
        lines.append(_say(ctx,
                          f"- Certified: {'yes' if metric['certified'] else 'no'}",
                          f"- معتمد: {'نعم' if metric['certified'] else 'لا'}")
                     + (f" ({metric['certified_on']})" if metric["certified_on"]
                        else ""))
        if metric["unit"]:
            lines.append(_say(ctx, f"- Unit: {metric['unit']}",
                              f"- الوحدة: {metric['unit']}"))
        if metric["formula"]:
            formula = glossary.formula_text(metric["formula"])
            lines.append(_say(ctx, f"- Defined as: {formula}",
                              f"- التعريف: {formula}"))
    else:
        claims.append(_claim(
            ctx, "cl_gov_undefined", "limitation",
            f"“{measure}” is analysed as a column, not as a defined "
            "metric: no glossary entry says what it means or who owns "
            "it. These figures describe that column and cannot be "
            "reconciled against an agreed definition.",
            f"يُحلَّل «{measure}» بوصفه عموداً لا مؤشراً معرَّفاً: لا يوجد في "
            "المسرد ما يبيّن معناه أو من يملكه. هذه الأرقام تصف ذلك العمود ولا "
            "يمكن مطابقتها مع تعريف متفق عليه.",
            ["c_gov_defined"]))
        lines.append(_say(
            ctx,
            f"This run analyses **{measure}** because it was chosen by "
            f"{source}. No definition exists for it: nothing here says "
            "what it means, who owns it, or how it should be computed.",
            f"يحلل هذا التشغيل **{measure}** لأنه اختير بناءً على "
            f"{MEASURE_SOURCES_AR.get(source, source)}. لا يوجد له تعريف: لا "
            "شيء هنا يبيّن معناه أو من يملكه أو كيف ينبغي حسابه."))
        if not metrics:
            lines.append("")
            lines.append(_say(
                ctx,
                "No metric glossary is configured. `metrics.example.json` "
                "shows the format; a definition becomes governance when "
                "someone is named as its owner.",
                "لم يُضبط مسرد للمؤشرات. يوضح الملف `metrics.example.json` "
                "الصيغة المطلوبة، ويصبح التعريف حوكمةً حين يُسمّى له مالك."))

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
        formula = glossary.formula_text(metric["formula"])
        checks.append({
            "name": "measure_matches_its_definition", "passed": holds,
            "detail": _say(
                ctx,
                f"{conformance['matching']}/{conformance['checked']} rows "
                f"match {formula}"
                + ("" if holds else f"; {conformance['breach_count']} do not"),
                f"{conformance['matching']}/{conformance['checked']} من الصفوف "
                f"تطابق {formula}"
                + ("" if holds else f"؛ {conformance['breach_count']} لا تطابق"))})
        if holds:
            claims.append(_claim(
                ctx, "cl_gov_conforms", "fact",
                f"Every one of the {conformance['checked']} checked rows "
                f"has {measure} equal to its definition, so the recorded "
                "figures and the agreed formula agree.",
                f"كل صف من الصفوف المفحوصة وعددها {conformance['checked']} "
                f"يساوي فيه {measure} تعريفه، فالأرقام المسجلة والصيغة المتفق "
                "عليها متطابقة.",
                ["c_gov_conformance"]))
        else:
            worst = conformance["breaches"][0]
            claims.append(_claim(
                ctx, "cl_gov_breach", "warning",
                f"{conformance['breach_count']} of "
                f"{conformance['checked']} rows record a {measure} that "
                f"does not match its own definition. The largest gap is "
                f"{abs(worst['gap']):,.2f} on row {worst['row']}, which "
                f"records {worst['recorded']:,.2f} where the definition "
                f"gives {worst['defined']:,.2f}. Every total built on "
                "this column inherits that gap.",
                f"{conformance['breach_count']} من أصل "
                f"{_ar_n(conformance['checked'], 'row')} تسجل قيمة {measure} لا "
                f"تطابق تعريفها. أكبر فرق {abs(worst['gap']):,.2f} في الصف "
                f"{worst['row']}، إذ يسجل {worst['recorded']:,.2f} بينما يعطي "
                f"التعريف {worst['defined']:,.2f}. وكل مجموع يُبنى على هذا "
                "العمود يرث هذا الفرق.",
                ["c_gov_conformance"]))
        lines += ["", _say(ctx, "### Does the data match the definition?",
                           "### هل تطابق البيانات التعريف؟"), "",
                  _say(ctx,
                       f"{conformance['matching']} of {conformance['checked']} rows "
                       f"match. "
                       + ("Nothing to explain."
                          if holds else
                          f"{conformance['breach_count']} do not, largest first:"),
                       f"يطابق {conformance['matching']} من أصل "
                       f"{_ar_n(conformance['checked'], 'row')}. "
                       + ("لا شيء يحتاج إلى تفسير."
                          if holds else
                          f"ولا يطابق {conformance['breach_count']}، وهذه مرتبة من "
                          "الأكبر:"))]
        if not holds:
            lines += ["", _say(ctx, "| Row | Recorded | Definition says | Gap |",
                               "| الصف | المسجَّل | ما يقوله التعريف | الفرق |"),
                      "| --- | --- | --- | --- |"]
            lines += [f"| {b['row']} | {b['recorded']:,.2f} | {b['defined']:,.2f} "
                      f"| {b['gap']:+,.2f} |" for b in conformance["breaches"]]
        if conformance["skipped"]:
            lines += ["", _say(
                ctx,
                f"{conformance['skipped']} row(s) could not be checked "
                "because a value the definition needs was missing.",
                f"تعذّر فحص {conformance['skipped']} من الصفوف لأن قيمة يحتاجها "
                "التعريف كانت مفقودة.")]
    elif metric and metric["formula"]:
        lines += ["", _say(
            ctx,
            "The definition's inputs are not in this dataset, so the "
            "column could not be checked against its own formula. That is "
            "not the same as checking it and finding it sound.",
            "مدخلات التعريف غير موجودة في هذه البيانات، لذلك تعذّر فحص العمود "
            "مقابل صيغته. وهذا يختلف عن فحصه والتأكد من سلامته.")]

    # More than one column answering to a glossary name is how two
    # correct reports disagree.
    others = [c["column"] for c in candidates if c["column"] != measure]
    if others:
        calcs.append({"id": "c_gov_candidates", "name": "columns_matching_a_metric",
                      "value": len(candidates),
                      "method": "numeric columns named by a glossary metric"})
        claims.append(_claim(
            ctx, "cl_gov_ambiguous", "limitation",
            f"{len(candidates)} columns in this dataset are named by a "
            f"glossary metric. This run analysed “{measure}”; "
            f"{', '.join(others)} was not analysed, so a report on it "
            "would show different figures for the same question.",
            f"في هذه البيانات {_ar_n(len(candidates), 'column')} يسمّيها مؤشر "
            f"في المسرد. حلّل هذا التشغيل «{measure}»، ولم يُحلَّل "
            f"{'، '.join(others)}، لذا فإن تقريراً عنه سيعرض أرقاماً مختلفة "
            "للسؤال نفسه.",
            ["c_gov_candidates"]))
        lines += ["", _say(ctx,
                           f"Also present and defined: {', '.join(others)}. This run "
                           f"analysed “{measure}”.",
                           f"موجود أيضاً ومعرَّف: {'، '.join(others)}. حلّل هذا "
                           f"التشغيل «{measure}».")]

    if report_language(ctx) == "ar":
        why = MEASURE_SOURCES_AR.get(source, source)
        summary = (f"المقياس «{measure}» ({why})"
                   + (f": المؤشر المعتمد {metric['title']}، ومالكه {metric['owner']}."
                      if metric and metric["certified"] else
                      f": مؤشر المسرد {metric['title']}، غير معتمد."
                      if metric else
                      "، غير معرَّف في أي مسرد."))
        if conformance and conformance["rate"] < 1.0:
            summary += (f" {conformance['breach_count']} من الصفوف لا تطابق "
                        "التعريف.")
    else:
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
        _say(ctx,
             f"Prepared analysis dataset: measure “{measure}”"
             + (f", grouped by “{group_col}”" if group_col else "")
             + (f", trended by “{date_col}”" if date_col else "") + ".",
             f"أُعدّت بيانات التحليل: المقياس «{measure}»"
             + (f"، مجمّعاً حسب «{group_col}»" if group_col else "")
             + (f"، ومتتبَّعاً عبر «{date_col}»" if date_col else "") + "."),
        output={"measure": measure, "group_col": group_col, "date_col": date_col,
                "groups": {k: round(v, 2) for k, v in groups.items()},
                "trend": {k: round(v, 2) for k, v in trend.items()},
                "total": total},
        calculations=[{"id": "c_total", "name": f"total_{measure}", "value": total,
                       "method": f"sum({measure}) over cleaned rows"}],
        claims=[_claim(ctx, "cl_total", "calculation",
                       f"Total {measure} is {total:,.2f}.",
                       f"إجمالي {measure} هو {total:,.2f}.",
                       ["c_total"])],
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
        return _fail(_say(ctx, f"No usable values in measure “{measure}”.",
                          f"لا توجد قيم صالحة في المقياس «{measure}»."))
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
        _claim(ctx, "cl_typical", "calculation",
               f"A typical record is {mean:,.2f} (half are above {median:,.2f}).",
               f"السجل النموذجي قيمته {mean:,.2f} (ونصف السجلات أعلى من {median:,.2f}).",
               ["c_mean", "c_median"]),
    ]
    if unusual:
        claims.append(_claim(
            ctx, "cl_unusual", "finding",
            f"{unusual} of {len(values)} records are far from the "
            "typical value and are worth checking individually.",
            f"{unusual} من أصل {_ar_n(len(values), 'record')} بعيدة عن القيمة "
            "النموذجية، وتستحق الفحص كلٌّ على حدة.",
            ["c_unusual"]))

    change = None
    series = list(prep["trend"].values())
    if len(series) >= 2 and series[0]:
        change = round((series[-1] - series[0]) / series[0], 4)
        calcs.append({"id": "c_change", "name": "period_change", "value": change,
                      "method": "(last period − first period) / first period"})
        direction = "risen" if change >= 0 else "fallen"
        claims.append(_claim(
            ctx, "cl_change", "calculation",
            f"{measure} has {direction} {abs(change):.1%} from the "
            f"first period to the last.",
            f"{'ارتفع' if change >= 0 else 'انخفض'} {measure} بنسبة "
            f"{abs(change):.1%} من الفترة الأولى إلى الأخيرة.",
            ["c_change"]))
    top = max(prep["groups"], key=prep["groups"].get) if prep["groups"] else None
    share = None
    if top is not None and prep["total"]:
        share = round(prep["groups"][top] / prep["total"], 4)
        calcs.append({"id": "c_topshare", "name": "top_group_share", "value": share,
                      "method": "largest group total / overall total"})
        claims.append(_claim(
            ctx, "cl_top", "calculation",
            f"“{top}” is the largest {prep['group_col']}, making up "
            f"{share:.1%} of total {measure}.",
            f"«{top}» هو الأكبر ضمن {prep['group_col']}، ويشكّل {share:.1%} "
            f"من إجمالي {measure}.",
            ["c_topshare"]))
    if report_language(ctx) == "ar":
        headline = (
            (f"{'ارتفع' if change >= 0 else 'انخفض'} {measure} بنسبة "
             f"{abs(change):.0%} خلال الفترة، وبلغ إجماليه {prep['total']:,.0f}."
             if change is not None else f"بلغ إجمالي {measure} {prep['total']:,.0f}.")
            + (f" و«{top}» هو الأكبر ضمن {prep['group_col']}." if top is not None else ""))
        body = [
            f"إجمالي {measure} هو **{prep['total']:,.2f}** على مدى "
            f"{_ar_n(len(prep['trend']) or 1, 'period')} و"
            f"{_ar_n(ctx['cleaner']['rows_after'], 'record')}.",
            f"السجل النموذجي قيمته {mean:,.2f}، ونصف السجلات أعلى من {median:,.2f}.",
            (f"{'ارتفع' if (change or 0) >= 0 else 'انخفض'} {measure} بنسبة "
             f"{abs(change):.1%} خلال الفترة." if change is not None else
             "تغطي البيانات فترة واحدة، فلا يمكن عرض أي تغير عبر الزمن."),
            (f"«{top}» هو الأكبر ضمن {prep['group_col']} بنسبة {share:.1%} من "
             "الإجمالي." if top is not None else "لا يوجد عمود للتجميع."),
            (f"{unusual} من السجلات بعيدة عن القيمة النموذجية وتستحق نظرة."
             if unusual else "لا توجد سجلات بعيدة على نحو غير اعتيادي عن القيمة "
                             "النموذجية.")]
    else:
        headline = (
            f"{measure.capitalize()} "
            + (f"{'is up' if change >= 0 else 'is down'} {abs(change):.0%} over the period, "
               f"at {prep['total']:,.0f} in total."
               if change is not None else f"totals {prep['total']:,.0f}.")
            + (f" “{top}” is the biggest {prep['group_col']}." if top is not None else ""))
        body = [
            f"Total {measure} is **{prep['total']:,.2f}** across "
            f"{len(prep['trend']) or 1} period(s) and {ctx['cleaner']['rows_after']} records.",
            f"A typical record is {mean:,.2f}; half are above {median:,.2f}.",
            (f"{measure} has {'risen' if (change or 0) >= 0 else 'fallen'} "
             f"{abs(change):.1%} across the period." if change is not None else
             "The data covers a single period, so no change over time can be shown."),
            (f"“{top}” is the largest {prep['group_col']} at {share:.1%} of the total."
             if top is not None else "No grouping column was available."),
            (f"{unusual} record(s) sit far from the typical value and deserve a look."
             if unusual else "No records sit unusually far from the typical value.")]
    report = _section_report("Descriptive", "What happened?", ctx, body,
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
            claims.append(_claim(
                ctx, "cl_driver", "finding",
                f"Most of the movement comes from “{driver['group']}”: it accounts "
                f"for {abs(driver['share_of_change']):.0%} of the total change of "
                f"{total_change:,.2f}. This identifies where the change happened, "
                "not what caused it.",
                f"يأتي معظم التحرك من «{driver['group']}»: فهو يمثل "
                f"{abs(driver['share_of_change']):.0%} من التغير الكلي البالغ "
                f"{total_change:,.2f}. وهذا يحدد أين وقع التغير، لا ما الذي "
                "سبّبه.",
                ["c_totalchange", "c_contrib_0"]))
        decliners = [c for c in contributions if c["change"] < 0]
        if decliners:
            worst = min(decliners, key=lambda c: c["change"])
            index = contributions.index(worst)
            claims.append(_claim(
                ctx, "cl_decline", "finding",
                f"“{worst['group']}” moved against the overall direction, changing "
                f"{worst['change']:,.2f} between the first and last period.",
                f"تحرك «{worst['group']}» عكس الاتجاه العام، إذ تغير بمقدار "
                f"{worst['change']:,.2f} بين الفترة الأولى والأخيرة.",
                [f"c_contrib_{index}"] if index < 5 else ["c_totalchange"]))

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
            claims.append(_claim(
                ctx, f"cl_assoc_{index}", "finding",
                f"“{column}” moves {'up' if correlation > 0 else 'down'} "
                f"together with {measure} ({abs(correlation):.0%} of their movement "
                "is shared). Moving together is not proof that one causes the other.",
                f"يتحرك «{column}» {'صعوداً' if correlation > 0 else 'هبوطاً'} مع "
                f"{measure} ({abs(correlation):.0%} من حركتهما مشتركة). والتحرك "
                "معاً ليس دليلاً على أن أحدهما يسبب الآخر.",
                [f"c_assoc_{index}"]))

    if not calcs:
        calcs.append({"id": "c_nodiag", "name": "diagnosable_structure", "value": 0,
                      "method": "no period column, group column, or second numeric "
                                "column was available"})
    lines = []
    if contributions:
        lines.append(_say(ctx,
                          "Change between the first and last period, by "
                          f"{group_col}, largest mover first:",
                          f"التغير بين الفترة الأولى والأخيرة حسب {group_col}، "
                          "مرتباً من الأكثر تحركاً:"))
        for item in contributions[:5]:
            share = (_say(ctx,
                          f" ({item['share_of_change']:+.0%} of the total change)",
                          f" ({item['share_of_change']:+.0%} من التغير الكلي)")
                     if item["share_of_change"] is not None else "")
            lines.append(f"- **{item['group']}**: {item['change']:+,.2f}{share}")
    else:
        lines.append(_say(ctx,
                          "The dataset has no period-and-group structure to decompose, "
                          "so the movement cannot be attributed to a segment.",
                          "لا تحتوي البيانات على بنية فترات ومجموعات يمكن تفكيكها، "
                          "فلا يمكن نسبة التحرك إلى شريحة بعينها."))
    if associations:
        lines.append("")
        lines.append(_say(ctx, "Columns that move together with " + measure + ":",
                          f"أعمدة تتحرك مع {measure}:"))
        for item in associations:
            strength = abs(item["correlation"])
            if report_language(ctx) == "ar":
                how = ("بقوة" if strength >= 0.7 else
                       "بدرجة متوسطة" if strength >= 0.4 else "بضعف")
                lines.append(f"- **{item['column']}** يتحرك {how} "
                             f"{'مع' if item['correlation'] > 0 else 'عكس'} {measure}.")
            else:
                how = ("strongly" if strength >= 0.7 else
                       "moderately" if strength >= 0.4 else "weakly")
                lines.append(f"- **{item['column']}** moves {how} "
                             f"{'with' if item['correlation'] > 0 else 'against'} {measure}.")
    lines.append("")
    lines.append(_say(ctx,
                      "*Moving together is not proof of cause. Confirming a cause needs a "
                      "controlled comparison or domain knowledge this dataset does not "
                      "carry.*",
                      "*التحرك معاً ليس دليلاً على السبب. إثبات السبب يحتاج إلى مقارنة "
                      "مضبوطة أو معرفة بالمجال لا تحملها هذه البيانات.*"))
    if contributions and contributions[0]["share_of_change"] is not None:
        driver = contributions[0]
        headline = _say(ctx,
                        f"The movement is concentrated in “{driver['group']}”, which "
                        f"accounts for {abs(driver['share_of_change']):.0%} of the change.",
                        f"يتركز التحرك في «{driver['group']}» الذي يمثل "
                        f"{abs(driver['share_of_change']):.0%} من التغير.")
        if associations and abs(associations[0]["correlation"]) >= 0.5:
            headline += _say(ctx,
                             f" It moves closely with {associations[0]['column']}, "
                             "which is where to look first.",
                             f" ويتحرك بشكل وثيق مع {associations[0]['column']}، وهو "
                             "أول ما ينبغي النظر فيه.")
    elif associations:
        headline = _say(ctx,
                        f"{measure.capitalize()} moves closely with "
                        f"{associations[0]['column']}, which is where to look first.",
                        f"يتحرك {measure} بشكل وثيق مع {associations[0]['column']}، "
                        "وهو أول ما ينبغي النظر فيه.")
    else:
        headline = _say(ctx,
                        "There is no segment or period structure in this data to "
                        "explain the movement.",
                        "لا توجد في هذه البيانات بنية شرائح أو فترات تفسّر التحرك.")
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
        english = ("There is not enough data here to compare anything, so no cause "
                   "can be claimed.")
        arabic = "لا توجد هنا بيانات كافية لمقارنة أي شيء، فلا يمكن ادعاء أي سبب."
        headline = _say(ctx, english, arabic)
        return _result(
            "succeeded", headline,
            output={"headline": headline, "is_experiment": False,
                    "report_markdown": _section_report(
                        "Causal", "Can we claim a cause?", ctx,
                        [_say(ctx,
                              "Fewer than two usable observations: nothing to compare.",
                              "أقل من مشاهدتين صالحتين: لا شيء يمكن مقارنته.")],
                        calcs, headline=headline)},
            calculations=calcs,
            claims=[_claim(ctx, "cl_exp_thin", "limitation", english, arabic,
                           ["c_exp_rows"])])

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
        _say(ctx,
             f"This dataset records what happened to {measure}. It carries no column "
             "saying which rows were treated differently, so every finding in this run "
             "describes an association. **Nothing here establishes a cause**, and no "
             "amount of extra rows of the same kind would change that — it is a "
             "question of design, not of volume.",
             f"تسجل هذه البيانات ما حدث لـ {measure}. ولا تحتوي على عمود يبيّن أي "
             "الصفوف عوملت بشكل مختلف، لذا فكل نتيجة في هذا التشغيل تصف ارتباطاً. "
             "**لا شيء هنا يثبت سبباً**، ولن تغيّر ذلك أي زيادة في صفوف من النوع "
             "نفسه؛ فالمسألة مسألة تصميم لا حجم."),
        "",
        _say(ctx, "### What it would take to prove one", "### ما الذي يلزم لإثبات سبب"),
    ]
    if sizing:
        lines += ["", _say(ctx,
                           "| Change you want to prove | Observations needed in *each* "
                           "group |",
                           "| التغير المراد إثباته | المشاهدات اللازمة في *كل* مجموعة |"),
                  "| --- | --- |"]
        lines += [_say(ctx,
                       f"| {item['lift']:.0%} of the average {measure} "
                       f"| {item['rows_per_arm']:,} |",
                       f"| {item['lift']:.0%} من متوسط {measure} "
                       f"| {item['rows_per_arm']:,} |") for item in sizing]
        lines += ["", _say(ctx,
                           "Split the population at random into two groups, change one "
                           "thing for one of them, and collect at least that many "
                           "observations in each. A test of that size catches a real "
                           "change of that size about four times in five.",
                           "قسّم المجتمع عشوائياً إلى مجموعتين، وغيّر أمراً واحداً "
                           "لإحداهما، واجمع على الأقل هذا العدد من المشاهدات في كل "
                           "منهما. اختبار بهذا الحجم يلتقط تغيراً حقيقياً بهذا الحجم "
                           "في نحو أربع مرات من كل خمس.")]
    else:
        lines += ["", _say(ctx,
                           f"The average {measure} is zero or the values never vary, so a "
                           "relative change cannot be sized from this data.",
                           f"متوسط {measure} صفر أو أن القيم لا تتغير، فلا يمكن تقدير "
                           "حجم تغير نسبي من هذه البيانات.")]
    if detectable is not None and scale:
        lines += ["", _say(ctx,
                           f"With the {count:,} observations already here, split evenly, "
                           f"the smallest change that would stand out from ordinary "
                           f"variation is about **{detectable / scale:.0%}** of the "
                           "average. Anything smaller would be invisible in a sample "
                           "this size — which is worth knowing before commissioning "
                           "the test.",
                           f"بالمشاهدات الموجودة هنا وعددها {count:,} مقسومة بالتساوي، "
                           "فإن أصغر تغير يمكن تمييزه عن التباين المعتاد يبلغ نحو "
                           f"**{detectable / scale:.0%}** من المتوسط. وأي تغير أصغر لن "
                           "يظهر في عينة بهذا الحجم، وهذا ما يستحق معرفته قبل تكليف "
                           "أحد بالاختبار.")]
    claims = [_claim(
        ctx, "cl_exp_observational", "limitation",
        f"This data records what happened; it contains no controlled "
        f"comparison, so no finding about {measure} may be stated as a cause.",
        f"تسجل هذه البيانات ما حدث ولا تتضمن مقارنة مضبوطة، فلا يجوز تقديم أي "
        f"نتيجة عن {measure} على أنها سبب.",
        ["c_exp_rows"])]
    if sizing:
        first = sizing[1] if len(sizing) > 1 else sizing[0]
        index = DETECTABLE_LIFTS.index(first["lift"])
        claims.append(_claim(
            ctx, "cl_exp_design", "recommendation",
            f"To prove a {first['lift']:.0%} change in {measure}, run a "
            f"randomised comparison with about {first['rows_per_arm']:,} "
            "observations in each group; a test that size catches a real "
            "change of that size about four times in five.",
            f"لإثبات تغير بنسبة {first['lift']:.0%} في {measure}، أجرِ مقارنة "
            f"عشوائية بنحو {_ar_n(first['rows_per_arm'], 'observation', True)} "
            "في كل مجموعة؛ "
            "فاختبار بهذا الحجم يلتقط تغيراً حقيقياً بهذا الحجم في نحو أربع "
            "مرات من كل خمس.",
            [f"c_exp_n_{index}", "c_exp_spread"]))
        headline = _say(ctx,
                        f"No cause can be claimed from this data — to prove a "
                        f"{first['lift']:.0%} change you would need about "
                        f"{first['rows_per_arm']:,} observations in each of two groups.",
                        f"لا يمكن ادعاء سبب من هذه البيانات؛ فلإثبات تغير بنسبة "
                        f"{first['lift']:.0%} يلزم نحو "
                        f"{_ar_n(first['rows_per_arm'], 'observation', True)} في كل "
                        "واحدة من مجموعتين.")
    else:
        headline = _say(ctx,
                        "No cause can be claimed from this data: it records what "
                        "happened, not a controlled comparison.",
                        "لا يمكن ادعاء سبب من هذه البيانات: فهي تسجل ما حدث، لا "
                        "مقارنة مضبوطة.")
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
        english = (f"“{column}” looks like an experiment, but only "
                   f"{len(usable)} group has enough rows to compare, so no cause "
                   "can be claimed.")
        arabic = (f"يبدو «{column}» تجربةً، لكن عدد المجموعات التي فيها صفوف "
                  f"كافية للمقارنة {len(usable)} فقط، فلا يمكن ادعاء أي سبب.")
        headline = _say(ctx, english, arabic)
        lines = [_say(ctx,
                      f"Column “{column}” records assignment to "
                      f"{len(arms)} group(s), but a comparison needs at least two "
                      "groups with two or more observations each.",
                      f"يسجل العمود «{column}» التوزيع على {_ar_n(len(arms), 'group')}، "
                      "لكن المقارنة تحتاج إلى مجموعتين على الأقل في كل منهما "
                      "مشاهدتان أو أكثر.")]
        return _result(
            "succeeded", headline,
            output={"headline": headline, "is_experiment": False,
                    "assignment_column": column,
                    "report_markdown": _section_report(
                        "Causal", "Can we claim a cause?", ctx, lines, calcs,
                        headline=headline)},
            calculations=calcs,
            claims=[_claim(ctx, "cl_exp_thin_arms", "limitation", english, arabic,
                           ["c_exp_arms"])])

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

    arabic = report_language(ctx) == "ar"
    yes, no = ("نعم", "لا") if arabic else ("yes", "no")
    claims, lines = [], [
        _say(ctx,
             f"Column “{column}” records which group each row belongs to, so this run "
             f"can compare them. “{baseline}” is used as the baseline; every figure "
             "below is the difference from it.",
             f"يسجل العمود «{column}» المجموعة التي ينتمي إليها كل صف، لذا يستطيع "
             f"هذا التشغيل المقارنة بينها. تُستخدم «{baseline}» مجموعةً مرجعية، "
             "وكل رقم أدناه هو الفرق عنها."),
        "",
        _say(ctx,
             "| Group | Rows | Average | Difference | Range (safe to check early) "
             "| Beyond chance? |",
             "| المجموعة | الصفوف | المتوسط | الفرق | النطاق (آمن للفحص المبكر) "
             "| أكبر من الصدفة؟ |"),
        "| --- | --- | --- | --- | --- | --- |",
        _say(ctx,
             f"| {baseline} (baseline) | {base_n} | {base_mean:,.2f} | — | — | — |",
             f"| {baseline} (المرجع) | {base_n} | {base_mean:,.2f} | — | — | — |"),
    ]
    to = "إلى" if arabic else "to"
    for item in results:
        relative = f" ({item['relative']:+.1%})" if item["relative"] is not None else ""
        lines.append(
            f"| {item['group']} | {item['rows']} | {item['average']:,.2f} "
            f"| {item['difference']:+,.2f}{relative} "
            f"| {item['low']:,.2f} {to} {item['high']:,.2f} "
            f"| {yes if item['beyond_chance'] else no} |")
    if arabic:
        lines += ["", "النطاق هو ما تستطيع البيانات دعمه فعلاً. الفرق المنفرد يبدو "
                  "دقيقاً وهو ليس كذلك: لو كُرر الاختبار نفسه لوقع الفرق في مكان ما "
                  "داخل هذا النطاق. وحيث يعبر النطاق الصفر، يكون الفرق ضمن ما تنتجه "
                  "الصدفة وحدها، ولا ينبغي التصرف على أساسه كنتيجة.",
                  "",
                  "### لماذا هذا النطاق لا نطاق أضيق", "",
                  "ينظر معظم الناس إلى الاختبار أكثر من مرة، يوم الثلاثاء ثم يوم "
                  "الخميس، ويتوقفون حين يبدو الرقم جيداً. والتوقف حين يبدو الرقم "
                  "جيداً هو ما يحوّل خطر نتيجة خاطئة بنسبة 1 من 20 إلى ما هو أسوأ "
                  "بكثير: في المحاكاة، يؤدي فحص نطاق عادي نحو مئتي مرة إلى العثور "
                  "على فرق «حقيقي» في قرابة ثلث الاختبارات التي لا يحدث فيها شيء "
                  "على الإطلاق.",
                  "",
                  "النطاق أعلاه مبني ليصمد أمام ذلك. فهو صالح عند كل حجم عينة في "
                  "آن واحد، ولذلك لا يفسده النظر المبكر ولا النظر المتكرر ولا "
                  "التوقف متى شئت. وهو أعرض من النطاق العادي بنحو النصف، وهذا "
                  "العرض هو ثمن حرية النظر.",
                  "",
                  "إذا كنت قد حددت حجم العينة فعلاً قبل جمع أي بيانات وتنظر إلى "
                  "النتيجة مرة واحدة فقط، فالنطاق الأضيق هو الذي ينطبق:"]
        lines += ["", "| المجموعة | النطاق (فقط إذا حُدد الحجم مسبقاً) "
                  "| أكبر من الصدفة؟ |", "| --- | --- | --- |"]
    else:
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
    lines += [f"| {item['group']} | {item['fixed_low']:,.2f} {to} "
              f"{item['fixed_high']:,.2f} "
              f"| {yes if item['beyond_chance_if_horizon_was_fixed'] else no} |"
              for item in results]
    if len(comparisons) > 1:
        lines += ["", _say(ctx,
                           f"{len(comparisons)} groups were compared against the "
                           "baseline. Comparing more groups gives chance more chances, "
                           "so each range was widened to keep the overall risk of a "
                           "false result at the same level as a single comparison.",
                           f"قورنت {_ar_n(len(comparisons), 'group')} بالمجموعة "
                           "المرجعية. ومقارنة مجموعات أكثر تمنح الصدفة فرصاً أكثر، "
                           "لذا وُسّع كل نطاق ليبقى الخطر الكلي لنتيجة خاطئة عند "
                           "مستوى مقارنة واحدة.")]

    for index, item in enumerate(results):
        relative_en = (f" ({abs(item['relative']):.1%})"
                       if item["relative"] is not None else "")
        if item["beyond_chance"]:
            direction = "ahead of" if item["difference"] > 0 else "behind"
            claims.append(_claim(
                ctx, f"cl_exp_effect_{index}", "finding",
                f"“{item['group']}” is {direction} “{baseline}” on {measure} "
                f"by {abs(item['difference']):,.2f}" + relative_en
                + f", and the range ({item['low']:,.2f} to "
                  f"{item['high']:,.2f}) does not include no-change, so this "
                  "is unlikely to be chance alone. That range holds however "
                  "often the test was checked along the way.",
                f"«{item['group']}» "
                + ("يتقدم على" if item["difference"] > 0 else "يتأخر عن")
                + f" «{baseline}» في {measure} بمقدار "
                  f"{abs(item['difference']):,.2f}" + relative_en
                + f"، والنطاق ({item['low']:,.2f} إلى {item['high']:,.2f}) لا "
                  "يشمل انعدام التغير، فمن غير المرجح أن يكون ذلك صدفة وحدها. "
                  "ويبقى هذا النطاق صالحاً مهما تكرر فحص الاختبار أثناء سيره.",
                [f"c_exp_diff_{index}", f"c_exp_range_{index}"]))
        else:
            narrower = item["beyond_chance_if_horizon_was_fixed"]
            claims.append(_claim(
                ctx, f"cl_exp_null_{index}", "finding",
                f"“{item['group']}” and “{baseline}” cannot be separated on "
                f"{measure}: the range ({item['low']:,.2f} to "
                f"{item['high']:,.2f}) includes no change, so the difference "
                "of " + f"{item['difference']:+,.2f} is within ordinary "
                "variation." + (
                    " A narrower reading would call it real, but only for "
                    "someone who fixed the sample size before collecting "
                    "anything and is looking exactly once."
                    if narrower else ""),
                f"لا يمكن التمييز بين «{item['group']}» و«{baseline}» في "
                f"{measure}: فالنطاق ({item['low']:,.2f} إلى {item['high']:,.2f}) "
                f"يشمل انعدام التغير، والفرق البالغ {item['difference']:+,.2f} ضمن "
                "التباين المعتاد." + (
                    " وقد تعدّه قراءة أضيق حقيقياً، لكن فقط لمن حدد حجم العينة "
                    "قبل جمع أي بيانات وينظر إلى النتيجة مرة واحدة."
                    if narrower else ""),
                [f"c_exp_diff_{index}", f"c_exp_range_{index}"]))
    if lopsided:
        lines += ["", _say(ctx,
                           f"⚠️ The groups are not evenly sized: “{worst}” holds "
                           f"{observed_share:.0%} of the rows where "
                           f"{expected_share:.0%} was expected. Random assignment "
                           "rarely lands that far apart, so check how rows were "
                           "assigned and logged before trusting anything above.",
                           f"⚠️ المجموعات غير متساوية الحجم: تضم «{worst}» "
                           f"{observed_share:.0%} من الصفوف بينما كان المتوقع "
                           f"{expected_share:.0%}. ونادراً ما يبتعد التوزيع العشوائي "
                           "إلى هذا الحد، فتحقق من طريقة توزيع الصفوف وتسجيلها قبل "
                           "الوثوق بأي شيء أعلاه.")]
        claims.append(_claim(
            ctx, "cl_exp_split", "warning",
            f"The groups are unevenly sized: “{worst}” holds "
            f"{observed_share:.0%} of rows against an expected "
            f"{expected_share:.0%}. Random assignment rarely produces a gap "
            "that wide, so the comparison may be measuring the assignment "
            "rather than the change.",
            f"المجموعات غير متساوية الحجم: تضم «{worst}» {observed_share:.0%} من "
            f"الصفوف مقابل {expected_share:.0%} متوقعة. ونادراً ما ينتج التوزيع "
            "العشوائي فجوة بهذا الاتساع، فقد تقيس المقارنة طريقة التوزيع لا "
            "التغيير.",
            ["c_exp_split"]))

    claims.append(_claim(
        ctx, "cl_exp_peeking", "assumption",
        "The ranges above stay honest however often this test was "
        "checked while it ran, which is why they are wider than the "
        "usual ones. The narrower figures beside them apply only if the "
        "number of observations was decided before any data was "
        "collected and the result is being read once.",
        "تبقى النطاقات أعلاه صادقة مهما تكرر فحص هذا الاختبار أثناء سيره، "
        "ولهذا هي أعرض من المعتاد. أما الأرقام الأضيق بجانبها فتنطبق فقط إذا "
        "حُدد عدد المشاهدات قبل جمع أي بيانات وقُرئت النتيجة مرة واحدة.",
        ["c_exp_range_0"]))

    # The column proves an assignment was recorded. It does not prove the
    # assignment was random — and only randomisation turns this difference
    # into an effect. A run that quietly skipped this sentence would let a
    # non-random rollout be read as proof of cause, which is the exact
    # failure this stage exists to prevent.
    claims.append(_claim(
        ctx, "cl_exp_random", "assumption",
        f"This difference counts as the effect of the change only if rows "
        f"were assigned to their “{column}” group at random. The data "
        "records the assignment, not how it was made; without "
        "randomisation this remains an association, like any other in "
        "this report.",
        f"لا يُعدّ هذا الفرق أثراً للتغيير إلا إذا وُزّعت الصفوف على مجموعات "
        f"«{column}» عشوائياً. فالبيانات تسجل التوزيع لا طريقة إجرائه، ومن دون "
        "توزيع عشوائي يبقى هذا ارتباطاً كغيره في هذا التقرير.",
        ["c_exp_arms"]))
    lines += ["", _say(ctx,
                       f"**This is a causal result only if assignment to “{column}” "
                       "was random.** The dataset records which group each row was "
                       "in, not how it got there. Where groups were formed by "
                       "something that already happened — who opted in, which "
                       "region rolled out first — the difference is an association "
                       "wearing an experiment's clothes.",
                       f"**هذه نتيجة سببية فقط إذا كان التوزيع على «{column}» "
                       "عشوائياً.** تسجل البيانات المجموعة التي كان فيها كل صف، لا "
                       "كيف وصل إليها. وحين تتكوّن المجموعات بفعل أمر حدث مسبقاً، "
                       "كمن اختار الانضمام أو أي منطقة بدأت أولاً، يكون الفرق "
                       "ارتباطاً يرتدي ثوب التجربة.")]

    # The comparison treats each row as one independent observation. When
    # rows are period-by-segment aggregates that is false, and the ranges
    # above are narrower than the truth. Saying so is cheaper than being
    # quietly wrong.
    claims.append(_claim(
        ctx, "cl_exp_units", "limitation",
        f"Each row is treated as one independent observation of {measure}. "
        "If rows are aggregates or the same subject appears more than once, "
        "the ranges above are narrower than reality and the comparison "
        "should be rerun on the underlying records.",
        f"يُعامل كل صف على أنه مشاهدة مستقلة واحدة لـ {measure}. فإذا كانت "
        "الصفوف مجاميع أو تكرر ظهور الحالة نفسها أكثر من مرة، فالنطاقات أعلاه "
        "أضيق من الواقع، وينبغي إعادة المقارنة على السجلات الأصلية.",
        ["c_exp_arms"]))
    lines += ["", _say(ctx,
                       "*Each row is treated as one independent observation. If the "
                       "rows are aggregates — one per month, per region — the ranges "
                       "above are narrower than the truth.*",
                       "*يُعامل كل صف على أنه مشاهدة مستقلة. فإذا كانت الصفوف مجاميع، "
                       "صفاً لكل شهر أو لكل منطقة، فالنطاقات أعلاه أضيق من "
                       "الحقيقة.*")]

    strongest = max(results, key=lambda r: abs(r["difference"]))
    if strongest["beyond_chance"]:
        relative = (f" ({abs(strongest['relative']):.1%})"
                    if strongest["relative"] is not None else "")
        gap = f"{abs(strongest['difference']):,.2f}{relative}"
        if strongest["difference"] > 0:
            headline = _say(ctx,
                            f"“{strongest['group']}” beats “{baseline}” on {measure} "
                            f"by {gap}, and the result is bigger than chance would "
                            "explain.",
                            f"«{strongest['group']}» يتفوق على «{baseline}» في "
                            f"{measure} بمقدار {gap}، والنتيجة أكبر مما تفسره "
                            "الصدفة.")
        else:
            headline = _say(ctx,
                            f"“{strongest['group']}” is behind “{baseline}” on "
                            f"{measure} by {gap}, by more than chance would explain.",
                            f"«{strongest['group']}» يتأخر عن «{baseline}» في "
                            f"{measure} بمقدار {gap}، وهو أكثر مما تفسره الصدفة.")
    else:
        headline = _say(ctx,
                        f"No group can be separated from “{baseline}” on {measure}: "
                        "every difference is inside what chance alone produces.",
                        f"لا يمكن تمييز أي مجموعة عن «{baseline}» في {measure}: فكل "
                        "فرق يقع ضمن ما تنتجه الصدفة وحدها.")
    if lopsided:
        headline += _say(ctx,
                         " The groups are unevenly sized, so treat this with caution.",
                         " والمجموعات غير متساوية الحجم، فتعامل مع هذا بحذر.")
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
    # Each breach in English (the audited record) and in Arabic (for an
    # Arabic reader); the English claim must never embed the Arabic.
    fields, breaches, breaches_ar = [], [], []
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
            breaches_ar.append(
                f"{column}: {len(present) - len(numbers)} من أصل "
                f"{_ar_n(len(present), 'value')} لا تُقرأ رقماً"
                + ("" if field["usable_as_measure"] else
                   f"، فلا يبقى صالحاً إلا {parse_rate:.0%}، وهو أقل من 90% "
                   "المطلوبة لتحليله مقياساً"))

    calcs = [{"id": "c_contract_fields", "name": "columns_under_contract",
              "value": len(fields), "method": "one contract row per column"}]
    kinds_ar = {"number": "رقمي", "text": "نصي"}
    claims = [_claim(
        ctx, "cl_contract", "fact",
        f"The data has {len(fields)} columns under contract: "
        + ", ".join(f"{f['name']} ({f['type']})" for f in fields[:6])
        + ("…" if len(fields) > 6 else "") + ".",
        f"للبيانات عقد يشمل {_ar_n(len(fields), 'column')}: "
        + "، ".join(f"{f['name']} ({kinds_ar[f['type']]})" for f in fields[:6])
        + ("…" if len(fields) > 6 else "") + ".",
        ["c_contract_fields"])]
    if breaches:
        claims.append(_claim(
            ctx, "cl_contract_breach", "finding",
            "Some values do not match the column they sit in: "
            + "; ".join(breaches[:3])
            + ". Those cells are treated as missing, not guessed.",
            "بعض القيم لا تطابق العمود الذي تقع فيه: "
            + "؛ ".join(breaches_ar[:3])
            + ". وتُعامل تلك الخلايا على أنها مفقودة، ولا تُخمَّن.",
            ["c_contract_fields"]))
    return _result(
        "succeeded",
        _say(ctx,
             f"Contract inferred for {len(fields)} columns"
             + (f"; {len(breaches)} column(s) contain values that break it." if breaches
                else "; every value matches its column."),
             f"استُنتج عقد البيانات لـ {_ar_n(len(fields), 'column')}"
             + (f"؛ وفي {len(breaches)} منها قيم تخالفه." if breaches
                else "؛ وكل قيمة تطابق عمودها.")),
        output={"fields": fields, "breaches": breaches},
        calculations=calcs, claims=claims,
        checks=[{"name": "contract_has_a_measure",
                 "passed": any(f["type"] == "number" for f in fields),
                 "detail": _say(ctx,
                                "At least one numeric column is needed to measure "
                                "anything.",
                                "يلزم عمود رقمي واحد على الأقل لقياس أي شيء.")}],
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
    dimensions_ar = {"completeness": "الاكتمال", "uniqueness": "التفرد",
                     "validity": "الصلاحية", "consistency": "الاتساق"}
    verdict = _say(ctx,
                   ("every dimension is perfect"
                    if flawless else
                    f"weakest dimension is {weakest} at {dimensions[weakest]:.0%}"),
                   ("كل الأبعاد كاملة"
                    if flawless else
                    f"أضعف بعد هو {dimensions_ar[weakest]} بنسبة "
                    f"{dimensions[weakest]:.0%}"))
    return _result(
        "succeeded",
        _say(ctx, f"Data quality {score}/100 (grade {grade}); {verdict}.",
             f"جودة البيانات {score}/100 (التقدير {grade})؛ {verdict}."),
        output={"dimensions": {k: round(v, 4) for k, v in dimensions.items()},
                "score": score, "grade": grade, "weakest": weakest},
        calculations=calcs,
        claims=[_claim(
            ctx, "cl_dq", "calculation",
            f"Data quality scores {score} out of 100 (grade {grade}). "
            + ("Completeness, uniqueness, validity and consistency are "
               "all perfect." if flawless else
               f"The weakest part is {weakest}, at "
               f"{dimensions[weakest]:.0%}."),
            f"تحصل جودة البيانات على {score} من 100 (التقدير {grade}). "
            + ("الاكتمال والتفرد والصلاحية والاتساق كلها كاملة." if flawless else
               f"وأضعف جزء هو {dimensions_ar[weakest]} بنسبة "
               f"{dimensions[weakest]:.0%}."),
            ["c_dq_score", f"c_dq_{weakest}"])],
        checks=[{"name": "quality_above_floor", "passed": score >= 50,
                 "detail": _say(ctx,
                                f"Score {score}/100. Below 50 the findings would rest "
                                "on data too broken to carry them.",
                                f"الدرجة {score}/100. وتحت 50 تستند النتائج إلى "
                                "بيانات أضعف من أن تحملها.")}],
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
        # The Arabic list mirrors the English one term for term, including
        # its precedence: when a column is flagged by name, its value counts
        # are not listed.
        summary = "; ".join(
            f"{f['column']} (" + ", ".join(
                [f"named like {'/'.join(f['by_name'])}"] if f["by_name"] else []
                + [f"{h['rows']} {h['kind']}(s)" for h in f["by_value"]]) + ")"
            for f in findings[:3])
        kinds_ar = {"email address": "عنوان بريد إلكتروني",
                    "phone number": "رقم هاتف", "long identifier": "معرّف طويل"}
        summary_ar = "؛ ".join(
            f"{f['column']} (" + "، ".join(
                [f"اسمه يشبه {'/'.join(f['by_name'])}"] if f["by_name"] else []
                + [f"{h['rows']} × {kinds_ar.get(h['kind'], h['kind'])}"
                   for h in f["by_value"]]) + ")"
            for f in findings[:3])
        claims.append(_claim(
            ctx, "cl_pii", "warning",
            f"This dataset appears to contain personal data in "
            f"{len(findings)} column(s): {summary}. Publishing writes the "
            "report to the vault — check that it is allowed to leave here.",
            f"يبدو أن هذه البيانات تحتوي على بيانات شخصية في "
            f"{len(findings)} من الأعمدة: {summary_ar}. النشر يكتب التقرير في "
            "المخزن، فتحقق من أنه مسموح بخروجه من هنا.",
            ["c_pii_columns"]))
    else:
        claims.append(_claim(
            ctx, "cl_pii_clear", "fact",
            "No personal data was detected in the dataset by name or by "
            "value pattern. Detection is pattern-based, so it is a strong "
            "hint rather than a guarantee.",
            "لم تُكتشف بيانات شخصية في البيانات، لا من أسماء الأعمدة ولا من "
            "أنماط القيم. والكشف قائم على الأنماط، فهو مؤشر قوي لا ضمان.",
            ["c_pii_columns"]))
    return _result(
        "succeeded",
        _say(ctx,
             (f"Personal data detected in {len(findings)} column(s) — review before "
              "publishing." if findings else
              "No personal data detected by name or value pattern."),
             (f"اكتُشفت بيانات شخصية في {len(findings)} من الأعمدة؛ راجعها قبل "
              "النشر." if findings else
              "لم تُكتشف بيانات شخصية من الأسماء أو أنماط القيم.")),
        output={"findings": findings, "personal_data": bool(findings)},
        calculations=calcs, claims=claims,
        checks=[{"name": "personal_data_declared", "passed": True,
                 "detail": _say(ctx,
                                (f"{len(findings)} column(s) flagged and reported to "
                                 "the approver." if findings else
                                 "Nothing matched; the scan itself is recorded."),
                                (f"حُدد {len(findings)} من الأعمدة وأُبلغ بها صاحب "
                                 "الموافقة." if findings else
                                 "لم يطابق شيء، والفحص نفسه مسجَّل."))}],
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
            _say(ctx, "No grouping column, so concentration cannot be measured.",
                 "لا يوجد عمود للتجميع، فلا يمكن قياس التركّز."),
            output={"shares": [], "hhi": None, "pareto_count": None},
            calculations=[{"id": "c_seg_none", "name": "segments", "value": 0,
                           "method": "no non-numeric column to group by"}],
            claims=[_claim(ctx, "cl_seg_none", "limitation",
                           "The data has no grouping column, so no segment "
                           "concentration can be reported.",
                           "لا تحتوي البيانات على عمود للتجميع، فلا يمكن الإبلاغ "
                           "عن تركّز الشرائح.",
                           ["c_seg_none"])])

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
    spread_ar = ("شديد التركّز" if hhi >= 0.5 else
                 "متركّز" if hhi >= 0.25 else "موزّع")
    group_col, measure = prep["group_col"], prep["measure"]
    # With two or three segments "N of them make 80%" is arithmetic, not
    # insight; the share of the largest is the fact worth stating.
    headline = _say(ctx,
                    (f"{len(shares)} segments; {pareto} of them make up 80% of the "
                     f"total ({spread})."
                     if len(shares) > 3 else
                     f"{len(shares)} segments, largest at {shares[0]['share']:.0%} "
                     f"of the total ({spread})."),
                    (f"{_ar_n(len(shares), 'segment')}، منها {pareto} تشكّل 80% من "
                     f"الإجمالي ({spread_ar})."
                     if len(shares) > 3 else
                     f"{_ar_n(len(shares), 'segment')}، أكبرها بنسبة "
                     f"{shares[0]['share']:.0%} من الإجمالي ({spread_ar})."))
    return _result(
        "succeeded", headline,
        output={"shares": shares, "hhi": hhi, "pareto_count": pareto},
        calculations=calcs,
        claims=[_claim(
            ctx, "cl_seg", "calculation",
            (f"{pareto} of {len(shares)} {group_col}s account for "
             f"80% of {measure} — the business is {spread}."
             if len(shares) > 3 else
             f"The largest of {len(shares)} {group_col}s holds "
             f"{shares[0]['share']:.0%} of {measure} — the "
             f"business is {spread}."),
            (f"{pareto} من أصل {len(shares)} من شرائح {group_col} تمثل 80% من "
             f"{measure}، فالنشاط {spread_ar}."
             if len(shares) > 3 else
             f"الأكبر بين شرائح {group_col} وعددها {len(shares)} يستحوذ على "
             f"{shares[0]['share']:.0%} من {measure}، فالنشاط {spread_ar}."),
            ["c_seg_pareto", "c_seg_hhi"])],
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
            _say(ctx,
                 f"Only {len(series)} period(s): too few to tell an unusual period "
                 "from ordinary variation.",
                 f"عدد الفترات {len(series)} فقط، وهو أقل من أن يميّز فترة غير "
                 "اعتيادية عن التباين المعتاد."),
            output={"anomalies": [], "residual_spread": None},
            calculations=[{"id": "c_anom_periods", "name": "periods_available",
                           "value": len(series), "method": "distinct periods"}],
            claims=[_claim(ctx, "cl_anom_none", "limitation",
                           f"With {len(series)} period(s) there is no basis for "
                           "calling any of them unusual.",
                           f"مع {len(series)} من الفترات لا يوجد أساس لوصف أي منها "
                           "بأنها غير اعتيادية.",
                           ["c_anom_periods"])])

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
        claims.append(_claim(
            ctx, "cl_anom", "finding",
            f"{len(anomalies)} period(s) sit well away from the pattern. "
            f"The largest is {worst['period']}, which came in "
            f"{abs(worst['gap']):,.0f} {'above' if worst['gap'] > 0 else 'below'} "
            "what the trend would give — worth asking what happened then.",
            f"{_ar_n(len(anomalies), 'period')} بعيدة بوضوح عن النمط. أكبرها "
            f"{worst['period']}، إذ جاءت "
            f"{'أعلى' if worst['gap'] > 0 else 'أدنى'} بمقدار "
            f"{abs(worst['gap']):,.0f} مما يعطيه الاتجاه، ويستحق السؤال عما حدث "
            "حينها.",
            ["c_anom_spread", "c_anom_0"]))
    else:
        claims.append(_claim(
            ctx, "cl_anom_clear", "fact",
            "Every period sits close to the overall pattern; nothing stands "
            "out as unusual.",
            "كل الفترات قريبة من النمط العام، ولا شيء يبرز على أنه غير اعتيادي.",
            ["c_anom_spread"]))
    return _result(
        "succeeded",
        _say(ctx,
             (f"{len(anomalies)} unusual period(s) against the trend."
              if anomalies else "No period departs from the trend."),
             (f"{_ar_n(len(anomalies), 'unusual_period')} مقارنة بالاتجاه."
              if anomalies else "لا توجد فترة تخرج عن الاتجاه.")),
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
            "succeeded",
            _say(ctx, "Fewer than two options, so there is nothing to test.",
                 "الخيارات أقل من اثنين، فلا يوجد ما يُختبر."),
            output={"stable": None, "scenarios": [], "break_even": None},
            calculations=[{"id": "c_sens_none", "name": "options_tested", "value":
                           len(options), "method": "options from the prescriptive stage"}],
            claims=[_claim(ctx, "cl_sens_none", "limitation",
                           "With fewer than two options there is no ranking to test "
                           "for sensitivity.",
                           "مع أقل من خيارين لا يوجد ترتيب يمكن اختبار حساسيته.",
                           ["c_sens_none"])])

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
    claims = [_claim(
        ctx, "cl_sens", "finding",
        (f"The recommendation does not depend on the size of the improvement "
         f"assumed: “{winner['title']}” wins at 5%, 10% and 20% alike."
         if stable else
         "The recommendation changes with the size of the improvement assumed, "
         "so it should be treated as a close call rather than a conclusion.")
        + (f" It would take a {break_even:.1f}× better result in "
           f"“{runner_up['target']}” than in “{winner['target']}” to change the answer."
           if break_even else ""),
        (f"لا تعتمد التوصية على حجم التحسن المفترض: "
         f"«{winner.get('title_ar', winner['title'])}» يتصدر عند "
         "5% و10% و20% على حد سواء."
         if stable else
         "تتغير التوصية بتغير حجم التحسن المفترض، فينبغي التعامل معها بوصفها قراراً "
         "متقارباً لا نتيجة محسومة.")
        + (f" ولتغيير الجواب يلزم أن تكون النتيجة في "
           f"«{runner_up.get('target_ar', runner_up['target'])}» أفضل بمقدار "
           f"{break_even:.1f}× مما هي في «{winner.get('target_ar', winner['target'])}»."
           if break_even else ""),
        ["c_sens_stable"] + (["c_sens_breakeven"] if break_even else []))]
    return _result(
        "succeeded",
        _say(ctx,
             ("The recommendation holds across every improvement assumption tested."
              if stable else
              "The recommendation depends on the improvement assumed — treat it as a "
              "close call."),
             ("تصمد التوصية أمام كل افتراضات التحسن التي اختُبرت."
              if stable else
              "تعتمد التوصية على التحسن المفترض، فتعامل معها بوصفها قراراً متقارباً.")),
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
    for stage in evidence_stages(ctx):
        result = ctx.get(stage + "_result", {})
        for calc in result.get("calculations", []):
            produced[calc["id"]] = stage
        for claim in result.get("claims", []):
            cited.update(claim.get("evidence", []))

    dangling = sorted(cited - set(produced))
    unused = sorted(set(produced) - cited)
    claim_count = sum(len(ctx.get(s + "_result", {}).get("claims", []))
                      for s in evidence_stages(ctx))
    calcs = [
        {"id": "c_lin_calcs", "name": "calculations_produced", "value": len(produced),
         "method": "calculations emitted across every evidence-producing stage"},
        {"id": "c_lin_claims", "name": "claims_made", "value": claim_count,
         "method": "claims emitted across every evidence-producing stage"},
        {"id": "c_lin_dangling", "name": "claims_citing_missing_evidence",
         "value": len(dangling),
         "method": "evidence ids cited by a claim but produced by no stage"},
    ]
    snapshot = ctx["collector"]["snapshot"]
    return _result(
        "succeeded",
        _say(ctx,
             f"Provenance chain built: {len(produced)} calculations support "
             f"{claim_count} claims, all rooted in snapshot sha256:{snapshot}."
             + (f" {len(unused)} calculation(s) went uncited." if unused else ""),
             f"بُنيت سلسلة الإثبات: {_ar_n(len(produced), 'calculation')} تدعم "
             f"{_ar_n(claim_count, 'claim')}، وكلها تعود إلى لقطة البيانات "
             f"sha256:{snapshot}."
             + (f" ولم يُستشهد بـ {len(unused)} من العمليات الحسابية." if unused
                else "")),
        output={"produced_by_stage": produced, "dangling": dangling,
                "unused": unused, "snapshot": snapshot},
        calculations=calcs,
        claims=[_claim(ctx, "cl_lineage", "fact",
                       f"Every figure in this report traces back to snapshot "
                       f"sha256:{snapshot} through "
                       f"{len(produced)} recorded calculations.",
                       f"كل رقم في هذا التقرير يعود إلى لقطة البيانات "
                       f"sha256:{snapshot} عبر "
                       f"{_ar_n(len(produced), 'calculation')} مسجَّلة.",
                       ["c_lin_calcs", "c_lin_dangling"])],
        checks=[{"name": "no_claim_cites_missing_evidence", "passed": not dangling,
                 "detail": _say(ctx,
                                ("Every cited calculation exists."
                                 if not dangling else
                                 "Missing evidence: " + ", ".join(dangling)),
                                ("كل عملية حسابية مستشهد بها موجودة."
                                 if not dangling else
                                 "أدلة مفقودة: " + ", ".join(dangling)))}],
    )


def visuals(ctx):
    prep = ctx["preparer"]
    measure, group_col, date_col = prep["measure"], prep["group_col"], prep["date_col"]
    charts = []
    forecast = ctx.get("predictive", {}).get("forecast") or []
    if prep["groups"]:
        items = sorted(prep["groups"].items(), key=lambda kv: -kv[1])[:8]
        charts.append({"id": "chart_groups", "type": "bar",
                       "title": _say(ctx, f"Total {measure} by {group_col}",
                                     f"إجمالي {measure} حسب {group_col}"),
                       "labels": [k for k, _ in items],
                       "values": [v for _, v in items],
                       "source": "preparer.groups",
                       "alt": _say(ctx,
                                   f"Bar chart of total {measure} for each "
                                   f"{group_col}, largest first.",
                                   f"مخطط أعمدة لإجمالي {measure} لكل {group_col}، "
                                   "من الأكبر إلى الأصغر.")})
    if len(prep["trend"]) >= 2:
        periods = len(prep["trend"])
        charts.append({"id": "chart_trend", "type": "line",
                       "title": _say(ctx, f"{measure} by {date_col}",
                                     f"{measure} حسب {date_col}"),
                       "labels": list(prep["trend"].keys()),
                       "values": list(prep["trend"].values()),
                       "source": "preparer.trend",
                       "alt": _say(ctx,
                                   f"Line chart of {measure} across {periods} periods.",
                                   f"مخطط خطي لـ {measure} على مدى "
                                   f"{_ar_n(periods, 'period')}.")})
    contributions = ctx.get("diagnostic", {}).get("contributions") or []
    if contributions:
        # The diagnostic answer as a picture: who moved the number, and
        # which way. This is the chart an executive acts on.
        items = contributions[:8]
        charts.append({"id": "chart_contributions", "type": "bar",
                       "title": _say(ctx,
                                     f"Who moved {measure}: change by {group_col}",
                                     f"من حرّك {measure}: التغير حسب {group_col}"),
                       "labels": [item["group"] for item in items],
                       "values": [item["change"] for item in items],
                       "source": "diagnostic.contributions",
                       "alt": _say(ctx,
                                   f"Bar chart of the change in {measure} for each "
                                   f"{group_col} between the first and last period, "
                                   "largest mover first; bars below zero moved "
                                   "against the overall direction.",
                                   f"مخطط أعمدة للتغير في {measure} لكل {group_col} "
                                   "بين الفترة الأولى والأخيرة، من الأكثر تحركاً؛ "
                                   "والأعمدة تحت الصفر تحركت عكس الاتجاه العام.")})
    if forecast:
        # History and forecast on one axis, with the boundary named in the
        # alt text so nobody mistakes a projection for a measurement.
        measured = len(prep["trend"])
        boundary = list(prep["trend"].keys())[-1]
        charts.append({"id": "chart_forecast", "type": "line",
                       "title": _say(ctx, f"{measure}: history and forecast",
                                     f"{measure}: التاريخ والتوقع"),
                       "labels": list(prep["trend"].keys()) + [f["label"] for f in forecast],
                       "values": list(prep["trend"].values()) + [f["value"] for f in forecast],
                       "source": "preparer.trend + predictive.forecast",
                       "alt": _say(ctx,
                                   f"Line chart of {measure} over {measured} measured "
                                   f"periods followed by {len(forecast)} forecast "
                                   f"periods; everything after {boundary} is a "
                                   "projection.",
                                   f"مخطط خطي لـ {measure} على مدى "
                                   f"{_ar_n(measured, 'period')} مقيسة تليها "
                                   f"{_ar_n(len(forecast), 'period')} متوقعة؛ وكل ما "
                                   f"بعد {boundary} إسقاط لا قياس.")})
    expected = {
        "chart_groups": sorted(prep["groups"].values(), reverse=True)[:8],
        "chart_trend": list(prep["trend"].values()),
        "chart_contributions": [item["change"] for item in contributions[:8]],
        "chart_forecast": list(prep["trend"].values()) + [f["value"] for f in forecast],
    }
    checks = [{"name": "chart_values_match_aggregates",
               "passed": all(chart["values"] == expected[chart["id"]] for chart in charts),
               "detail": _say(ctx,
                              "Chart values are taken directly from the prepared "
                              "aggregates and the forecast; axes start at zero.",
                              "قيم المخططات مأخوذة مباشرة من المجاميع المعدّة ومن "
                              "التوقع، والمحاور تبدأ من الصفر.")}]
    return _result("succeeded",
                   _say(ctx,
                        f"Prepared {len(charts)} truthful chart specifications with "
                        "alt text.",
                        f"أُعدّت مواصفات {_ar_n(len(charts), 'chart')} صادقة مع نص "
                        "بديل."),
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
        reason_en = (f"Only {len(series)} period(s) of history are available; at least "
                     f"{MIN_PERIODS_TO_FORECAST} are needed before a forecast means "
                     "anything.")
        reason_ar = (f"المتاح من التاريخ {len(series)} من الفترات فقط، ويلزم "
                     f"{MIN_PERIODS_TO_FORECAST} على الأقل قبل أن يكون للتوقع معنى.")
        reason = _say(ctx, reason_en, reason_ar)
        calcs.append({"id": "c_periods", "name": "periods_available",
                      "value": len(series), "method": f"distinct values of {date_col or '—'}"})
        claims.append(_claim(ctx, "cl_noforecast", "limitation",
                             f"No forecast was produced. {reason_en}",
                             f"لم يُنتَج أي توقع. {reason_ar}",
                             ["c_periods"]))
        headline = _say(ctx,
                        "We cannot responsibly forecast from this data yet — there is "
                        "not enough history.",
                        "لا يمكننا التوقع بمسؤولية من هذه البيانات بعد، فالتاريخ "
                        "المتاح غير كافٍ.")
        return _result("succeeded", headline,
                       output={"headline": headline, "forecast": [], "reason": reason,
                               "report_markdown": _section_report(
                                   "Predictive", "What will happen?", ctx,
                                   [reason, "",
                                    _say(ctx,
                                         "*Producing a number here anyway would look "
                                         "like analysis and behave like a guess.*",
                                         "*إنتاج رقم هنا رغم ذلك سيبدو تحليلاً "
                                         "ويتصرف كتخمين.*")], calcs,
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

    band_en = band_ar = ""
    if error is not None:
        low, high = predictions[0] * (1 - error), predictions[0] * (1 + error)
        band_en = f" In backtesting this method was off by about {error:.1%}, so treat it as " \
                  f"roughly {low:,.0f}–{high:,.0f}."
        band_ar = (f" وعند اختبارها على بيانات سابقة أخطأت هذه الطريقة بنحو {error:.1%}، "
                   f"فاعتبره تقريباً بين {low:,.0f} و{high:,.0f}.")
    claims.append(_claim(
        ctx, "cl_forecast", "forecast",
        f"If the pattern of the last {len(series)} periods continues, {measure} "
        f"for {forecast_labels[0]} is around {predictions[0]:,.2f}.{band_en} "
        "This assumes nothing changes about how the business operates.",
        f"إذا استمر نمط آخر {_ar_n(len(series), 'period')}، فإن {measure} في "
        f"{_period_label(ctx, forecast_labels[0])} سيكون نحو "
        f"{predictions[0]:,.2f}.{band_ar} "
        "ويفترض هذا ألا يتغير شيء في طريقة عمل النشاط.",
        ["c_forecast_0"] + (["c_backtest"] if error is not None else [])))
    claims.append(_claim(
        ctx, "cl_fit", "calculation",
        f"The trend line explains {explained:.0%} of the period-to-period "
        f"movement in {measure}; the rest is variation it does not capture.",
        f"يفسّر خط الاتجاه {explained:.0%} من تحرك {measure} من فترة إلى أخرى، "
        "والباقي تباين لا يلتقطه.",
        ["c_explained"]))
    if error is None:
        claims.append(_claim(
            ctx, "cl_nobacktest", "limitation",
            f"The forecast could not be backtested — that needs at least "
            f"{MIN_PERIODS_TO_BACKTEST} periods — so its accuracy is unmeasured.",
            f"تعذّر اختبار التوقع على بيانات سابقة، إذ يتطلب ذلك "
            f"{_ar_n(MIN_PERIODS_TO_BACKTEST, 'period')} على الأقل، فدقته غير "
            "مقيسة.",
            ["c_slope"]))

    if report_language(ctx) == "ar":
        lines = [f"الاتجاه: {measure} {'يرتفع' if slope >= 0 else 'ينخفض'} بنحو "
                 f"{abs(slope):,.2f} في كل فترة.", "",
                 "| الفترة | التوقع |", "| --- | --- |"]
    else:
        lines = [f"Direction: {measure} is moving {'up' if slope >= 0 else 'down'} "
                 f"by about {abs(slope):,.2f} per period.", "",
                 "| Period | Forecast |", "| --- | --- |"]
    lines += [f"| {_period_label(ctx, label)} | {value:,.2f} |"
              for label, value in zip(forecast_labels, predictions)]
    if report_language(ctx) == "ar":
        lines += ["",
                  (f"الدقة المقيسة: عند توقع آخر {_ar_n(holdout, 'period')} من "
                   f"البيانات الأسبق وحدها، أخطأت هذه الطريقة بمتوسط {error:.1%}."
                   if error is not None else
                   f"الدقة غير مقيسة: الاختبار على بيانات سابقة يتطلب "
                   f"{_ar_n(MIN_PERIODS_TO_BACKTEST, 'period')} على الأقل، وفي هذه "
                   f"البيانات {len(series)}."),
                  "",
                  f"يفسّر خط الاتجاه {explained:.0%} من التحرك بين الفترات.",
                  "",
                  "*هذا امتداد للماضي لا نموذج للنشاط. ويفترض عدم تغير الأسعار أو "
                  "الطاقة الاستيعابية أو الموسمية بما يتجاوز ما في البيانات، ولا "
                  "ظروف السوق.*"]
    else:
        lines += ["",
                  (f"Measured accuracy: predicting the most recent {holdout} period(s) "
                   f"from earlier data only, this method was off by {error:.1%} on "
                   "average."
                   if error is not None else
                   f"Accuracy is unmeasured: backtesting needs at least "
                   f"{MIN_PERIODS_TO_BACKTEST} periods and this dataset has "
                   f"{len(series)}."),
                  "",
                  f"The trend line explains {explained:.0%} of the movement between "
                  "periods.",
                  "",
                  "*This is an extension of the past, not a model of the business. It "
                  "assumes no change in pricing, capacity, seasonality beyond what is "
                  "already in the data, or market conditions.*"]
    first_value = prep["trend"][labels[-1]]
    expected_move = ((predictions[0] - first_value) / first_value) if first_value else None
    if report_language(ctx) == "ar":
        headline = (
            f"نتوقع أن يبلغ {measure} نحو {predictions[0]:,.0f} في "
            f"{_period_label(ctx, forecast_labels[0])}"
            + (f"، {'بارتفاع' if expected_move >= 0 else 'بانخفاض'} "
               f"{abs(expected_move):.0%} عن آخر فترة"
               if expected_move is not None else "")
            + (f". وقد أخطأت هذه الطريقة بنحو {error:.0%} عند اختبارها على بيانات "
               "سابقة."
               if error is not None else
               ". ولم تُختبر الدقة بعد على بيانات سابقة."))
    else:
        headline = (
            f"We expect {measure} of about {predictions[0]:,.0f} in {forecast_labels[0]}"
            + (f", {'up' if expected_move >= 0 else 'down'} {abs(expected_move):.0%} "
               "on the latest period" if expected_move is not None else "")
            + (f" — this method has been off by about {error:.0%} when tested on past "
               "data."
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

    arabic = report_language(ctx) == "ar"

    def add_option(key, title, target, base_value, rationale, evidence,
                   gain=None, method=None):
        """`title`, `target` and `rationale` are (English, Arabic) pairs. The
        English is what the audited claims and the calculation method cite;
        the Arabic is what an Arabic report shows."""
        gain = round(base_value * PLANNING_UPLIFT, 2) if gain is None else gain
        calcs.append({"id": f"c_option_{key}", "name": f"expected_gain_{key}",
                      "value": gain,
                      "method": method or (f"{PLANNING_UPLIFT:.0%} of {target[0]}'s "
                                           f"current {measure} ({base_value:,.2f})")})
        option = {"key": key, "title": title[0], "target": target[0],
                  "base_value": round(base_value, 2), "expected_gain": gain,
                  "rationale": rationale[0],
                  "evidence": evidence + [f"c_option_{key}"]}
        if arabic:
            option.update(title_ar=title[1], target_ar=target[1],
                          rationale_ar=rationale[1])
        options.append(option)

    if groups:
        leader = max(groups, key=groups.get)
        add_option("protect_leader",
                   (f"Protect the leading {group_col}: “{leader}”",
                    f"حماية الأكبر ضمن {group_col}: «{leader}»"),
                   (leader, leader), groups[leader],
                   (f"It is the largest single source of {measure}, so a given "
                    "percentage improvement is worth more here than anywhere else — "
                    "and so is a given percentage loss.",
                    f"هو أكبر مصدر منفرد لـ {measure}، فأي تحسن بنسبة معينة يساوي هنا "
                    "أكثر مما يساويه في أي مكان آخر، وكذلك أي خسارة بالنسبة نفسها."),
                   ["c_topshare"] if desc.get("top_share") is not None else [])
        laggard = min(groups, key=groups.get)
        if laggard != leader:
            add_option("grow_laggard",
                       (f"Grow the smallest {group_col}: “{laggard}”",
                        f"تنمية الأصغر ضمن {group_col}: «{laggard}»"),
                       (laggard, laggard), groups[laggard],
                       ("Smallest current contribution, so the same percentage "
                        "improvement moves the total least — but it reduces "
                        "dependence on the leader.",
                        "أصغر مساهمة حالية، فالتحسن بالنسبة نفسها يحرك الإجمالي "
                        "أقل من غيره، لكنه يقلل الاعتماد على الأكبر."),
                       [])
    declining = [c for c in diag.get("contributions", []) if c["change"] < 0]
    if declining:
        worst = min(declining, key=lambda c: c["change"])
        add_option("recover_decline",
                   (f"Reverse the decline in “{worst['group']}”",
                    f"عكس التراجع في «{worst['group']}»"),
                   (worst["group"], worst["group"]), abs(worst["change"]),
                   (f"This segment moved {worst['change']:,.2f} against the overall "
                    "direction; recovering part of that is a defined, bounded target.",
                    f"تحركت هذه الشريحة بمقدار {worst['change']:,.2f} عكس الاتجاه "
                    "العام، واسترداد جزء من ذلك هدف محدد ومحدود."),
                   ["c_totalchange"])

    forecast = pred.get("forecast") or []
    if forecast:
        # The baseline is worth exactly nothing extra by definition — that
        # is what makes it the bar the others have to clear.
        label = forecast[0]["label"]
        add_option("hold_course",
                   ("Hold course and re-measure next period",
                    "الاستمرار على النهج الحالي وإعادة القياس في الفترة التالية"),
                   ("the whole business", "النشاط كله"), 0.0,
                   (f"Changing nothing adds nothing: the forecast of "
                    f"{forecast[0]['value']:,.2f} for {label} already "
                    "assumes today's behaviour continues. This is the bar every other "
                    "option has to clear.",
                    f"عدم تغيير شيء لا يضيف شيئاً: فتوقع {forecast[0]['value']:,.2f} "
                    f"في {_period_label(ctx, label)} يفترض أصلاً استمرار السلوك "
                    "الحالي. وهذا هو الحد الذي يجب أن يتجاوزه كل خيار آخر."),
                   ["c_forecast_0"], gain=0.0,
                   method="baseline: no change means no gain beyond the forecast")

    def shown(option, field):
        return option.get(field + "_ar", option[field]) if arabic else option[field]

    if not options:
        reason_en = ("No option could be derived: the dataset has no grouping column "
                     "and no usable trend, so there is nothing to compare.")
        reason_ar = ("تعذّر استخلاص أي خيار: لا تحتوي البيانات على عمود للتجميع ولا "
                     "على اتجاه صالح، فلا يوجد ما يُقارن.")
        reason = _say(ctx, reason_en, reason_ar)
        calcs.append({"id": "c_nooptions", "name": "options_available", "value": 0,
                      "method": "no group column and no forecast"})
        claims.append(_claim(ctx, "cl_nooptions", "limitation", reason_en, reason_ar,
                             ["c_nooptions"]))
        headline = _say(ctx,
                        "We cannot recommend an action from this data: there are no "
                        "options to compare.",
                        "لا يمكننا التوصية بإجراء من هذه البيانات: لا توجد خيارات "
                        "للمقارنة.")
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

    claims.append(_claim(
        ctx, "cl_recommendation", "recommendation",
        f"Recommended action: {best['title']}. On the same {PLANNING_UPLIFT:.0%} "
        f"improvement applied to every option, it is worth {best['expected_gain']:,.2f} "
        f"in {measure}" +
        (f", ahead of the next option by {margin:,.2f}." if margin else ".") +
        " This is a recommendation under a stated assumption, not an observed "
        "outcome.",
        f"الإجراء الموصى به: {shown(best, 'title')}. عند تطبيق التحسن نفسه بنسبة "
        f"{PLANNING_UPLIFT:.0%} على كل خيار، تبلغ قيمته {best['expected_gain']:,.2f} "
        f"في {measure}" +
        (f"، متقدماً على الخيار التالي بمقدار {margin:,.2f}." if margin else ".") +
        " وهذه توصية قائمة على افتراض معلن، لا نتيجة مشاهدة.",
        best["evidence"]))
    claims.append(_claim(
        ctx, "cl_assumption", "assumption",
        f"Every option is scored with the same {PLANNING_UPLIFT:.0%} improvement "
        "applied to its target. The ranking therefore shows where the leverage is "
        "largest, not which option is easiest to achieve — that judgement needs "
        "cost and feasibility data this dataset does not contain.",
        f"يُقيَّم كل خيار بالتحسن نفسه بنسبة {PLANNING_UPLIFT:.0%} مطبقاً على هدفه. "
        "لذلك يبيّن الترتيب أين يكون الأثر الأكبر، لا أي الخيارات أسهل تحقيقاً؛ "
        "فهذا الحكم يحتاج إلى بيانات تكلفة وجدوى لا تتضمنها هذه البيانات.",
        [f"c_option_{best['key']}"]))

    if arabic:
        facts = [f"إجمالي {measure} هو {prep['total']:,.2f}."]
        if desc.get("change") is not None:
            facts.append(f"تحرك {measure} بنسبة {desc['change']:+.1%} خلال الفترة.")
        if diag.get("contributions"):
            facts.append(f"يمثل {diag['contributions'][0]['group']} الجزء الأكبر من "
                         "هذا التحرك.")
        if forecast:
            facts.append(f"التوقع للفترة التالية {forecast[0]['value']:,.2f}.")
        facts.append(f"الإجراء الموصى به: {shown(best, 'title')}.")
    else:
        facts = [f"Total {measure} is {prep['total']:,.2f}."]
        if desc.get("change") is not None:
            facts.append(f"{measure} moved {desc['change']:+.1%} across the period.")
        if diag.get("contributions"):
            facts.append(f"{diag['contributions'][0]['group']} accounts for the largest "
                         "part of that movement.")
        if forecast:
            facts.append(f"Next period is forecast at {forecast[0]['value']:,.2f}.")
        facts.append(f"The recommended action is: {best['title']}.")
    goal = ctx.get("goal", "the analysis")
    if not gateway:
        narration = {"text": " ".join(facts), "source": "deterministic"}
    elif arabic:
        narration = gateway.narrate(goal, facts, language="ar")
    else:
        narration = gateway.narrate(goal, facts)

    if arabic:
        lines = ["| الخيار | الهدف | المكسب المتوقع | السبب |", "| --- | --- | --- | --- |"]
    else:
        lines = ["| Option | Target | Expected gain | Why |", "| --- | --- | --- | --- |"]
    for option in options:
        lines.append(f"| {shown(option, 'title')} | {shown(option, 'target')} | "
                     f"{option['expected_gain']:,.2f} | {shown(option, 'rationale')} |")
    if arabic:
        lines += ["", f"**التوصية: {shown(best, 'title')}**", "",
                  shown(best, "rationale"), "",
                  f"*يُقيَّم كل خيار بالتحسن نفسه بنسبة {PLANNING_UPLIFT:.0%} مطبقاً "
                  "على هدفه، فهذا ترتيب لمواضع الأثر الأكبر، لا لأرخص الخيارات أو "
                  "أرجحها نجاحاً. وقد يتغير الترتيب عند إدخال أرقام التكلفة "
                  "والجدوى.*"]
    else:
        lines += ["", f"**Recommendation: {best['title']}**", "", best["rationale"], "",
                  f"*Every option is scored with the same {PLANNING_UPLIFT:.0%} "
                  "improvement applied to its target, so this ranks where the leverage "
                  "is — not which option is cheapest or most likely to succeed. Supply "
                  "cost and feasibility figures and the ranking can change.*"]
    if margin is not None and best["expected_gain"]:
        closeness = margin / best["expected_gain"]
        lines += ["", _say(ctx,
                           f"*How close is the call? The runner-up is behind by "
                           f"{closeness:.0%} of the leading option's value."
                           + (" That is close enough that cost and feasibility should "
                              "decide it, not this ranking.*"
                              if closeness < 0.20 else "*"),
                           f"*ما مدى تقارب القرار؟ يتأخر الخيار الثاني بما يعادل "
                           f"{closeness:.0%} من قيمة الخيار الأول."
                           + (" وهذا تقارب يجعل التكلفة والجدوى هما الحكم، لا هذا "
                              "الترتيب.*" if closeness < 0.20 else "*"))]
    headline = _say(ctx,
                    f"We recommend: {best['title']}. It is worth about "
                    f"{best['expected_gain']:,.0f} in {measure} — more than any other "
                    f"option we compared.",
                    f"نوصي بـ: {shown(best, 'title')}. وقيمته نحو "
                    f"{best['expected_gain']:,.0f} في {measure}، وهي أكبر من أي خيار "
                    "آخر قارنّاه.")
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
                   "detail": _say(ctx,
                                  f"{clean['rows_after']} kept + {clean['dropped']} "
                                  f"dropped = {clean['rows_before']} input rows",
                                  f"{clean['rows_after']} محتفظ به + {clean['dropped']} "
                                  f"محذوف = {clean['rows_before']} صف مُدخل")})
    all_calc_ids = {c["id"] for stage in evidence_stages(ctx)
                    for c in ctx.get(stage + "_result", {}).get("calculations", [])}
    all_claims = [cl for stage in evidence_stages(ctx)
                  for cl in ctx.get(stage + "_result", {}).get("claims", [])]
    unsupported = [cl["id"] for cl in all_claims
                   if not set(cl.get("evidence", [])) <= all_calc_ids]
    checks.append({"name": "every_claim_has_evidence", "passed": not unsupported,
                   "detail": (_say(ctx, "All claims trace to calculations.",
                                   "كل الاستنتاجات تعود إلى عمليات حسابية.")
                              if not unsupported else
                              _say(ctx, "Unsupported claims: ",
                                   "استنتاجات بلا دليل: ") + ", ".join(unsupported))})

    # Each analytics type must have produced its own report.
    missing_reports = [name for name, _ in ANALYTICS_TYPES
                       if not ctx.get(name, {}).get("report_markdown")]
    checks.append({"name": "every_analytics_type_reported",
                   "passed": not missing_reports,
                   "detail": (_say(ctx, "All four analytics types produced a report.",
                                   "أنتجت أنواع التحليل الأربعة تقاريرها كلها.")
                              if not missing_reports else
                              _say(ctx, "Missing reports: ", "تقارير مفقودة: ")
                              + ", ".join(missing_reports))})

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
    # Read from the English text, which every claim carries in every run.
    forecast_claims = [cl for cl in all_claims if cl["type"] == "forecast"]
    backtested = ctx.get("predictive", {}).get("backtest_error") is not None
    declared = any(cl["type"] == "limitation" and "backtest" in cl["text"].lower()
                   for cl in all_claims)
    checks.append({"name": "forecast_accuracy_is_measured_or_declared",
                   "passed": not forecast_claims or backtested or declared,
                   "detail": _say(
                       ctx,
                       ("Forecast accuracy is backtested." if backtested else
                        "No forecast made." if not forecast_claims else
                        "Unmeasured accuracy is declared as a limitation."
                        if declared else
                        "A forecast was made without measuring or declaring "
                        "its accuracy."),
                       ("دقة التوقع مختبرة على بيانات سابقة." if backtested else
                        "لم يُنتَج توقع." if not forecast_claims else
                        "الدقة غير المقيسة مصرَّح بها بوصفها قيداً."
                        if declared else
                        "أُنتج توقع دون قياس دقته أو التصريح بذلك."))})

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
            "detail": _say(
                ctx,
                (f"“{measured.get('measure')}” is a certified metric "
                 f"owned by {measured.get('owner')}." if certified else
                 "The report states that the measure carries no certified "
                 "definition." if declared else
                 "The measure is uncertified and the report does not say "
                 "so."),
                (f"«{measured.get('measure')}» مؤشر معتمد ومالكه "
                 f"{measured.get('owner')}." if certified else
                 "يصرّح التقرير بأن المقياس ليس له تعريف معتمد." if declared else
                 "المقياس غير معتمد والتقرير لا يصرّح بذلك."))})

    # Recommendations are only honest with their assumptions attached.
    recommendations = [cl for cl in all_claims if cl["type"] == "recommendation"]
    assumptions = [cl for cl in all_claims if cl["type"] == "assumption"]
    checks.append({"name": "recommendations_state_their_assumptions",
                   "passed": not recommendations or bool(assumptions),
                   "detail": _say(ctx,
                                  f"{len(recommendations)} recommendation(s), "
                                  f"{len(assumptions)} stated assumption(s).",
                                  f"التوصيات: {len(recommendations)}، والافتراضات "
                                  f"المعلنة: {len(assumptions)}.")})

    # Personal data must reach the approver, because approval is the moment
    # the report leaves the analyst's hands.
    privacy_result = ctx.get("privacy", {})
    if privacy_result.get("personal_data"):
        surfaced = any(cl["type"] == "warning" for cl in all_claims)
        flagged = len(privacy_result["findings"])
        checks.append({"name": "personal_data_reaches_the_approver",
                       "passed": surfaced,
                       "detail": _say(
                           ctx,
                           (f"{flagged} column(s) with personal data are declared in "
                            "the report." if surfaced else
                            "Personal data was detected but no warning reached "
                            "the report."),
                           (f"صُرّح في التقرير بـ {flagged} من الأعمدة التي تحتوي "
                            "على بيانات شخصية." if surfaced else
                            "اكتُشفت بيانات شخصية ولم يصل أي تحذير إلى التقرير."))})

    # Provenance must hold in the direction that matters: no claim may cite
    # evidence that does not exist.
    dangling = ctx.get("lineage", {}).get("dangling")
    if dangling is not None:
        checks.append({"name": "provenance_chain_is_complete", "passed": not dangling,
                       "detail": (_say(ctx,
                                       "Every claim walks back to a recorded "
                                       "calculation.",
                                       "كل استنتاج يعود إلى عملية حسابية مسجلة.")
                                  if not dangling else
                                  _say(ctx, "Claims cite missing evidence: ",
                                       "استنتاجات تستشهد بأدلة مفقودة: ")
                                  + ", ".join(dangling))})

    # Business language is a requirement, so it is checked — on the
    # headlines as well as the claims, since the headline is the line an
    # executive actually reads. In an Arabic run the Arabic is what the
    # executive reads, so it is checked too.
    def reader_texts(claim):
        return [claim["text"]] + ([claim["text_ar"]] if "text_ar" in claim else [])

    jargon_hits = {}
    for claim in all_claims:
        hits = [word for text in reader_texts(claim) for word in _jargon_in(text)]
        if hits:
            jargon_hits[claim["id"]] = hits
    for name, _ in REPORT_SECTIONS:
        headline = ctx.get(name, {}).get("headline", "")
        if _jargon_in(headline):
            jargon_hits[f"{name}.headline"] = _jargon_in(headline)
    checks.append({"name": "claims_avoid_statistical_jargon",
                   "passed": not jargon_hits,
                   "detail": (_say(ctx, "Claims are written in business language.",
                                   "الاستنتاجات مكتوبة بلغة الأعمال.")
                              if not jargon_hits else
                              _say(ctx, "Jargon found: ", "مصطلحات إحصائية: ")
                              + "; ".join(f"{k}: {', '.join(v)}"
                                          for k, v in jargon_hits.items()))})

    # A report in a second language is a second chance to misstate a
    # figure. The audited English and the Arabic the reader sees must cite
    # the same figures, or the run is rejected rather than published with
    # a number nobody calculated (ADR 0022).
    if report_language(ctx) != "en":
        drifted = [cl["id"] for cl in all_claims
                   if "text_ar" in cl and figures(cl["text_ar"]) != figures(cl["text"])]
        untranslated = [cl["id"] for stage in EVIDENCE_STAGES
                        for cl in ctx.get(stage + "_result", {}).get("claims", [])
                        if "text_ar" not in cl]
        checks.append({
            "name": "both_languages_cite_the_same_figures",
            "passed": not drifted,
            "detail": (_say(ctx,
                            "Every claim cites the same figures in English and in "
                            "the report's language.",
                            "كل استنتاج يذكر الأرقام نفسها بالإنجليزية وبلغة "
                            "التقرير.")
                       if not drifted else
                       _say(ctx, "Figures differ between languages in: ",
                            "تختلف الأرقام بين اللغتين في: ") + ", ".join(drifted))})
        checks.append({
            "name": "every_builtin_claim_is_in_the_report_language",
            "passed": not untranslated,
            "detail": (_say(ctx, "No built-in claim is left in English only.",
                            "لم يُترك أي استنتاج من المراحل المدمجة بالإنجليزية "
                            "وحدها.")
                       if not untranslated else
                       _say(ctx, "Only in English: ", "بالإنجليزية فقط: ")
                       + ", ".join(untranslated))})
    passed = all(c["passed"] for c in checks)
    return _result(
        "succeeded" if passed else "failed",
        _say(ctx,
             ("All validation checks passed: totals reconcile, rows are accounted "
              "for, and every claim traces to a calculation.")
             if passed else "Validation FAILED — see quality checks. The work is "
                            "rejected, not rewritten.",
             ("اجتازت كل فحوص التحقق: المجاميع متطابقة، وكل صف محسوب، وكل استنتاج "
              "يعود إلى عملية حسابية.")
             if passed else "فشل التحقق، انظر فحوص الجودة. يُرفض العمل ولا يُعاد "
                            "تحريره."),
        output={"passed": passed, "claim_count": len(all_claims),
                "unsupported": unsupported},
        checks=checks,
    )


def _routing_note(routing, source=None, language="en"):
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
    arabic = language == "ar"
    if not routing.get("honoured"):
        # The router's reason is its own text and is quoted as written.
        why = routing.get("why", "").rstrip(".")
        return (f"، بعد أن لم يُستخدم اختيار {routing['router']}: {why}" if arabic
                else f", after {routing['router']}'s choice was not used — {why}")
    if source == "deterministic":
        return (f"، بعد أن وجّهه {routing['router']} إلى «{routing['chose']}» الذي "
                "لم يُجب" if arabic else
                f", after {routing['router']} routed this to "
                f"“{routing['chose']}”, which did not answer")
    return (f"، باختيار {routing['router']} الذي انتقى «{routing['chose']}»"
            if arabic else
            f", chosen by {routing['router']} which picked “{routing['chose']}”")


def _custom_stage_lines(ctx):
    """What each custom stage found, or that it failed. A stage the
    operator added is part of the run, so its outcome is in the report
    either way — a report that silently lacked a stage would be a
    report the reader could not tell was incomplete."""
    roles = ctx.get("custom_stages") or []
    if not roles:
        return []
    titles = ctx.get("custom_titles") or {}
    failures = ctx.get("custom_failures") or {}
    lines = ["", _say(ctx, "## Custom stages", "## المراحل المخصصة")]
    for role in roles:
        result = ctx.get(role + "_result")
        title = titles.get(role, role)
        if result:
            lines.append(f"- **{title}:** {result['summary']}")
        else:
            reason = failures.get(role) or _say(ctx, "no result was recorded",
                                                "لم تُسجَّل أي نتيجة")
            lines.append(_say(ctx, f"- **{title}:** failed — {reason}",
                              f"- **{title}:** أخفقت: {reason}"))
    return lines


# The comprehensive report's fixed text, per language. Kept together so
# the two can be read side by side.
REPORT_TEXT = {
    "en": {
        "title": "# Business Analytics Report — {dataset}",
        "goal": "**Goal:** {goal}",
        "summary": "## Executive summary",
        "source": "*(Narrative source: {source}{routing}; every figure in this "
                  "report is deterministically calculated.)*",
        "questions": "## The four questions",
        "questions_head": "| Type | Question | Answer in one line |",
        "cause": "**Can we claim a cause?** {answer}",
        "measures": "## What this report measures",
        "quality": "## Data quality, privacy and provenance",
        "metrics": "## Key metrics",
        "metrics_intro": "Every figure produced by the run, in one place. Each "
                         "per-type section below repeats the figures it used.",
        "metrics_head": "| Metric | Value | Method |",
        "claims": "## Every claim in this report",
        "claims_head": "| Claim | Type | Evidence | Status |",
        "charts": "## Charts",
        "validation": "## Validation",
        "pass": "PASS", "fail": "FAIL",
        "limits": "## Assumptions and limitations",
        "limits_lines": [
            "- Findings describe only the supplied snapshot (sha256:{snapshot}).",
            "- Diagnostic analysis shows where movement came from and what moves "
            "with what. It does not establish cause; the causal section states "
            "whether this dataset supports a causal claim at all, and what design "
            "would settle it.",
            "- The forecast extends the historical pattern. It assumes the business "
            "keeps operating as it has, and it is stated with the error measured by "
            "backtesting (or explicitly marked unmeasured).",
            "- The recommendation ranks options by leverage under one stated "
            "improvement assumption applied equally to each. It is not a claim "
            "about cost, feasibility, or certainty of outcome.",
        ],
        "footer": "*Generated by Agentic OS run {run_id} — measure “{measure}”, "
                  "{rows} analyzed rows.*",
        "done": "Comprehensive report assembled from all four analytics types: "
                "{claims} claims, all with evidence links, validation {verdict}",
        "passed": "passed.", "failed": "FAILED.",
    },
    "ar": {
        "title": "# تقرير تحليل الأعمال: {dataset}",
        "goal": "**الهدف:** {goal}",
        "summary": "## الملخص التنفيذي",
        "source": "*(مصدر الصياغة: {source}{routing}؛ وكل رقم في هذا التقرير محسوب "
                  "حساباً حتمياً.)*",
        "questions": "## الأسئلة الأربعة",
        "questions_head": "| النوع | السؤال | الإجابة في سطر واحد |",
        "cause": "**هل يمكننا ادعاء سبب؟** {answer}",
        "measures": "## ما يقيسه هذا التقرير",
        "quality": "## جودة البيانات والخصوصية وسلسلة الإثبات",
        "metrics": "## المؤشرات الرئيسية",
        "metrics_intro": "كل رقم أنتجه التشغيل في مكان واحد. ويكرر كل قسم أدناه "
                         "الأرقام التي استخدمها.",
        "metrics_head": "| المؤشر | القيمة | الطريقة |",
        "claims": "## كل استنتاج في هذا التقرير",
        "claims_head": "| الاستنتاج | النوع | الدليل | الحالة |",
        "charts": "## المخططات",
        "validation": "## التحقق",
        "pass": "اجتاز", "fail": "لم يجتز",
        "limits": "## الافتراضات والقيود",
        "limits_lines": [
            "- تصف النتائج لقطة البيانات المقدَّمة وحدها (sha256:{snapshot}).",
            "- يبيّن التحليل التشخيصي من أين جاء التحرك وما الذي يتحرك مع ماذا. "
            "ولا يثبت سبباً؛ ويبيّن القسم السببي هل تدعم هذه البيانات ادعاءً سببياً "
            "أصلاً، وما التصميم الذي يحسم المسألة.",
            "- يمدّ التوقع النمط التاريخي. ويفترض استمرار النشاط على ما كان عليه، "
            "ويُعرض مع الخطأ المقيس بالاختبار على بيانات سابقة (أو مع التصريح بأنه "
            "غير مقيس).",
            "- ترتب التوصية الخيارات حسب الأثر في ظل افتراض تحسن واحد معلن ومطبق "
            "بالتساوي على كل خيار. وليست ادعاءً عن التكلفة أو الجدوى أو يقين "
            "النتيجة.",
        ],
        "footer": "*أُنتج بواسطة تشغيل Agentic OS رقم {run_id}، المقياس «{measure}»، "
                  "وعدد الصفوف المحللة {rows}.*",
        "done": "جُمع التقرير الشامل من أنواع التحليل الأربعة: {claims} مع روابط "
                "أدلتها كلها، والتحقق {verdict}",
        "passed": "ناجح.", "failed": "فاشل.",
    },
}

# How an Arabic report names the four types, the claim kinds and the
# narrator. Identifiers stay as they are in the evidence; these are labels.
TYPE_NAMES_AR = {"descriptive": "وصفي", "diagnostic": "تشخيصي",
                 "predictive": "تنبؤي", "prescriptive": "توجيهي"}
CLAIM_KINDS_AR = {"fact": "حقيقة", "calculation": "حساب", "finding": "نتيجة",
                  "forecast": "توقع", "recommendation": "توصية",
                  "assumption": "افتراض", "limitation": "قيد", "warning": "تحذير"}
NARRATOR_AR = {"deterministic": "حتمية (قالب ثابت)", "model": "نموذج لغوي"}
STATUS_AR = {"verified": "متحقق منه"}


def reporter(ctx):
    """The comprehensive report: the four type reports in one document.

    It embeds each type report in full rather than linking to it, because
    the approval gate binds to this artifact's hash — whatever a human
    approves for publication is exactly what they were shown.
    """
    prep = ctx["preparer"]
    language = report_language(ctx)
    arabic = language == "ar"
    text = REPORT_TEXT[language]
    source = ctx["prescriptive"]["exec_summary_source"]
    lines = [
        text["title"].format(dataset=ctx.get("dataset_name", "dataset")),
        "",
        text["goal"].format(goal=ctx.get("goal", "")),
        "",
        text["summary"],
        ctx["prescriptive"]["exec_summary"],
        text["source"].format(
            source=NARRATOR_AR.get(source, source) if arabic else source,
            routing=_routing_note(ctx["prescriptive"].get("exec_summary_routing"),
                                  source, language)),
        "",
        text["questions"],
        text["questions_head"],
        "| --- | --- | --- |",
    ]
    headlines = {
        "descriptive": ctx["descriptive_result"]["summary"],
        "diagnostic": ctx["diagnostic_result"]["summary"],
        "predictive": ctx["predictive_result"]["summary"],
        "prescriptive": ctx["prescriptive_result"]["summary"],
    }
    for name, question in ANALYTICS_TYPES:
        if arabic:
            question = SECTION_TITLES_AR[name.capitalize()][1]
            lines.append(f"| {TYPE_NAMES_AR[name]} | {question} | {headlines[name]} |")
        else:
            lines.append(f"| {name.capitalize()} | {question} | {headlines[name]} |")
    # The boundary question sits under the table rather than in it: it is
    # not a fifth type, it is the check on what the four may be used for.
    lines += ["", text["cause"].format(answer=ctx["experiment_result"]["summary"]),
              "", text["measures"],
              ctx["governance"]["notes_markdown"],
              "", text["quality"],
              ctx["governance_result"]["summary"],
              ctx["quality_result"]["summary"],
              ctx["contract_result"]["summary"],
              ctx["profiler_result"]["summary"], ctx["cleaner_result"]["summary"],
              ctx["privacy_result"]["summary"],
              ctx["lineage_result"]["summary"],
              ctx["segments_result"]["summary"],
              ctx["anomaly_result"]["summary"],
              ctx["sensitivity_result"]["summary"],
              *_custom_stage_lines(ctx),
              "", text["metrics"],
              text["metrics_intro"],
              "", text["metrics_head"], "| --- | --- | --- |"]
    for stage in evidence_stages(ctx):
        for calc in ctx.get(stage + "_result", {}).get("calculations", []):
            lines.append(f"| {calc['name']} | {calc['value']} | {calc['method']} |")
    if arabic:
        lines += ["", AR_METHODS_NOTE]

    for name, _ in REPORT_SECTIONS:
        section = ctx[name].get("report_markdown", "")
        # Demote the section's own H1 so the combined document keeps one
        # heading level per depth.
        lines += ["", "---", ""]
        lines += ["#" + line if line.startswith("# ") else line
                  for line in section.split("\n")]
    for role in ctx.get("custom_stages") or []:
        section = ctx.get(role, {}).get("report_markdown", "")
        if section:
            lines += ["", "---", ""]
            lines += ["#" + line if line.startswith("# ") else line
                      for line in section.split("\n")]

    lines += ["", "---", "", text["claims"],
              text["claims_head"], "| --- | --- | --- | --- |"]
    for stage in evidence_stages(ctx):
        for claim in ctx.get(stage + "_result", {}).get("claims", []):
            if arabic:
                # A custom stage may speak English only; its claim is shown
                # as written rather than left out.
                lines.append(f"| {claim.get('text_ar', claim['text'])} | "
                             f"{CLAIM_KINDS_AR.get(claim['type'], claim['type'])} | "
                             f"{', '.join(claim['evidence'])} | "
                             f"{STATUS_AR.get(claim['status'], claim['status'])} |")
            else:
                lines.append(f"| {claim['text']} | {claim['type']} | "
                             f"{', '.join(claim['evidence'])} | {claim['status']} |")
    lines += ["", text["charts"]]
    for chart in ctx["visuals"]["charts"]:
        lines.append(f"- **{chart['title']}** ({chart['type']}): {chart['alt']}")
    lines += ["", text["validation"], ctx["validator_result"]["summary"]]
    for check in ctx["validator_result"]["quality_checks"]:
        verdict = text["pass"] if check["passed"] else text["fail"]
        lines.append(f"- {verdict}: {check['name']}: {check['detail']}"
                     if arabic else
                     f"- {verdict} — {check['name']}: {check['detail']}")
    lines += ["", text["limits"]]
    lines += [line.format(snapshot=ctx["collector"]["snapshot"])
              for line in text["limits_lines"]]
    lines += ["", text["footer"].format(run_id=ctx.get("run_id", ""),
                                        measure=prep["measure"],
                                        rows=ctx["cleaner"]["rows_after"])]
    report = "\n".join(lines)
    return _result(
        "succeeded",
        text["done"].format(claims=(_ar_n(ctx["validator"]["claim_count"], "claim")
                                    if arabic else ctx["validator"]["claim_count"]),
                            verdict=text["passed"] if ctx["validator"]["passed"]
                            else text["failed"]),
        output={"report_markdown": report, "language": language},
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


def evidence_stages(ctx):
    """The stages whose claims and calculations this run audits: the
    built-in evidence stages plus any custom stages the run declared
    (ADR 0020). Provenance, validation and the report all read this,
    so a custom stage is under the same governance as a built-in one
    — that is the condition of being admitted, not an option."""
    return EVIDENCE_STAGES + tuple(ctx.get("custom_stages") or ())


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

# The same roster as an Arabic run names it. Keyed identically, so a stage
# added to one and not the other is caught by tests/test_report_language.py.
ROLE_TITLES_AR = {
    "planner": "وكيل التخطيط",
    "collector": "وكيل مصادر البيانات",
    "contract": "وكيل عقد البيانات",
    "profiler": "وكيل توصيف البيانات",
    "quality": "وكيل جودة البيانات",
    "privacy": "وكيل الخصوصية",
    "cleaner": "وكيل تنظيف البيانات",
    "governance": "وكيل حوكمة المؤشرات: هل المقياس معرَّف وله مالك؟",
    "preparer": "وكيل إعداد البيانات",
    "segments": "وكيل تركّز الشرائح",
    "descriptive": "وكيل التحليل الوصفي: ماذا حدث؟",
    "diagnostic": "وكيل التحليل التشخيصي: لماذا حدث؟",
    "experiment": "وكيل التجارب والاستدلال السببي: هل يمكننا ادعاء سبب؟",
    "predictive": "وكيل التحليل التنبؤي: ماذا سيحدث؟",
    "anomaly": "وكيل رصد الحالات الشاذة",
    "prescriptive": "وكيل التحليل التوجيهي: ماذا ينبغي أن أفعل؟",
    "sensitivity": "وكيل الحساسية: هل تصمد التوصية أمام افتراض مختلف؟",
    "visuals": "خبير التمثيل البصري",
    "lineage": "وكيل سلسلة الإثبات",
    "validator": "خبير التحقق",
    "reporter": "خبير إعداد التقارير",
    "publish": "أمين المعرفة (النشر في المخزن)",
}
