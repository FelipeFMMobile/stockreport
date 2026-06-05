from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import requests

from stock_report.price_enrichment import (
    B3_TIMEZONE,
    YahooFinanceError,
    build_price_row,
    parse_quarter_period,
    parse_yahoo_chart,
    to_epoch,
    to_yahoo_symbol,
)

from .feature_engineering import normalize_ticker

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


@dataclass(frozen=True)
class Quote:
    ticker: str
    yahoo_symbol: str
    name: str
    current_price: float | None
    currency: str | None
    updated_at: str | None
    previous_close: float | None
    change_value: float | None
    change_pct: float | None
    status: str
    source: str = "Yahoo Finance"


class YahooQuoteService:
    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout

    def get_chart(self, yahoo_symbol: str, start: date, end: date) -> dict[str, Any]:
        params = {
            "period1": to_epoch(start),
            "period2": to_epoch(end + timedelta(days=1)),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
        response = requests.get(
            YAHOO_CHART_URL.format(symbol=yahoo_symbol),
            params=params,
            headers={"User-Agent": "stock-report-application/0.1"},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise YahooFinanceError(f"Yahoo request failed with {response.status_code}: {response.text}")
        payload = response.json()
        error = payload.get("chart", {}).get("error")
        if error:
            raise YahooFinanceError(f"Yahoo returned an error for {yahoo_symbol}: {error}")
        return payload

    def get_quote(self, ticker: str) -> Quote:
        ticker = normalize_ticker(ticker)
        yahoo_symbol = to_yahoo_symbol(ticker)
        today = datetime.now(B3_TIMEZONE).date()
        payload = self.get_chart(yahoo_symbol, today - timedelta(days=10), today)
        result = _chart_result(payload, yahoo_symbol)
        meta = result.get("meta", {})

        current_price = _as_float(meta.get("regularMarketPrice"))
        previous_close = _as_float(meta.get("chartPreviousClose") or meta.get("previousClose"))
        change_value = None
        change_pct = None
        if current_price is not None and previous_close not in {None, 0}:
            change_value = current_price - previous_close
            change_pct = change_value / previous_close

        updated_at = None
        if meta.get("regularMarketTime") is not None:
            updated_at = datetime.fromtimestamp(meta["regularMarketTime"], tz=B3_TIMEZONE).isoformat()

        return Quote(
            ticker=ticker,
            yahoo_symbol=yahoo_symbol,
            name=meta.get("longName") or meta.get("shortName") or ticker,
            current_price=current_price,
            currency=meta.get("currency"),
            updated_at=updated_at,
            previous_close=previous_close,
            change_value=change_value,
            change_pct=change_pct,
            status="success" if current_price is not None else "no_price",
        )

    def get_quarter_price_row(self, ticker: str, period: str) -> dict[str, Any]:
        ticker = normalize_ticker(ticker)
        yahoo_symbol = to_yahoo_symbol(ticker)
        quarter = parse_quarter_period(period)
        payload = self.get_chart(yahoo_symbol, quarter.start, quarter.end)
        ticker_prices = parse_yahoo_chart(ticker, yahoo_symbol, payload)
        return build_price_row(yahoo_symbol, quarter, ticker_prices)


def _chart_result(payload: dict[str, Any], yahoo_symbol: str) -> dict[str, Any]:
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise YahooFinanceError(f"Yahoo returned no chart result for {yahoo_symbol}")
    return result


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

