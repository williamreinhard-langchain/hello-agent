"""Hello-world MCP server used to exercise the agent-authz verify path.

It plays the role of a platform-managed *memory* MCP service. The one tool it
exposes returns a greeting plus the trusted identity headers that
agent-authz (verify mode) set on the request. That makes the authorization
decision observable end-to-end: the response proves which agent, user and
memory bank the backend was told it was serving.

The server never parses the delegation token. It trusts X-Agent-Id,
X-User-Subject, X-Project and X-Bank-Id because the Istio sidecar strips any
caller-supplied copies and ext_authz overwrites them on allow.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

mcp = FastMCP("hello-memory")

TRUSTED = ("x-agent-id", "x-user-subject", "x-project", "x-bank-id")


def _identity() -> dict[str, str]:
    headers = get_http_headers()
    return {k: headers.get(k, "") for k in TRUSTED}


@mcp.tool()
def hello(name: str) -> dict:
    """Greet `name` and report the platform identity this call was authorized as."""
    ident = _identity()
    return {
        "greeting": f"Hello, {name}!",
        "served_by": "hello-memory-mcp",
        "identity": ident,
    }


@mcp.tool()
def remember(note: str) -> dict:
    """Pretend to store `note` in the caller's memory bank (write-class operation)."""
    ident = _identity()
    return {"stored": note, "bank": ident.get("x-bank-id", ""), "identity": ident}


@mcp.tool()
def recall() -> dict:
    """Pretend to read from the caller's memory bank (read-class operation)."""
    ident = _identity()
    return {"items": [], "bank": ident.get("x-bank-id", ""), "identity": ident}


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        path="/mcp",
    )
