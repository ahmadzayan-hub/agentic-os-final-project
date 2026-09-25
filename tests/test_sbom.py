"""The bill of materials, and the licence gate it carries.

An SBOM is only worth generating if it is right, so the interesting
tests here are the ways it can quietly be wrong: a licence classified
into the wrong family, a dependency listed that the project does not
actually use, a package counted as shipped when it only ever reaches a
developer's machine. Each of those turns the document from evidence into
paperwork.
"""

import json
import re
import unittest
from pathlib import Path

from scripts import sbom

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


class LicenceClassificationTestCase(unittest.TestCase):
    def test_permissive_licences_are_recognised(self):
        for licence in ("MIT", "BSD-3-Clause", "Apache-2.0", "ISC",
                        "Python-2.0", "BSD License"):
            with self.subTest(licence=licence):
                self.assertEqual(sbom._classify(licence), "permissive")

    def test_strong_copyleft_is_recognised(self):
        for licence in ("GPL-3.0", "GPL-3.0-or-later", "AGPL-3.0", "SSPL-1.0",
                        "GPL-2.0-only"):
            with self.subTest(licence=licence):
                self.assertEqual(sbom._classify(licence), "strong-copyleft")

    def test_lgpl_is_weak_not_strong(self):
        """LGPL contains the letters GPL and is a different obligation.
        Classifying it as strong would cry wolf on psycopg2 — which this
        project ships — and a gate that cries wolf gets switched off."""
        for licence in ("LGPL-3.0", "LGPL v3", "GNU LGPL",
                        "LGPL with exceptions"):
            with self.subTest(licence=licence):
                self.assertEqual(sbom._classify(licence), "weak-copyleft")

    def test_other_weak_copyleft_families_are_recognised(self):
        for licence in ("MPL-2.0", "EPL-2.0", "CDDL-1.0"):
            with self.subTest(licence=licence):
                self.assertEqual(sbom._classify(licence), "weak-copyleft")

    def test_a_missing_licence_is_unknown_not_permissive(self):
        """Silence is not permission."""
        self.assertEqual(sbom._classify(None), "unknown")
        self.assertEqual(sbom._classify(""), "unknown")


class RequirementsParsingTestCase(unittest.TestCase):
    def test_the_real_requirements_file_parses(self):
        direct = sbom.direct_python_requirements()
        self.assertIn("fastapi", direct)
        self.assertIn("uvicorn", direct)
        self.assertIn("psycopg2-binary", direct)

    def test_extras_are_carried_because_they_change_the_tree(self):
        direct = sbom.direct_python_requirements()
        self.assertEqual(direct["uvicorn"], {"standard"})
        self.assertEqual(direct["pyjwt"], {"crypto"})

    def test_comments_and_blank_lines_are_ignored(self):
        direct = sbom.direct_python_requirements()
        self.assertTrue(all(name and not name.startswith("#")
                            for name in direct))


class NpmInventoryTestCase(unittest.TestCase):
    def setUp(self):
        self.components = sbom.npm_components()

    def test_every_locked_package_is_listed(self):
        lockfile = json.loads(sbom.LOCKFILE.read_text(encoding="utf-8"))
        locked = [path for path in lockfile["packages"] if path]
        self.assertEqual(len(self.components), len(locked))

    def test_react_is_present_and_marked_as_shipped(self):
        react = next(c for c in self.components if c["name"] == "react")
        self.assertEqual(react["scope"], "required")
        self.assertTrue(sbom.shipped(react))
        self.assertEqual(react["purl"], f"pkg:npm/react@{react['version']}")

    def test_build_tooling_is_listed_but_not_counted_as_shipped(self):
        """Vite reaches a developer, never a user. Treating the two the
        same would put the whole toolchain into a distribution question
        it has nothing to do with."""
        vite = next(c for c in self.components if c["name"] == "vite")
        self.assertEqual(vite["scope"], "optional")
        self.assertFalse(sbom.shipped(vite))

    def test_integrity_hashes_are_carried_through(self):
        react = next(c for c in self.components if c["name"] == "react")
        properties = {p["name"]: p["value"] for p in react["properties"]}
        self.assertTrue(properties["agentic:integrity"].startswith("sha512-"))


class PythonClosureTestCase(unittest.TestCase):
    def setUp(self):
        self.components = sbom.python_components()
        self.names = {c["name"].lower() for c in self.components}

    def test_the_direct_dependencies_are_all_there(self):
        for name in ("fastapi", "uvicorn", "psycopg2-binary", "pyjwt", "httpx"):
            self.assertIn(name, self.names)

    def test_a_transitive_dependency_is_included(self):
        """starlette arrives through fastapi and belongs in the document
        as much as fastapi does — that is what "transitive" means for
        anyone reading the SBOM during an incident."""
        self.assertIn("starlette", self.names)

    def test_an_extra_that_was_asked_for_is_followed(self):
        """requirements.txt says pyjwt[crypto], so cryptography is part
        of this project whether or not anyone imports it directly."""
        self.assertIn("cryptography", self.names)

    def test_the_inventory_describes_the_project_not_the_machine(self):
        """A container carries system packages that have nothing to do
        with this application; naming them sends an incident responder
        chasing dependencies that are not there."""
        for stranger in ("launchpadlib", "pygobject", "wadllib",
                         "lazr.restfulclient"):
            self.assertNotIn(stranger, self.names)

    def test_each_package_appears_once(self):
        names = [c["name"].lower() for c in self.components]
        self.assertEqual(len(names), len(set(names)))

    def test_the_environment_flag_widens_it_deliberately(self):
        everything = {c["name"].lower()
                      for c in sbom.python_components(environment=True)}
        self.assertTrue(self.names <= everything)


class DocumentTestCase(unittest.TestCase):
    def setUp(self):
        self.document = sbom.build()

    def test_it_is_a_cyclonedx_document(self):
        self.assertEqual(self.document["bomFormat"], "CycloneDX")
        self.assertEqual(self.document["specVersion"], "1.5")
        self.assertEqual(self.document["metadata"]["component"]["name"],
                         "agentic-os")

    def test_it_covers_both_ecosystems(self):
        ecosystems = {p["value"] for c in self.document["components"]
                      for p in c["properties"]
                      if p["name"] == "agentic:ecosystem"}
        self.assertEqual(ecosystems, {"npm", "pypi"})

    def test_it_serialises(self):
        json.loads(json.dumps(self.document))


class LicenceGateTestCase(unittest.TestCase):
    def component(self, name, licence, dev=False, scope="required"):
        return {"type": "library", "name": name, "version": "1.0.0",
                "purl": f"pkg:npm/{name}@1.0.0", "scope": scope,
                "licenses": [{"license": {"name": licence}}],
                "properties": [
                    {"name": "agentic:ecosystem", "value": "npm"},
                    {"name": "agentic:dev-only", "value": str(dev).lower()},
                    {"name": "agentic:licence-class",
                     "value": sbom._classify(licence)}]}

    def test_the_real_project_passes_its_own_gate(self):
        report = sbom.summarise(sbom.build())
        blocking = [c for c in report["strong_copyleft"] if sbom.shipped(c)]
        self.assertEqual(blocking, [], "a shipped dependency is copyleft")

    def test_a_shipped_copyleft_dependency_is_caught(self):
        document = {"components": [self.component("trouble", "GPL-3.0")]}
        report = sbom.summarise(document)
        self.assertEqual(len(report["strong_copyleft"]), 1)
        self.assertTrue(sbom.shipped(report["strong_copyleft"][0]))

    def test_a_copyleft_build_tool_is_reported_but_not_blocking(self):
        """A GPL linter is not a distribution question: it never leaves
        the developer's machine."""
        document = {"components": [
            self.component("linter", "GPL-3.0", dev=True, scope="optional")]}
        report = sbom.summarise(document)
        self.assertEqual(len(report["strong_copyleft"]), 1)
        self.assertFalse(sbom.shipped(report["strong_copyleft"][0]))

    def test_a_shipped_weak_copyleft_dependency_is_named_not_buried(self):
        document = {"components": [self.component("driver", "LGPL-3.0")]}
        report = sbom.summarise(document)
        self.assertEqual([c["name"] for c in report["weak_shipped"]],
                         ["driver"])
        self.assertEqual(report["strong_copyleft"], [])

    def test_the_command_reports_its_verdict_through_the_exit_code(self):
        """CI reads the exit code, not the prose."""
        import io
        from contextlib import redirect_stderr, redirect_stdout

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sbom.main(["--output", "-", "--check"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["bomFormat"], "CycloneDX")
        self.assertIn("licence check", err.getvalue())


class PinnedActionsTestCase(unittest.TestCase):
    """Third-party actions must be pinned to a commit, never a tag.

    `actions/checkout@v4` before and after a compromise of that
    repository are the same line of YAML running different code, with a
    token that can write to this repository. Pinning is a one-line habit
    that is easy to lose in a hurry, so it is checked rather than
    remembered.
    """

    def workflows(self):
        found = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
        self.assertTrue(found, "no workflows to check")
        return found

    def test_every_action_is_pinned_to_a_commit(self):
        pattern = re.compile(r"uses:\s*([^\s#]+)")
        for path in self.workflows():
            for reference in pattern.findall(path.read_text(encoding="utf-8")):
                if reference.startswith("./"):
                    continue  # a local action in this repository
                with self.subTest(action=reference):
                    _, _, version = reference.partition("@")
                    self.assertRegex(
                        version, r"^[0-9a-f]{40}$",
                        f"{path.name} uses “{reference}” — a tag can be moved "
                        "by its owner; pin the commit instead")

    def test_every_pin_says_which_release_it_was(self):
        """A bare SHA is unreviewable: nobody can tell an upgrade from a
        substitution without the version beside it."""
        pattern = re.compile(r"uses:\s*([^\s#]+)[^\S\n]*(#.*)?")
        for path in self.workflows():
            for reference, comment in pattern.findall(path.read_text(encoding="utf-8")):
                if reference.startswith("./"):
                    continue
                with self.subTest(action=reference):
                    self.assertRegex(comment or "", r"#\s*v?\d+\.\d+",
                                     f"{path.name}: {reference} has no version "
                                     "comment")


if __name__ == "__main__":
    unittest.main()
