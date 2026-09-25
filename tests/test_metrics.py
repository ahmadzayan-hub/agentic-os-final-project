"""The metric glossary: loading, validation, and arithmetic.

A glossary is only governance if it can be wrong out loud. These tests
are mostly about the ways it refuses: an entry with no definition, a
certification with no owner, a formula that is not an operation, a file
that is not JSON. Each is rejected with a sentence naming the entry,
because "the glossary did not load" tells an operator nothing.
"""

import json
import tempfile
import unittest
from pathlib import Path

from server import metrics


def write(document, directory):
    path = Path(directory) / "metrics.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


VALID = {
    "name": "revenue", "definition": "Invoiced amount after discounts.",
    "owner": "Finance", "certified": True, "columns": ["revenue"],
}


class LoadingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def load(self, document):
        return metrics.load_glossary(path=write(document, self.root))

    def test_no_file_is_a_normal_state_not_an_error(self):
        entries, problems = metrics.load_glossary(
            path=self.root / "absent.json")
        self.assertEqual(entries, [])
        self.assertEqual(problems, [])

    def test_a_valid_glossary_loads(self):
        entries, problems = self.load({"version": 1, "metrics": [VALID]})
        self.assertEqual(problems, [])
        self.assertEqual(entries[0]["name"], "revenue")
        self.assertEqual(entries[0]["title"], "revenue")
        self.assertTrue(entries[0]["certified"])

    def test_the_shipped_example_is_valid(self):
        """A template that does not load is worse than none."""
        example = Path(__file__).resolve().parent.parent / "metrics.example.json"
        entries, problems = metrics.load_glossary(path=example)
        self.assertEqual(problems, [])
        self.assertEqual(len(entries), 3)
        self.assertTrue(any(e["certified"] for e in entries))
        self.assertTrue(any(not e["certified"] for e in entries))

    def test_broken_json_reports_the_file_rather_than_raising(self):
        path = self.root / "metrics.json"
        path.write_text("{not json", encoding="utf-8")
        entries, problems = metrics.load_glossary(path=path)
        self.assertEqual(entries, [])
        self.assertIn("metrics.json", problems[0])

    def test_a_future_version_is_refused_rather_than_guessed_at(self):
        entries, problems = self.load({"version": 99, "metrics": [VALID]})
        self.assertEqual(entries, [])
        self.assertIn("version", problems[0])

    def test_an_entry_with_no_definition_defines_nothing(self):
        entries, problems = self.load({"version": 1, "metrics": [
            {"name": "revenue", "columns": ["revenue"]}]})
        self.assertEqual(entries, [])
        self.assertIn("revenue", problems[0])
        self.assertIn("definition", problems[0])

    def test_certification_without_an_owner_is_refused(self):
        """A certified metric with nobody accountable is a rubber stamp:
        there is no one to ask when the definition turns out to be wrong."""
        entries, problems = self.load({"version": 1, "metrics": [
            {**VALID, "owner": None}]})
        self.assertEqual(entries, [])
        self.assertIn("owner", problems[0])

    def test_an_uncertified_entry_needs_no_owner(self):
        entries, problems = self.load({"version": 1, "metrics": [
            {"name": "aov", "definition": "Revenue per order.",
             "columns": ["aov"], "certified": False}]})
        self.assertEqual(problems, [])
        self.assertEqual(len(entries), 1)

    def test_one_bad_entry_does_not_discard_the_good_ones(self):
        entries, problems = self.load({"version": 1, "metrics": [
            VALID, {"name": "broken"}]})
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(problems), 1)

    def test_a_duplicate_name_is_reported_and_the_first_wins(self):
        entries, problems = self.load({"version": 1, "metrics": [
            VALID, {**VALID, "definition": "Something else entirely."}]})
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["definition"], VALID["definition"])
        self.assertIn("more than once", problems[0])

    def test_an_unknown_formula_operation_is_refused(self):
        entries, problems = self.load({"version": 1, "metrics": [
            {**VALID, "formula": {"exponentiate": ["a", "b"]}}]})
        self.assertEqual(entries, [])
        self.assertIn("exponentiate", problems[0])

    def test_subtract_takes_exactly_two_columns(self):
        entries, problems = self.load({"version": 1, "metrics": [
            {**VALID, "formula": {"subtract": ["a", "b", "c"]}}]})
        self.assertEqual(entries, [])
        self.assertIn("exactly 2", problems[0])

    def test_the_environment_can_point_at_another_file(self):
        path = write({"version": 1, "metrics": [VALID]}, self.root)
        found = metrics.glossary_path(env={metrics.ENV_VAR: str(path)})
        self.assertEqual(found, path)


class FormulaTestCase(unittest.TestCase):
    def test_each_operation_computes_what_it_says(self):
        row = {"a": 10.0, "b": 4.0, "c": 2.0}
        self.assertEqual(metrics.evaluate({"sum": ["a", "b", "c"]}, row), 16.0)
        self.assertEqual(metrics.evaluate({"multiply": ["a", "b"]}, row), 40.0)
        self.assertEqual(metrics.evaluate({"subtract": ["a", "b"]}, row), 6.0)
        self.assertEqual(metrics.evaluate({"divide": ["a", "b"]}, row), 2.5)

    def test_a_missing_or_non_numeric_value_yields_nothing_not_a_guess(self):
        self.assertIsNone(metrics.evaluate({"sum": ["a", "b"]}, {"a": 1.0}))
        self.assertIsNone(metrics.evaluate({"sum": ["a", "b"]},
                                           {"a": 1.0, "b": "x"}))
        self.assertIsNone(metrics.evaluate({"sum": ["a", "b"]},
                                           {"a": 1.0, "b": None}))

    def test_division_by_zero_is_a_property_of_the_row_not_an_error(self):
        self.assertIsNone(metrics.evaluate({"divide": ["a", "b"]},
                                           {"a": 1.0, "b": 0.0}))

    def test_the_formula_reads_back_as_something_checkable_by_hand(self):
        self.assertEqual(
            metrics.formula_text({"multiply": ["unit_price", "units"]}),
            "unit_price × units")

    def test_rounding_is_not_treated_as_a_breach(self):
        """Exact equality on a currency column would flag ordinary
        rounding and teach people to ignore the check."""
        self.assertTrue(metrics.matches(100.004, 100.0))
        self.assertFalse(metrics.matches(120.0, 100.0))


class ConformanceTestCase(unittest.TestCase):
    def rows(self, revenues):
        return [{"unit_price": 10.0, "units": 5.0, "revenue": revenue}
                for revenue in revenues]

    def metric(self):
        return {**VALID, "formula": {"multiply": ["unit_price", "units"]},
                "title": "Net Revenue", "unit": None, "certified_on": None}

    def test_a_column_that_matches_its_definition_reports_a_full_rate(self):
        result = metrics.conformance(self.metric(), self.rows([50.0] * 4),
                                     "revenue")
        self.assertEqual(result["rate"], 1.0)
        self.assertEqual(result["checked"], 4)
        self.assertEqual(result["breaches"], [])

    def test_a_breach_is_counted_and_the_worst_ones_named(self):
        result = metrics.conformance(
            self.metric(), self.rows([50.0, 90.0, 50.0, 200.0]), "revenue")
        self.assertEqual(result["checked"], 4)
        self.assertEqual(result["matching"], 2)
        self.assertEqual(result["breach_count"], 2)
        self.assertEqual(result["breaches"][0]["recorded"], 200.0)
        self.assertEqual(result["breaches"][0]["defined"], 50.0)
        self.assertEqual(result["breaches"][0]["gap"], 150.0)

    def test_missing_inputs_mean_not_checkable_not_checked_and_fine(self):
        """Reporting "no breaches" for a check that never ran would be a
        lie of omission."""
        rows = [{"revenue": 50.0}, {"revenue": 60.0}]
        self.assertIsNone(metrics.conformance(self.metric(), rows, "revenue"))

    def test_rows_the_definition_cannot_reach_are_skipped_and_counted(self):
        rows = self.rows([50.0, 50.0])
        rows[1]["units"] = None
        result = metrics.conformance(self.metric(), rows, "revenue")
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["skipped"], 1)

    def test_a_metric_with_no_formula_is_not_checkable(self):
        self.assertIsNone(metrics.conformance(
            {**VALID, "formula": None}, self.rows([50.0]), "revenue"))


class ResolutionTestCase(unittest.TestCase):
    def entry(self, name, columns, certified=True):
        return {"name": name, "title": name, "definition": "d",
                "owner": "o" if certified else None, "unit": None,
                "certified": certified, "certified_on": None,
                "columns": columns, "formula": None}

    def test_a_certified_metric_outranks_everything_else(self):
        book = [self.entry("units_sold", ["units"])]
        measure, metric, source, _ = metrics.resolve(
            book, ["month", "revenue", "units"], ["revenue", "units"])
        self.assertEqual(measure, "units")
        self.assertEqual(metric["name"], "units_sold")
        self.assertIn("certified", source)

    def test_an_uncertified_definition_still_beats_a_name_hint(self):
        """Somebody writing it down is more intentional than a hard-coded
        list of words."""
        book = [self.entry("units_sold", ["units"], certified=False)]
        measure, _metric, source, _ = metrics.resolve(
            book, ["revenue", "units"], ["revenue", "units"])
        self.assertEqual(measure, "units")
        self.assertIn("not certified", source)

    def test_without_a_glossary_the_name_hint_applies_and_says_so(self):
        measure, metric, source, candidates = metrics.resolve(
            [], ["month", "units", "revenue"], ["units", "revenue"])
        self.assertEqual(measure, "revenue")
        self.assertIsNone(metric)
        self.assertEqual(source, "column name")
        self.assertEqual(candidates, [])

    def test_with_nothing_to_go_on_the_first_numeric_column_is_named_as_such(self):
        measure, _metric, source, _ = metrics.resolve(
            [], ["a", "b"], ["a", "b"])
        self.assertEqual(measure, "a")
        self.assertEqual(source, "first numeric column")

    def test_every_column_a_metric_claims_is_reported_as_a_candidate(self):
        """Two columns answering to a glossary name is how two correct
        reports come to disagree."""
        book = [self.entry("revenue", ["revenue", "net_revenue"])]
        _measure, _metric, _source, candidates = metrics.resolve(
            book, ["revenue", "net_revenue"], ["revenue", "net_revenue"])
        self.assertEqual([c["column"] for c in candidates],
                         ["revenue", "net_revenue"])

    def test_column_matching_ignores_case(self):
        book = [self.entry("revenue", ["Revenue"])]
        measure, metric, _source, _ = metrics.resolve(
            book, ["REVENUE"], ["REVENUE"])
        self.assertEqual(measure, "REVENUE")
        self.assertIsNotNone(metric)


if __name__ == "__main__":
    unittest.main()
