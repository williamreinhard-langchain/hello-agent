# hello-agent

A hello-world MCP agent with delegated authorization, packaged for **LangSmith Deployment** and tested in **LangSmith**.

- A LangChain `create_agent` agent served by LangGraph Server (Studio, threads, runs, streaming).
- MCP tools reached over streamable HTTP. The agent forwards the caller's delegation headers on every tool call and never parses or mints tokens itself.
- All model calls go through the **LangSmith LLM Gateway**. The agent holds no provider API keys.
- A LangSmith dataset and experiment that run against the local graph or the deployed one.

```
src/hello_agent/graph.py        # graph factory `make_graph` (create_agent + MCP tools + gateway model)
src/hello_agent/local_tools.py  # in-process copies of the MCP tools (used when MEMORY_MCP_URL is unset)
mcp_server/server.py            # sample "memory" MCP server (FastMCP, streamable-http on /mcp)
evals/run_eval.py               # LangSmith dataset + experiment
langgraph.json                  # deployment config
managed_agent/                  # the same agent as a Managed Deep Agent (see managed_agent/README.md)
```

## How it works

| Concern | Implementation |
|---|---|
| Serving | LangGraph Server API (threads/runs/streaming, Studio) in place of an OpenAI `/v1/chat/completions` endpoint |
| Delegation headers | `http.configurable_headers` in `langgraph.json` copies `X-Delegation-Authorization`, `Authorization`, `X-Session-Id`, `X-Request-Id` and the W3C trace headers into `config["configurable"]`. `make_graph` forwards them on every MCP call |
| Per-caller tool auth | `make_graph` is a graph factory, so each run builds its own MCP client with that run's headers |
| Tool auth failures | A 401/403 from the tool servers is returned as data, not a 500. Discovery failures are reported in the answer, and failed tool calls come back as error `ToolMessage`s through middleware |
| Model access | LangSmith LLM Gateway via `MODEL=langsmith:openai/gpt-4o-mini` |

Runs without a delegation token are allowed, so you can test in Studio. To require one, add a LangGraph custom auth handler (`"auth"` in `langgraph.json`).

## Model calls go through the LangSmith LLM Gateway

`init_chat_model("langsmith:<gateway model id>")` always calls `https://gateway.smith.langchain.com/v1`, and `OPENAI_BASE_URL` can't redirect it. It authenticates with a LangSmith API key, never a provider key. The provider key stays in LangSmith as a workspace secret, and the gateway's spend, rate-limit and data policies apply. Each LLM run in a trace includes a `ls_gateway_info` block showing the provider, model and outcome.

| Env var | Purpose |
|---|---|
| `LANGSMITH_GATEWAY_API_KEY` | **Workspace-scoped** LangSmith key with `gateway:invoke` + `workspaces:read`. If it isn't set, the agent uses `LANGSMITH_API_KEY`. **Set it explicitly in deployments**: the `LANGSMITH_API_KEY` the platform injects may not be allowed to call the gateway. |
| `MODEL` | `langsmith:` + any id from `GET https://gateway.smith.langchain.com/v1/models`, e.g. `langsmith:anthropic/claude-sonnet-4-5` or `langsmith:custom/<saved-config>` |
| `LANGSMITH_GATEWAY` | Optional. A non-US or self-hosted gateway host, e.g. `https://eu.gateway.smith.langchain.com` |

## Run locally

```bash
cp .env.example .env    # set LANGSMITH_GATEWAY_API_KEY and LANGSMITH_API_KEY
uv sync
uv run langgraph dev    # opens LangSmith Studio
```

Optional real MCP backend: run `PORT=8000 uv run python mcp_server/server.py`, then set `MEMORY_MCP_URL=http://localhost:8000/mcp`.

Pass the delegation headers like this:

```bash
curl -X POST localhost:2024/runs/wait -H 'content-type: application/json' \
  -H 'x-delegation-authorization: Bearer <token>' -H 'x-session-id: s1' \
  -d '{"assistant_id":"hello_agent","input":{"messages":[{"role":"user","content":"Greet Ada"}]}}'
```

## Deploy

**UI:** in LangSmith go to **Deployments → New Deployment**, pick this repo, and set the config path to `langgraph.json`. Add `LANGSMITH_GATEWAY_API_KEY` as a secret, plus `MEMORY_MCP_URL` and `SKILLS_MCP_URL` if you use them. No provider key is needed.

**CLI:**

```bash
uv run langgraph deploy --api-key "$LANGSMITH_API_KEY"
```

The CLI uploads the variables in `.env` as deployment secrets. It skips reserved names such as `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT`. `--api-key` (or `LANGGRAPH_HOST_API_KEY`) sets the key used to **manage** deployments, which needs `deployments:*` permissions. This can be a different key from the gateway key.

The MCP URLs have to be reachable from the deployment. An in-cluster `*.svc.cluster.local` URL only works for a self-hosted or hybrid deployment in that cluster.

## Test in LangSmith

- **Studio:** open the deployment and chat with `hello_agent`. Traces show up in the deployment's tracing project.
- **Experiments:** this creates the `hello-agent-smoke` dataset and scores `called_hello` and `greeted_by_name`:

```bash
uv run python evals/run_eval.py                                                # local graph
DEPLOYMENT_URL=https://<your-deployment>.langgraph.app uv run python evals/run_eval.py
```

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `langgraph deploy`: `GET /v2/deployments failed with status 403: Forbidden` | The key the CLI picked (`LANGSMITH_API_KEY` in `.env` comes first) has no deployment permissions | Use `--api-key` or `LANGGRAPH_HOST_API_KEY` with a key that has them |
| `OpenAIPermissionDeniedError 403` at runtime | The gateway rejected the key: it's invalid or lacks `gateway:invoke`. Usually `LANGSMITH_GATEWAY_API_KEY` is missing or misspelled, so the agent fell back to the platform's `LANGSMITH_API_KEY` | Set `LANGSMITH_GATEWAY_API_KEY` in the deployment and create a new revision |
| `401 Incorrect API key provided: lsv2_...` | The gateway received the key but couldn't use it for this workspace | Use a key from the workspace where the provider secret is configured |
| `Missing credentials ... OPENAI_API_KEY` | `MODEL` uses `openai:` instead of `langsmith:`, which bypasses the gateway | Set `MODEL=langsmith:openai/gpt-4o-mini` |
