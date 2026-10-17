"""The house style (.claude/skills/rta-style): one source of colours, readable
in light and dark, used by the dashboards, the clips and the evaluation report,
and never carrying an organisation's name or logo (ADR 0027)."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLE = ROOT / ".claude" / "skills" / "rta-style"
sys.path.insert(0, str(STYLE))
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "dashboards"))
sys.path.insert(0, str(ROOT / "scripts"))
import build  # noqa: E402
import render as dash  # noqa: E402

TOKENS = json.loads((STYLE / "tokens.json").read_text(encoding="utf-8"))
NODE = shutil.which("node")
# Names and marks a themed output must never carry, in English or Arabic.
# The abbreviation is matched in capitals only, so the skill's folder name passes.
FORBIDDEN = re.compile(r"\bRTA\b|(?i:roads and transport|هيئة الطرق|<img\b)")


def luminance(colour):
    r, g, b = (int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class TokenTests(unittest.TestCase):

    def test_the_css_is_built_from_the_tokens(self):
        self.assertEqual((STYLE / "tokens.css").read_text(encoding="utf-8"), build.css(TOKENS),
                         "tokens.css is stale: run python .claude/skills/rta-style/build.py")

    def test_both_modes_carry_the_same_tokens(self):
        self.assertEqual(list(TOKENS["light"]), list(TOKENS["dark"]))

    def test_text_meets_aa_contrast_in_light_and_dark(self):
        for mode in ("light", "dark"):
            palette = TOKENS[mode]
            for fore, back in TOKENS["contrast_pairs"]:
                with self.subTest(mode=mode, pair=f"{fore} on {back}"):
                    self.assertGreaterEqual(contrast(palette[fore], palette[back]), 4.5)

    def test_chart_marks_meet_the_non_text_contrast(self):
        for mode in ("light", "dark"):
            palette = TOKENS[mode]
            for fore, back in TOKENS["chart_pairs"]:
                with self.subTest(mode=mode, pair=f"{fore} on {back}"):
                    self.assertGreaterEqual(contrast(palette[fore], palette[back]), 3.0)

    def test_the_print_variant_is_built_and_readable(self):
        self.assertEqual((STYLE / "document.css").read_text(encoding="utf-8"), build.document_css(TOKENS),
                         "document.css is stale: run python .claude/skills/rta-style/build.py")
        doc = TOKENS["document"]
        for fore, back in TOKENS["document_contrast_pairs"]:
            with self.subTest(pair=f"{fore} on {back}"):
                self.assertGreaterEqual(contrast(doc[fore], doc[back]), 4.5)
        for fore, back in TOKENS["document_chart_pairs"]:
            with self.subTest(pair=f"{fore} on {back}"):
                self.assertGreaterEqual(contrast(doc[fore], doc[back]), 3.0)

    def test_every_default_colour_has_a_print_role(self):
        for kind, table in TOKENS["from_default"].items():
            for colour, role in table.items():
                with self.subTest(kind=kind, colour=colour):
                    self.assertRegex(colour, r"^#[0-9a-f]{6}$")
                    self.assertIn(role, TOKENS["document"])

    def test_the_style_files_carry_no_name_or_logo(self):
        for name in ("tokens.json", "tokens.css", "document.css", "build.py", "restyle.py"):
            with self.subTest(file=name):
                self.assertIsNone(FORBIDDEN.search((STYLE / name).read_text(encoding="utf-8")))


class WiringTests(unittest.TestCase):

    def test_the_motion_themes_match_the_tokens(self):
        page = (ROOT / ".claude" / "skills" / "motion" / "composition.html").read_text(encoding="utf-8")
        names = {"paper": "bg", "surface": "surface", "ink": "text", "ink-2": "charcoal", "muted": "muted",
                 "rule": "border", "accent": "accent", "accent-soft": "accent-tint", "amber": "brand",
                 "amber-soft": "brand-tint", "bar": "bar", "bar-edge": "bar-edge"}
        for theme, mode in (("rta", "light"), ("rta-dark", "dark")):
            block = re.search(r':root\[data-theme="%s"\]\s*\{([^}]*)\}' % theme, page).group(1)
            found = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-f]{6})", block))
            with self.subTest(theme=theme):
                self.assertEqual(found, {var: TOKENS[mode][token] for var, token in names.items()})

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_clip_renderer_accepts_the_house_themes_only(self):
        scene = [{"type": "title", "duration": 3, "title": "Briefing"}]
        with tempfile.TemporaryDirectory() as tmp:
            for theme, code in (("rta", 0), ("rta-dark", 0), ("neon", 1)):
                path = Path(tmp) / "spec.json"
                path.write_text(json.dumps({"theme": theme, "scenes": scene}), encoding="utf-8")
                done = subprocess.run([NODE, str(ROOT / ".claude/skills/motion/render.mjs"), str(path), "--check"],
                                      capture_output=True, text=True, timeout=60)
                with self.subTest(theme=theme):
                    self.assertEqual(done.returncode, code, done.stderr)

    def spec(self, **extra):
        return {"title": "Fleet review", "sections": [
            {"type": "kpis", "items": [{"label": "Trips", "value": 1200, "source": "c_trips"}]},
            {"type": "bars", "title": "Trips by depot", "items": [
                {"label": "North", "value": 700, "highlight": True, "source": "c_depot"},
                {"label": "South", "value": 500, "source": "c_depot"}]}], **extra}

    def test_the_dashboard_theme_uses_the_tokens_and_no_name(self):
        page = dash.render(self.spec(theme="rta"))
        for token in ("brand", "accent", "bg", "bar"):
            self.assertIn(TOKENS["light"][token], page)
            self.assertIn(TOKENS["dark"][token], page)
        self.assertIn("border-inline-start:5px solid var(--accent)", page)
        self.assertIsNone(FORBIDDEN.search(page))
        self.assertNotIn("<script", page)

    def test_the_default_dashboard_is_unchanged_and_themes_are_checked(self):
        self.assertNotIn(TOKENS["light"]["brand"], dash.render(self.spec()))
        self.assertEqual(dash.render(self.spec()), dash.render(self.spec(theme="default")))
        self.assertIn(TOKENS["light"]["brand"], dash.render(self.spec(), theme="rta"))
        self.assertIn("theme must be one of default, rta.", dash.validate(self.spec(theme="neon")))

    def test_restyling_changes_colours_and_type_never_words(self):
        import restyle
        slide = ('<section style="background:#17252F;color:#F6F5F1;font-family:\'IBM Plex Sans\', Arial, sans-serif">'
                 '<p style="color:#E39A4C">Group · briefing</p><h1 style="color:#F6F5F1">Maintain by consequence</h1>'
                 '<div style="background:#F6F5F1"><h2 style="font-family:\'Source Serif 4\', Georgia, serif;'
                 'color:#17252F">Downtime costs 4.5 times</h2><p style="color:#A35A14">$228.9M</p><br>'
                 '<p style="color:#5B6770;border-top:2px solid #DCE2E5">Source: KPI register</p></div></section>')
        out = restyle.Restyler().restyle(slide)
        doc = TOKENS["document"]
        strip = lambda html: re.sub(r"<[^>]+>", "", html)
        self.assertEqual(strip(out), strip(slide))
        self.assertIn(f"background:{doc['primary']};color:{doc['on-primary']}", out)
        # Amber on the dark band becomes the light blue that reads on navy, not the red that would not.
        self.assertIn(f'<p style="color:{doc["primary-4"]}">Group', out)
        # A heading on a light background takes the brand blue; the figure to look at, the red.
        self.assertIn(f"color:{doc['primary']}\">Downtime", out)
        self.assertIn(f'<p style="color:{doc["accent"]}">$228.9M', out)
        self.assertIn(f"border-top:2px solid {doc['rule']}", out)
        self.assertNotIn("'IBM Plex Sans', Arial", out)
        self.assertNotIn("Source Serif", out)
        self.assertEqual(out.count(f"font-family:{TOKENS['document_font']}"), 2)
        for colour, background in ((doc["primary-4"], doc["primary"]), (doc["primary"], doc["page"])):
            self.assertGreaterEqual(contrast(colour, background), 4.5)

    def test_a_text_colour_that_would_not_read_is_replaced(self):
        import restyle
        # Body text inside a red panel: the mapped dark text fails there, so white is used.
        out = restyle.Restyler().restyle('<div style="background:#E39A4C"><p style="color:#17252F">Approve now</p></div>')
        self.assertIn(f'<p style="color:{TOKENS["document"]["on-accent"]}">Approve now', out)

    def test_the_evaluation_report_wears_the_style(self):
        import evaluate_agents as ev
        page = ev.render_html([ev.run_suite("raw_guard")])
        self.assertIn(build.css(TOKENS), page)
        self.assertIn('class="brandbar"', page)
        self.assertIsNone(FORBIDDEN.search(page))


if __name__ == "__main__":
    unittest.main()
