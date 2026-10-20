"""Full flow: Agent A (collect) -> Agent B (analyze)."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TypedDict

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from flatmarket import agent_a, agent_b
from flatmarket.agent_a import _text


class State(TypedDict, total=False):
    request: str
    a: dict
    report: str
    report_path: str
    charts: list[str]


def _short(x, n=300) -> str:
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + " ..."


async def _stream(agent, request: str, tag: str, verbose: bool, **config) -> dict:
    seen, state = 0, None
    async for state in agent.astream({"messages": [("user", request)]}, config, stream_mode="values"):
        for m in state["messages"][seen:]:
            if not verbose:
                continue
            if isinstance(m, AIMessage):
                for c in m.tool_calls:
                    print(f"[{tag}] call   {c['name']} {_short(c['args'])}", file=sys.stderr)
                if not m.tool_calls:
                    print(f"[{tag}] answer ({len(_text(m.content))} chars)", file=sys.stderr)
            elif isinstance(m, ToolMessage):
                status = "ERROR " if m.status == "error" else ""
                print(f"[{tag}] result {m.name}: {status}{_short(_text(m.content))}", file=sys.stderr)
        seen = len(state["messages"])
    return state


def build_pipeline(model_a=None, model_b=None, verbose: bool = True):
    async def collect(state: State) -> State:
        agent = await agent_a.build_agent(model_a)
        return {"a": agent_a.handoff(await _stream(agent, state["request"], "A", verbose))}

    async def analyze(state: State) -> State:
        report_dir = agent_b.new_report_dir()
        agent = await agent_b.build_agent(report_dir, model_b)
        result = await _stream(agent, agent_b.task(state["request"], state["a"]), "B", verbose, recursion_limit=40)
        path = agent_b.finish(_text(result["messages"][-1].content), report_dir)
        return {"report": path.read_text(encoding="utf-8"), "report_path": str(path),
                "charts": sorted(p.name for p in report_dir.glob("*.png"))}

    def route(state: State) -> str:
        return "analyze" if state["a"]["search"] else END

    g = StateGraph(State)
    g.add_node("collect", collect)
    g.add_node("analyze", analyze)
    g.add_edge(START, "collect")
    g.add_conditional_edges("collect", route, ["analyze", END])
    g.add_edge("analyze", END)
    return g.compile()


async def run(request: str, model_a=None, model_b=None, verbose: bool = True) -> State:
    return await build_pipeline(model_a, model_b, verbose).ainvoke({"request": request})


def main() -> None:
    args = sys.argv[1:]
    verbose = "-q" not in args
    args = [a for a in args if a != "-q"]
    if not args:
        raise SystemExit('usage: flatmarket [-q] "<request in natural language>"')
    out = asyncio.run(run(" ".join(args), verbose=verbose))
    if "report" not in out:
        print(out["a"]["summary"])
        return
    print(out["report"])
    print(f"\nReport: {out['report_path']}\nCharts: {', '.join(out['charts']) or 'none'}", file=sys.stderr)


if __name__ == "__main__":
    main()
