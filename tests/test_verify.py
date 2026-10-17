"""Tests for scripts/verify.py, the one command that runs every check."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import verify  # noqa: E402


class SummaryTests(unittest.TestCase):
    def test_unittest_counts_and_skips(self):
        output = "....s..\n----\nRan 705 tests in 51.2s\n\nOK (skipped=16)\n"
        self.assertEqual(verify.summarise_unittest(output), "705 tests, 16 skipped")
        self.assertEqual(verify.summarise_unittest("Ran 1 test in 0.1s\n\nOK\n"), "1 tests")
        self.assertEqual(verify.summarise_unittest("ImportError: no module"), "")

    def test_vitest_line_is_read_through_colour_codes(self):
        output = (" \x1b[2m Test Files \x1b[22m \x1b[1m\x1b[32m9 passed\x1b[39m\x1b[22m (9)\n"
                  "\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m54 passed\x1b[39m\x1b[22m (54)\n")
        self.assertEqual(verify.summarise_vitest(output), "54 passed (54)")

    def test_playwright_totals(self):
        output = "  ✓ 1 [desktop] › overview.spec.ts\n\n  3 skipped\n  63 passed (1.6m)\n"
        self.assertEqual(verify.summarise_playwright(output), "3 skipped, 63 passed")

    def test_brain_line(self):
        output = "Brain: 23 notes · 0 broken links\nOK\n"
        self.assertEqual(verify.summarise_brain(output), "23 notes · 0 broken links")


class BudgetTests(unittest.TestCase):
    def build(self, js_bytes, font_bytes, chunk_bytes=0, preload_bytes=0):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        dist = Path(temp.name)
        (dist / "assets").mkdir()
        # Random-looking text barely compresses, so its size is predictable.
        import random
        rng = random.Random(7)

        def noise(size):
            return "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(size))

        head = ['<script type="module" crossorigin src="/assets/index-a1.js"></script>',
                '<link rel="stylesheet" crossorigin href="/assets/index-a1.css">']
        (dist / "assets" / "index-a1.js").write_text(noise(js_bytes))
        if preload_bytes:
            head.append('<link rel="modulepreload" crossorigin href="/assets/vendor-b2.js">')
            (dist / "assets" / "vendor-b2.js").write_text(noise(preload_bytes))
        if chunk_bytes:  # fetched only when its view opens, so not in index.html
            (dist / "assets" / "RunsView-c3.js").write_text(noise(chunk_bytes))
        (dist / "index.html").write_text(
            "<!doctype html><html><head><script>/* theme */</script>"
            + "".join(head) + "</head><body></body></html>")
        (dist / "assets" / "index-a1.css").write_text("body{margin:0}" * 10)
        (dist / "assets" / "font-400.woff2").write_bytes(b"\0" * font_bytes)
        (dist / "assets" / "font-400.woff").write_bytes(b"\0" * 500_000)  # never counted
        return dist

    def test_a_views_stylesheet_counts_in_the_total_only(self):
        dist = self.build(20_000, 50_000)
        (dist / "assets" / "index-a1.css").write_text(
            "".join(f".c{i}{{color:#{i * 2654435761 % 16777216:06x}}}" for i in range(3000)))
        light = verify.measure_budget(dist)
        (dist / "assets" / "DashboardView-d4.css").write_text(
            "".join(f".d{i}{{margin:{i * 40503 % 997}px}}" for i in range(3000)))
        sizes = verify.measure_budget(dist)
        self.assertEqual(sizes["css"], light["css"])
        self.assertGreater(sizes["css_total"], light["css_total"])
        self.assertGreater(light["css"], 0)

    def test_a_build_inside_the_budget_passes(self):
        ok, summary = verify.check_budget(self.build(20_000, 50_000))
        self.assertTrue(ok, summary)
        self.assertIn("fonts 50.0 of 120 KB", summary)

    def test_a_build_over_the_budget_fails_and_names_what(self):
        ok, summary = verify.check_budget(self.build(200_000, 50_000))
        self.assertFalse(ok)
        self.assertIn("over: js first load", summary)

    def test_a_chunk_loaded_on_demand_is_not_first_load(self):
        light = verify.measure_budget(self.build(20_000, 50_000))
        sizes = verify.measure_budget(self.build(20_000, 50_000, chunk_bytes=40_000))
        self.assertEqual(sizes["js"], light["js"])
        self.assertGreater(sizes["js_chunk"], sizes["js"])
        self.assertAlmostEqual(sizes["js_total"], sizes["js"] + sizes["js_chunk"], delta=0.2)

    def test_a_preloaded_module_is_first_load(self):
        light = verify.measure_budget(self.build(20_000, 50_000))
        sizes = verify.measure_budget(self.build(20_000, 50_000, preload_bytes=20_000))
        self.assertGreater(sizes["js"], 1.8 * light["js"])
        self.assertEqual(sizes["js_chunk"], 0)
        self.assertEqual(sizes["js_total"], sizes["js"])

    def test_one_heavy_view_fails_even_when_the_first_load_is_light(self):
        ok, summary = verify.check_budget(self.build(20_000, 50_000, chunk_bytes=60_000))
        self.assertFalse(ok)
        self.assertIn("over: largest js chunk", summary)
        self.assertNotIn("js first load", summary.split("over:")[1])

    def test_no_build_is_a_failure_not_a_pass(self):
        with tempfile.TemporaryDirectory() as empty:
            ok, summary = verify.check_budget(Path(empty))
        self.assertFalse(ok)
        self.assertIn("no build", summary)

    def test_a_page_with_no_script_is_a_failure_not_a_pass(self):
        dist = self.build(20_000, 50_000)
        (dist / "index.html").write_text("<!doctype html><html><body></body></html>")
        ok, summary = verify.check_budget(dist)
        self.assertFalse(ok)
        self.assertIn("loads no script", summary)

    def test_the_real_build_is_read(self):
        """index.html as Vite writes it: the entry and its preloads."""
        if not (verify.DIST / "index.html").is_file():
            self.skipTest("no frontend build")
        first = verify.first_load_scripts(verify.DIST)
        self.assertTrue(first)
        self.assertTrue(all((verify.DIST / name).is_file() for name in first))


class StepTests(unittest.TestCase):
    def names(self, group):
        return [s.name for s in verify.steps() if group in s.groups]

    def test_quick_skips_the_build_and_the_browser(self):
        quick = self.names("quick")
        self.assertIn("Python tests", quick)
        self.assertNotIn("Production build", quick)
        self.assertNotIn("End-to-end tests", quick)

    def test_the_default_runs_what_ci_runs_without_a_browser(self):
        full = self.names("full")
        for name in ("Python tests", "Brain check", "Type check", "Frontend unit tests",
                     "Production build", "Interface budget"):
            self.assertIn(name, full)
        self.assertNotIn("End-to-end tests", full)
        # The budget is measured after the build that produces it.
        self.assertLess(full.index("Production build"), full.index("Interface budget"))

    def test_list_runs_nothing(self):
        with mock.patch.object(verify.subprocess, "run", side_effect=AssertionError("ran")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(verify.main(["--e2e", "--list"]), 0)
        self.assertIn("End-to-end tests", out.getvalue())

    def test_a_failed_build_is_not_followed_by_checks_of_the_old_build(self):
        build = verify.Step("Production build", [sys.executable, "-c", "raise SystemExit(2)"],
                            groups={"full"})
        budget = verify.Step("Interface budget", ["budget"], groups={"full"},
                             needs=("Production build",))
        with mock.patch.object(verify, "steps", return_value=[build, budget]), \
                mock.patch.object(verify, "check_budget", side_effect=AssertionError("measured")):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(verify.main([]), 1)
        self.assertIn("FAIL Interface budget", out.getvalue())
        self.assertIn("not run: Production build failed", out.getvalue())
        self.assertIn("2 of 2 steps failed", out.getvalue())

    def test_the_budget_and_browser_tests_need_the_build(self):
        by_name = {s.name: s for s in verify.steps()}
        self.assertIn("Production build", by_name["Interface budget"].needs)
        self.assertIn("Production build", by_name["End-to-end tests"].needs)

    def test_a_failing_step_fails_the_run(self):
        failing = verify.Step("Python tests", [sys.executable, "-c", "raise SystemExit(3)"],
                              groups={"quick"})
        with mock.patch.object(verify, "steps", return_value=[failing]):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(verify.main(["--quick"]), 1)
        self.assertIn("FAIL Python tests", out.getvalue())
        self.assertIn("1 of 1 steps failed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
