"""A custom stage built as a LangGraph graph — audited like any other.

This is point five of ADR 0021: a framework can live *inside* a stage.
The graph has three nodes — rank the segments, flag the ones under a
floor share, write the result — and LangGraph runs them in order. No
node calls a model: a stage calculates, and every figure below has a
method a reader can recompute. What comes out is the ADR 0020 contract,
so provenance, validation and the report treat it exactly as they treat
a stage written in plain functions. The framework changes how the
stage is structured, and nothing about how it is governed.

Register it with an option:

    {"stages": [{"path": "examples.stages.graph_stage.GroupFloor",
                 "options": {"floor_share": 0.05}}]}
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict, total=False):
    ctx: dict
    floor: float
    ranked: list
    total: float
    below: list
    result: dict


class GroupFloor:
    role = "group_floor"
    title = "Group Floor Agent — which segments fall below the floor?"
    after = "sensitivity"
    question = "Which segments are below the floor?"
    can_fail_run = False

    def __init__(self, floor_share=0.05):
        self.floor = float(floor_share)
        graph = StateGraph(State)
        graph.add_node("rank", self._rank)
        graph.add_node("flag", self._flag)
        graph.add_node("write", self._write)
        graph.add_edge(START, "rank")
        graph.add_edge("rank", "flag")
        graph.add_edge("flag", "write")
        graph.add_edge("write", END)
        self.graph = graph.compile()

    def run(self, ctx):
        return self.graph.invoke({"ctx": ctx, "floor": self.floor})["result"]

    # -- nodes ----------------------------------------------------------
    @staticmethod
    def _rank(state):
        prep = state["ctx"]["preparer"]
        groups = prep.get("groups") or {}
        ranked = sorted(groups.items(), key=lambda item: item[1], reverse=True)
        return {"ranked": ranked, "total": float(prep.get("total") or 0.0)}

    @staticmethod
    def _flag(state):
        total, floor = state["total"], state["floor"]
        below = [(name, value, value / total) for name, value in state["ranked"]
                 if total > 0 and value / total < floor]
        return {"below": below}

    def _write(self, state):
        ctx, floor = state["ctx"], state["floor"]
        prep = ctx["preparer"]
        measure, group_col = prep["measure"], prep.get("group_col")
        ranked, total, below = state["ranked"], state["total"], state["below"]
        prefix = self.role
        if not 0 < floor < 1:
            return {"result": {
                "status": "failed",
                "summary": f"The floor share must be between 0 and 1; {floor} was configured.",
                "claims": [], "calculations": [], "quality_checks": [], "output": {}}}
        smallest = ranked[-1] if ranked else None
        calculations = [
            {"id": f"{prefix}.c_floor", "name": "floor_share", "value": floor,
             "method": "operator-supplied floor (a decision, not a property of the data)"},
            {"id": f"{prefix}.c_segments", "name": "segments_ranked", "value": len(ranked),
             "method": f"count of {group_col or 'segment'} groups in the prepared data"},
            {"id": f"{prefix}.c_below", "name": "segments_below_floor", "value": len(below),
             "method": f"count of groups whose {measure} / total_{measure} < floor_share"},
        ]
        if smallest:
            calculations.append({
                "id": f"{prefix}.c_smallest_share", "name": "smallest_segment_share",
                "value": round(smallest[1] / total, 4) if total else 0.0,
                "method": f"{measure} of the smallest group / total_{measure}"})
        if not ranked:
            headline = (f"The dataset has no segment column, so no segment could "
                        f"be checked against the {floor:.0%} floor.")
            claim_type = "limitation"
        elif below:
            names = ", ".join(f"{name} ({share:.1%})" for name, _, share in below)
            headline = (f"{len(below)} of {len(ranked)} {group_col} segments are "
                        f"below the {floor:.0%} floor of total {measure}: {names}.")
            claim_type = "calculation"
        else:
            headline = (f"Every one of the {len(ranked)} {group_col} segments is at "
                        f"or above the {floor:.0%} floor of total {measure}; the "
                        f"smallest holds {smallest[1] / total:.1%}.")
            claim_type = "calculation"
        claims = [{
            "id": f"{prefix}.cl_floor", "type": claim_type, "text": headline,
            "evidence": [c["id"] for c in calculations] + (["c_total"] if ranked else []),
            "status": "verified"}]
        checks = [{"name": "floor_between_0_and_1", "passed": True,
                   "detail": f"floor_share = {floor}"}]
        report = "\n".join([
            f"# {self.title.split(' — ')[0]} — {self.question}", "",
            f"**Dataset:** {ctx.get('dataset_name', 'dataset')} · "
            f"**Goal:** {ctx.get('goal', '')}", "",
            f"> **{headline}**", "",
            "This stage is a three-node graph — rank, flag, write — run by "
            "LangGraph; no node calls a model, and every figure has a method.", "",
            "## Segments by share",
            f"| {group_col or 'Segment'} | {measure} | Share | Below floor |",
            "| --- | --- | --- | --- |",
            *[f"| {name} | {value:,.2f} | {value / total:.1%} | "
              f"{'yes' if any(b[0] == name for b in below) else 'no'} |"
              for name, value in ranked if total],
            "", "## How each figure was calculated",
            "| Figure | Value | Method |", "| --- | --- | --- |",
            *[f"| {c['name']} | {c['value']} | {c['method']} |" for c in calculations],
        ])
        return {"result": {
            "status": "succeeded", "summary": headline, "claims": claims,
            "calculations": calculations, "quality_checks": checks,
            "output": {"floor_share": floor, "below": [b[0] for b in below],
                       "headline": headline, "question": self.question,
                       "report_markdown": report}}}
