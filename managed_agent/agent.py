import os

from managed_deepagents import define_deep_agent

from middleware.tool_errors import surface_tool_errors
from tools.memory import DelegationContext, hello, recall, remember

agent = define_deep_agent(
    name="hello-agent-mda",
    model=os.environ.get("MODEL", "langsmith:openai/gpt-4o-mini"),
    tools=[hello, remember, recall],
    middleware=[surface_tool_errors],
    context_schema=DelegationContext,
)
