"""Reports in the reader's language (ADR 0022).

The promise under test: an Arabic report is the same analysis as the
English one. The calculations are the same bytes, every claim cites the
same figures, the English record the validator audits is unchanged, and a
translation that drifts from a figure is rejected rather than published.
"""

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from server import analytics
from server.model_gateway import ModelGateway
from server.routing import RoutedGateway

try:
    from fastapi.testclient import TestClient
    from server.app import create_app
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False


def _rows(header, lines):
    return header + "\n" + "\n".join(lines) + "\n"


# Datasets chosen to walk every narrative branch: trend and groups, a
# controlled comparison with and without a lopsided split, too little
# history to forecast, personal data, no dates at all, and a dirty measure.
DATASETS = {
    "sample": analytics.sample_dataset(),
    "experiment": _rows("variant,revenue", [
        f"{'control' if i % 2 else 'treatment'},{100 + i * (3 if i % 2 else 5)}"
        for i in range(40)]),
    "three_arms": _rows("variant,revenue", [
        f"{('control', 'treatment', 'variant_b')[i % 3]},{100 + i * (i % 3)}"
        for i in range(45)]),
    "lopsided": _rows("variant,revenue", [
        f"{'control' if i % 5 else 'treatment'},{100 + i}" for i in range(40)]),
    "thin_arms": _rows("variant,revenue", ["control,5", "control,7", "treatment,9"]),
    "short": _rows("month,region,revenue",
                   ["2025-01,N,10", "2025-02,N,12", "2025-01,S,8", "2025-02,S,6"]),
    "five_months": _rows("month,revenue", [f"2025-0{m},{10 * m}" for m in range(1, 6)]),
    "personal": _rows("email,revenue", ["a@b.com,5", "c@d.com,7", "e@f.com,9"]),
    "no_dates": _rows("region,revenue", ["N,1", "S,2", "E,3", "W,5", "C,8"]),
    # One bad value in twelve: still a measure (the 90% bar), and a
    # contract breach worth reporting. Weeks are not dates, so the forecast
    # labels are "next period +N".
    "dirty": _rows("week,revenue", [f"w{i},{'oops' if i == 3 else 10 + i * 2}"
                                    for i in range(1, 13)]),
}


def run_pipeline(text, language=None, glossary=None):
    ctx = {"goal": "Explain revenue", "dataset_text": text,
           "dataset_name": "test data", "run_id": "r1"}
    if language:
        ctx["report_language"] = language
    if glossary:
        ctx["glossary"] = glossary
    results = {}
    for role, stage in analytics.PIPELINE:
        result = stage(ctx)
        ctx[role], ctx[role + "_result"] = result["output"], result
        results[role] = result
        if result["status"] == "failed" and role != "validator":
            break
    return results, ctx


def claims_of(results):
    return [claim for result in results.values() for claim in result["claims"]]


class TheAnalysisIsTheSameInBothLanguages(unittest.TestCase):

    def test_every_dataset_reaches_the_report_in_both_languages(self):
        for name, text in DATASETS.items():
            with self.subTest(dataset=name):
                english, _ = run_pipeline(text)
                arabic, _ = run_pipeline(text, "ar")
                self.assertIn("reporter", english, name)
                self.assertIn("reporter", arabic, name)

    def test_the_calculations_are_the_same_bytes(self):
        for name, text in DATASETS.items():
            with self.subTest(dataset=name):
                english, _ = run_pipeline(text)
                arabic, _ = run_pipeline(text, "ar")
                for role in english:
                    self.assertEqual(json.dumps(english[role]["calculations"]),
                                     json.dumps(arabic[role]["calculations"]), role)

    def test_the_audited_english_record_does_not_change_with_the_reader(self):
        # Ids, kinds, evidence and the English text itself: the record the
        # validator and the provenance chain read is identical whichever
        # language the report is written in.
        for name, text in DATASETS.items():
            with self.subTest(dataset=name):
                english, _ = run_pipeline(text)
                arabic, _ = run_pipeline(text, "ar")
                strip = [{k: v for k, v in claim.items() if k != "text_ar"}
                         for claim in claims_of(arabic)]
                self.assertEqual(claims_of(english), strip)

    def test_an_english_run_carries_no_second_language(self):
        english, _ = run_pipeline(DATASETS["sample"])
        self.assertFalse(any("text_ar" in claim for claim in claims_of(english)))
        self.assertEqual(english["reporter"]["output"]["language"], "en")
        self.assertTrue(english["reporter"]["output"]["report_markdown"]
                        .startswith("# Business Analytics Report"))

    def test_every_claim_cites_the_same_figures_in_both_languages(self):
        for name, text in DATASETS.items():
            with self.subTest(dataset=name):
                arabic, _ = run_pipeline(text, "ar")
                for claim in claims_of(arabic):
                    self.assertIn("text_ar", claim, claim["id"])
                    self.assertEqual(analytics.figures(claim["text"]),
                                     analytics.figures(claim["text_ar"]), claim["id"])

    def test_headlines_summaries_and_reports_cite_the_same_figures(self):
        for name, text in DATASETS.items():
            english, _ = run_pipeline(text)
            arabic, _ = run_pipeline(text, "ar")
            for role in english:
                for field in ("headline", "report_markdown", "notes_markdown"):
                    with self.subTest(dataset=name, role=role, field=field):
                        self.assertEqual(
                            analytics.figures(english[role]["output"].get(field, "")),
                            analytics.figures(arabic[role]["output"].get(field, "")))
                with self.subTest(dataset=name, role=role, field="summary"):
                    self.assertEqual(analytics.figures(english[role]["summary"]),
                                     analytics.figures(arabic[role]["summary"]))

    def test_a_glossary_run_keeps_parity_including_a_breached_definition(self):
        metric = {"name": "revenue", "title": "Net revenue", "columns": ["revenue"],
                  "definition": "Units times price.", "owner": "Finance",
                  "certified": True, "certified_on": "2026-01-01", "unit": "AED",
                  "formula": {"multiply": ["units", "price"]}}
        glossary = {"metrics": [metric], "problems": ["entry 2 has no owner"]}
        text = _rows("units,price,revenue", ["2,5,10", "3,5,15", "4,5,21"])
        english, _ = run_pipeline(text, glossary=glossary)
        arabic, _ = run_pipeline(text, "ar", glossary=glossary)
        self.assertEqual(json.dumps(english["governance"]["calculations"]),
                         json.dumps(arabic["governance"]["calculations"]))
        for claim in arabic["governance"]["claims"]:
            self.assertEqual(analytics.figures(claim["text"]),
                             analytics.figures(claim["text_ar"]), claim["id"])
        self.assertEqual(analytics.figures(english["governance"]["output"]["notes_markdown"]),
                         analytics.figures(arabic["governance"]["output"]["notes_markdown"]))

    def test_a_metric_with_no_owner_keeps_the_english_record_english(self):
        metric = {"name": "revenue", "title": "Revenue", "columns": ["revenue"],
                  "definition": "Money in.", "owner": None, "certified": True,
                  "certified_on": None, "unit": None, "formula": None}
        glossary = {"metrics": [metric], "problems": []}
        english, _ = run_pipeline(DATASETS["sample"], glossary=glossary)
        arabic, _ = run_pipeline(DATASETS["sample"], "ar", glossary=glossary)
        strip = [{k: v for k, v in claim.items() if k != "text_ar"}
                 for claim in arabic["governance"]["claims"]]
        self.assertEqual(english["governance"]["claims"], strip)
        self.assertIn("nobody named", strip[0]["text"])


class TheValidatorHoldsTheTranslationToTheFigures(unittest.TestCase):

    def arabic_run(self):
        return run_pipeline(DATASETS["sample"], "ar")

    def revalidate(self, ctx):
        return analytics.validator(ctx)

    def check(self, result, name):
        return next(c for c in result["quality_checks"] if c["name"] == name)

    def test_an_arabic_run_passes_both_language_checks(self):
        results, _ = self.arabic_run()
        validator = results["validator"]
        self.assertEqual(validator["status"], "succeeded")
        for name in ("both_languages_cite_the_same_figures",
                     "every_builtin_claim_is_in_the_report_language"):
            self.assertTrue(self.check(validator, name)["passed"], name)

    def test_an_english_run_has_no_language_checks_to_pass(self):
        results, _ = run_pipeline(DATASETS["sample"])
        names = {c["name"] for c in results["validator"]["quality_checks"]}
        self.assertNotIn("both_languages_cite_the_same_figures", names)

    def test_a_translated_claim_with_a_different_figure_is_rejected(self):
        _, ctx = self.arabic_run()
        ctx = copy.deepcopy(ctx)
        claim = ctx["preparer_result"]["claims"][0]
        claim["text_ar"] = claim["text_ar"].replace("3,583,440.00", "3,583,404.00")
        result = self.revalidate(ctx)
        self.assertEqual(result["status"], "failed")
        drift = self.check(result, "both_languages_cite_the_same_figures")
        self.assertFalse(drift["passed"])
        self.assertIn("cl_total", drift["detail"])

    def test_a_built_in_claim_left_in_english_only_is_rejected(self):
        _, ctx = self.arabic_run()
        ctx = copy.deepcopy(ctx)
        del ctx["descriptive_result"]["claims"][0]["text_ar"]
        result = self.revalidate(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(self.check(
            result, "every_builtin_claim_is_in_the_report_language")["passed"])

    def test_statistical_jargon_is_caught_in_arabic_too(self):
        _, ctx = self.arabic_run()
        ctx = copy.deepcopy(ctx)
        claim = ctx["descriptive_result"]["claims"][0]
        claim["text_ar"] += " وهذا ذو دلالة إحصائية."
        result = self.revalidate(ctx)
        jargon = self.check(result, "claims_avoid_statistical_jargon")
        self.assertFalse(jargon["passed"])
        self.assertIn("دلالة إحصائية", jargon["detail"])

    def test_the_arabic_as_written_carries_no_statistical_jargon(self):
        for name, text in DATASETS.items():
            with self.subTest(dataset=name):
                arabic, ctx = run_pipeline(text, "ar")
                texts = [c["text_ar"] for c in claims_of(arabic)]
                texts += [ctx.get(n, {}).get("headline", "")
                          for n, _ in analytics.REPORT_SECTIONS]
                for text_ in texts:
                    self.assertEqual(analytics._jargon_in(text_), [], text_)


class TheArabicReportReadsAsArabic(unittest.TestCase):

    def setUp(self):
        results, _ = run_pipeline(DATASETS["sample"], "ar")
        self.report = results["reporter"]["output"]["report_markdown"]
        self.results = results

    def test_its_headings_are_arabic(self):
        headings = [line for line in self.report.split("\n") if line.startswith("#")]
        self.assertTrue(headings)
        for heading in headings:
            self.assertRegex(heading, r"[؀-ۿ]", heading)
        self.assertIn("## الملخص التنفيذي", self.report)
        self.assertNotIn("Executive summary", self.report)

    def test_the_evidence_record_is_left_as_it_was_written(self):
        # Calculation names are identifiers; the Arabic report says so.
        self.assertIn("| forecast_2026-01 | 361505.45 |", self.report)
        self.assertIn(analytics.AR_METHODS_NOTE, self.report)

    def test_digits_stay_western(self):
        self.assertIsNone(re.search(r"[٠-٩۰-۹]", self.report))

    def test_the_narrative_prose_is_arabic(self):
        # Outside the tables, identifiers and user data, prose lines carry
        # Arabic letters. Table rows and lines that are pure data are
        # exempt; everything else a reader reads as a sentence is checked.
        prose = [line for line in self.report.split("\n")
                 if line and not line.startswith(("|", "---", "- **", "#"))]
        english_only = [line for line in prose
                        if not re.search(r"[؀-ۿ]", line)]
        self.assertEqual(english_only, [])

    def test_every_headline_is_arabic(self):
        for name, _ in analytics.REPORT_SECTIONS:
            self.assertRegex(self.results[name]["output"]["headline"],
                             r"[؀-ۿ]", name)


class ArabicCountsAndFigures(unittest.TestCase):

    def test_nouns_take_the_form_their_number_asks_for(self):
        cases = {1: "صف واحد", 2: "صفان", 3: "3 صفوف", 10: "10 صفوف",
                 11: "11 صفاً", 99: "99 صفاً", 100: "100 صف", 101: "101 صف",
                 103: "103 صفوف", 111: "111 صفاً", 0: "0 صف"}
        for count, expected in cases.items():
            self.assertEqual(analytics._ar_n(count, "row"), expected)
        self.assertEqual(analytics._ar_n(1234, "observation", grouped=True),
                         "1,234 مشاهدة")

    def test_figures_ignore_grouping_signs_and_the_numbers_arabic_says_in_words(self):
        self.assertEqual(analytics.figures("1,234.50 and +12% of 72 in 1 or 2"),
                         analytics.figures("1234.50 و12% من 72"))
        self.assertNotEqual(analytics.figures("12%"), analytics.figures("12"))

    def test_every_role_and_section_has_an_arabic_name(self):
        self.assertEqual(set(analytics.ROLE_TITLES), set(analytics.ROLE_TITLES_AR))
        titles = {"Descriptive", "Diagnostic", "Causal", "Predictive", "Prescriptive"}
        self.assertEqual(set(analytics.SECTION_TITLES_AR), titles)

    def test_a_non_date_period_label_is_translated_only_where_it_is_read(self):
        results, _ = run_pipeline(DATASETS["dirty"], "ar")
        names = [c["name"] for c in results["predictive"]["calculations"]]
        self.assertIn("forecast_next period +1", names)
        self.assertIn("الفترة التالية +1", results["predictive"]["output"]["headline"])


class TheNarratorWritesInTheReportLanguage(unittest.TestCase):

    def test_the_deterministic_narrator_answers_in_arabic(self):
        gateway = ModelGateway(env={})
        result = gateway.narrate("هدف", ["حقيقة أولى.", "حقيقة ثانية."], language="ar")
        self.assertEqual(result["source"], "deterministic")
        self.assertTrue(result["text"].startswith("تحليل الهدف «هدف»"))

    def test_a_model_is_told_the_language_and_to_copy_every_figure(self):
        gateway = ModelGateway(env={"GROQ_API_KEY": "test"})
        seen = {}

        def complete(system, user, max_tokens=None):
            seen["system"], seen["user"] = system, user
            return "ملخص."
        gateway._complete_groq = complete
        result = gateway.narrate("g", ["إجمالي revenue هو 1,234.00."], language="ar")
        self.assertEqual(result, {"text": "ملخص.", "source": "model"})
        self.assertIn("Arabic", seen["system"])
        self.assertIn("same digits", seen["system"])
        self.assertIn("1,234.00", seen["user"])

    def test_an_english_narration_prompt_is_unchanged(self):
        gateway = ModelGateway(env={"GROQ_API_KEY": "test"})
        seen = {}

        def complete(system, user, max_tokens=None):
            seen["system"] = system
            return "Summary."
        gateway._complete_groq = complete
        gateway.narrate("g", ["Total is 1."])
        self.assertNotIn("Arabic", seen["system"])

    def test_a_routed_gateway_passes_the_language_through(self):
        routed = RoutedGateway(ModelGateway(env={}))
        result = routed.narrate("هدف", ["حقيقة."], language="ar")
        self.assertTrue(result["text"].startswith("تحليل الهدف"))

    def test_the_prescriptive_stage_hands_the_narrator_arabic_facts(self):
        class Recorder:
            def narrate(self, goal, facts, language="en"):
                self.facts, self.language = facts, language
                return {"text": "ملخص", "source": "model"}
        _, ctx = run_pipeline(DATASETS["sample"], "ar")
        recorder = Recorder()
        analytics.prescriptive(ctx, recorder)
        self.assertEqual(recorder.language, "ar")
        self.assertTrue(all(re.search(r"[؀-ۿ]", f) for f in recorder.facts))


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class ArabicRunsThroughTheApi(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.vault = root / "vault"
        config_path = root / "config.json"
        config_path.write_text(json.dumps({
            "agent_name": "Language Test Agent",
            "memory_file": str(root / "memory.json"),
            "vault_dir": str(self.vault),
            "database_file": str(root / "agentic.db")}), encoding="utf-8")
        self.client = TestClient(create_app(config_path),
                                 raise_server_exceptions=False)

    def advance_until(self, run_id, states):
        for _ in range(40):
            run = self.client.post(f"/api/runs/{run_id}/advance").json()
            if run["state"] in states:
                return run
        raise AssertionError("the run did not settle")

    def test_a_run_created_in_arabic_is_written_and_published_in_arabic(self):
        created = self.client.post("/api/runs", json={
            "goal": "حلّل بيانات المبيعات", "language": "ar"})
        self.assertEqual(created.status_code, 201)
        run = created.json()
        self.assertEqual(run["report_language"], "ar")
        titles = {t["role"]: t["title"] for t in run["tasks"]}
        self.assertEqual(titles["validator"], "خبير التحقق")

        run = self.advance_until(run["id"], {"awaiting_approval"})
        self.assertTrue(run["report"]["content"].startswith("# تقرير تحليل الأعمال"))
        # The approval is read by the same person, so it is Arabic too;
        # the risk stays an enum the interface labels.
        approval = run["approvals"][0]
        self.assertEqual(approval["action"], "نشر تقرير التحليل في مخزن Obsidian")
        self.assertEqual(approval["risk"], "high")
        descriptive = next(r for r in run["reports"] if r["type"] == "descriptive")
        self.assertEqual(descriptive["title"], analytics.ROLE_TITLES_AR["descriptive"])
        self.assertRegex(descriptive["headline"], r"[؀-ۿ]")

        self.client.post(f"/api/runs/{run['id']}/approvals/{run['approvals'][0]['id']}",
                         json={"decision": "approve"})
        note = next((self.vault / "Reports").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("lang: ar", note)
        self.assertIn("## الملخص التنفيذي", note)

    def test_the_default_is_english_and_says_so(self):
        run = self.client.post("/api/runs", json={"goal": "Analyse the sample"}).json()
        self.assertEqual(run["report_language"], "en")

    def test_a_language_reports_are_not_written_in_is_refused(self):
        response = self.client.post("/api/runs", json={"goal": "Analyse it",
                                                       "language": "fr"})
        self.assertEqual(response.status_code, 422)


class TheAssistantStartsRunsInTheReadersLanguage(unittest.TestCase):

    def test_an_arabic_conversation_starts_an_arabic_run(self):
        from server.assistant import Assistant
        from tests.test_assistant import FakeSession, engine_in, make_agent

        with tempfile.TemporaryDirectory() as directory:
            engine = engine_in(directory)
            outcome = Assistant(ModelGateway(env={}), engine).handle(
                "analyse the sample sales data", FakeSession(make_agent("Arabic")))
            self.assertEqual(outcome.get("action"), "start_run")
            run = engine.get_run(outcome["result"]["run_id"])
            self.assertEqual(run["report_language"], "ar")


if __name__ == "__main__":
    unittest.main()
