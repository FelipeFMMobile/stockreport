from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from stock_report.price_enrichment import (
    B3_TIMEZONE,
    calculate_variation,
    enrich_prices,
    first_price_on_or_after,
    last_price_on_or_before,
    parse_quarter_period,
    to_epoch,
)


class FakeYahooClient:
    def __init__(self, payloads: dict[str, dict] | None = None, errors: dict[str, Exception] | None = None) -> None:
        self.payloads = payloads or {}
        self.errors = errors or {}
        self.calls = []

    def get_chart(self, yahoo_symbol: str, start: date, end: date) -> dict:
        self.calls.append((yahoo_symbol, start, end))
        if yahoo_symbol in self.errors:
            raise self.errors[yahoo_symbol]
        return self.payloads[yahoo_symbol]


def make_chart_payload(symbol: str, rows: list[tuple[date, float, float]], current_price: float = 12.5) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "BRL",
                        "symbol": symbol,
                        "regularMarketPrice": current_price,
                        "regularMarketTime": to_epoch(date(2026, 5, 21)),
                    },
                    "timestamp": [to_epoch(row_date) for row_date, _, _ in rows],
                    "indicators": {
                        "quote": [{"close": [close for _, close, _ in rows]}],
                        "adjclose": [{"adjclose": [adj_close for _, _, adj_close in rows]}],
                    },
                }
            ],
            "error": None,
        }
    }


def test_parse_quarter_period_returns_expected_start_and_end_dates():
    assert parse_quarter_period("1T2011").start == date(2011, 1, 1)
    assert parse_quarter_period("1T2011").end == date(2011, 3, 31)
    assert parse_quarter_period("2T2011").start == date(2011, 4, 1)
    assert parse_quarter_period("2T2011").end == date(2011, 6, 30)
    assert parse_quarter_period("3T2011").start == date(2011, 7, 1)
    assert parse_quarter_period("3T2011").end == date(2011, 9, 30)
    assert parse_quarter_period("4T2011").start == date(2011, 10, 1)
    assert parse_quarter_period("4T2011").end == date(2011, 12, 31)


def test_selects_first_trading_day_on_or_after_quarter_start():
    prices = pd.DataFrame(
        [
            {"price_date": date(2024, 1, 2), "close": 10.0, "adj_close": 9.0},
            {"price_date": date(2024, 1, 3), "close": 11.0, "adj_close": 10.0},
        ]
    )

    point = first_price_on_or_after(prices, date(2024, 1, 1), date(2024, 3, 31))

    assert point is not None
    assert point.price_date == date(2024, 1, 2)
    assert point.close == 10.0
    assert point.adj_close == 9.0


def test_selects_last_trading_day_on_or_before_quarter_end():
    prices = pd.DataFrame(
        [
            {"price_date": date(2024, 3, 27), "close": 10.0, "adj_close": 9.0},
            {"price_date": date(2024, 3, 28), "close": 12.0, "adj_close": 11.0},
            {"price_date": date(2024, 4, 1), "close": 13.0, "adj_close": 12.0},
        ]
    )

    point = last_price_on_or_before(prices, date(2024, 1, 1), date(2024, 3, 31))

    assert point is not None
    assert point.price_date == date(2024, 3, 28)
    assert point.close == 12.0
    assert point.adj_close == 11.0


def test_calculate_variation_returns_value_and_percent():
    assert calculate_variation(10.0, 12.5) == (2.5, 0.25)


def test_enrich_prices_adds_nominal_and_adjusted_price_columns():
    frame = pd.DataFrame(
        [
            {"ticker": "PETR4", "period": "1T2024", "Receita líquida": "100"},
            {"ticker": "PETR4", "period": "2T2024", "Receita líquida": "110"},
        ]
    )
    client = FakeYahooClient(
        {
            "PETR4.SA": make_chart_payload(
                "PETR4.SA",
                [
                    (date(2024, 1, 2), 10.0, 8.0),
                    (date(2024, 3, 28), 12.0, 10.0),
                    (date(2024, 4, 1), 20.0, 18.0),
                    (date(2024, 6, 28), 24.0, 21.0),
                ],
            )
        }
    )

    enriched = enrich_prices(frame, client=client, sleep_seconds=0, sleep_func=lambda _: None)

    assert len(client.calls) == 1
    assert client.calls[0] == ("PETR4.SA", date(2024, 1, 1), date(2024, 6, 30))
    assert enriched["ticker_yahoo"].tolist() == ["PETR4.SA", "PETR4.SA"]
    assert enriched["price_start_date"].tolist() == ["2024-01-02", "2024-04-01"]
    assert enriched["price_end_date"].tolist() == ["2024-03-28", "2024-06-28"]
    assert enriched["quarter_variation_close"].tolist() == [2.0, 4.0]
    assert enriched["quarter_variation_close_pct"].tolist() == [0.2, 0.2]
    assert enriched["quarter_variation_adj_close"].tolist() == [2.0, 3.0]
    assert enriched["quarter_variation_adj_close_pct"].tolist() == [0.25, 1 / 6]
    assert enriched["current_price"].tolist() == [12.5, 12.5]
    assert enriched["current_price_datetime"].tolist() == [
        datetime(2026, 5, 21, tzinfo=B3_TIMEZONE).isoformat(),
        datetime(2026, 5, 21, tzinfo=B3_TIMEZONE).isoformat(),
    ]
    assert enriched["price_currency"].tolist() == ["BRL", "BRL"]
    assert enriched["price_status"].tolist() == ["success", "success"]


def test_enrich_prices_preserves_rows_and_marks_errors():
    frame = pd.DataFrame(
        [
            {"ticker": "PETR4", "period": "BAD", "Receita líquida": "100"},
            {"ticker": "VALE3", "period": "1T2024", "Receita líquida": "110"},
            {"ticker": "ABEV3", "period": "1T2024", "Receita líquida": "120"},
        ]
    )
    client = FakeYahooClient(
        payloads={
            "ABEV3.SA": make_chart_payload(
                "ABEV3.SA",
                [(date(2023, 12, 29), 10.0, 10.0), (date(2024, 4, 1), 11.0, 11.0)],
            )
        },
        errors={"VALE3.SA": RuntimeError("network down")},
    )

    enriched = enrich_prices(frame, client=client, sleep_seconds=0, sleep_func=lambda _: None)

    assert enriched["Receita líquida"].tolist() == ["100", "110", "120"]
    assert enriched["price_status"].tolist() == ["invalid_period", "error", "no_data"]
    assert enriched.loc[0, "price_error"] == "Invalid period: BAD"
    assert enriched.loc[1, "price_error"] == "network down"
    assert enriched.loc[2, "price_error"] == "No trading data found for 1T2024"
