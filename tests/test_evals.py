"""The agent evaluation (ADR 0027): its arithmetic, its suites, and the
recall floors every classifying agent must keep.

The suites in evals/ are synthetic and labelled. Each has dev cases, used
to find and fix misses, and holdout cases scored before and after. For the
text classifiers, the current holdout is a blind set written by an
independent agent from the label definitions only. A change that drops a
suite below its floor in evals/floors.json fails here.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import claims_lint  # noqa: E402
import consult  # noqa: E402
import evaluate_agents as ev  # noqa: E402
import figures_check as fc  # noqa: E402
from server import analytics, mapping, routing  # noqa: E402


class MetricsTests(unittest.TestCase):

    def test_the_confusion_matrix_and_recall_are_counted_by_hand(self):
        pairs = [("a", "a", 1), ("a", "b", 2), ("b", "b", 3), ("b", "b", 4), ("c", "a", 5)]
        labels, matrix = ev.confusion(pairs, ["a", "b", "c"])
        self.assertEqual(matrix["a"], {"a": 1, "b": 1, "c": 0})
        self.assertEqual(matrix["c"], {"a": 1, "b": 0, "c": 0})
        scores = ev.scores(labels, matrix)
        self.assertEqual(scores["per_class"]["a"]["recall"], 0.5)
        self.assertEqual(scores["per_class"]["a"]["precision"], 0.5)
        self.assertEqual(scores["per_class"]["b"]["recall"], 1.0)
        self.assertEqual(scores["per_class"]["c"]["recall"], 0.0)
        self.assertAlmostEqual(scores["macro_recall"], 0.5)
        self.assertEqual(scores["accuracy"], 0.6)

    def test_a_detector_is_judged_by_the_recall_of_what_it_must_catch(self):
        pairs = [(True, True, 1), (True, False, 2), (False, False, 3), (False, True, 4)]
        labels, matrix = ev.confusion(pairs, [True, False])
        scores = ev.scores(labels, matrix, positive=True)
        self.assertEqual((scores["recall"], scores["precision"]), (0.5, 0.5))

    def test_an_unexpected_prediction_gets_its_own_column(self):
        labels, matrix = ev.confusion([("a", "zzz", 1)], ["a"])
        self.assertEqual(labels, ["a", "zzz"])
        self.assertEqual(matrix["a"]["zzz"], 1)


class SuiteTests(unittest.TestCase):

    def test_every_suite_has_dev_and_holdout_cases_with_known_labels(self):
        for name, spec in ev.SUITES.items():
            with self.subTest(suite=name):
                data = json.loads((ev.EVALS / spec["file"]).read_text(encoding="utf-8"))
                self.assertTrue(data["dev"] and data["holdout"])
                if "labels" in data and name not in ("column_roles", "personal_data", "figures"):
                    allowed = {str(label) for label in data["labels"]}
                    for case in data["dev"] + data["holdout"]:
                        self.assertIn(str(case["label"]), allowed)

    def test_no_suite_falls_below_its_recall_floor(self):
        floors = json.loads((ev.EVALS / "floors.json").read_text(encoding="utf-8"))
        for name in ev.SUITES:
            result = ev.run_suite(name)
            for split in ("dev", "holdout"):
                with self.subTest(suite=name, split=split):
                    self.assertGreaterEqual(ev.headline(result[split]) + 1e-9, floors[name][split])

    def test_the_report_page_draws_every_matrix(self):
        import score_review
        page = ev.render_html([ev.run_suite("router")], score_review.summary())
        self.assertIn("<table class=\"cm\">", page)
        self.assertIn("Rows: true label", page)
        self.assertIn("Reviewers on seeded memos", page)
        self.assertIn("Rows: the planted defect.", page)


class RecallFixTests(unittest.TestCase):
    """One example of each measured fix, so a reader sees what changed."""

    def test_a_name_alone_is_not_personal_data_when_the_values_say_otherwise(self):
        rows = [{"card_type": t, "email_opens": str(n), "full_name": f, "submitted_at": d}
                for t, n, f, d in zip(["Visa", "Amex"] * 5, range(10),
                                      ["Ali Hassan", "Sara Khan", "Omar Saeed", "Laila Noor", "John Smith",
                                       "Maria Lopez", "Fatima Zahra", "Yusuf Amin", "Chen Wei", "Priya Nair"],
                                      [f"2025-03-0{i} 10:0{i}" for i in range(1, 10)] + ["2025-03-10 11:00"])]
        flagged = {f["column"] for f in analytics.personal_data_findings(list(rows[0]), rows)}
        self.assertEqual(flagged, {"full_name"})

    def test_a_year_beside_the_date_and_a_cost_centre_are_breakdowns(self):
        text = "ship_date,year,cost_centre,cost\n" + "\n".join(
            f"2025-0{(i % 9) + 1}-1{i % 9},{2024 + i % 2},{4100 + 100 * (i % 3)},{100 + 7 * i}" for i in range(12))
        roles = mapping.suggest(*mapping.table(text))["roles"]
        self.assertEqual((roles["year"], roles["cost_centre"], roles["cost"]), ("dimension", "dimension", "measure"))

    def test_the_router_reads_naming_conventions(self):
        every = [{"provider": p} for p in ("ollama", "anthropic", "groq", "deterministic")]
        self.assertEqual(routing.provider_for("gpt-oss:20b", every), "ollama")
        self.assertEqual(routing.provider_for("llama-3.3-70b-versatile", every), "groq")
        self.assertEqual(routing.provider_for("anthropic/claude-3.7-sonnet", every), "anthropic")
        self.assertIsNone(routing.provider_for("bert-base-uncased", every))

    def test_the_raw_data_guard_knows_json_aligned_and_keyed_rows(self):
        self.assertTrue(consult.looks_like_raw_rows(json.dumps([{"sales": i} for i in range(9)])))
        self.assertTrue(consult.looks_like_raw_rows("\n".join(f"2025-0{i % 9 + 1}  North   {1000 + i}" for i in range(9))))
        self.assertTrue(consult.looks_like_raw_rows("\n".join(f"name: P{i}, salary: {9000 + i}" for i in range(9))))
        self.assertFalse(consult.looks_like_raw_rows("Revenue rose 12% to 3.4 million; costs were flat."))

    def test_jargon_abbreviations_match_only_as_words(self):
        self.assertTrue(analytics._jargon_in("The 95% CI runs from 1.2 to 3.4."))
        self.assertTrue(analytics._jargon_in("A Mann-Whitney test shows the shifts differ."))
        self.assertEqual(analytics._jargon_in("The decision was special."), [])
        self.assertEqual(analytics._jargon_in("Budget variance was 2 million."), [])

    def test_causal_wording_is_found_and_associations_are_left_alone(self):
        self.assertTrue(claims_lint.causal_phrases("Stockouts double outages."))
        self.assertTrue(claims_lint.causal_phrases("The discount increased orders by 15%."))
        self.assertTrue(claims_lint.causal_phrases("أدى نقص المخزون إلى زيادة التوقف."))
        self.assertFalse(claims_lint.causal_phrases("Orders increased 15% in weeks with a discount."))
        self.assertFalse(claims_lint.causal_phrases("Records with a stockout average twice the downtime."))
        self.assertFalse(claims_lint.causal_phrases("We cannot claim a cause from this data."))

    def test_the_claims_lint_cli_exits_by_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("Stockouts are associated with longer outages.", encoding="utf-8")
            self.assertEqual(claims_lint.main(["--doc", str(doc)]), 0)
            doc.write_text("Stockouts prolong outages.", encoding="utf-8")
            self.assertEqual(claims_lint.main(["--doc", str(doc)]), 1)

    def test_figures_in_arabic_digits_approximations_and_brackets_are_read(self):
        self.assertEqual(fc.normalise("٣٬٥٨٣٬٤٤٠ و١٢٫٤٪"), "3,583,440 و12.4%")
        self.assertEqual(fc.normalise("Variance (1,200) and margin (18.2%)"), "Variance -1,200 and margin (18.2%)")
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text("About 6,400 hours were lost; the plan said 7,100.", encoding="utf-8")
            result = fc.check([{"label": "gap", "value": "6421"}], [doc], sourcing_only=True)
            self.assertEqual([u["number"] for u in result["unsourced"]], ["7,100"])

    def test_round_five_causal_wording(self):
        claims = lambda text: [p for p, _ in claims_lint.causal_phrases(text)]
        # Questions and untested hypotheses talk about a cause without claiming one.
        self.assertEqual(claims("Does the heat cause the breakdowns?"), [])
        self.assertEqual(claims("هل يسبب الحر زيادة الأعطال؟"), [])
        self.assertEqual(claims("The hypothesis that heat causes the breakdowns is untested."), [])
        self.assertEqual(claims("Busier depots have more delays, but we have not checked whether one drives the other."), [])
        # A hyphenated word after the verb is its object, not a preposition.
        self.assertTrue(claims("Training the dispatchers boosted on-time performance."))
        # Arabic: a longer subject inside "أدى … إلى", prefixed verbs, colloquial causatives.
        self.assertTrue(claims("أدى إلغاء الدعم عن تذاكر الطلاب إلى انخفاض عدد الركاب."))
        self.assertTrue(claims("الحر الشديد ويرفع طلبات الصيانة"))
        self.assertTrue(claims("التأخير في القطع بيخلي الأتوبيسات واقفة"))

    def test_round_five_jargon_and_intent(self):
        self.assertTrue(analytics._jargon_in("After a Bonferroni correction, two comparisons stay."))
        self.assertTrue(analytics._jargon_in("وجدنا عدم تجانس التباين في البواقي."))
        self.assertFalse(analytics._jargon_in("The residual value of the fleet is $2.1 million."))
        import assistant
        for text, action in (("Could you walk me through how to upload a spreadsheet?", "help"),
                             ("Erase our previous messages from this session, please.", "clear_history"),
                             ("pls forget that thing about the discount", "forget"),
                             ("what have you got saved about me so far", "recall"),
                             ("خلك حافظ عندك إن المورد يطلب الدفع خلال 45 يوم", "remember"),
                             ("التقرير بيقول إيه عن المصاريف؟", "explain_report")):
            with self.subTest(text=text):
                self.assertEqual(assistant.understand(text)["action"], action)

    def sourcing(self, text, register):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "doc.md"
            doc.write_text(text, encoding="utf-8")
            return fc.check([{"label": k, "value": v} for k, v in register.items()], [doc], sourcing_only=True)

    def test_a_small_percentage_is_a_figure_and_units_must_agree(self):
        # Benchmark A: "27%" was skipped as a small count, and "40%" passed
        # because the register held $39.95.
        result = self.sourcing("Online orders grew 27%. Sales rose 40%. Store 17 opened.", {"Basket": "$39.95"})
        self.assertEqual(sorted(u["number"] for u in result["unsourced"]), ["27%", "40%"])

    def test_a_figure_its_sentence_derives_is_sourced_and_a_slip_is_wrong(self):
        register = {"Revenue 2025": "$12,480,000", "Revenue 2024": "$11,200,000", "Stores": "48", "Staff": "610"}
        text = ("Revenue reached $12.48 million in 2025, up from $11.2 million in 2024. That is growth of 13.4%. "
                "With 610 staff across 48 stores, each store has 15.2 staff on average. "
                "Revenue per store was about $260,000.")
        result = self.sourcing(text, register)
        self.assertEqual(result["unsourced"], [])
        wrong = {w["result"]: w["computed"] for w in result["wrong_arithmetic"]}
        self.assertEqual(set(wrong), {"13.4%", "15.2"})
        self.assertAlmostEqual(wrong["13.4%"], 11.428571, places=4)
        self.assertAlmostEqual(wrong["15.2"], 12.708333, places=4)

    def test_a_table_read_as_one_sentence_derives_nothing(self):
        # A dashboard's data table: dozens of figures and the word "per"; any
        # two of them would "derive" a third, so the rule keeps to prose.
        months = " ".join(f"2024-{m:02d} {7_000_000 + m * 104_729:,}" for m in range(1, 13))
        text = f"Loss per record by month. The numbers in this chart Label Value {months} Total 7,104,729"
        result = self.sourcing(text, {"January": "7,104,729", "February": "7,209,458"})
        self.assertEqual(result["wrong_arithmetic"], [])
        self.assertEqual(len(result["unsourced"]), 10)

    def test_one_figure_written_twice_is_not_two_inputs(self):
        # 75.2% and 0.752 are one quantity: their difference must not source 74.1%.
        result = self.sourcing("The preventive ratio was 75.2%, up from 74.1%.", {"Preventive ratio": "0.752"})
        self.assertEqual([u["number"] for u in result["unsourced"]], ["74.1%"])


class ReviewerBenchmarkTests(unittest.TestCase):
    """The seeded memos in evals/reviewers/ and their scorer (ADR 0027)."""

    def test_every_benchmark_labels_paragraphs_that_exist(self):
        import re
        for bench in ("A", "B", "C"):
            with self.subTest(bench=bench):
                folder = ROOT / "evals" / "reviewers" / bench
                labels = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
                memo = (folder / "memo.md").read_text(encoding="utf-8")
                self.assertEqual(re.findall(r"\[(P\d{2})\]", memo), labels["paragraphs"])
                self.assertLessEqual(set(labels["defects"]), set(labels["paragraphs"]))
                for categories in labels["defects"].values():
                    self.assertLessEqual(set(categories), set(labels["categories"]))
                self.assertTrue(fc.load_register(folder / "register.csv", "Expected", ["Check"]))

    def test_the_scorer_separates_misses_false_alarms_and_secondary_findings(self):
        import score_review
        reply = ("FINDING F1 · major · P02\nCategory: arithmetic\n\n"
                 "FINDING F2 · major · P07\nCategory: causal_claim\n\n"
                 "FINDING F3 · minor · P08\nCategory: denominator\n\n"
                 "FINDING F4 · major · P06\nCategory: unsourced_figure\n\n"
                 "FINDING F5 · major · P06\nCategory: denominator\n")
        result = score_review.score(ROOT / "evals" / "reviewers" / "A", reply, ["causal_claim", "denominator", "overclaim"])
        self.assertEqual(result["false_alarms"], ["P08 · denominator"])
        self.assertIn("P06 · unsourced_figure", result["secondary"])
        self.assertEqual(result["category_confusion"]["matrix"]["overclaim"]["causal_claim"], 1)
        self.assertEqual(result["category_confusion"]["matrix"]["overclaim"]["missed"], 1)
        self.assertEqual(result["per_category"]["denominator"]["misses"], ["P15 · denominator"])
        self.assertAlmostEqual(result["recall"], 1 / 6)

    def test_the_checker_as_a_reviewer_keeps_its_benchmark_recall(self):
        import score_review
        floors = json.loads((ROOT / "evals" / "floors.json").read_text(encoding="utf-8"))["figures_tool"]
        for bench, floor in floors.items():
            with self.subTest(bench=bench):
                result = score_review.score(ROOT / "evals" / "reviewers" / bench,
                                            score_review.figures_tool_findings(ROOT / "evals" / "reviewers" / bench),
                                            ["unsourced_figure", "arithmetic"])
                self.assertGreaterEqual(result["detection"]["recall"] + 1e-9, floor)
                self.assertEqual(result["false_alarms"], [])


if __name__ == "__main__":
    unittest.main()
