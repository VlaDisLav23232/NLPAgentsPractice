# flatmarket: flat market evaluation (DOM.RIA)

```
user request ─▶ Agent A (collect) ──SQLite──▶ Agent B (analyze) ─▶ reports/<time>/report.md + charts
                 │ MCP `flats`:                 │ MCP `flats`:  query_flats
                 │  get_locations, search_flats │ MCP `charts`: run_python
                 └─ DOM.RIA API                 └─ no API keys
```

Both agents are Gemini + LangGraph `create_agent`; [pipeline.py](src/flatmarket/pipeline.py) joins them in one
`StateGraph` (`collect → analyze`). If Agent A asks a clarifying question instead of searching, Agent B is skipped.

## Setup and run

```bash
uv sync --extra dev
cp .env.example .env        # set RIA_API_KEY and GOOGLE_API_KEY
uv run pytest
uv run flatmarket "1-2 кімнатні квартири у Львові до 90000 $"         # -q hides the step trace
uv run flatmarket-agent-a "1-2 кімнатні квартири у Львові до 90000 $" # Agent A only
```

Reports are saved in `reports/<YYYYmmdd-HHMMSS>/` (override with `REPORTS_DIR`).

## Code

| File | What it does |
|---|---|
| [ria.py](src/flatmarket/ria.py) | DOM.RIA HTTP client |
| [db.py](src/flatmarket/db.py) | SQLite table `flats` |
| [server.py](src/flatmarket/server.py) | MCP server `flats` |
| [charts.py](src/flatmarket/charts.py) | MCP server `charts` |
| [agent_a.py](src/flatmarket/agent_a.py) | Agent A: collects listings |
| [agent_b.py](src/flatmarket/agent_b.py) | Agent B: stats, charts, report |
| [pipeline.py](src/flatmarket/pipeline.py) | A → B graph and `flatmarket` CLI |

## DOM.RIA quota

The free package allows 30 requests/hour and 1000/month. Each new listing costs one request, so Agent A stores
~20 per call; already stored listings are skipped. When the quota runs out, `search_flats` keeps what it saved and
returns `status: "partial"`.
