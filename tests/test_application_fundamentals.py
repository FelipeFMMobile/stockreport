from __future__ import annotations

from pathlib import Path

import pandas as pd

from application.services.fundamentals import build_fundamental_snapshot


class FakePriceProvider:
    def get_quarter_price_row(self, ticker: str, period: str) -> dict:
        assert ticker == "PETR4"
        assert period == "1T2026"
        return {
            "price_end_close": 50.0,
            "quarter_variation_close_pct": 0.10,
            "quarter_variation_adj_close_pct": 0.08,
            "current_price": 54.0,
            "price_currency": "BRL",
            "price_status": "success",
            "price_error": None,
        }


def test_build_fundamental_snapshot_reconstructs_model_features_from_raw_site_tables(tmp_path: Path):
    ticker_dir = tmp_path / "PETR4"
    ticker_dir.mkdir()
    pd.DataFrame(
        [
            {"Conta": "Ativo total", "1T2026": "1,25 T", "4T2025": "1,22 T"},
            {"Conta": "Passivo total", "1T2026": "1,25 T", "4T2025": "1,22 T"},
            {"Conta": "Ativo circulante", "1T2026": "140,53 B", "4T2025": "140,03 B"},
        ]
    ).to_csv(ticker_dir / "balancos.csv", index=False)
    pd.DataFrame(
        [
            {"Conta": "Receita líquida", "1T2026": "123,69 B", "4T2025": "127,37 B"},
            {"Conta": "EBIT", "1T2026": "41,27 B", "4T2025": "28,48 B"},
            {"Conta": "Lucro líquido", "1T2026": "35,00 B", "4T2025": "20,00 B"},
            {"Conta": "Lucro bruto", "1T2026": "59,60 B", "4T2025": "58,49 B"},
            {"Conta": "Resultado financeiro", "1T2026": "-3,20 B", "4T2025": "-3,50 B"},
        ]
    ).to_csv(ticker_dir / "resultados.csv", index=False)
    pd.DataFrame(
        [
            {"Conta": "LPA", "4T2025 (TTM)": "8,54", "2025": "7,10", "2024": "2,84"},
            {"Conta": "P/VP", "4T2025 (TTM)": "1,49", "2025": "1,30", "2024": "1,17"},
            {"Conta": "ROE", "4T2025 (TTM)": "25,00%", "2025": "24,00%", "2024": "20,00%"},
            {"Conta": "ROA", "4T2025 (TTM)": "10,00%", "2025": "9,00%", "2024": "8,00%"},
            {"Conta": "ROIC", "4T2025 (TTM)": "18,00%", "2025": "17,00%", "2024": "16,00%"},
            {"Conta": "Margem líquida", "4T2025 (TTM)": "28,00%", "2025": "27,00%", "2024": "26,00%"},
            {"Conta": "Margem EBIT", "4T2025 (TTM)": "33,00%", "2025": "32,00%", "2024": "31,00%"},
            {"Conta": "Margem bruta", "4T2025 (TTM)": "48,00%", "2025": "47,00%", "2024": "46,00%"},
            {"Conta": "Dívida líquida", "4T2025 (TTM)": "100,00 B", "2025": "95,00 B", "2024": "90,00 B"},
            {"Conta": "Liquidez corrente", "4T2025 (TTM)": "1,20", "2025": "1,10", "2024": "1,00"},
        ]
    ).to_csv(ticker_dir / "indicadores.csv", index=False)

    snapshot = build_fundamental_snapshot("PETR4", price_provider=FakePriceProvider(), site_raw_root=tmp_path)

    assert snapshot.period == "1T2026"
    assert snapshot.feature_row["ticker"] == "PETR4"
    assert snapshot.feature_row["ativo_total"] == 1_250_000_000_000
    assert snapshot.feature_row["receita_liquida"] == 123_690_000_000
    assert snapshot.feature_row["price_end_close"] == 50.0
    assert snapshot.feature_row["pl_calculado"] == 50.0 / 7.10
    assert snapshot.feature_row["margem_ebit_calculada"] == 41_270_000_000 / 123_690_000_000
    assert snapshot.raw_values["lpa_source"] == "annual_previous_year"
