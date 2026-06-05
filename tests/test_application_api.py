from __future__ import annotations

from fastapi.testclient import TestClient

from application import api
from application.main import app


class FakeQuote:
    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        self.yahoo_symbol = f"{ticker}.SA"
        self.name = "Petrobras"
        self.current_price = 54.0
        self.currency = "BRL"
        self.updated_at = "2026-06-05T12:00:00-03:00"
        self.previous_close = 53.0
        self.change_value = 1.0
        self.change_pct = 1 / 53
        self.status = "success"
        self.source = "test"


class FakeQuoteService:
    def get_quote(self, ticker: str) -> FakeQuote:
        return FakeQuote(ticker.upper())


class FakePrediction:
    def to_dict(self) -> dict:
        return {
            "ticker": "PETR4",
            "period": "1T2026",
            "predicted_class": "PH",
            "target_price_12m": 55.0,
            "probabilities": [],
        }


class FakePredictionService:
    def predict(self, ticker: str) -> FakePrediction:
        return FakePrediction()


class FakeBrokerTargets:
    def to_dict(self) -> dict:
        return {"ticker": "PETR4", "status": "success", "average_target": 52.67}


class FakeBrokerService:
    def get_targets(self, ticker: str) -> FakeBrokerTargets:
        return FakeBrokerTargets()


def test_api_quote_and_analysis_routes_use_service_layer(monkeypatch):
    monkeypatch.setattr(api, "quote_service", FakeQuoteService())
    monkeypatch.setattr(api, "prediction_service", FakePredictionService())
    monkeypatch.setattr(api, "broker_service", FakeBrokerService())
    client = TestClient(app)

    quote = client.get("/api/quote/PETR4")
    analysis = client.post("/api/analysis/PETR4")
    brokers = client.get("/api/broker-targets/PETR4")

    assert quote.status_code == 200
    assert quote.json()["current_price"] == 54.0
    assert analysis.status_code == 200
    assert analysis.json()["target_price_12m"] == 55.0
    assert brokers.status_code == 200
    assert brokers.json()["average_target"] == 52.67
