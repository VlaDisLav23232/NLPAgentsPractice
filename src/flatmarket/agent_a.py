"""Agent A: a Gemini-driven LangGraph agent that collects flat listings from DOM.RIA into SQLite.

    uv run flatmarket-agent-a "двокімнатні квартири у Львові до 80000 $"

Needs GOOGLE_API_KEY (Gemini) and RIA_API_KEY in .env. Other agents can reuse `build_agent` (a compiled
LangGraph graph, usable as a node) and `handoff` (pulls the structured result out of the run).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

SYSTEM = """You are Agent A in a flat-market analysis pipeline for Ukraine. Your job: collect flat \
listings from DOM.RIA into the local database for the next agent (you never see the listings themselves, \
only counts).

1. Find the city: call get_locations() to get regions, then get_locations(state_id) to get that region's \
cities (names are Ukrainian). If the place is missing or ambiguous, do NOT guess: reply asking the user.
2. Call search_flats with the user's filters (prices are in USD). Do not invent filters the user did not ask for.
3. Reply briefly in the user's language: what was stored, how many matches exist on DOM.RIA, and any note.

The DOM.RIA free quota is tiny (30 requests/hour). Keep max_new at 20 or less unless the user explicitly \
asks for more. If search_flats returns status "partial", do not retry; tell the user to try later."""


def gemini() -> ChatGoogleGenerativeAI:
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        raise RuntimeError("Set GOOGLE_API_KEY in .env (Gemini key from https://aistudio.google.com/apikey)")
    return ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"), temperature=0)


def mcp_client() -> MultiServerMCPClient:
    env_keys = ("RIA_API_KEY", "RIA_BASE_URL", "FLATS_DB_PATH")
    return MultiServerMCPClient({"flats": {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "flatmarket.server"],
        "env": {k: os.environ[k] for k in env_keys if k in os.environ},
    }})


async def build_agent(model=None):
    # query_flats is Agent B's tool; offering it here makes the model read the (empty) DB instead of collecting
    tools = [t for t in await mcp_client().get_tools() if t.name in ("get_locations", "search_flats")]
    return create_agent(model or gemini(), tools, system_prompt=SYSTEM, name="agent_a")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def handoff(result: dict) -> dict:
    """{"summary": Agent A's final message, "search": result of the last successful search_flats or None}."""
    messages = result["messages"]
    search = None
    for m in messages:
        if isinstance(m, ToolMessage) and m.name == "search_flats" and m.status != "error":
            try:
                search = json.loads(_text(m.content))
            except ValueError:
                pass
    return {"summary": _text(messages[-1].content), "search": search}


async def run(request: str, model=None) -> dict:
    agent = await build_agent(model)
    return handoff(await agent.ainvoke({"messages": [("user", request)]}))


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit('usage: flatmarket-agent-a "<request in natural language>"')
    out = asyncio.run(run(" ".join(sys.argv[1:])))
    print(out["summary"])
    print(json.dumps(out["search"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
