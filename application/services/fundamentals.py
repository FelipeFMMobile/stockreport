from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from application import settings

from .feature_engineering import (
    CURRENT_QUARTER_FEATURES,
    INDICATOR_ACCOUNT_TO_FEATURE,
    MODEL_ALL_NUMERIC_FEATURES,
    MODEL_INDICATOR_FEATURES,
    MODEL_PRICE_FEATURES,
    latest_common_quarter,
    normalize_ticker,
    parse_financial_value,
    parse_float_like,
    parse_indicator_value,
    period_to_year,
    safe_divide,
)


class QuarterPriceProvider(Protocol):
    def get_quarter_price_row(self, ticker: str, period: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class FundamentalSnapshot:
    ticker: str
    period: str
    feature_row: dict[str, Any]
    raw_values: dict[str, Any]
    missing_features: list[str]
    source_dir: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "period": self.period,
            "features": {key: _json_value(value) for key, value in self.feature_row.items()},
            "raw_values": {key: _json_value(value) for key, value in self.raw_values.items()},
            "missing_features": self.missing_features,
            "source_dir": str(self.source_dir),
        }


BALANCE_ACCOUNT_TO_FEATURE = {
    "Ativo total": "ativo_total",
    "Passivo total": "passivo_total",
    "Ativo circulante": "ativo_circulante",
}
INCOME_ACCOUNT_TO_FEATURE = {
    "Receita líquida": "receita_liquida",
    "EBIT": "ebit",
    "Lucro líquido": "lucro_liquido",
    "Lucro bruto": "lucro_bruto",
    "Resultado financeiro": "resultado_financeiro",
}


def build_fundamental_snapshot(
    ticker: str,
    price_provider: QuarterPriceProvider,
    site_raw_root: Path = settings.SITE_RAW_ROOT,
) -> FundamentalSnapshot:
    ticker = normalize_ticker(ticker)
    source_dir = site_raw_root / ticker
    if not source_dir.exists():
        raise FileNotFoundError(f"Ticker {ticker} não encontrado na base local em {site_raw_root}.")

    balances = _read_wide_csv(source_dir / "balancos.csv")
    incomes = _read_wide_csv(source_dir / "resultados.csv")
    indicators = _read_wide_csv(source_dir / "indicadores.csv")
    period = latest_common_quarter(balances, incomes)

    raw_values: dict[str, Any] = {}
    row: dict[str, Any] = {"ticker": ticker}
    row.update(_extract_financial_features(balances, BALANCE_ACCOUNT_TO_FEATURE, period, raw_values))
    row.update(_extract_financial_features(incomes, INCOME_ACCOUNT_TO_FEATURE, period, raw_values))

    price_row = price_provider.get_quarter_price_row(ticker, period)
    for feature in MODEL_PRICE_FEATURES:
        row[feature] = parse_float_like(price_row.get(feature))
    raw_values.update({feature: price_row.get(feature) for feature in MODEL_PRICE_FEATURES})
    raw_values["current_price"] = price_row.get("current_price")
    raw_values["price_currency"] = price_row.get("price_currency")
    raw_values["price_status"] = price_row.get("price_status")
    raw_values["price_error"] = price_row.get("price_error")

    indicator_values, indicator_sources = _extract_indicator_features(indicators, period)
    row.update(indicator_values)
    raw_values.update(indicator_sources)

    row["pl_calculado"] = safe_divide(row.get("price_end_close"), row.get("lpa"))
    row["margem_ebit_calculada"] = safe_divide(row.get("ebit"), row.get("receita_liquida"))
    row["margem_liquida_calculada"] = safe_divide(row.get("lucro_liquido"), row.get("receita_liquida"))
    row["margem_bruta_calculada"] = safe_divide(row.get("lucro_bruto"), row.get("receita_liquida"))
    row["resultado_financeiro_pct"] = safe_divide(row.get("resultado_financeiro"), row.get("receita_liquida"))
    row["ativo_circulante_pct"] = safe_divide(row.get("ativo_circulante"), row.get("ativo_total"))
    row["passivo_total_pct"] = safe_divide(row.get("passivo_total"), row.get("ativo_total"))

    for feature in MODEL_ALL_NUMERIC_FEATURES:
        row[feature] = parse_float_like(row.get(feature))

    missing_features = [
        feature
        for feature in ["ticker", *MODEL_ALL_NUMERIC_FEATURES]
        if row.get(feature) is None or pd.isna(row.get(feature))
    ]
    return FundamentalSnapshot(
        ticker=ticker,
        period=period,
        feature_row=row,
        raw_values=raw_values,
        missing_features=missing_features,
        source_dir=source_dir,
    )


def _read_wide_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _extract_financial_features(
    frame: pd.DataFrame,
    account_to_feature: dict[str, str],
    period: str,
    raw_values: dict[str, Any],
) -> dict[str, float | None]:
    values = {}
    for account, feature in account_to_feature.items():
        raw = _lookup_account_value(frame, account, period)
        raw_values[feature] = raw
        values[feature] = parse_financial_value(raw)
    return values


def _lookup_account_value(frame: pd.DataFrame, account: str, period: str) -> Any:
    if frame.empty or "Conta" not in frame.columns or period not in frame.columns:
        return None
    matches = frame.loc[frame["Conta"].astype(str).str.strip().eq(account)]
    if matches.empty:
        return None
    return matches.iloc[0][period]


def _extract_indicator_features(frame: pd.DataFrame, period: str) -> tuple[dict[str, float | None], dict[str, Any]]:
    year = period_to_year(period)
    previous_year = str(int(year) - 1)
    selected_accounts = {"LPA": "lpa", **INDICATOR_ACCOUNT_TO_FEATURE}
    values: dict[str, float | None] = {}
    sources: dict[str, Any] = {}

    for account, feature in selected_accounts.items():
        row = frame.loc[frame.get("Conta", pd.Series(dtype=str)).astype(str).str.strip().eq(account)]
        if row.empty:
            values[feature] = None
            sources[f"{feature}_source"] = None
            continue

        record = row.iloc[0]
        annual_same = record.get(year)
        annual_previous = record.get(previous_year)
        ttm_same = _latest_ttm_value(record, year)
        latest_prior_ttm = _latest_prior_ttm_value(record, period)
        parser = parse_financial_value if feature == "lpa" else parse_indicator_value
        candidates = [
            ("annual_same_year", annual_same),
            ("ttm_same_year", ttm_same),
            ("annual_previous_year", annual_previous),
            ("latest_prior_ttm", latest_prior_ttm),
        ]
        selected_source = None
        selected_value = None
        for source, raw_value in candidates:
            parsed = parser(raw_value)
            if parsed is not None:
                selected_source = source
                selected_value = parsed
                sources[f"{feature}_raw"] = raw_value
                break
        values[feature] = selected_value
        sources[f"{feature}_source"] = selected_source

    return values, sources


def _latest_ttm_value(record: pd.Series, year: str) -> Any:
    candidates = []
    for column, value in record.items():
        column_text = str(column).strip()
        if not column_text.endswith(f"T{year} (TTM)"):
            continue
        try:
            quarter = int(column_text[0])
        except ValueError:
            continue
        candidates.append((quarter, value))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _latest_prior_ttm_value(record: pd.Series, period: str) -> Any:
    from .feature_engineering import quarter_sort_key

    current_key = quarter_sort_key(period)
    candidates = []
    for column, value in record.items():
        column_text = str(column).strip()
        match = column_text.removesuffix(" (TTM)")
        if match == column_text:
            continue
        try:
            key = quarter_sort_key(match)
        except ValueError:
            continue
        if key <= current_key:
            candidates.append((key, value))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if hasattr(value, "item"):
        return value.item()
    return value
