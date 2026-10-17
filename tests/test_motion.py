"""The motion skill and its subagent (.claude/skills/motion, .claude/agents).

Rendering needs Chromium and ffmpeg and takes a minute, so it is checked
by hand and recorded in the session log. What can drift silently is
checked here: the example clips' figures against the data they cite, the
renderer's refusal of a figure without a source, and the files that wire
the skill and subagent into Claude Code.
"""

import csv
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from server import analytics

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "motion"
AGENT = ROOT / ".claude" / "agents" / "motion-designer.md"
NODE = shutil.which("node")


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    head = text.split("---\n", 2)[1]
    return dict(line.split(": ", 1) for line in head.strip().splitlines() if ": " in line)


def figures(spec):
    for scene in spec["scenes"]:
        for item in scene.get("items", []):
            yield scene, item
        if scene.get("figure"):
            yield scene, scene["figure"]


class WiringTests(unittest.TestCase):

    def test_the_skill_and_the_subagent_are_declared(self):
        skill = frontmatter(SKILL / "SKILL.md")
        self.assertEqual(skill["name"], "motion")
        self.assertIn("MP4", skill["description"])
        agent = frontmatter(AGENT)
        self.assertEqual(agent["name"], "motion-designer")
        self.assertIn("never invents a number", agent["description"])
        self.assertEqual(set(agent["tools"].split(", ")), {"Read", "Write", "Edit", "Bash", "Glob", "Grep"})
        self.assertIn(".claude/skills/motion/", AGENT.read_text(encoding="utf-8"))

    def test_the_composition_keeps_its_contract(self):
        html = (SKILL / "composition.html").read_text(encoding="utf-8")
        for marker in ("/*FONTS*/", "/*SPEC*/null", "window.motion =", "seek", "transcript"):
            self.assertIn(marker, html)
        # Frames must be a function of time alone, or two renders differ.
        for clock in ("requestAnimationFrame(", "setTimeout(", "setInterval(", "Math.random(", "Date.now("):
            self.assertNotIn(clock, html)


class ExampleFigureTests(unittest.TestCase):
    """The examples are the only clips in the repository; every figure in
    them must be what the sample dataset actually gives."""

    @classmethod
    def setUpClass(cls):
        rows = list(csv.DictReader(io.StringIO(analytics.sample_dataset())))
        by_category, by_month = defaultdict(float), defaultdict(float)
        for row in rows:
            by_category[row["category"]] += float(row["revenue"])
            by_month[row["month"]] += float(row["revenue"])
        months = sorted(by_month)
        cls.truth = {
            "sum(revenue), 72 rows": sum(float(r["revenue"]) for r in rows),
            "sum(units), 72 rows": sum(float(r["units"]) for r in rows),
            "distinct month, 2025-01 to 2025-12": len(months),
            **{f"sum(revenue) where category = {name}": value for name, value in by_category.items()},
            "(365,400 − 252,000) / 252,000: December against January revenue":
                round((by_month[months[-1]] - by_month[months[0]]) / by_month[months[0]] * 100),
        }
        cls.months = (by_month[months[0]], by_month[months[-1]])

    def test_every_example_figure_matches_the_sample(self):
        for name in ("sample-sales.json", "sample-sales.ar.json"):
            spec = json.loads((SKILL / "examples" / name).read_text(encoding="utf-8"))
            for _, item in figures(spec):
                with self.subTest(example=name, source=item["source"]):
                    self.assertIn(item["source"], self.truth)
                    self.assertAlmostEqual(item["value"], self.truth[item["source"]], places=2)

    def test_the_figures_quoted_in_text_match_too(self):
        january, december = self.months
        self.assertEqual((january, december), (252000.0, 365400.0))
        spec = json.loads((SKILL / "examples" / "sample-sales.json").read_text(encoding="utf-8"))
        bars = next(s for s in spec["scenes"] if s["type"] == "bars")
        software = next(i["value"] for i in bars["items"] if i["label"] == "Software")
        total = self.truth["sum(revenue), 72 rows"]
        self.assertIn(f"{software / total:.0%}", bars["note"])


@unittest.skipUnless(NODE, "node is not installed")
class RendererCheckTests(unittest.TestCase):
    """`render.mjs --check` validates without Playwright or ffmpeg."""

    def check(self, spec):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            return subprocess.run([NODE, str(SKILL / "render.mjs"), str(path), "--check"],
                                  capture_output=True, text=True, timeout=60)

    def test_the_examples_pass(self):
        for name in ("sample-sales.json", "sample-sales.ar.json"):
            with self.subTest(example=name):
                spec = json.loads((SKILL / "examples" / name).read_text(encoding="utf-8"))
                done = self.check(spec)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertIn("each with a source", done.stdout)

    def test_a_figure_without_a_source_is_refused(self):
        spec = {"scenes": [{"type": "kpis", "duration": 4, "heading": "Totals",
                            "items": [{"label": "Revenue", "value": 120}]}]}
        done = self.check(spec)
        self.assertEqual(done.returncode, 1)
        self.assertIn('every figure needs a "source"', done.stderr)

    def test_every_problem_is_listed_at_once(self):
        spec = {"width": 800, "height": 600, "fps": 12, "language": "fr",
                "scenes": [{"type": "spin", "duration": 40},
                           {"type": "bars", "duration": 3, "heading": "x", "items": []}]}
        done = self.check(spec)
        self.assertEqual(done.returncode, 1)
        for words in ("Size 800x600", "fps must be", "language must be", "type must be",
                      "duration must be", "needs 1 to 8 items"):
            self.assertIn(words, done.stderr)

    def test_the_poster_names_a_scene_that_exists(self):
        spec = {"poster": 3, "scenes": [{"type": "title", "duration": 3, "title": "Briefing"},
                                        {"type": "statement", "duration": 4, "text": "of records.",
                                         "figure": {"value": 27, "suffix": "%", "source": "sample"}}]}
        done = self.check(spec)
        self.assertEqual(done.returncode, 1)
        self.assertIn("poster must be a scene number from 1 to 2", done.stderr)
        spec["poster"] = 1
        self.assertEqual(self.check(spec).returncode, 0)


if __name__ == "__main__":
    unittest.main()
