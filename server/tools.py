"""One catalogue of what an outside driver may do.

Two kinds of thing drive the assistant from outside its own rules: an
agent runtime (ADR 0021 — LangGraph, Pydantic AI, or four lines of your
own) and any MCP client. Both see exactly this list, and both go through
`ToolBox`, so what a tool *does* is decided here, once, and never by
the driver.

What is offered is the assistant's own action catalogue (`assistant.py`)
minus two things. `chat` is not a tool — a driver phrases its own
closing line. And the destructive actions are not offered at all: a
person deletes by asking the assistant directly and confirming in the
next message, and no loop of tool calls can do it for them.

Three guards hold whoever the driver is: the arguments are checked by
the same rule as a model's; the number of calls one message may cause
is capped; and every call's own text is recorded, so what the driver
did is on the transcript verbatim, whatever it says afterwards.
"""

from assistant import ACTIONS, DESTRUCTIVE, PREFERENCE_KEYS, SECTIONS, arguments_valid, reply

MAX_STEPS = 8
MAX_STEP_TEXT = 2000
MEMORY_CATEGORIES = ("general", "profile", "work", "projects", "preferences")
NOT_OFFERED = frozenset({"chat"} | DESTRUCTIVE)


def _schema(properties, required=()):
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


TOOLS = (
    {"name": "help",
     "description": "List what the assistant can do, in the person's language.",
     "inputSchema": _schema({})},
    {"name": "remember",
     "description": "Save one piece of information to the person's memory. "
                    "The reply names the key it was saved under.",
     "inputSchema": _schema({
         "information": {"type": "string", "description": "What to remember."},
         "category": {"type": "string", "enum": list(MEMORY_CATEGORIES)},
     }, required=("information",))},
    {"name": "recall",
     "description": "List what the assistant remembers, optionally only the "
                    "entries containing a word.",
     "inputSchema": _schema({
         "query": {"type": "string", "description": "A word to filter by."},
     })},
    {"name": "set_preference",
     "description": "Change how the assistant replies: tone (friendly, concise "
                    "or formal), language (English or Arabic), the person's "
                    "name, or whether history is recorded.",
     "inputSchema": _schema({
         "key": {"type": "string", "enum": list(PREFERENCE_KEYS)},
         "value": {"type": "string"},
     }, required=("key", "value"))},
    {"name": "start_run",
     "description": "Start a governed analytics run on a stored dataset or the "
                    "bundled sample. The pipeline is deterministic and "
                    "publishing waits for the person's approval. The reply "
                    "names the run id.",
     "inputSchema": _schema({
         "goal": {"type": "string", "description": "One sentence: what to find out."},
         "dataset": {"type": "string",
                     "description": "A stored dataset's name, or \"sample\"."},
     }, required=("goal",))},
    {"name": "run_status",
     "description": "How the latest analysis is going: its state, steps done, "
                    "and whether it waits for approval.",
     "inputSchema": _schema({})},
    {"name": "explain_report",
     "description": "Quote the latest report's verified headlines — one "
                    "section or all of them. The assistant quotes; it does "
                    "not paraphrase.",
     "inputSchema": _schema({
         "section": {"type": "string", "enum": [*SECTIONS, "all"]},
     })},
)

NAMES = tuple(tool["name"] for tool in TOOLS)


def describe():
    """The catalogue as a list of plain dicts (name, description, inputSchema)."""
    return [dict(tool) for tool in TOOLS]


class ToolBox:
    """The tools, bound to one assistant and one session.

    `call` never raises for a driver's mistake: an unknown tool, a
    deletion, bad arguments and the step limit each come back as
    `{"ok": False, "text": <a sentence in the person's language>}`, so
    a driver that loops on tool results sees what happened and can say
    so. Every call is appended to `steps`, refused or not.
    """

    def __init__(self, assistant, session, max_steps=MAX_STEPS):
        self.assistant = assistant
        self.session = session
        self.max_steps = max_steps
        self.steps = []
        self.last_result = None

    def describe(self):
        return describe()

    def call(self, name, arguments=None):
        name = str(name)
        given = arguments if isinstance(arguments, dict) else {}
        outcome = self._call(name, given)
        self.steps.append({"tool": name, "arguments": outcome.pop("arguments"),
                           "ok": outcome["ok"],
                           "text": str(outcome["text"])[:MAX_STEP_TEXT]})
        if outcome["ok"] and outcome.get("result"):
            self.last_result = outcome["result"]
        return outcome

    def _call(self, name, given):
        language = self.session.agent.language()
        if len(self.steps) >= self.max_steps:
            return {"ok": False, "arguments": {}, "result": None,
                    "text": reply(language, "tool_limit", limit=self.max_steps)}
        if name not in NAMES:
            key = "tool_not_offered" if name in DESTRUCTIVE else "tool_unknown"
            return {"ok": False, "arguments": {}, "result": None,
                    "text": reply(language, key, name=name,
                                  available=", ".join(NAMES))}
        arguments = {}
        for key in ACTIONS[name]:
            value = given.get(key)
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                return {"ok": False, "arguments": {}, "result": None,
                        "text": reply(language, "tool_bad_arguments", name=name)}
            arguments[key] = value if isinstance(value, bool) else str(value)
        if not arguments_valid(name, arguments):
            return {"ok": False, "arguments": arguments, "result": None,
                    "text": reply(language, "tool_bad_arguments", name=name)}
        # The executor takes the person's sentence as a haystack for
        # dataset names and as the fallback goal; a driver's arguments
        # are that sentence.
        text = " ".join(str(v) for v in arguments.values())
        outcome = self.assistant._execute(name, arguments, self.session, text,
                                          source="runtime")
        return {"ok": True, "arguments": arguments,
                "result": outcome.get("result"), "text": outcome["text"]}
