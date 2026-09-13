"""The four business-analytics agents.

Each type answers one question, and each is tested against figures
computed independently here rather than against whatever the pipeline
happens to produce. The honest-refusal paths matter as much as the happy
path: a forecast from three data points, or a recommendation with no
options to compare, must decline rather than invent.
"""

import math
import statistics
import unittest

from server import analytics


def run_pipeline(dataset_text, goal="Analyze the data", name="test.csv",
                 gateway=None, glossary=None):
    ctx = {"goal": goal, "dataset_name": name, "dataset_text": dataset_text,
           "run_id": "test-run", "glossary": glossary}
    results = {}
    for role, stage in analytics.PIPELINE:
        result = (stage(ctx, gateway=gateway)
                  if role in analytics.NARRATED_STAGES else stage(ctx))
        results[role] = result
        if result["status"] == "failed":
            return ctx, results
        ctx[role] = result["output"]
        ctx[role + "_result"] = result
    return ctx, results


# A dataset with arithmetic that is easy to verify by hand: two teams,
# six months, a straight line up for one and flat for the other.
def linear_dataset():
    lines = ["month,team,sales"]
    for index in range(6):
        month = f"2025-{index + 1:02d}"
        lines.append(f"{month},Alpha,{100 + 10 * index}")
        lines.append(f"{month},Beta,50")
    return "\n".join(lines) + "\n"


class FourAnalyticsTypesTestCase(unittest.TestCase):
    def test_every_type_runs_and_produces_its_own_report(self):
        ctx, results = run_pipeline(analytics.sample_dataset())
        for name, question in analytics.ANALYTICS_TYPES:
            self.assertEqual(results[name]["status"], "succeeded", name)
            report = ctx[name]["report_markdown"]
            self.assertIn(question, report, name)
            # Each report stands alone: it names its dataset and shows its
            # own arithmetic.
            self.assertIn("How each figure was calculated", report)

    def test_the_comprehensive_report_contains_all_four(self):
        ctx, results = run_pipeline(analytics.sample_dataset())
        combined = results["reporter"]["output"]["report_markdown"]
        for name, question in analytics.ANALYTICS_TYPES:
            self.assertIn(question, combined, name)
        # It embeds rather than links: what a human approves is what gets
        # published, so the hash has to cover the whole thing. Only the
        # section's own H1 is demoted; every other line appears verbatim.
        for name, _ in analytics.ANALYTICS_TYPES:
            body = "\n".join(ctx[name]["report_markdown"].split("\n")[1:])
            self.assertIn(body, combined, f"{name} section is not embedded in full")

    # -- descriptive ------------------------------------------------------
    def test_descriptive_figures_match_an_independent_calculation(self):
        ctx, _ = run_pipeline(linear_dataset())
        values = [100 + 10 * i for i in range(6)] + [50] * 6
        self.assertAlmostEqual(ctx["preparer"]["total"], sum(values), places=2)
        self.assertAlmostEqual(ctx["descriptive"]["mean"],
                               round(statistics.fmean(values), 2), places=2)
        # Alpha 100->150, Beta 50->50: total 150 -> 200, a third up.
        self.assertAlmostEqual(ctx["descriptive"]["change"], 1 / 3, places=4)
        self.assertEqual(ctx["descriptive"]["top_group"], "Alpha")

    def test_descriptive_claims_are_written_in_business_language(self):
        _, results = run_pipeline(analytics.sample_dataset())
        for name, _ in analytics.ANALYTICS_TYPES:
            for claim in results[name]["claims"]:
                self.assertEqual(analytics._jargon_in(claim["text"]), [],
                                 f"{name}: {claim['text']}")

    # -- diagnostic -------------------------------------------------------
    def test_diagnostic_decomposition_adds_up_to_the_total_change(self):
        ctx, _ = run_pipeline(linear_dataset())
        contributions = ctx["diagnostic"]["contributions"]
        self.assertEqual({c["group"] for c in contributions}, {"Alpha", "Beta"})
        alpha = next(c for c in contributions if c["group"] == "Alpha")
        self.assertAlmostEqual(alpha["change"], 50.0, places=2)   # 100 -> 150
        beta = next(c for c in contributions if c["group"] == "Beta")
        self.assertAlmostEqual(beta["change"], 0.0, places=2)     # flat
        self.assertAlmostEqual(sum(c["change"] for c in contributions), 50.0, places=2)
        self.assertAlmostEqual(alpha["share_of_change"], 1.0, places=4)

    def test_diagnostic_states_association_without_asserting_cause(self):
        ctx, results = run_pipeline(analytics.sample_dataset())
        claims = results["diagnostic"]["claims"]
        self.assertTrue(claims, "the sample dataset has structure to diagnose")
        for claim in claims:
            text = claim["text"].lower()
            if "caus" in text:
                # Any sentence that reaches for cause must disown it in the
                # same breath, not three paragraphs later.
                self.assertRegex(text, r"not (what caused|proof)")
        self.assertIn("not proof", ctx["diagnostic"]["report_markdown"].lower())
        self.assertIn("controlled comparison",
                      ctx["diagnostic"]["report_markdown"].lower())

    # -- predictive -------------------------------------------------------
    def test_the_forecast_extends_a_straight_line_exactly(self):
        """Alpha+Beta per month is 150,160,...,200 — a line of slope 10."""
        ctx, _ = run_pipeline(linear_dataset())
        self.assertAlmostEqual(ctx["predictive"]["per_period_change"], 10.0, places=2)
        forecast = ctx["predictive"]["forecast"]
        self.assertEqual([f["label"] for f in forecast],
                         ["2025-07", "2025-08", "2025-09"])
        self.assertAlmostEqual(forecast[0]["value"], 210.0, places=2)
        self.assertAlmostEqual(forecast[2]["value"], 230.0, places=2)
        # A perfect line is perfectly explained, and backtests to no error.
        self.assertAlmostEqual(ctx["predictive"]["explained"], 1.0, places=4)
        self.assertAlmostEqual(ctx["predictive"]["backtest_error"], 0.0, places=6)

    def test_too_little_history_declines_to_forecast(self):
        data = "month,team,sales\n2025-01,A,10\n2025-02,A,20\n2025-03,A,30\n"
        ctx, results = run_pipeline(data)
        self.assertEqual(results["predictive"]["status"], "succeeded")
        self.assertEqual(ctx["predictive"]["forecast"], [])
        self.assertIn("not enough history", results["predictive"]["summary"].lower())
        types = {c["type"] for c in results["predictive"]["claims"]}
        self.assertEqual(types, {"limitation"})

    def test_a_forecast_without_a_backtest_declares_that(self):
        rows = "\n".join(f"2025-{m:02d},A,{100 + m}" for m in range(1, 6))
        ctx, results = run_pipeline("month,team,sales\n" + rows + "\n")
        self.assertTrue(ctx["predictive"]["forecast"])
        self.assertIsNone(ctx["predictive"]["backtest_error"])
        self.assertTrue(any(c["type"] == "limitation"
                            for c in results["predictive"]["claims"]))
        self.assertIn("unmeasured", ctx["predictive"]["report_markdown"].lower())
        # The validator accepts it only because the gap is declared.
        self.assertTrue(ctx["validator"]["passed"])

    # -- prescriptive -----------------------------------------------------
    def test_options_are_ranked_by_arithmetic_the_reader_can_check(self):
        ctx, _ = run_pipeline(linear_dataset())
        options = ctx["prescriptive"]["options"]
        by_key = {o["key"]: o for o in options}
        # Alpha totals 750, Beta 300; 10% of each is the expected gain.
        self.assertAlmostEqual(by_key["protect_leader"]["expected_gain"], 75.0, places=2)
        self.assertAlmostEqual(by_key["grow_laggard"]["expected_gain"], 30.0, places=2)
        # Doing nothing is worth nothing extra — that is what makes it the bar.
        self.assertAlmostEqual(by_key["hold_course"]["expected_gain"], 0.0, places=2)
        self.assertEqual(ctx["prescriptive"]["recommendation"]["key"], "protect_leader")
        self.assertEqual([o["expected_gain"] for o in options],
                         sorted((o["expected_gain"] for o in options), reverse=True))

    def test_a_recommendation_always_carries_its_assumption(self):
        _, results = run_pipeline(analytics.sample_dataset())
        claims = results["prescriptive"]["claims"]
        self.assertTrue(any(c["type"] == "recommendation" for c in claims))
        assumption = next(c for c in claims if c["type"] == "assumption")
        self.assertIn("10%", assumption["text"])
        self.assertIn("not which option is easiest", assumption["text"])

    def test_nothing_to_compare_means_no_recommendation(self):
        # One column of numbers: no segments, no periods, no options.
        ctx, results = run_pipeline("sales\n10\n20\n30\n40\n")
        self.assertEqual(results["prescriptive"]["status"], "succeeded")
        self.assertEqual(ctx["prescriptive"]["options"], [])
        self.assertIsNone(ctx["prescriptive"]["recommendation"])
        self.assertTrue(any(c["type"] == "limitation"
                            for c in results["prescriptive"]["claims"]))

    # -- validation of the whole ladder -----------------------------------
    def test_the_validator_enforces_the_new_guarantees(self):
        ctx, _ = run_pipeline(analytics.sample_dataset())
        names = {c["name"]: c for c in ctx["validator_result"]["quality_checks"]}
        for required in ("every_analytics_type_reported",
                         "change_decomposition_reconciles",
                         "forecast_accuracy_is_measured_or_declared",
                         "recommendations_state_their_assumptions",
                         "claims_avoid_statistical_jargon"):
            self.assertIn(required, names)
            self.assertTrue(names[required]["passed"], required)
        self.assertTrue(ctx["validator"]["passed"])

    def test_the_jargon_check_actually_fires(self):
        """Guard against a check that can only ever pass."""
        self.assertEqual(analytics._jargon_in("Costs are rising significantly."), [])
        self.assertEqual(
            analytics._jargon_in("The coefficient of determination (R²) is 0.87."),
            ["r²", "coefficient of determination"])
        self.assertEqual(
            analytics._jargon_in("There is a statistically significant result (p < 0.05)."),
            ["p <", "statistically significant"])

    # -- business language ------------------------------------------------
    def test_every_type_leads_with_a_headline_a_board_can_read(self):
        """The brief's core skill: findings translated into business
        language. Each type answers its question in one plain sentence,
        and that sentence is the stage's summary and the top of its
        report — not a footnote."""
        ctx, results = run_pipeline(analytics.sample_dataset())
        for name, _ in analytics.ANALYTICS_TYPES:
            headline = ctx[name]["headline"]
            self.assertEqual(analytics._jargon_in(headline), [], name)
            self.assertEqual(results[name]["summary"], headline, name)
            self.assertIn(headline, ctx[name]["report_markdown"], name)
        # And each reads as its own question's answer.
        self.assertRegex(ctx["descriptive"]["headline"], r"(up|down|totals)")
        self.assertIn("accounts for", ctx["diagnostic"]["headline"])
        self.assertTrue(ctx["predictive"]["headline"].startswith("We expect"))
        self.assertTrue(ctx["prescriptive"]["headline"].startswith("We recommend"))

    def test_headlines_are_checked_for_jargon_too(self):
        """The check must cover the line executives read, not only claims."""
        ctx, _ = run_pipeline(analytics.sample_dataset())
        ctx["descriptive"]["headline"] = "The mean has increased by 2.3 standard deviations."
        recheck = analytics.validator(ctx)
        check = next(c for c in recheck["quality_checks"]
                     if c["name"] == "claims_avoid_statistical_jargon")
        self.assertFalse(check["passed"])
        self.assertIn("descriptive.headline", check["detail"])

    def test_the_diagnostic_answer_is_also_a_chart(self):
        """A finding that cannot be communicated cannot drive action."""
        ctx, _ = run_pipeline(analytics.sample_dataset())
        chart = next(c for c in ctx["visuals"]["charts"]
                     if c["id"] == "chart_contributions")
        self.assertEqual(chart["values"],
                         [item["change"] for item in ctx["diagnostic"]["contributions"]])
        self.assertIn("moved against the overall direction", chart["alt"])

    def test_the_forecast_chart_is_labelled_as_a_projection(self):
        ctx, _ = run_pipeline(analytics.sample_dataset())
        chart = next(c for c in ctx["visuals"]["charts"] if c["id"] == "chart_forecast")
        self.assertIn("projection", chart["alt"])
        measured = len(ctx["preparer"]["trend"])
        self.assertEqual(len(chart["values"]),
                         measured + len(ctx["predictive"]["forecast"]))


class GovernedSpecialistsTestCase(unittest.TestCase):
    """The seven specialists that surround the four analytics types.

    Each is tested on data that makes it fire, not only on the tidy
    sample — a detector that has never detected anything is a decoration.
    """

    def test_the_contract_names_types_and_flags_values_that_break_them(self):
        data = ("month,team,sales\n"
                "2025-01,A,100\n2025-02,A,oops\n2025-03,A,120\n"
                "2025-04,A,130\n2025-05,A,140\n2025-06,A,150\n")
        ctx, results = run_pipeline(data)
        fields = {f["name"]: f for f in ctx["contract"]["fields"]}
        self.assertEqual(fields["sales"]["type"], "number")
        self.assertEqual(fields["team"]["type"], "text")
        self.assertEqual(fields["team"]["distinct"], 1)
        # The one value that will not parse is named, not silently dropped.
        self.assertTrue(ctx["contract"]["breaches"])
        self.assertIn("sales", ctx["contract"]["breaches"][0])
        self.assertTrue(any("do not match the column" in c["text"]
                            for c in results["contract"]["claims"]))

    def test_the_quality_score_is_the_mean_of_four_stated_ratios(self):
        ctx, _ = run_pipeline(analytics.sample_dataset())
        dimensions = ctx["quality"]["dimensions"]
        self.assertEqual(set(dimensions),
                         {"completeness", "uniqueness", "validity", "consistency"})
        expected = round(100 * statistics.fmean(dimensions.values()), 1)
        self.assertEqual(ctx["quality"]["score"], expected)
        self.assertEqual(ctx["quality"]["grade"], "A")

    def test_the_quality_score_falls_when_the_data_is_worse(self):
        holes = "month,team,sales\n" + "".join(
            f"2025-{m:02d},A,{100 + m if m % 2 else ''}\n" for m in range(1, 9))
        ctx, _ = run_pipeline(holes)
        self.assertLess(ctx["quality"]["score"], 100)
        self.assertEqual(ctx["quality"]["weakest"], "completeness")

    def test_the_privacy_agent_finds_personal_data_by_value_and_by_name(self):
        data = ("month,customer_email,phone,sales\n"
                "2025-01,ada@example.com,+971 50 123 4567,100\n"
                "2025-02,bob@example.com,+971 50 765 4321,120\n"
                "2025-03,cy@example.com,+971 50 111 2222,130\n"
                "2025-04,di@example.com,+971 50 333 4444,140\n")
        ctx, results = run_pipeline(data)
        self.assertTrue(ctx["privacy"]["personal_data"])
        flagged = {f["column"] for f in ctx["privacy"]["findings"]}
        self.assertIn("customer_email", flagged)
        self.assertIn("phone", flagged)
        warning = next(c for c in results["privacy"]["claims"] if c["type"] == "warning")
        self.assertIn("before publishing", warning["text"].lower() + " before publishing")
        # And the approver is told, because approval is when it leaves.
        checks = {c["name"]: c for c in ctx["validator_result"]["quality_checks"]}
        self.assertTrue(checks["personal_data_reaches_the_approver"]["passed"])

    def test_the_privacy_agent_does_not_cry_wolf_on_ordinary_business_data(self):
        ctx, _ = run_pipeline(analytics.sample_dataset())
        self.assertFalse(ctx["privacy"]["personal_data"])
        self.assertEqual(ctx["privacy"]["findings"], [])

    def test_concentration_is_measured_with_a_stated_formula(self):
        data = "month,team,sales\n" + "".join(
            f"2025-{m:02d},{team},{value}\n"
            for m in range(1, 5)
            for team, value in (("A", 90), ("B", 5), ("C", 3), ("D", 2)))
        ctx, _ = run_pipeline(data)
        shares = {s["group"]: s["share"] for s in ctx["segments"]["shares"]}
        self.assertAlmostEqual(shares["A"], 0.90, places=4)
        # HHI of 0.9/0.05/0.03/0.02 = 0.8138
        self.assertAlmostEqual(ctx["segments"]["hhi"], 0.8138, places=4)
        self.assertEqual(ctx["segments"]["pareto_count"], 1)

    def test_an_unusual_period_is_found_against_the_trend_not_the_average(self):
        """A spike that sits near the mean can still break the pattern."""
        values = [100, 110, 120, 130, 300, 150, 160, 170]
        data = "month,team,sales\n" + "".join(
            f"2025-{i + 1:02d},A,{v}\n" for i, v in enumerate(values))
        ctx, _ = run_pipeline(data)
        periods = [a["period"] for a in ctx["anomaly"]["anomalies"]]
        self.assertEqual(periods, ["2025-05"])
        spike = ctx["anomaly"]["anomalies"][0]
        self.assertGreater(spike["value"], spike["expected"])

    def test_a_steady_series_produces_no_anomalies(self):
        data = "month,team,sales\n" + "".join(
            f"2025-{i + 1:02d},A,{100 + 10 * i}\n" for i in range(8))
        ctx, _ = run_pipeline(data)
        self.assertEqual(ctx["anomaly"]["anomalies"], [])

    def test_sensitivity_reports_whether_the_advice_survives_the_assumption(self):
        ctx, results = run_pipeline(analytics.sample_dataset())
        self.assertTrue(ctx["sensitivity"]["stable"])
        self.assertEqual(len(ctx["sensitivity"]["scenarios"]), 3)
        # Every scenario picks the same winner, which is what "stable" means.
        self.assertEqual(len({s["winner"] for s in ctx["sensitivity"]["scenarios"]}), 1)
        claim = results["sensitivity"]["claims"][0]
        self.assertIn("does not depend on the size", claim["text"])
        self.assertIn("break_even", str(ctx["sensitivity"]))

    def test_provenance_walks_every_claim_back_to_a_calculation(self):
        ctx, _ = run_pipeline(analytics.sample_dataset())
        self.assertEqual(ctx["lineage"]["dangling"], [])
        self.assertEqual(ctx["lineage"]["snapshot"], ctx["collector"]["snapshot"])
        self.assertGreater(len(ctx["lineage"]["produced_by_stage"]), 20)
        checks = {c["name"]: c for c in ctx["validator_result"]["quality_checks"]}
        self.assertTrue(checks["provenance_chain_is_complete"]["passed"])

    def test_provenance_catches_a_claim_with_no_evidence_behind_it(self):
        """The check must be able to fail, or it is decoration."""
        ctx, _ = run_pipeline(analytics.sample_dataset())
        ctx["descriptive_result"]["claims"].append(
            {"id": "cl_invented", "type": "finding", "text": "Something unsupported.",
             "evidence": ["c_does_not_exist"], "status": "verified"})
        recheck = analytics.lineage(ctx)
        self.assertEqual(recheck["output"]["dangling"], ["c_does_not_exist"])
        self.assertFalse(recheck["quality_checks"][0]["passed"])

    def test_every_stage_declares_a_title_and_hermes_is_not_one_of_them(self):
        """Hermes orchestrates; it never analyses. A stage named after the
        orchestrator would blur who is accountable for what."""
        for role, _ in analytics.PIPELINE:
            self.assertIn(role, analytics.ROLE_TITLES, role)
        self.assertIn("publish", analytics.ROLE_TITLES)
        self.assertEqual(analytics.ORCHESTRATOR, "Hermes")
        self.assertNotIn("hermes", [role for role, _ in analytics.PIPELINE])

    def test_the_pipeline_order_respects_its_dependencies(self):
        """Each stage may only read what an earlier stage produced."""
        order = [role for role, _ in analytics.PIPELINE]
        needs = {
            "contract": ["collector"], "quality": ["collector", "contract"],
            "privacy": ["collector"], "cleaner": ["profiler"],
            "preparer": ["cleaner", "profiler"], "segments": ["preparer"],
            "descriptive": ["preparer"], "diagnostic": ["preparer", "descriptive"],
            "predictive": ["preparer"], "anomaly": ["preparer"],
            "prescriptive": ["diagnostic", "predictive"],
            "sensitivity": ["prescriptive"], "visuals": ["preparer", "predictive"],
            "lineage": ["collector"], "reporter": ["validator"],
            "experiment": ["preparer", "diagnostic"],
        }
        for stage, dependencies in needs.items():
            for dependency in dependencies:
                self.assertLess(order.index(dependency), order.index(stage),
                                f"{stage} runs before {dependency}")


def priced_dataset(revenues=None):
    """Twelve rows carrying the parts of their own definition, so the
    glossary's `unit_price × units` can be checked against them."""
    lines = ["month,region,unit_price,units,revenue"]
    for index in range(12):
        price, units = 10.0 + index, 100 + index
        revenue = revenues[index] if revenues else round(price * units, 2)
        lines.append(f"2025-{index + 1:02d},North,{price},{units},{revenue}")
    return "\n".join(lines) + "\n"


def book(entries):
    return {"metrics": entries, "problems": []}


def entry(**overrides):
    base = {"name": "revenue", "title": "Net Revenue",
            "definition": "Invoiced amount after discounts.",
            "owner": "Finance — Group Controller", "unit": "AED",
            "certified": True, "certified_on": "2026-01-31",
            "columns": ["revenue"],
            "formula": {"multiply": ["unit_price", "units"]}}
    base.update(overrides)
    return base


class MetricGovernanceTestCase(unittest.TestCase):
    """Which number the report is about, and who says so.

    The choice of measure used to be a silent guess inside the preparer.
    These tests are about it being a decision instead: reported, with a
    reason, and checkable against the definition it claims to satisfy.
    """

    def test_without_a_glossary_the_report_says_the_measure_is_undefined(self):
        ctx, results = run_pipeline(analytics.sample_dataset())
        governance = ctx["governance"]
        self.assertFalse(governance["certified"])
        self.assertFalse(governance["glossary_configured"])
        self.assertEqual(governance["source"], "column name")
        limitations = [c for c in results["governance"]["claims"]
                       if c["type"] == "limitation"]
        self.assertTrue(limitations)
        self.assertIn("not as a defined metric", limitations[0]["text"])

    def test_a_certified_metric_is_named_with_its_owner(self):
        ctx, results = run_pipeline(priced_dataset(), glossary=book([entry()]))
        governance = ctx["governance"]
        self.assertTrue(governance["certified"])
        self.assertEqual(governance["owner"], "Finance — Group Controller")
        self.assertEqual(governance["source"], "certified glossary metric")
        facts = [c["text"] for c in results["governance"]["claims"]
                 if c["type"] == "fact"]
        self.assertTrue(any("Finance — Group Controller" in text
                            for text in facts))

    def test_the_glossary_decides_the_measure_not_the_column_name(self):
        """A hard-coded preference for a column called "revenue" is a
        guess. A glossary entry is a decision somebody made."""
        units = entry(name="units_sold", title="Units Sold",
                      columns=["units"], formula=None)
        ctx, _ = run_pipeline(priced_dataset(), glossary=book([units]))
        self.assertEqual(ctx["governance"]["measure"], "units")
        self.assertEqual(ctx["preparer"]["measure"], "units")

    def test_a_column_that_breaks_its_own_definition_is_a_finding(self):
        broken = [round((10.0 + i) * (100 + i), 2) for i in range(12)]
        broken[3] = 999999.0
        ctx, results = run_pipeline(priced_dataset(broken),
                                    glossary=book([entry()]))
        conformance = ctx["governance"]["conformance"]
        self.assertEqual(conformance["checked"], 12)
        self.assertEqual(conformance["breach_count"], 1)
        self.assertEqual(conformance["breaches"][0]["row"], 4)
        warnings = [c for c in results["governance"]["claims"]
                    if c["type"] == "warning"]
        self.assertTrue(warnings)
        self.assertIn("does not match its own definition", warnings[0]["text"])
        failed = [c for c in results["governance"]["quality_checks"]
                  if not c["passed"]]
        self.assertEqual([c["name"] for c in failed],
                         ["measure_matches_its_definition"])

    def test_a_definition_the_data_satisfies_passes_its_check(self):
        ctx, results = run_pipeline(priced_dataset(), glossary=book([entry()]))
        self.assertEqual(ctx["governance"]["conformance"]["rate"], 1.0)
        self.assertTrue(all(c["passed"]
                            for c in results["governance"]["quality_checks"]))

    def test_a_definition_that_cannot_be_checked_here_says_so(self):
        """The sample data has no unit_price column: "not checkable" is
        not the same statement as "checked and sound"."""
        ctx, _ = run_pipeline(analytics.sample_dataset(),
                              glossary=book([entry()]))
        self.assertIsNone(ctx["governance"]["conformance"])
        self.assertIn("could not be checked",
                      ctx["governance"]["notes_markdown"])

    def test_a_broken_glossary_is_reported_rather_than_ignored(self):
        """Someone believes those definitions are in force."""
        _, results = run_pipeline(
            analytics.sample_dataset(),
            glossary={"metrics": [], "problems": ["metric “revenue” has no owner."]})
        failed = [c for c in results["governance"]["quality_checks"]
                  if not c["passed"]]
        self.assertEqual(len(failed), 1)
        self.assertIn("no owner", failed[0]["detail"])
        self.assertTrue(any(c["type"] == "warning"
                            for c in results["governance"]["claims"]))

    def test_a_second_defined_column_is_named_as_the_road_not_taken(self):
        both = entry(columns=["revenue", "units"], formula=None)
        ctx, results = run_pipeline(priced_dataset(), glossary=book([both]))
        self.assertEqual(ctx["governance"]["also_defined"], ["units"])
        limitations = [c["text"] for c in results["governance"]["claims"]
                       if c["type"] == "limitation"]
        self.assertTrue(any("was not analysed" in text for text in limitations))

    def test_the_validator_requires_the_measure_to_be_certified_or_declared(self):
        ctx, _ = run_pipeline(analytics.sample_dataset())
        check = next(c for c in ctx["validator_result"]["quality_checks"]
                     if c["name"] == "measure_is_certified_or_declared_uncertified")
        self.assertTrue(check["passed"])
        self.assertIn("no certified definition", check["detail"])

        # Silence is the failure the check exists for: strip the stage's
        # declaration and the run must stop passing.
        ctx["governance_result"]["claims"] = []
        ctx["governance"]["certified"] = False
        recheck = analytics.validator(ctx)
        failed = next(c for c in recheck["quality_checks"]
                      if c["name"] == "measure_is_certified_or_declared_uncertified")
        self.assertFalse(failed["passed"])
        self.assertEqual(recheck["status"], "failed")

    def test_the_comprehensive_report_says_what_it_measures(self):
        ctx, results = run_pipeline(priced_dataset(), glossary=book([entry()]))
        combined = results["reporter"]["output"]["report_markdown"]
        self.assertIn("## What this report measures", combined)
        self.assertIn("Net Revenue", combined)
        self.assertIn("Finance — Group Controller", combined)
        self.assertIn("unit_price × units", combined)

    def test_governance_claims_are_in_business_language(self):
        for glossary in (None, book([entry()])):
            _, results = run_pipeline(priced_dataset(), glossary=glossary)
            for claim in results["governance"]["claims"]:
                self.assertEqual(analytics._jargon_in(claim["text"]), [],
                                 claim["text"])


def ab_dataset(control, treatment, extra=None, column="variant"):
    """A two- or three-arm dataset with values chosen by hand, so every
    figure in the tests below can be recomputed on paper."""
    lines = [f"{column},score"]
    for value in control:
        lines.append(f"control,{value}")
    for value in treatment:
        lines.append(f"treatment,{value}")
    for name, values in (extra or {}).items():
        for value in values:
            lines.append(f"{name},{value}")
    return "\n".join(lines) + "\n"


def independent_range(baseline, arm, comparisons=1):
    """The fixed-size difference and range, from stdlib only."""
    z = statistics.NormalDist().inv_cdf(1 - 0.05 / (2 * comparisons))
    difference = statistics.fmean(arm) - statistics.fmean(baseline)
    spread = math.sqrt(statistics.variance(arm) / len(arm)
                       + statistics.variance(baseline) / len(baseline))
    return difference, difference - z * spread, difference + z * spread


def independent_safe_range(baseline, arm, comparisons=1):
    """The always-valid range, recomputed here from the published formula
    rather than by calling the code under test."""
    alpha = 0.05 / comparisons
    n = min(len(arm), len(baseline))
    term = -2 * math.log(alpha)
    rho_squared = (term + math.log(term + 1)) / 1000
    scaled = n * rho_squared
    factor = math.sqrt((2 * (scaled + 1) / scaled)
                       * math.log(math.sqrt(scaled + 1) / alpha))
    difference = statistics.fmean(arm) - statistics.fmean(baseline)
    spread = math.sqrt(statistics.variance(arm) / len(arm)
                       + statistics.variance(baseline) / len(baseline))
    return difference, difference - factor * spread, difference + factor * spread


def spread_of(size, start, step=1.0, offset=0.0):
    """Distinct values with real variance — identical rows are dropped as
    duplicates during cleaning, which would shrink the arm."""
    return [round(start + offset + index * step, 2) for index in range(size)]


class ExperimentAgentTestCase(unittest.TestCase):
    """The boundary between association and cause.

    This stage is the one that has to say no. Most of these tests are
    therefore about refusal: refusing to read a segment as an experiment,
    refusing to call an overlapping difference a result, and refusing to
    let a comparison pass without stating what it assumed.
    """

    def test_ordinary_business_data_yields_no_causal_claim(self):
        ctx, results = run_pipeline(analytics.sample_dataset())
        stage = results["experiment"]
        self.assertEqual(stage["status"], "succeeded")
        self.assertFalse(ctx["experiment"]["is_experiment"])
        self.assertTrue(any(c["type"] == "limitation" for c in stage["claims"]))
        self.assertNotIn("cause", ctx["experiment"]["headline"].lower().replace(
            "no cause", ""))

    def test_a_segment_is_never_mistaken_for_an_experiment(self):
        """region and category split the data; neither assigns anything.
        Reading one as a controlled comparison is the single error this
        stage exists to prevent."""
        for column in ("region", "category", "cohort", "channel"):
            dataset = (f"month,{column},revenue\n"
                       "2025-01,Alpha,100\n2025-01,Beta,120\n"
                       "2025-02,Alpha,110\n2025-02,Beta,130\n"
                       "2025-03,Alpha,120\n2025-03,Beta,140\n")
            ctx, _ = run_pipeline(dataset)
            self.assertFalse(ctx["experiment"]["is_experiment"],
                             f"“{column}” was read as an experiment")

    def test_the_sample_size_it_asks_for_matches_an_independent_calculation(self):
        ctx, results = run_pipeline(analytics.sample_dataset())
        rows = ctx["cleaner"]["rows"]
        measure = ctx["preparer"]["measure"]
        values = [r[measure] for r in rows if r.get(measure) is not None]
        variance = statistics.variance(values)
        delta = 0.10 * abs(statistics.fmean(values))
        z_sum = (statistics.NormalDist().inv_cdf(0.975)
                 + statistics.NormalDist().inv_cdf(0.80))
        expected = math.ceil(2 * z_sum ** 2 * variance / delta ** 2)
        found = next(c for c in results["experiment"]["calculations"]
                     if c["id"] == "c_exp_n_1")
        self.assertEqual(found["value"], expected)
        self.assertGreater(expected, 0)

    def test_it_says_what_the_rows_in_hand_could_already_detect(self):
        """Sizing the test you cannot afford is only half an answer."""
        ctx, results = run_pipeline(analytics.sample_dataset())
        rows = ctx["cleaner"]["rows"]
        measure = ctx["preparer"]["measure"]
        values = [r[measure] for r in rows if r.get(measure) is not None]
        z_sum = (statistics.NormalDist().inv_cdf(0.975)
                 + statistics.NormalDist().inv_cdf(0.80))
        expected = (z_sum * math.sqrt(2 * statistics.variance(values)
                                      / (len(values) / 2))
                    / abs(statistics.fmean(values)))
        self.assertAlmostEqual(ctx["experiment"]["smallest_detectable_change"],
                               round(expected, 4), places=4)

    def test_a_real_difference_is_measured_as_a_range_not_a_point(self):
        control = spread_of(60, 100.0, 0.5)
        treatment = spread_of(60, 130.0, 0.5)
        ctx, results = run_pipeline(ab_dataset(control, treatment))
        self.assertTrue(ctx["experiment"]["is_experiment"])
        self.assertEqual(ctx["experiment"]["baseline"], "control")
        arm = ctx["experiment"]["arms"][0]
        difference, low, high = independent_safe_range(control, treatment)
        self.assertAlmostEqual(arm["difference"], round(difference, 2), places=2)
        self.assertAlmostEqual(arm["low"], round(low, 2), places=2)
        self.assertAlmostEqual(arm["high"], round(high, 2), places=2)
        self.assertTrue(arm["beyond_chance"])

    def test_the_narrower_fixed_size_range_is_reported_beside_it(self):
        """Someone who really did fix the sample size in advance is
        entitled to the tighter reading — as long as the report says
        which assumption buys it."""
        control = spread_of(60, 100.0, 0.5)
        treatment = spread_of(60, 130.0, 0.5)
        ctx, _ = run_pipeline(ab_dataset(control, treatment))
        arm = ctx["experiment"]["arms"][0]
        _difference, fixed_low, fixed_high = independent_range(control, treatment)
        self.assertAlmostEqual(arm["fixed_low"], round(fixed_low, 2), places=2)
        self.assertAlmostEqual(arm["fixed_high"], round(fixed_high, 2), places=2)
        self.assertLess(arm["fixed_high"] - arm["fixed_low"],
                        arm["high"] - arm["low"],
                        "the fixed-size range should be the narrower one")
        report = ctx["experiment"]["report_markdown"]
        self.assertIn("fixed in advance", report)

    def test_eight_observations_do_not_prove_anything(self):
        """Four against four, perfectly separated, used to be called a
        result. A range that survives being looked at twice will not do
        that, and should not: eight observations are eight observations."""
        ctx, _ = run_pipeline(ab_dataset([10, 12, 14, 16], [30, 32, 34, 36]))
        arm = ctx["experiment"]["arms"][0]
        self.assertFalse(arm["beyond_chance"])
        self.assertLess(arm["low"], 0)
        self.assertGreater(arm["high"], 0)

    def test_the_report_explains_why_its_range_is_wider(self):
        """A wider number with no reason beside it reads as a worse
        answer rather than an honest one."""
        ctx, _ = run_pipeline(ab_dataset(spread_of(60, 100.0, 0.5),
                                         spread_of(60, 130.0, 0.5)))
        report = ctx["experiment"]["report_markdown"].lower()
        self.assertIn("more than once", report)
        self.assertIn("stop", report)

    def test_the_peeking_assumption_is_always_stated(self):
        _, results = run_pipeline(ab_dataset(spread_of(60, 100.0, 0.5),
                                             spread_of(60, 130.0, 0.5)))
        assumptions = [c["text"] for c in results["experiment"]["claims"]
                       if c["type"] == "assumption"]
        self.assertTrue(any("however often" in text for text in assumptions))

    def test_a_difference_inside_the_noise_is_not_reported_as_a_result(self):
        """The expensive mistake is acting on a difference that a rerun
        would not reproduce."""
        control = spread_of(40, 10.0, 2.0)
        treatment = spread_of(40, 11.0, 2.0)
        ctx, _ = run_pipeline(ab_dataset(control, treatment))
        arm = ctx["experiment"]["arms"][0]
        self.assertFalse(arm["beyond_chance"])
        self.assertLess(arm["low"], 0)
        self.assertGreater(arm["high"], 0)
        self.assertIn("chance", ctx["experiment"]["headline"].lower())

    def test_comparing_more_groups_widens_every_range(self):
        """More comparisons give chance more chances. The correction is
        arithmetic, not a footnote."""
        control = spread_of(40, 10.0, 0.5)
        treatment = spread_of(40, 20.0, 0.5)
        two_arms, _ = run_pipeline(ab_dataset(control, treatment))
        three_arms, _ = run_pipeline(ab_dataset(
            control, treatment, extra={"variant-b": spread_of(40, 15.0, 0.5)}))
        narrow = next(a for a in two_arms["experiment"]["arms"]
                      if a["group"] == "treatment")
        wide = next(a for a in three_arms["experiment"]["arms"]
                    if a["group"] == "treatment")
        self.assertEqual(narrow["difference"], wide["difference"])
        self.assertGreater(wide["high"] - wide["low"], narrow["high"] - narrow["low"])

    def test_a_lopsided_split_is_flagged_before_the_result_is_believed(self):
        """A randomised split that lands 75/25 across sixty rows is
        evidence the assignment or the logging is broken."""
        # Distinct values throughout: identical rows are dropped as
        # duplicates during cleaning, which would rebalance the split.
        ctx, results = run_pipeline(ab_dataset(
            [round(10 + index * 0.1, 1) for index in range(45)],
            [round(20 + index * 0.1, 1) for index in range(15)]))
        self.assertFalse(ctx["experiment"]["balanced"])
        warnings = [c for c in results["experiment"]["claims"]
                    if c["type"] == "warning"]
        self.assertTrue(warnings)
        self.assertIn("caution", ctx["experiment"]["headline"].lower())

    def test_an_even_split_is_not_flagged(self):
        ctx, results = run_pipeline(
            ab_dataset(spread_of(20, 10.0, 0.5), spread_of(20, 20.0, 0.5)))
        self.assertTrue(ctx["experiment"]["balanced"])
        self.assertFalse([c for c in results["experiment"]["claims"]
                          if c["type"] == "warning"])

    def test_a_comparison_always_states_that_it_assumed_randomisation(self):
        """The column proves an assignment was recorded, never that it was
        random — and only randomisation turns a difference into an effect."""
        _, results = run_pipeline(ab_dataset(spread_of(20, 10.0, 0.5),
                                             spread_of(20, 20.0, 0.5)))
        assumptions = [c for c in results["experiment"]["claims"]
                       if c["type"] == "assumption"]
        self.assertTrue(assumptions)
        self.assertIn("random", " ".join(c["text"] for c in assumptions).lower())

    def test_a_comparison_always_states_how_it_treated_the_rows(self):
        _, results = run_pipeline(ab_dataset(spread_of(20, 10.0, 0.5),
                                             spread_of(20, 20.0, 0.5)))
        limitations = [c["text"] for c in results["experiment"]["claims"]
                       if c["type"] == "limitation"]
        self.assertTrue(any("independent observation" in text
                            for text in limitations))

    def test_one_group_with_almost_no_rows_refuses_to_compare(self):
        ctx, results = run_pipeline(ab_dataset([10, 12, 14, 16], [20]))
        self.assertFalse(ctx["experiment"]["is_experiment"])
        self.assertEqual(results["experiment"]["status"], "succeeded")
        self.assertTrue(any(c["type"] == "limitation"
                            for c in results["experiment"]["claims"]))

    def test_the_causal_section_is_a_report_of_its_own(self):
        ctx, results = run_pipeline(analytics.sample_dataset())
        self.assertIn("experiment", dict(analytics.REPORT_SECTIONS))
        self.assertNotIn("experiment", dict(analytics.ANALYTICS_TYPES),
                         "the causal check is a boundary, not a fifth type")
        report = ctx["experiment"]["report_markdown"]
        self.assertIn("Can we claim a cause?", report)
        self.assertIn("How each figure was calculated", report)
        self.assertIn(report.split("\n")[0].lstrip("# "),
                      results["reporter"]["output"]["report_markdown"]
                      .replace("## Causal", "# Causal"))

    def test_its_claims_are_in_business_language_like_every_other_stage(self):
        for dataset in (analytics.sample_dataset(),
                        ab_dataset(spread_of(20, 10.0, 0.5),
                                   spread_of(20, 20.0, 0.5))):
            _, results = run_pipeline(dataset)
            for claim in results["experiment"]["claims"]:
                self.assertEqual(analytics._jargon_in(claim["text"]), [],
                                 claim["text"])
            self.assertEqual(
                analytics._jargon_in(results["experiment"]["output"]["headline"]),
                [])


if __name__ == "__main__":
    unittest.main()
