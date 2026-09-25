"""A runtime on Pydantic AI: the framework's own tool loop over the ToolBox.

Each tool in the catalogue becomes a Pydantic AI tool with the same
name, description and JSON schema; the framework runs the model, the
loop and the argument validation, and every call still lands in the
ToolBox, which decides what happens. The person sees the tools' own
texts; the runtime's closing text is the one line of its making.

`model` is a Pydantic AI model name — "anthropic:claude-…", "groq:…",
"openai:…" — whose key that provider reads from its own environment
variable on the server, or a Model instance (tests pass a
FunctionModel). This runtime does not go through the project's model
gateway: Pydantic AI talks to the provider itself. That is the trade-off
against the LangGraph example, and the reason both exist.

Register it in config.json:

    {"agent_runtime": {"path": "examples.runtimes.pydantic_ai_runtime.PydanticAIRuntime",
                       "options": {"model": "anthropic:claude-sonnet-5"}}}
"""

import os

# The library prints a banner on first use; standard output is not a
# place this application writes prose (over MCP it is the protocol).
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import Agent, Tool  # noqa: E402
from pydantic_ai.exceptions import UsageLimitExceeded  # noqa: E402
from pydantic_ai.usage import UsageLimits  # noqa: E402

INSTRUCTIONS = (
    "You drive tools inside Agentic OS, a governed business-analytics "
    "workspace, on the person's behalf. Call the tools the message needs, "
    "then answer in one or two sentences in the person's language. Tool "
    "results are shown to the person verbatim: do not repeat them, and never "
    "state a number or a finding of your own. Deleting is not offered."
)


class PydanticAIRuntime:
    name = "Pydantic AI"

    def __init__(self, model, max_steps=6):
        self.model = model
        self.max_steps = int(max_steps)

    def run(self, message, tools, context):
        agent = Agent(self.model, instructions=INSTRUCTIONS,
                      tools=[self._tool(spec, tools) for spec in tools.describe()],
                      retries=1)
        prompt = f"{context.get('notes', '')}\n\nMessage: {message}"
        try:
            result = agent.run_sync(
                prompt, usage_limits=UsageLimits(request_limit=self.max_steps + 1))
        except UsageLimitExceeded:
            return ""  # the calls it made are on the transcript already
        output = result.output
        return output if isinstance(output, str) else ""

    @staticmethod
    def _tool(spec, tools):
        name = spec["name"]

        def call(**arguments):
            return tools.call(name, arguments)["text"]

        call.__name__ = name
        return Tool.from_schema(call, name=name, description=spec["description"],
                                json_schema=spec["inputSchema"])
