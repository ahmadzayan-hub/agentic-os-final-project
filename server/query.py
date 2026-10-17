"""Questions asked of a run's cleaned table (ADR 0031).

A run's analysis table — cleaned, and merged when the run joins datasets
(ADR 0030) — can be downloaded as CSV, described field by field, totalled
by group under filters, and read row by row. This module holds all four
as pure functions over a `Table`, so the API only checks who is asking.

The query language is small on purpose: named aggregates, named filter
operators, at most two groupings. A rate is a ratio of sums, never an
average of row rates, because that is the one definition that adds up.
"""

import csv
import io
import math
import re
from dataclasses import dataclass, field

AGGREGATES = ("sum", "mean", "min", "max", "count", "distinct", "ratio")
OPERATORS = ("eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "between",
             "empty", "not_empty")
MAX_GROUP_BY = 2
MAX_MEASURES = 8
MAX_FILTERS = 12
MAX_VALUES = 200
MAX_GROUPS = 1000
MAX_PAGE = 100
MAX_SAMPLE = 2000
MIN_BINS, MAX_BINS = 2, 50
# Text columns list their values when there are at most this many.
LISTED_VALUES = 200
# A cell a spreadsheet would read as a formula (OWASP, CSV injection).
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@dataclass
class Table:
    """A run's analysis table, as rows of tuples in column order."""
    columns: list
    numeric: set
    rows: list
    roles: dict = field(default_factory=dict)

    def index(self, column):
        return self.columns.index(column)


def table_from(columns, numeric, rows, roles=None):
    """Build a Table from the stored rows (dicts), keeping column order."""
    return Table(list(columns), set(numeric),
                 [tuple(row.get(c) for c in columns) for row in rows], roles or {})


@dataclass
class Problem:
    field: str
    column: str | None
    en: str
    ar: str

    def as_dict(self, language="en"):
        return {"field": self.field, "column": self.column,
                "message": self.ar if language == "ar" else self.en}


class QueryError(Exception):
    """A question the table cannot answer as asked, with every reason."""

    def __init__(self, problems):
        super().__init__(problems[0].en)
        self.problems = problems

    def detail(self, language="en"):
        count = len(self.problems)
        if language == "ar":
            many = ("مشكلة واحدة" if count == 1 else "مشكلتان" if count == 2
                    else f"{count} مشكلات" if count <= 10 else f"{count} مشكلة")
            summary = f"لم يُنفَّذ الاستعلام: {many} تحتاج إلى إصلاح."
        else:
            summary = f"The query was not run: {count} problem{'s' if count != 1 else ''} to fix."
        return {"message": summary,
                "errors": [p.as_dict(language) for p in self.problems]}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _cell(value, numeric):
    if value is None:
        return ""
    if numeric and isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return repr(value) if isinstance(value, float) else str(value)
    text = str(value)
    # Only text is guarded: a measure is a number and is never altered.
    return "'" + text if text.startswith(FORMULA_START) else text


def to_csv(table):
    """The table as CSV text: UTF-8 byte-order mark, RFC 4180 quoting,
    numbers written plainly, formula-like text neutralised."""
    out = io.StringIO()
    out.write("﻿")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([_cell(c, False) for c in table.columns])
    numeric = [c in table.numeric for c in table.columns]
    for row in table.rows:
        writer.writerow([_cell(v, n) for v, n in zip(row, numeric)])
    return out.getvalue()


def download_name(goal, run_id):
    slug = re.sub(r"[^a-z0-9]+", "-", str(goal or "").lower()).strip("-")[:48] or "run"
    return f"{slug}-{run_id}-cleaned.csv"


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

def _text_order(values):
    return sorted(values, key=lambda v: (v == "", v))


def fields(table):
    """Each column: its type, its role, how filled it is, and the range
    or the values a filter can offer."""
    out = []
    for position, column in enumerate(table.columns):
        values = [row[position] for row in table.rows]
        filled = [v for v in values if v is not None and v != ""]
        entry = {"name": column, "type": "number" if column in table.numeric else "text",
                 "role": table.roles.get(column), "filled": len(filled),
                 "records": len(values)}
        if column in table.numeric:
            numbers = [v for v in filled if isinstance(v, (int, float))]
            entry.update(min=min(numbers) if numbers else None,
                         max=max(numbers) if numbers else None)
        else:
            distinct = set(str(v) for v in values if v is not None)
            entry["distinct"] = len(distinct)
            if len(distinct) <= LISTED_VALUES:
                entry["values"] = _text_order(distinct)
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Checking a request
# ---------------------------------------------------------------------------

def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _unknown(column, where):
    return Problem(where, column,
                   f"“{column}” is not a column of this run's table.",
                   f"«{column}» ليس عموداً في جدول هذا التشغيل.")


def _check_filters(table, filters, problems):
    """Each filter as (position, operator, typed values, numeric)."""
    filters = list(filters or [])
    if len(filters) > MAX_FILTERS:
        problems.append(Problem("filters", None,
                                f"At most {MAX_FILTERS} filters; {len(filters)} were given.",
                                f"الحد الأقصى {MAX_FILTERS} مرشحاً، وحُدد {len(filters)}."))
    checked = []
    for item in filters[:MAX_FILTERS]:
        item = item or {}
        column, op = item.get("column"), item.get("op")
        if column not in table.columns:
            problems.append(_unknown(column, "filters"))
            continue
        if op not in OPERATORS:
            problems.append(Problem("filters", column,
                                    f"“{op}” is not a filter; use one of {', '.join(OPERATORS)}.",
                                    f"«{op}» ليس مرشحاً؛ استخدم واحداً من {', '.join(OPERATORS)}."))
            continue
        numeric = column in table.numeric
        if op in ("empty", "not_empty"):
            raw = []
        elif op in ("in", "not_in", "between"):
            raw = item.get("values")
            if not isinstance(raw, list) or not raw or len(raw) > MAX_VALUES or (
                    op == "between" and len(raw) != 2):
                problems.append(Problem(
                    "filters", column,
                    (f"“{op}” on {column} needs two values, from and to." if op == "between"
                     else f"“{op}” on {column} needs a list of 1 to {MAX_VALUES} values."),
                    (f"«{op}» على {column} يحتاج إلى قيمتين: من وإلى." if op == "between"
                     else f"«{op}» على {column} يحتاج إلى قائمة من 1 إلى {MAX_VALUES} قيمة.")))
                continue
        else:
            if "value" not in item:
                problems.append(Problem("filters", column,
                                        f"“{op}” on {column} needs a value.",
                                        f"«{op}» على {column} يحتاج إلى قيمة."))
                continue
            raw = [item.get("value")]
        if numeric:
            typed = [_number(v) for v in raw]
            if any(v is None for v in typed):
                problems.append(Problem("filters", column,
                                        f"{column} holds numbers, so its filter needs numbers.",
                                        f"{column} يحمل أرقاماً، فمرشحه يحتاج إلى أرقام."))
                continue
        else:
            typed = ["" if v is None else str(v) for v in raw]
        checked.append((table.index(column), op, typed, numeric))
    return checked


def _passes(row, filters):
    for position, op, values, numeric in filters:
        value = row[position]
        empty = value is None or value == ""
        if op == "empty":
            if not empty:
                return False
            continue
        if op == "not_empty":
            if empty:
                return False
            continue
        if not numeric:
            value = "" if value is None else str(value)
        if op == "eq":
            ok = value == values[0]
        elif op == "ne":
            ok = value != values[0]
        elif op == "in":
            ok = value in values
        elif op == "not_in":
            ok = value not in values
        elif empty and numeric:
            ok = False  # an empty measure is neither above nor below anything
        elif op == "gt":
            ok = value > values[0]
        elif op == "gte":
            ok = value >= values[0]
        elif op == "lt":
            ok = value < values[0]
        elif op == "lte":
            ok = value <= values[0]
        else:  # between, inclusive
            ok = values[0] <= value <= values[1]
        if not ok:
            return False
    return True


def filtered(table, filters):
    """(rows that pass, the checked filters). Raises QueryError."""
    problems = []
    checked = _check_filters(table, filters, problems)
    if problems:
        raise QueryError(problems)
    return [row for row in table.rows if _passes(row, checked)], checked


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def _measure_key(measure):
    agg = measure["agg"]
    if agg == "count":
        return "count"
    if agg == "ratio":
        return f"ratio:{measure['numerator']}/{measure['denominator']}"
    return f"{agg}:{measure['column']}"


def _check_measures(table, measures, problems):
    measures = list(measures or [])
    if not measures or len(measures) > MAX_MEASURES:
        problems.append(Problem("measures", None,
                                f"Ask for 1 to {MAX_MEASURES} measures.",
                                f"اطلب من 1 إلى {MAX_MEASURES} مقاييس."))
        return []
    checked = []
    for item in measures:
        item = dict(item or {})
        agg = item.get("agg")
        if agg not in AGGREGATES:
            problems.append(Problem("measures", None,
                                    f"“{agg}” is not an aggregate; use one of "
                                    f"{', '.join(AGGREGATES)}.",
                                    f"«{agg}» ليست دالة تجميع؛ استخدم واحدة من "
                                    f"{', '.join(AGGREGATES)}."))
            continue
        if agg == "count":
            checked.append({"agg": "count"})
            continue
        if agg == "ratio":
            parts = [item.get("numerator"), item.get("denominator")]
            bad = [p for p in parts if p not in table.numeric]
            for part in bad:
                problems.append(Problem("measures", part,
                                        f"A ratio needs two measure columns; “{part}” is not one.",
                                        f"النسبة تحتاج إلى عمودين من المقاييس؛ «{part}» ليس منها."))
            if not bad:
                checked.append({"agg": "ratio", "numerator": parts[0], "denominator": parts[1]})
            continue
        column = item.get("column")
        if column not in table.columns:
            problems.append(_unknown(column, "measures"))
            continue
        if agg in ("sum", "mean", "min", "max") and column not in table.numeric:
            problems.append(Problem("measures", column,
                                    f"“{agg}” needs a measure column; “{column}” holds text.",
                                    f"«{agg}» تحتاج إلى عمود مقياس؛ «{column}» يحمل نصاً."))
            continue
        checked.append({"agg": agg, "column": column})
    for item in checked:
        item["key"] = _measure_key(item)
    return checked


def _check_group_by(table, group_by, rows, problems):
    """Each grouping as (name, position, bins) where bins is None or
    (low, width, count) over the filtered values."""
    group_by = list(group_by or [])
    if len(group_by) > MAX_GROUP_BY:
        problems.append(Problem("group_by", None,
                                f"Group by at most {MAX_GROUP_BY} columns.",
                                f"التجميع على عمودين على الأكثر."))
        return []
    checked = []
    for item in group_by:
        column, bins = (item, None) if isinstance(item, str) else (
            (item or {}).get("column"), (item or {}).get("bins"))
        if column not in table.columns:
            problems.append(_unknown(column, "group_by"))
            continue
        position = table.index(column)
        if bins is None:
            checked.append({"name": column, "position": position, "bins": None})
            continue
        if column not in table.numeric or not isinstance(bins, int) or isinstance(bins, bool) \
                or not MIN_BINS <= bins <= MAX_BINS:
            problems.append(Problem("group_by", column,
                                    f"Bins need a measure column and {MIN_BINS} to {MAX_BINS} bins.",
                                    f"الفئات تحتاج إلى عمود مقياس ومن {MIN_BINS} إلى {MAX_BINS} فئة."))
            continue
        values = [row[position] for row in rows if isinstance(row[position], (int, float))]
        low = min(values) if values else 0.0
        high = max(values) if values else 0.0
        width = (high - low) / bins if high > low else 1.0
        checked.append({"name": column, "position": position,
                        "bins": (low, width, bins if high > low else 1)})
    return checked


def _key(row, grouping):
    value = row[grouping["position"]]
    if grouping["bins"] is None:
        return value
    if not isinstance(value, (int, float)):
        return None
    low, width, count = grouping["bins"]
    return min(int((value - low) / width), count - 1)


def _bin_label(index, bins):
    low, width, _ = bins
    start, end = low + index * width, low + (index + 1) * width
    return [round(start, 6), round(end, 6)]


def _sort_value(value):
    # None sorts last, numbers before text.
    if value is None:
        return (2, 0, "")
    if isinstance(value, (int, float)):
        return (0, value, "")
    return (1, 0, str(value))


def _sorted(items, value_of, descending):
    """Sorted by a value, with empty values last whichever the direction."""
    present = [i for i in items if value_of(i) not in (None, "")]
    missing = [i for i in items if value_of(i) in (None, "")]
    present.sort(key=lambda i: _sort_value(value_of(i)), reverse=descending)
    return present + missing


def aggregate(table, spec):
    """Totals by group under filters. Raises QueryError."""
    spec = spec or {}
    problems = []
    checked_filters = _check_filters(table, spec.get("filters"), problems)
    measures = _check_measures(table, spec.get("measures"), problems)
    limit = spec.get("limit", 100)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_GROUPS:
        problems.append(Problem("limit", None, f"The limit is 1 to {MAX_GROUPS} groups.",
                                f"الحد من 1 إلى {MAX_GROUPS} مجموعة."))
    if problems:
        raise QueryError(problems)
    rows = [row for row in table.rows if _passes(row, checked_filters)]
    groupings = _check_group_by(table, spec.get("group_by"), rows, problems)
    keys = [m["key"] for m in measures]
    sort = spec.get("sort") or {}
    sort_by = sort.get("by")
    if sort_by is not None and sort_by not in keys + [g["name"] for g in groupings]:
        problems.append(Problem("sort", sort_by,
                                f"Sort by a grouped column or a measure key ({', '.join(keys)}).",
                                f"رتّب حسب عمود مجمَّع أو مفتاح مقياس ({', '.join(keys)})."))
    if problems:
        raise QueryError(problems)

    positions = {}
    for measure in measures:
        for part in ("column", "numerator", "denominator"):
            if part in measure:
                positions[measure[part]] = table.index(measure[part])
    groups = {}
    for row in rows:
        key = tuple(_key(row, g) for g in groupings)
        slot = groups.get(key)
        if slot is None:
            slot = groups[key] = {"records": 0, "acc": [None] * len(measures)}
        slot["records"] += 1
        for index, measure in enumerate(measures):
            acc = slot["acc"][index]
            agg = measure["agg"]
            if agg == "count":
                continue
            if agg == "ratio":
                num = row[positions[measure["numerator"]]]
                den = row[positions[measure["denominator"]]]
                acc = acc or [0.0, 0.0]
                if isinstance(num, (int, float)) and isinstance(den, (int, float)):
                    acc[0] += num
                    acc[1] += den
                slot["acc"][index] = acc
                continue
            value = row[positions[measure["column"]]]
            if agg == "distinct":
                acc = acc if acc is not None else set()
                if value is not None and value != "":
                    acc.add(value)
            elif isinstance(value, (int, float)):
                if agg in ("sum", "mean"):
                    acc = acc or [0.0, 0]
                    acc[0] += value
                    acc[1] += 1
                elif agg == "min":
                    acc = value if acc is None else min(acc, value)
                else:
                    acc = value if acc is None else max(acc, value)
            slot["acc"][index] = acc

    def final(measure, acc, records):
        agg = measure["agg"]
        if agg == "count":
            return records
        if acc is None:
            return 0 if agg == "distinct" else None
        if agg == "sum":
            return round(acc[0], 6)
        if agg == "mean":
            return round(acc[0] / acc[1], 6) if acc[1] else None
        if agg == "distinct":
            return len(acc)
        if agg == "ratio":
            return round(acc[0] / acc[1], 6) if acc[1] else None
        return acc

    out = []
    for key, slot in groups.items():
        shown = [(_bin_label(k, g["bins"]) if g["bins"] is not None and k is not None else k)
                 for k, g in zip(key, groupings)]
        out.append({"keys": shown, "records": slot["records"],
                    "values": [final(m, acc, slot["records"])
                               for m, acc in zip(measures, slot["acc"])],
                    "_order": key})
    if sort_by is None:
        out.sort(key=lambda g: tuple(_sort_value(k) for k in g["_order"]))
    elif sort_by in keys:
        position = keys.index(sort_by)
        present = [g for g in out if g["values"][position] is not None]
        missing = [g for g in out if g["values"][position] is None]
        present.sort(key=lambda g: g["values"][position], reverse=bool(sort.get("desc")))
        out = present + missing
    else:
        position = [g["name"] for g in groupings].index(sort_by)
        out = _sorted(out, lambda g: g["_order"][position], bool(sort.get("desc")))
    for group in out:
        group.pop("_order")
    return {"group_by": [{"column": g["name"], "binned": g["bins"] is not None}
                         for g in groupings],
            "measures": measures, "groups": out[:limit], "group_count": len(out),
            "truncated": len(out) > limit, "matched_records": len(rows),
            "records": len(table.rows)}


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def records(table, spec):
    """A page of the rows behind a figure, or an even sample of them."""
    spec = spec or {}
    problems = []
    checked = _check_filters(table, spec.get("filters"), problems)
    offset, limit, sample = spec.get("offset", 0), spec.get("limit", 50), spec.get("sample")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        problems.append(Problem("offset", None, "The offset is a whole number from 0.",
                                "الإزاحة عدد صحيح يبدأ من 0."))
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE:
        problems.append(Problem("limit", None, f"A page holds 1 to {MAX_PAGE} rows.",
                                f"الصفحة تحمل من 1 إلى {MAX_PAGE} صف."))
    if sample is not None and (not isinstance(sample, int) or isinstance(sample, bool)
                               or not 1 <= sample <= MAX_SAMPLE):
        problems.append(Problem("sample", None, f"A sample holds 1 to {MAX_SAMPLE} rows.",
                                f"العينة تحمل من 1 إلى {MAX_SAMPLE} صف."))
    sort = spec.get("sort") or {}
    if sort.get("by") is not None and sort["by"] not in table.columns:
        problems.append(_unknown(sort["by"], "sort"))
    if problems:
        raise QueryError(problems)
    rows = [row for row in table.rows if _passes(row, checked)]
    if sort.get("by") is not None:
        position = table.index(sort["by"])
        rows = _sorted(rows, lambda r: r[position], bool(sort.get("desc")))
    total = len(rows)
    if sample is not None:
        step = max(total / sample, 1.0)
        picked = [rows[int(i * step)] for i in range(min(sample, total))]
        return {"columns": table.columns, "rows": [list(r) for r in picked],
                "total": total, "sampled": len(picked) < total}
    return {"columns": table.columns, "rows": [list(r) for r in rows[offset:offset + limit]],
            "total": total, "offset": offset, "limit": limit}
