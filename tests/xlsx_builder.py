"""Build small .xlsx workbooks with the standard library, for tests.

Each test needs a workbook shaped a particular way: a date in the 1904
system, an error cell, a formula with no saved result, a hidden first
sheet, hostile XML. Writing the parts directly gives that control, and
keeps the tests free of `openpyxl`, which CI does not install.

Run as a module to write the end-to-end fixture:

    python -m tests.xlsx_builder frontend/e2e/fixtures/regional-sales.xlsx
"""

import io
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from xml.sax.saxutils import escape

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
STRICT_MAIN = "http://purl.oclc.org/ooxml/spreadsheetml/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"

# Cell styles (indexes into cellXfs): 0 General, 1 date (built-in 14),
# 2 time (built-in 20), 3 date and time (built-in 22). Custom formats
# follow from index 4, numbered from 164 as Excel numbers them.
GENERAL, DATE, TIME, DATETIME = 0, 1, 2, 3


@dataclass
class Cell:
    """Explicit control over one cell: its type, style, formula and ref."""
    value: object = None
    t: str = None
    s: int = None
    formula: str = None
    ref: str = None


def _col(index):
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _serial(value, date1904):
    epoch = date(1904, 1, 1) if date1904 else date(1899, 12, 30)
    if isinstance(value, datetime):
        day = (value.date() - epoch).days
        seconds = value.hour * 3600 + value.minute * 60 + value.second
        return day + seconds / 86400
    return (value - epoch).days


def build_xlsx(sheets, *, date1904=False, custom_formats=(), hidden=(), ns=MAIN,
               pretty=False, sheet_xml=None, extra_parts=None, sheet_targets=None):
    """`sheets` is a list of (name, rows); a row is a list of cell values.

    A value is None (no cell at all), a str (a shared string), a bool, an
    int or float, a date or datetime (a serial number with a date style),
    or a Cell. `sheet_xml` replaces a sheet's XML outright, by index.
    """
    strings, index_of = [], {}
    nl = "\n  " if pretty else ""

    def shared(text):
        if text not in index_of:
            index_of[text] = len(strings)
            strings.append(text)
        return index_of[text]

    def cell_xml(ref, value):
        if isinstance(value, Cell):
            attrs = f' r="{value.ref or ref}"'
            if value.t:
                attrs += f' t="{value.t}"'
            if value.s is not None:
                attrs += f' s="{value.s}"'
            inner = f"<f>{escape(value.formula)}</f>" if value.formula else ""
            if value.t == "inlineStr":
                inner += f"<is>{nl}<t>{escape(str(value.value))}</t>{nl}</is>"
            elif value.t == "s":
                inner += f"<v>{shared(str(value.value))}</v>"
            elif value.value is not None:
                inner += f"<v>{escape(str(value.value))}</v>"
            return f"<c{attrs}>{inner}</c>"
        if isinstance(value, bool):
            return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
        if isinstance(value, datetime):
            return f'<c r="{ref}" s="{DATETIME}"><v>{_serial(value, date1904)}</v></c>'
        if isinstance(value, date):
            return f'<c r="{ref}" s="{DATE}"><v>{_serial(value, date1904)}</v></c>'
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value}</v></c>'
        return f'<c r="{ref}" t="s"><v>{shared(str(value))}</v></c>'

    def worksheet(rows):
        out = []
        for r, row in enumerate(rows, 1):
            cells = "".join(cell_xml(f"{_col(c)}{r}", v)
                            for c, v in enumerate(row) if v is not None)
            out.append(f'{nl}<row r="{r}">{cells}</row>')
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                f'<worksheet xmlns="{ns}" xmlns:r="{REL}"><sheetData>'
                f'{"".join(out)}{nl}</sheetData></worksheet>')

    parts = {}
    sheet_entries, rels = [], []
    for i, (name, rows) in enumerate(sheets, 1):
        target = (sheet_targets or {}).get(i - 1, f"worksheets/sheet{i}.xml")
        xml = (sheet_xml or {}).get(i - 1) or worksheet(rows)
        if not target.startswith(".."):
            parts["xl/" + target if not target.startswith("/") else target.lstrip("/")] = xml
        state = ' state="hidden"' if name in hidden else ""
        sheet_entries.append(
            f'<sheet name="{escape(name)}" sheetId="{i}"{state} r:id="rId{i}"/>')
        rels.append(f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="{target}"/>')
    n = len(sheets)
    rels.append(f'<Relationship Id="rId{n + 1}" Type="{REL}/sharedStrings" Target="sharedStrings.xml"/>')
    rels.append(f'<Relationship Id="rId{n + 2}" Type="{REL}/styles" Target="styles.xml"/>')

    custom = "".join(f'<numFmt numFmtId="{164 + i}" formatCode="{escape(code)}"/>'
                     for i, code in enumerate(custom_formats))
    xfs = ['<xf numFmtId="0"/>', '<xf numFmtId="14"/>', '<xf numFmtId="20"/>',
           '<xf numFmtId="22"/>'] + [f'<xf numFmtId="{164 + i}"/>'
                                     for i in range(len(custom_formats))]
    parts["xl/styles.xml"] = (
        f'<styleSheet xmlns="{ns}"><numFmts count="{len(custom_formats)}">{custom}</numFmts>'
        f'<cellStyleXfs count="1"><xf numFmtId="0"/></cellStyleXfs>'
        f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs></styleSheet>')
    parts["xl/sharedStrings.xml"] = (
        f'<sst xmlns="{ns}" count="{len(strings)}" uniqueCount="{len(strings)}">'
        + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>")
    pr = '<workbookPr date1904="1"/>' if date1904 else "<workbookPr/>"
    parts["xl/workbook.xml"] = (
        f'<workbook xmlns="{ns}" xmlns:r="{REL}">{pr}<sheets>'
        f'{"".join(sheet_entries)}</sheets></workbook>')
    parts["xl/_rels/workbook.xml.rels"] = (
        f'<Relationships xmlns="{PKG}">{"".join(rels)}</Relationships>')
    parts["_rels/.rels"] = (
        f'<Relationships xmlns="{PKG}"><Relationship Id="rId1" '
        f'Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
        f'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, n + 1))
    parts["[Content_Types].xml"] = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f'{overrides}'
        '<Override PartName="/xl/styles.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '</Types>')
    parts.update(extra_parts or {})

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["[Content_Types].xml"] + sorted(p for p in parts if p != "[Content_Types].xml"):
            # A fixed timestamp, so the same workbook is the same bytes.
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, parts[name])
    return buffer.getvalue()


# A small table the tests write in every format.
QUARTERLY_SALES = [
    ["team", "quarter", "sales"],
    ["A", "Q1", 120],
    ["A", "Q2", 180],
    ["B", "Q1", 60],
    ["B", "Q2", 40],
]

# The workbook the end-to-end tests upload: its own table, so that
# content addressing never merges it with another spec's CSV, and a date
# column, so that Excel dates are read in the browser journey too.
REGIONAL_SALES = [
    ["region", "month", "revenue", "booked"],
    ["North", "2025-01", 1200, date(2025, 1, 31)],
    ["North", "2025-02", 1350, date(2025, 2, 28)],
    ["South", "2025-01", 900, date(2025, 1, 31)],
    ["South", "2025-02", 980, date(2025, 2, 28)],
]

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "regional-sales.xlsx"
    with open(path, "wb") as handle:
        handle.write(build_xlsx([("Sales", REGIONAL_SALES), ("Notes", [["not read"]])]))
    print(f"wrote {path}")
