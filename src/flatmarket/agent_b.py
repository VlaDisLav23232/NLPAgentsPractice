"""Agent B: turns the collected flats into a Markdown report with charts."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

from flatmarket import db
from flatmarket.agent_a import _text, gemini

SYSTEM = """You are Agent B in a flat-market analysis pipeline for Ukraine: a careful real-estate analyst. \
Agent A has stored flat listings from DOM.RIA in the SQLite table `flats`. You write the market report.

1. The table accumulates many searches. ALWAYS restrict every query to the SCOPE condition you are given.
2. Explore with query_flats (aggregate in SQL; don't pull hundreds of rows): n, min/max, median and IQR of \
price_usd and price_per_m2_usd, overall and by rooms; by district_name only for groups with n >= 3; NULL counts.
3. Make 2-4 charts with run_python (e.g. price distribution, price per m2 by rooms, by district, area vs price). \
Save each into OUT, give it a title and axis labels with units. If code fails, read stderr and fix it.
4. Reply with ONLY the final report in Markdown, in the user's language:
   - title and one-paragraph summary answering the user's request;
   - a table of key statistics (always with n per group);
   - each chart as ![short caption](file.png) using the exact file names run_python returned, with 1-2 sentences \
of interpretation;
   - a short "Recommendations" section (what a buyer/renter can expect for their budget, notable cheap listings \
with their url);
   - a "Caveats" section: small sample of the newest listings only (matching_on_ria is the true market size), \
asking prices not deal prices, possible outliers/duplicates, NULLs; mention a partial search if status is partial.

Use only numbers you got from the tools; never invent data. price_usd is the total price for sales and the \
monthly rent for rentals. City/district names in the table are in Russian; translate them in the report."""

ADVERT_TYPE = {"sale": "%продаж%", "rent_long": "%долгосроч%", "rent_daily": "%посуточ%"}
RANGES = {"rooms": ("rooms_min", "rooms_max"), "total_area": ("area_min", "area_max"),
          "price_usd": ("price_min_usd", "price_max_usd")}


def scope_sql(filters: dict) -> str:
    parts = [f"city_id = {int(filters['city_id'])}"]
    if pattern := ADVERT_TYPE.get(filters.get("operation", "sale")):
        parts.append(f"advert_type LIKE '{pattern}'")
    for col, (lo, hi) in RANGES.items():
        if filters.get(lo) is not None:
            parts.append(f"{col} >= {float(filters[lo])}")
        if filters.get(hi) is not None:
            parts.append(f"{col} <= {float(filters[hi])}")
    return " AND ".join(parts)


def mcp_client(report_dir: Path) -> MultiServerMCPClient:
    env = {"FLATS_DB_PATH": str(db.path()), "REPORT_DIR": str(report_dir)}
    server = lambda module: {"transport": "stdio", "command": sys.executable, "args": ["-m", module], "env": env}
    return MultiServerMCPClient({"flats": server("flatmarket.server"), "charts": server("flatmarket.charts")})


async def build_agent(report_dir: Path, model=None):
    tools = [t for t in await mcp_client(report_dir).get_tools() if t.name in ("query_flats", "run_python")]
    return create_agent(model or gemini(), tools, system_prompt=SYSTEM, name="agent_b")


def task(request: str, handoff: dict) -> str:
    search = handoff["search"]
    return (f"User request: {request}\n\nAgent A summary: {handoff['summary']}\n\n"
            f"Last search result: {json.dumps(search, ensure_ascii=False)}\n\n"
            f"SCOPE (use in every WHERE): {scope_sql(search['filters'])}")


def finish(report_md: str, report_dir: Path) -> Path:
    charts = sorted(p.name for p in report_dir.glob("*.png"))
    missing = [c for c in charts if c not in report_md]
    if missing:
        report_md += "\n\n## Charts\n\n" + "\n\n".join(f"![{c}]({c})" for c in missing)
    path = report_dir / "report.md"
    path.write_text(report_md.strip() + "\n", encoding="utf-8")
    return path


def new_report_dir() -> Path:
    root = Path(os.getenv("REPORTS_DIR", "reports")).expanduser().resolve()
    p = root / datetime.now().strftime("%Y%m%d-%H%M%S")
    p.mkdir(parents=True, exist_ok=True)
    return p


async def run(request: str, handoff: dict, report_dir: Path | None = None, model=None) -> dict:
    report_dir = report_dir or new_report_dir()
    agent = await build_agent(report_dir, model)
    result = await agent.ainvoke({"messages": [("user", task(request, handoff))]}, {"recursion_limit": 40})
    path = finish(_text(result["messages"][-1].content), report_dir)
    return {"report": path.read_text(encoding="utf-8"), "report_path": str(path),
            "charts": sorted(p.name for p in report_dir.glob("*.png"))}
