"""MCP server `flats`: DOM.RIA search + local SQLite access. Run: `uv run python -m flatmarket.server`

Agent A uses get_locations + search_flats. Agent B reads the data with query_flats.
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from flatmarket import db, ria

load_dotenv()
mcp = FastMCP("flats")
MAX_PAGES = 5  # looking for new (not yet stored) listings beyond the first 500 matches is not worth the quota


@mcp.tool()
def get_locations(state_id: int | None = None) -> list[dict]:
    """Without state_id: all regions (oblasts) with ids. With state_id: the cities of that region.

    Costs 1 DOM.RIA request (free quota: 30/hour), so call it only as needed.
    """
    if state_id is None:
        return [{"state_id": s["stateID"], "name": s["name"], "center": s.get("region_name")} for s in ria.states()]
    return [{"city_id": c["cityID"], "name": c["name"]} for c in ria.cities(state_id)]


@mcp.tool()
def search_flats(
    city_id: int,
    state_id: int | None = None,
    operation: Literal["sale", "rent_long", "rent_daily"] = "sale",
    rooms_min: int | None = None,
    rooms_max: int | None = None,
    area_min: float | None = None,
    area_max: float | None = None,
    price_min_usd: float | None = None,
    price_max_usd: float | None = None,
    max_new: int = 20,
) -> dict:
    """Find flats on DOM.RIA (newest first) and store their details in the local SQLite table `flats`.

    Each NEW listing costs 1 request (plus 1 per 100 search results); the free package allows only
    30/hour, so keep max_new small (default 20). Listings already stored are skipped for free, so
    calling again later with the same filters adds more. Returns counts, not the data itself.
    """
    max_new = max(1, min(max_new, 100))
    query = ria.build_query(city_id, state_id, operation, rooms_min, rooms_max, area_min, area_max,
                            price_min_usd, price_max_usd)
    conn = db.connect()
    total, fresh, already = 0, [], 0
    for page in range(MAX_PAGES):
        data = ria.search(query, page)
        ids = [int(i) for i in data.get("items", [])]
        if page == 0:
            total = int(data.get("count", len(ids)))
        have = db.known_ids(conn, ids)
        already += len(have)
        fresh += [i for i in ids if i not in have]
        if len(fresh) >= max_new or len(ids) < ria.PAGE_SIZE:
            break
    fresh = fresh[:max_new]

    stored, failed, note = 0, 0, None
    for rid in fresh:
        try:
            db.save(conn, ria.normalize(ria.info(rid)))
            stored += 1
        except ria.QuotaExceeded as e:
            note = f"Stopped early, API quota reached: {e}. Try again later (stored listings are kept)."
            break
        except ria.RiaError:
            failed += 1  # e.g. listing was removed
    return {
        "status": "partial" if note else "ok",
        "note": note,
        "matching_on_ria": total,
        "stored_now": stored,
        "already_stored_seen": already,
        "failed": failed,
        "rows_in_db": conn.execute("SELECT COUNT(*) FROM flats").fetchone()[0],
        "db_path": str(db.path()),
        "filters": {k: v for k, v in dict(city_id=city_id, state_id=state_id, operation=operation,
                                          rooms_min=rooms_min, rooms_max=rooms_max, area_min=area_min,
                                          area_max=area_max, price_min_usd=price_min_usd,
                                          price_max_usd=price_max_usd).items() if v is not None},
    }


@mcp.tool()
def query_flats(sql: str, max_rows: int = 200) -> dict:
    """Run one read-only SQL SELECT on table `flats` (SQLite). Columns: realty_id, url, advert_type,
    state_id, city_id, city_name, district_name, street_name, latitude, longitude, rooms, total_area,
    living_area, kitchen_area, floor, floors_total, wall_type, price_usd, price_per_m2_usd, published_at,
    fetched_at. Text values are Russian (e.g. 'Львов'). Prefer aggregating in SQL over pulling rows.
    """
    conn = db.connect_readonly()
    limit = max(1, min(max_rows, 5000))
    try:
        cur = conn.execute(sql)
        rows = cur.fetchmany(limit + 1)
        return {"columns": [d[0] for d in cur.description], "rows": [list(r) for r in rows[:limit]],
                "truncated": len(rows) > limit}
    except sqlite3.Error as e:
        raise ValueError(f"SQL error: {e}") from None
    finally:
        conn.close()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
