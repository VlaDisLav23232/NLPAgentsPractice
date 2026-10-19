# flatmarket: realtor-style flat market evaluation (DOM.RIA)

```
user request ─▶ Agent A (collect) ──SQLite──▶ Agent B (analyze) ─▶ reports/<time>/report.md + charts
                 │ MCP `flats`:                 │ MCP `flats`:  query_flats (read-only SQL)
                 │  get_locations, search_flats │ MCP `charts`: run_python (pandas/matplotlib subprocess)
                 └─ DOM.RIA API                 └─ never sees API keys
```

Both agents are Gemini + LangGraph `create_agent`; [pipeline.py](src/flatmarket/pipeline.py) joins them in one
`StateGraph` (`collect → analyze`). If Agent A asks a clarifying question instead of searching, Agent B is skipped.
Interface between the two: [HANDOFF_AGENT_B.md](HANDOFF_AGENT_B.md).

## Setup and run

```bash
uv sync --extra dev
cp .env.example .env        # fill RIA_API_KEY and GOOGLE_API_KEY
uv run pytest               # offline, no keys needed
uv run flatmarket "1-2 кімнатні квартири у Львові до 90000 $"       # full flow; -q hides the step trace
uv run flatmarket-agent-a "1-2 кімнатні квартири у Львові до 90000 $" # Agent A only
```

The full flow prints every step to stderr (`[A] call search_flats {...}`, `[B] result run_python: ...`), then the
report. The report and its charts are saved in `reports/<YYYYmmdd-HHMMSS>/` (override the root with `REPORTS_DIR`).

## Code

| File | What it does |
|---|---|
| [src/flatmarket/ria.py](src/flatmarket/ria.py) | DOM.RIA HTTP client, query building, listing → row, quota detection |
| [src/flatmarket/db.py](src/flatmarket/db.py) | the single SQLite table `flats` (+ a read-only connection) |
| [src/flatmarket/server.py](src/flatmarket/server.py) | MCP server `flats` with 3 tools |
| [src/flatmarket/agent_a.py](src/flatmarket/agent_a.py) | Agent A: collects listings (tools `get_locations`, `search_flats`) + CLI |
| [src/flatmarket/charts.py](src/flatmarket/charts.py) | MCP server `charts`: `run_python` in a subprocess (60 s timeout, read-only DB, no API keys) |
| [src/flatmarket/agent_b.py](src/flatmarket/agent_b.py) | Agent B: stats + charts + Markdown report, scoped to Agent A's last search |
| [src/flatmarket/pipeline.py](src/flatmarket/pipeline.py) | LangGraph graph A → B, step trace, `flatmarket` CLI |

## DOM.RIA quota

The free package allows **30 requests/hour and 1000/month**, shared by every endpoint. Each new listing costs
one request, so Agent A stores ~20 per call. Calling it again later with the same filters adds more (stored
listings are skipped for free). When the quota runs out, the API replies 403 with "закінчились запити"; the tool
stops, keeps what it saved, and reports `status: "partial"`.
