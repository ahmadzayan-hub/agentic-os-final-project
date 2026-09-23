"""A runtime on LangGraph: a plan → act loop with a thread per session.

LangGraph supplies what a loop needs — a state, two nodes, an edge that
decides whether to go round again, and a checkpoint so the next message
on the same thread remembers what the tools said last time. Nothing
here decides what a tool does: the ToolBox does, and refuses what it
refuses. The model is the deployment's own gateway (`context["ask"]`),
so the keys stay where they are and the same three providers work.

Register it:

    AGENTIC_OS_AGENT_RUNTIME=examples.runtimes.langgraph_runtime.LangGraphRuntime

or in config.json: {"agent_runtime": {"path": "…LangGraphRuntime",
"options": {"max_steps": 6}}}.
"""

import json
import re
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

SYSTEM = (
    "You drive tools inside Agentic OS, a governed business-analytics "
    "workspace, on the person's behalf. Answer with ONE JSON object and "
    "nothing else. To call a tool: {\"tool\": \"<name>\", \"arguments\": "
    "{...}}. When nothing more is needed: {\"reply\": \"<one or two "
    "sentences>\"}. Tool results are shown to the person verbatim, so the "
    "reply must not repeat them and must never state a number or a finding "
    "of your own. Deleting is not offered; do not try. Write the reply in "
    "the person's language."
)
MAX_OBSERVATIONS = 12


class State(TypedDict, total=False):
    message: str
    notes: str
    tools: str
    observations: list
    steps: int
    call: dict | None
    reply: str | None
    done: bool


def _decision(raw):
    """The model's JSON, or None."""
    match = re.search(r"\{.*\}", raw if isinstance(raw, str) else "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class LangGraphRuntime:
    name = "LangGraph"

    def __init__(self, max_steps=6, max_tokens=400):
        self.max_steps = int(max_steps)
        self.max_tokens = int(max_tokens)
        # In memory: threads live as long as the process. A durable
        # checkpointer (langgraph-checkpoint-sqlite/-postgres) drops in here.
        self.saver = InMemorySaver()

    def run(self, message, tools, context):
        graph = self._graph(tools, context["ask"])
        thread = {"configurable": {"thread_id": str(context.get("thread_id") or "default")}}
        state = graph.invoke({"message": message, "notes": context.get("notes", ""),
                              "tools": json.dumps(tools.describe()), "steps": 0,
                              "call": None, "reply": None, "done": False},
                             config=thread)
        reply = state.get("reply") or ""
        if not reply and not state.get("steps"):
            return None  # nothing called, nothing said: let the ordinary path answer
        return reply

    def _graph(self, tools, ask):
        def plan(state):
            user = "\n".join([
                state.get("notes", ""), "Tools (name, description, inputSchema):",
                state["tools"], "What the tools said so far on this thread:",
                *(state.get("observations") or ["(nothing yet)"]),
                "Message: " + state["message"]])
            decision = _decision(ask(SYSTEM, user, max_tokens=self.max_tokens))
            if not decision or "tool" not in decision:
                reply = (decision or {}).get("reply")
                return {"call": None, "done": True,
                        "reply": reply if isinstance(reply, str) else ""}
            arguments = decision.get("arguments")
            return {"call": {"name": str(decision["tool"]),
                             "arguments": arguments if isinstance(arguments, dict) else {}}}

        def act(state):
            call = state["call"]
            outcome = tools.call(call["name"], call["arguments"])
            seen = list(state.get("observations") or [])[-(MAX_OBSERVATIONS - 1):]
            seen.append(f"{call['name']} → {outcome['text']}")
            steps = state.get("steps", 0) + 1
            return {"observations": seen, "steps": steps, "call": None,
                    "done": steps >= self.max_steps or not outcome["ok"]}

        def after(state):
            return END if state.get("done") else "next"

        graph = StateGraph(State)
        graph.add_node("plan", plan)
        graph.add_node("act", act)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges("plan", after, {"next": "act", END: END})
        graph.add_conditional_edges("act", after, {"next": "plan", END: END})
        return graph.compile(checkpointer=self.saver)
