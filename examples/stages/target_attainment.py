"""A custom stage: how far is the measure from a target the business set?

The built-in pipeline knows nothing about targets — a target is a
decision, not a property of the data, so it has to come from outside.
This stage takes it as an option and answers the one question a target
exists to answer, in the shape every built-in stage answers in.

It is a complete example of the contract (ADR 0020):

- it reads the prepared data from the context it is given and changes
  nothing there;
- every figure it reports is a calculation with a method string a reader
  can recompute by hand;
- its claim cites its own calculations *and* the built-in total
  (`c_total`), which is allowed — evidence is evidence wherever it was
  produced — and which the validator checks exists;
- its ids carry its role, so they can never collide with a built-in one;
- it contributes a report section, so the run's own report carries the
  answer and the approval gate binds to it.

Standard library only, like every stage: the reader must be able to
follow the arithmetic.
"""


class TargetAttainment:
    role = "target_attainment"
    title = "Target Attainment Agent — how far from the target?"
    after = "sensitivity"
    question = "Did we hit the target?"
    can_fail_run = False

    def __init__(self, target, label="target"):
        self.target = float(target)
        self.label = str(label)

    def run(self, ctx):
        prep = ctx["preparer"]
        measure, total = prep["measure"], prep["total"]
        if self.target <= 0:
            return {
                "status": "failed",
                "summary": f"The {self.label} must be a positive number; "
                           f"{self.target} was configured.",
                "claims": [], "calculations": [], "quality_checks": [],
                "output": {},
            }
        attainment = total / self.target
        gap = round(self.target - total, 2)
        met = gap <= 0
        prefix = self.role
        calculations = [
            {"id": f"{prefix}.c_target", "name": self.label, "value": self.target,
             "method": "operator-supplied target (a decision, not a property "
                       "of the data)"},
            {"id": f"{prefix}.c_attainment", "name": f"{self.label}_attainment",
             "value": round(attainment, 4),
             "method": f"total_{measure} / {self.label}"},
            {"id": f"{prefix}.c_gap", "name": f"gap_to_{self.label}", "value": gap,
             "method": f"{self.label} - total_{measure} (negative means exceeded)"},
        ]
        headline = (f"{measure.capitalize()} reached {attainment:.0%} of the "
                    f"{self.label} of {self.target:,.0f}"
                    + (" — the target was met." if met
                       else f" — {gap:,.2f} short."))
        claims = [{
            "id": f"{prefix}.cl_attainment", "type": "calculation",
            "text": headline,
            # Its own figures, and the built-in total it divided by.
            "evidence": [f"{prefix}.c_attainment", f"{prefix}.c_gap", "c_total"],
            "status": "verified",
        }]
        checks = [{"name": "target_is_positive", "passed": True,
                   "detail": f"{self.label} = {self.target:,.0f}"}]
        report = "\n".join([
            f"# {self.title.split(' — ')[0]} — {self.question}", "",
            f"**Dataset:** {ctx.get('dataset_name', 'dataset')} · "
            f"**Goal:** {ctx.get('goal', '')}", "",
            f"> **{headline}**", "",
            f"The {self.label} is an input to this stage, not something the "
            f"data contains: it was configured by the operator as "
            f"{self.target:,.0f}. Total {measure} over the analysed rows is "
            f"{total:,.2f}, so attainment is {attainment:.1%}.", "",
            "## How each figure was calculated",
            "| Figure | Value | Method |", "| --- | --- | --- |",
            *[f"| {c['name']} | {c['value']} | {c['method']} |" for c in calculations],
        ])
        return {
            "status": "succeeded",
            "summary": headline,
            "claims": claims,
            "calculations": calculations,
            "quality_checks": checks,
            "output": {"target": self.target, "attainment": round(attainment, 4),
                       "gap": gap, "met": met, "headline": headline,
                       "question": self.question, "report_markdown": report},
        }
