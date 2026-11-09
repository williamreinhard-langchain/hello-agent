"""`hello` / `remember` / `recall`, the same tools as ``mcp_server/server.py``.

With ``MEMORY_MCP_URL`` set, every call opens an MCP session to that server and
forwards the caller's delegation headers, taken from the run ``context``. Managed
Deep Agents owns the generated ``langgraph.json``, so inbound HTTP headers can't be
mapped into the run. Callers pass them as ``context`` instead. The agent never
parses or mints tokens.

Without ``MEMORY_MCP_URL`` the tools answer in-process. Identity then comes from the
caller that MDA verified (``runtime.server_info.principal``), not from agent-authz.
"""

from __future__ import annotations

import os
from typing import Any, TypedDict

import httpx
import jsonschema  # noqa: F401  # mcp imports it lazily (blocking disk scan) when validating tool results
from langchain.tools import tool
from managed_deepagents import ManagedToolRuntime
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class DelegationContext(TypedDict, total=False):
    delegation_authorization: str
    authorization: str
    session_id: str
    request_id: str
    traceparent: str
    tracestate: str


HEADER_FOR = {
    "delegation_authorization": "x-delegation-authorization",
    "authorization": "authorization",
    "session_id": "x-session-id",
    "request_id": "x-request-id",
    "traceparent": "traceparent",
    "tracestate": "tracestate",
}

_SSL = httpx.create_ssl_context()


def _forward_headers(runtime: ManagedToolRuntime[DelegationContext]) -> dict[str, str]:
    ctx = runtime.context or {}
    return {header: str(ctx[key]) for key, header in HEADER_FOR.items() if ctx.get(key)}


def _local_identity(runtime: ManagedToolRuntime[DelegationContext]) -> dict[str, str]:
    info = runtime.server_info
    principal = info.principal if info else None
    return {
        "x-agent-id": str(getattr(info, "graph_id", "") or ""),
        "x-user-subject": principal.id if principal else "",
        "x-project": "",
        "x-bank-id": "",
    }


async def _call_remote(url: str, name: str, args: dict[str, Any], headers: dict[str, str]) -> Any:
    async with (
        httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30, read=300), verify=_SSL) as http,
        streamable_http_client(url, http_client=http) as (read, write, *_),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(name, args)
    text = "\n".join(c.text for c in result.content if getattr(c, "text", None))
    if result.isError:
        raise RuntimeError(text or f"MCP tool {name} failed")
    return result.structuredContent or text


@tool
async def hello(name: str, runtime: ManagedToolRuntime[DelegationContext]) -> Any:
    """Greet `name` and report the platform identity this call was authorized as."""
    if url := os.environ.get("MEMORY_MCP_URL"):
        return await _call_remote(url, "hello", {"name": name}, _forward_headers(runtime))
    return {"greeting": f"Hello, {name}!", "served_by": "hello-memory-local", "identity": _local_identity(runtime)}


@tool
async def remember(note: str, runtime: ManagedToolRuntime[DelegationContext]) -> Any:
    """Pretend to store `note` in the caller's memory bank (write-class operation)."""
    if url := os.environ.get("MEMORY_MCP_URL"):
        return await _call_remote(url, "remember", {"note": note}, _forward_headers(runtime))
    ident = _local_identity(runtime)
    return {"stored": note, "bank": ident["x-bank-id"], "identity": ident}


@tool
async def recall(runtime: ManagedToolRuntime[DelegationContext]) -> Any:
    """Pretend to read from the caller's memory bank (read-class operation)."""
    if url := os.environ.get("MEMORY_MCP_URL"):
        return await _call_remote(url, "recall", {}, _forward_headers(runtime))
    ident = _local_identity(runtime)
    return {"items": [], "bank": ident["x-bank-id"], "identity": ident}
