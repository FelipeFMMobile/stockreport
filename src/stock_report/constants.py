COMPANY_COLUMNS = [
    "cvm_code",
    "name",
    "trade_name",
    "cnpj",
    "main_activity",
    "is_b3_listed",
    "b3_issuer_code",
    "b3_listing_segment",
    "b3_sector",
    "b3_subsector",
    "b3_segment",
    "b3_trade_name",
]

BALANCE_COLUMNS = [
    "cvm_code",
    "statement_type",
    "reference_date",
    "assets",
    "current_assets",
    "cash",
    "financial_investments",
    "receivables",
    "inventories",
    "noncurrent_assets",
    "investments",
    "fixed_assets",
    "intangible_assets",
    "liabilities",
    "current_liabilities",
    "suppliers",
    "loans",
    "noncurrent_liabilities",
    "long_term_loans",
    "equity",
    "equity_non_controlling",
]

INCOME_COLUMNS = [
    "cvm_code",
    "statement_type",
    "period_init",
    "period_end",
    "period_type",
    "net_sales",
    "costs",
    "gross_income",
    "operating_expenses",
    "selling_expenses",
    "administrative_expenses",
    "ebit",
    "operating_income",
    "non_operating_income",
    "profit_before_taxes",
    "taxes",
    "net_income",
    "net_income_controlling",
    "net_income_non_controlling",
]

CASH_FLOW_COLUMNS = [
    "cvm_code",
    "statement_type",
    "period_init",
    "period_end",
    "period_type",
    "operating",
    "cash_generated_from_operations",
    "changes_in_assets_and_liabilities",
    "investing",
    "financing",
    "foreign_exchange_variation",
    "increase_in_cash",
    "depreciation_and_amortization",
]

RATIO_COLUMNS = [
    "cvm_code",
    "statement_type",
    "period_init",
    "period_end",
    "period_type",
    "gross_margin",
    "net_margin",
    "ebit_margin",
    "operating_margin",
    "return_on_equity",
    "return_on_assets",
    "return_on_invested_capital",
    "asset_turnover",
    "current_liquidity",
    "quick_liquidity",
    "cash_liquidity",
    "working_capital",
    "gross_debt",
    "net_debt",
    "total_debt",
    "ebitda",
    "ebitda_margin",
]

SHARE_COLUMNS = [
    "cvm_code",
    "shares_total",
    "shares_pn",
    "shares_on",
    "free_total",
    "free_pn",
    "free_on",
]

TICKER_COLUMNS = [
    "cvm_code",
    "ticker",
    "type",
    "market_type",
    "market",
    "issuer_code",
    "currency",
    "isin",
]

FINANCIAL_COLUMNS_FOR_COMPLETENESS = (
    BALANCE_COLUMNS[3:]
    + INCOME_COLUMNS[5:]
    + CASH_FLOW_COLUMNS[5:]
    + RATIO_COLUMNS[5:]
    + SHARE_COLUMNS[1:]
)
