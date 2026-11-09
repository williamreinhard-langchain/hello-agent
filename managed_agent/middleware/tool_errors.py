"""Return MCP 401/403s from verify as tool output instead of failing the run."""

from __future__ import annotations

import logging

from langchain.agents.middleware import wrap_tool_call
from langchain.messages import ToolMessage

log = logging.getLogger("hello-agent-mda")


def _err_text(e: BaseException) -> str:
    """Flatten ExceptionGroups (anyio TaskGroups wrap the real HTTP error)."""
    subs = getattr(e, "exceptions", None)
    if subs:
        return "; ".join(_err_text(s) for s in subs)
    return f"{type(e).__name__}: {e}"


@wrap_tool_call
async def surface_tool_errors(request, handler):
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
