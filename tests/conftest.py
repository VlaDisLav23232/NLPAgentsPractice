import pytest

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
