"""Column mapping: the owner says what each column is (ADR 0025).

A run used to guess its measure, its breakdown and its time axis from
column names. This module holds everything that replaces the guess when a
mapping exists: reading numbers and dates the way the owner declared them,
profiling columns for the interface, suggesting a mapping with a reason for
each column, and validating a mapping against every row before it is saved.

Standard library only. Messages come in English and Arabic, because the
person reading a refusal is the person who has to fix the mapping.
"""

import calendar
import csv
import io
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

ROLES = ("measure", "dimension", "date", "ignore")
DATE_ORDERS = ("auto", "day-first", "month-first")
GRAINS = ("auto", "day", "month", "quarter", "year")
FINEST_FIRST = ("day", "month", "quarter", "year")
MAPPING_VERSION = 1

# A trend over more periods than this is rolled up (day to month to quarter
# to year) when the grain is "auto": three years of months fit, a year of
# days does not.
MAX_AUTO_PERIODS = 36
# Validation: a mapped measure or date must read in at least half of its
# filled cells. A suggestion is stricter, because it is a guess.
MIN_READABLE_SHARE = 0.5
SUGGEST_SHARE = 0.9
PREVIEW_ROWS = 5
EXAMPLES = 3
# The profile and suggestion read an evenly spaced sample of this many rows.
# A suggestion is a guess either way, and the whole table costs seconds at
# the 50,000-row limit. Validation always reads every row.
PROFILE_SAMPLE = 10_000

# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# Longest first, so "ر.س" is removed whole rather than leaving "ر.".
CURRENCY = re.compile(r"(?:ر\.س|د\.إ|ج\.م|\b(?:usd|eur|gbp|sar|aed|egp|kwd|qar|omr|bhd)\b|[$€£¥₹﷼])",
                      re.IGNORECASE)
SPACES = re.compile(r"[   ]")
PLAIN_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
# Separators are read only where they group thousands. "12,5" is a decimal
# comma in much of the world and 125 in the rest, so it is refused, not
# guessed: a refused value is counted and reported, a misread one is not.
GROUPED = re.compile(r"[+-]?\d{1,3}(?:([, ])\d{3})(?:\1\d{3})*(?:\.\d+)?")


def parse_number(value):
    """A number from a cell the owner says is a number, or None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if PLAIN_NUMBER.fullmatch(text):
        return float(text)  # the common case, answered without the rest
    text = text.translate(DIGITS)
    text = text.replace("٫", ".").replace("٬", ",").replace("−", "-")
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    text = CURRENCY.sub("", text).strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    text = SPACES.sub(" ", text).strip()
    if "," in text or " " in text:
        if not GROUPED.fullmatch(text):
            return None
        text = text.replace(",", "").replace(" ", "")
    if not PLAIN_NUMBER.fullmatch(text):
        return None
    number = float(text)
    return -number if negative else number


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

MONTHS = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): index for index, name in enumerate(calendar.month_abbr) if name})
MONTHS.update({"sept": 9})
MONTHS.update({name: index for index, names in enumerate((
    (), ("يناير", "كانون الثاني"), ("فبراير", "شباط"), ("مارس", "آذار"),
    ("أبريل", "ابريل", "إبريل", "نيسان"), ("مايو", "أيار", "ايار"),
    ("يونيو", "يونيه", "حزيران"), ("يوليو", "يوليه", "تموز"), ("أغسطس", "اغسطس", "آب"),
    ("سبتمبر", "أيلول", "ايلول"), ("أكتوبر", "اكتوبر", "تشرين الأول"),
    ("نوفمبر", "تشرين الثاني"), ("ديسمبر", "كانون الأول"))) for name in names})

ISO_DAY = re.compile(r"(\d{4})([-/.])(\d{1,2})\2(\d{1,2})(?:[ t]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:z|[+-]\d{2}:?\d{2})?)?")
# A dot is not a month separator: "2025.03" is far more often a number.
ISO_MONTH = re.compile(r"(\d{4})[-/](\d{1,2})")
MONTH_YEAR = re.compile(r"(\d{1,2})[-/](\d{4})")
YEAR = re.compile(r"(\d{4})")
QUARTER = re.compile(r"(?:(\d{4})\s*[-/ ]?\s*q([1-4])|q([1-4])\s*[-/ ]?\s*(\d{4}))")
NUMERIC_DAY = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})(?:[ t]\d{1,2}:\d{2}(?::\d{2})?)?")
PLAIN_DECIMAL = re.compile(r"[+-]?\d+(?:\.\d+)?")
DATE_NAME_WORDS = ("date", "month", "period", "week", "year", "day", "time", "quarter",
                   "تاريخ", "التاريخ", "شهر", "سنة", "السنة", "فترة", "ربع")


@dataclass(frozen=True)
class Period:
    year: int
    month: int = None
    day: int = None
    quarter: int = None
    precision: str = "day"

    def label(self, grain):
        """This period as a sortable label at a grain, or None when the
        value is coarser than the grain (a year cannot be put in a month)."""
        if FINEST_FIRST.index(self.precision) > FINEST_FIRST.index(grain):
            return None
        if grain == "day":
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        if grain == "month":
            return f"{self.year:04d}-{self.month:02d}"
        if grain == "quarter":
            quarter = self.quarter or (self.month - 1) // 3 + 1
            return f"{self.year:04d}-Q{quarter}"
        return f"{self.year:04d}"


def _year(text):
    year = int(text)
    if len(text) == 2:
        # POSIX's rule for two-digit years: 69 and below are this century.
        year += 2000 if year <= 68 else 1900
    return year


def _plausible(year):
    return 1800 <= year <= 2200


def _month(year, month):
    if not (_plausible(year) and 1 <= month <= 12):
        return None
    return Period(year, month, precision="month")


def _day(year, month, day):
    if not _plausible(year):
        return None
    try:
        date(year, month, day)
    except ValueError:
        return None
    return Period(year, month, day, precision="day")


def _plain(text):
    return text.strip().translate(DIGITS).lower().replace("،", ",")


def _named_month(text):
    """'Jan 2025', '15 January 2025', 'January 15, 2025', 'يناير 2025'."""
    tokens = [t for t in re.split(r"[\s,\-/.]+", text) if t]
    joined = " ".join(tokens)
    month = None
    for name in sorted(MONTHS, key=len, reverse=True):
        if " " in name and name in joined:
            month = MONTHS[name]
            tokens = [t for t in re.split(r"[\s,\-/.]+", joined.replace(name, " ")) if t]
            break
    if month is None:
        named = [t for t in tokens if t in MONTHS]
        if len(named) != 1:
            return None
        month = MONTHS[named[0]]
        tokens = [t for t in tokens if t not in MONTHS]
    if not all(t.isdigit() for t in tokens):
        return None
    if len(tokens) == 1:
        if len(tokens[0]) not in (2, 4):
            return None
        return _month(_year(tokens[0]), month)
    if len(tokens) == 2:
        if len(tokens[0]) == 4 and len(tokens[1]) != 4:
            year, day = tokens
        elif len(tokens[1]) == 4 and len(tokens[0]) != 4:
            day, year = tokens
        else:
            day, year = tokens
        if len(day) > 2:
            return None
        return _day(_year(year), month, int(day))
    return None


def parse_date(value, order="day-first"):
    """A Period from one cell, or None. `order` settles 03/04/2025 and is
    never "auto" here: read_dates decides it for a whole column."""
    text = _plain(str(value or ""))
    if not text or (PLAIN_DECIMAL.fullmatch(text) and len(text) != 4):
        # Most cells in a numeric column: answered without trying dates.
        return None
    if match := ISO_DAY.fullmatch(text):
        return _day(int(match[1]), int(match[3]), int(match[4]))
    if match := ISO_MONTH.fullmatch(text) or MONTH_YEAR.fullmatch(text):
        year, month = (match[1], match[2]) if len(match[1]) == 4 else (match[2], match[1])
        return _month(int(year), int(month))
    if match := QUARTER.fullmatch(text):
        year, quarter = (match[1], match[2]) if match[1] else (match[4], match[3])
        return Period(int(year), quarter=int(quarter), precision="quarter") if _plausible(int(year)) else None
    if match := YEAR.fullmatch(text):
        year = int(match[1])
        return Period(year, precision="year") if _plausible(year) else None
    if match := NUMERIC_DAY.fullmatch(text):
        first, second = int(match[1]), int(match[2])
        day, month = (first, second) if order == "day-first" else (second, first)
        if not 1 <= month <= 12:
            return None
        return _day(_year(match[3]), month, day)
    if re.search(r"[a-z؀-ۿ]", text):
        return _named_month(text)
    return None


def resolve_order(values, order="auto"):
    """How a column writes day and month: (order, ambiguous).

    A value whose first part is over 12 proves day-first; one whose second
    part is over 12 proves month-first. With no proof either way and at
    least one value where the readings differ, the column is ambiguous and
    the owner is asked: 03/04/2025 is 3 April or 4 March, and a wrong guess
    moves every figure into the wrong month without an error.
    """
    if order != "auto":
        return order, False
    day_first = month_first = differs = 0
    for value in values:
        match = NUMERIC_DAY.fullmatch(_plain(str(value or "")))
        if not match:
            continue
        first, second = int(match[1]), int(match[2])
        day_first += first > 12 >= second
        month_first += second > 12 >= first
        differs += first != second and first <= 12 and second <= 12
    if day_first and not month_first:
        return "day-first", False
    if month_first and not day_first:
        return "month-first", False
    if day_first and month_first:
        # Both proofs: the column mixes conventions. The larger side wins,
        # and the values of the other side will not read and are counted.
        return ("day-first" if day_first >= month_first else "month-first"), False
    return "day-first", bool(differs)


def read_dates(values, order="auto"):
    """(periods aligned with values, the order used, ambiguous)."""
    resolved, ambiguous = resolve_order(values, order)
    return [parse_date(v, resolved) for v in values], resolved, ambiguous


def choose_grain(periods, grain="auto"):
    """The grain a trend uses. "auto" is the finest grain that nine in ten
    readable values reach, rolled up until there are at most
    MAX_AUTO_PERIODS periods."""
    readable = [p for p in periods if p is not None]
    if grain != "auto":
        return grain
    if not readable:
        return "month"
    for index, candidate in enumerate(FINEST_FIRST):
        fits = sum(1 for p in readable if p.label(candidate) is not None)
        if fits >= SUGGEST_SHARE * len(readable):
            break
    for candidate in FINEST_FIRST[index:]:
        if len({p.label(candidate) for p in readable} - {None}) <= MAX_AUTO_PERIODS:
            return candidate
    return "year"


def period_labels(values, order="auto", grain="auto"):
    """Labels for a date column at a grain: (labels with None for a value
    that does not read, the grain used, the order used)."""
    periods, resolved, _ = read_dates(values, order)
    used = choose_grain(periods, grain)
    return [p.label(used) if p else None for p in periods], used, resolved


def next_period_labels(last, count):
    """Continue a calendar from its last label, or None if it is not one
    of the labels this module writes."""
    text = str(last)
    out = []
    if match := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
        current = date(int(match[1]), int(match[2]), int(match[3]))
        for step in range(1, count + 1):
            out.append(date.fromordinal(current.toordinal() + step).isoformat())
        return out
    if match := re.fullmatch(r"(\d{4})-Q([1-4])", text):
        year, quarter = int(match[1]), int(match[2])
        for _ in range(count):
            quarter += 1
            if quarter > 4:
                quarter, year = 1, year + 1
            out.append(f"{year:04d}-Q{quarter}")
        return out
    if re.fullmatch(r"\d{4}", text):
        return [f"{int(text) + step:04d}" for step in range(1, count + 1)]
    return None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@dataclass
class Problem:
    field: str
    column: str
    en: str
    ar: str

    def as_dict(self, language="en"):
        return {"field": self.field, "column": self.column,
                "message": self.ar if language == "ar" else self.en}


class MappingError(Exception):
    """A mapping that cannot be saved, with every reason at once."""

    def __init__(self, problems):
        super().__init__(problems[0].en)
        self.problems = problems

    def detail(self, language="en"):
        count = len(self.problems)
        if language == "ar":
            many = ("مشكلة واحدة" if count == 1 else "مشكلتان" if count == 2
                    else f"{count} مشكلات" if count <= 10 else f"{count} مشكلة")
            summary = f"لم يُحفظ الربط: {many} تحتاج إلى إصلاح."
        else:
            summary = f"The mapping was not saved: {count} problem{'s' if count != 1 else ''} to fix."
        return {"message": summary,
                "errors": [p.as_dict(language) for p in self.problems]}


# ---------------------------------------------------------------------------
# Profile and suggestion
# ---------------------------------------------------------------------------

def _cells(rows, column):
    return [str(row.get(column) or "").strip() for row in rows]


def _named_like_a_date(column):
    lowered = column.lower()
    return any(word in lowered for word in DATE_NAME_WORDS)


def _named_like_an_id(column):
    lowered = column.lower().replace(" ", "_").replace("-", "_")
    camel = len(column) > 2 and column.endswith("Id") and column[-3].islower()
    return camel or lowered in ("id", "code", "key") or lowered.endswith(
        ("_id", "_code", "_key", "_no", "_number", "_centre", "_center"))


def _personal_columns(columns, rows):
    """Columns the Privacy Agent would flag, by name or by value (ADR 0027)."""
    from server.analytics import personal_data_findings  # imported late: analytics imports this module
    return {f["column"] for f in personal_data_findings(columns, rows)}


def table(text):
    """(columns, rows) of canonical CSV, read exactly as the collector
    reads it, so a mapping names the columns a run will see."""
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return [c for c in (reader.fieldnames or []) if c], rows


def sample(rows, size=PROFILE_SAMPLE):
    """Every k-th row, so a sample spans the table rather than its start."""
    if len(rows) <= size:
        return rows
    step = len(rows) / size
    return [rows[int(i * step)] for i in range(size)]


def profile(columns, rows):
    """What each column holds, for the interface and the suggestion.
    Pass sample(rows) for a large table."""
    out = []
    for column in columns:
        cells = _cells(rows, column)
        filled = [c for c in cells if c]
        # Each distinct value is read once: dates and categories repeat,
        # and 50,000 rows of 60 columns must profile in about a second.
        counts = Counter(filled)
        numbers = {value: parse_number(value) for value in counts}
        numeric = sum(n for value, n in counts.items() if numbers[value] is not None)
        dated = 0
        for value, n in counts.items():
            if parse_date(value, "day-first") or (
                    NUMERIC_DAY.fullmatch(_plain(value)) and parse_date(value, "month-first")):
                dated += n
        ambiguous = resolve_order(counts)[1] if dated else False
        examples = list(counts)[:EXAMPLES]
        share_n = numeric / len(filled) if filled else 0.0
        share_d = dated / len(filled) if filled else 0.0
        if not filled:
            kind = "empty"
        elif share_d >= SUGGEST_SHARE and (share_n < SUGGEST_SHARE or _named_like_a_date(column)):
            kind = "date"
        elif share_n >= SUGGEST_SHARE:
            kind = "number"
        elif _named_like_a_date(column) and share_d >= MIN_READABLE_SHARE:
            kind = "date"
        else:
            kind = "text"
        whole = bool(filled) and all(n is not None and float(n).is_integer()
                                     for n in numbers.values())
        # Currency signs or grouped digits mean an amount, never an ID.
        formatted = any(n is not None and not PLAIN_NUMBER.fullmatch(value)
                        for value, n in numbers.items())
        readable = [n for n in numbers.values() if n is not None]
        sequence = bool(readable) and whole and (
            max(readable) - min(readable) + 1 <= 2 * len(readable))
        out.append({"name": column, "type": kind, "filled": len(filled), "cells": len(cells),
                    "numeric_share": round(share_n, 4), "date_share": round(share_d, 4),
                    "distinct": len(set(filled)), "examples": examples,
                    "ambiguous_order": bool(ambiguous and kind == "date"),
                    "whole_numbers": whole, "formatted": formatted,
                    "sequence": sequence})
    return out


REASONS = {
    "date": ("Reads as dates in {share} of filled cells.",
             "تُقرأ تواريخَ في {share} من الخلايا المعبأة."),
    "second_date": ("Also reads as dates, but a run has one time axis.",
                    "تُقرأ تواريخَ أيضاً، لكن للتشغيل محور زمني واحد."),
    "measure": ("Numbers in {share} of filled cells.",
                "أرقام في {share} من الخلايا المعبأة."),
    "identifier": ("A whole number unique in every row, counting up: it looks like an identifier.",
                   "رقم صحيح لا يتكرر في أي صف ويتزايد بانتظام: يبدو معرّفاً."),
    "coded_dimension": ("Numbered like a code and repeated, so it groups rows.",
                        "رقم يشبه الرمز ويتكرر، فهو يجمّع الصفوف."),
    "dimension": ("Text with {distinct} distinct values.",
                  "نص فيه {distinct} من القيم المختلفة."),
    "unique_text": ("Nearly every value is different, like names or notes.",
                    "كل قيمة تقريباً مختلفة، مثل الأسماء أو الملاحظات."),
    "personal": ("Looks like personal data, by its name or its values, so it is left out of the analysis.",
                 "يبدو بيانات شخصية، من اسمه أو من قيمه، فيُستبعد من التحليل."),
    "year": ("Years, kept as a breakdown beside the time axis.",
             "سنوات، تُستخدم تقسيماً إلى جانب المحور الزمني."),
    "empty": ("Every cell is empty.", "كل الخلايا فارغة."),
}


def _reason(key, **values):
    en, ar = REASONS[key]
    return {"code": key, "en": en.format(**values), "ar": ar.format(**values)}


def suggest(columns, rows, metrics=(), profiles=None):
    """A mapping with a reason for each column. Never saved by itself."""
    from server import metrics as glossary
    profiles = profiles or profile(columns, rows)
    roles, reasons, date_column = {}, {}, None
    personal = _personal_columns(columns, rows)
    for p in profiles:
        name, kind = p["name"], p["type"]
        share = f"{max(p['numeric_share'], p['date_share']):.0%}"
        if kind == "empty":
            roles[name], reasons[name] = "ignore", _reason("empty")
        elif name in personal:
            roles[name], reasons[name] = "ignore", _reason("personal")
        elif kind == "date":
            if date_column is None:
                date_column = name
                roles[name], reasons[name] = "date", _reason("date", share=f"{p['date_share']:.0%}")
            elif p["examples"] and all(re.fullmatch(r"(19|20)\d{2}", _plain(v)) for v in p["examples"]):
                roles[name], reasons[name] = "dimension", _reason("year")
            else:
                roles[name], reasons[name] = "ignore", _reason("second_date")
        elif kind == "number":
            unique = p["distinct"] == p["filled"] and p["filled"] >= 10
            code_like = p["whole_numbers"] and not p["formatted"]
            if code_like and unique and (p["sequence"] or _named_like_an_id(name)):
                roles[name], reasons[name] = "ignore", _reason("identifier")
            elif code_like and not unique and _named_like_an_id(name):
                roles[name], reasons[name] = "dimension", _reason("coded_dimension")
            else:
                roles[name], reasons[name] = "measure", _reason("measure", share=share)
        elif p["distinct"] == p["filled"] and p["filled"] >= 10:
            roles[name], reasons[name] = "ignore", _reason("unique_text")
        elif p["distinct"] <= 50 or p["distinct"] <= 0.5 * p["filled"]:
            roles[name], reasons[name] = "dimension", _reason("dimension", distinct=p["distinct"])
        else:
            roles[name], reasons[name] = "ignore", _reason("unique_text")
    measures = [c for c in columns if roles.get(c) == "measure"]
    measure = glossary.resolve(list(metrics), columns, measures)[0] if measures else None
    dimension = next((c for c in columns if roles.get(c) == "dimension"), None)
    return {"version": MAPPING_VERSION, "roles": roles, "measure": measure,
            "dimension": dimension, "date_order": "auto", "grain": "auto",
            "reasons": reasons}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

ROLE_NAMES_AR = {"measure": "مقياس", "dimension": "بُعد", "date": "تاريخ", "ignore": "مستبعد"}


def validate(mapping, columns, rows):
    """The mapping as it will be saved, or MappingError with every problem.

    Checked against every row, not the preview: a measure that is numeric
    in the first five rows and text in the next five thousand is exactly
    the mistake a preview hides.
    """
    problems = []
    mapping = mapping or {}
    roles = mapping.get("roles") or {}
    if not isinstance(roles, dict):
        roles = {}
    for column in roles:
        if column not in columns:
            problems.append(Problem("roles", column,
                                    f"“{column}” is not a column of this dataset.",
                                    f"«{column}» ليس عموداً في هذه البيانات."))
    for column in columns:
        role = roles.get(column)
        if role is None:
            problems.append(Problem("roles", column,
                                    f"Choose a role for “{column}”.",
                                    f"اختر دوراً للعمود «{column}»."))
        elif role not in ROLES:
            problems.append(Problem("roles", column,
                                    f"“{role}” is not a role. Choose measure, dimension, date or ignore.",
                                    f"«{role}» ليس دوراً. اختر مقياساً أو بُعداً أو تاريخاً أو مستبعداً."))
    order = mapping.get("date_order") or "auto"
    grain = mapping.get("grain") or "auto"
    if order not in DATE_ORDERS:
        problems.append(Problem("date_order", None, "Choose how dates write day and month.",
                                "اختر كيف تُكتب التواريخ اليوم والشهر."))
        order = "auto"
    if grain not in GRAINS:
        problems.append(Problem("grain", None, "Choose day, month, quarter or year as the period.",
                                "اختر اليوم أو الشهر أو الربع أو السنة فترةً زمنية."))
        grain = "auto"

    measures = [c for c in columns if roles.get(c) == "measure"]
    dates = [c for c in columns if roles.get(c) == "date"]
    measure, dimension = mapping.get("measure"), mapping.get("dimension")
    if not measures:
        problems.append(Problem("measure", None,
                                "Map at least one column as a measure: the number the analysis is about.",
                                "اربط عموداً واحداً على الأقل بوصفه مقياساً: الرقم الذي يدور حوله التحليل."))
    elif measure not in measures:
        problems.append(Problem("measure", measure,
                                "Choose which measure the analysis is about.",
                                "اختر المقياس الذي يدور حوله التحليل."))
    if dimension is not None and roles.get(dimension) != "dimension":
        problems.append(Problem("dimension", dimension,
                                "The breakdown must be a column mapped as a dimension.",
                                "يجب أن يكون التقسيم عموداً مربوطاً بوصفه بُعداً."))
    if len(dates) > 1:
        for column in dates[1:]:
            problems.append(Problem("roles", column,
                                    f"Only one column can be the date; “{dates[0]}” already is.",
                                    f"يمكن أن يكون عمود واحد فقط هو التاريخ، و«{dates[0]}» هو التاريخ بالفعل."))

    for column in measures:
        filled = [c for c in _cells(rows, column) if c]
        readable = sum(1 for c in filled if parse_number(c) is not None)
        if not filled or readable < MIN_READABLE_SHARE * len(filled):
            problems.append(Problem(
                "roles", column,
                f"“{column}” cannot be a measure: {readable:,} of {len(filled):,} filled cells are numbers.",
                f"لا يصلح «{column}» مقياساً: {readable:,} فقط من {len(filled):,} خلية معبأة أرقام."))

    resolved = None
    if dates:
        column = dates[0]
        filled = [c for c in _cells(rows, column) if c]
        periods, resolved, ambiguous = read_dates(filled, order)
        if ambiguous:
            example = next(c for c in filled if NUMERIC_DAY.fullmatch(_plain(c)))
            problems.append(Problem(
                "date_order", column,
                f"“{column}” writes dates like {example}, which could be day first or month first. Choose one.",
                f"يكتب «{column}» التواريخ بصيغة مثل {example}، وقد يكون اليوم أولاً أو الشهر أولاً. اختر واحدة."))
        else:
            used = choose_grain(periods, grain)
            readable = sum(1 for p in periods if p is not None and p.label(used) is not None)
            if not filled or readable < MIN_READABLE_SHARE * len(filled):
                grain_names = {"day": ("day", "اليوم"), "month": ("month", "الشهر"),
                               "quarter": ("quarter", "الربع"), "year": ("year", "السنة")}
                en_g, ar_g = grain_names[used]
                problems.append(Problem(
                    "roles" if grain == "auto" else "grain", column,
                    f"“{column}” cannot be the date by {en_g}: {readable:,} of {len(filled):,} filled cells read as dates at that grain.",
                    f"لا يصلح «{column}» تاريخاً على مستوى {ar_g}: {readable:,} فقط من {len(filled):,} خلية معبأة تُقرأ تواريخَ بهذا المستوى."))

    if problems:
        raise MappingError(problems)
    return {"version": MAPPING_VERSION,
            "roles": {c: roles[c] for c in columns},
            "measure": measure, "dimension": dimension,
            "date_order": order, "grain": grain}


def measures_of(mapping, columns):
    return [c for c in columns if mapping["roles"].get(c) == "measure"]


def date_of(mapping, columns):
    return next((c for c in columns if mapping["roles"].get(c) == "date"), None)


def dimensions_of(mapping, columns):
    return [c for c in columns if mapping["roles"].get(c) == "dimension"]


def describe(mapping, columns, language="en"):
    """One line for a report: what the owner mapped."""
    counts = Counter(mapping["roles"].get(c) for c in columns)
    date_column = date_of(mapping, columns)
    if language == "ar":
        parts = [f"المقياس «{mapping['measure']}»"]
        if mapping.get("dimension"):
            parts.append(f"التقسيم «{mapping['dimension']}»")
        if date_column:
            parts.append(f"التاريخ «{date_column}»")
        if counts["ignore"]:
            parts.append(f"والمستبعد {counts['ignore']}")
        return "ربط الأعمدة الذي حفظه المالك: " + "، ".join(parts) + "."
    parts = [f"measure “{mapping['measure']}”"]
    if mapping.get("dimension"):
        parts.append(f"breakdown “{mapping['dimension']}”")
    if date_column:
        parts.append(f"date “{date_column}”")
    if counts["ignore"]:
        parts.append(f"{counts['ignore']} ignored")
    return "Column mapping saved by the owner: " + ", ".join(parts) + "."
