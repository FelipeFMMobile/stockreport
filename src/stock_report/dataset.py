from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .api import DadosDeMercadoClient, DadosDeMercadoError
from .constants import (
    BALANCE_COLUMNS,
    CASH_FLOW_COLUMNS,
    COMPANY_COLUMNS,
    FINANCIAL_COLUMNS_FOR_COMPLETENESS,
    INCOME_COLUMNS,
    RATIO_COLUMNS,
    SHARE_COLUMNS,
    TICKER_COLUMNS,
)

LOGGER = logging.getLogger(__name__)
STATEMENT_TYPE_PRIORITY = ("con*", "ind*")


def build_dataset(
    client: DadosDeMercadoClient,
    output_dir: Path,
    sleep_seconds: float = 1.0,
    today: date | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
) -> dict[str, Path]:
    today = today or datetime.now(UTC).date()
    cutoff_date = today - timedelta(days=365)
    raw_dir = output_dir / "raw"
    processed_dir = output_dir / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    companies = filter_b3_companies(client.companies())
    companies_rows = [select_columns(company, COMPANY_COLUMNS) for company in companies]

    balance_rows: list[dict[str, Any]] = []
    income_rows: list[dict[str, Any]] = []
    cash_flow_rows: list[dict[str, Any]] = []
    ratio_rows: list[dict[str, Any]] = []
    share_rows: list[dict[str, Any]] = []
    ticker_rows: list[dict[str, Any]] = []

    for index, company in enumerate(companies):
        if index > 0:
            sleep_func(sleep_seconds)

        cvm_code = company["cvm_code"]
        LOGGER.info("Collecting company cvm_code=%s (%s/%s)", cvm_code, index + 1, len(companies))

        balance_rows.extend(
            collect_statement_record(
                cvm_code=cvm_code,
                fetch=lambda statement_type, code=cvm_code: client.balances(code, statement_type),
                columns=BALANCE_COLUMNS,
                cutoff_date=cutoff_date,
                date_column="reference_date",
            )
        )
        income_rows.extend(
            collect_statement_record(
                cvm_code=cvm_code,
                fetch=lambda statement_type, code=cvm_code: client.incomes(code, statement_type),
                columns=INCOME_COLUMNS,
                cutoff_date=cutoff_date,
                date_column="period_end",
            )
        )
        cash_flow_rows.extend(
            collect_statement_record(
                cvm_code=cvm_code,
                fetch=lambda statement_type, code=cvm_code: client.cash_flows(code, statement_type),
                columns=CASH_FLOW_COLUMNS,
                cutoff_date=cutoff_date,
                date_column="period_end",
            )
        )
        ratio_rows.extend(
            collect_statement_record(
                cvm_code=cvm_code,
                fetch=lambda statement_type, code=cvm_code: client.ratios(code, statement_type),
                columns=RATIO_COLUMNS,
                cutoff_date=cutoff_date,
                date_column="period_end",
            )
        )

        share = client.shares(cvm_code)
        if share:
            share_rows.append(select_columns(with_cvm_code(share, cvm_code), SHARE_COLUMNS))

        for ticker in client.tickers(cvm_code):
            ticker_rows.append(select_columns(with_cvm_code(ticker, cvm_code), TICKER_COLUMNS))

    frames = {
        "companies": dataframe_with_columns(companies_rows, COMPANY_COLUMNS),
        "balances": dataframe_with_columns(balance_rows, BALANCE_COLUMNS),
        "incomes_ttm": dataframe_with_columns(income_rows, INCOME_COLUMNS),
        "cash_flows_ttm": dataframe_with_columns(cash_flow_rows, CASH_FLOW_COLUMNS),
        "ratios_ttm": dataframe_with_columns(ratio_rows, RATIO_COLUMNS),
        "shares": dataframe_with_columns(share_rows, SHARE_COLUMNS),
        "tickers": dataframe_with_columns(ticker_rows, TICKER_COLUMNS),
    }

    final = build_final_dataset(frames, collected_at=datetime.now(UTC))

    paths = {
        "companies": raw_dir / "companies.csv",
        "balances": raw_dir / "balances.csv",
        "incomes_ttm": raw_dir / "incomes_ttm.csv",
        "cash_flows_ttm": raw_dir / "cash_flows_ttm.csv",
        "ratios_ttm": raw_dir / "ratios_ttm.csv",
        "shares": raw_dir / "shares.csv",
        "tickers": raw_dir / "tickers.csv",
        "final": processed_dir / "b3_financials_last_year.csv",
    }

    for name, frame in frames.items():
        write_csv(frame, paths[name])
    write_csv(final, paths["final"])

    return paths


def filter_b3_companies(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = [company for company in companies if company.get("is_b3_listed") is True and company.get("cvm_code")]
    return sorted(filtered, key=lambda company: company["cvm_code"])


def collect_statement_record(
    cvm_code: int,
    fetch: Callable[[str], list[dict[str, Any]]],
    columns: list[str],
    cutoff_date: date,
    date_column: str,
) -> list[dict[str, Any]]:
    for statement_type in STATEMENT_TYPE_PRIORITY:
        records = fetch(statement_type)
        latest = latest_record_in_last_year(records, cutoff_date, date_column)
        if latest:
            latest["statement_type"] = latest.get("statement_type") or statement_type
            return [select_columns(with_cvm_code(latest, cvm_code), columns)]
    return []


def latest_record_in_last_year(
    records: list[dict[str, Any]],
    cutoff_date: date,
    date_column: str,
) -> dict[str, Any] | None:
    eligible = []
    for record in records:
        parsed_date = parse_date(record.get(date_column))
        if parsed_date and parsed_date >= cutoff_date:
            eligible.append((parsed_date, record))

    if not eligible:
        return None

    return max(eligible, key=lambda item: item[0])[1].copy()


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def with_cvm_code(record: dict[str, Any], cvm_code: int) -> dict[str, Any]:
    return {**record, "cvm_code": record.get("cvm_code") or cvm_code}


def select_columns(record: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    selected = {column: record.get(column) for column in columns}
    for column in columns:
        if column.endswith("date") or column in {"period_init", "period_end"}:
            selected[column] = format_date(selected[column])
    return selected


def format_date(value: Any) -> str | None:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else None


def dataframe_with_columns(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=columns)
    return frame[columns]


def build_final_dataset(frames: dict[str, pd.DataFrame], collected_at: datetime) -> pd.DataFrame:
    final = frames["companies"].copy()

    final = merge_one_to_one(final, frames["balances"], prefix_dates={"reference_date": "balance_reference_date"})
    final = merge_one_to_one(
        final,
        frames["incomes_ttm"],
        prefix_dates={"period_init": "income_period_init", "period_end": "income_period_end"},
        suffix="_income",
    )
    final = merge_one_to_one(
        final,
        rename_cash_flow_columns(frames["cash_flows_ttm"]),
        prefix_dates={"period_init": "cash_flow_period_init", "period_end": "cash_flow_period_end"},
        suffix="_cash_flow",
    )
    final = merge_one_to_one(
        final,
        frames["ratios_ttm"],
        prefix_dates={"period_init": "ratio_period_init", "period_end": "ratio_period_end"},
        suffix="_ratio",
    )
    final = merge_one_to_one(final, frames["shares"])

    ticker_summary = summarize_tickers(frames["tickers"])
    final = final.merge(ticker_summary, on="cvm_code", how="left")

    final["source_api_base_url"] = "https://api.dadosdemercado.com.br/v1"
    final["collected_at"] = collected_at.replace(microsecond=0).isoformat()
    final["data_completeness_score"] = final.apply(completeness_score, axis=1)

    return move_cvm_code_first(final.drop_duplicates(subset=["cvm_code"]))


def merge_one_to_one(
    left: pd.DataFrame,
    right: pd.DataFrame,
    prefix_dates: dict[str, str] | None = None,
    suffix: str = "",
) -> pd.DataFrame:
    if right.empty:
        return left
    prepared = right.rename(columns=prefix_dates or {})
    return left.merge(prepared, on="cvm_code", how="left", suffixes=("", suffix))


def rename_cash_flow_columns(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(
        columns={
            "operating": "operating_cash_flow",
            "investing": "investing_cash_flow",
            "financing": "financing_cash_flow",
        }
    )


def summarize_tickers(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["cvm_code", "main_ticker", "tickers", "currency"]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for cvm_code, group in frame.groupby("cvm_code", sort=True):
        tickers = [ticker for ticker in group["ticker"].dropna().astype(str).tolist() if ticker]
        main_ticker = choose_main_ticker(group)
        currencies = [currency for currency in group["currency"].dropna().astype(str).unique().tolist() if currency]
        rows.append(
            {
                "cvm_code": cvm_code,
                "main_ticker": main_ticker,
                "tickers": ";".join(tickers),
                "currency": currencies[0] if currencies else None,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def choose_main_ticker(group: pd.DataFrame) -> str | None:
    if group.empty:
        return None

    type_values = group["type"].fillna("").astype(str).str.lower()
    preferred = group[type_values.str.contains("ordinaria|preferencial|unit|ação|acao", regex=True)]
    source = preferred if not preferred.empty else group
    ticker = source["ticker"].dropna().astype(str)
    return ticker.iloc[0] if not ticker.empty else None


def completeness_score(row: pd.Series) -> float:
    available_columns = [column for column in FINANCIAL_COLUMNS_FOR_COMPLETENESS if column in row.index]
    if not available_columns:
        return 0.0
    filled = row[available_columns].notna().sum()
    return round(float(filled / len(available_columns)), 4)


def move_cvm_code_first(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["cvm_code"] + [column for column in frame.columns if column != "cvm_code"]
    return frame[columns]


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_frame = move_cvm_code_first(frame) if "cvm_code" in frame.columns else frame
    write_frame.to_csv(path, index=False)


def require_token(token: str | None) -> str:
    if not token:
        raise DadosDeMercadoError("Missing DDM_API_TOKEN environment variable.")
    return token
