"""In-process copies of the ``mcp_server/server.py`` tools, used when ``MEMORY_MCP_URL`` is unset.

In the real platform the identity headers are set by agent-authz (verify mode) after
validating the delegation token. Here they are read from the run's configurable, so
they are UNVERIFIED and exist only to keep the response shape identical for testing.
"""

from __future__ import annotations

from langchain.tools import ToolRuntime, tool

TRUSTED = ("x-agent-id", "x-user-subject", "x-project", "x-bank-id")


def _identity(runtime: ToolRuntime) -> dict[str, str]:
    configurable = runtime.config.get("configurable") or {}
    return {k: str(configurable.get(k, "")) for k in TRUSTED}


@tool
def hello(name: str, runtime: ToolRuntime) -> dict:
    """Greet `name` and report the platform identity this call was authorized as."""
    return {"greeting": f"Hello, {name}!", "served_by": "hello-memory-local", "identity": _identity(runtime)}


@tool
def remember(note: str, runtime: ToolRuntime) -> dict:
    """Pretend to store `note` in the caller's memory bank (write-class operation)."""
    ident = _identity(runtime)
    return {"stored": note, "bank": ident.get("x-bank-id", ""), "identity": ident}


@tool
def recall(runtime: ToolRuntime) -> dict:
    """Pretend to read from the caller's memory bank (read-class operation)."""
    ident = _identity(runtime)
    return {"items": [], "bank": ident.get("x-bank-id", ""), "identity": ident}


LOCAL_TOOLS = [hello, remember, recall]
