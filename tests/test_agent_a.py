import pytest
from langchain_core.messages import AIMessage

from flatmarket import agent_a
from tests.conftest import ScriptedModel, call


async def test_agent_a_collects_via_mcp_tools(fake_ria):
    model = ScriptedModel(responses=[
        call("get_locations", {}, "1"),
        call("get_locations", {"state_id": 5}, "2"),
        call("search_flats", {"city_id": 5, "state_id": 5, "rooms_max": 2, "max_new": 5}, "3"),
        AIMessage(content="Saved 2 flats from Lviv."),
    ])
    out = await agent_a.run("1-2 кімнатні у Львові", model=model)
    assert out["summary"] == "Saved 2 flats from Lviv."
    assert out["search"]["stored_now"] == 2 and out["search"]["filters"]["rooms_max"] == 2
    assert out["search"]["db_path"].endswith("flats.db")


def test_gemini_key_is_required(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        agent_a.gemini()
