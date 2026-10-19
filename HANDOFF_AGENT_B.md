# Handoff: Agent A → Agent B

## What Agent A leaves you

A SQLite file (default `data/flats.db`, override with `FLATS_DB_PATH`) with one table, **`flats`**, one row per
listing. `agent_a.run(request)` returns:

```python
{"summary": "Saved 20 flats from Lviv ...",          # Agent A's final message (may be a question to the user)
 "search": {"status": "ok" | "partial", "note": None, "matching_on_ria": 1584, "stored_now": 20,
            "rows_in_db": 25, "db_path": "/abs/data/flats.db",
            "filters": {"city_id": 5, "rooms_max": 2, ...}}}   # or None if no search happened
```

If `search` is `None` (Agent A asked for clarification or failed), don't run Agent B; show `summary`.
`status == "partial"` means the DOM.RIA quota ran out: usable, but mention it.

**The table accumulates across searches.** Filter by what you need (`city_id`, `rooms`, `advert_type`, ...);
`search.filters` says what the last search used.

| Column | Notes |
|---|---|
| `realty_id` (PK), `url`, `fetched_at` | |
| `advert_type` | `'продажа'` (Russian) |
| `state_id`, `city_id`, `city_name`, `district_name`, `street_name` | **Russian** names: `'Львов'`, `'Франковский'`. Filter by id |
| `latitude`, `longitude` | WGS84 |
| `rooms`, `total_area`, `living_area`, `kitchen_area` (m²), `floor`, `floors_total` | living/kitchen sometimes NULL |
| `wall_type` | free text |
| `price_usd`, `price_per_m2_usd` | total asking price in USD; derived per m² |
| `published_at` | `YYYY-MM-DD HH:MM:SS` |

## Using it from Agent B (MCP)

Server `flats` (`uv run python -m flatmarket.server`, stdio). Tool for you: **`query_flats(sql, max_rows=200)`**:
one read-only SELECT on `flats`; aggregate in SQL. Wiring is the same as in `agent_a.py`:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from flatmarket.agent_a import mcp_client           # or build your own MultiServerMCPClient config
tools = await mcp_client().get_tools()              # get_locations, search_flats, query_flats
```

Give Agent B only `query_flats` (not `search_flats`: it spends the API quota). Agent A can be a node in the
parent graph: `agent_a.build_agent()` returns a compiled LangGraph graph; `agent_a.handoff(result)` extracts the dict above.

**Your 2nd MCP server** (code execution for charts) is yours to design: run LLM-generated pandas/matplotlib in a
subprocess with a timeout, give it the DB **read-only**, save figures to a folder, return file paths. Don't pass
`RIA_API_KEY`/`GOOGLE_API_KEY` to it. (`uv add pandas matplotlib`.)

## Caveats to put in the report

- **Small sample.** The free API allows 30 requests/hour and each listing costs one, so expect tens of rows
  (hundreds after several runs), the newest listings only, not "the market". `matching_on_ria` is the true count.
- Asking prices, not sale prices. Possible duplicates and outliers (typos); prefer median/IQR; show n per group.
- NULLs happen (`district_name`, `living_area`); filter explicitly.
- To get data without your own RIA key, ask the Agent A owner for `data/flats.db` (git-ignored).
