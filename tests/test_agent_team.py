"""The agent team (docs/AGENT_TEAM.md) and the tools it runs on.

The agents themselves are prompts, so what is tested is what they stand
on: every agent is wired as documented, reviewers cannot edit, and the
deterministic tools (figures_check, review_gate, analyse, the dashboard
renderer) do what the agents are told they do.
"""

import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "dashboards"))
import analyse  # noqa: E402
import figures_check as fc  # noqa: E402
import render as dash  # noqa: E402
import review_gate  # noqa: E402
from server import analytics  # noqa: E402

AGENTS = ROOT / ".claude" / "agents"
REVIEWERS = {"figures-auditor", "brief-compliance-reviewer", "analytics-expert-reviewer",
             "security-privacy-reviewer", "accessibility-i18n-reviewer"}
MODELS = {"haiku", "sonnet", "opus", "inherit"}


def frontmatter(path):
    head = path.read_text(encoding="utf-8").split("---\n", 2)[1]
    return dict(line.split(": ", 1) for line in head.strip().splitlines() if ": " in line)


class RosterTests(unittest.TestCase):

    def test_every_agent_is_wired_and_documented(self):
        doc = (ROOT / "docs" / "AGENT_TEAM.md").read_text(encoding="utf-8")
        names = set()
        for path in sorted(AGENTS.glob("*.md")):
            meta = frontmatter(path)
            with self.subTest(agent=path.stem):
                self.assertEqual(meta["name"], path.stem)
                self.assertGreater(len(meta["description"]), 80)
                self.assertIn(meta.get("model", "inherit"), MODELS)
                self.assertIn(f"`{path.stem}`", doc, "missing from the roster in docs/AGENT_TEAM.md")
                names.add(path.stem)
        roster = doc.split("## 2. The roster", 1)[1].split("## 3.", 1)[0]
        listed = set(re.findall(r"^\| `([a-z0-9-]+)` \|", roster, re.M))
        self.assertEqual(listed, names, "the roster and .claude/agents/ disagree")

    def test_reviewers_read_and_report_but_never_edit(self):
        for name in REVIEWERS:
            with self.subTest(agent=name):
                tools = set(frontmatter(AGENTS / f"{name}.md")["tools"].split(", "))
                self.assertFalse(tools & {"Write", "Edit", "NotebookEdit"})
                self.assertIn("FINDING", (AGENTS / f"{name}.md").read_text(encoding="utf-8"))

    def test_mechanical_checks_get_the_cheap_model(self):
        for name in ("figures-auditor", "security-privacy-reviewer", "accessibility-i18n-reviewer"):
            self.assertEqual(frontmatter(AGENTS / f"{name}.md")["model"], "haiku")

    def test_the_skills_the_team_uses_exist(self):
        for skill in ("review-loop", "dashboards", "motion", "verify"):
            meta = frontmatter(ROOT / ".claude" / "skills" / skill / "SKILL.md")
            self.assertEqual(meta["name"], skill)


class FiguresCheckTests(unittest.TestCase):

    def test_rounded_and_abbreviated_forms_match_and_loose_ones_do_not(self):
        self.assertTrue(fc.same_figure("363", 363.2))
        self.assertTrue(fc.same_figure("$50.4 million", 50_430_446))
        self.assertTrue(fc.same_figure("$43.2k", 43_173))
        self.assertTrue(fc.same_figure("26.5 thousand", 26_501))
        self.assertTrue(fc.same_figure("45%", 0.45))
        self.assertTrue(fc.same_figure("46.1%", 46.1))
        self.assertFalse(fc.same_figure("0", 363.2))
        self.assertFalse(fc.same_figure("364", 363.2))
        self.assertFalse(fc.same_figure("$50.5 million", 50_430_446))

    def test_small_counts_and_years_are_not_figures(self):
        self.assertEqual(fc.numbers_in("In 2025, 12 teams sold 1,200 units, up 4.5%."), ["1,200", "4.5%"])

    def test_documents_of_each_kind_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            deck = tmp / "deck.pptx"
            with zipfile.ZipFile(deck, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml",
                                 '<p:sld><p:cNvPr id="2" descr="Revenue 3,583,440"/><a:t>Total</a:t></p:sld>')
                archive.writestr("ppt/notesSlides/notesSlide1.xml", "<a:t>Up 45% on January.</a:t>")
            page = tmp / "page.html"
            page.write_text('<p>Units <b>33,525</b></p><svg><text>91,350</text></svg>', encoding="utf-8")
            data = tmp / "a.json"
            data.write_text(json.dumps({"x": [{"v": 12.5}, "note 7,000"]}), encoding="utf-8")
            self.assertIn("3,583,440", fc.read_text(deck))
            self.assertIn("Up 45%", fc.read_text(deck))
            self.assertIn("33,525", fc.read_text(page))
            self.assertNotIn("91,350", fc.read_text(page))  # chart drawings are skipped
            self.assertIn("12.5", fc.read_text(data))
            table = tmp / "agg.csv"
            table.write_text("site,loss,records,per_record\nNorth,52594720.49,862,61014.76\n", encoding="utf-8")
            self.assertEqual(fc.numbers_in(fc.read_text(table)), ["52594720.49", "61014.76", "862"])

    def test_coverage_and_sourcing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            register = [{"label": "Revenue", "value": "$3,583,440"}, {"label": "Units", "value": "33,525"}]
            report = tmp / "report.md"
            report.write_text("Revenue reached $3,583,440 from 33,525 units; growth 45%.", encoding="utf-8")
            slide = tmp / "slide.md"
            slide.write_text("Revenue $3.58 million. Growth 45%. Margin 17.2%.", encoding="utf-8")
            full = fc.check(register, [report])
            self.assertTrue(full["passed"])
            partial = fc.check(register, [slide], [report], sourcing_only=True)
            self.assertEqual([u["number"] for u in partial["unsourced"]], ["17.2%"])
            self.assertFalse(partial["passed"])
            self.assertEqual(partial["missing"], [])  # a slide shows a subset

    def test_a_figure_run_into_a_word_is_still_read(self):
        # Table cells glued by text extraction: "798" and "8.1 y" became "Reactive7988.1".
        self.assertEqual(fc.numbers_in("Reactive7988.1 y219 h Team A50.4% rev37 sha256 dataset v1.0"),
                         ["50.4%", "7988.1"])

    def test_a_worked_calculation_must_hold_and_then_sources_its_result(self):
        text = fc.normalise("Gap: 24.4 h − 16.9 h = 7.5 h per record × 862 records × about $2,500 per hour ≈ $16M")
        calcs = fc.calculations_in(text)
        self.assertEqual([(c["result"], c["holds"]) for c in calcs], [("7.5", True), ("$16M", True)])
        self.assertFalse(fc.calculations_in(fc.normalise("24.4 h − 16.9 h = 7.6 h"))[0]["holds"])
        self.assertEqual(fc.calculations_in("Sales rose 4.5× in 2025 = a record"), [])
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            register = [{"label": "Critical", "value": "24.4"}, {"label": "Rest", "value": "16.9"},
                        {"label": "Records", "value": "862"}, {"label": "Per hour", "value": "$2,500"},
                        {"label": "Scale", "value": "$16M"}]
            slide = tmp / "slide.md"
            slide.write_text("Gap: 24.4 h − 16.9 h = 7.5 h × 862 × $2,500 ≈ $16M", encoding="utf-8")
            result = fc.check(register, [slide], sourcing_only=True)
            self.assertTrue(result["passed"], result["unsourced"])  # 7.5 is derived, not unsourced
            slide.write_text("Gap: 7.5 h × 862 × $2,500", encoding="utf-8")
            self.assertEqual([u["number"] for u in fc.check(register, [slide], sourcing_only=True)["unsourced"]],
                             ["7.5"])
            slide.write_text("Gap: 24.4 h − 16.9 h = 6.5 h", encoding="utf-8")
            wrong = fc.check(register, [slide], sourcing_only=True)
            self.assertFalse(wrong["passed"])
            self.assertEqual(wrong["wrong_arithmetic"][0]["computed"], 7.5)

    def test_the_cli_reports_and_exits_by_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "kpis.csv").write_text("Check,Expected\nRevenue,\"$1,200\"\nUnits,340\n", encoding="utf-8")
            (tmp / "doc.md").write_text("Revenue was $1,200.", encoding="utf-8")
            self.assertEqual(fc.main(["--register", str(tmp / "kpis.csv"), "--doc", str(tmp / "doc.md")]), 1)
            (tmp / "doc.md").write_text("Revenue was $1,200 on 340 units.", encoding="utf-8")
            self.assertEqual(fc.main(["--register", str(tmp / "kpis.csv"), "--doc", str(tmp / "doc.md")]), 0)


class ReviewGateTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "kpis.csv").write_text("Check,Expected\nRevenue,\"$1,200\"\n", encoding="utf-8")
        (self.dir / "report.md").write_text("# Report\nRevenue was $1,200. [Add: owner name]\n",
                                            encoding="utf-8")

    def plan(self, **extra):
        plan = {"name": "t-plan", "gates": [
            {"id": "files", "type": "exists", "files": ["report.md", "kpis.csv"]},
            {"id": "figures", "type": "figures", "register": "kpis.csv", "docs": ["report.md"]},
            {"id": "heading", "type": "present", "files": ["report.md"], "patterns": ["# Report"]},
            {"id": "team-items", "type": "absent", "files": ["report.md"], "patterns": [r"\[Add"],
             "owner": "team"},
            {"id": "tests", "type": "command", "run": f'"{sys.executable}" -c "raise SystemExit(0)"'},
        ], **extra}
        path = self.dir / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path

    def run_plan(self, path, reset=False):
        return review_gate.review(path, reset, state_dir=self.dir / "state")

    def test_a_round_scores_every_gate_and_names_the_owner(self):
        card = self.run_plan(self.plan(), reset=True)
        self.assertEqual((card["passed"], card["failed"], card["score"]), (4, 1, 80.0))
        failing = next(g for g in card["gates"] if g["status"] == "fail")
        self.assertEqual((failing["id"], failing["owner"]), ("team-items", "team"))
        self.assertTrue(card["decision"].startswith("continue"))

    def test_only_a_named_person_can_accept_a_gate(self):
        with self.assertRaises(ValueError):
            self.run_plan(self.plan(accepted=[{"gate": "team-items", "reason": "later"}]))
        card = self.run_plan(self.plan(accepted=[{"gate": "team-items", "by": "A. Owner",
                                                   "reason": "supplied on submission day"}]), reset=True)
        self.assertEqual((card["score"], card["accepted"]), (100.0, 1))
        self.assertEqual(card["decision"], "stop: 100% validated")

    def test_the_loop_stops_when_it_stops_improving_or_runs_out_of_rounds(self):
        path = self.plan()
        decisions = [self.run_plan(path, reset=(i == 0))["decision"] for i in range(3)]
        self.assertTrue(decisions[1].startswith("continue"))
        self.assertTrue(decisions[2].startswith("stop: no gain"))
        path = self.plan(max_rounds=2)
        self.run_plan(path, reset=True)
        self.assertIn("2 rounds reached", self.run_plan(path)["decision"])

    def test_a_fix_shows_as_progress_and_reaches_100(self):
        path = self.plan()
        self.run_plan(path, reset=True)
        (self.dir / "report.md").write_text("# Report\nRevenue was $1,200.\n", encoding="utf-8")
        card = self.run_plan(path)
        self.assertEqual(card["history"], [80.0, 100.0])
        self.assertEqual(card["decision"], "stop: 100% validated")

    def test_starting_again_archives_the_old_rounds(self):
        path = self.plan()
        self.run_plan(path, reset=True)
        self.run_plan(path)
        card = self.run_plan(path, reset=True)
        self.assertEqual(card["round"], 1)
        archived = [p for p in (self.dir / "state").glob("*.json") if p.name != "t-plan.json"]
        self.assertEqual(len(archived), 1)
        self.assertEqual(len(json.loads(archived[0].read_text())["rounds"]), 2)

    def test_a_bad_plan_is_refused_with_reasons(self):
        bad = self.dir / "bad.json"
        bad.write_text(json.dumps({"name": "x y", "gates": [{"id": "a", "type": "vibes"},
                                                            {"id": "a", "type": "exists"}]}))
        with self.assertRaises(ValueError) as caught:
            review_gate.review(bad, state_dir=self.dir / "state")
        for words in ("short `name`", "unique `id`", "type must be"):
            self.assertIn(words, str(caught.exception))


class AnalyseAndDashboardTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        (cls.dir / "sample.csv").write_text(analytics.sample_dataset(), encoding="utf-8")
        cls.analysis = analyse.analyse(cls.dir / "sample.csv", suggest=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_pipeline_runs_to_the_gate_and_exports_figures_not_rows(self):
        a = self.analysis
        self.assertEqual(a["state"], "awaiting_approval")
        self.assertEqual(a["prepared"]["total"], 3583440.0)
        self.assertEqual(a["mapping"]["measure"], "revenue")
        refs = {c["ref"] for c in a["calculations"]}
        self.assertIn("preparer.c_total", refs)
        self.assertTrue(all(c.get("evidence") for c in a["claims"]))
        text = json.dumps(a)
        self.assertNotIn('"rows": [', text)
        self.assertNotIn("45360.0", text)  # the first row's revenue, a raw value

    def test_aggregates_are_written_as_small_csv_files(self):
        written = analyse.write_aggregates(self.analysis, self.dir / "agg")
        self.assertEqual(sorted(p.name for p in written), ["by_group.csv", "calculations.csv", "trend.csv"])
        self.assertIn("North,1935057.6", (self.dir / "agg" / "by_group.csv").read_text())

    def test_a_figure_without_a_source_is_refused(self):
        spec = {"title": "T", "sections": [{"type": "kpis", "items": [{"label": "Revenue", "value": 1}]}]}
        self.assertIn("section 1, item 1: every figure needs a source.", dash.validate(spec))
        spec = {"title": "T", "sections": [{"type": "line", "labels": ["a", "b"], "values": [1, 2]}]}
        self.assertIn("section 1: a chart needs a source.", dash.validate(spec))

    def test_the_default_dashboard_is_fully_sourced(self):
        spec = dash.spec_from_analysis(self.analysis)
        self.assertEqual(dash.validate(spec), [])
        self.assertEqual([s["type"] for s in spec["sections"]], ["kpis", "text", "line", "bars", "text", "table"])
        # Limitations come before the charts, never only in the claims table.
        self.assertEqual(spec["sections"][1]["title"], "Read with care")
        limits = [c["text"] for c in self.analysis["claims"] if c["type"] in ("limitation", "warning")]
        self.assertEqual(spec["sections"][1]["items"], limits)
        page = self.dir / "dashboard.html"
        page.write_text(dash.render(spec), encoding="utf-8")
        html_text = page.read_text()
        self.assertIn('<li id="src-1">preparer.c_total', html_text)
        self.assertNotIn("<script", html_text)
        analysis_file = self.dir / "analysis.json"
        analysis_file.write_text(json.dumps(self.analysis), encoding="utf-8")
        register = [{"label": c["ref"], "value": str(c["value"])} for c in self.analysis["calculations"]
                    if isinstance(c.get("value"), (int, float))]
        result = fc.check(register, [page], [analysis_file], sourcing_only=True)
        self.assertEqual(result["unsourced"], [])

    def test_uneven_periods_and_groups_are_also_shown_per_record(self):
        analysis = {"dataset": {"name": "t.csv", "rows": 9}, "goal": "g", "state": "awaiting_approval",
                    "prepared": {"measure": "loss", "group_col": "site", "date_col": "month",
                                 "groups": {"North": 600.0, "South": 300.0}, "group_counts": {"North": 6, "South": 2},
                                 "trend": {"2025-01": 400.0, "2025-02": 240.0}, "trend_counts": {"2025-01": 4, "2025-02": 2},
                                 "total": 900.0},
                    "calculations": [], "claims": [], "failed_checks": []}
        spec = dash.spec_from_analysis(analysis)
        self.assertEqual(dash.validate(spec), [])
        titles = [s.get("title") for s in spec["sections"]]
        self.assertIn("loss per record, by month", titles)
        line = next(s for s in spec["sections"] if s.get("title") == "loss per record, by month")
        self.assertEqual(line["values"], [100.0, 120.0])
        bars = next(s for s in spec["sections"] if s.get("title") == "loss per record, by site")
        self.assertEqual([(i["label"], i["value"]) for i in bars["items"]], [("South", 150.0), ("North", 100.0)])
        written = analyse.write_aggregates(analysis, self.dir / "uneven")
        self.assertIn("2025-02,240.0,2,120.0", (self.dir / "uneven" / "trend.csv").read_text())
        self.assertEqual(sorted(p.name for p in written), ["by_group.csv", "calculations.csv", "trend.csv"])

    def test_an_arabic_dashboard_reads_right_to_left_with_isolated_figures(self):
        spec = {"title": "لوحة", "language": "ar", "sections": [{"type": "kpis", "items": [
            {"label": "الإيرادات", "value": 3583440, "format": "currency", "currency": "USD", "source": "c_total"}]}]}
        page = dash.render(spec)
        self.assertIn('dir="rtl"', page)
        self.assertIn("<bdi>3,583,440 US$</bdi>", page)


if __name__ == "__main__":
    unittest.main()
