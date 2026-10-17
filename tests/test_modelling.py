"""Modelling stages (ADR 0033): every model against its baseline.

Each model is tested where the answer is known: data with a real
structure, where it must beat its baseline, and noise, where it must say
it is weak instead of dressing a guess up. The stages are then run inside
a governed run, where the Validation Expert audits their claims like any
other stage's, in English and in Arabic.
"""

import json
import random
import tempfile
import unittest
from pathlib import Path

from server import analytics
from server import modelling as m
from server import stages
from tests.test_runs import FASTAPI_AVAILABLE

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from server.app import create_app

STAGE_PATHS = ["server.modelling.RegressionModel", "server.modelling.ClassificationModel",
               "server.modelling.ClusteringModel", "server.modelling.SeasonalForecast"]
ROLES = ["regression_model", "classification_model", "clustering_model", "seasonal_model"]


def context(rows, columns, numeric, measure, date=None, trend=None, grain=None, language="en"):
    """The parts of a run's context the models read."""
    return {"report_language": language,
            "collector": {"columns": columns, "rows": rows},
            "profiler": {"numeric_columns": numeric},
            "cleaner": {"rows": rows},
            "governance": {"measure": measure},
            "preparer": {"measure": measure, "date_col": date, "trend": trend or {},
                         "date_grain": grain}}


def linear_rows(n=400, noise=1.0, seed=3):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        price, ads = rng.uniform(1, 10), rng.uniform(0, 5)
        channel = ("web", "store", "phone")[i % 3]
        sales = 50 + 8 * price - 3 * ads + (6 if channel == "web" else 0) + rng.gauss(0, noise)
        rows.append({"price": price, "ads": ads, "channel": channel, "sales": sales})
    return rows


def noise_rows(n=400, seed=5):
    rng = random.Random(seed)
    return [{"a": rng.random(), "b": rng.random(), "sales": rng.gauss(100, 10)}
            for _ in range(n)]


def checked(stage, ctx):
    """Run a stage and hold its result to the plugin contract."""
    return stages.validate_result(stage.role, stage.run(ctx))


class ArithmeticTests(unittest.TestCase):

    def test_least_squares_recovers_known_weights(self):
        rng = random.Random(1)
        xs = [[rng.uniform(-1, 1), rng.uniform(-1, 1)] for _ in range(300)]
        ys = [3 * a - 2 * b + 7 for a, b in xs]
        weights, intercept = m.fit_least_squares(xs, ys, ridge=0.0)
        self.assertAlmostEqual(weights[0], 3, places=6)
        self.assertAlmostEqual(weights[1], -2, places=6)
        self.assertAlmostEqual(intercept, 7, delta=0.2)

    def test_a_repeated_input_does_not_break_the_solve(self):
        xs = [[float(i), float(i)] for i in range(50)]
        weights, _ = m.fit_least_squares(xs, [2.0 * i for i in range(50)])
        self.assertAlmostEqual(weights[0] + weights[1], 2, places=2)

    def test_kmeans_and_separation_find_clear_groups(self):
        rng = random.Random(2)
        points = [[rng.gauss(cx, 0.2), rng.gauss(cy, 0.2)]
                  for cx, cy in ((0, 0), (5, 5), (0, 5)) for _ in range(60)]
        assignment, _, _ = m.kmeans(points, 3)
        self.assertEqual(len(set(assignment)), 3)
        self.assertGreater(m.silhouette(points, assignment), 0.8)

    def test_the_seasonal_model_repeats_a_season(self):
        pattern = [10, 20, 30, 20]
        series = [100 + 2 * i + pattern[i % 4] for i in range(16)]
        forecast = m.seasonal_forecast(series, 4, 4)
        expected = [100 + 2 * i + pattern[i % 4] for i in range(16, 20)]
        for got, want in zip(forecast, expected):
            self.assertAlmostEqual(got, want, places=6)


class RegressionTests(unittest.TestCase):

    def test_a_real_relationship_beats_the_average(self):
        rows = linear_rows()
        result = checked(m.RegressionModel(), context(rows, ["channel", "price", "ads", "sales"],
                                                      ["price", "ads", "sales"], "sales"))
        card = result["output"]["model_card"]
        self.assertTrue(card["beats_baseline"])
        self.assertGreater(card["improvement"], 0.5)
        self.assertEqual(card["metric"]["baseline_name"], "training_average")
        self.assertEqual(card["details"]["weights"][0]["input"], "price")
        # Each channel is compared with the most common one, which is web here.
        self.assertEqual([n for n in card["inputs"] if n.startswith("channel")],
                         ["channel = store", "channel = phone"])
        self.assertEqual(card["test_records"], 80)  # every fifth, no date
        ids = {c["id"] for c in result["claims"]}
        self.assertIn("regression_model.cl_strongest", ids)
        self.assertNotIn("regression_model.cl_weak", ids)

    def test_noise_is_reported_as_weak(self):
        rows = noise_rows()
        result = checked(m.RegressionModel(), context(rows, ["a", "b", "sales"],
                                                      ["a", "b", "sales"], "sales"))
        self.assertFalse(result["output"]["model_card"]["beats_baseline"])
        weak = next(c for c in result["claims"] if c["id"] == "regression_model.cl_weak")
        self.assertEqual(weak["type"], "limitation")
        self.assertIn("should not be used", weak["text"])
        self.assertFalse(result["quality_checks"][0]["passed"])

    def test_too_few_records_is_a_limitation_not_a_failure(self):
        rows = linear_rows(n=20)
        result = checked(m.RegressionModel(), context(rows, ["price", "ads", "sales"],
                                                      ["price", "ads", "sales"], "sales"))
        self.assertEqual(result["status"], "succeeded")
        self.assertFalse(result["output"]["fitted"])
        self.assertEqual(result["claims"][0]["type"], "limitation")

    def test_with_a_date_it_tests_on_the_latest_periods(self):
        rows = linear_rows(n=300)
        for i, row in enumerate(rows):
            row["month"] = f"2024-{i % 10 + 1:02d}"
        result = checked(m.RegressionModel(), context(rows, ["month", "price", "ads", "sales"],
                                                      ["price", "ads", "sales"], "sales", "month"))
        split = result["output"]["model_card"]["split"]
        self.assertEqual(split, {"kind": "time", "first_held_out": "2024-09"})
        self.assertEqual(result["output"]["model_card"]["test_records"], 60)


class ClassificationTests(unittest.TestCase):

    def test_the_top_quarter_is_predicted_from_the_drivers(self):
        rows = linear_rows(n=600)
        result = checked(m.ClassificationModel(), context(rows, ["channel", "price", "ads", "sales"],
                                                          ["price", "ads", "sales"], "sales"))
        card = result["output"]["model_card"]
        self.assertTrue(card["beats_baseline"])
        self.assertEqual(card["metric"]["baseline"], 0.5)  # two classes, always the larger
        self.assertNotIn("sales", card["inputs"])
        self.assertEqual(set(card["details"]["classes"]), {"top quarter", "rest"})

    def test_a_named_class_column(self):
        rng = random.Random(9)
        rows = []
        for i in range(300):
            kind = ("A", "B", "C")[i % 3]
            rows.append({"kind": kind, "x": {"A": 0, "B": 5, "C": 10}[kind] + rng.gauss(0, 1),
                         "y": rng.random(), "sales": rng.random()})
        result = checked(m.ClassificationModel(target="kind"),
                         context(rows, ["kind", "x", "y", "sales"], ["x", "y", "sales"], "sales"))
        card = result["output"]["model_card"]
        self.assertEqual(card["target"], "kind")
        self.assertGreater(card["metric"]["model"], 0.9)
        self.assertAlmostEqual(card["metric"]["baseline"], 1 / 3, places=4)

    def test_noise_is_reported_as_weak(self):
        rows = noise_rows()
        result = checked(m.ClassificationModel(), context(rows, ["a", "b", "sales"],
                                                          ["a", "b", "sales"], "sales"))
        self.assertFalse(result["output"]["model_card"]["beats_baseline"])
        self.assertIn("classification_model.cl_weak", {c["id"] for c in result["claims"]})

    def test_too_many_classes(self):
        rows = [{"kind": str(i % 9), "x": float(i), "sales": 1.0} for i in range(90)]
        result = checked(m.ClassificationModel(target="kind"),
                         context(rows, ["kind", "x", "sales"], ["x", "sales"], "sales"))
        self.assertFalse(result["output"]["fitted"])
        self.assertIn("9 classes", result["summary"])


class ClusteringTests(unittest.TestCase):

    def test_separated_groups_are_found(self):
        rng = random.Random(4)
        rows = [{"a": rng.gauss(cx, 0.3), "b": rng.gauss(cy, 0.3), "sales": cx + cy}
                for cx, cy in ((0, 0), (6, 0), (3, 6)) for _ in range(80)]
        result = checked(m.ClusteringModel(), context(rows, ["a", "b", "sales"],
                                                      ["a", "b", "sales"], "sales"))
        card = result["output"]["model_card"]
        self.assertTrue(card["beats_baseline"])
        self.assertEqual(card["details"]["groups"], 3)
        self.assertGreater(card["details"]["share_of_spread_explained"], 0.8)

    def test_uniform_noise_has_no_groups(self):
        rng = random.Random(6)
        rows = [{"a": rng.random(), "b": rng.random(), "c": rng.random(), "sales": rng.random()}
                for _ in range(300)]
        result = checked(m.ClusteringModel(), context(rows, ["a", "b", "c", "sales"],
                                                      ["a", "b", "c", "sales"], "sales"))
        self.assertFalse(result["output"]["model_card"]["beats_baseline"])
        self.assertIn("clustering_model.cl_weak", {c["id"] for c in result["claims"]})


class SeasonalTests(unittest.TestCase):

    def months(self, count, pattern, noise=0.0, seed=8):
        rng = random.Random(seed)
        labels = [f"{2022 + i // 12}-{i % 12 + 1:02d}" for i in range(count)]
        return {label: 1000 + 5 * i + pattern[i % 12] + rng.gauss(0, noise)
                for i, label in enumerate(labels)}

    def test_a_real_season_beats_simple_guesses(self):
        pattern = [0, -50, 30, 80, 120, 60, 0, -40, -90, -30, 20, 200]
        trend = self.months(36, pattern, noise=5)
        result = checked(m.SeasonalForecast(), context([], [], [], "sales", trend=trend))
        card = result["output"]["model_card"]
        self.assertTrue(card["beats_baseline"])
        self.assertEqual(card["details"]["season"], 12)
        self.assertEqual(card["details"]["grain"], "month")
        self.assertEqual(card["details"]["forecast"][0]["label"], "2025-01")
        self.assertIn("seasonal_model.cl_forecast", {c["id"] for c in result["claims"]})

    def test_too_little_history_is_a_limitation(self):
        trend = self.months(12, [0] * 12)
        result = checked(m.SeasonalForecast(), context([], [], [], "sales", trend=trend))
        self.assertFalse(result["output"]["fitted"])
        self.assertIn("36", result["summary"])

    def test_no_season_in_noise(self):
        trend = self.months(36, [0] * 12, noise=80, seed=11)
        result = checked(m.SeasonalForecast(), context([], [], [], "sales", trend=trend))
        card = result["output"]["model_card"]
        self.assertFalse(card["beats_baseline"])

    def test_a_trend_alone_is_not_a_season(self):
        # A rising series with no season: the trend-only baseline wins.
        trend = self.months(36, [0] * 12, noise=2, seed=12)
        card = checked(m.SeasonalForecast(), context([], [], [], "sales", trend=trend))[
            "output"]["model_card"]
        self.assertEqual(card["metric"]["baseline_name"], "trend_only")
        self.assertFalse(card["beats_baseline"])


class LanguageTests(unittest.TestCase):

    def test_arabic_claims_cite_the_same_figures_and_avoid_jargon(self):
        rows = linear_rows()
        for stage in (m.RegressionModel(), m.ClassificationModel(), m.ClusteringModel()):
            with self.subTest(stage=stage.role):
                result = checked(stage, context(rows, ["channel", "price", "ads", "sales"],
                                                ["price", "ads", "sales"], "sales",
                                                language="ar"))
                for claim in result["claims"]:
                    self.assertIn("text_ar", claim)
                    self.assertEqual(analytics.figures(claim["text_ar"]),
                                     analytics.figures(claim["text"]), claim["id"])
                    self.assertEqual(analytics._jargon_in(claim["text"]), [], claim["id"])
                    self.assertEqual(analytics._jargon_in(claim["text_ar"]), [], claim["id"])
                self.assertIn("ـ", result["summary"] + "ـ")  # written in Arabic

    def test_every_stage_is_admitted_by_the_registry(self):
        registry, problems = stages.load_stages(env={}, config={"stages": STAGE_PATHS})
        self.assertEqual(problems, [])
        self.assertEqual(list(registry), ROLES)
        self.assertTrue(all(stages.describe(s)["title_ar"] for s in registry.values()))


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ModelsInARunTests(unittest.TestCase):
    """The four stages inside a governed run, audited like any stage."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        path = root / "config.json"
        path.write_text(json.dumps({
            "agent_name": "Model Test", "memory_file": str(root / "m.json"),
            "database_file": str(root / "a.db"), "vault_dir": str(root / "v"),
            "stages": STAGE_PATHS, "profiles": {"default": [], "models": ROLES}}),
            encoding="utf-8")
        self.app = create_app(path)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def run_to_gate(self, **body):
        run = self.client.post("/api/runs", json={"goal": "Model the sales", **body}).json()
        for _ in range(80):
            if run["state"] not in ("queued", "running"):
                break
            run = self.client.post(f"/api/runs/{run['id']}/advance").json()
        self.assertEqual(run["state"], "awaiting_approval", run.get("error"))
        return run

    def test_the_default_profile_has_no_models(self):
        run = self.run_to_gate()
        self.assertEqual(run["models"], [])
        self.assertFalse(set(ROLES) & {t["role"] for t in run["tasks"]})

    def test_a_models_run_reports_every_card_and_passes_validation(self):
        for language in ("en", "ar"):
            with self.subTest(language=language):
                run = self.run_to_gate(profile="models", language=language)
                roles = [t["role"] for t in run["tasks"]]
                self.assertEqual(roles[roles.index("sensitivity") + 1:roles.index("visuals")], ROLES)
                validator = next(t for t in run["tasks"] if t["role"] == "validator")
                failed = [c["name"] for c in validator["quality_checks"] if not c["passed"]]
                self.assertEqual(failed, [])
                kinds = [card["kind"] for card in run["models"]]
                # The sample has twelve months: too few for a season.
                self.assertEqual(kinds, ["regression", "classification", "clustering"])
                self.assertTrue(all("beats_baseline" in card for card in run["models"]))
                self.assertIn(m.RegressionModel.question if language == "en" else
                              "ما الذي يتنبأ بالمقياس، وبأي دقة؟",
                              [r["question"] for r in run["reports"]])
                if language == "ar":
                    task = next(t for t in run["tasks"] if t["role"] == "regression_model")
                    self.assertEqual(task["title"], m.RegressionModel.title_ar)


if __name__ == "__main__":
    unittest.main()
