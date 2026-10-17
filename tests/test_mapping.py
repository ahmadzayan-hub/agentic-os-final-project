"""Column mapping (ADR 0025): the owner says what each column is.

The reading rules are tested on the values real exports contain, because
a mapping is only as good as what it can read. The pipeline is tested on
mapped data and on unmapped data, which must run exactly as before. The
API is tested on SQLite and PostgreSQL, and across the tenant boundary.
"""

import csv
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from server import analytics
from server import mapping as m
from tests.test_runs import FASTAPI_AVAILABLE, PG_TEST_URL, _postgres_available

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from server.app import create_app

from server.auth import issue_local_test_token

SECRET = "mapping-test-secret-not-used-anywhere-else"


def rows_of(text):
    return m.table(text)


def mapping_for(roles, measure, dimension=None, date_order="auto", grain="auto"):
    return {"roles": roles, "measure": measure, "dimension": dimension,
            "date_order": date_order, "grain": grain}


# A shop's export: day-first dates across a year boundary, so text order
# and time order disagree; money with signs and grouping; a numeric store
# code; a row ID; and free-text notes.
SHOP_ROWS = [
    ("1", "15/11/2024", "3", "North", "$1,200", "first order"),
    ("2", "20/11/2024", "1", "South", "$800", "repeat"),
    ("3", "05/12/2024", "3", "North", "$1,500", "gift wrap"),
    ("4", "18/12/2024", "2", "South", "(200)", "refund"),
    ("5", "09/01/2025", "1", "North", "$1,100", "new customer"),
    ("6", "22/01/2025", "2", "South", "$950", "late delivery"),
    ("7", "03/02/2025", "3", "North", "$1,300", "bulk"),
    ("8", "14/02/2025", "1", "South", "$1,050", "card"),
    ("9", "28/02/2025", "2", "North", "$1,250", "cash"),
    ("10", "13/03/2025", "3", "South", "$1,400", "online"),
    ("11", "not a date", "1", "North", "$900", "pending"),
    ("12", "27/03/2025", "2", "South", "$1,000", "promo"),
]
SHOP_CSV = "row_id,order_date,store_id,region,amount,notes\n" + "\n".join(
    ",".join(f'"{v}"' if "," in v else v for v in row) for row in SHOP_ROWS) + "\n"
SHOP_MAPPING = mapping_for(
    {"row_id": "ignore", "order_date": "date", "store_id": "dimension",
     "region": "dimension", "amount": "measure", "notes": "ignore"},
    measure="amount", dimension="region", grain="month")


class NumberTests(unittest.TestCase):

    def test_the_values_a_measure_really_holds(self):
        cases = {
            "1200": 1200.0, "-3.5": -3.5, "1e3": 1000.0,
            "$1,200": 1200.0, "€ 3.5": 3.5, "SAR 5,000": 5000.0, "5,000 ر.س": 5000.0,
            "(300)": -300.0, "-$5": -5.0, "12%": 12.0, "1 200": 1200.0,
            "١٢٠٠": 1200.0, "١٬٢٠٠٫٥": 1200.5, "۱۲۳": 123.0, "−7": -7.0,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(m.parse_number(text), expected)

    def test_a_separator_that_could_mean_two_things_is_refused(self):
        # A decimal comma in much of the world, a thousands one in the rest:
        # refusing it is counted and reported; misreading it is silent.
        for text in ("12,5", "1.234,56", "1,20,000", "1,2", "abc", "", "  ", "nan", "inf"):
            with self.subTest(text=text):
                self.assertIsNone(m.parse_number(text))

    def test_non_text_values(self):
        self.assertEqual(m.parse_number(7), 7.0)
        self.assertIsNone(m.parse_number(None))
        self.assertIsNone(m.parse_number(True))


class DateTests(unittest.TestCase):

    def label(self, text, grain="day", order="day-first"):
        period = m.parse_date(text, order)
        return period.label(grain) if period else None

    def test_the_formats_a_date_column_really_holds(self):
        cases = [
            ("2025-03-14", "day", "2025-03-14"), ("2025/3/4", "day", "2025-03-04"),
            ("2025.03.04", "day", "2025-03-04"), ("2025-03-14T10:00:00Z", "day", "2025-03-14"),
            ("2025-03-14 10:00", "day", "2025-03-14"), ("2025-03", "month", "2025-03"),
            ("3/2025", "month", "2025-03"), ("2025", "year", "2025"),
            ("2025-Q1", "quarter", "2025-Q1"), ("Q3 2024", "quarter", "2024-Q3"),
            ("2024q4", "quarter", "2024-Q4"), ("13/04/2025", "day", "2025-04-13"),
            ("Jan 2025", "month", "2025-01"), ("January 15, 2025", "day", "2025-01-15"),
            ("15-Jan-2025", "day", "2025-01-15"), ("Jan-25", "month", "2025-01"),
            ("sept 2024", "month", "2024-09"), ("يناير 2025", "month", "2025-01"),
            ("١٥ مارس ٢٠٢٥", "day", "2025-03-15"), ("كانون الثاني 2025", "month", "2025-01"),
            ("1/2/99", "day", "1999-02-01"), ("1/2/05", "day", "2005-02-01"),
        ]
        for text, grain, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.label(text, grain), expected)

    def test_what_is_not_a_date(self):
        for text in ("2025-02-30", "2025-13", "13/13/2025", "1234.5", "2025.03", "26.5",
                     "9999-01-01", "hello", "", "Q5 2025", "Jan Feb 2025"):
            with self.subTest(text=text):
                self.assertIsNone(m.parse_date(text))

    def test_the_order_decides_an_ambiguous_day(self):
        self.assertEqual(self.label("03/04/2025", order="day-first"), "2025-04-03")
        self.assertEqual(self.label("03/04/2025", order="month-first"), "2025-03-04")

    def test_a_column_proves_its_order_or_is_asked(self):
        self.assertEqual(m.resolve_order(["13/04/2025", "03/04/2025"]), ("day-first", False))
        self.assertEqual(m.resolve_order(["04/13/2025", "03/04/2025"]), ("month-first", False))
        self.assertEqual(m.resolve_order(["03/04/2025", "05/06/2025"]), ("day-first", True))
        # Where both readings agree there is nothing to ask.
        self.assertEqual(m.resolve_order(["03/03/2025", "2025-01-01"]), ("day-first", False))
        self.assertEqual(m.resolve_order(["03/04/2025"], "month-first"), ("month-first", False))

    def test_a_coarse_value_cannot_be_placed_in_a_finer_period(self):
        year = m.parse_date("2025")
        self.assertIsNone(year.label("month"))
        self.assertEqual(year.label("year"), "2025")
        self.assertEqual(m.parse_date("2025-05-17").label("quarter"), "2025-Q2")

    def test_auto_grain_keeps_precision_until_there_are_too_many_periods(self):
        months = [f"{y}-{mo:02d}" for y in (2023, 2024, 2025) for mo in range(1, 13)]
        labels, grain, _ = m.period_labels(months)
        self.assertEqual((grain, len(set(labels))), ("month", 36))
        days = [f"2025-{mo:02d}-{d:02d}" for mo in (1, 2) for d in range(1, 29)]
        self.assertEqual(m.period_labels(days)[1], "month")
        eight_years = [f"{y}-{mo:02d}" for y in range(2017, 2025) for mo in range(1, 13)]
        self.assertEqual(m.period_labels(eight_years)[1], "quarter")  # 96 months, 32 quarters
        decade = [f"{y}-{mo:02d}" for y in range(2015, 2025) for mo in range(1, 13)]
        self.assertEqual(m.period_labels(decade)[1], "year")  # 40 quarters is too many
        self.assertEqual(m.period_labels(days, grain="day")[1], "day")
        # A stray year among days does not drag the whole column to years.
        self.assertEqual(m.period_labels(["2025-01-01"] * 20 + ["2025"])[1], "day")

    def test_forecast_labels_continue_the_calendar(self):
        self.assertEqual(m.next_period_labels("2025-Q4", 2), ["2026-Q1", "2026-Q2"])
        self.assertEqual(m.next_period_labels("2025", 2), ["2026", "2027"])
        self.assertEqual(m.next_period_labels("2024-02-28", 2), ["2024-02-29", "2024-03-01"])
        self.assertIsNone(m.next_period_labels("week 3", 1))
        self.assertEqual(analytics._next_labels(["2025-Q3"], 1), ["2025-Q4"])
        self.assertEqual(analytics._next_labels(["2025-11"], 2), ["2025-12", "2026-01"])
        self.assertEqual(analytics._next_labels(["Spring"], 1), ["next period +1"])


class SuggestionTests(unittest.TestCase):

    def suggest(self, text, metrics=()):
        columns, rows = rows_of(text)
        return m.suggest(columns, rows, metrics)

    def test_the_sample_is_suggested_exactly_as_it_was_guessed(self):
        s = self.suggest(analytics.sample_dataset())
        self.assertEqual(s["roles"], {"month": "date", "region": "dimension",
                                      "category": "dimension", "revenue": "measure",
                                      "units": "measure"})
        self.assertEqual((s["measure"], s["dimension"]), ("revenue", "region"))

    def test_each_column_gets_a_role_and_a_reason(self):
        s = self.suggest(SHOP_CSV)
        self.assertEqual(s["roles"], {"row_id": "ignore", "order_date": "date",
                                      "store_id": "dimension", "region": "dimension",
                                      "amount": "measure", "notes": "ignore"})
        self.assertEqual(s["reasons"]["row_id"]["code"], "identifier")
        self.assertEqual(s["reasons"]["store_id"]["code"], "coded_dimension")
        self.assertEqual(s["reasons"]["notes"]["code"], "unique_text")
        self.assertIn("%", s["reasons"]["amount"]["en"])
        self.assertTrue(all(r["ar"] for r in s["reasons"].values()))
        self.assertEqual(s["measure"], "amount")

    def test_personal_data_a_second_date_and_empty_columns_are_left_out(self):
        text = "email,created,updated,blank,score\n" + "\n".join(
            f"u{i}@x.org,2025-01-{i + 1:02d},2025-02-{i + 1:02d},,{i * 1.5}" for i in range(12))
        s = self.suggest(text)
        self.assertEqual(s["roles"], {"email": "ignore", "created": "date", "updated": "ignore",
                                      "blank": "ignore", "score": "measure"})
        self.assertEqual(s["reasons"]["updated"]["code"], "second_date")

    def test_a_year_column_is_a_date_only_when_named_like_one(self):
        text = "year,units\n" + "\n".join(f"{2010 + i},{2000 + i * 3}" for i in range(12))
        self.assertEqual(self.suggest(text)["roles"], {"year": "date", "units": "measure"})

    def test_the_glossary_still_chooses_among_measures(self):
        metrics = [{"name": "units", "columns": ["units"], "certified": True}]
        s = self.suggest(analytics.sample_dataset(), metrics)
        self.assertEqual(s["measure"], "units")

    def test_an_ambiguous_date_column_is_flagged_in_the_profile(self):
        text = "day,amount\n" + "\n".join(f"0{i}/0{i + 1}/2025,{i}" for i in range(1, 9))
        columns, rows = rows_of(text)
        profile = {p["name"]: p for p in m.profile(columns, rows)}
        self.assertTrue(profile["day"]["ambiguous_order"])
        self.assertEqual(profile["day"]["type"], "date")

    def test_a_large_table_is_profiled_on_an_even_sample(self):
        rows = [{"n": str(i)} for i in range(25_000)]
        sample = m.sample(rows, 10)
        self.assertEqual(len(sample), 10)
        self.assertEqual(sample[0]["n"], "0")
        self.assertEqual(sample[-1]["n"], "22500")
        self.assertIs(m.sample(rows[:5], 10)[0], rows[0])


class ValidationTests(unittest.TestCase):

    def setUp(self):
        self.columns, self.rows = rows_of(SHOP_CSV)

    def problems(self, mapping):
        with self.assertRaises(m.MappingError) as caught:
            m.validate(mapping, self.columns, self.rows)
        return caught.exception

    def test_a_good_mapping_is_saved_in_column_order(self):
        clean = m.validate(dict(SHOP_MAPPING, roles=dict(reversed(SHOP_MAPPING["roles"].items()))),
                           self.columns, self.rows)
        self.assertEqual(list(clean["roles"]), self.columns)
        self.assertEqual(clean["version"], m.MAPPING_VERSION)
        self.assertEqual(clean["measure"], "amount")

    def test_every_problem_is_reported_at_once(self):
        error = self.problems(mapping_for(
            {"order_date": "date", "region": "measure", "notes": "date", "ghost": "measure",
             "amount": "weight"}, measure="row_id", dimension="amount"))
        found = {(p.field, p.column) for p in error.problems}
        self.assertIn(("roles", "ghost"), found)  # not a column
        self.assertIn(("roles", "row_id"), found)  # no role
        self.assertIn(("roles", "amount"), found)  # not a role
        self.assertIn(("roles", "notes"), found)  # a second date
        self.assertIn(("roles", "region"), found)  # text as a measure
        self.assertIn(("measure", "row_id"), found)
        self.assertIn(("dimension", "amount"), found)

    def test_a_text_measure_is_explained_with_counts_in_both_languages(self):
        roles = dict(SHOP_MAPPING["roles"], region="measure")
        error = self.problems(dict(SHOP_MAPPING, roles=roles, measure="region"))
        problem = next(p for p in error.problems if p.column == "region" and p.field == "roles")
        self.assertIn("0 of 12 filled cells are numbers", problem.en)
        self.assertIn("0 فقط من 12", problem.ar)

    def test_no_measure_at_all(self):
        roles = dict(SHOP_MAPPING["roles"], amount="ignore")
        error = self.problems(dict(SHOP_MAPPING, roles=roles))
        self.assertEqual(error.problems[0].field, "measure")

    def test_an_ambiguous_date_order_is_asked_for(self):
        text = "day,amount\n" + "\n".join(f"0{i}/0{i + 1}/2025,{i}" for i in range(1, 9))
        columns, rows = rows_of(text)
        mapping = mapping_for({"day": "date", "amount": "measure"}, "amount")
        with self.assertRaises(m.MappingError) as caught:
            m.validate(mapping, columns, rows)
        self.assertEqual(caught.exception.problems[0].field, "date_order")
        self.assertIn("01/02/2025", caught.exception.problems[0].en)
        clean = m.validate(dict(mapping, date_order="month-first"), columns, rows)
        self.assertEqual(clean["date_order"], "month-first")

    def test_a_grain_finer_than_the_dates_is_refused(self):
        text = "year,amount\n" + "\n".join(f"{2015 + i},{i}" for i in range(8))
        columns, rows = rows_of(text)
        mapping = mapping_for({"year": "date", "amount": "measure"}, "amount", grain="month")
        with self.assertRaises(m.MappingError) as caught:
            m.validate(mapping, columns, rows)
        self.assertEqual(caught.exception.problems[0].field, "grain")
        self.assertEqual(m.validate(dict(mapping, grain="year"), columns, rows)["grain"], "year")

    def test_unknown_order_and_grain(self):
        error = self.problems(dict(SHOP_MAPPING, date_order="sideways", grain="fortnight"))
        self.assertEqual({p.field for p in error.problems}, {"date_order", "grain"})

    def test_the_refusal_reads_in_the_readers_language(self):
        error = self.problems(dict(SHOP_MAPPING, measure=None))
        self.assertEqual(error.detail()["message"], "The mapping was not saved: 1 problem to fix.")
        self.assertEqual(error.detail("ar")["message"], "لم يُحفظ الربط: مشكلة واحدة تحتاج إلى إصلاح.")
        self.assertEqual(error.detail("ar")["errors"][0]["field"], "measure")


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class MappingApiTestCase(unittest.TestCase):
    """The mapping API and mapped runs, against SQLite."""

    def database_config(self):
        return {"database_file": str(self.root / "agentic.db")}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        config = {"agent_name": "Mapping Test", "memory_file": str(self.root / "memory.json"),
                  "vault_dir": str(self.root / "vault")}
        config.update(self.database_config())
        path = self.root / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        self.app = create_app(path)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def upload(self, text, name="shop.csv"):
        response = self.client.post(f"/api/datasets?name={name}", content=text.encode())
        self.assertIn(response.status_code, (200, 201), response.text)
        return response.json()["dataset"]["id"]

    def run_to_gate(self, **body):
        run = self.client.post("/api/runs", json={"goal": "Analyse the shop", **body}).json()
        for _ in range(60):
            run = self.client.post(f"/api/runs/{run['id']}/advance").json()
            if run["state"] not in ("queued", "running"):
                break
        self.assertEqual(run["state"], "awaiting_approval", run.get("error"))
        return run

    def task(self, run, role):
        return next(t for t in run["tasks"] if t["role"] == role)

    def result(self, run, role):
        # Stage outputs hold rows, so the API never returns them; the
        # stored task result is the record of what the stage decided.
        stored = next(t for t in self.app.state.store.get_tasks(run["id"]) if t["role"] == role)
        return json.loads(stored["result_json"])

    def output(self, run, role):
        return self.result(run, role)["output"]

    def claim_ids(self, run):
        return {c["id"] for t in run["tasks"] for c in t["claims"]}

    def dataset_of(self, run):
        return self.app.state.store.get_run(run["id"])["dataset_id"]

    def test_the_detail_holds_preview_profile_and_suggestion(self):
        dataset_id = self.upload(SHOP_CSV)
        detail = self.client.get(f"/api/datasets/{dataset_id}?language=ar").json()
        self.assertEqual(len(detail["preview"]), m.PREVIEW_ROWS)
        self.assertEqual(detail["preview"][0], list(SHOP_ROWS[0]))
        self.assertEqual((detail["row_count"], detail["profiled_rows"]), (12, 12))
        self.assertIsNone(detail["mapping"])
        self.assertFalse(detail["dataset"]["mapped"])
        columns = {c["name"]: c for c in detail["columns"]}
        self.assertEqual(columns["order_date"]["type"], "date")
        self.assertEqual(columns["amount"]["suggested_role"], "measure")
        self.assertIn("أرقام", columns["amount"]["reason"])
        self.assertEqual(detail["suggestion"]["measure"], "amount")
        self.assertNotIn("reasons", detail["suggestion"])

    def test_save_list_and_clear(self):
        dataset_id = self.upload(SHOP_CSV)
        saved = self.client.put(f"/api/datasets/{dataset_id}/mapping", json=SHOP_MAPPING)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["mapping"]["dimension"], "region")
        listed = self.client.get("/api/datasets").json()["datasets"][0]
        self.assertTrue(listed["mapped"])
        self.assertIsNotNone(listed["mapping_updated_at"])
        cleared = self.client.delete(f"/api/datasets/{dataset_id}/mapping")
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()["mapping"])
        self.assertFalse(self.client.get("/api/datasets").json()["datasets"][0]["mapped"])

    def test_a_refusal_lists_each_problem_by_field(self):
        dataset_id = self.upload(SHOP_CSV)
        roles = dict(SHOP_MAPPING["roles"], region="measure")
        response = self.client.put(f"/api/datasets/{dataset_id}/mapping?language=ar",
                                   json=dict(SHOP_MAPPING, roles=roles, dimension="amount"))
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertTrue(detail["message"].startswith("لم يُحفظ الربط"))
        self.assertEqual({(e["field"], e["column"]) for e in detail["errors"]},
                         {("roles", "region"), ("dimension", "amount")})
        self.assertIsNone(self.client.get(f"/api/datasets/{dataset_id}").json()["mapping"])

    def test_an_unknown_dataset_is_a_404(self):
        self.assertEqual(self.client.get("/api/datasets/nope").status_code, 404)
        self.assertEqual(self.client.put("/api/datasets/nope/mapping", json=SHOP_MAPPING).status_code,
                         404)
        self.assertEqual(self.client.delete("/api/datasets/nope/mapping").status_code, 404)

    def test_a_mapped_run_follows_the_mapping(self):
        dataset_id = self.upload(SHOP_CSV)
        self.client.put(f"/api/datasets/{dataset_id}/mapping", json=SHOP_MAPPING)
        run = self.run_to_gate(dataset_id=dataset_id)
        self.assertEqual(self.output(run, "profiler")["numeric_columns"], ["amount"])
        governance = self.output(run, "governance")
        self.assertEqual((governance["measure"], governance["source"]),
                         ("amount", "the owner's column mapping"))
        cleaner = self.output(run, "cleaner")
        self.assertEqual((cleaner["date_grain"], cleaner["date_order"],
                          cleaner["dates_unreadable"]), ("month", "day-first", 1))
        prep = self.output(run, "preparer")
        self.assertEqual((prep["group_col"], prep["date_col"]), ("region", "order_date"))
        # Time order, not text order: 15/11/2024 would sort after 13/03/2025.
        self.assertEqual(list(prep["trend"]),
                         ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03"])
        self.assertEqual(prep["trend"]["2024-12"], 1300.0)  # $1,500 and (200)
        # Every row counts in the total, including the one whose date did not
        # read; only the trend leaves it out.
        self.assertEqual(prep["total"], 12250.0)
        self.assertEqual(sum(prep["trend"].values()), 12250.0 - 900.0)
        claims = self.claim_ids(run)
        self.assertIn("cl_mapping", claims)
        self.assertIn("cl_dates_unread", claims)
        self.assertIn("(column mapping)", self.task(run, "preparer")["summary"])

    def test_the_run_keeps_the_mapping_it_started_with(self):
        dataset_id = self.upload(SHOP_CSV)
        self.client.put(f"/api/datasets/{dataset_id}/mapping", json=SHOP_MAPPING)
        run = self.client.post("/api/runs", json={"goal": "Analyse the shop",
                                                  "dataset_id": dataset_id}).json()
        self.client.put(f"/api/datasets/{dataset_id}/mapping",
                        json=dict(SHOP_MAPPING, dimension="store_id"))
        for _ in range(60):
            run = self.client.post(f"/api/runs/{run['id']}/advance").json()
            if run["state"] not in ("queued", "running"):
                break
        self.assertEqual(self.output(run, "preparer")["group_col"], "region")
        later = self.run_to_gate(dataset_id=dataset_id)
        self.assertEqual(self.output(later, "preparer")["group_col"], "store_id")

    def test_a_mapping_that_matches_the_old_guesses_gives_the_same_figures(self):
        unmapped = self.run_to_gate()  # the sample, as every run before ADR 0025
        dataset_id = self.dataset_of(unmapped)
        suggestion = self.client.get(f"/api/datasets/{dataset_id}").json()["suggestion"]
        self.assertEqual(self.client.put(f"/api/datasets/{dataset_id}/mapping",
                                         json=suggestion).status_code, 200)
        mapped = self.run_to_gate(dataset_id=dataset_id)
        for role in ("preparer", "descriptive", "predictive"):
            with self.subTest(role=role):
                before, after = self.output(unmapped, role), self.output(mapped, role)
                for key in ("total", "trend", "groups", "forecast"):
                    if key in before:
                        self.assertEqual(before[key], after[key], key)

    def test_unmapped_data_is_analysed_as_before(self):
        run = self.run_to_gate()
        governance = self.output(run, "governance")
        self.assertEqual((governance["measure"], governance["source"]), ("revenue", "column name"))
        prep = self.output(run, "preparer")
        self.assertEqual((prep["date_col"], prep["group_col"], prep["date_grain"]),
                         ("month", "region", None))
        self.assertFalse(self.output(run, "collector")["mapped"])
        self.assertNotIn("cl_mapping", self.claim_ids(run))

    def test_pasted_data_ignores_a_saved_mapping_of_the_same_content(self):
        dataset_id = self.upload(SHOP_CSV)
        self.client.put(f"/api/datasets/{dataset_id}/mapping", json=SHOP_MAPPING)
        run = self.run_to_gate(dataset_text=SHOP_CSV, dataset_name="pasted")
        self.assertEqual(self.dataset_of(run), dataset_id)
        self.assertFalse(self.output(run, "collector")["mapped"])

    def test_clearing_the_mapping_returns_runs_to_detection(self):
        dataset_id = self.upload(SHOP_CSV)
        self.client.put(f"/api/datasets/{dataset_id}/mapping", json=SHOP_MAPPING)
        self.client.delete(f"/api/datasets/{dataset_id}/mapping")
        run = self.run_to_gate(dataset_id=dataset_id)
        self.assertFalse(self.output(run, "collector")["mapped"])

    def test_a_quarterly_mapping_forecasts_in_quarters(self):
        text = "period,sales\n" + "\n".join(
            f"{2022 + i // 4}-Q{i % 4 + 1},{100 + i * 10}" for i in range(12))
        dataset_id = self.upload(text, "quarters.csv")
        mapping = mapping_for({"period": "date", "sales": "measure"}, "sales")
        self.assertEqual(self.client.put(f"/api/datasets/{dataset_id}/mapping",
                                         json=mapping).status_code, 200)
        run = self.run_to_gate(dataset_id=dataset_id)
        forecast = self.output(run, "predictive").get("forecast") or []
        self.assertTrue(forecast)
        self.assertEqual(forecast[0]["label"], "2025-Q1")


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
@unittest.skipUnless(_postgres_available(), "test PostgreSQL is not reachable")
class MappingApiPostgresTestCase(MappingApiTestCase):
    """The same API and runs against the hosted-mode PostgresStore."""

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
class MappingTenancyTests(unittest.TestCase):

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

    def test_another_owner_cannot_read_map_or_clear(self):
        alice = self.auth("alice")
        dataset_id = self.client.post("/api/datasets?name=shop.csv", content=SHOP_CSV.encode(),
                                      headers=alice).json()["dataset"]["id"]
        mallory = self.auth("mallory")
        self.assertEqual(self.client.get(f"/api/datasets/{dataset_id}", headers=mallory).status_code,
                         404)
        self.assertEqual(self.client.put(f"/api/datasets/{dataset_id}/mapping", headers=mallory,
                                         json=SHOP_MAPPING).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/datasets/{dataset_id}/mapping",
                                            headers=mallory).status_code, 404)
        self.assertIsNone(self.client.get(f"/api/datasets/{dataset_id}",
                                          headers=alice).json()["mapping"])

    def test_a_viewer_can_read_but_not_map(self):
        dataset_id = self.client.post("/api/datasets?name=shop.csv", content=SHOP_CSV.encode(),
                                      headers=self.auth("team")).json()["dataset"]["id"]
        viewer = self.auth("team", role="viewer")
        self.assertEqual(self.client.get(f"/api/datasets/{dataset_id}", headers=viewer).status_code,
                         200)
        self.assertEqual(self.client.put(f"/api/datasets/{dataset_id}/mapping", headers=viewer,
                                         json=SHOP_MAPPING).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/datasets/{dataset_id}/mapping",
                                            headers=viewer).status_code, 403)
        self.assertEqual(self.client.get(f"/api/datasets/{dataset_id}").status_code, 401)


class MappingMigrationTests(unittest.TestCase):

    def test_a_database_from_before_mapping_gains_its_columns(self):
        from server.storage import open_store

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            conn = sqlite3.connect(path)
            conn.execute("""CREATE TABLE datasets (
              id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, name TEXT NOT NULL,
              content TEXT NOT NULL, byte_size INTEGER NOT NULL,
              owner TEXT NOT NULL, created_at TEXT NOT NULL)""")
            conn.execute("""CREATE TABLE runs (
              id TEXT PRIMARY KEY, goal TEXT NOT NULL, dataset_name TEXT NOT NULL,
              dataset_text TEXT NOT NULL, state TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT)""")
            conn.execute("INSERT INTO datasets VALUES ('d1','x','old.csv','a,b\n1,2\n',8,"
                         "'local-owner','2026-01-01T00:00:00+00:00')")
            conn.commit()
            conn.close()
            store = open_store(sqlite_path=str(path))
            self.assertIsNone(store.list_datasets("local-owner")[0]["mapping_updated_at"])
            self.assertIn("mapping_json", store.get_dataset("d1"))
            names = [row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(runs)")]
            self.assertIn("mapping_json", names)
            open_store(sqlite_path=str(path))  # repeatable


if __name__ == "__main__":
    unittest.main()
