from __future__ import annotations

import argparse
import calendar
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
import requests

LOGGER = logging.getLogger(__name__)

B3_TIMEZONE = ZoneInfo("America/Sao_Paulo")
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
PERIOD_RE = re.compile(r"^([1-4])T(\d{4})$")

PRICE_COLUMNS = [
    "ticker_yahoo",
    "quarter_start_date",
    "quarter_end_date",
    "price_start_date",
    "price_end_date",
    "price_start_close",
    "price_end_close",
    "price_start_adj_close",
    "price_end_adj_close",
    "quarter_variation_close",
    "quarter_variation_close_pct",
    "quarter_variation_adj_close",
    "quarter_variation_adj_close_pct",
    "current_price",
    "current_price_datetime",
    "price_currency",
    "price_status",
    "price_error",
]


class YahooFinanceError(RuntimeError):
    """Raised when Yahoo Finance chart data cannot be collected."""


@dataclass(frozen=True)
class QuarterPeriod:
    label: str
    start: date
    end: date


@dataclass(frozen=True)
class PricePoint:
    price_date: date
    close: float | None
    adj_close: float | None


@dataclass(frozen=True)
class YahooTickerPrices:
    ticker: str
    yahoo_symbol: str
    prices: pd.DataFrame
    current_price: float | None
    current_price_datetime: str | None
    currency: str | None


@dataclass(frozen=True)
class YahooFinanceClient:
    timeout: int = 30
    max_retries: int = 3
    backoff_seconds: float = 2.0
    user_agent: str = "stock-report/0.1"

    def get_chart(self, yahoo_symbol: str, start: date, end: date) -> dict[str, Any]:
        params = {
            "period1": to_epoch(start),
            # Yahoo treats period2 as exclusive. Add one day so the quarter end can be returned.
            "period2": to_epoch(end + timedelta(days=1)),
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
        headers = {"User-Agent": self.user_agent}
        url = YAHOO_CHART_URL.format(symbol=yahoo_symbol)

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    sleep_for = self.backoff_seconds * (attempt + 1)
                    LOGGER.warning("Yahoo request failed for %s: %s. Retrying in %.1fs.", yahoo_symbol, exc, sleep_for)
                    time.sleep(sleep_for)
                    continue
                raise YahooFinanceError(f"Yahoo request failed for {yahoo_symbol}: {exc}") from exc

            if response.status_code == 200:
                payload = response.json()
                error = payload.get("chart", {}).get("error")
                if error:
                    raise YahooFinanceError(f"Yahoo returned an error for {yahoo_symbol}: {error}")
                return payload

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                sleep_for = self.backoff_seconds * (attempt + 1)
                LOGGER.warning(
                    "Yahoo request failed with %s for %s. Retrying in %.1fs.",
                    response.status_code,
                    yahoo_symbol,
                    sleep_for,
                )
                time.sleep(sleep_for)
                continue

            raise YahooFinanceError(
                f"Yahoo request failed with {response.status_code} for {yahoo_symbol}: {response.text}"
            )

        raise YahooFinanceError(f"Yahoo request failed after retries for {yahoo_symbol}")


class ChartClient(Protocol):
    def get_chart(self, yahoo_symbol: str, start: date, end: date) -> dict[str, Any]: ...


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich dfDemonstrativos with B3 stock prices from Yahoo Finance.")
    parser.add_argument(
        "--input-path",
        type=Path,
        default=Path("data/notebook/dfDemonstrativos.csv"),
        help="Input CSV path. Defaults to data/notebook/dfDemonstrativos.csv.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("data/notebook/dfDemonstrativos_precos.csv"),
        help="Output CSV path. Defaults to data/notebook/dfDemonstrativos_precos.csv.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Pause between ticker requests. Defaults to 1 second.",
    )
    parser.add_argument(
        "--ticker-limit",
        type=int,
        default=None,
        help="Limit the number of unique tickers processed. Useful for smoke tests.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

    output_path = enrich_prices_file(
        input_path=args.input_path,
        output_path=args.output_path,
        sleep_seconds=args.sleep_seconds,
        ticker_limit=args.ticker_limit,
    )
    LOGGER.info("Wrote enriched dataset to %s", output_path)


def enrich_prices_file(
    input_path: Path,
    output_path: Path,
    sleep_seconds: float = 1.0,
    ticker_limit: int | None = None,
    client: ChartClient | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
) -> Path:
    frame = pd.read_csv(input_path)
    enriched = enrich_prices(
        frame,
        client=client or YahooFinanceClient(),
        sleep_seconds=sleep_seconds,
        sleep_func=sleep_func,
        ticker_limit=ticker_limit,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(output_path, index=False)
    return output_path


def enrich_prices(
    frame: pd.DataFrame,
    client: ChartClient,
    sleep_seconds: float = 1.0,
    sleep_func: Callable[[float], None] = time.sleep,
    ticker_limit: int | None = None,
) -> pd.DataFrame:
    require_columns(frame, {"ticker", "period"})
    working = frame.copy()
    working["ticker"] = working["ticker"].astype(str).str.strip().str.upper()

    if ticker_limit is not None:
        allowed_tickers = list(dict.fromkeys(working["ticker"].tolist()))[:ticker_limit]
        working = working[working["ticker"].isin(allowed_tickers)].copy()
    if working.empty:
        return pd.concat([working, pd.DataFrame(columns=PRICE_COLUMNS)], axis=1)

    parsed_periods = {period: try_parse_quarter_period(period) for period in working["period"].astype(str).unique()}
    results: dict[int, dict[str, Any]] = {}
    stats = {"success": 0, "invalid_period": 0, "no_data": 0, "error": 0}

    for ticker_index, (ticker, ticker_frame) in enumerate(working.groupby("ticker", sort=False)):
        if ticker_index > 0:
            sleep_func(sleep_seconds)

        yahoo_symbol = to_yahoo_symbol(ticker)
        valid_periods = [parsed_periods[str(period)] for period in ticker_frame["period"].astype(str).unique()]
        valid_periods = [period for period in valid_periods if period is not None]

        ticker_prices: YahooTickerPrices | None = None
        ticker_error: str | None = None
        if valid_periods:
            start = min(period.start for period in valid_periods)
            end = max(period.end for period in valid_periods)
            LOGGER.info("Collecting prices for ticker=%s (%s)", ticker, yahoo_symbol)
            try:
                ticker_prices = parse_yahoo_chart(ticker, yahoo_symbol, client.get_chart(yahoo_symbol, start, end))
            except Exception as exc:
                ticker_error = str(exc)
                LOGGER.warning("Failed to collect prices for %s: %s", ticker, exc)

        for row_index, row in ticker_frame.iterrows():
            period = parsed_periods.get(str(row["period"]))
            if period is None:
                results[row_index] = empty_price_row(
                    yahoo_symbol,
                    status="invalid_period",
                    error=f"Invalid period: {row['period']}",
                )
                stats["invalid_period"] += 1
                continue

            if ticker_error is not None or ticker_prices is None:
                results[row_index] = empty_price_row(
                    yahoo_symbol,
                    quarter_period=period,
                    status="error",
                    error=ticker_error or "No valid periods for ticker",
                )
                stats["error"] += 1
                continue

            enriched_row = build_price_row(yahoo_symbol, period, ticker_prices)
            results[row_index] = enriched_row
            stats[enriched_row["price_status"]] = stats.get(enriched_row["price_status"], 0) + 1

    price_frame = pd.DataFrame.from_dict(results, orient="index").reindex(working.index)
    enriched = pd.concat([working, price_frame[PRICE_COLUMNS]], axis=1)
    LOGGER.info(
        "Price enrichment finished: rows=%s tickers=%s success=%s invalid_period=%s no_data=%s error=%s",
        len(enriched),
        enriched["ticker"].nunique() if not enriched.empty else 0,
        stats.get("success", 0),
        stats.get("invalid_period", 0),
        stats.get("no_data", 0),
        stats.get("error", 0),
    )
    return enriched


def require_columns(frame: pd.DataFrame, columns: set[str]) -> None:
    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"Input dataset is missing required columns: {', '.join(sorted(missing))}")


def parse_quarter_period(value: str) -> QuarterPeriod:
    match = PERIOD_RE.match(str(value).strip().upper())
    if not match:
        raise ValueError(f"Invalid period: {value}")

    quarter = int(match.group(1))
    year = int(match.group(2))
    start_month = ((quarter - 1) * 3) + 1
    end_month = start_month + 2
    return QuarterPeriod(
        label=f"{quarter}T{year}",
        start=date(year, start_month, 1),
        end=date(year, end_month, calendar.monthrange(year, end_month)[1]),
    )


def try_parse_quarter_period(value: str) -> QuarterPeriod | None:
    try:
        return parse_quarter_period(value)
    except ValueError:
        return None


def to_yahoo_symbol(ticker: str) -> str:
    return f"{str(ticker).strip().upper()}.SA"


def to_epoch(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=B3_TIMEZONE).timestamp())


def parse_yahoo_chart(ticker: str, yahoo_symbol: str, payload: dict[str, Any]) -> YahooTickerPrices:
    chart = payload.get("chart", {})
    result = (chart.get("result") or [None])[0]
    if not result:
        raise YahooFinanceError(f"Yahoo returned no chart result for {yahoo_symbol}")

    meta = result.get("meta", {})
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adjclose = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    closes = quote.get("close") or []

    records = []
    for index, timestamp in enumerate(timestamps):
        close = closes[index] if index < len(closes) else None
        adj_close = adjclose[index] if index < len(adjclose) else None
        if close is None and adj_close is None:
            continue
        price_datetime = datetime.fromtimestamp(timestamp, tz=B3_TIMEZONE)
        records.append(
            {
                "price_date": price_datetime.date(),
                "close": close,
                "adj_close": adj_close,
            }
        )

    prices = pd.DataFrame(records, columns=["price_date", "close", "adj_close"])
    if not prices.empty:
        prices = prices.sort_values("price_date").reset_index(drop=True)

    regular_market_time = meta.get("regularMarketTime")
    current_price_datetime = None
    if regular_market_time is not None:
        current_price_datetime = datetime.fromtimestamp(regular_market_time, tz=B3_TIMEZONE).isoformat()

    return YahooTickerPrices(
        ticker=ticker,
        yahoo_symbol=yahoo_symbol,
        prices=prices,
        current_price=meta.get("regularMarketPrice"),
        current_price_datetime=current_price_datetime,
        currency=meta.get("currency"),
    )


def build_price_row(yahoo_symbol: str, quarter_period: QuarterPeriod, ticker_prices: YahooTickerPrices) -> dict[str, Any]:
    start_point = first_price_on_or_after(ticker_prices.prices, quarter_period.start, quarter_period.end)
    end_point = last_price_on_or_before(ticker_prices.prices, quarter_period.start, quarter_period.end)
    base_row = empty_price_row(yahoo_symbol, quarter_period=quarter_period, status="success")
    base_row.update(
        {
            "current_price": ticker_prices.current_price,
            "current_price_datetime": ticker_prices.current_price_datetime,
            "price_currency": ticker_prices.currency,
        }
    )

    if start_point is None or end_point is None:
        base_row["price_status"] = "no_data"
        base_row["price_error"] = f"No trading data found for {quarter_period.label}"
        return base_row

    close_variation = calculate_variation(start_point.close, end_point.close)
    adj_close_variation = calculate_variation(start_point.adj_close, end_point.adj_close)
    base_row.update(
        {
            "price_start_date": start_point.price_date.isoformat(),
            "price_end_date": end_point.price_date.isoformat(),
            "price_start_close": start_point.close,
            "price_end_close": end_point.close,
            "price_start_adj_close": start_point.adj_close,
            "price_end_adj_close": end_point.adj_close,
            "quarter_variation_close": close_variation[0],
            "quarter_variation_close_pct": close_variation[1],
            "quarter_variation_adj_close": adj_close_variation[0],
            "quarter_variation_adj_close_pct": adj_close_variation[1],
        }
    )
    return base_row


def first_price_on_or_after(prices: pd.DataFrame, start: date, end: date) -> PricePoint | None:
    if prices.empty:
        return None
    candidates = prices[(prices["price_date"] >= start) & (prices["price_date"] <= end)]
    if candidates.empty:
        return None
    row = candidates.iloc[0]
    return PricePoint(price_date=row["price_date"], close=as_float(row["close"]), adj_close=as_float(row["adj_close"]))


def last_price_on_or_before(prices: pd.DataFrame, start: date, end: date) -> PricePoint | None:
    if prices.empty:
        return None
    candidates = prices[(prices["price_date"] >= start) & (prices["price_date"] <= end)]
    if candidates.empty:
        return None
    row = candidates.iloc[-1]
    return PricePoint(price_date=row["price_date"], close=as_float(row["close"]), adj_close=as_float(row["adj_close"]))


def calculate_variation(start_value: float | None, end_value: float | None) -> tuple[float | None, float | None]:
    if start_value is None or end_value is None:
        return None, None
    variation = end_value - start_value
    if start_value == 0:
        return variation, None
    return variation, variation / start_value


def empty_price_row(
    yahoo_symbol: str,
    quarter_period: QuarterPeriod | None = None,
    status: str = "error",
    error: str | None = None,
) -> dict[str, Any]:
    row = {column: None for column in PRICE_COLUMNS}
    row.update(
        {
            "ticker_yahoo": yahoo_symbol,
            "price_status": status,
            "price_error": error,
        }
    )
    if quarter_period is not None:
        row.update(
            {
                "quarter_start_date": quarter_period.start.isoformat(),
                "quarter_end_date": quarter_period.end.isoformat(),
            }
        )
    return row


def as_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


if __name__ == "__main__":
    main()
