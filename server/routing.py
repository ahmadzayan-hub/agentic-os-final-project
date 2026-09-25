"""Which model narrates this report, and who decided.

The model gateway picks a provider by a fixed priority: local Ollama if
configured, else Anthropic, else Groq, else the deterministic template.
That is a sensible default and it is also a guess — the same guess for
every report, made once at start-up, with no reason attached.

This is the same shape of problem ADR 0011 found in the choice of
measure: a silent default standing in for a decision. The fix is the
same. The choice becomes explicit, something else can make it, and the
report says which model wrote the summary **and why that one**.

The something else is a router from LLMRouter (ulab-uiuc), whose whole
subject is picking a model per query under a cost and quality budget.
The contract taken from it is deliberately one method wide:

    route_single({"query": str, ...}) -> {"model_name": str, ...}

Anything satisfying that works here — LLMRouter's KNN, MLP, graph and
heuristic routers, or four lines of your own. LLMRouter is **not** a
dependency of this project: it is optional, it is never imported at
module scope, and with nothing configured this module changes no
behaviour at all. A research library that pulls in torch, transformers
and CUDA wheels has no business being required by a CLI whose headline
promise is that it needs only the standard library.

What is sent to the router is the narration prompt — goal and verified
facts — and never the dataset. That rule (ADR 0007) does not relax
because the recipient is a local scikit-learn model rather than a
hosted API: the router runs inside the same process boundary as the
narrator it is choosing for, and it gets the same material.
"""

import os

# A router names a model; the gateway knows providers. These are the
# names a router is expected to produce, mapped to what this application
# can actually reach. Deliberately generous: routers are trained on
# public model catalogues and will say "gpt-4o" long before they say
# "the ollama one".
PROVIDER_ALIASES = {
    "ollama": "ollama",
    "local": "ollama",
    "llama": "ollama",
    "llama3": "ollama",
    "llama3.1": "ollama",
    "qwen": "ollama",
    "qwen3": "ollama",
    "mistral": "ollama",
    "phi": "ollama",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "claude-3": "anthropic",
    "claude-sonnet": "anthropic",
    "sonnet": "anthropic",
    "haiku": "anthropic",
    "opus": "anthropic",
    "groq": "groq",
    "gpt-oss": "groq",
    "mixtral": "groq",
    "gpt": "groq",
    "gpt-4": "groq",
    "gpt-4o": "groq",
    "deterministic": "deterministic",
    "template": "deterministic",
    "none": "deterministic",
}


def provider_for(model_name, available):
    """Which reachable provider a router's chosen model name refers to.

    Matching is by the longest alias the name contains, so
    "claude-sonnet-4-5" resolves through "claude-sonnet" rather than
    stopping at "claude", and a name nobody recognises returns None
    rather than a guess.
    """
    if not model_name:
        return None
    lowered = str(model_name).strip().lower()
    reachable = {entry["provider"] for entry in available}
    best = None
    for alias, provider in PROVIDER_ALIASES.items():
        if alias in lowered and provider in reachable:
            if best is None or len(alias) > len(best[0]):
                best = (alias, provider)
    return best[1] if best else None


class RoutedGateway:
    """A model gateway whose narrator is chosen per report.

    Wraps a `ModelGateway` rather than replacing it: every fallback,
    timeout and honest-degradation path in that class still applies, and
    with no router configured this object is a pass-through.
    """

    def __init__(self, gateway, router=None, name=None):
        self.gateway = gateway
        self.router = router
        self.name = name or (type(router).__name__ if router else None)

    # The run engine treats the gateway as an opaque narrator; anything
    # it asks of one, it may ask of this.
    def status(self):
        status = dict(self.gateway.status())
        status["router"] = self.name
        status["candidates"] = [
            f"{entry['provider']}:{entry['model']}" if entry["model"]
            else entry["provider"]
            for entry in self.gateway.providers()
        ]
        return status

    def ask(self, system, user, provider=None, max_tokens=None):
        """The assistant's understanding step is not routed: routing
        chooses the narrator of a report, and this is a different job.
        The gateway's own priority order applies."""
        return self.gateway.ask(system, user, provider=provider,
                                max_tokens=max_tokens)

    def narrate(self, goal, facts):
        """Narrate, having asked the router which model should do it.

        The returned dict carries the routing decision as well as the
        text, because "who wrote this summary" is already in the report
        and "why that one" belongs beside it.
        """
        available = self.gateway.providers()
        decision = self._decide(goal, facts, available)
        result = self.gateway.narrate(goal, facts,
                                      provider=decision["provider"])
        result["routing"] = decision
        return result

    def _decide(self, goal, facts, available):
        """Ask the router, and record what happened either way."""
        if self.router is None:
            return {"router": None, "provider": None,
                    "chose": None, "honoured": None,
                    "why": "No router configured: the gateway's own "
                           "priority order applies."}
        query = self.gateway._prompt(goal, facts)
        try:
            answer = self.router.route_single({"query": query})
        except Exception as error:
            # A router that fails must cost a routing decision, never a
            # report. The gateway's priority order is right here.
            return {"router": self.name, "provider": None, "chose": None,
                    "honoured": False,
                    "why": f"The router failed ({type(error).__name__}), so "
                           "the gateway's own priority order applied."}
        chose = (answer or {}).get("model_name")
        provider = provider_for(chose, available)
        if provider is None:
            return {"router": self.name, "provider": None, "chose": chose,
                    "honoured": False,
                    "why": f"The router chose “{chose}”, which this "
                           "deployment cannot reach, so the gateway's own "
                           "priority order applied."}
        return {"router": self.name, "provider": provider, "chose": chose,
                "honoured": True,
                "why": f"The router chose “{chose}”, served here by the "
                       f"{provider} provider."}


def build_router(env=None, config=None):
    """Load the configured router, or return None.

    Returns `(router, name, problem)`. A problem is a sentence for an
    operator, not an exception: a router that cannot be loaded must
    leave the application exactly as it was, and say so — the same
    contract the metric glossary follows (ADR 0011).

    Configuration is two values, because a third would be a framework:

        AGENTIC_OS_ROUTER        dotted path to a router class
        AGENTIC_OS_ROUTER_CONFIG the YAML path that class wants
    """
    env = os.environ if env is None else env
    config = config or {}
    target = env.get("AGENTIC_OS_ROUTER") or config.get("router")
    if not target:
        return None, None, None
    yaml_path = (env.get("AGENTIC_OS_ROUTER_CONFIG")
                 or config.get("router_config"))
    module_name, _, class_name = str(target).rpartition(".")
    if not module_name:
        return None, None, (f"AGENTIC_OS_ROUTER is “{target}”, which is not a "
                            "dotted path to a class (for example "
                            "llmrouter.models.smallest_llm.router.SmallestLLM).")
    try:
        import importlib

        router_class = getattr(importlib.import_module(module_name), class_name)
        router = router_class(yaml_path) if yaml_path else router_class()
    except Exception as error:
        return None, None, (f"The router “{target}” could not be loaded "
                            f"({type(error).__name__}: {error}). Narration "
                            "falls back to the gateway's priority order.")
    return router, class_name, None
