"""The dataset API (ADR 0024): several formats read into one canonical table.

The reader is tested on files built to be awkward (semicolons, byte-order
marks, Excel's 1904 dates, error cells, hostile XML) because real exports
are awkward. The API is tested on SQLite and PostgreSQL, from the
attacker's side of the tenant boundary as well as the owner's.
"""

import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from server import datasets
from server.datasets import DatasetError, read
from tests.test_runs import FASTAPI_AVAILABLE, PG_TEST_URL, _postgres_available
from tests.xlsx_builder import (DATE, QUARTERLY_SALES, REGIONAL_SALES, STRICT_MAIN, TIME,
                                Cell, build_xlsx)

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from server.app import create_app

from server.auth import issue_local_test_token

ROOT = Path(__file__).resolve().parent.parent
SECRET = "dataset-test-secret-not-used-anywhere-else"


def table(parsed):
    return [parsed.columns] + parsed.rows


class FormatDetectionTests(unittest.TestCase):

    def test_the_extension_decides_first(self):
        self.assertEqual(datasets.detect_format("a.CSV", b"x"), "csv")
        self.assertEqual(datasets.detect_format("a.tsv", b"x"), "tsv")
        self.assertEqual(datasets.detect_format("a.xlsx", b"x"), "xlsx")
        self.assertEqual(datasets.detect_format("a.ndjson", b"x"), "jsonl")

    def test_without_one_the_bytes_decide(self):
        self.assertEqual(datasets.detect_format("export", b"PK\x03\x04rest"), "xlsx")
        self.assertEqual(datasets.detect_format("export", b"\xef\xbb\xbf [1]"), "json")
        self.assertEqual(datasets.detect_format("export", b"a,b\n1,2"), "csv")

    def test_old_workbooks_and_binary_files_are_refused_by_name(self):
        for name, body in (("old.xls", b"anything"),
                           ("renamed.bin", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1....")):
            with self.assertRaises(DatasetError) as caught:
                datasets.detect_format(name, body)
            self.assertEqual(caught.exception.status, 415)
            self.assertIn(".xlsx", caught.exception.en)
        with self.assertRaises(DatasetError) as caught:
            datasets.detect_format("image", b"\x89PNG\r\n\x1a\n\x00\x00\x00")
        self.assertEqual(caught.exception.status, 415)

    def test_every_error_speaks_both_languages(self):
        with self.assertRaises(DatasetError) as caught:
            read(b"", "empty.csv")
        self.assertEqual(caught.exception.message("en"), "The file is empty.")
        self.assertEqual(caught.exception.message("ar"), "الملف فارغ.")


class CsvTests(unittest.TestCase):

    def test_the_delimiter_is_detected_and_the_output_uses_commas(self):
        for delimiter in (",", ";", "\t", "|"):
            text = delimiter.join(["month", "region", "revenue"]) + "\n"
            text += delimiter.join(["2025-01", "North", "1,5" if delimiter != "," else "15"]) + "\n"
            parsed = read(text.encode(), "export.txt")
            self.assertEqual(parsed.columns, ["month", "region", "revenue"], delimiter)
            self.assertTrue(parsed.csv_text.startswith("month,region,revenue\n"))
        self.assertEqual(read(b"a\tb\n1\t2\n", "x.txt").source_format, "tsv")

    def test_a_single_column_file_is_still_a_table(self):
        parsed = read(b"revenue\n10\n20\n", "one.csv")
        self.assertEqual(table(parsed), [["revenue"], ["10"], ["20"]])

    def test_byte_order_marks_are_handled_and_other_encodings_refused(self):
        self.assertEqual(read("﻿name,value\nسعيد,1\n".encode("utf-8"), "a.csv").columns,
                         ["name", "value"])
        utf16 = "name,value\nسعيد,1\n".encode("utf-16")
        self.assertEqual(read(utf16, "b.csv").rows, [["سعيد", "1"]])
        with self.assertRaises(DatasetError) as caught:
            read("name,value\ncafé,1\n".encode("cp1252"), "c.csv")
        self.assertEqual(caught.exception.status, 422)
        self.assertIn("CSV UTF-8", caught.exception.en)

    def test_headers_are_made_addressable(self):
        parsed = read(b" region ,,region,\nN,1,2,3\n", "h.csv")
        self.assertEqual(parsed.columns, ["region", "column_2", "region_2", "column_4"])

    def test_blank_rows_go_short_rows_are_padded_and_extra_values_kept(self):
        parsed = read(b"a,b\n\n1\n,,\n2,3,4\n", "r.csv")
        self.assertEqual(table(parsed), [["a", "b", "column_3"], ["1", "", ""], ["2", "3", "4"]])
        self.assertIn("1 rows had more values", parsed.warning_texts()[0])

    def test_quoted_values_survive_the_round_trip(self):
        parsed = read(b'note,value\n"two\nlines, and a comma",1\n', "q.csv")
        self.assertEqual(parsed.rows, [["two\nlines, and a comma", "1"]])
        self.assertIn('"two\nlines, and a comma"', parsed.csv_text)

    def test_a_file_with_no_data_is_refused(self):
        for body, words in ((b"\n\n , \n", "no data"), (b"a,b\n", "no data rows")):
            with self.assertRaises(DatasetError) as caught:
                read(body, "x.csv")
            self.assertIn(words, caught.exception.en)

    def test_row_column_and_size_limits(self):
        body = b"n\n" + b"1\n" * (datasets.MAX_ROWS + 1)
        with self.assertRaises(DatasetError) as caught:
            read(body, "long.csv")
        self.assertIn("50,000 rows", caught.exception.en)
        self.assertEqual(len(read(b"n\n" + b"1\n" * datasets.MAX_ROWS, "ok.csv").rows),
                         datasets.MAX_ROWS)
        wide = ",".join(f"c{i}" for i in range(datasets.MAX_COLUMNS + 1)).encode()
        with self.assertRaises(DatasetError) as caught:
            read(wide + b"\n" + b"1\n", "wide.csv")
        self.assertIn("columns", caught.exception.en)
        with mock.patch.object(datasets, "MAX_DATASET_BYTES", 20):
            with self.assertRaises(DatasetError) as caught:
                read(b"month,revenue\n2025-01,100\n2025-02,120\n", "big.csv")
        self.assertIn("As CSV the dataset is", caught.exception.en)
        with self.assertRaises(DatasetError) as caught:
            read(b"x" * (datasets.MAX_UPLOAD_BYTES + 1), "huge.csv")
        self.assertEqual(caught.exception.status, 413)


class JsonTests(unittest.TestCase):

    def test_a_list_of_objects_takes_every_key_in_first_seen_order(self):
        body = json.dumps([{"month": "2025-01", "revenue": 100},
                           {"month": "2025-02", "units": 3, "revenue": 120.5}]).encode()
        parsed = read(body, "records.json")
        self.assertEqual(table(parsed), [["month", "revenue", "units"],
                                         ["2025-01", "100", ""], ["2025-02", "120.5", "3"]])
        self.assertEqual(parsed.source_format, "json")

    def test_nested_objects_flatten_and_lists_stay_json(self):
        body = json.dumps([{"id": 1, "region": {"name": "North", "code": {"iso": "N"}},
                            "tags": ["a", "ب"], "ok": True, "gone": None}],
                          ensure_ascii=False).encode()
        parsed = read(body, "nested.json")
        self.assertEqual(parsed.columns,
                         ["id", "region.name", "region.code.iso", "tags", "ok", "gone"])
        self.assertEqual(parsed.rows[0], ["1", "North", "N", '["a", "ب"]', "true", ""])

    def test_the_other_shapes_a_table_comes_in(self):
        shapes = [
            [["month", "revenue"], ["2025-01", 100]],
            {"data": [{"month": "2025-01", "revenue": 100}]},
            {"meta": {"source": "erp"}, "records": [{"month": "2025-01", "revenue": 100}]},
            {"columns": ["month", "revenue"], "data": [["2025-01", 100]]},
        ]
        for shape in shapes:
            parsed = read(json.dumps(shape).encode(), "shape.json")
            self.assertEqual(table(parsed), [["month", "revenue"], ["2025-01", "100"]], shape)

    def test_json_lines_by_name_and_by_content(self):
        body = b'{"month": "2025-01", "revenue": 100}\n\n{"month": "2025-02", "revenue": 120}\n'
        self.assertEqual(read(body, "events.jsonl").source_format, "jsonl")
        # Saved as .json by a tool that writes one object per line.
        self.assertEqual(len(read(body, "events.json").rows), 2)
        with self.assertRaises(DatasetError) as caught:
            read(b'{"a": 1}\n{"a": \n', "bad.jsonl")
        self.assertIn("Line 2", caught.exception.en)
        self.assertIn("السطر 2", caught.exception.ar)

    def test_json_that_is_not_a_table_says_why(self):
        cases = (([1, 2, 3], "Item 1 is not an object"),
                 ({"a": 1}, "holds no table"),
                 ([], "is empty"),
                 ([{"a": 1}, "x"], "Item 2 is not an object"))
        for value, words in cases:
            with self.assertRaises(DatasetError) as caught:
                read(json.dumps(value).encode(), "x.json")
            self.assertIn(words, caught.exception.en, value)
        with self.assertRaises(DatasetError) as caught:
            read(b'{"a": [1,', "broken.json")
        self.assertIn("line 1", caught.exception.en)


class XlsxTests(unittest.TestCase):

    def test_strings_numbers_booleans_and_dates(self):
        body = build_xlsx([("Data", [
            ["month", "region", "revenue", "active", "booked"],
            ["2025-01", "الشمال", 100, True, date(2025, 1, 15)],
            ["2025-02", "South", 120.5, False, datetime(2025, 2, 1, 9, 30)],
        ])])
        parsed = read(body, "book.xlsx")
        self.assertEqual(table(parsed), [
            ["month", "region", "revenue", "active", "booked"],
            ["2025-01", "الشمال", "100", "TRUE", "2025-01-15"],
            ["2025-02", "South", "120.5", "FALSE", "2025-02-01 09:30:00"]])
        self.assertEqual(parsed.sheets, ["Data"])
        self.assertEqual(parsed.warnings, [])

    def test_the_1904_date_system(self):
        body = build_xlsx([("S", [["d"], [date(2025, 3, 1)]])], date1904=True)
        self.assertEqual(read(body, "mac.xlsx").rows, [["2025-03-01"]])

    def test_the_first_days_of_the_1900_system(self):
        # Excel counts a 29 February 1900 that never happened, so serials
        # before and after it map differently.
        cells = [Cell(1, s=DATE), Cell(59, s=DATE), Cell(61, s=DATE), Cell(0.75, s=TIME)]
        body = build_xlsx([("S", [["a", "b", "c", "t"], cells])])
        self.assertEqual(read(body, "early.xlsx").rows,
                         [["1900-01-01", "1900-02-28", "1900-03-01", "18:00:00"]])

    def test_custom_number_formats_decide_what_is_a_date(self):
        body = build_xlsx([("S", [["d", "pct", "clock"],
                                  [Cell(45672, s=4), Cell(0.25, s=5), Cell(0.5, s=6)]])],
                          custom_formats=('dd/mm/yyyy;@', "0.00%", "h:mm"))
        self.assertEqual(read(body, "fmt.xlsx").rows, [["2025-01-15", "0.25", "12:00:00"]])

    def test_inline_strings_sparse_cells_and_pretty_printed_xml(self):
        body = build_xlsx([("S", [
            ["a", "b", "c"],
            [Cell("inline text", t="inlineStr"), None, 3],
        ])], pretty=True)
        self.assertEqual(read(body, "sparse.xlsx").rows, [["inline text", "", "3"]])

    def test_errors_and_formulas_without_a_saved_result_are_left_empty_and_counted(self):
        body = build_xlsx([("S", [
            ["x", "y", "z"],
            [Cell("#N/A", t="e"), Cell(None, formula="A1*2"), Cell(4, formula="2*2")],
            [Cell("#DIV/0!", t="e"), 1, Cell("total", t="str", formula="\"total\"")],
        ])])
        parsed = read(body, "errors.xlsx")
        self.assertEqual(parsed.rows, [["", "", "4"], ["", "1", "total"]])
        texts = parsed.warning_texts()
        self.assertIn("2 error cells", texts[0])
        self.assertIn("1 formulas had no saved result", texts[1])

    def test_sheets_are_chosen_visibly(self):
        body = build_xlsx([("Hidden", [["h"], [1]]), ("Sales", [["s"], [2]]),
                           ("Costs", [["c"], [3]])], hidden=("Hidden",))
        parsed = read(body, "multi.xlsx")
        self.assertEqual(parsed.columns, ["s"])
        self.assertEqual(parsed.sheets, ["Hidden", "Sales", "Costs"])
        self.assertIn("Read the sheet “Sales”, the first of 3.", parsed.warning_texts())
        self.assertEqual(read(body, "multi.xlsx", sheet="costs").columns, ["c"])
        with self.assertRaises(DatasetError) as caught:
            read(body, "multi.xlsx", sheet="Budget")
        self.assertIn("Its sheets: Hidden, Sales, Costs", caught.exception.en)

    def test_strict_ooxml_namespaces_read_the_same(self):
        body = build_xlsx([("S", [["a"], [1]])], ns=STRICT_MAIN)
        self.assertEqual(table(read(body, "strict.xlsx")), [["a"], ["1"]])

    def test_phonetic_runs_are_not_read_as_text(self):
        strings = ('<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<si><r><t>東</t></r><r><t>京</t></r><rPh sb="0" eb="2"><t>トウキョウ</t></rPh></si>'
                   '<si><t>city</t></si></sst>')
        sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 '<sheetData><row r="1"><c r="A1" t="s"><v>1</v></c></row>'
                 '<row r="2"><c r="A2" t="s"><v>0</v></c></row></sheetData></worksheet>')
        body = build_xlsx([("S", [])], sheet_xml={0: sheet},
                          extra_parts={"xl/sharedStrings.xml": strings})
        self.assertEqual(table(read(body, "jp.xlsx")), [["city"], ["東京"]])

    def test_a_document_type_declaration_is_refused_before_expansion(self):
        laughs = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
                  + "".join(f'<!ENTITY lol{i} "{"&lol%s;" % (i - 1 if i else "") * 10}">'
                            for i in range(1, 9))
                  + ']><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                  '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&lol8;</t></is></c></row>'
                  '</sheetData></worksheet>')
        body = build_xlsx([("S", [])], sheet_xml={0: laughs})
        with self.assertRaises(DatasetError) as caught:
            read(body, "laughs.xlsx")
        self.assertIn("document type", caught.exception.en)

    def test_a_decompression_bomb_stops_at_the_budget(self):
        rows = [["n"]] + [[i] for i in range(2000)]
        body = build_xlsx([("S", rows)])
        self.assertLess(len(body), 20_000)
        with mock.patch.object(datasets, "MAX_XML_BYTES", 20_000):
            with self.assertRaises(DatasetError) as caught:
                read(body, "bomb.xlsx")
        self.assertIn("expand to more than", caught.exception.en)

    def test_only_parts_inside_the_archive_are_opened(self):
        body = build_xlsx([("S", [["a"], [1]])], sheet_targets={0: "../../etc/passwd"})
        with self.assertRaises(DatasetError) as caught:
            read(body, "escape.xlsx")
        self.assertIn("no worksheets", caught.exception.en)

    def test_a_cell_far_to_the_right_is_refused_before_it_is_allocated(self):
        body = build_xlsx([("S", [["a", Cell("far", t="inlineStr", ref="XFD1")], [1]])])
        with self.assertRaises(DatasetError) as caught:
            read(body, "wide.xlsx")
        self.assertIn("columns", caught.exception.en)

    def test_a_file_that_is_not_a_workbook(self):
        for body in (b"PK\x03\x04 not really a zip", _zip({"hello.txt": "hi"})):
            with self.assertRaises(DatasetError) as caught:
                read(body, "fake.xlsx")
            self.assertEqual(caught.exception.status, 422)

    def test_the_same_table_from_any_format_is_the_same_canonical_text(self):
        csv_text = "\n".join(",".join(str(v) for v in row) for row in QUARTERLY_SALES) + "\n"
        records = [dict(zip(QUARTERLY_SALES[0], row)) for row in QUARTERLY_SALES[1:]]
        texts = {
            "csv": read(csv_text.encode(), "q.csv").csv_text,
            "semicolons": read(csv_text.replace(",", ";").encode(), "q.csv").csv_text,
            "xlsx": read(build_xlsx([("Sales", QUARTERLY_SALES)]), "q.xlsx").csv_text,
            "json": read(json.dumps(records).encode(), "q.json").csv_text,
            "jsonl": read("\n".join(json.dumps(r) for r in records).encode(), "q.jsonl").csv_text,
        }
        self.assertEqual(len(set(texts.values())), 1, texts)

    def test_the_end_to_end_fixture_is_the_regional_sales_table(self):
        path = ROOT / "frontend" / "e2e" / "fixtures" / "regional-sales.xlsx"
        parsed = read(path.read_bytes(), path.name)
        expected = [[v.isoformat() if isinstance(v, date) else str(v) for v in row]
                    for row in REGIONAL_SALES]
        self.assertEqual(table(parsed), expected)
        self.assertEqual(parsed.sheets, ["Sales", "Notes"])


def _zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


try:
    import openpyxl  # noqa: F401
    OPENPYXL = True
except ImportError:
    OPENPYXL = False


@unittest.skipUnless(OPENPYXL, "openpyxl is not installed (it is not a dependency)")
class OpenpyxlCrossCheckTests(unittest.TestCase):
    """Workbooks written by a real spreadsheet library, read by ours."""

    def test_a_workbook_written_by_openpyxl(self):
        import openpyxl

        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = "Sales"
        sheet.append(["month", "region", "revenue", "booked", "share"])
        sheet.append(["2025-01", "الشمال", 1250.75, date(2025, 1, 31), 0.4])
        sheet.append(["2025-02", "South", 980, datetime(2025, 2, 28, 17, 45), 0.6])
        sheet["E2"].number_format = "0%"
        book.create_sheet("Notes").append(["not read"])
        buffer = io.BytesIO()
        book.save(buffer)
        parsed = read(buffer.getvalue(), "openpyxl.xlsx")
        self.assertEqual(table(parsed), [
            ["month", "region", "revenue", "booked", "share"],
            ["2025-01", "الشمال", "1250.75", "2025-01-31", "0.4"],
            ["2025-02", "South", "980", "2025-02-28 17:45:00", "0.6"]])
        self.assertEqual(parsed.sheets, ["Sales", "Notes"])


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class DatasetApiTestCase(unittest.TestCase):
    """POST /api/datasets and what it changes, against SQLite."""

    def database_config(self):
        return {"database_file": str(self.root / "agentic.db")}

    def env(self):
        return {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        config = {"agent_name": "Dataset Test", "memory_file": str(self.root / "memory.json"),
                  "vault_dir": str(self.root / "vault")}
        config.update(self.database_config())
        path = self.root / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        self.client = TestClient(create_app(path, env=self.env()),
                                 raise_server_exceptions=False)

    def upload(self, body, name, **params):
        query = "&".join(f"{k}={v}" for k, v in {"name": name, **params}.items())
        return self.client.post(f"/api/datasets?{query}", content=body,
                                headers=getattr(self, "headers", {}))

    def test_each_format_is_stored_with_what_it_is(self):
        records = [dict(zip(QUARTERLY_SALES[0], row)) for row in QUARTERLY_SALES[1:]]
        uploads = {
            "sales.csv": b"month;region;revenue\n2025-01;North;100\n2025-02;South;120\n",
            "book.xlsx": build_xlsx([("Sales", QUARTERLY_SALES)]),
            "records.json": json.dumps({"data": [{"a": 1, "b": {"c": 2}}]}).encode(),
            "events.jsonl": "\n".join(json.dumps(r) for r in records[:3]).encode(),
        }
        for name, body in uploads.items():
            response = self.upload(body, name)
            self.assertEqual(response.status_code, 201, response.text)
            payload = response.json()
            self.assertTrue(payload["created"])
            self.assertLessEqual(len(payload["preview"]), datasets.PREVIEW_ROWS)
        listed = {d["name"]: d for d in self.client.get("/api/datasets").json()["datasets"]}
        self.assertEqual(listed["sales.csv"]["source_format"], "csv")
        self.assertEqual(listed["book.xlsx"]["source_format"], "xlsx")
        self.assertEqual(listed["book.xlsx"]["row_count"], 4)
        self.assertEqual(listed["book.xlsx"]["column_count"], 3)
        self.assertEqual(listed["records.json"]["column_count"], 2)
        self.assertEqual(listed["events.jsonl"]["row_count"], 3)

    def test_identical_data_is_stored_once_whatever_the_format(self):
        first = self.upload(build_xlsx([("Sales", QUARTERLY_SALES)]), "q.xlsx")
        csv_body = "\n".join(",".join(str(v) for v in r) for r in QUARTERLY_SALES).encode()
        again = self.upload(csv_body, "q.csv")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 200)
        self.assertFalse(again.json()["created"])
        self.assertEqual(again.json()["dataset"]["id"], first.json()["dataset"]["id"])
        self.assertEqual(len(self.client.get("/api/datasets").json()["datasets"]), 1)

    def test_size_is_refused_from_the_header_and_while_streaming(self):
        too_big = b"a\n" + b"1\n" * (datasets.MAX_UPLOAD_BYTES // 2 + 1)
        response = self.upload(too_big, "big.csv")
        self.assertEqual(response.status_code, 413)

        def chunks():
            # No Content-Length: the cap must hold while the body streams.
            for _ in range(datasets.MAX_UPLOAD_BYTES // 65536 + 2):
                yield b"1\n" * 32768
        response = self.client.post("/api/datasets?name=stream.csv", content=chunks(),
                                    headers=getattr(self, "headers", {}))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.get("/api/datasets").json()["datasets"], [])

    def test_errors_come_back_in_the_readers_language(self):
        response = self.upload(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1....", "old.xls", language="ar")
        self.assertEqual(response.status_code, 415)
        self.assertIn("‎.xlsx‎", response.json()["detail"])
        response = self.upload(b"a,b\n", "empty.csv")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "The file has a header row but no data rows.")
        self.assertEqual(self.upload(b"a\n1\n", "x.csv", format="parquet").status_code, 422)

    def test_a_run_starts_from_an_uploaded_workbook(self):
        dataset = self.upload(build_xlsx([("Sales", QUARTERLY_SALES)]), "q.xlsx").json()["dataset"]
        run = self.client.post("/api/runs", json={"goal": "Analyse sales by team",
                                                  "dataset_id": dataset["id"]},
                               headers=getattr(self, "headers", {})).json()
        for _ in range(40):
            run = self.client.post(f"/api/runs/{run['id']}/advance",
                                   headers=getattr(self, "headers", {})).json()
            if run["state"] not in ("queued", "running"):
                break
        self.assertEqual(run["state"], "awaiting_approval")
        self.assertEqual(run["dataset_name"], "q.xlsx")
        collector = next(t for t in run["tasks"] if t["role"] == "collector")
        self.assertIn("4 rows × 3 columns", collector["summary"])

    def test_a_path_in_the_name_is_dropped(self):
        response = self.upload(b"a\n1\n", "..%2F..%2Fsecret%2Fq.csv")
        self.assertEqual(response.json()["dataset"]["name"], "q.csv")

    def test_pasted_and_sample_data_record_their_shape_too(self):
        self.client.post("/api/runs", json={"goal": "Analyse the sample"},
                         headers=getattr(self, "headers", {}))
        self.client.post("/api/runs", json={"goal": "Analyse pasted", "dataset_text": "a,b\n1,2\n3,4\n",
                                            "dataset_name": "pasted CSV"},
                         headers=getattr(self, "headers", {}))
        listed = {d["name"]: d for d in self.client.get(
            "/api/datasets", headers=getattr(self, "headers", {})).json()["datasets"]}
        self.assertEqual(listed["sample sales dataset"]["source_format"], "sample")
        self.assertEqual(listed["sample sales dataset"]["row_count"], 72)
        self.assertEqual((listed["pasted CSV"]["row_count"], listed["pasted CSV"]["column_count"]),
                         (2, 2))


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class DatasetApiPostgresTestCase(DatasetApiTestCase):
    """The same API against the hosted-mode PostgresStore."""

    def database_config(self):
        return {"database_url": PG_TEST_URL}

    def setUp(self):
        import psycopg2

        from server.storage import TABLES

        conn = psycopg2.connect(PG_TEST_URL)
        conn.autocommit = True
        conn.cursor().execute(f"DROP TABLE IF EXISTS {', '.join(TABLES)} CASCADE")
        conn.close()
        super().setUp()


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class DatasetQuotaAndTenancyTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        path = root / "config.json"
        path.write_text(json.dumps({"agent_name": "T", "database_file": str(root / "a.db"),
                                    "memory_file": str(root / "m.json"),
                                    "vault_dir": str(root / "v")}), encoding="utf-8")
        self.client = TestClient(create_app(path, env={
            "AGENTIC_OS_JWT_SECRET": SECRET, "AGENTIC_OS_ENV": "production",
            "AGENTIC_OS_QUOTA_DATASETS": "1"}), raise_server_exceptions=False)

    def auth(self, subject, role="owner"):
        return {"Authorization": "Bearer " + issue_local_test_token(
            SECRET, subject=subject, role=role)}

    def upload(self, subject, body, name="x.csv", role="owner"):
        return self.client.post(f"/api/datasets?name={name}", content=body,
                                headers=self.auth(subject, role))

    def test_the_quota_counts_new_data_and_never_a_repeat(self):
        self.assertEqual(self.upload("alice", b"a\n1\n").status_code, 201)
        self.assertEqual(self.upload("alice", b"a\n1\n").status_code, 200)
        refused = self.upload("alice", b"a\n2\n")
        self.assertEqual(refused.status_code, 429)
        self.assertIn("Dataset limit reached", refused.json()["detail"])

    def test_another_owner_can_neither_see_nor_use_a_dataset(self):
        dataset = self.upload("alice", b"a,b\n1,2\n").json()["dataset"]
        mallory = self.auth("mallory")
        self.assertEqual(self.client.get("/api/datasets", headers=mallory).json()["datasets"], [])
        response = self.client.post("/api/runs", headers=mallory, json={
            "goal": "Read alice's data", "dataset_id": dataset["id"]})
        self.assertEqual(response.status_code, 404)
        # The same bytes uploaded by another owner are that owner's own copy.
        theirs = self.upload("mallory", b"a,b\n1,2\n")
        self.assertEqual(theirs.status_code, 201)
        self.assertNotEqual(theirs.json()["dataset"]["id"], dataset["id"])

    def test_uploading_needs_permission_to_write(self):
        self.assertEqual(self.client.post("/api/datasets?name=x.csv", content=b"a\n1\n").status_code,
                         401)
        self.assertEqual(self.upload("viewer", b"a\n1\n", role="viewer").status_code, 403)


class DatasetMigrationTests(unittest.TestCase):
    """A database from before the dataset API keeps working, and its
    datasets learn their shape when the same data is stored again."""

    def test_old_rows_gain_columns_and_then_their_shape(self):
        from server.runs import RunEngine
        from server.storage import open_store

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            conn = sqlite3.connect(path)
            conn.execute("""CREATE TABLE datasets (
              id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, name TEXT NOT NULL,
              content TEXT NOT NULL, byte_size INTEGER NOT NULL,
              owner TEXT NOT NULL, created_at TEXT NOT NULL)""")
            import hashlib
            text = "a,b\n1,2\n"
            conn.execute("INSERT INTO datasets VALUES (?,?,?,?,?,?,?)", (
                "old1", hashlib.sha256(text.encode()).hexdigest(), "old.csv", text,
                len(text), "local-owner", "2026-01-01T00:00:00+00:00"))
            conn.commit()
            conn.close()

            store = open_store(sqlite_path=str(path))
            listed = store.list_datasets("local-owner")
            self.assertEqual(listed[0]["row_count"], None)
            self.assertEqual(listed[0]["source_format"], None)

            engine = RunEngine(store, Path(tmp) / "vault", gateway=None)
            stored = engine.store_dataset(text, "again.csv", "local-owner")
            self.assertEqual(stored["id"], "old1")
            self.assertEqual((stored["row_count"], stored["column_count"],
                              stored["source_format"]), (1, 2, "csv"))
            # Opening it again is harmless: the migration is repeatable.
            open_store(sqlite_path=str(path))


class DocsTests(unittest.TestCase):

    def test_the_upload_limit_quoted_in_the_interface_is_the_real_one(self):
        megabytes = datasets.MAX_UPLOAD_BYTES // 1_000_000
        en = (ROOT / "frontend" / "src" / "i18n" / "en.ts").read_text(encoding="utf-8")
        ar = (ROOT / "frontend" / "src" / "i18n" / "ar.ts").read_text(encoding="utf-8")
        self.assertTrue(f"Up to {megabytes} MB" in en, "en.ts does not say the real limit")
        self.assertTrue(f"حتى {megabytes} ميغابايت" in ar, "ar.ts does not say the real limit")


if __name__ == "__main__":
    unittest.main()
