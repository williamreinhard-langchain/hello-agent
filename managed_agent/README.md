# hello-agent (Managed Deep Agents)

The same hello-world agent-authz agent as the repo root, packaged as a [Managed Deep Agent](https://docs.langchain.com/langsmith/python/managed-deep-agents-overview). LangSmith hosts the runtime, so there's no `langgraph.json` or graph factory to maintain. `mda` generates them.

```
agent.py                  # define_deep_agent(...): model, tools, middleware, context schema
instructions.md           # system prompt (synced to Context Hub on deploy)
identity.py               # callers authenticate with a LangSmith API key (x-api-key)
tools/memory.py           # hello / remember / recall: remote MCP call or in-process fallback
middleware/tool_errors.py # MCP 401/403s come back as tool output, not a failed run
```

This directory is self-contained because `mda build` only copies the project directory.

## Differences from the root agent

| Concern | Root agent (LangSmith Deployment) | Managed Deep Agent |
|---|---|---|
| Harness | `create_agent` | Deep Agents harness (`create_deep_agent`, compiled by the managed runtime) |
| Delegation headers in | `http.configurable_headers` copies inbound HTTP headers | **Run `context`**. MDA owns the generated `langgraph.json` and doesn't pass custom inbound headers through |
| Delegation headers out | Per-run `MultiServerMCPClient` with tool discovery | Each tool call opens an MCP session with the run's headers. The tool set is fixed (`hello`, `remember`, `recall`) |
| Caller auth | None (open for Studio) | `identity.py`: LangSmith API key. Studio is unaffected |
| Local identity (no MCP) | Unverified values from `configurable` | Verified caller from `runtime.server_info.principal` |
| `SKILLS_MCP_URL` | Optional second server, tools discovered | Not ported. Add tools for it to `tools/memory.py` once its tool names are known |

### Passing delegation context

| `context` key | Forwarded as header |
|---|---|
| `delegation_authorization` | `x-delegation-authorization` |
| `authorization` | `authorization` |
| `session_id` | `x-session-id` |
| `request_id` | `x-request-id` |
| `traceparent` / `tracestate` | `traceparent` / `tracestate` |

```python
from langgraph_sdk import get_client

client = get_client(url=DEPLOYMENT_URL, api_key=LANGSMITH_API_KEY)
thread = await client.threads.create()
await client.runs.wait(
    thread["thread_id"],
    "hello-agent-mda",
    input={"messages": [{"role": "user", "content": "Greet Ada"}]},
    context={"delegation_authorization": "Bearer <token>", "session_id": "s1"},
)
```

Run context is application data, so MDA doesn't verify it. The token is still validated downstream by agent-authz (verify mode), the same as in the root agent.

## Run locally

```bash
cd managed_agent
cp .env.example .env   # set LANGSMITH_API_KEY and LANGSMITH_GATEWAY_API_KEY
uv sync
uv run mda dev         # opens LangSmith Studio
```

To use the real MCP backend, start it from the repo root with `PORT=8000 uv run python mcp_server/server.py`. Then set `MEMORY_MCP_URL=http://localhost:8000/mcp` in `.env`.

## Deploy

```bash
uv run mda deploy
```

This syncs `instructions.md` to Context Hub, forwards non-reserved `.env` values as deployment secrets, and builds a hosted deployment named `hello-agent-mda`. Forwarded values include `MODEL`, `LANGSMITH_GATEWAY_API_KEY` and `MEMORY_MCP_URL`. `MEMORY_MCP_URL` has to be reachable from LangSmith Cloud.

### Deploy to a BYOC data plane (Azure)

BYOC doesn't support remote builds (HTTP 501) or Serverless, so build and push the image yourself and deploy as Dedicated:

```bash
./scripts/check_byoc.sh    # read-only: data plane APIs + gateway key, prints status codes only
env -u LANGSMITH_API_KEY -u LANGSMITH_GATEWAY_API_KEY -u LANGSMITH_GATEWAY \
  uv run mda deploy --deployment-type dedicated --push-to <dockerhub-user>/hello-agent-mda:<tag> --yes
```

| `.env` key | Value |
|---|---|
| `LANGSMITH_ENDPOINT` | The data plane's `api_url` (`GET https://azure.api.smith.langchain.com/orgs/current/data-planes?view=SUMMARY`), not `azure.api.smith.langchain.com` |
| `LANGSMITH_WORKSPACE_ID` | The workspace **linked to that data plane** (listed in the same response). Other workspaces get 403 from the data plane |
| `LANGSMITH_API_KEY` | A key with access to that workspace |
| `LANGSMITH_GATEWAY` | `<data plane api_url>/gateway`. The US gateway doesn't accept BYOC keys |
| `LANGSMITH_GATEWAY_API_KEY` | A key scoped to that workspace with a role that has `gateway:invoke` (Admin or Deployment Runtime) |

The `env -u …` prefix matters: `mda` prefers exported shell variables over `.env`. The image registry must be pullable by the data plane, so make the repo public or add registry credentials.
