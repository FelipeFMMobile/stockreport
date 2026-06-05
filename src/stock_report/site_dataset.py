from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

SITE_BASE_URL = "https://www.dadosdemercado.com.br"
LONG_COLUMNS = ["ticker", "topic", "account", "period", "value_raw", "source_url", "collected_at"]
ERROR_COLUMNS = ["ticker", "source_url", "error", "collected_at"]
TABLES = {
    "indicadores": ("marketratios", "indicadores.csv"),
    "balancos": ("balances", "balancos.csv"),
    "resultados": ("incomes", "resultados.csv"),
}
TICKER_RE = re.compile(r"^[A-Z]{4}\d{1,2}[A-Z]?$")


class DadosDeMercadoSiteError(RuntimeError):
    """Raised when the public Dados de Mercado website cannot be collected."""


@dataclass(frozen=True)
class SiteDadosDeMercadoClient:
    base_url: str = SITE_BASE_URL
    timeout: int = 30
    max_retries: int = 3
    backoff_seconds: float = 2.0
    user_agent: str = "stock-report/0.1 (+https://www.dadosdemercado.com.br)"

    def get_html(self, path: str) -> str:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {"User-Agent": self.user_agent}

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.get(url, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    sleep_for = self.backoff_seconds * (attempt + 1)
                    LOGGER.warning("Site request failed for %s: %s. Retrying in %.1fs.", url, exc, sleep_for)
                    time.sleep(sleep_for)
                    continue
                raise DadosDeMercadoSiteError(f"Site request failed for {url}: {exc}") from exc

            if response.status_code == 200:
                return response.text

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                sleep_for = self.backoff_seconds * (attempt + 1)
                LOGGER.warning("Site request failed with %s for %s. Retrying in %.1fs.", response.status_code, url, sleep_for)
                time.sleep(sleep_for)
                continue

            raise DadosDeMercadoSiteError(f"Site request failed with {response.status_code} for {url}: {response.text}")

        raise DadosDeMercadoSiteError(f"Site request failed after retries for {url}")

    def stocks_index(self) -> str:
        return self.get_html("/acoes")

    def stock_page(self, ticker: str) -> str:
        return self.get_html(f"/acoes/{ticker.lower()}")

    def stock_url(self, ticker: str) -> str:
        return f"{self.base_url.rstrip('/')}/acoes/{ticker.lower()}"


def build_site_dataset(
    client: SiteDadosDeMercadoClient,
    output_dir: Path,
    sleep_seconds: float = 1.0,
    sleep_func: Callable[[float], None] = time.sleep,
    ticker_limit: int | None = None,
) -> dict[str, Path]:
    site_dir = output_dir / "site"
    raw_dir = site_dir / "raw"
    processed_dir = site_dir / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    collected_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    tickers = parse_stock_tickers(client.stocks_index())
    if ticker_limit is not None:
        tickers = tickers[:ticker_limit]

    consolidated_rows = {topic: [] for topic in TABLES}
    error_rows: list[dict[str, str]] = []

    for index, ticker in enumerate(tickers):
        if index > 0:
            sleep_func(sleep_seconds)

        source_url = client.stock_url(ticker)
        LOGGER.info("Collecting site tables for ticker=%s (%s/%s)", ticker, index + 1, len(tickers))

        try:
            html = client.stock_page(ticker)
        except Exception as exc:
            LOGGER.warning("Failed to collect %s: %s", ticker, exc)
            error_rows.append(
                {"ticker": ticker, "source_url": source_url, "error": str(exc), "collected_at": collected_at}
            )
            continue

        ticker_dir = raw_dir / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)

        for topic, (table_id, filename) in TABLES.items():
            table = parse_html_table(html, table_id)
            if table.empty:
                LOGGER.warning("Ticker %s has no table #%s.", ticker, table_id)
            write_csv(table, ticker_dir / filename)
            consolidated_rows[topic].extend(table_to_long(table, ticker, topic, source_url, collected_at))

    paths = {
        "indicadores": processed_dir / "indicadores.csv",
        "balancos": processed_dir / "balancos.csv",
        "resultados": processed_dir / "resultados.csv",
        "errors": processed_dir / "errors.csv",
    }

    for topic in TABLES:
        write_csv(pd.DataFrame(consolidated_rows[topic], columns=LONG_COLUMNS), paths[topic])
    write_csv(pd.DataFrame(error_rows, columns=ERROR_COLUMNS), paths["errors"])

    return paths


def parse_stock_tickers(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    tickers = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        path = urlparse(href).path.lower()
        if not path.startswith("/acoes/"):
            continue

        ticker = path.rsplit("/", 1)[-1].upper()
        if not TICKER_RE.match(ticker) or ticker in seen:
            continue

        seen.add(ticker)
        tickers.append(ticker)

    return tickers


def parse_html_table(html: str, table_id: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("div", id=table_id)
    if table is None:
        table = soup.find("table", id=table_id)
    if table is None:
        return pd.DataFrame()

    table_node = table.find("table") if table.name != "table" else table
    if table_node is None:
        return pd.DataFrame()

    headers = [normalize_text(cell.get_text(" ", strip=True)) for cell in table_node.select("thead th")]
    if not headers:
        first_row = table_node.find("tr")
        if first_row:
            headers = [normalize_text(cell.get_text(" ", strip=True)) for cell in first_row.find_all(["th", "td"])]

    body_rows = table_node.select("tbody tr")
    if not body_rows:
        rows = table_node.find_all("tr")
        body_rows = rows[1:] if headers else rows

    parsed_rows = []
    for row in body_rows:
        values = [normalize_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
        if not values or all(value == "" for value in values):
            continue
        parsed_rows.append(pad_or_trim(values, len(headers)))

    if not headers:
        return pd.DataFrame(parsed_rows)

    return pd.DataFrame(parsed_rows, columns=headers)


def table_to_long(
    table: pd.DataFrame,
    ticker: str,
    topic: str,
    source_url: str,
    collected_at: str,
) -> list[dict[str, Any]]:
    if table.empty or len(table.columns) < 2:
        return []

    account_column = table.columns[0]
    rows = []
    account_index = table.columns.get_loc(account_column)
    if isinstance(account_index, slice):
        account_index = 0
    elif not isinstance(account_index, int):
        account_index = int(account_index[0])

    for _, record in table.iterrows():
        account = record.iloc[account_index]
        if pd.isna(account) or str(account).strip() == "":
            continue

        for column_index, period in enumerate(table.columns[1:], start=1):
            value = record.iloc[column_index]
            rows.append(
                {
                    "ticker": ticker,
                    "topic": topic,
                    "account": str(account),
                    "period": str(period),
                    "value_raw": None if pd.isna(value) else str(value),
                    "source_url": source_url,
                    "collected_at": collected_at,
                }
            )
    return rows


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def pad_or_trim(values: list[str], expected_size: int) -> list[str]:
    if expected_size <= 0:
        return values
    if len(values) < expected_size:
        return values + [""] * (expected_size - len(values))
    return values[:expected_size]


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
