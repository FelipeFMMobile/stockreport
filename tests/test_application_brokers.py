from __future__ import annotations

import json
from pathlib import Path

import requests

from application.services.brokers import (
    BrokerTargetAggregatorService,
    parse_bb_bi_research_html,
    parse_brapi_quote_payload,
    parse_btg_recommendation_payload,
    parse_btg_research_html,
    parse_investing_consensus_html,
    parse_xp_research_html,
    parse_yahoo_quote_summary_payload,
)


class FakeResponse:
    def __init__(self, *, url: str, text: str = "", payload: dict | None = None, status_code: int = 200) -> None:
        self.url = url
        self.text = text
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for {self.url}")


def test_parse_investing_consensus_html_extracts_summary_and_recommendation_rows():
    html = Path("tests/fixtures/investing_consensus_petr4.html").read_text(encoding="utf-8")

    result = parse_investing_consensus_html(html, ticker="PETR4", source_url="https://example.test")

    assert result.status == "success"
    assert result.consensus == "Compra"
    assert result.analyst_count == 11
    assert result.average_target == 52.67
    assert result.high_target == 65.0
    assert result.low_target == 43.0
    assert result.recommendations[0]["firm"] == "BofA"
    assert result.recommendations[0]["target_price"] == 65.0


def test_parse_brapi_quote_payload_extracts_aggregate_targets():
    payload = json.loads(Path("tests/fixtures/brapi_itub4_financial_data.json").read_text(encoding="utf-8"))

    result = parse_brapi_quote_payload(payload, ticker="ITUB4", source_url="https://brapi.test")

    assert result.status == "success"
    assert result.average_target == 39.5
    assert result.high_target == 45.0
    assert result.low_target == 32.0
    assert result.median_target == 40.0
    assert result.consensus == "Compra"
    assert result.analyst_count == 14


def test_parse_yahoo_quote_summary_payload_extracts_financial_data_and_history():
    payload = json.loads(Path("tests/fixtures/yahoo_itub4_quote_summary.json").read_text(encoding="utf-8"))

    result = parse_yahoo_quote_summary_payload(payload, ticker="ITUB4", source_url="https://yahoo.test")

    assert result.status == "success"
    assert result.average_target == 38.2
    assert result.median_target == 38.5
    assert result.consensus == "Manter"
    assert result.analyst_count == 11
    assert result.recommendations[0]["firm"] == "Morgan Stanley"


def test_public_broker_scrapers_extract_recommendation_rows():
    xp = parse_xp_research_html(Path("tests/fixtures/xp_itub4.html").read_text(encoding="utf-8"), "ITUB4", "https://xp.test")
    bb = parse_bb_bi_research_html(Path("tests/fixtures/bb_bi_itub4.html").read_text(encoding="utf-8"), "ITUB4", "https://bb.test")
    btg = parse_btg_research_html(Path("tests/fixtures/btg_itub4.html").read_text(encoding="utf-8"), "ITUB4", "https://btg.test")

    assert xp.recommendations[0]["firm"] == "XP Investimentos"
    assert xp.recommendations[0]["rating"] == "Compra"
    assert xp.recommendations[0]["target_price"] == 42.0
    assert bb.recommendations[0]["rating"] == "Manter"
    assert bb.recommendations[0]["target_price"] == 37.5
    assert btg.recommendations[0]["rating"] == "Neutro"
    assert btg.recommendations[0]["target_price"] == 39.1


def test_parse_btg_recommendation_payload_extracts_json_endpoint_data():
    payload = json.loads(Path("tests/fixtures/btg_itub4_recommendation.json").read_text(encoding="utf-8"))

    result = parse_btg_recommendation_payload(payload, "ITUB4", "https://btg.test/api")

    assert result.status == "success"
    assert result.recommendations[0]["firm"] == "BTG Pactual"
    assert result.recommendations[0]["rating"] == "Compra"
    assert result.recommendations[0]["target_price"] == 52.0
    assert result.recommendations[0]["date"] == "2026-05-06"
    assert result.recommendations[0]["source_url"].endswith("ITUB4__1T26.pdf")


def test_public_broker_scraper_trims_analyst_text_after_rating():
    html = "<html><body>Recomendação Compra Bernardo Guttmann Head Preço Alvo R$ 51,00 Atualizado em 05/06/2026</body></html>"

    result = parse_xp_research_html(html, "ITUB4", "https://xp.test")

    assert result.recommendations[0]["rating"] == "Compra"
    assert result.recommendations[0]["target_price"] == 51.0


def test_aggregator_uses_brapi_when_token_is_configured_and_keeps_source_statuses():
    brapi_payload = json.loads(Path("tests/fixtures/brapi_itub4_financial_data.json").read_text(encoding="utf-8"))
    xp_html = Path("tests/fixtures/xp_itub4.html").read_text(encoding="utf-8")
    bb_html = Path("tests/fixtures/bb_bi_itub4.html").read_text(encoding="utf-8")
    btg_payload = json.loads(Path("tests/fixtures/btg_itub4_recommendation.json").read_text(encoding="utf-8"))

    def fake_get(url, **kwargs):
        if "brapi.dev" in url:
            return FakeResponse(url=url, payload=brapi_payload)
        if "query2.finance.yahoo.com" in url:
            return FakeResponse(url=url, status_code=403)
        if "conteudos.xpi.com.br" in url:
            return FakeResponse(url=url, text=xp_html)
        if "investalk.bb.com.br" in url:
            return FakeResponse(url=url, text=bb_html)
        if "content.btgpactual.com" in url:
            return FakeResponse(url=url, payload=btg_payload)
        raise AssertionError(url)

    result = BrokerTargetAggregatorService(request_get=fake_get, brapi_token="token").get_targets("ITUB4")

    assert result.source == "brapi"
    assert result.average_target == 39.5
    assert result.median_target == 40.0
    assert len(result.recommendations) == 3
    assert {source.name: source.status for source in result.sources}["Yahoo Finance"] == "error"


def test_aggregator_falls_back_to_yahoo_without_brapi_token():
    yahoo_payload = json.loads(Path("tests/fixtures/yahoo_itub4_quote_summary.json").read_text(encoding="utf-8"))

    def fake_get(url, **kwargs):
        if "query2.finance.yahoo.com" in url:
            return FakeResponse(url=url, payload=yahoo_payload)
        return FakeResponse(url=url, status_code=404)

    result = BrokerTargetAggregatorService(request_get=fake_get, brapi_token=None).get_targets("ITUB4")

    assert result.source == "Yahoo Finance"
    assert result.average_target == 38.2
    assert result.consensus == "Manter"
    assert result.status == "success"


def test_aggregator_handles_blocked_sources_without_breaking_response():
    def fake_get(url, **kwargs):
        return FakeResponse(url=url, status_code=403)

    result = BrokerTargetAggregatorService(request_get=fake_get, brapi_token=None).get_targets("ITUB4")

    assert result.status == "error"
    assert result.average_target is None
    assert result.recommendations == []
    assert all(source.status in {"unsupported", "error"} for source in result.sources)
