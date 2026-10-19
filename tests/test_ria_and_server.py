import httpx
import pytest
import respx

from flatmarket import db, ria, server
from tests.conftest import info

BASE = "https://developers.ria.com"
# Verbatim body DOM.RIA returned (HTTP 403) for a key whose free package was used up.
QUOTA_BODY = {"error": "У Вашому пакеті закінчились запити. Ви не можете робити запити на це API"}


def test_build_query_uses_documented_params():
    q = ria.build_query(5, 5, "sale", 1, 2, None, 80.5, None, 90000)
    assert q["operation_type"] == 1 and q["category"] == 1 and q["realty_type"] == 2 and q["city_id"] == 5
    assert q["characteristic[209][from]"] == 1 and q["characteristic[209][to]"] == 2
    assert q["characteristic[214][to]"] == 80.5 and "characteristic[214][from]" not in q
    assert q["characteristic[234][to]"] == 90000 and q["characteristic[242]"] == 239  # USD
    assert "characteristic[242]" not in ria.build_query(5, None, "sale", None, None, None, None, None, None)


def test_normalize_real_shaped_payload():
    r = ria.normalize(info(1))
    assert r["price_usd"] == 34500 and r["total_area"] == 15.7 and r["price_per_m2_usd"] == 2197.45
    assert r["latitude"] == 49.84774049 and r["url"].startswith("https://dom.ria.com/uk/realty-")


def test_normalize_missing_fields_does_not_crash():
    r = ria.normalize({"realty_id": 7})
    assert r["price_usd"] is None and r["rooms"] is None and r["price_per_m2_usd"] is None


@respx.mock
def test_quota_error_body_is_quota_not_auth():
    respx.get(f"{BASE}/dom/states").mock(return_value=httpx.Response(403, json=QUOTA_BODY))
    with pytest.raises(ria.QuotaExceeded):
        ria.states()


@respx.mock
def test_http_429_is_quota():
    respx.get(f"{BASE}/dom/states").mock(return_value=httpx.Response(429))
    with pytest.raises(ria.QuotaExceeded):
        ria.states()


@respx.mock
def test_invalid_key_is_plain_error_and_never_echoes_key():
    body = {"error": {"code": "API_KEY_INVALID", "message": "An invalid api_key was supplied."}}
    respx.get(f"{BASE}/dom/states").mock(return_value=httpx.Response(403, json=body))
    with pytest.raises(ria.RiaError) as e:
        ria.states()
    assert not isinstance(e.value, ria.QuotaExceeded) and "test-key" not in str(e.value)


def test_missing_key(monkeypatch):
    monkeypatch.delenv("RIA_API_KEY")
    with pytest.raises(ria.RiaError, match="RIA_API_KEY"):
        ria.states()


def mock_search(pages: dict[str, list[int]], count=500):
    respx.get(f"{BASE}/dom/search").mock(side_effect=lambda req: httpx.Response(
        200, json={"items": pages.get(req.url.params["page"], []), "count": count}))
    for ids in pages.values():
        for i in ids:
            respx.get(f"{BASE}/dom/info/{i}").mock(return_value=httpx.Response(200, json=info(i)))


@respx.mock
def test_search_flats_stores_then_skips_stored():
    mock_search({"0": [1, 2, 3]}, count=3)
    first = server.search_flats(city_id=5, rooms_max=2, max_new=10)
    assert first["status"] == "ok" and first["stored_now"] == 3 and first["rows_in_db"] == 3
    assert first["filters"] == {"city_id": 5, "operation": "sale", "rooms_max": 2}
    calls = len(respx.calls)
    again = server.search_flats(city_id=5, rooms_max=2, max_new=10)
    assert again["stored_now"] == 0 and again["already_stored_seen"] == 3
    assert len(respx.calls) == calls + 1  # only the search request, no /dom/info


@respx.mock
def test_search_flats_pages_past_stored_listings():
    p0, p1 = list(range(1, 101)), list(range(101, 111))
    mock_search({"0": p0, "1": p1})
    server.search_flats(city_id=5, max_new=100)  # stores all of page 0
    out = server.search_flats(city_id=5, max_new=5)
    assert out["stored_now"] == 5 and out["rows_in_db"] == 105  # went on to page 1


@respx.mock
def test_search_flats_keeps_partial_results_when_quota_runs_out():
    respx.get(f"{BASE}/dom/search").mock(return_value=httpx.Response(200, json={"items": [1, 2, 3, 4], "count": 4}))
    for i in (1, 2):
        respx.get(f"{BASE}/dom/info/{i}").mock(return_value=httpx.Response(200, json=info(i)))
    for i in (3, 4):
        respx.get(f"{BASE}/dom/info/{i}").mock(return_value=httpx.Response(403, json=QUOTA_BODY))
    out = server.search_flats(city_id=5, max_new=10)
    assert out["status"] == "partial" and out["stored_now"] == 2 and "quota" in out["note"]


@respx.mock
def test_removed_listing_is_skipped_not_fatal():
    mock_search({"0": [1, 2]}, count=2)
    respx.get(f"{BASE}/dom/info/2").mock(return_value=httpx.Response(404, json={"error": "not found"}))
    out = server.search_flats(city_id=5)
    assert out["stored_now"] == 1 and out["failed"] == 1 and out["status"] == "ok"


@respx.mock
def test_get_locations():
    respx.get(f"{BASE}/dom/states").mock(return_value=httpx.Response(200, json=[
        {"stateID": 5, "name": "Львівська", "region_name": "Львів"}]))
    respx.get(f"{BASE}/dom/cities/5").mock(return_value=httpx.Response(200, json=[{"cityID": 5, "name": "Львів"}]))
    assert server.get_locations() == [{"state_id": 5, "name": "Львівська", "center": "Львів"}]
    assert server.get_locations(5) == [{"city_id": 5, "name": "Львів"}]


@respx.mock
def test_query_flats_reads_and_is_read_only():
    mock_search({"0": [1, 2]}, count=2)
    server.search_flats(city_id=5)
    out = server.query_flats("SELECT COUNT(*) AS n, AVG(price_usd) AS p FROM flats")
    assert out["columns"] == ["n", "p"] and out["rows"] == [[2, 34500.0]]
    assert server.query_flats("SELECT realty_id FROM flats", max_rows=1)["truncated"] is True
    for bad in ("DROP TABLE flats", "DELETE FROM flats", "ATTACH DATABASE '/tmp/x.db' AS x",
                "WITH x AS (SELECT 1) INSERT INTO flats (realty_id) VALUES (9)"):
        with pytest.raises(Exception):
            server.query_flats(bad)
    assert db.connect().execute("SELECT COUNT(*) FROM flats").fetchone()[0] == 2


def test_query_flats_before_any_data():
    with pytest.raises(FileNotFoundError, match="Agent A"):
        server.query_flats("SELECT 1")
