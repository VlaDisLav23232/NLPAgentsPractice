import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

# Shaped like a real /dom/info response (checked live against DOM.RIA).
SAMPLE = {
    "realty_id": 35055305, "rooms_count": 1, "state_id": 5, "state_name": "Львовская", "city_id": 5,
    "city_name": "Львов", "district_name": "Привокзальная", "street_name": "Шевченко Тараса улица",
    "latitude": "49.84774049", "longitude": "24.00063724", "total_square_meters": 15.7,
    "living_square_meters": 10, "kitchen_square_meters": 2, "floor": 3, "floors_count": 7,
    "wall_type": "керамический блок", "currency_type": "$", "price": 34500, "price_total": 34500,
    "priceArr": {"1": "34 500", "2": "30 640", "3": "1 561 125"}, "advert_type_name": "продажа",
    "beautiful_url": "realty-prodaja-kvartira-lvov-35055305.html", "publishing_date": "2026-10-19 17:58:33",
}


def info(realty_id: int, **over) -> dict:
    return {**SAMPLE, "realty_id": realty_id, **over}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RIA_API_KEY", "test-key")
    monkeypatch.setenv("FLATS_DB_PATH", str(tmp_path / "flats.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))


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
