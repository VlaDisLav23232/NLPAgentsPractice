"""Agent A end to end: scripted model -> real MCP server subprocess (stdio) -> fake DOM.RIA over HTTP -> SQLite."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from flatmarket import agent_a
from tests.conftest import info


class FakeRia(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        body = {
            "/dom/states": [{"stateID": 5, "name": "Львівська", "region_name": "Львів"}],
            "/dom/cities/5": [{"cityID": 5, "name": "Львів"}],
            "/dom/search": {"items": [1, 2], "count": 2},
        }.get(path) or (info(int(path.rsplit("/", 1)[1])) if path.startswith("/dom/info/") else {})
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def call(name, args, id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id, "type": "tool_call"}])


@pytest.fixture
def fake_ria(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), FakeRia)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("RIA_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    yield
    srv.shutdown()


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
