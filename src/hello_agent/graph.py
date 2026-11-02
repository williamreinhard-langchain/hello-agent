"""Hello-world LangGraph agent for the agent-authz delegation example, packaged for LangSmith Deployment.

Port of a FastAPI/OpenAI-compatible agent container to a LangGraph graph:

* The OpenAI ``/v1/chat/completions`` surface is replaced by the LangGraph Server API
  (threads/runs, streaming, Studio, assistants), which LangSmith Deployment hosts.
* Inbound ``X-Delegation-Authorization`` / ``Authorization`` / ``X-Session-Id`` / tracing
  headers are copied into ``config["configurable"]`` by the server (see
  ``http.configurable_headers`` in ``langgraph.json``) and forwarded on every outbound
  MCP call. The agent never parses or mints tokens.
* ``make_graph`` is a graph factory: LangGraph Server calls it per run with that run's
  config, so each run gets its own MCP client carrying the caller's delegation token.
* If ``MEMORY_MCP_URL`` is unset, the agent uses in-process copies of the MCP server's
  tools (``mcp_server/server.py``) so it runs standalone (e.g. in LangSmith Studio) without the MCP backend.
* LLM calls go through the LangSmith LLM Gateway (``MODEL=langsmith:...``) rather than
  directly to a provider, so provider keys stay in LangSmith and gateway policies apply.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain.chat_models import init_chat_model
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from hello_agent.local_tools import LOCAL_TOOLS

log = logging.getLogger("hello-agent")

AGENT_NAME = os.environ.get("AGENT_NAME", "hello-agent")
FORWARDED = (
    "x-delegation-authorization",
    "authorization",
    "x-session-id",
    "x-request-id",
    "traceparent",
    "tracestate",
)

SYSTEM_PROMPT = "You are a hello-world agent. Use the `hello` tool to greet the user by name."


def _err_text(e: BaseException) -> str:
    """Flatten ExceptionGroups (anyio TaskGroups wrap the real HTTP error) so the
    answer shows e.g. "Client error '403 Forbidden' for url ..." instead of
    "unhandled errors in a TaskGroup"."""
    subs = getattr(e, "exceptions", None)
    if subs:
        return "; ".join(_err_text(s) for s in subs)
    return f"{type(e).__name__}: {e}"


def _forward_headers(config: RunnableConfig) -> dict[str, str]:
    configurable = config.get("configurable") or {}
    return {k: str(configurable[k]) for k in FORWARDED if configurable.get(k)}


async def _mcp_tools(headers: dict[str, str]) -> list[BaseTool]:
    # One MCP connection per server: each is authorized independently by its verify.
    servers: dict[str, Any] = {
        "memory": {"transport": "streamable_http", "url": os.environ["MEMORY_MCP_URL"], "headers": headers}
    }
    if os.environ.get("SKILLS_MCP_URL"):
        servers["skills"] = {"transport": "streamable_http", "url": os.environ["SKILLS_MCP_URL"], "headers": headers}
    return await MultiServerMCPClient(servers).get_tools()


@wrap_tool_call
async def surface_tool_errors(request, handler):
    """Return MCP 401/403s from verify as tool output instead of failing the run."""
    try:
        return await handler(request)
    except Exception as e:  # noqa: BLE001
        log.warning("tool call failed: %s", e)
        return ToolMessage(
            content=f'{{"error": "mcp_call_failed", "detail": {_err_text(e)[:300]!r}}}',
            tool_call_id=request.tool_call["id"],
            name=request.tool_call["name"],
            status="error",
        )


async def make_graph(config: RunnableConfig):
    prompt = SYSTEM_PROMPT
    if os.environ.get("MEMORY_MCP_URL"):
        try:
            tools = await _mcp_tools(_forward_headers(config))
        except Exception as e:  # noqa: BLE001 — surface verify denials as data, not a 500
            log.warning("MCP tool discovery failed: %s", e)
            tools = []
            prompt += (
                "\n\nThe tool servers could not be reached or denied access. Tell the user the "
                f"request could not be completed and report this error verbatim: {_err_text(e)[:500]}"
            )
    else:
        tools = LOCAL_TOOLS

    # "langsmith:<provider>/<model>" routes through the LangSmith LLM Gateway, authenticated
    # with LANGSMITH_GATEWAY_API_KEY (falls back to LANGSMITH_API_KEY). No provider key needed.
    model = init_chat_model(os.environ.get("MODEL", "langsmith:openai/gpt-4o-mini"), temperature=0)
    return create_agent(
        model,
        tools=tools,
        system_prompt=prompt,
        middleware=[surface_tool_errors],
        name=AGENT_NAME,
    )
