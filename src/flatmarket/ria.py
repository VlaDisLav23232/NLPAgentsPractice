"""DOM.RIA client. Docs: https://docs-developers.ria.com/en/dim_ria/"""

from __future__ import annotations

import logging
import os
import re

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)

OPERATIONS = {"sale": 1, "rent_long": 3, "rent_daily": 4}
PAGE_SIZE = 100
_QUOTA_WORDS = ("закінчились запити", "ліміт", "перевищ", "limit", "quota")


class RiaError(RuntimeError):
    pass


class QuotaExceeded(RiaError):
    pass


def _get(path: str, params: dict | None = None):
    key = os.getenv("RIA_API_KEY", "").strip()
    if not key:
        raise RiaError("RIA_API_KEY is not set")
    base = os.getenv("RIA_BASE_URL", "https://developers.ria.com").rstrip("/")
    try:
        resp = httpx.get(base + path, params={**(params or {}), "api_key": key}, timeout=30)
    except httpx.HTTPError as e:
        raise RiaError(f"network error: {type(e).__name__}") from None
    if resp.status_code == 429:
        raise QuotaExceeded("HTTP 429: too many requests")
    try:
        body = resp.json()
    except ValueError:
        raise RiaError(f"HTTP {resp.status_code} from {path}: not JSON") from None
    err = body.get("error") if isinstance(body, dict) else None
    if err:
        msg = str(err.get("message") or err) if isinstance(err, dict) else str(err)
        if any(w in msg.lower() for w in _QUOTA_WORDS):
            raise QuotaExceeded(msg)
        raise RiaError(msg)
    if resp.status_code >= 400:
        raise RiaError(f"HTTP {resp.status_code} from {path}")
    return body


def states() -> list[dict]:
    return _get("/dom/states", {"lang_id": 4})


def cities(state_id: int) -> list[dict]:
    return _get(f"/dom/cities/{state_id}", {"lang_id": 4})


def build_query(
    city_id: int, state_id: int | None, operation: str, rooms_min: int | None, rooms_max: int | None,
    area_min: float | None, area_max: float | None, price_min_usd: float | None, price_max_usd: float | None,
) -> dict:
    """Flats only (category=1, realty_type=2). Characteristic ids: 209 rooms, 214 total area, 234 price, 242=239 USD."""
    q: dict = {"category": 1, "realty_type": 2, "operation_type": OPERATIONS[operation],
               "city_id": city_id, "sort": "created_at"}
    if state_id is not None:
        q["state_id"] = state_id
    for code, lo, hi in ((209, rooms_min, rooms_max), (214, area_min, area_max), (234, price_min_usd, price_max_usd)):
        if lo is not None:
            q[f"characteristic[{code}][from]"] = lo
        if hi is not None:
            q[f"characteristic[{code}][to]"] = hi
    if price_min_usd is not None or price_max_usd is not None:
        q["characteristic[242]"] = 239
    return q


def search(query: dict, page: int = 0) -> dict:
    return _get("/dom/search", {**query, "page": page})


def info(realty_id: int) -> dict:
    return _get(f"/dom/info/{realty_id}")


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v)).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


COLUMNS = [
    "realty_id", "url", "advert_type", "state_id", "city_id", "city_name", "district_name", "street_name",
    "latitude", "longitude", "rooms", "total_area", "living_area", "kitchen_area", "floor", "floors_total",
    "wall_type", "price_usd", "price_per_m2_usd", "published_at",
]


def normalize(raw: dict) -> dict:
    area = _num(raw.get("total_square_meters"))
    price = _num((raw.get("priceArr") or {}).get("1"))
    if price is None and raw.get("currency_type") == "$":
        price = _num(raw.get("price_total"))
    url = raw.get("beautiful_url")
    return {
        "realty_id": int(raw["realty_id"]),
        "url": f"https://dom.ria.com/uk/{url}" if url else None,
        "advert_type": raw.get("advert_type_name"),
        "state_id": raw.get("state_id"),
        "city_id": raw.get("city_id"),
        "city_name": raw.get("city_name"),
        "district_name": raw.get("district_name"),
        "street_name": raw.get("street_name"),
        "latitude": _num(raw.get("latitude")),
        "longitude": _num(raw.get("longitude")),
        "rooms": raw.get("rooms_count"),
        "total_area": area,
        "living_area": _num(raw.get("living_square_meters")),
        "kitchen_area": _num(raw.get("kitchen_square_meters")),
        "floor": raw.get("floor"),
        "floors_total": raw.get("floors_count"),
        "wall_type": raw.get("wall_type"),
        "price_usd": price,
        "price_per_m2_usd": round(price / area, 2) if price and area else None,
        "published_at": raw.get("publishing_date"),
    }
