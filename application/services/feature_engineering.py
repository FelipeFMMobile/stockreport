from __future__ import annotations

import re
import unicodedata
from typing import Any

import numpy as np
import pandas as pd

TICKER_RE = re.compile(r"^[A-Z]{4}\d{1,2}[A-Z]?$")
QUARTER_RE = re.compile(r"^([1-4])T(\d{4})$")

CLASS_ORDER = ["NH", "N", "S", "P", "PH"]
CLASS_MEANINGS = {
    "NH": "queda forte (<= -10%)",
    "N": "queda moderada (-10% a -3%)",
    "S": "estabilidade (-3% a 3%)",
    "P": "alta moderada (3% a 10%)",
    "PH": "alta forte (>= 10%)",
}
CLASS_TARGET_MULTIPLIERS = {
    "NH": -0.10,
    "N": -0.03,
    "S": 0.03,
    "P": 0.10,
    "PH": 0.10,
}

CURRENT_QUARTER_FEATURES = [
    "ativo_total",
    "passivo_total",
    "ativo_circulante",
    "receita_liquida",
    "ebit",
    "lucro_liquido",
    "lucro_bruto",
    "resultado_financeiro",
]
MODEL_ENGINEERED_FEATURES = [
    "margem_ebit_calculada",
    "margem_liquida_calculada",
    "margem_bruta_calculada",
    "resultado_financeiro_pct",
    "ativo_circulante_pct",
    "passivo_total_pct",
]
MODEL_PRICE_FEATURES = [
    "price_end_close",
    "quarter_variation_close_pct",
    "quarter_variation_adj_close_pct",
]
INDICATOR_ACCOUNT_TO_FEATURE = {
    "P/VP": "p_vp_indicador",
    "ROE": "roe_indicador",
    "ROA": "roa_indicador",
    "ROIC": "roic_indicador",
    "Margem líquida": "margem_liquida_indicador",
    "Margem EBIT": "margem_ebit_indicador",
    "Margem bruta": "margem_bruta_indicador",
    "Dívida líquida": "divida_liquida_indicador",
    "Liquidez corrente": "liquidez_corrente_indicador",
}
MODEL_INDICATOR_FEATURES = list(INDICATOR_ACCOUNT_TO_FEATURE.values())
MODEL_ALL_NUMERIC_FEATURES = [
    "pl_calculado",
    *CURRENT_QUARTER_FEATURES,
    *MODEL_ENGINEERED_FEATURES,
    *MODEL_PRICE_FEATURES,
    *MODEL_INDICATOR_FEATURES,
]


def normalize_ticker(ticker: str) -> str:
    normalized = str(ticker).strip().upper()
    if not TICKER_RE.match(normalized):
        raise ValueError(f"Ticker B3 inválido: {ticker}")
    return normalized


def to_snake_case(column_name: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(column_name))
    ascii_name = "".join(char for char in normalized if not unicodedata.combining(char))
    snake_name = re.sub(r"[^0-9a-zA-Z]+", "_", ascii_name)
    return re.sub(r"_+", "_", snake_name).strip("_").lower()


def parse_numeric(value: Any) -> float | None:
    text = "" if value is None else str(value).strip()
    if text in {"", "--", "-", "nan", "None"}:
        return None
    numeric_text = re.sub(r"[^0-9,.-]", "", text)
    if "," in numeric_text:
        numeric_text = numeric_text.replace(".", "").replace(",", ".")
    try:
        return float(numeric_text)
    except ValueError:
        return None


def parse_financial_value(value: Any) -> float | None:
    text = "" if value is None else str(value).strip()
    if text in {"", "--", "-", "nan", "None"}:
        return None
    match = re.search(r"\s*([KMBT])\s*$", text, flags=re.IGNORECASE)
    suffix = match.group(1).upper() if match else None
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}.get(suffix, 1)
    if suffix:
        text = re.sub(r"\s*[KMBT]\s*$", "", text, flags=re.IGNORECASE)
    numeric = parse_numeric(text)
    return None if numeric is None else numeric * multiplier


def parse_indicator_value(value: Any) -> float | None:
    text = "" if value is None else str(value).strip()
    if text in {"", "--", "-", "nan", "None"}:
        return None
    has_mi = re.search(r"\bmi\b", text, flags=re.IGNORECASE) is not None
    match = re.search(r"\s*([KMBT])\s*$", text, flags=re.IGNORECASE)
    suffix = match.group(1).upper() if match else None
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}.get(suffix, 1)
    if has_mi:
        multiplier = 1_000_000
        text = re.sub(r"\bmi\b", "", text, flags=re.IGNORECASE)
    if suffix:
        text = re.sub(r"\s*[KMBT]\s*$", "", text, flags=re.IGNORECASE)
    text = text.replace("%", "")
    numeric = parse_numeric(text)
    return None if numeric is None else numeric * multiplier


def quarter_sort_key(period: str) -> tuple[int, int]:
    match = QUARTER_RE.match(str(period).strip().upper())
    if not match:
        raise ValueError(f"Período trimestral inválido: {period}")
    return int(match.group(2)), int(match.group(1))


def period_to_year(period: str) -> str:
    return str(quarter_sort_key(period)[0])


def list_quarter_columns(frame: pd.DataFrame) -> list[str]:
    return [str(column).strip().upper() for column in frame.columns if QUARTER_RE.match(str(column).strip().upper())]


def latest_common_quarter(*frames: pd.DataFrame) -> str:
    period_sets = [set(list_quarter_columns(frame)) for frame in frames if len(frame.columns) > 0]
    if not period_sets:
        raise ValueError("Nenhum período trimestral encontrado nas bases do ticker.")
    common = set.intersection(*period_sets) if len(period_sets) > 1 else period_sets[0]
    candidates = common or set.union(*period_sets)
    return max(candidates, key=quarter_sort_key)


def safe_divide(numerator: Any, denominator: Any) -> float | None:
    numerator_float = parse_float_like(numerator)
    denominator_float = parse_float_like(denominator)
    if numerator_float is None or denominator_float in {None, 0}:
        return None
    return numerator_float / denominator_float


def parse_float_like(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return parse_numeric(value)


def target_price_from_class(base_price: float | None, predicted_class: str | None) -> float | None:
    if base_price is None or predicted_class not in CLASS_TARGET_MULTIPLIERS:
        return None
    return round(base_price * (1 + CLASS_TARGET_MULTIPLIERS[predicted_class]), 10)


def coerce_model_input_row(row: dict[str, Any], input_columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame([{column: row.get(column) for column in input_columns}], columns=input_columns)


def nan_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if pd.isna(value):
        return None
    return value
