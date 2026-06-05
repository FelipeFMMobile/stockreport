from __future__ import annotations

from datetime import date

import pandas as pd

from stock_report.dataset import (
    build_dataset,
    filter_b3_companies,
    latest_record_in_last_year,
)


class FakeClient:
    base_url = "https://api.dadosdemercado.com.br/v1"

    def __init__(self) -> None:
        self.statement_types_seen: list[tuple[str, int, str]] = []

    def companies(self):
        return [
            {
                "cvm_code": 2,
                "name": "Beta S.A.",
                "trade_name": "Beta",
                "cnpj": "00.000.000/0002-00",
                "main_activity": "Energia",
                "is_b3_listed": True,
                "b3_issuer_code": "BETA",
                "b3_listing_segment": "Novo Mercado",
                "b3_sector": "Utilidade Publica",
                "b3_subsector": "Energia Eletrica",
                "b3_segment": "Energia",
                "b3_trade_name": "BETA",
            },
            {
                "cvm_code": 1,
                "name": "Alpha S.A.",
                "trade_name": "Alpha",
                "cnpj": "00.000.000/0001-00",
                "main_activity": "Industria",
                "is_b3_listed": True,
                "b3_issuer_code": "ALFA",
                "b3_listing_segment": "Novo Mercado",
                "b3_sector": "Bens Industriais",
                "b3_subsector": "Maquinas",
                "b3_segment": "Equipamentos",
                "b3_trade_name": "ALFA",
            },
            {"cvm_code": 3, "name": "Private S.A.", "is_b3_listed": False},
        ]

    def balances(self, cvm_code, statement_type):
        self.statement_types_seen.append(("balances", cvm_code, statement_type))
        if cvm_code == 1 and statement_type == "con*":
            return []
        return [
            {
                "cvm_code": cvm_code,
                "statement_type": statement_type,
                "reference_date": "2026-03-31",
                "assets": 1000 + cvm_code,
                "current_assets": 400,
                "cash": 100,
                "liabilities": 500,
                "equity": 500,
            }
        ]

    def incomes(self, cvm_code, statement_type, period_type="ttm"):
        return [
            {
                "cvm_code": cvm_code,
                "statement_type": statement_type,
                "period_init": "2025-04-01",
                "period_end": "2026-03-31",
                "period_type": period_type,
                "net_sales": 900,
                "ebit": 120,
                "net_income": 80,
            }
        ]

    def cash_flows(self, cvm_code, statement_type, period_type="ttm"):
        return [
            {
                "cvm_code": cvm_code,
                "statement_type": statement_type,
                "period_init": "2025-04-01",
                "period_end": "2026-03-31",
                "period_type": period_type,
                "operating": 150,
                "investing": -50,
                "financing": -20,
            }
        ]

    def ratios(self, cvm_code, statement_type, period_type="ttm"):
        return [
            {
                "cvm_code": cvm_code,
                "statement_type": statement_type,
                "period_init": "2025-04-01",
                "period_end": "2026-03-31",
                "period_type": period_type,
                "gross_margin": 0.4,
                "net_margin": 0.1,
                "return_on_equity": 0.16,
                "ebitda": 180,
            }
        ]

    def shares(self, cvm_code):
        return {
            "cvm_code": cvm_code,
            "shares_total": 1000000,
            "shares_pn": None,
            "shares_on": 1000000,
            "free_total": 400000,
            "free_pn": None,
            "free_on": 400000,
        }

    def tickers(self, cvm_code):
        return [
            {
                "ticker": f"TEST{cvm_code}3",
                "type": "acao ordinaria",
                "market_type": "spot",
                "market": "BVMF",
                "issuer_code": f"TEST{cvm_code}",
                "currency": "BRL",
                "isin": f"BRTEST{cvm_code}",
            }
        ]


def test_filter_b3_companies_keeps_only_b3_and_sorts_by_cvm_code():
    companies = [
        {"cvm_code": 20, "is_b3_listed": True},
        {"cvm_code": 10, "is_b3_listed": True},
        {"cvm_code": 30, "is_b3_listed": False},
        {"is_b3_listed": True},
    ]

    assert [company["cvm_code"] for company in filter_b3_companies(companies)] == [10, 20]


def test_latest_record_in_last_year_uses_most_recent_eligible_date():
    records = [
        {"reference_date": "2024-12-31", "assets": 1},
        {"reference_date": "2026-03-31", "assets": 3},
        {"reference_date": "2025-06-30", "assets": 2},
    ]

    latest = latest_record_in_last_year(records, date(2025, 5, 19), "reference_date")

    assert latest == {"reference_date": "2026-03-31", "assets": 3}


def test_build_dataset_outputs_cvm_code_csvs_and_final_unique_rows(tmp_path):
    sleeps = []
    client = FakeClient()

    paths = build_dataset(
        client=client,
        output_dir=tmp_path,
        today=date(2026, 5, 19),
        sleep_func=sleeps.append,
    )

    expected_csvs = [
        "companies",
        "balances",
        "incomes_ttm",
        "cash_flows_ttm",
        "ratios_ttm",
        "shares",
        "tickers",
        "final",
    ]
    for name in expected_csvs:
        frame = pd.read_csv(paths[name])
        assert frame.columns[0] == "cvm_code"
        assert "cvm_code" in frame.columns

    final = pd.read_csv(paths["final"])
    assert final["cvm_code"].is_unique
    assert final["cvm_code"].tolist() == [1, 2]
    assert final.loc[final["cvm_code"] == 1, "main_ticker"].iloc[0] == "TEST13"
    assert final["data_completeness_score"].between(0, 1).all()
    assert sleeps == [1.0]


def test_build_dataset_falls_back_from_consolidated_to_individual(tmp_path):
    client = FakeClient()

    paths = build_dataset(client=client, output_dir=tmp_path, today=date(2026, 5, 19), sleep_func=lambda _: None)

    balances = pd.read_csv(paths["balances"])
    alpha_statement_type = balances.loc[balances["cvm_code"] == 1, "statement_type"].iloc[0]
    beta_statement_type = balances.loc[balances["cvm_code"] == 2, "statement_type"].iloc[0]

    assert alpha_statement_type == "ind*"
    assert beta_statement_type == "con*"
    assert ("balances", 1, "con*") in client.statement_types_seen
    assert ("balances", 1, "ind*") in client.statement_types_seen
