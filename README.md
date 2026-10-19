# flatmarket: realtor-style flat market evaluation (DOM.RIA)

```
user request ─▶ Agent A (Gemini + LangGraph) ──SQLite──▶ Agent B (stats + charts) ─▶ report
                 │ MCP server `flats`: get_locations, search_flats, query_flats
                 └─ DOM.RIA API
```

Agent A is done. Agent B: [docs/HANDOFF_AGENT_B.md](docs/HANDOFF_AGENT_B.md).

## Setup

```bash
uv sync --extra dev
cp .env.example .env        # fill RIA_API_KEY and GOOGLE_API_KEY
uv run pytest               # offline, no keys needed
uv run flatmarket-agent-a "1-2 кімнатні квартири у Львові до 90000 $"
```

## Code (about 400 lines)

| File | What it does |
|---|---|
| [src/flatmarket/ria.py](src/flatmarket/ria.py) | DOM.RIA HTTP client, query building, listing → row, quota detection |
| [src/flatmarket/db.py](src/flatmarket/db.py) | the single SQLite table `flats` (+ a read-only connection) |
| [src/flatmarket/server.py](src/flatmarket/server.py) | MCP server `flats` with 3 tools |
| [src/flatmarket/agent_a.py](src/flatmarket/agent_a.py) | the Gemini agent (LangGraph `create_agent`) + CLI |

## DOM.RIA quota

The free package allows **30 requests/hour and 1000/month**, shared by every endpoint. Each new listing costs
one request, so Agent A stores ~20 per call. Calling it again later with the same filters adds more (stored
listings are skipped for free). When the quota runs out, the API replies 403 with "закінчились запити"; the tool
stops, keeps what it saved, and reports `status: "partial"`.
