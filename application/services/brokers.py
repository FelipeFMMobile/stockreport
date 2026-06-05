from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests
from bs4 import BeautifulSoup

from .feature_engineering import normalize_ticker, parse_numeric

RequestGet = Callable[..., requests.Response]

YAHOO_QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
BRAPI_QUOTE_URL = "https://brapi.dev/api/quote/{ticker}"
BTG_RECOMMENDATION_URL = (
    "https://content.btgpactual.com/api/research/content-hub/recommendations/ticker/"
    "{ticker}?includeInstitutionalData=true"
)


@dataclass(frozen=True)
class SourceStatus:
    name: str
    status: str
    url: str | None = None
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "url": self.url, "warning": self.warning}


@dataclass(frozen=True)
class BrokerTargets:
    ticker: str
    source_url: str | None
    consensus: str | None
    analyst_count: int | None
    average_target: float | None
    high_target: float | None
    low_target: float | None
    recommendations: list[dict[str, Any]]
    status: str
    warning: str | None = None
    source: str = "Multi-source"
    median_target: float | None = None
    sources: list[SourceStatus] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "source": self.source,
            "source_url": self.source_url,
            "consensus": self.consensus,
            "analyst_count": self.analyst_count,
            "average_target": self.average_target,
            "high_target": self.high_target,
            "low_target": self.low_target,
            "median_target": self.median_target,
            "recommendations": self.recommendations,
            "status": self.status,
            "warning": self.warning,
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass(frozen=True)
class BrokerSourceResult:
    name: str
    status: str
    url: str | None = None
    warning: str | None = None
    consensus: str | None = None
    analyst_count: int | None = None
    average_target: float | None = None
    high_target: float | None = None
    low_target: float | None = None
    median_target: float | None = None
    recommendations: list[dict[str, Any]] = field(default_factory=list)

    def source_status(self) -> SourceStatus:
        return SourceStatus(name=self.name, status=self.status, url=self.url, warning=self.warning)


class BrokerTargetAggregatorService:
    def __init__(
        self,
        timeout: int = 25,
        request_get: RequestGet = requests.get,
        brapi_token: str | None = None,
        enable_investing: bool | None = None,
    ) -> None:
        self.timeout = timeout
        self.request_get = request_get
        self.brapi_token = brapi_token if brapi_token is not None else os.getenv("BRAPI_TOKEN")
        self.enable_investing = (
            _env_truthy(os.getenv("STOCKREPORT_ENABLE_INVESTING")) if enable_investing is None else enable_investing
        )

    def get_targets(self, ticker: str) -> BrokerTargets:
        ticker = normalize_ticker(ticker)
        results = [
            self._fetch_brapi(ticker),
            self._fetch_yahoo_quote_summary(ticker),
            self._fetch_xp(ticker),
            self._fetch_bb_bi(ticker),
            self._fetch_btg(ticker),
        ]
        if self.enable_investing:
            results.append(self._fetch_investing_disabled_fallback(ticker))
        return _aggregate_results(ticker, results)

    def _fetch_brapi(self, ticker: str) -> BrokerSourceResult:
        url = BRAPI_QUOTE_URL.format(ticker=ticker)
        if not self.brapi_token:
            return BrokerSourceResult(name="brapi", status="unsupported", url=url, warning="BRAPI_TOKEN não configurado.")
        try:
            response = self.request_get(
                url,
                params={"modules": "financialData"},
                headers={"Authorization": f"Bearer {self.brapi_token}", "User-Agent": "stock-report-application/0.1"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return parse_brapi_quote_payload(response.json(), ticker=ticker, source_url=response.url or url)
        except Exception as exc:
            return BrokerSourceResult(name="brapi", status="error", url=url, warning=f"Falha ao consultar brapi: {exc}")

    def _fetch_yahoo_quote_summary(self, ticker: str) -> BrokerSourceResult:
        symbol = f"{ticker}.SA"
        url = YAHOO_QUOTE_SUMMARY_URL.format(symbol=symbol)
        try:
            response = self.request_get(
                url,
                params={"modules": "financialData,recommendationTrend,upgradeDowngradeHistory"},
                headers={"User-Agent": "Mozilla/5.0 stock-report-application/0.1"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return parse_yahoo_quote_summary_payload(response.json(), ticker=ticker, source_url=response.url or url)
        except Exception as exc:
            return BrokerSourceResult(name="Yahoo Finance", status="error", url=url, warning=f"Falha ao consultar Yahoo: {exc}")

    def _fetch_xp(self, ticker: str) -> BrokerSourceResult:
        url = f"https://conteudos.xpi.com.br/acoes/{ticker.lower()}/"
        return self._fetch_public_research_page("XP", url, ticker, parse_xp_research_html)

    def _fetch_bb_bi(self, ticker: str) -> BrokerSourceResult:
        url = f"https://investalk.bb.com.br/acoes/{ticker}"
        return self._fetch_public_research_page("BB-BI", url, ticker, parse_bb_bi_research_html)

    def _fetch_btg(self, ticker: str) -> BrokerSourceResult:
        url = BTG_RECOMMENDATION_URL.format(ticker=ticker)
        try:
            response = self.request_get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 stock-report-application/0.1",
                    "Accept": "application/json",
                    "Referer": f"https://content.btgpactual.com/research/ativo/{ticker}",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return parse_btg_recommendation_payload(response.json(), ticker=ticker, source_url=response.url or url)
        except Exception as exc:
            return BrokerSourceResult(name="BTG Pactual", status="error", url=url, warning=f"Falha ao consultar BTG Pactual: {exc}")

    def _fetch_public_research_page(
        self,
        name: str,
        url: str,
        ticker: str,
        parser: Callable[[str, str, str], BrokerSourceResult],
    ) -> BrokerSourceResult:
        try:
            response = self.request_get(
                url,
                headers={"User-Agent": "Mozilla/5.0 stock-report-application/0.1", "Accept-Language": "pt-BR,pt;q=0.9"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return parser(response.text, ticker, response.url or url)
        except Exception as exc:
            return BrokerSourceResult(name=name, status="error", url=url, warning=f"Falha ao consultar {name}: {exc}")

    def _fetch_investing_disabled_fallback(self, ticker: str) -> BrokerSourceResult:
        return BrokerSourceResult(
            name="Investing.com",
            status="unsupported",
            url=None,
            warning="Investing.com permanece desativado por padrão devido a bloqueios recorrentes.",
        )


def parse_brapi_quote_payload(payload: dict[str, Any], ticker: str, source_url: str | None = None) -> BrokerSourceResult:
    ticker = normalize_ticker(ticker)
    result = _first_payload_result(payload)
    financial_data = result.get("financialData") or {}
    return BrokerSourceResult(
        name="brapi",
        status=_status_for_aggregate(financial_data),
        url=source_url,
        consensus=_normalize_consensus(_raw_value(financial_data.get("recommendationKey"))),
        analyst_count=_as_int(_raw_value(financial_data.get("numberOfAnalystOpinions"))),
        average_target=_as_float(_raw_value(financial_data.get("targetMeanPrice"))),
        high_target=_as_float(_raw_value(financial_data.get("targetHighPrice"))),
        low_target=_as_float(_raw_value(financial_data.get("targetLowPrice"))),
        median_target=_as_float(_raw_value(financial_data.get("targetMedianPrice"))),
        warning=None if financial_data else "brapi não retornou financialData para o ticker.",
    )


def parse_yahoo_quote_summary_payload(
    payload: dict[str, Any],
    ticker: str,
    source_url: str | None = None,
) -> BrokerSourceResult:
    ticker = normalize_ticker(ticker)
    result = _first_quote_summary_result(payload)
    financial_data = result.get("financialData") or {}
    recommendation_trend = result.get("recommendationTrend") or {}
    upgrades = result.get("upgradeDowngradeHistory") or {}
    recommendations = _recommendations_from_yahoo(upgrades.get("history") or [], source_url)
    consensus = _normalize_consensus(_raw_value(financial_data.get("recommendationKey")))
    analyst_count = _as_int(_raw_value(financial_data.get("numberOfAnalystOpinions")))
    if analyst_count is None:
        trend = (recommendation_trend.get("trend") or [{}])[0]
        analyst_count = sum(_as_int(_raw_value(trend.get(key))) or 0 for key in ["strongBuy", "buy", "hold", "sell", "strongSell"]) or None
    return BrokerSourceResult(
        name="Yahoo Finance",
        status=_status_for_aggregate(financial_data) if financial_data else ("success" if recommendations else "partial"),
        url=source_url,
        consensus=consensus,
        analyst_count=analyst_count,
        average_target=_as_float(_raw_value(financial_data.get("targetMeanPrice"))),
        high_target=_as_float(_raw_value(financial_data.get("targetHighPrice"))),
        low_target=_as_float(_raw_value(financial_data.get("targetLowPrice"))),
        median_target=_as_float(_raw_value(financial_data.get("targetMedianPrice"))),
        recommendations=recommendations,
        warning=None if financial_data or recommendations else "Yahoo não retornou financialData ou histórico de recomendações.",
    )


def parse_xp_research_html(html: str, ticker: str, source_url: str | None = None) -> BrokerSourceResult:
    return _parse_public_research_html(
        html=html,
        ticker=ticker,
        source_url=source_url,
        source_name="XP",
        firm="XP Investimentos",
        target_patterns=[r"pre[cç]o\s*alvo(?:\s*(?:de|é|:))?\s*(?:R\$|BRL)?\s*([0-9]+(?:[.,][0-9]+)?)"],
        rating_patterns=[r"recomenda[cç][aã]o(?:\s*(?:é|:))?\s*([A-Za-zÀ-ÿ ]{3,30})"],
    )


def parse_bb_bi_research_html(html: str, ticker: str, source_url: str | None = None) -> BrokerSourceResult:
    return _parse_public_research_html(
        html=html,
        ticker=ticker,
        source_url=source_url,
        source_name="BB-BI",
        firm="BB-BI",
        target_patterns=[
            r"pre[cç]o[- ]alvo\s*BB[- ]BI(?:\s*(?:é|:))?\s*(?:R\$|BRL)?\s*([0-9]+(?:[.,][0-9]+)?)",
            r"pre[cç]o[- ]alvo(?:\s*(?:é|:))?\s*(?:R\$|BRL)?\s*([0-9]+(?:[.,][0-9]+)?)",
        ],
        rating_patterns=[
            r"recomenda[cç][aã]o\s*BB[- ]BI(?:\s*(?:é|:))?\s*([A-Za-zÀ-ÿ ]{3,30})",
            r"recomenda[cç][aã]o(?:\s*(?:é|:))?\s*([A-Za-zÀ-ÿ ]{3,30})",
        ],
    )


def parse_btg_research_html(html: str, ticker: str, source_url: str | None = None) -> BrokerSourceResult:
    return _parse_public_research_html(
        html=html,
        ticker=ticker,
        source_url=source_url,
        source_name="BTG Pactual",
        firm="BTG Pactual",
        target_patterns=[r"pre[cç]o[- ]alvo(?:\s*(?:é|:))?\s*(?:R\$|BRL)?\s*([0-9]+(?:[.,][0-9]+)?)"],
        rating_patterns=[r"recomenda[cç][aã]o(?:\s*(?:é|:))?\s*([A-Za-zÀ-ÿ ]{3,30})"],
    )


def parse_btg_recommendation_payload(
    payload: dict[str, Any],
    ticker: str,
    source_url: str | None = None,
) -> BrokerSourceResult:
    ticker = normalize_ticker(ticker)
    if not isinstance(payload, dict):
        return BrokerSourceResult(
            name="BTG Pactual",
            status="partial",
            url=source_url,
            warning="BTG Pactual retornou um payload inválido para recomendação.",
        )

    target_price = _as_float(payload.get("targetPrice"))
    rating = _normalize_consensus(payload.get("recommendation"))
    source_report = payload.get("analysisFile") or source_url
    date = _date_from_iso(payload.get("recommendationDate"))
    recommendations = []
    if target_price is not None or rating:
        recommendations.append(
            {
                "firm": "BTG Pactual",
                "rating": rating,
                "target_price": target_price,
                "date": date,
                "source_url": source_report,
                "raw": {
                    "asset": payload.get("asset"),
                    "informationSource": payload.get("informationSource"),
                    "recommendationDate": payload.get("recommendationDate"),
                },
            }
        )

    status = "success" if recommendations else "partial"
    return BrokerSourceResult(
        name="BTG Pactual",
        status=status,
        url=source_url,
        recommendations=recommendations,
        warning=None if recommendations else "BTG Pactual não retornou recomendação/preço-alvo para o ticker.",
    )


def _parse_public_research_html(
    html: str,
    ticker: str,
    source_url: str | None,
    source_name: str,
    firm: str,
    target_patterns: list[str],
    rating_patterns: list[str],
) -> BrokerSourceResult:
    ticker = normalize_ticker(ticker)
    text = _clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    target_price = _first_number_match(text, target_patterns)
    rating = _normalize_consensus(_first_text_match(text, rating_patterns))
    date = _first_text_match(text, [r"(?:atualizado em|data de atualiza[cç][aã]o|publicado em)\s*(\d{1,2}/\d{1,2}/\d{2,4})"])
    recommendations = []
    if target_price is not None or rating:
        recommendations.append(
            {
                "firm": firm,
                "rating": rating,
                "target_price": target_price,
                "date": date,
                "source_url": source_url,
                "raw": None,
            }
        )
    status = "success" if recommendations else "partial"
    return BrokerSourceResult(
        name=source_name,
        status=status,
        url=source_url,
        recommendations=recommendations,
        warning=None if recommendations else f"{source_name} não expôs recomendação/preço-alvo no HTML retornado.",
    )


def parse_investing_consensus_html(html: str, ticker: str, source_url: str | None = None) -> BrokerTargets:
    """Legacy parser kept for fixture compatibility; not used by the default service."""
    ticker = normalize_ticker(ticker)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    consensus = _first_text_match(
        text,
        [
            r"recomenda(?:ç|c)[aã]o consensual.*?(Compra|Venda|Neutro|Manter|Buy|Sell|Hold)",
            r"consensus rating.*?(Strong Buy|Buy|Hold|Sell|Strong Sell)",
            r"classifica(?:ç|c)[aã]o geral de\s+([A-Za-zçÇãÃéÉ ]+)",
        ],
    )
    analyst_count_text = _first_text_match(
        text,
        [
            r"base nas avalia(?:ç|c)[oõ]es de\s+(\d+)\s+analistas",
            r"proje(?:ç|c)[oõ]es de\s+(\d+)\s+analistas",
            r"based on insights from\s+(\d+)\s+analysts",
        ],
    )
    analyst_count = int(analyst_count_text) if analyst_count_text else None
    average_target = _extract_target(text, ["preço-alvo.*?m[ée]dio", "average.*?price target", "12-month price target"])
    high_target = _extract_target(text, ["alta estimativa", "high estimate", "preço-alvo.*?m[aá]ximo"])
    low_target = _extract_target(text, ["baixa estimativa", "low estimate", "preço-alvo.*?m[ií]nimo"])
    recommendations = _extract_recommendation_rows(soup)
    status = (
        "success"
        if any(value is not None for value in [consensus, analyst_count, average_target, high_target, low_target]) or recommendations
        else "partial"
    )
    warning = None if status == "success" else "A página foi lida, mas os dados de consenso não estavam disponíveis no HTML retornado."
    return BrokerTargets(
        ticker=ticker,
        source_url=source_url,
        consensus=consensus,
        analyst_count=analyst_count,
        average_target=average_target,
        high_target=high_target,
        low_target=low_target,
        recommendations=recommendations,
        status=status,
        warning=warning,
        source="Investing.com",
        sources=[SourceStatus(name="Investing.com", status=status, url=source_url, warning=warning)],
    )


def _aggregate_results(ticker: str, results: list[BrokerSourceResult]) -> BrokerTargets:
    aggregate = next(
        (
            result
            for result in results
            if result.status == "success"
            and any(value is not None for value in [result.average_target, result.high_target, result.low_target, result.median_target])
        ),
        None,
    )
    recommendations = []
    seen_recommendations = set()
    for result in results:
        for recommendation in result.recommendations:
            key = (
                recommendation.get("firm"),
                recommendation.get("rating"),
                recommendation.get("target_price"),
                recommendation.get("source_url"),
            )
            if key in seen_recommendations:
                continue
            seen_recommendations.add(key)
            recommendations.append(recommendation)

    recommendation_prices = [item["target_price"] for item in recommendations if item.get("target_price") is not None]
    average_target = aggregate.average_target if aggregate else _average(recommendation_prices)
    high_target = aggregate.high_target if aggregate else (max(recommendation_prices) if recommendation_prices else None)
    low_target = aggregate.low_target if aggregate else (min(recommendation_prices) if recommendation_prices else None)
    median_target = aggregate.median_target if aggregate else _median(recommendation_prices)
    consensus = aggregate.consensus if aggregate else _first_recommendation_rating(recommendations)
    analyst_count = aggregate.analyst_count if aggregate else (len(recommendation_prices) or None)
    successful_sources = [result for result in results if result.status == "success"]
    partial_sources = [result for result in results if result.status == "partial"]
    status = "success" if aggregate or recommendations else ("partial" if partial_sources else "error")
    warning = _aggregate_warning(results, status)
    source_url = aggregate.url if aggregate else next((item.get("source_url") for item in recommendations if item.get("source_url")), None)
    return BrokerTargets(
        ticker=ticker,
        source_url=source_url,
        consensus=consensus,
        analyst_count=analyst_count,
        average_target=average_target,
        high_target=high_target,
        low_target=low_target,
        median_target=median_target,
        recommendations=recommendations[:12],
        status=status,
        warning=warning,
        source=aggregate.name if aggregate else ("Corretoras públicas" if successful_sources else "Multi-source"),
        sources=[result.source_status() for result in results],
    )


def _aggregate_warning(results: list[BrokerSourceResult], status: str) -> str | None:
    warnings = [result.warning for result in results if result.warning]
    if status == "success" and not warnings:
        return None
    if status == "success":
        return "Algumas fontes não retornaram dados: " + " | ".join(warnings[:3])
    if warnings:
        return " | ".join(warnings[:4])
    return "Nenhuma fonte retornou preço-alvo para o ticker."


def _status_for_aggregate(financial_data: dict[str, Any]) -> str:
    fields = ["targetMeanPrice", "targetHighPrice", "targetLowPrice", "targetMedianPrice", "recommendationKey"]
    return "success" if any(_raw_value(financial_data.get(field)) is not None for field in fields) else "partial"


def _first_payload_result(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results") or payload.get("data") or []
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return {}


def _first_quote_summary_result(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("quoteSummary", {}).get("result") or []
    if results and isinstance(results[0], dict):
        return results[0]
    return {}


def _recommendations_from_yahoo(history: list[dict[str, Any]], source_url: str | None) -> list[dict[str, Any]]:
    recommendations = []
    for item in history[:10]:
        firm = _raw_value(item.get("firm"))
        to_grade = _raw_value(item.get("toGrade"))
        epoch = _as_int(_raw_value(item.get("epochGradeDate")))
        date = None
        if epoch:
            from datetime import UTC, datetime

            date = datetime.fromtimestamp(epoch, tz=UTC).date().isoformat()
        recommendations.append(
            {"firm": firm, "rating": _normalize_consensus(to_grade), "target_price": None, "date": date, "source_url": source_url, "raw": item}
        )
    return recommendations


def _raw_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "raw" in value:
            return value.get("raw")
        if "fmt" in value:
            return value.get("fmt")
    return value


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return parse_numeric(value)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        numeric = parse_numeric(value)
        return None if numeric is None else int(numeric)


def _date_from_iso(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if "T" not in text:
        return text[:10]
    return text.split("T", maxsplit=1)[0]


def _average(values: list[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _first_recommendation_rating(recommendations: list[dict[str, Any]]) -> str | None:
    return next((item.get("rating") for item in recommendations if item.get("rating")), None)


def _normalize_consensus(value: Any) -> str | None:
    if value is None:
        return None
    text = _clean_text(str(value)).strip(" :;-")
    text = re.split(r"\b(?:pre[cç]o|alvo|atualizado|publicado|data)\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = text.strip(" :;-")
    mapping = {
        "strong_buy": "Compra forte",
        "strong buy": "Compra forte",
        "buy": "Compra",
        "compra": "Compra",
        "outperform": "Compra",
        "neutral": "Neutro",
        "neutro": "Neutro",
        "hold": "Manter",
        "manter": "Manter",
        "underperform": "Venda",
        "sell": "Venda",
        "venda": "Venda",
        "strong_sell": "Venda forte",
        "strong sell": "Venda forte",
    }
    lowered = text.lower().replace("-", " ").replace("_", " ")
    if lowered in mapping:
        return mapping[lowered]
    for token, normalized in [
        ("compra forte", "Compra forte"),
        ("strong buy", "Compra forte"),
        ("compra", "Compra"),
        ("buy", "Compra"),
        ("outperform", "Compra"),
        ("neutro", "Neutro"),
        ("neutral", "Neutro"),
        ("manter", "Manter"),
        ("hold", "Manter"),
        ("venda forte", "Venda forte"),
        ("strong sell", "Venda forte"),
        ("venda", "Venda"),
        ("sell", "Venda"),
    ]:
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            return normalized
    return text.title()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _first_number_match(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return parse_numeric(match.group(1))
    return None


def _first_text_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_text(match.group(1)).strip(" :;-")
    return None


def _extract_target(text: str, labels: list[str]) -> float | None:
    for label in labels:
        match = re.search(label + r"(.{0,160})", text, flags=re.IGNORECASE)
        if match:
            segment = match.group(1)
            currency_match = re.search(
                r"(?:R\$|BRL)\s*([0-9]+(?:[.,][0-9]+)?)|([0-9]+(?:[.,][0-9]+)?)\s*(?:R\$|BRL)",
                segment,
                flags=re.IGNORECASE,
            )
            if currency_match:
                return parse_numeric(currency_match.group(1) or currency_match.group(2))
            numbers = re.findall(r"[0-9]+(?:[.,][0-9]+)?", segment)
            if numbers:
                return parse_numeric(numbers[-1])
    return None


def _extract_recommendation_rows(soup: BeautifulSoup) -> list[dict[str, Any]]:
    rows = []
    for tr in soup.find_all("tr"):
        if not tr.find_all("td"):
            continue
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        joined = " | ".join(cells)
        if not re.search(r"(compra|venda|neutro|manter|buy|sell|hold|preço|target)", joined, flags=re.IGNORECASE):
            continue
        price = _first_price(cells)
        firm = cells[0]
        rating = next(
            (cell for cell in cells if re.search(r"(compra|venda|neutro|manter|buy|sell|hold)", cell, flags=re.IGNORECASE)),
            None,
        )
        date = next((cell for cell in reversed(cells) if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}|\d{4}", cell)), None)
        rows.append({"firm": firm, "rating": _normalize_consensus(rating), "target_price": price, "date": date, "raw": cells})
    return rows[:10]


def _first_price(cells: list[str]) -> float | None:
    for cell in cells:
        if re.search(r"(R\$|BRL|\d+[,.]\d{2})", cell):
            value = parse_numeric(cell)
            if value is not None:
                return value
    return None


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
