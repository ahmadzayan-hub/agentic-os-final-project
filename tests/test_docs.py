"""Documentation that makes a checkable claim gets checked.

Prose drifts silently. The pipeline grew from thirteen tasks to twenty
and two prompt documents kept telling readers "thirteen stages" — both
had been verified against the code when they were written, which is
exactly why a one-off verification is not enough. These tests fail the
build instead.

Scope is deliberately narrow: only claims with a single right answer in
the code. Nothing here polices style or wording.
"""

import re
import unittest
from pathlib import Path

from server import analytics

DOCS = Path(__file__).resolve().parent.parent
# Decision records are excluded on purpose. An ADR states what was true and
# what was decided on its date; editing "nineteen stages" to "twenty" in a
# record from before the twentieth existed would destroy the thing the file
# is for. A superseded ADR says so at the top and points forward instead.
MARKDOWN = sorted(p for p in DOCS.rglob("*.md")
                  if "node_modules" not in p.parts and ".tmp" not in str(p)
                  and "adr" not in p.parts)

WORD_NUMBERS = {
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "twenty-one": 21,
}


def stage_count():
    return len(analytics.PIPELINE)


def task_count():
    """Stages plus the approval-gated publish task."""
    return len(analytics.PIPELINE) + 1


class PipelineCountsTestCase(unittest.TestCase):
    def test_numeric_pipeline_claims_match_the_code(self):
        patterns = [
            (re.compile(r"(\d+) task rows"), task_count),
            (re.compile(r"// (\d+) of them, in order"), task_count),
            (re.compile(r"(\d+) tasks per run"), task_count),
            (re.compile(r"(\d+) pipeline stages"), stage_count),
        ]
        for path in MARKDOWN:
            text = path.read_text(encoding="utf-8")
            for pattern, expected in patterns:
                for found in pattern.findall(text):
                    self.assertEqual(
                        int(found), expected(),
                        f"{path.relative_to(DOCS)} says {found} where the code "
                        f"says {expected()} — the pipeline changed and the "
                        "document did not")

    def test_spelled_out_pipeline_claims_match_the_code(self):
        """"Nineteen governed specialists" has to mean nineteen."""
        joined = "|".join(WORD_NUMBERS)
        patterns = [
            (re.compile(rf"({joined})\s+(?:governed\s+)?(?:pipeline\s+)?"
                        r"(?:specialists?|stages?)", re.I), stage_count),
            (re.compile(rf"({joined})\s+specialist agents", re.I), stage_count),
            (re.compile(rf"({joined})\s+rows", re.I), task_count),
            (re.compile(rf"({joined})\s+tasks per run", re.I), task_count),
        ]
        for path in MARKDOWN:
            text = path.read_text(encoding="utf-8")
            for pattern, expected in patterns:
                for found in pattern.findall(text):
                    self.assertEqual(
                        WORD_NUMBERS[found.lower()], expected(),
                        f"{path.relative_to(DOCS)} says “{found}” where the "
                        f"code says {expected()}")

    def test_the_catalog_lists_every_stage_that_exists(self):
        """A stage nobody documented is a stage nobody can audit."""
        catalog = (DOCS / "docs" / "AGENT_CATALOG.md").read_text(encoding="utf-8")
        for role, title in analytics.ROLE_TITLES.items():
            # Titles carry a trailing question for the analytics types
            # ("… — what happened?"); the name before it is the identity.
            name = title.split(" — ")[0]
            self.assertIn(name, catalog,
                          f"stage “{role}” ({name}) is missing from the catalog")

    def test_the_orchestrator_is_named_consistently(self):
        for path in (DOCS / "README.md", DOCS / "user_guide.md",
                     DOCS / "docs" / "AGENT_CATALOG.md"):
            self.assertIn(analytics.ORCHESTRATOR,
                          path.read_text(encoding="utf-8"),
                          f"{path.name} does not name the orchestrator")

    def test_the_dataset_limits_quoted_in_docs_are_the_real_ones(self):
        from server import datasets

        megabytes = analytics.MAX_DATASET_BYTES // 1_000_000
        upload = datasets.MAX_UPLOAD_BYTES // 1_000_000
        rows = f"{analytics.MAX_ROWS:,}"
        for path in (DOCS / "README.md", DOCS / "user_guide.md",
                     DOCS / "docs" / "KNOWN_LIMITATIONS.md"):
            text = path.read_text(encoding="utf-8")
            if "MB" in text and "rows" in text:
                self.assertIn(f"{megabytes} MB", text, path.name)
                self.assertIn(f"{upload} MB", text, path.name)
                self.assertIn(rows, text, path.name)


class AgentInstructionsTestCase(unittest.TestCase):
    """AGENTS.md tells other coding agents where things are; keep it true."""

    # Paths that exist only while the application runs.
    RUNTIME = {"vault/"}

    def setUp(self):
        self.text = (DOCS / "AGENTS.md").read_text(encoding="utf-8")

    def test_it_defers_to_claude_md(self):
        self.assertIn("`CLAUDE.md`", self.text)

    def test_every_path_it_names_exists(self):
        named = {p for p in re.findall(r"`([^`\s]+)`", self.text)
                 if "/" in p or re.search(r"\.(md|py|css|example)$", p)}
        self.assertTrue(named)
        for path in sorted(named - self.RUNTIME):
            with self.subTest(path=path):
                self.assertTrue((DOCS / path).exists(), f"AGENTS.md names {path}, which does not exist")

    def test_the_verify_options_it_lists_are_real(self):
        source = (DOCS / "scripts" / "verify.py").read_text(encoding="utf-8")
        for option in re.findall(r"scripts/verify\.py (--[a-z0-9-]+)", self.text):
            with self.subTest(option=option):
                self.assertIn(f'"{option}"', source)


if __name__ == "__main__":
    unittest.main()
