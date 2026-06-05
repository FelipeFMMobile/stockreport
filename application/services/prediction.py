from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from application import settings

from .feature_engineering import (
    CLASS_MEANINGS,
    CLASS_ORDER,
    MODEL_ALL_NUMERIC_FEATURES,
    coerce_model_input_row,
    nan_to_none,
    target_price_from_class,
)
from .fundamentals import FundamentalSnapshot, QuarterPriceProvider, build_fundamental_snapshot


@dataclass(frozen=True)
class PredictionResult:
    ticker: str
    period: str
    predicted_class: str
    predicted_class_meaning: str
    probabilities: list[dict[str, Any]]
    target_price_12m: float | None
    target_return_pct: float | None
    target_base_price: float | None
    prediction_status: str
    feature_missing_count: int
    missing_features: list[str]
    current_price: float | None
    price_currency: str | None
    model_name: str | None
    fundamentals: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "period": self.period,
            "predicted_class": self.predicted_class,
            "predicted_class_meaning": self.predicted_class_meaning,
            "probabilities": self.probabilities,
            "target_price_12m": self.target_price_12m,
            "target_return_pct": self.target_return_pct,
            "target_base_price": self.target_base_price,
            "prediction_status": self.prediction_status,
            "feature_missing_count": self.feature_missing_count,
            "missing_features": self.missing_features,
            "current_price": self.current_price,
            "price_currency": self.price_currency,
            "model_name": self.model_name,
            "fundamentals": self.fundamentals,
        }


class StockPredictionService:
    def __init__(
        self,
        price_provider: QuarterPriceProvider,
        model_path: Path = settings.MODEL_PATH,
        feature_contract_path: Path = settings.FEATURE_CONTRACT_PATH,
    ) -> None:
        self.price_provider = price_provider
        self.model_path = model_path
        self.feature_contract_path = feature_contract_path
        self._contract: dict[str, Any] | None = None
        self._model: Any | None = None
        self._metadata: dict[str, Any] | None = None

    @property
    def contract(self) -> dict[str, Any]:
        if self._contract is None:
            with self.feature_contract_path.open(encoding="utf-8") as file:
                self._contract = json.load(file)
        return self._contract

    @property
    def model(self) -> Any:
        if self._model is None:
            self._model = joblib.load(self.model_path)
        return self._model

    def predict(self, ticker: str) -> PredictionResult:
        snapshot = build_fundamental_snapshot(ticker, self.price_provider)
        return self.predict_snapshot(snapshot)

    def predict_snapshot(self, snapshot: FundamentalSnapshot) -> PredictionResult:
        input_columns = self.contract["input_columns"]
        _assert_contract(input_columns)
        missing_columns = [column for column in input_columns if column not in snapshot.feature_row]
        if missing_columns:
            raise KeyError(f"Colunas exigidas pelo feature_contract ausentes: {missing_columns}")

        model_input = coerce_model_input_row(snapshot.feature_row, input_columns)
        feature_missing_count = int(model_input.isna().sum(axis=1).iloc[0])
        predicted_class = str(self.model.predict(model_input)[0])
        if predicted_class not in CLASS_ORDER:
            raise ValueError(f"Classe prevista fora do contrato: {predicted_class}")

        price_end_close = _as_float(snapshot.feature_row.get("price_end_close"))
        target_price = target_price_from_class(price_end_close, predicted_class)
        target_return_pct = None if target_price is None or price_end_close in {None, 0} else (target_price / price_end_close) - 1

        probabilities = _predict_probabilities(self.model, model_input, CLASS_ORDER)
        raw_values = snapshot.raw_values
        return PredictionResult(
            ticker=snapshot.ticker,
            period=snapshot.period,
            predicted_class=predicted_class,
            predicted_class_meaning=CLASS_MEANINGS[predicted_class],
            probabilities=probabilities,
            target_price_12m=target_price,
            target_return_pct=target_return_pct,
            target_base_price=price_end_close,
            prediction_status="previsto com imputacao" if feature_missing_count > 0 else "previsto sem imputacao",
            feature_missing_count=feature_missing_count,
            missing_features=snapshot.missing_features,
            current_price=_as_float(raw_values.get("current_price")),
            price_currency=raw_values.get("price_currency"),
            model_name=_model_name(self.model),
            fundamentals=snapshot.to_dict(),
        )


def _assert_contract(input_columns: list[str]) -> None:
    expected = ["ticker", *MODEL_ALL_NUMERIC_FEATURES]
    if input_columns != expected:
        raise AssertionError("feature_contract.input_columns diverge das features reconstruídas pela aplicação.")


def _predict_probabilities(model: Any, model_input: pd.DataFrame, class_order: list[str]) -> list[dict[str, Any]]:
    if not hasattr(model, "predict_proba"):
        return [
            {"class_label": class_label, "meaning": CLASS_MEANINGS[class_label], "probability": None}
            for class_label in class_order
        ]

    probabilities = model.predict_proba(model_input)
    classes = getattr(model, "classes_", None)
    if classes is None and hasattr(model, "named_steps"):
        classifier = model.named_steps.get("classifier")
        classes = getattr(classifier, "classes_", None)
    if classes is None:
        classes = class_order
    class_to_probability = {
        str(class_label): float(probability)
        for class_label, probability in zip(np.asarray(classes).astype(str), probabilities[0], strict=False)
    }
    return [
        {
            "class_label": class_label,
            "meaning": CLASS_MEANINGS[class_label],
            "probability": nan_to_none(class_to_probability.get(class_label)),
        }
        for class_label in class_order
    ]


def _model_name(model: Any) -> str | None:
    if hasattr(model, "named_steps") and "classifier" in model.named_steps:
        return model.named_steps["classifier"].__class__.__name__
    return model.__class__.__name__ if model is not None else None


def _as_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)

