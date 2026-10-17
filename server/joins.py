"""Several datasets in one run (ADR 0030): what a join declares, how a
joined table is cleaned, and the merge itself.

A join is the easiest way to change a total without noticing, so this
module refuses rather than guesses:

- a lookup whose key repeats is refused, because it would count the
  matching records more than once;
- a joined column whose name is taken is renamed, never overwritten;
- every join reports how many rows it matched, kept and left out.

Everything here is a pure function of the tables it is given. The Data
Merge Agent (`analytics.merge`) and the preview endpoint both call it, so
a preview and the run it describes cannot disagree.
"""

import re
from collections import Counter
from dataclasses import dataclass

from server import mapping as colmap

MAX_JOINS = 4
MAX_KEYS = 3
HOWS = ("left", "inner")
# The same ceiling one dataset has (server/datasets.py, ADR 0024).
MAX_MERGED_COLUMNS = 500
UNMATCHED_EXAMPLES = 5
DUPLICATE_EXAMPLES = 3
# The 90% rule the Data Profiling Agent applies to unmapped data.
NUMERIC_SHARE = 0.9
ALIAS = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
# Rows kept as text for the personal-data screen, which reads at most
# this many (analytics.personal_data_findings).
SCREENED_ROWS = 2000


@dataclass
class Problem:
    """One reason a join cannot be made, said in both languages."""
    field: str
    column: str | None
    en: str
    ar: str
    join: int | None = None

    def as_dict(self, language="en"):
        return {"field": self.field, "column": self.column, "join": self.join,
                "message": self.ar if language == "ar" else self.en}


class JoinError(Exception):
    """A join declaration that cannot run, with every reason at once."""

    def __init__(self, problems):
        super().__init__(problems[0].en)
        self.problems = problems

    def message(self, language="en"):
        return "; ".join(p.ar if language == "ar" else p.en for p in self.problems)

    def detail(self, language="en"):
        count = len(self.problems)
        if language == "ar":
            many = ("مشكلة واحدة" if count == 1 else "مشكلتان" if count == 2
                    else f"{count} مشكلات" if count <= 10 else f"{count} مشكلة")
            summary = f"لا يمكن دمج البيانات: {many} تحتاج إلى إصلاح."
        else:
            summary = (f"The datasets cannot be merged: {count} problem"
                       f"{'s' if count != 1 else ''} to fix.")
        return {"message": summary,
                "errors": [p.as_dict(language) for p in self.problems]}


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------

def default_alias(name):
    """A file name as a column prefix: `Regional Targets.xlsx` → `regional_targets`."""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", str(name or "")).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    if not slug or not slug[0].isalpha():
        slug = "joined_" + slug if slug else "joined"
    return slug[:24].rstrip("_") or "joined"


def normalise(joins, breakdown=None):
    """The declaration a run keeps: checked for shape, nothing loaded.

    `joins` is a list of {dataset_id, keys: [{left, right}], how, alias};
    names are checked against real columns later, by `merge`."""
    problems = []
    joins = list(joins or [])
    if not joins:
        problems.append(Problem("joins", None, "Name at least one dataset to join.",
                                "حدد مجموعة بيانات واحدة على الأقل للدمج."))
    if len(joins) > MAX_JOINS:
        problems.append(Problem(
            "joins", None,
            f"A run can join at most {MAX_JOINS} other datasets; {len(joins)} were given.",
            f"يمكن أن يدمج التشغيل {MAX_JOINS} مجموعات بيانات أخرى على الأكثر، "
            f"وحُدد {len(joins)}."))
    clean = []
    for index, item in enumerate(joins[:MAX_JOINS]):
        item = dict(item or {})
        dataset_id = str(item.get("dataset_id") or "").strip()
        if not dataset_id:
            problems.append(Problem("joins", None, f"Join {index + 1} names no dataset.",
                                    f"الدمج رقم {index + 1} لا يحدد مجموعة بيانات.",
                                    index))
        how = item.get("how") or "left"
        if how not in HOWS:
            problems.append(Problem(
                "how", None,
                f"Join {index + 1}: “{how}” is not a join type; use left or inner.",
                f"الدمج رقم {index + 1}: «{how}» ليس نوع دمج؛ استخدم left أو inner.",
                index))
        keys = []
        for pair in item.get("keys") or []:
            left = str((pair or {}).get("left") or "").strip()
            right = str((pair or {}).get("right") or "").strip()
            if left and right:
                keys.append({"left": left, "right": right})
        if not keys:
            problems.append(Problem(
                "keys", None,
                f"Join {index + 1} needs a key: a column of the main table and the "
                "column of the joined dataset that holds the same values.",
                f"الدمج رقم {index + 1} يحتاج إلى مفتاح: عمود من الجدول الرئيسي "
                "والعمود الذي يحمل القيم نفسها في البيانات المدمجة.", index))
        elif len(keys) > MAX_KEYS:
            problems.append(Problem(
                "keys", None,
                f"Join {index + 1} has {len(keys)} key pairs; the limit is {MAX_KEYS}.",
                f"الدمج رقم {index + 1} فيه {len(keys)} أزواج مفاتيح، والحد {MAX_KEYS}.",
                index))
        alias = item.get("alias")
        if alias is not None:
            alias = str(alias).strip().lower() or None
            if alias is not None and not ALIAS.match(alias):
                problems.append(Problem(
                    "alias", None,
                    f"Join {index + 1}: the prefix “{alias}” must start with a letter "
                    "and use only lowercase letters, digits and underscores (24 at most).",
                    f"الدمج رقم {index + 1}: البادئة «{alias}» يجب أن تبدأ بحرف وأن "
                    "تتكون من حروف إنجليزية صغيرة وأرقام وشرطات سفلية (24 على الأكثر).",
                    index))
        clean.append({"dataset_id": dataset_id, "how": how, "keys": keys,
                      "alias": alias})
    if problems:
        raise JoinError(problems)
    breakdown = str(breakdown).strip() if breakdown else None
    return {"joins": clean, "breakdown": breakdown or None}


def assign_aliases(joins, names):
    """Fill each join's prefix from its dataset's name and make them unique.
    `names` holds each join's dataset name, in order."""
    taken = set()
    for join, name in zip(joins, names):
        alias = join.get("alias") or default_alias(name)
        base, suffix = alias, 2
        while alias in taken:
            alias = f"{base[:21]}_{suffix}"
            suffix += 1
        taken.add(alias)
        join["alias"] = alias
    return joins


# ---------------------------------------------------------------------------
# Cleaning a joined table, the way the main one is cleaned
# ---------------------------------------------------------------------------

def _plain_number(value):
    """The unmapped reading of a number (analytics._to_number)."""
    try:
        return float(value.replace(",", "")) if isinstance(value, str) else float(value)
    except (ValueError, AttributeError, TypeError):
        return None


@dataclass
class Table:
    columns: list
    rows: list
    numeric: list
    rows_before: int
    dropped_empty: int
    dropped_duplicates: int
    screened: list


def clean_table(text, mapping=None):
    """A joined dataset as the main one would be after cleaning: cells
    trimmed, empty and exact-duplicate rows removed, measures as numbers.

    With a mapping, its measures are the numbers (ADR 0025); without one,
    a column is numeric when 90% of its filled cells read as numbers, the
    rule the Data Profiling Agent uses."""
    columns, raw = colmap.table(text)
    cleaned, seen, empty, duplicates = [], set(), 0, 0
    for row in raw:
        stripped = {c: (str(row.get(c)).strip() if row.get(c) is not None else "")
                    for c in columns}
        if not any(stripped.values()):
            empty += 1
            continue
        key = tuple(stripped[c] for c in columns)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        cleaned.append(stripped)
    screened = [dict(row) for row in cleaned[:SCREENED_ROWS]]
    if mapping:
        numeric = colmap.measures_of(mapping, columns)
        read = colmap.parse_number
    else:
        numeric, read = [], _plain_number
        for column in columns:
            filled = [row[column] for row in cleaned if row[column]]
            numbers = sum(1 for value in filled if _plain_number(value) is not None)
            if filled and numbers >= max(1, len(filled) * NUMERIC_SHARE):
                numeric.append(column)
    for row in cleaned:
        for column in numeric:
            row[column] = read(row[column]) if row[column] else None
    return Table(columns, cleaned, numeric, len(raw), empty, duplicates, screened)


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

def key_text(value, numeric):
    """A key value as it is compared. Numbers compare as numbers, so 3,
    3.0 and "003" are one key; everything else as trimmed text."""
    if value is None:
        return None
    if numeric:
        if isinstance(value, bool):
            return None
        number = value if isinstance(value, (int, float)) else colmap.parse_number(str(value))
        if number is None:
            return None
        number = float(number)
        return str(int(number)) if number.is_integer() else format(number, ".15g")
    text = str(value).strip()
    return text or None


def _quoted(keys):
    return ", ".join("/".join(str(part) for part in key) for key in keys)


# ---------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------

def merge(columns, rows, numeric, joined, date=None):
    """Join each table in `joined` onto `rows`, in order.

    `joined` holds dicts with `table` (a Table), `keys`, `how`, `alias`,
    `name`, `dataset_id` and `snapshot`. `date` is the main dataset's
    mapped date as the cleaner left it ({column, order, grain}), so a key
    on it can read the joined dates at the same grain.

    Returns the merged columns, rows and numeric columns, and one record
    per join of what it did. Raises JoinError when a join cannot be made
    without changing what the rows count."""
    columns, numeric, rows = list(columns), list(numeric), rows
    problems, records = [], []
    for index, item in enumerate(joined):
        table, keys, how = item["table"], item["keys"], item["how"]
        name, alias = item["name"], item["alias"]
        missing = [k["left"] for k in keys if k["left"] not in columns]
        missing_right = [k["right"] for k in keys if k["right"] not in table.columns]
        for column in missing:
            problems.append(Problem(
                "keys", column,
                f"Join {index + 1}: the main table has no column “{column}”.",
                f"الدمج رقم {index + 1}: لا يوجد في الجدول الرئيسي عمود «{column}».",
                index))
        for column in missing_right:
            problems.append(Problem(
                "keys", column,
                f"Join {index + 1}: {name} has no column “{column}”.",
                f"الدمج رقم {index + 1}: لا يوجد في {name} عمود «{column}».", index))
        if missing or missing_right:
            continue

        lefts = [k["left"] for k in keys]
        rights = [k["right"] for k in keys]
        as_number = [left in numeric for left in lefts]
        # A key on the mapped date compares periods, not raw text: the
        # cleaner has already turned the main dates into period labels.
        right_values = {}
        for left, right in zip(lefts, rights):
            if date and left == date.get("column"):
                labels, _, _ = colmap.period_labels(
                    [row.get(right) or "" for row in table.rows],
                    date.get("order") or "auto", date.get("grain") or "auto")
                right_values[right] = labels
        lookup, counts, empty_keys = {}, Counter(), 0
        for position, row in enumerate(table.rows):
            key = tuple(
                key_text(right_values[right][position] if right in right_values
                         else row.get(right), number)
                for right, number in zip(rights, as_number))
            if None in key:
                empty_keys += 1
                continue
            counts[key] += 1
            lookup.setdefault(key, row)
        repeated = [(key, n) for key, n in counts.most_common() if n > 1]
        if repeated:
            examples = repeated[:DUPLICATE_EXAMPLES]
            shown = "; ".join(f"“{_quoted([key])}” ({n} times)" for key, n in examples)
            shown_ar = "؛ ".join(f"«{_quoted([key])}» ({n} مرات)" for key, n in examples)
            problems.append(Problem(
                "keys", ", ".join(rights),
                f"Join {index + 1}: {len(repeated)} key value(s) appear more than once in "
                f"{name}, for example {shown}. Each main row must find at most one "
                "match, or its figures would be counted more than once. Keep one row "
                "per key in the joined dataset, or join on more columns.",
                f"الدمج رقم {index + 1}: تتكرر {len(repeated)} من قيم المفتاح في {name}، "
                f"مثل {shown_ar}. يجب أن يجد كل صف رئيسي تطابقاً واحداً على الأكثر، وإلا "
                "حُسبت أرقامه أكثر من مرة. أبقِ صفاً واحداً لكل مفتاح في البيانات المدمجة، "
                "أو ادمج على أعمدة أكثر.", index))
            continue

        added, renamed = [], {}
        for column in table.columns:
            if column in rights:
                continue
            new = column if column not in columns and column not in added else f"{alias}.{column}"
            suffix = 2
            while new in columns or new in added:
                new = f"{alias}.{column}_{suffix}"
                suffix += 1
            if new != column:
                renamed[column] = new
            added.append(new)
        if len(columns) + len(added) > MAX_MERGED_COLUMNS:
            problems.append(Problem(
                "joins", None,
                f"Join {index + 1}: the merged table would have "
                f"{len(columns) + len(added)} columns; the limit is {MAX_MERGED_COLUMNS}.",
                f"الدمج رقم {index + 1}: سيصبح في الجدول المدمج "
                f"{len(columns) + len(added)} عموداً، والحد {MAX_MERGED_COLUMNS}.", index))
            continue

        merged, matched, unmatched_keys, used = [], 0, [], set()
        # An unmatched row gets what a blank cell becomes after cleaning:
        # no number for a measure, empty text otherwise. A breakdown on a
        # joined column then groups the unmatched rows together, and the
        # group totals still add up to the total.
        source = [c for c in table.columns if c not in rights]
        blank = {new: (None if old in table.numeric else "")
                 for old, new in zip(source, added)}
        for row in rows:
            key = tuple(key_text(row.get(left), number)
                        for left, number in zip(lefts, as_number))
            match = lookup.get(key) if None not in key else None
            if match is None:
                if len(unmatched_keys) < UNMATCHED_EXAMPLES and key not in unmatched_keys:
                    unmatched_keys.append(key)
                if how == "left":
                    merged.append({**row, **blank})
                continue
            matched += 1
            used.add(key)
            merged.append({**row, **{new: match[old] for old, new in zip(source, added)}})
        rows_in = len(rows)
        records.append({
            "dataset_id": item.get("dataset_id"), "name": name, "alias": alias,
            "how": how, "keys": keys, "snapshot": item.get("snapshot"),
            "rows_in": rows_in, "rows_out": len(merged), "matched": matched,
            "unmatched": rows_in - matched,
            "coverage": round(matched / rows_in, 4) if rows_in else 0.0,
            "unmatched_keys": ["/".join("" if p is None else p for p in key)
                               for key in unmatched_keys],
            "lookup_rows": len(table.rows), "lookup_unused": len(lookup) - len(used),
            "lookup_empty_keys": empty_keys,
            "lookup_dropped_empty": table.dropped_empty,
            "lookup_dropped_duplicates": table.dropped_duplicates,
            "added_columns": added, "renamed": renamed,
        })
        columns += added
        numeric += [renamed.get(c, c) for c in table.numeric if c not in rights]
        rows = merged
    if problems:
        raise JoinError(problems)
    return {"columns": columns, "rows": rows, "numeric_columns": numeric,
            "joins": records}


def breakdown_problem(breakdown, columns, numeric):
    """Why a chosen breakdown cannot be used, or None."""
    if breakdown is None:
        return None
    if breakdown not in columns:
        return Problem("breakdown", breakdown,
                       f"The breakdown “{breakdown}” is not a column of the merged table.",
                       f"التقسيم «{breakdown}» ليس عموداً في الجدول المدمج.")
    if breakdown in numeric:
        return Problem("breakdown", breakdown,
                       f"The breakdown “{breakdown}” holds numbers; choose a column of "
                       "names or categories.",
                       f"التقسيم «{breakdown}» يحمل أرقاماً؛ اختر عموداً للأسماء أو الفئات.")
    return None
