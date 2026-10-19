"""One SQLite table, `flats`, one row per DOM.RIA listing."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flatmarket.ria import COLUMNS

_TEXT = {"url", "advert_type", "city_name", "district_name", "street_name", "wall_type", "published_at"}
_INT = {"realty_id", "state_id", "city_id", "rooms", "floor", "floors_total"}
_DDL = ", ".join(
    f"{c} {'TEXT' if c in _TEXT else 'INTEGER' if c in _INT else 'REAL'}" + (" PRIMARY KEY" if c == "realty_id" else "")
    for c in COLUMNS
)


def path() -> Path:
    return Path(os.getenv("FLATS_DB_PATH", "data/flats.db")).expanduser().resolve()


def connect() -> sqlite3.Connection:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute(f"CREATE TABLE IF NOT EXISTS flats ({_DDL}, fetched_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    return conn


def known_ids(conn: sqlite3.Connection, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    q = ",".join("?" * len(ids))
    return {r[0] for r in conn.execute(f"SELECT realty_id FROM flats WHERE realty_id IN ({q})", ids)}


def save(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        f"INSERT OR REPLACE INTO flats ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
        [row[c] for c in COLUMNS],
    )
    conn.commit()


def connect_readonly() -> sqlite3.Connection:
    p = path()
    if not p.exists():
        raise FileNotFoundError(f"{p} does not exist yet; run Agent A first")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
    conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
    return conn
