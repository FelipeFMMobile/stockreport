from __future__ import annotations

import pandas as pd

from stock_report.site_dataset import (
    build_site_dataset,
    parse_html_table,
    parse_stock_tickers,
    table_to_long,
)


STOCKS_HTML = """
<html>
  <body>
    <a href="/acoes/petr3">PETR3</a>
    <a href="/acoes/petr4">PETR4</a>
    <a href="/acoes">Acoes</a>
    <a href="/acoes/petr3">PETR3 duplicate</a>
    <a href="/acoes/bbas3">BBAS3</a>
  </body>
</html>
"""


STOCK_PAGE_HTML = """
<html>
  <body>
    <div class="table-container" id="marketratios">
      <table>
        <thead>
          <tr><th>Conta</th><th>4T2025 (TTM)</th><th>2024</th></tr>
        </thead>
        <tbody>
          <tr><td>P/L</td><td>10,50</td><td>9,20</td></tr>
          <tr><td>Margem líquida</td><td>20,00%</td><td>19,00%</td></tr>
        </tbody>
      </table>
    </div>

    <div class="table-container" id="balances">
      <table>
        <thead>
          <tr><th>Conta</th><th>1T2026</th><th>4T2025</th></tr>
        </thead>
        <tbody>
          <tr><td>Ativo total</td><td>1,20 B</td><td>1,10 B</td></tr>
        </tbody>
      </table>
    </div>

    <div class="table-container" id="incomes">
      <table>
        <thead>
          <tr><th>Conta</th><th>1T2026 (TTM)</th><th>2025</th></tr>
        </thead>
        <tbody>
          <tr><td>Receita líquida</td><td>900,00 M</td><td>850,00 M</td></tr>
        </tbody>
      </table>
    </div>
  </body>
</html>
"""


class FakeSiteClient:
    base_url = "https://www.dadosdemercado.com.br"

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = pages or {}

    def stocks_index(self) -> str:
        return STOCKS_HTML

    def stock_page(self, ticker: str) -> str:
        return self.pages.get(ticker, STOCK_PAGE_HTML)

    def stock_url(self, ticker: str) -> str:
        return f"{self.base_url}/acoes/{ticker.lower()}"


def test_parse_stock_tickers_reads_unique_tickers_from_index_links():
    assert parse_stock_tickers(STOCKS_HTML) == ["PETR3", "PETR4", "BBAS3"]


def test_parse_html_table_reads_named_table_as_wide_dataframe():
    frame = parse_html_table(STOCK_PAGE_HTML, "marketratios")

    assert frame.columns.tolist() == ["Conta", "4T2025 (TTM)", "2024"]
    assert frame.to_dict("records") == [
        {"Conta": "P/L", "4T2025 (TTM)": "10,50", "2024": "9,20"},
        {"Conta": "Margem líquida", "4T2025 (TTM)": "20,00%", "2024": "19,00%"},
    ]


def test_table_to_long_preserves_ticker_account_period_and_raw_value():
    frame = parse_html_table(STOCK_PAGE_HTML, "balances")

    rows = table_to_long(
        frame,
        ticker="PETR3",
        topic="balancos",
        source_url="https://www.dadosdemercado.com.br/acoes/petr3",
        collected_at="2026-05-19T12:00:00+00:00",
    )

    assert rows == [
        {
            "ticker": "PETR3",
            "topic": "balancos",
            "account": "Ativo total",
            "period": "1T2026",
            "value_raw": "1,20 B",
            "source_url": "https://www.dadosdemercado.com.br/acoes/petr3",
            "collected_at": "2026-05-19T12:00:00+00:00",
        },
        {
            "ticker": "PETR3",
            "topic": "balancos",
            "account": "Ativo total",
            "period": "4T2025",
            "value_raw": "1,10 B",
            "source_url": "https://www.dadosdemercado.com.br/acoes/petr3",
            "collected_at": "2026-05-19T12:00:00+00:00",
        },
    ]


def test_build_site_dataset_writes_raw_by_ticker_and_processed_long_csvs(tmp_path):
    paths = build_site_dataset(
        client=FakeSiteClient(),
        output_dir=tmp_path,
        sleep_seconds=0,
        sleep_func=lambda _: None,
        ticker_limit=2,
    )

    assert (tmp_path / "site" / "raw" / "PETR3" / "indicadores.csv").exists()
    assert (tmp_path / "site" / "raw" / "PETR4" / "indicadores.csv").exists()

    indicadores = pd.read_csv(paths["indicadores"])
    assert indicadores["ticker"].tolist() == ["PETR3", "PETR3", "PETR3", "PETR3", "PETR4", "PETR4", "PETR4", "PETR4"]
    assert set(indicadores.columns) == {
        "ticker",
        "topic",
        "account",
        "period",
        "value_raw",
        "source_url",
        "collected_at",
    }

    balancos = pd.read_csv(paths["balancos"])
    assert balancos[["ticker", "account", "period", "value_raw"]].to_dict("records")[:2] == [
        {"ticker": "PETR3", "account": "Ativo total", "period": "1T2026", "value_raw": "1,20 B"},
        {"ticker": "PETR3", "account": "Ativo total", "period": "4T2025", "value_raw": "1,10 B"},
    ]


def test_build_site_dataset_handles_missing_table_with_empty_dataset(tmp_path):
    missing_incomes_html = STOCK_PAGE_HTML.replace('id="incomes"', 'id="other-table"')
    paths = build_site_dataset(
        client=FakeSiteClient(pages={"PETR3": missing_incomes_html}),
        output_dir=tmp_path,
        sleep_seconds=0,
        sleep_func=lambda _: None,
        ticker_limit=1,
    )

    resultados = pd.read_csv(paths["resultados"])
    assert resultados.empty
    assert resultados.columns.tolist() == [
        "ticker",
        "topic",
        "account",
        "period",
        "value_raw",
        "source_url",
        "collected_at",
    ]
