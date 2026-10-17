"""A run's cleaned table (ADR 0031): download, fields, totals and records.

The query functions are tested on what makes an answer wrong: a rate
averaged over rows instead of summed, a filter that compares a number as
text, a formula smuggled into a spreadsheet. The endpoints are tested on
SQLite and PostgreSQL, before the table exists, and across the tenant
boundary, where another owner's run must look exactly like no run.
"""

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from server import query as q
from tests.test_joins import PRODUCTS_CSV, SALES_CSV, SALES_TOTAL
from tests.test_runs import FASTAPI_AVAILABLE, PG_TEST_URL, _postgres_available

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from server.app import create_app

from server.auth import issue_local_test_token

SECRET = "query-test-secret-not-used-anywhere-else"

ROWS = [
    {"month": "2025-01", "region": "North", "sold": 10.0, "returned": 1.0, "note": "ok"},
    {"month": "2025-01", "region": "South", "sold": 100.0, "returned": 50.0, "note": "=1+1"},
    {"month": "2025-02", "region": "North", "sold": 30.0, "returned": 3.0, "note": "-check"},
    {"month": "2025-02", "region": "South", "sold": None, "returned": None, "note": ""},
    {"month": "2025-03", "region": "North", "sold": 20.0, "returned": 2.0, "note": "@home"},
    {"month": "2025-12", "region": "عربي", "sold": 5.5, "returned": 0.0, "note": "مرحبا"},
]
COLUMNS = ["month", "region", "sold", "returned", "note"]


def table():
    return q.table_from(COLUMNS, ["sold", "returned"], ROWS, {"sold": "analysed"})


class DownloadTests(unittest.TestCase):

    def test_the_csv_is_excel_safe_and_exact(self):
        text = q.to_csv(table())
        self.assertTrue(text.startswith("﻿"))
        rows = list(csv.reader(io.StringIO(text[1:])))
        self.assertEqual(rows[0], COLUMNS)
        self.assertEqual(rows[1], ["2025-01", "North", "10", "1", "ok"])
        # Formula-like text is neutralised; numbers are never altered.
        self.assertEqual(rows[2][4], "'=1+1")
        self.assertEqual(rows[3][4], "'-check")
        self.assertEqual(rows[5][4], "'@home")
        self.assertEqual(rows[4][2:4], ["", ""])
        self.assertEqual(rows[6], ["2025-12", "عربي", "5.5", "0", "مرحبا"])

    def test_a_negative_number_is_a_number(self):
        negative = q.table_from(["v"], ["v"], [{"v": -3.0}])
        self.assertEqual(q.to_csv(negative).splitlines()[1], "-3")

    def test_the_file_name(self):
        self.assertEqual(q.download_name("Sales by region?", "r1"), "sales-by-region-r1-cleaned.csv")
        self.assertEqual(q.download_name("تحليل", "r1"), "run-r1-cleaned.csv")


class FieldTests(unittest.TestCase):

    def test_each_field_describes_itself(self):
        fields = {f["name"]: f for f in q.fields(table())}
        self.assertEqual(fields["sold"]["type"], "number")
        self.assertEqual((fields["sold"]["min"], fields["sold"]["max"]), (5.5, 100.0))
        self.assertEqual(fields["sold"]["filled"], 5)
        self.assertEqual(fields["sold"]["role"], "analysed")
        self.assertEqual(fields["month"]["values"], ["2025-01", "2025-02", "2025-03", "2025-12"])
        self.assertEqual(fields["note"]["values"][-1], "")

    def test_a_wide_text_column_gives_its_count_only(self):
        wide = q.table_from(["id"], [], [{"id": str(i)} for i in range(q.LISTED_VALUES + 1)])
        field = q.fields(wide)[0]
        self.assertNotIn("values", field)
        self.assertEqual(field["distinct"], q.LISTED_VALUES + 1)


class AggregateTests(unittest.TestCase):

    def ask(self, **spec):
        return q.aggregate(table(), spec)

    def test_totals_by_group_with_record_counts(self):
        answer = self.ask(group_by=["region"],
                          measures=[{"agg": "sum", "column": "sold"}, {"agg": "count"}])
        self.assertEqual([m["key"] for m in answer["measures"]], ["sum:sold", "count"])
        groups = {g["keys"][0]: g for g in answer["groups"]}
        self.assertEqual(groups["North"]["values"], [60.0, 3])
        self.assertEqual(groups["South"]["values"], [100.0, 2])
        self.assertEqual(groups["South"]["records"], 2)
        self.assertEqual((answer["matched_records"], answer["records"]), (6, 6))

    def test_a_rate_is_a_ratio_of_sums_never_an_average_of_rows(self):
        answer = self.ask(measures=[{"agg": "ratio", "numerator": "returned",
                                     "denominator": "sold"}])
        rate = answer["groups"][0]["values"][0]
        self.assertAlmostEqual(rate, 56.0 / 165.5, places=6)
        average_of_rows = sum(r["returned"] / r["sold"] for r in ROWS if r["sold"]) / 5
        self.assertNotAlmostEqual(rate, average_of_rows, places=3)

    def test_mean_min_max_and_distinct(self):
        answer = self.ask(measures=[{"agg": "mean", "column": "sold"},
                                    {"agg": "min", "column": "sold"},
                                    {"agg": "max", "column": "sold"},
                                    {"agg": "distinct", "column": "region"}])
        self.assertEqual(answer["groups"][0]["values"], [33.1, 5.5, 100.0, 3])

    def test_filters_compare_numbers_as_numbers_and_periods_in_time_order(self):
        answer = self.ask(measures=[{"agg": "count"}],
                          filters=[{"column": "sold", "op": "gte", "value": "9"},
                                   {"column": "month", "op": "between",
                                    "values": ["2025-01", "2025-02"]}])
        # As text "9" > "100", so a text comparison would drop the 100.
        self.assertEqual(answer["groups"][0]["values"], [3])

    def test_every_operator(self):
        cases = [
            ("region", "eq", "North", 3), ("region", "ne", "North", 3),
            ("region", "in", ["North", "عربي"], 4), ("region", "not_in", ["North"], 3),
            ("sold", "gt", 20, 2), ("sold", "lt", 20, 2), ("sold", "lte", 20, 3),
            ("note", "empty", None, 1), ("note", "not_empty", None, 5),
            ("sold", "empty", None, 1),
        ]
        for column, op, value, expected in cases:
            with self.subTest(op=op, column=column):
                spec = {"column": column, "op": op}
                if isinstance(value, list):
                    spec["values"] = value
                elif value is not None:
                    spec["value"] = value
                answer = self.ask(measures=[{"agg": "count"}], filters=[spec])
                self.assertEqual(answer["matched_records"], expected)

    def test_bins_cut_a_measure_into_equal_widths(self):
        answer = self.ask(group_by=[{"column": "sold", "bins": 4}], measures=[{"agg": "count"}])
        labels = [g["keys"][0] for g in answer["groups"]]
        self.assertEqual(labels[0], [5.5, 29.125])
        self.assertEqual(labels[-1], None)  # the empty measure, last
        self.assertEqual(sum(g["records"] for g in answer["groups"]), 6)
        self.assertTrue(answer["group_by"][0]["binned"])

    def test_sorting_and_the_limit(self):
        answer = self.ask(group_by=["month"], measures=[{"agg": "sum", "column": "sold"}],
                          sort={"by": "sum:sold", "desc": True}, limit=2)
        self.assertEqual([g["keys"][0] for g in answer["groups"]], ["2025-01", "2025-02"])
        self.assertTrue(answer["truncated"])
        self.assertEqual(answer["group_count"], 4)
        by_key = self.ask(group_by=["month"], measures=[{"agg": "count"}],
                          sort={"by": "month", "desc": True})
        self.assertEqual(by_key["groups"][0]["keys"], ["2025-12"])

    def test_two_groupings(self):
        answer = self.ask(group_by=["month", "region"], measures=[{"agg": "count"}])
        self.assertEqual(answer["groups"][0]["keys"], ["2025-01", "North"])
        self.assertEqual(answer["group_count"], 6)

    def test_every_problem_at_once_in_both_languages(self):
        with self.assertRaises(q.QueryError) as caught:
            self.ask(measures=[{"agg": "sum", "column": "region"}, {"agg": "median"},
                               {"agg": "ratio", "numerator": "sold", "denominator": "note"}],
                     filters=[{"column": "nope", "op": "eq", "value": 1},
                              {"column": "sold", "op": "gt", "value": "lots"},
                              {"column": "month", "op": "between", "values": ["2025-01"]}],
                     limit=5000)
        detail = caught.exception.detail("ar")
        self.assertTrue(detail["message"].startswith("لم يُنفَّذ الاستعلام"))
        self.assertEqual(len(detail["errors"]), 7)

    def test_unknown_group_and_sort(self):
        with self.assertRaises(q.QueryError):
            self.ask(group_by=["nope"], measures=[{"agg": "count"}])
        with self.assertRaises(q.QueryError):
            self.ask(measures=[{"agg": "count"}], sort={"by": "sum:sold"})
        with self.assertRaises(q.QueryError):
            self.ask(group_by=[{"column": "region", "bins": 3}], measures=[{"agg": "count"}])


class RecordsTests(unittest.TestCase):

    def test_pages_and_sorting(self):
        page = q.records(table(), {"limit": 2, "offset": 2,
                                   "sort": {"by": "sold", "desc": True}})
        self.assertEqual(page["total"], 6)
        self.assertEqual([row[2] for row in page["rows"]], [20.0, 10.0])
        # An empty value is last in either direction.
        last = q.records(table(), {"limit": 1, "offset": 5, "sort": {"by": "sold", "desc": True}})
        self.assertIsNone(last["rows"][0][2])
        first = q.records(table(), {"limit": 1, "sort": {"by": "sold"}})
        self.assertEqual(first["rows"][0][2], 5.5)

    def test_filters_and_an_even_sample(self):
        many = q.table_from(["i"], ["i"], [{"i": float(i)} for i in range(100)])
        sample = q.records(many, {"sample": 10, "filters": [{"column": "i", "op": "gte",
                                                             "value": 50}]})
        self.assertEqual([r[0] for r in sample["rows"]], [50.0 + 5 * k for k in range(10)])
        self.assertTrue(sample["sampled"])

    def test_limits(self):
        for spec in ({"limit": 0}, {"limit": q.MAX_PAGE + 1}, {"offset": -1},
                     {"sample": q.MAX_SAMPLE + 1}, {"sort": {"by": "nope"}}):
            with self.subTest(spec=spec):
                with self.assertRaises(q.QueryError):
                    q.records(table(), spec)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class TableApiTestCase(unittest.TestCase):
    """The four endpoints against SQLite."""

    def database_config(self):
        return {"database_file": str(self.root / "agentic.db")}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        config = {"agent_name": "Query Test", "memory_file": str(self.root / "memory.json"),
                  "vault_dir": str(self.root / "vault")}
        config.update(self.database_config())
        path = self.root / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        self.app = create_app(path)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def upload(self, text, name):
        return self.client.post(f"/api/datasets?name={name}", content=text.encode()).json()[
            "dataset"]["id"]

    def run_analysis(self, steps=80, **body):
        run = self.client.post("/api/runs", json={"goal": "Sales by category", **body}).json()
        for _ in range(steps):
            if run["state"] not in ("queued", "running"):
                break
            run = self.client.post(f"/api/runs/{run['id']}/advance").json()
        return run

    def test_the_table_is_not_ready_before_cleaning(self):
        run = self.run_analysis(steps=3)
        response = self.client.get(f"/api/runs/{run['id']}/fields?language=ar")
        self.assertEqual(response.status_code, 409)
        self.assertIn("غير جاهز", response.json()["detail"])

    def test_download_fields_totals_and_records(self):
        sales = self.upload(SALES_CSV, "sales.csv")
        run = self.run_analysis(dataset_id=sales)
        self.assertEqual(run["state"], "awaiting_approval", run.get("error"))
        download = self.client.get(f"/api/runs/{run['id']}/data.csv")
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.headers["content-type"].startswith("text/csv"))
        self.assertIn(f"sales-by-category-{run['id']}-cleaned.csv",
                      download.headers["content-disposition"])
        rows = list(csv.DictReader(io.StringIO(download.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 24)
        self.assertEqual(sum(float(r["revenue"]) for r in rows), SALES_TOTAL)

        fields = {f["name"]: f for f in
                  self.client.get(f"/api/runs/{run['id']}/fields").json()["fields"]}
        self.assertEqual(fields["revenue"]["role"], "analysed")
        # Unmapped: the first text column is the breakdown, and a column
        # named month is the time axis, as the run itself decided.
        self.assertEqual(fields["product"]["role"], "breakdown")
        self.assertEqual(fields["month"]["role"], "date")
        self.assertEqual(fields["region"]["values"], ["North", "South"])

        totals = self.client.post(f"/api/runs/{run['id']}/query", json={
            "group_by": ["month"], "measures": [{"agg": "sum", "column": "revenue"}]}).json()
        prep = json.loads(next(t for t in self.app.state.store.get_tasks(run["id"])
                               if t["role"] == "preparer")["result_json"])["output"]
        # The same figures the run reported, recomputed from the table.
        self.assertEqual({g["keys"][0]: g["values"][0] for g in totals["groups"]}, prep["trend"])

        page = self.client.post(f"/api/runs/{run['id']}/records", json={
            "filters": [{"column": "product", "op": "eq", "value": "P4"}], "limit": 5}).json()
        self.assertEqual(page["total"], 6)
        self.assertEqual(len(page["rows"]), 5)
        refused = self.client.post(f"/api/runs/{run['id']}/query?language=ar",
                                   json={"measures": [{"agg": "sum", "column": "region"}]})
        self.assertEqual(refused.status_code, 422)
        self.assertTrue(refused.json()["detail"]["message"].startswith("لم يُنفَّذ"))

    def test_a_joined_run_serves_the_merged_table(self):
        sales = self.upload(SALES_CSV, "sales.csv")
        products = self.upload(PRODUCTS_CSV, "products.csv")
        run = self.run_analysis(dataset_id=sales, joins=[
            {"dataset_id": products, "keys": [{"left": "product", "right": "code"}]}])
        fields = {f["name"]: f for f in
                  self.client.get(f"/api/runs/{run['id']}/fields").json()["fields"]}
        self.assertEqual(fields["category"]["role"], "joined")
        self.assertEqual(fields["list_price"]["type"], "number")
        totals = self.client.post(f"/api/runs/{run['id']}/query", json={
            "group_by": ["category"], "measures": [{"agg": "sum", "column": "revenue"}]}).json()
        self.assertAlmostEqual(sum(g["values"][0] for g in totals["groups"]), SALES_TOTAL)

    def test_a_table_is_parsed_once(self):
        run = self.run_analysis()
        engine = self.app.state.engine
        first = engine.analysis_table(run["id"])
        self.assertIs(engine.analysis_table(run["id"]), first)

    def test_an_unknown_run_is_a_404(self):
        for method, path in (("get", "data.csv"), ("get", "fields"),
                             ("post", "query"), ("post", "records")):
            response = getattr(self.client, method)(
                f"/api/runs/nope/{path}",
                **({"json": {"measures": [{"agg": "count"}]}} if method == "post" else {}))
            self.assertEqual(response.status_code, 404, path)


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class TableApiPostgresTestCase(TableApiTestCase):

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
class TableTenancyTests(unittest.TestCase):
    """Analysts own their runs; the workspace owner and admins read across
    owners by design (server/auth.py), as they do for runs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        path = root / "config.json"
        path.write_text(json.dumps({"agent_name": "T", "database_file": str(root / "a.db"),
                                    "memory_file": str(root / "m.json"),
                                    "vault_dir": str(root / "v")}), encoding="utf-8")
        self.client = TestClient(create_app(path, env={
            "AGENTIC_OS_JWT_SECRET": SECRET, "AGENTIC_OS_ENV": "production"}),
            raise_server_exceptions=False)

    def auth(self, subject, role="analyst"):
        return {"Authorization": "Bearer " + issue_local_test_token(
            SECRET, subject=subject, role=role)}

    def calls(self, run_id):
        return (("get", f"/api/runs/{run_id}/data.csv", None),
                ("get", f"/api/runs/{run_id}/fields", None),
                ("post", f"/api/runs/{run_id}/query", {"measures": [{"agg": "count"}]}),
                ("post", f"/api/runs/{run_id}/records", {}))

    def finished_run(self, headers):
        run = self.client.post("/api/runs", headers=headers,
                               json={"goal": "Private sales"}).json()
        for _ in range(80):
            if run["state"] not in ("queued", "running"):
                break
            run = self.client.post(f"/api/runs/{run['id']}/advance", headers=headers).json()
        return run

    def test_another_owner_sees_no_table_at_all(self):
        run = self.finished_run(self.auth("alice"))
        mallory = self.auth("mallory")
        for method, path, body in self.calls(run["id"]):
            with self.subTest(path=path):
                response = getattr(self.client, method)(
                    path, headers=mallory, **({"json": body} if body is not None else {}))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["detail"], "Run not found.")

    def test_a_viewer_reads_and_an_admin_reads_across_owners(self):
        run = self.finished_run(self.auth("team"))
        for headers in (self.auth("team", role="viewer"), self.auth("ops", role="admin")):
            for method, path, body in self.calls(run["id"]):
                with self.subTest(path=path, role=headers):
                    response = getattr(self.client, method)(
                        path, headers=headers, **({"json": body} if body is not None else {}))
                    self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(f"/api/runs/{run['id']}/fields").status_code, 401)


if __name__ == "__main__":
    unittest.main()
