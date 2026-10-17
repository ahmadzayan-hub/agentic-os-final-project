"""Reading uploaded datasets: CSV, TSV, Excel workbooks, JSON and JSON Lines.

Every format becomes the same thing, a header and rows, written out as one
canonical comma-separated UTF-8 CSV (ADR 0024). The pipeline reads that
CSV exactly as it always has, and the canonical text is what is hashed,
so the same table uploaded as a workbook and as a CSV is stored once.

Standard library only, like the rest of the core. A workbook is a ZIP of
XML, read here with `zipfile` and `pyexpat`; nothing executes, nothing is
fetched, and the XML is treated as hostile: a document type declaration
is refused before anything is expanded, the parts opened are only those
the workbook's own relationships name, and bytes are counted as they are
read, because the sizes a ZIP declares can lie.

Errors carry their message in English and Arabic; the API answers in the
reader's language. Nothing here ever sends data anywhere.
"""

import csv
import io
import json
import math
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from xml.parsers import expat

from server.analytics import MAX_DATASET_BYTES, MAX_ROWS

# Under the 4.5 MB request limit of the platform the app is deployed to.
MAX_UPLOAD_BYTES = 4_000_000
# A sheet that touches column XFD would otherwise allocate 16,384 cells
# for every row.
MAX_COLUMNS = 500
# The most XML read from one workbook, across every part: a decompression
# bomb stops here.
MAX_XML_BYTES = 200_000_000
PREVIEW_ROWS = 5
FORMATS = ("csv", "tsv", "xlsx", "json", "jsonl")

_EXTENSIONS = {
    ".csv": "csv", ".txt": "csv", ".tsv": "tsv", ".tab": "tsv",
    ".xlsx": "xlsx", ".xlsm": "xlsx",
    ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl",
}
_ZIP_SIGNATURE = b"PK\x03\x04"
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # old binary .xls
_DELIMITERS = (",", ";", "\t", "|")


class DatasetError(Exception):
    """A file this module will not or cannot read, with an HTTP status."""

    def __init__(self, status, en, ar):
        super().__init__(en)
        self.status = status
        self.en = en
        self.ar = ar

    def message(self, language="en"):
        return self.ar if language == "ar" else self.en


@dataclass
class ParsedDataset:
    source_format: str
    columns: list
    rows: list
    warnings: list = field(default_factory=list)   # [{"en": ..., "ar": ...}]
    sheets: list = field(default_factory=list)
    csv_text: str = ""

    def preview(self):
        return self.rows[:PREVIEW_ROWS]

    def warning_texts(self, language="en"):
        return [w["ar"] if language == "ar" else w["en"] for w in self.warnings]


def too_large():
    limit = MAX_UPLOAD_BYTES // 1_000_000
    return DatasetError(
        413, f"The file is larger than {limit} MB, the most one upload can be.",
        f"الملف أكبر من {limit} ميغابايت، وهو أقصى حجم للرفع الواحد.")


def read(body, name, fmt=None, sheet=None):
    """Read an uploaded file into a canonical table. Raises DatasetError."""
    if len(body) > MAX_UPLOAD_BYTES:
        raise too_large()
    if not body.strip():
        raise DatasetError(422, "The file is empty.", "الملف فارغ.")
    fmt = fmt or detect_format(name, body)
    if fmt == "xlsx":
        parsed = _read_xlsx(body, sheet)
    elif fmt == "json":
        parsed = _read_json(_decode(body), allow_lines=True)
    elif fmt == "jsonl":
        parsed = _read_json_lines(_decode(body))
    elif fmt in ("csv", "tsv"):
        parsed = _read_csv(_decode(body), "\t" if fmt == "tsv" else None)
    else:
        raise _unsupported()
    return _finish(parsed)


def detect_format(name, body):
    """From the file name first, then from the bytes themselves."""
    if body.startswith(_OLE_SIGNATURE) or (name or "").lower().endswith(".xls"):
        raise DatasetError(
            415, "Old .xls workbooks are not read. Save it as .xlsx or CSV and upload that.",
            "لا تُقرأ مصنّفات ‎.xls‎ القديمة. احفظه بصيغة ‎.xlsx‎ أو CSV وارفعه.")
    suffix = posixpath.splitext((name or "").lower())[1]
    if suffix in _EXTENSIONS:
        return _EXTENSIONS[suffix]
    if body.startswith(_ZIP_SIGNATURE):
        return "xlsx"
    head = body.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if head in (b"[", b"{"):
        return "json"
    if b"\x00" in body[:4096] and not body.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise _unsupported()
    return "csv"


def _unsupported():
    return DatasetError(
        415, "This is not a format the workspace reads. Upload CSV, TSV, Excel (.xlsx), JSON or JSON Lines.",
        "هذه ليست صيغة تقرؤها مساحة العمل. ارفع ملف CSV أو TSV أو Excel ‏(‎.xlsx‎) أو JSON أو JSON Lines.")


def _decode(body):
    if body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    elif body.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return body.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        # Guessing between Windows-1252 and Windows-1256 would turn Arabic
        # into nonsense without an error, so the file is refused instead.
        raise DatasetError(
            422, "The file is not UTF-8 text. In Excel, save it as “CSV UTF-8”; elsewhere, choose UTF-8 when saving.",
            "الملف ليس نصًا بترميز UTF-8. احفظه في Excel بصيغة «CSV UTF-8»، أو اختر UTF-8 عند الحفظ في برنامج آخر.")


# ---------------------------------------------------------------------------
# The canonical table
# ---------------------------------------------------------------------------

def _header(names):
    """Trimmed, never empty, never repeated: a column must be addressable."""
    seen, header = set(), []
    for index, raw in enumerate(names):
        name = str(raw).strip() or f"column_{index + 1}"
        candidate, n = name, 2
        while candidate in seen:
            candidate, n = f"{name}_{n}", n + 1
        seen.add(candidate)
        header.append(candidate)
    return header


def _too_many_rows():
    return DatasetError(
        422, f"The dataset has more than {MAX_ROWS:,} rows, the most an analysis reads.",
        f"تحتوي البيانات على أكثر من {MAX_ROWS:,} صف، وهو أقصى ما يقرؤه التحليل.")


def _too_many_columns():
    return DatasetError(
        422, f"The dataset has more than {MAX_COLUMNS} columns.",
        f"تحتوي البيانات على أكثر من {MAX_COLUMNS} عمود.")


def _table(source_format, raw_rows, warnings=None, sheets=None):
    """Header from the first non-blank row; blank rows dropped; short rows
    padded; values past the header kept in new columns, with a warning."""
    rows = [list(r) for r in raw_rows if any(str(v).strip() for v in r)]
    if not rows:
        raise DatasetError(422, "The file has no data in it.", "لا يحتوي الملف على بيانات.")
    names, body = rows[0], rows[1:]
    if not body:
        raise DatasetError(422, "The file has a header row but no data rows.",
                           "يحتوي الملف على صف عناوين ولكن بلا صفوف بيانات.")
    if len(body) > MAX_ROWS:
        raise _too_many_rows()
    width = max(len(names), *(len(r) for r in body))
    if width > MAX_COLUMNS:
        raise _too_many_columns()
    warnings = list(warnings or [])
    longer = sum(1 for r in body if len(r) > len(names))
    if longer:
        warnings.append({
            "en": f"{longer:,} rows had more values than the header; the extra values are in new columns.",
            "ar": f"في {longer:,} صفًا قيم أكثر من صف العناوين؛ وُضعت القيم الزائدة في أعمدة جديدة."})
    columns = _header(list(names) + [""] * (width - len(names)))
    table = [[str(v) for v in r] + [""] * (width - len(r)) for r in body]
    return ParsedDataset(source_format, columns, table, warnings, list(sheets or []))


def _finish(parsed):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(parsed.columns)
    writer.writerows(parsed.rows)
    text = out.getvalue()
    size = len(text.encode())
    if size > MAX_DATASET_BYTES:
        raise DatasetError(
            422, f"As CSV the dataset is {size / 1_000_000:.1f} MB, over the {MAX_DATASET_BYTES // 1_000_000} MB an analysis reads.",
            f"حجم البيانات بصيغة CSV هو {size / 1_000_000:.1f} ميغابايت، وهذا أكثر من {MAX_DATASET_BYTES // 1_000_000} ميغابايت يقرؤها التحليل.")
    parsed.csv_text = text
    return parsed


def counts(text):
    """Rows and columns of CSV text, as the canonical reader counts them.
    None for text that does not parse."""
    try:
        rows = [r for r in csv.reader(io.StringIO(text)) if any(v.strip() for v in r)]
    except csv.Error:
        return None, None
    if not rows:
        return 0, 0
    return len(rows) - 1, len(rows[0])


# ---------------------------------------------------------------------------
# CSV and TSV
# ---------------------------------------------------------------------------

def _sniff_delimiter(text):
    """The delimiter that splits the first lines into the same number of
    fields, more than one; a comma when nothing does."""
    sample = text[:65536].splitlines()[:20]
    best, best_width = ",", 1
    for delimiter in _DELIMITERS:
        try:
            widths = [len(r) for r in csv.reader(sample, delimiter=delimiter) if r]
        except csv.Error:
            continue
        if not widths:
            continue
        width = max(set(widths), key=widths.count)
        consistent = widths.count(width) >= max(1, int(len(widths) * 0.8))
        if consistent and width > best_width:
            best, best_width = delimiter, width
    return best


def _read_csv(text, delimiter=None):
    delimiter = delimiter or _sniff_delimiter(text)
    rows, filled = [], 0
    try:
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            rows.append(row)
            if any(v.strip() for v in row):
                filled += 1
                # The header plus the most rows an analysis reads.
                if filled > MAX_ROWS + 1:
                    raise _too_many_rows()
    except csv.Error as error:
        raise DatasetError(422, f"The file could not be read as CSV: {error}.",
                           f"تعذّرت قراءة الملف بصيغة CSV: {error}.")
    return _table("tsv" if delimiter == "\t" else "csv", rows)


# ---------------------------------------------------------------------------
# JSON and JSON Lines
# ---------------------------------------------------------------------------

_PREFERRED_KEYS = ("data", "records", "rows", "items", "results")


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _flatten(record, prefix="", out=None, depth=0):
    out = {} if out is None else out
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value and depth < 5:
            _flatten(value, f"{name}.", out, depth + 1)
        else:
            out[name] = _cell(value)
    return out


def _records_table(source_format, records):
    columns, seen, flat = [], set(), []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise DatasetError(
                422, f"Item {index + 1} is not an object; every item needs the same kind of fields.",
                f"العنصر {index + 1} ليس كائنًا؛ يجب أن يحمل كل عنصر حقولًا من النوع نفسه.")
        row = _flatten(record)
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
                if len(columns) > MAX_COLUMNS:
                    raise _too_many_columns()
        flat.append(row)
        if len(flat) > MAX_ROWS:
            raise _too_many_rows()
    rows = [[row.get(c, "") for c in columns] for row in flat]
    return _table(source_format, [columns] + rows)


def _no_table():
    return DatasetError(
        422, "The JSON holds no table. Use a list of objects, a list of lists with a header first, or an object holding one such list.",
        "لا يحتوي ملف JSON على جدول. استخدم قائمة كائنات، أو قائمة قوائم أولها صف العناوين، أو كائنًا يحمل قائمة كهذه.")


def _json_table(value, depth=0):
    if isinstance(value, list):
        if not value:
            raise DatasetError(422, "The JSON list is empty.", "قائمة JSON فارغة.")
        if all(isinstance(item, list) for item in value):
            return _table("json", [[_cell(v) for v in row] for row in value])
        return _records_table("json", value)
    if isinstance(value, dict) and depth < 3:
        columns, data = value.get("columns"), value.get("data")
        if isinstance(columns, list) and isinstance(data, list) and all(
                isinstance(row, list) for row in data):
            return _table("json", [[_cell(c) for c in columns]]
                          + [[_cell(v) for v in row] for row in data])
        lists = {k: v for k, v in value.items() if isinstance(v, list)}
        if len(lists) == 1:
            return _json_table(next(iter(lists.values())), depth + 1)
        for key in _PREFERRED_KEYS:
            if key in lists:
                return _json_table(lists[key], depth + 1)
    raise _no_table()


def _read_json(text, allow_lines=False):
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        if allow_lines and error.msg == "Extra data":
            return _read_json_lines(text)
        raise DatasetError(
            422, f"The JSON could not be read: {error.msg} (line {error.lineno}, column {error.colno}).",
            f"تعذّرت قراءة JSON: {error.msg} (السطر {error.lineno}، العمود {error.colno}).")
    return _json_table(value)


def _read_json_lines(text):
    records = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise DatasetError(
                422, f"Line {number} is not valid JSON: {error.msg}.",
                f"السطر {number} ليس JSON صالحًا: {error.msg}.")
        if len(records) > MAX_ROWS:
            raise _too_many_rows()
    if not records:
        raise DatasetError(422, "The file has no data in it.", "لا يحتوي الملف على بيانات.")
    parsed = _records_table("jsonl", records)
    return parsed


# ---------------------------------------------------------------------------
# Excel workbooks (.xlsx)
# ---------------------------------------------------------------------------

_BUILTIN_DATE_FORMATS = set(range(14, 18)) | set(range(27, 37)) | set(range(50, 59))
_BUILTIN_TIME_FORMATS = set(range(18, 22)) | {45, 46, 47}
_BUILTIN_DATETIME_FORMATS = {22}
_MAX_SERIAL = 2_958_465   # 9999-12-31


def _bad_workbook(detail=""):
    suffix = f" ({detail})" if detail else ""
    return DatasetError(
        422, f"The file is not a workbook the workspace can read{suffix}.",
        f"الملف ليس مصنّفًا تستطيع مساحة العمل قراءته{suffix}.")


def _refuse_doctype(*_):
    raise _bad_workbook("it declares a document type")


class _Budget:
    """Counts the XML bytes read from one workbook, across every part."""

    def __init__(self):
        self.used = 0

    def take(self, n):
        self.used += n
        if self.used > MAX_XML_BYTES:
            raise _bad_workbook("its sheets expand to more than "
                                f"{MAX_XML_BYTES // 1_000_000} MB")


def _parse_part(archive, name, budget, start=None, end=None, text=None):
    parser = expat.ParserCreate(namespace_separator="}")
    parser.StartDoctypeDeclHandler = _refuse_doctype
    parser.EntityDeclHandler = _refuse_doctype
    parser.buffer_text = True
    if start:
        parser.StartElementHandler = start
    if end:
        parser.EndElementHandler = end
    if text:
        parser.CharacterDataHandler = text
    try:
        with archive.open(name) as stream:
            while True:
                chunk = stream.read(65536)
                budget.take(len(chunk))
                if not chunk:
                    break
                parser.Parse(chunk, False)
        parser.Parse(b"", True)
    except expat.ExpatError as error:
        raise _bad_workbook(f"{name}: {expat.ErrorString(error.code)}")
    except (zipfile.BadZipFile, KeyError, RuntimeError, EOFError) as error:
        raise _bad_workbook(str(error))


def _local(name):
    return name.rsplit("}", 1)[-1]


def _attr(attrs, local):
    for key, value in attrs.items():
        if _local(key) == local:
            return value
    return None


def _relationships(archive, part, budget):
    """Id -> (type, resolved target) for the part's relationships file."""
    folder, base = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", base + ".rels")
    rels = {}
    if rels_name not in archive.namelist():
        return rels

    def start(tag, attrs):
        if _local(tag) != "Relationship" or attrs.get("TargetMode") == "External":
            return
        target = attrs.get("Target", "")
        if target.startswith("/"):
            resolved = target.lstrip("/")
        else:
            resolved = posixpath.normpath(posixpath.join(folder, target))
        if resolved.startswith("..") or resolved.startswith("/"):
            return
        rels[attrs.get("Id")] = (attrs.get("Type", ""), resolved)

    _parse_part(archive, rels_name, budget, start=start)
    return rels


def _is_date_code(code):
    """(has_date, has_time) for a custom number format."""
    cleaned = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", code.split(";")[0]).lower()
    if not cleaned or "general" in cleaned:
        return False, False
    has_time = "h" in cleaned or "s" in cleaned
    has_date = "y" in cleaned or "d" in cleaned or ("m" in cleaned and not has_time)
    if any(token in code.lower() for token in ("[h]", "[mm]", "[ss]")):
        has_time = True
    return has_date, has_time


def _styles(archive, part, budget):
    """For each cell style index: (has_date, has_time)."""
    custom, xf_formats = {}, []
    state = {"in_xfs": False}

    def start(tag, attrs):
        local = _local(tag)
        if local == "numFmt":
            try:
                custom[int(attrs.get("numFmtId", "-1"))] = attrs.get("formatCode", "")
            except ValueError:
                pass
        elif local == "cellXfs":
            state["in_xfs"] = True
        elif local == "xf" and state["in_xfs"]:
            try:
                xf_formats.append(int(attrs.get("numFmtId", "0")))
            except ValueError:
                xf_formats.append(0)

    def end(tag):
        if _local(tag) == "cellXfs":
            state["in_xfs"] = False

    if part:
        _parse_part(archive, part, budget, start=start, end=end)
    kinds = []
    for fmt_id in xf_formats:
        if fmt_id in custom:
            kinds.append(_is_date_code(custom[fmt_id]))
        elif fmt_id in _BUILTIN_DATE_FORMATS:
            kinds.append((True, False))
        elif fmt_id in _BUILTIN_TIME_FORMATS:
            kinds.append((False, True))
        elif fmt_id in _BUILTIN_DATETIME_FORMATS:
            kinds.append((True, True))
        else:
            kinds.append((False, False))
    return kinds


def _shared_strings(archive, part, budget):
    strings, state = [], {"buffer": None, "in_t": False, "skip": 0}

    def start(tag, attrs):
        local = _local(tag)
        if local == "si":
            state["buffer"] = []
        elif local == "rPh":
            state["skip"] += 1
        elif local == "t" and state["buffer"] is not None and not state["skip"]:
            state["in_t"] = True

    def end(tag):
        local = _local(tag)
        if local == "si":
            strings.append("".join(state["buffer"] or []))
            state["buffer"] = None
        elif local == "rPh":
            state["skip"] -= 1
        elif local == "t":
            state["in_t"] = False

    def text(data):
        if state["in_t"]:
            state["buffer"].append(data)

    if part:
        _parse_part(archive, part, budget, start=start, end=end, text=text)
    return strings


def _serial_to_text(serial, kind, date1904):
    has_date, has_time = kind
    if not math.isfinite(serial) or serial < 0 or serial > _MAX_SERIAL:
        return None
    days = int(serial)
    seconds = round((serial - days) * 86400)
    if seconds >= 86400:
        days, seconds = days + 1, seconds - 86400
    if date1904:
        day = date(1904, 1, 1) + timedelta(days=days)
    elif days == 60:
        day = None   # 1900-02-29, a day Excel invented for Lotus compatibility
    elif days < 60:
        day = date(1899, 12, 31) + timedelta(days=days)
    else:
        day = date(1899, 12, 30) + timedelta(days=days)
    clock = "%02d:%02d:%02d" % (seconds // 3600, seconds % 3600 // 60, seconds % 60)
    day_text = "1900-02-29" if day is None else day.isoformat()
    if has_date and (not has_time or seconds == 0):
        return day_text
    if has_time and not has_date and days == 0:
        return clock
    return f"{day_text} {clock}"


def _column_index(ref):
    letters = re.match(r"[A-Za-z]+", ref or "")
    if not letters:
        return None
    index = 0
    for letter in letters.group(0).upper():
        index = index * 26 + (ord(letter) - 64)
        if index > MAX_COLUMNS:
            raise _too_many_columns()
    return index - 1


def _read_sheet(archive, part, budget, strings, kinds, date1904):
    rows, counts = [], {"errors": 0, "uncached": 0, "kept": 0}
    state = {"row": None, "col": -1, "cell": None, "in_value": False,
             "in_inline": 0, "in_text": False, "skip": 0}

    def start(tag, attrs):
        local = _local(tag)
        if local == "row":
            state["row"], state["col"] = {}, -1
        elif local == "c" and state["row"] is not None:
            index = _column_index(attrs.get("r"))
            state["col"] = state["col"] + 1 if index is None else index
            if state["col"] >= MAX_COLUMNS:
                raise _too_many_columns()
            try:
                style = int(attrs.get("s", "0"))
            except ValueError:
                style = 0
            state["cell"] = {"t": attrs.get("t", "n"), "s": style, "v": [],
                             "inline": [], "formula": False}
        elif state["cell"] is not None:
            if local == "v":
                state["in_value"] = True
            elif local == "f":
                state["cell"]["formula"] = True
            elif local == "is":
                state["in_inline"] += 1
            elif local == "t" and state["in_inline"]:
                state["in_text"] = True
            elif local == "rPh":
                state["skip"] += 1

    def end(tag):
        local = _local(tag)
        cell = state["cell"]
        if local == "v":
            state["in_value"] = False
        elif local == "is":
            state["in_inline"] -= 1
        elif local == "t":
            state["in_text"] = False
        elif local == "rPh":
            state["skip"] -= 1
        elif local == "c" and cell is not None:
            state["row"][state["col"]] = _cell_value(cell)
            state["cell"] = None
        elif local == "row" and state["row"] is not None:
            values = state["row"]
            if values and any(v.strip() for v in values.values()):
                width = max(values) + 1
                rows.append([values.get(i, "") for i in range(width)])
                if len(rows) > MAX_ROWS + 1:
                    raise _too_many_rows()
            state["row"] = None

    def text(data):
        cell = state["cell"]
        if cell is None:
            return
        if state["in_value"]:
            cell["v"].append(data)
        elif state["in_inline"] and state["in_text"] and not state["skip"]:
            cell["inline"].append(data)

    def _cell_value(cell):
        kind, raw = cell["t"], "".join(cell["v"]).strip()
        if kind == "s":
            try:
                return strings[int(raw)]
            except (ValueError, IndexError):
                return ""
        if kind == "inlineStr":
            return "".join(cell["inline"])
        if kind == "b":
            return "TRUE" if raw == "1" else "FALSE"
        if kind == "e":
            counts["errors"] += 1
            return ""
        if kind in ("str", "d"):
            return raw
        if not raw:
            if cell["formula"]:
                counts["uncached"] += 1
            return ""
        style = kinds[cell["s"]] if cell["s"] < len(kinds) else (False, False)
        if style != (False, False):
            try:
                converted = _serial_to_text(float(raw), style, date1904)
            except ValueError:
                converted = None
            if converted is not None:
                return converted
        return raw

    _parse_part(archive, part, budget, start=start, end=end, text=text)
    return rows, counts


def _read_xlsx(body, sheet=None):
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:
        raise _bad_workbook("it is not a valid ZIP archive")
    budget = _Budget()
    with archive:
        names = set(archive.namelist())
        root_rels = _relationships(archive, "", budget) if "_rels/.rels" in names else {}
        workbook = next((target for kind, target in root_rels.values()
                         if kind.endswith("/officeDocument")), "xl/workbook.xml")
        if workbook not in names:
            raise _bad_workbook("it has no workbook part")
        rels = _relationships(archive, workbook, budget)

        sheets, settings = [], {"date1904": False}

        def start(tag, attrs):
            local = _local(tag)
            if local == "workbookPr":
                settings["date1904"] = attrs.get("date1904", "").lower() in ("1", "true")
            elif local == "sheet":
                rel = rels.get(_attr(attrs, "id"))
                if rel and rel[0].endswith("/worksheet") and rel[1] in names:
                    sheets.append({"name": attrs.get("name", ""), "part": rel[1],
                                   "hidden": attrs.get("state", "visible") != "visible"})

        _parse_part(archive, workbook, budget, start=start)
        if not sheets:
            raise _bad_workbook("it has no worksheets")
        if sheet:
            chosen = next((s for s in sheets if s["name"] == sheet), None) or next(
                (s for s in sheets if s["name"].lower() == sheet.strip().lower()), None)
            if chosen is None:
                listed = ", ".join(s["name"] for s in sheets)
                raise DatasetError(422, f"The workbook has no sheet called “{sheet}”. Its sheets: {listed}.",
                                   f"لا يحتوي المصنّف على ورقة باسم «{sheet}». أوراقه: {listed}.")
        else:
            chosen = next((s for s in sheets if not s["hidden"]), sheets[0])

        def part_of(suffix):
            return next((target for kind, target in rels.values()
                         if kind.endswith(suffix) and target in names), None)

        strings = _shared_strings(archive, part_of("/sharedStrings"), budget)
        kinds = _styles(archive, part_of("/styles"), budget)
        rows, counts = _read_sheet(archive, chosen["part"], budget, strings, kinds,
                                   settings["date1904"])

    warnings = []
    if counts["errors"]:
        warnings.append({
            "en": f"{counts['errors']:,} error cells (such as #N/A or #DIV/0!) were left empty.",
            "ar": f"تُركت {counts['errors']:,} خلية خطأ (مثل ‎#N/A‎ أو ‎#DIV/0!‎) فارغة."})
    if counts["uncached"]:
        warnings.append({
            "en": f"{counts['uncached']:,} formulas had no saved result and were left empty; open and save the file in Excel to keep them.",
            "ar": f"تُركت {counts['uncached']:,} صيغة بلا نتيجة محفوظة فارغة؛ افتح الملف في Excel واحفظه للاحتفاظ بها."})
    if len(sheets) > 1 and not sheet:
        warnings.append({
            "en": f"Read the sheet “{chosen['name']}”, the first of {len(sheets)}.",
            "ar": f"قُرئت الورقة «{chosen['name']}»، وهي الأولى من {len(sheets)} أوراق."})
    return _table("xlsx", rows, warnings, [s["name"] for s in sheets])
