"""An agent runtime is optional, loaded by dotted path, and never in charge.

The assistant's rules turn one sentence into one action, exactly and
without a model (ADR 0019). What they cannot do is a sentence that
asks for several things — "see what you remember about Q4, then start
an analysis of last quarter on that basis" — because that needs a loop:
decide, call a tool, read the result, decide again. That loop is what
agent frameworks are for, and rather than pick one this module lets an
operator plug one in (ADR 0021):

    AGENTIC_OS_AGENT_RUNTIME   dotted path to a class or an instance
    config["agent_runtime"]    the same, or {"path": …, "options": {…}}

A runtime is anything with one method:

    run(message, tools, context) -> str

`tools` is a `server.tools.ToolBox`: `tools.describe()` lists what may
be called, with JSON schemas, and `tools.call(name, arguments)` calls
it. `context` is a dict: `language` ("en" or "ar"), `notes` (verified
sentences and settings — never a dataset row), `thread_id` (the session
id, for a runtime that keeps a thread), and `ask(system, user,
max_tokens=None)`, the model gateway, so the runtime's model is the one
the deployment configured and every key stays server-side. The return
value is the runtime's closing text — or `None`, having called nothing,
to decline, in which case the sentence is answered the ordinary way
(the rules, or the configured model) as if no runtime were there.

What the runtime never gets to decide: what a tool does (the ToolBox
does, the same for every driver), whether to delete (not offered), how
many calls one message may cause (capped), or what the transcript
shows (every call's own text, verbatim, above the closing line, which
is labelled as the runtime's). With nothing configured — the default,
and always in CI — this module changes nothing.

`examples/runtimes/` holds one runtime on LangGraph and one on Pydantic
AI; each is short enough to read in a minute.
"""

import os

from server.stages import _instantiate


def build_runtime(env=None, config=None):
    """Load the configured runtime, or return nothing.

    Returns `(runtime, name, problem)`. A problem is a sentence for an
    operator, not an exception — the same contract the router
    (ADR 0017) and the stages (ADR 0020) follow: what cannot be loaded
    leaves the application exactly as it was, and says so.
    """
    env = os.environ if env is None else env
    config = config or {}
    target = env.get("AGENTIC_OS_AGENT_RUNTIME")
    options = {}
    if not target:
        configured = config.get("agent_runtime")
        if isinstance(configured, dict):
            target = configured.get("path")
            options = configured.get("options") or {}
        elif configured:
            target = str(configured)
    if not target:
        return None, None, None
    try:
        runtime = _instantiate(target, options)
    except Exception as error:
        return None, None, (f"The agent runtime “{target}” could not be loaded "
                            f"({type(error).__name__}: {error}); the rules "
                            "answer every message.")
    if not callable(getattr(runtime, "run", None)):
        return None, None, (f"The agent runtime “{target}” has no run(message, "
                            "tools, context) method; the rules answer every "
                            "message.")
    name = type(runtime).__name__ if not isinstance(runtime, type) else runtime.__name__
    return runtime, getattr(runtime, "name", None) or name, None
