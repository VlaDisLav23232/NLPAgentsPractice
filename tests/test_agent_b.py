import sqlite3
from pathlib import Path

from langchain_core.messages import AIMessage

from flatmarket import agent_b, charts, db, pipeline, ria
from tests.conftest import ScriptedModel, call, info

CHART = 'df = pd.read_sql("SELECT rooms, price_usd FROM flats", DB)\n' \
        'df.plot.scatter(x="rooms", y="price_usd"); plt.savefig(OUT / "price.png"); plt.close()\n' \
        'print(len(df))'


def seed():
    conn = db.connect()
    for i, (rooms, price) in enumerate([(1, "30 000"), (2, "50 000"), (3, "90 000")], start=1):
        db.save(conn, ria.normalize(info(i, rooms_count=rooms, priceArr={"1": price})))
    conn.close()


def test_scope_sql_matches_last_search():
    s = agent_b.scope_sql({"city_id": 5, "operation": "rent_long", "rooms_max": 2, "price_max_usd": 500})
    assert s == "city_id = 5 AND advert_type LIKE '%долгосроч%' AND rooms <= 2.0 AND price_usd <= 500.0"
    seed()
    sql = "SELECT COUNT(*) FROM flats WHERE " + agent_b.scope_sql({"city_id": 5, "rooms_max": 2})
    assert sqlite3.connect(db.path()).execute(sql).fetchone()[0] == 2


def test_run_python_makes_chart_and_reads_db(tmp_path, monkeypatch):
    seed()
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "r"))
    out = charts.run_python(CHART)
    assert out["exit_code"] == 0 and out["stdout"].strip() == "3" and out["files"] == ["price.png"]
    assert charts.run_python("print(1)")["files"] == []


def test_run_python_is_read_only_and_keyless(tmp_path, monkeypatch):
    seed()
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "r"))
    monkeypatch.setenv("GOOGLE_API_KEY", "secret")
    out = charts.run_python('import os\nprint(os.environ.get("GOOGLE_API_KEY"), os.environ.get("RIA_API_KEY"))\n'
                            'DB.execute("DELETE FROM flats")')
    assert out["stdout"].startswith("None None") and "readonly" in out["stderr"]
    assert sqlite3.connect(db.path()).execute("SELECT COUNT(*) FROM flats").fetchone()[0] == 3


def test_run_python_timeout(tmp_path, monkeypatch):
    seed()
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "r"))
    monkeypatch.setattr(charts, "TIMEOUT_S", 2)
    assert "timed out" in charts.run_python("while True: pass")["error"]


async def test_agent_b_writes_report_with_charts_via_mcp(tmp_path):
    seed()
    handoff = {"summary": "Saved 3 flats.", "search": {"status": "ok", "matching_on_ria": 3,
                                                       "filters": {"city_id": 5, "operation": "sale"}}}
    model = ScriptedModel(responses=[
        call("query_flats", {"sql": "SELECT COUNT(*) FROM flats WHERE city_id = 5"}, "1"),
        call("run_python", {"code": CHART}, "2"),
        AIMessage(content="# Report\n\nMedian price: $50 000."),
    ])
    out = await agent_b.run("квартири у Львові", handoff, report_dir=tmp_path / "rep", model=model)
    assert out["charts"] == ["price.png"] and "![price.png](price.png)" in out["report"]
    assert Path(out["report_path"]).read_text(encoding="utf-8").startswith("# Report")


async def test_pipeline_runs_a_then_b(fake_ria):
    model_a = ScriptedModel(responses=[
        call("search_flats", {"city_id": 5, "max_new": 5}, "1"),
        AIMessage(content="Saved 2 flats."),
    ])
    model_b = ScriptedModel(responses=[
        call("run_python", {"code": CHART}, "1"),
        AIMessage(content="# Lviv\n\n![Prices](price.png)"),
    ])
    out = await pipeline.run("квартири у Львові", model_a, model_b, verbose=False)
    assert out["a"]["search"]["stored_now"] == 2
    assert out["charts"] == ["price.png"] and out["report"] == "# Lviv\n\n![Prices](price.png)\n"


async def test_pipeline_skips_b_when_a_asks_back():
    model_a = ScriptedModel(responses=[AIMessage(content="Яке саме місто?")])
    out = await pipeline.run("квартири", model_a, model_b=None, verbose=False)
    assert out["a"] == {"summary": "Яке саме місто?", "search": None} and "report" not in out
