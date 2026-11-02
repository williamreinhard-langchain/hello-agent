"""Run a LangSmith experiment against the hello agent.

    uv run python evals/run_eval.py                       # local graph
    DEPLOYMENT_URL=https://... uv run python evals/run_eval.py   # deployed graph

Creates (or reuses) the dataset ``hello-agent-smoke`` and scores each run on whether
the agent called the ``hello`` tool and greeted the user by the right name.
"""

from __future__ import annotations

import asyncio
import os

from langchain_core.runnables import RunnableConfig
from langsmith import Client, aevaluate

DATASET = "hello-agent-smoke"
EXAMPLES = [
    ("Hi, my name is Ada", "Ada"),
    ("Please say hello to Grace", "Grace"),
    ("Greet Linus!", "Linus"),
    ("hey it's Margaret here", "Margaret"),
]
CONFIG: RunnableConfig = {"configurable": {"x-delegation-authorization": "Bearer eval-token", "x-session-id": "eval"}}


def _ensure_dataset(client: Client) -> None:
    if client.has_dataset(dataset_name=DATASET):
        return
    ds = client.create_dataset(DATASET, description="Smoke tests for the hello agent")
    client.create_examples(
        dataset_id=ds.id,
        examples=[{"inputs": {"question": q}, "outputs": {"name": n}} for q, n in EXAMPLES],
    )


async def _graph():
    if url := os.environ.get("DEPLOYMENT_URL"):
        from langgraph.pregel.remote import RemoteGraph

        return RemoteGraph("hello_agent", url=url)
    from hello_agent.graph import make_graph

    return await make_graph(CONFIG)


GRAPH = None


async def target(inputs: dict) -> dict:
    result = await GRAPH.ainvoke({"messages": [{"role": "user", "content": inputs["question"]}]}, CONFIG)
    messages = result["messages"]

    def _get(m, key):
        return m.get(key) if isinstance(m, dict) else getattr(m, key, None)

    tools_called = [_get(m, "name") for m in messages if _get(m, "type") == "tool"]
    return {"answer": _get(messages[-1], "content"), "tools_called": tools_called}


def called_hello(outputs: dict) -> bool:
    return "hello" in outputs["tools_called"]


def greeted_by_name(outputs: dict, reference_outputs: dict) -> bool:
    return reference_outputs["name"].lower() in str(outputs["answer"]).lower()


async def main() -> None:
    global GRAPH
    client = Client()
    _ensure_dataset(client)
    GRAPH = await _graph()
    await aevaluate(
        target,
        data=DATASET,
        evaluators=[called_hello, greeted_by_name],
        experiment_prefix="hello-agent-deployed" if os.environ.get("DEPLOYMENT_URL") else "hello-agent-local",
        client=client,
    )


if __name__ == "__main__":
    asyncio.run(main())
