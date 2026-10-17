"""Several datasets per run (ADR 0030): declared joins, merged after cleaning.

A join is tested on what makes one wrong: a repeated lookup key, keys
spelled as numbers or dates, an inner join's lost rows, a name already
taken. The run is tested on its figures: a left join must leave every
total of the main dataset where it was, and the Validation Expert must
recount the rows itself. The API is tested on SQLite and PostgreSQL, and
across the tenant boundary.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from server import analytics
from server import joins as j
from tests.test_runs import FASTAPI_AVAILABLE, PG_TEST_URL, _postgres_available

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from server.app import create_app

from server.auth import issue_local_test_token

SECRET = "joins-test-secret-not-used-anywhere-else"

MONTHS = [f"2025-{m:02d}" for m in range(1, 7)]
PRODUCTS = ("P1", "P2", "P3", "P4")
# Six months of sales for four products; P4 is not in the product list,
# so its rows find no match.
SALES_ROWS = [(month, product, "North" if i % 2 else "South", 100 + 10 * i + 5 * p)
              for i, month in enumerate(MONTHS) for p, product in enumerate(PRODUCTS)]
SALES_CSV = "month,product,region,revenue\n" + "\n".join(
    f"{m},{p},{r},{v}" for m, p, r, v in SALES_ROWS) + "\n"
SALES_TOTAL = float(sum(v for *_, v in SALES_ROWS))
P4_TOTAL = float(sum(v for _, p, _, v in SALES_ROWS if p == "P4"))
PRODUCTS_CSV = ("code,category,list_price\nP1,Hardware,10\nP2,Software,20\n"
                "P3,Hardware,15\nP9,Services,5\n")
DUPLICATED_CSV = "code,category\nP1,Hardware\nP1,Software\nP2,Software\n"
# Monthly targets, written the way a planning sheet writes months.
TARGETS_CSV = "month,target\n" + "\n".join(
    f"{name} 2025,{1000 + 100 * i}"
    for i, name in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun"))) + "\n"


def table(text, mapping=None):
    return j.clean_table(text, mapping)


def joined(text, keys, how="left", alias="lookup", name="lookup.csv", mapping=None):
    return {"table": table(text, mapping), "keys": keys, "how": how, "alias": alias,
            "name": name, "dataset_id": "d", "snapshot": "s"}


def base():
    main = table(SALES_CSV)
    return main.columns, main.rows, main.numeric


class DeclarationTests(unittest.TestCase):

    def test_a_declaration_is_checked_for_shape(self):
        spec = j.normalise([{"dataset_id": "d1", "keys": [{"left": "a", "right": "b"}]}],
                           " region ")
        self.assertEqual(spec, {"joins": [{"dataset_id": "d1", "how": "left", "alias": None,
                                           "keys": [{"left": "a", "right": "b"}]}],
                                "breakdown": "region"})

    def test_every_problem_is_reported_at_once_in_both_languages(self):
        with self.assertRaises(j.JoinError) as caught:
            j.normalise([{"dataset_id": "", "keys": [], "how": "outer", "alias": "9x"}])
        fields = [p.field for p in caught.exception.problems]
        self.assertEqual(fields, ["joins", "how", "keys", "alias"])
        detail = caught.exception.detail("ar")
        self.assertTrue(detail["message"].startswith("لا يمكن دمج البيانات"))
        self.assertEqual(len(detail["errors"]), 4)
        self.assertTrue(all(e["join"] == 0 for e in detail["errors"]))

    def test_too_many_joins(self):
        many = [{"dataset_id": f"d{i}", "keys": [{"left": "a", "right": "a"}]}
                for i in range(j.MAX_JOINS + 1)]
        with self.assertRaises(j.JoinError):
            j.normalise(many)

    def test_aliases_come_from_file_names_and_never_collide(self):
        joins = [{"alias": None}, {"alias": None}, {"alias": "own"}]
        j.assign_aliases(joins, ["Regional Targets.xlsx", "regional targets.csv", "x"])
        self.assertEqual([x["alias"] for x in joins],
                         ["regional_targets", "regional_targets_2", "own"])
        self.assertEqual(j.default_alias("2025 plan.csv"), "joined_2025_plan")


class KeyTests(unittest.TestCase):

    def test_numbers_compare_as_numbers(self):
        for value in (3, 3.0, "3", "003", " 3.0 ", "٣"):
            with self.subTest(value=value):
                self.assertEqual(j.key_text(value, True), "3")
        self.assertEqual(j.key_text("2.50", True), "2.5")
        self.assertIsNone(j.key_text("n/a", True))

    def test_text_compares_trimmed_and_exact(self):
        self.assertEqual(j.key_text("  North ", False), "North")
        self.assertNotEqual(j.key_text("north", False), j.key_text("North", False))
        self.assertIsNone(j.key_text("   ", False))
        self.assertIsNone(j.key_text(None, False))


class CleaningTests(unittest.TestCase):

    def test_a_joined_table_is_cleaned_like_the_main_one(self):
        text = "code,price,note\n P1 ,10,a\n\n,,\nP1,10,a\nP2,x,b\nP3,30,c\nP4,40,d\n"
        cleaned = table(text)
        self.assertEqual((cleaned.rows_before, cleaned.dropped_empty,
                          cleaned.dropped_duplicates, len(cleaned.rows)), (6, 1, 1, 4))
        self.assertEqual(cleaned.rows[0]["code"], "P1")
        # Three of four filled cells read as numbers: under the 90% rule.
        self.assertEqual(cleaned.numeric, [])

    def test_a_mapping_decides_the_measures(self):
        mapping = {"roles": {"code": "dimension", "price": "measure", "note": "ignore"},
                   "measure": "price", "dimension": "code", "date_order": "auto",
                   "grain": "auto"}
        cleaned = table("code,price,note\nP1,$1,200,a\nP2,(30),b\n".replace("$1,200", '"$1,200"'),
                        mapping)
        self.assertEqual(cleaned.numeric, ["price"])
        self.assertEqual([r["price"] for r in cleaned.rows], [1200.0, -30.0])


class MergeTests(unittest.TestCase):

    def test_a_left_join_keeps_every_row_and_counts_its_matches(self):
        columns, rows, numeric = base()
        result = j.merge(columns, rows, numeric,
                         [joined(PRODUCTS_CSV, [{"left": "product", "right": "code"}])])
        record = result["joins"][0]
        self.assertEqual(len(result["rows"]), len(rows))
        self.assertEqual((record["rows_in"], record["rows_out"], record["matched"],
                          record["unmatched"]), (24, 24, 18, 6))
        self.assertEqual(record["coverage"], 0.75)
        self.assertEqual(record["unmatched_keys"], ["P4"])
        self.assertEqual(record["lookup_unused"], 1)  # P9 matched nothing
        self.assertEqual(result["columns"], columns + ["category", "list_price"])
        self.assertIn("list_price", result["numeric_columns"])
        p4 = next(r for r in result["rows"] if r["product"] == "P4")
        self.assertEqual((p4["category"], p4["list_price"]), ("", None))
        # The main table's figures are untouched.
        self.assertEqual(sum(r["revenue"] for r in result["rows"]), SALES_TOTAL)

    def test_an_inner_join_keeps_only_matched_rows(self):
        columns, rows, numeric = base()
        result = j.merge(columns, rows, numeric,
                         [joined(PRODUCTS_CSV, [{"left": "product", "right": "code"}],
                                 how="inner")])
        record = result["joins"][0]
        self.assertEqual((record["rows_out"], record["matched"]), (18, 18))
        self.assertEqual(sum(r["revenue"] for r in result["rows"]), SALES_TOTAL - P4_TOTAL)

    def test_a_repeated_lookup_key_is_refused(self):
        columns, rows, numeric = base()
        with self.assertRaises(j.JoinError) as caught:
            j.merge(columns, rows, numeric,
                    [joined(DUPLICATED_CSV, [{"left": "product", "right": "code"}])])
        problem = caught.exception.problems[0]
        self.assertEqual(problem.field, "keys")
        self.assertIn("“P1” (2 times)", problem.en)
        self.assertIn("«P1» (2 مرات)", problem.ar)

    def test_a_missing_key_column_is_named_on_its_side(self):
        columns, rows, numeric = base()
        with self.assertRaises(j.JoinError) as caught:
            j.merge(columns, rows, numeric,
                    [joined(PRODUCTS_CSV, [{"left": "sku", "right": "id"}])])
        self.assertEqual({(p.column, "main" if "main table" in p.en else "joined")
                          for p in caught.exception.problems},
                         {("sku", "main"), ("id", "joined")})

    def test_a_taken_name_is_prefixed_never_overwritten(self):
        columns, rows, numeric = base()
        lookup = "code,region,category\nP1,West,A\nP2,West,B\nP3,East,C\nP4,East,D\n"
        result = j.merge(columns, rows, numeric,
                         [joined(lookup, [{"left": "product", "right": "code"}],
                                 alias="products")])
        self.assertIn("products.region", result["columns"])
        self.assertEqual(result["joins"][0]["renamed"], {"region": "products.region"})
        first = result["rows"][0]
        self.assertEqual((first["region"], first["products.region"]), ("South", "West"))

    def test_numeric_keys_match_however_they_are_written(self):
        main = table("store,sales\n3,10\n7,20\n12,30\n")
        self.assertIn("store", main.numeric)
        result = j.merge(main.columns, main.rows, main.numeric,
                         [joined("store_code,city\n003,Dubai\n7.0,Abu Dhabi\n",
                                 [{"left": "store", "right": "store_code"}])])
        self.assertEqual([r["city"] for r in result["rows"]], ["Dubai", "Abu Dhabi", ""])

    def test_a_date_key_reads_the_joined_dates_at_the_main_grain(self):
        main = table("month,revenue\n2025-01,100\n2025-02,200\n")
        result = j.merge(main.columns, main.rows, main.numeric,
                         [joined("when,target\nJan 2025,150\n2025-02-14,250\n",
                                 [{"left": "month", "right": "when"}])],
                         date={"column": "month", "order": "auto", "grain": "month"})
        self.assertEqual([r["target"] for r in result["rows"]], [150.0, 250.0])

    def test_composite_keys(self):
        main = table("region,product,units\nN,P1,1\nN,P2,2\nS,P1,3\n")
        lookup = "r,p,price\nN,P1,10\nS,P1,30\nN,P2,20\n"
        result = j.merge(main.columns, main.rows, main.numeric,
                         [joined(lookup, [{"left": "region", "right": "r"},
                                          {"left": "product", "right": "p"}])])
        self.assertEqual([r["price"] for r in result["rows"]], [10.0, 20.0, 30.0])

    def test_joins_apply_in_order_and_can_use_earlier_columns(self):
        main = table("product,units\nP1,1\nP2,2\n")
        result = j.merge(main.columns, main.rows, main.numeric, [
            joined("code,category\nP1,Hardware\nP2,Software\n",
                   [{"left": "product", "right": "code"}], alias="a"),
            joined("category,owner\nHardware,Dana\nSoftware,Sami\n",
                   [{"left": "category", "right": "category"}], alias="b"),
        ])
        self.assertEqual([r["owner"] for r in result["rows"]], ["Dana", "Sami"])

    def test_the_column_ceiling(self):
        main = table("k\n1\n")
        wide = "k," + ",".join(f"c{i}" for i in range(j.MAX_MERGED_COLUMNS)) + "\n1," + \
               ",".join("x" for _ in range(j.MAX_MERGED_COLUMNS)) + "\n"
        with self.assertRaises(j.JoinError):
            j.merge(main.columns, main.rows, main.numeric,
                    [joined(wide, [{"left": "k", "right": "k"}])])

    def test_a_breakdown_must_be_a_text_column_of_the_merged_table(self):
        self.assertIsNone(j.breakdown_problem(None, ["a"], []))
        self.assertIsNone(j.breakdown_problem("a", ["a"], []))
        self.assertEqual(j.breakdown_problem("x", ["a"], []).field, "breakdown")
        self.assertIn("numbers", j.breakdown_problem("a", ["a"], ["a"]).en)


class PreviewTests(unittest.TestCase):

    def inputs(self, text=PRODUCTS_CSV, keys=None, how="left"):
        return [{"dataset_id": "d", "name": "products.csv", "alias": "products",
                 "content": text, "snapshot": "abc", "mapping": None, "how": how,
                 "keys": keys or [{"left": "product", "right": "code"}]}]

    def test_the_preview_runs_the_real_stages(self):
        preview = analytics.preview_merge(SALES_CSV, None, self.inputs(), "category")
        self.assertEqual((preview["rows_before"], preview["rows_after"]), (24, 24))
        self.assertEqual(preview["added_columns"], ["category", "list_price"])
        self.assertIn("category", preview["breakdown_choices"])
        self.assertNotIn("revenue", preview["breakdown_choices"])
        self.assertEqual(preview["preview"][0], ["2025-01", "P1", "South", "100", "Hardware", "10"])
        self.assertEqual(preview["joins"][0]["matched"], 18)

    def test_a_main_dataset_the_pipeline_refuses_is_refused_here(self):
        with self.assertRaises(j.JoinError):
            analytics.preview_merge("a,b\nx,y\n", None, self.inputs(), None)

    def test_a_numeric_breakdown_is_refused(self):
        with self.assertRaises(j.JoinError) as caught:
            analytics.preview_merge(SALES_CSV, None, self.inputs(), "list_price")
        self.assertEqual(caught.exception.problems[0].field, "breakdown")

    def test_personal_data_in_a_joined_dataset_is_found(self):
        people = "code,owner_email\nP1,a.person@example.com\nP2,b.person@example.com\n"
        preview = analytics.preview_merge(SALES_CSV, None, self.inputs(people), None)
        self.assertEqual(preview["personal_data"],
                         [{"dataset": "products.csv", "column": "owner_email"}])


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class JoinApiTestCase(unittest.TestCase):
    """Runs with joins, through the API, against SQLite."""

    def database_config(self):
        return {"database_file": str(self.root / "agentic.db")}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        config = {"agent_name": "Join Test", "memory_file": str(self.root / "memory.json"),
                  "vault_dir": str(self.root / "vault")}
        config.update(self.database_config())
        path = self.root / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        self.app = create_app(path)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def upload(self, text, name):
        response = self.client.post(f"/api/datasets?name={name}", content=text.encode())
        self.assertIn(response.status_code, (200, 201), response.text)
        return response.json()["dataset"]["id"]

    def advance(self, run):
        for _ in range(80):
            run = self.client.post(f"/api/runs/{run['id']}/advance").json()
            if run["state"] not in ("queued", "running"):
                break
        return run

    def run_to_gate(self, **body):
        response = self.client.post("/api/runs", json={"goal": "Sales by category", **body})
        self.assertEqual(response.status_code, 201, response.text)
        run = self.advance(response.json())
        self.assertEqual(run["state"], "awaiting_approval", run.get("error"))
        return run

    def output(self, run, role):
        stored = next(t for t in self.app.state.store.get_tasks(run["id"]) if t["role"] == role)
        return json.loads(stored["result_json"])["output"]

    def task(self, run, role):
        return next(t for t in run["tasks"] if t["role"] == role)

    def check(self, run, role, name):
        return next(c for c in self.task(run, role)["quality_checks"] if c["name"] == name)

    def joins(self, products, how="left"):
        return [{"dataset_id": products, "how": how,
                 "keys": [{"left": "product", "right": "code"}]}]

    def test_a_left_join_leaves_every_total_where_it_was(self):
        sales = self.upload(SALES_CSV, "sales.csv")
        products = self.upload(PRODUCTS_CSV, "products.csv")
        alone = self.run_to_gate(dataset_id=sales)
        run = self.run_to_gate(dataset_id=sales, joins=self.joins(products))
        roles = [t["role"] for t in run["tasks"]]
        self.assertEqual(roles[roles.index("cleaner") + 1], "merge")
        self.assertNotIn("merge", [t["role"] for t in alone["tasks"]])
        self.assertEqual(run["dataset_name"], "sales.csv + products.csv")
        self.assertEqual(run["joins"][0]["alias"], "products")
        for role in ("preparer", "descriptive"):
            for key in ("total", "trend", "groups"):
                before = self.output(alone, role).get(key)
                if before is not None:
                    self.assertEqual(before, self.output(run, role)[key], (role, key))
        merged = self.output(run, "merge")
        self.assertEqual((merged["rows_before"], merged["rows_after"]), (24, 24))
        self.assertTrue(self.check(run, "validator", "joins_keep_the_row_count")["passed"])
        self.assertFalse(self.check(run, "merge", "join_products_keys_cover_every_row")["passed"])
        self.assertTrue(self.check(run, "merge", "join_products_keeps_the_row_count")["passed"])
        claim = next(c for c in self.task(run, "merge")["claims"] if c["id"] == "cl_merge_0")
        self.assertEqual(claim["type"], "limitation")
        self.assertIn("18 of 24 rows found a match in products.csv", claim["text"])
        self.assertTrue(all(c["passed"] for c in self.task(run, "validator")["quality_checks"]))
        self.assertIn("products.csv", run["report"]["content"])

    def test_a_breakdown_from_the_lookup_groups_the_run(self):
        sales = self.upload(SALES_CSV, "sales.csv")
        products = self.upload(PRODUCTS_CSV, "products.csv")
        run = self.run_to_gate(dataset_id=sales, joins=self.joins(products),
                               breakdown="category")
        prep = self.output(run, "preparer")
        self.assertEqual(prep["group_col"], "category")
        self.assertEqual(set(prep["groups"]), {"Hardware", "Software", ""})
        self.assertAlmostEqual(sum(prep["groups"].values()), SALES_TOTAL)
        self.assertEqual(prep["groups"][""], P4_TOTAL)
        self.assertTrue(self.check(run, "validator", "group_totals_reconcile")["passed"])
        self.assertEqual(run["breakdown"], "category")

    def test_an_inner_join_says_what_it_left_out(self):
        sales = self.upload(SALES_CSV, "sales.csv")
        products = self.upload(PRODUCTS_CSV, "products.csv")
        run = self.run_to_gate(dataset_id=sales, joins=self.joins(products, "inner"))
        self.assertEqual(self.output(run, "preparer")["total"], SALES_TOTAL - P4_TOTAL)
        ids = {c["id"] for c in self.task(run, "merge")["claims"]}
        self.assertIn("cl_merge_0_inner", ids)
        self.assertIn("18 analyzed rows", run["report"]["content"])

    def test_a_monthly_target_joins_daily_sales_by_month(self):
        daily = "day,revenue\n" + "\n".join(
            f"2025-{m:02d}-{d:02d},{10 * m + d}" for m in range(1, 7) for d in (3, 17)) + "\n"
        sales = self.upload(daily, "daily.csv")
        mapping = {"roles": {"day": "date", "revenue": "measure"}, "measure": "revenue",
                   "dimension": None, "date_order": "auto", "grain": "month"}
        self.assertEqual(self.client.put(f"/api/datasets/{sales}/mapping",
                                         json=mapping).status_code, 200)
        targets = self.upload(TARGETS_CSV, "targets.csv")
        run = self.run_to_gate(dataset_id=sales, joins=[
            {"dataset_id": targets, "keys": [{"left": "day", "right": "month"}]}])
        merged = self.output(run, "merge")
        self.assertEqual(merged["joins"][0]["matched"], 12)
        self.assertIn("target", merged["numeric_columns"])

    def test_an_arabic_run_with_joins_passes_validation(self):
        sales = self.upload(SALES_CSV, "sales.csv")
        products = self.upload(PRODUCTS_CSV, "products.csv")
        run = self.run_to_gate(dataset_id=sales, joins=self.joins(products), language="ar")
        self.assertTrue(self.check(run, "validator", "both_languages_cite_the_same_figures")["passed"])
        self.assertTrue(self.check(run, "validator",
                                   "every_builtin_claim_is_in_the_report_language")["passed"])
        self.assertEqual(self.task(run, "merge")["title"],
                         analytics.ROLE_TITLES_AR["merge"])

    def test_a_run_that_would_fail_its_merge_is_refused_before_it_starts(self):
        sales = self.upload(SALES_CSV, "sales.csv")
        dupes = self.upload(DUPLICATED_CSV, "dupes.csv")
        response = self.client.post("/api/runs", json={
            "goal": "Sales by category", "dataset_id": sales, "language": "ar",
            "joins": self.joins(dupes)})
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertTrue(detail["message"].startswith("لا يمكن دمج البيانات"))
        self.assertEqual(detail["errors"][0]["field"], "keys")
        self.assertEqual(self.client.get("/api/runs").json()["runs"], [])

    def test_joins_need_a_stored_main_dataset(self):
        products = self.upload(PRODUCTS_CSV, "products.csv")
        response = self.client.post("/api/runs", json={
            "goal": "Sales by category", "dataset_text": SALES_CSV,
            "joins": self.joins(products)})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["errors"][0]["field"], "dataset")

    def test_the_preview(self):
        sales = self.upload(SALES_CSV, "sales.csv")
        products = self.upload(PRODUCTS_CSV, "products.csv")
        response = self.client.post("/api/joins/preview", json={
            "dataset_id": sales, "joins": self.joins(products)})
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual((preview["rows_before"], preview["rows_after"]), (24, 24))
        self.assertEqual(preview["joins"][0]["unmatched_keys"], ["P4"])
        self.assertEqual(len(preview["preview"]), 5)
        refused = self.client.post("/api/joins/preview?language=ar", json={
            "dataset_id": sales, "joins": self.joins(self.upload(DUPLICATED_CSV, "d.csv"))})
        self.assertEqual(refused.status_code, 422)
        self.assertIn("«P1»", refused.json()["detail"]["errors"][0]["message"])
        missing = self.client.post("/api/joins/preview", json={
            "dataset_id": sales, "joins": self.joins("nope")})
        self.assertEqual(missing.status_code, 404)

    def test_the_run_keeps_its_own_copy_of_a_joined_mapping(self):
        sales = self.upload(SALES_CSV, "sales.csv")
        products = self.upload(PRODUCTS_CSV, "products.csv")
        mapping = {"roles": {"code": "dimension", "category": "dimension",
                             "list_price": "measure"},
                   "measure": "list_price", "dimension": "category",
                   "date_order": "auto", "grain": "auto"}
        self.client.put(f"/api/datasets/{products}/mapping", json=mapping)
        run = self.client.post("/api/runs", json={"goal": "Sales by category",
                                                  "dataset_id": sales,
                                                  "joins": self.joins(products)}).json()
        self.client.delete(f"/api/datasets/{products}/mapping")
        stored = json.loads(self.app.state.store.get_run(run["id"])["joins_json"])
        self.assertEqual(stored["joins"][0]["mapping"]["measure"], "list_price")
        run = self.advance(run)
        self.assertEqual(run["state"], "awaiting_approval", run.get("error"))
        self.assertIn("list_price", self.output(run, "merge")["numeric_columns"])

    def test_provenance_names_every_snapshot(self):
        sales = self.upload(SALES_CSV, "sales.csv")
        products = self.upload(PRODUCTS_CSV, "products.csv")
        run = self.run_to_gate(dataset_id=sales, joins=self.joins(products))
        lineage = self.output(run, "lineage")
        self.assertEqual(len(lineage["joined_snapshots"]), 1)
        self.assertIn(lineage["joined_snapshots"][0], self.task(run, "lineage")["summary"])


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class JoinApiPostgresTestCase(JoinApiTestCase):
    """The same runs against the hosted-mode PostgresStore."""

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
class JoinTenancyTests(unittest.TestCase):

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

    def auth(self, subject, role="owner"):
        return {"Authorization": "Bearer " + issue_local_test_token(
            SECRET, subject=subject, role=role)}

    def upload(self, text, name, headers):
        return self.client.post(f"/api/datasets?name={name}", content=text.encode(),
                                headers=headers).json()["dataset"]["id"]

    def test_another_owners_dataset_cannot_be_joined_or_previewed(self):
        alice, mallory = self.auth("alice"), self.auth("mallory")
        products = self.upload(PRODUCTS_CSV, "products.csv", alice)
        sales = self.upload(SALES_CSV, "sales.csv", mallory)
        joins = [{"dataset_id": products, "keys": [{"left": "product", "right": "code"}]}]
        run = self.client.post("/api/runs", headers=mallory, json={
            "goal": "Steal a lookup", "dataset_id": sales, "joins": joins})
        self.assertEqual(run.status_code, 404)
        preview = self.client.post("/api/joins/preview", headers=mallory,
                                   json={"dataset_id": sales, "joins": joins})
        self.assertEqual(preview.status_code, 404)
        # And the other way round: someone else's main dataset.
        own = self.upload(PRODUCTS_CSV, "mine.csv", mallory)
        other_main = self.client.post("/api/joins/preview", headers=mallory, json={
            "dataset_id": products,
            "joins": [{"dataset_id": own, "keys": [{"left": "code", "right": "code"}]}]})
        self.assertEqual(other_main.status_code, 404)

    def test_a_viewer_can_preview_but_not_start_a_run(self):
        owner = self.auth("team")
        sales = self.upload(SALES_CSV, "sales.csv", owner)
        products = self.upload(PRODUCTS_CSV, "products.csv", owner)
        viewer = self.auth("team", role="viewer")
        body = {"dataset_id": sales,
                "joins": [{"dataset_id": products,
                           "keys": [{"left": "product", "right": "code"}]}]}
        self.assertEqual(self.client.post("/api/joins/preview", headers=viewer,
                                          json=body).status_code, 200)
        self.assertEqual(self.client.post("/api/runs", headers=viewer,
                                          json={"goal": "Sales", **body}).status_code, 403)


class JoinMigrationTests(unittest.TestCase):

    def test_a_database_from_before_joins_gains_the_column(self):
        from server.storage import open_store

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            conn = sqlite3.connect(path)
            conn.execute("""CREATE TABLE runs (
              id TEXT PRIMARY KEY, goal TEXT NOT NULL, dataset_name TEXT NOT NULL,
              dataset_text TEXT NOT NULL, state TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT)""")
            conn.commit()
            conn.close()
            open_store(sqlite_path=str(path))
            names = [row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(runs)")]
            self.assertIn("joins_json", names)
            open_store(sqlite_path=str(path))  # repeatable


if __name__ == "__main__":
    unittest.main()
