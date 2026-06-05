from __future__ import annotations

import numpy as np

from application.services.feature_engineering import MODEL_ALL_NUMERIC_FEATURES
from application.services.fundamentals import FundamentalSnapshot
from application.services.prediction import StockPredictionService


class FakeModel:
    classes_ = np.array(["NH", "N", "S", "P", "PH"])

    def __init__(self) -> None:
        self.seen_columns = None

    def predict(self, frame):
        self.seen_columns = frame.columns.tolist()
        return np.array(["PH"])

    def predict_proba(self, frame):
        return np.array([[0.05, 0.10, 0.15, 0.20, 0.50]])


class FakePriceProvider:
    pass


def test_prediction_service_sends_exact_contract_columns_and_calculates_target():
    row = {"ticker": "PETR4", **{feature: 1.0 for feature in MODEL_ALL_NUMERIC_FEATURES}}
    row["price_end_close"] = 50.0
    snapshot = FundamentalSnapshot(
        ticker="PETR4",
        period="1T2026",
        feature_row=row,
        raw_values={"current_price": 52.0, "price_currency": "BRL"},
        missing_features=[],
        source_dir=None,
    )
    service = StockPredictionService(price_provider=FakePriceProvider())
    fake_model = FakeModel()
    service._model = fake_model

    result = service.predict_snapshot(snapshot)

    assert fake_model.seen_columns == service.contract["input_columns"]
    assert result.predicted_class == "PH"
    assert result.target_price_12m == 55.0
    assert result.probabilities[-1]["probability"] == 0.50

