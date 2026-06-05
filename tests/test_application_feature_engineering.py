from __future__ import annotations

import pytest

from application.services.feature_engineering import (
    latest_common_quarter,
    normalize_ticker,
    parse_financial_value,
    parse_indicator_value,
    target_price_from_class,
)
import pandas as pd


def test_normalize_ticker_accepts_b3_format_and_rejects_invalid_values():
    assert normalize_ticker(" petr4 ") == "PETR4"
    assert normalize_ticker("bpac11") == "BPAC11"
    with pytest.raises(ValueError):
        normalize_ticker("PETR")


def test_parse_financial_value_handles_brazilian_suffixes():
    assert parse_financial_value("1,25 T") == 1_250_000_000_000
    assert parse_financial_value("-64,08 B") == -64_080_000_000
    assert parse_financial_value("123,82 M") == 123_820_000
    assert parse_financial_value("--") is None


def test_parse_indicator_value_handles_percentages_and_mi_suffix():
    assert parse_indicator_value("20,00%") == 20.0
    assert parse_indicator_value("4,21 mi") == 4_210_000


def test_latest_common_quarter_prefers_latest_period_available_in_both_tables():
    balances = pd.DataFrame(columns=["Conta", "4T2025", "1T2026"])
    incomes = pd.DataFrame(columns=["Conta", "3T2025", "4T2025", "1T2026"])

    assert latest_common_quarter(balances, incomes) == "1T2026"


def test_target_price_from_class_uses_upper_limit_mapping():
    assert target_price_from_class(50.0, "NH") == 45.0
    assert target_price_from_class(50.0, "N") == 48.5
    assert target_price_from_class(50.0, "S") == 51.5
    assert target_price_from_class(50.0, "P") == 55.0
    assert target_price_from_class(50.0, "PH") == 55.0

