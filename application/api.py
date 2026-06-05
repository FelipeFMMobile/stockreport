from __future__ import annotations

from fastapi import APIRouter, HTTPException

from stock_report.price_enrichment import YahooFinanceError

from .services.brokers import BrokerTargetAggregatorService
from .services.fundamentals import build_fundamental_snapshot
from .services.prediction import StockPredictionService
from .services.quotes import YahooQuoteService

api_router = APIRouter(prefix="/api")

quote_service = YahooQuoteService()
broker_service = BrokerTargetAggregatorService()
prediction_service = StockPredictionService(price_provider=quote_service)


@api_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api_router.get("/quote/{ticker}")
def quote(ticker: str) -> dict:
    try:
        return quote_service.get_quote(ticker).__dict__
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except YahooFinanceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@api_router.get("/fundamentals/{ticker}")
def fundamentals(ticker: str) -> dict:
    try:
        return build_fundamental_snapshot(ticker, price_provider=quote_service).to_dict()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except YahooFinanceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@api_router.post("/analysis/{ticker}")
def analysis(ticker: str) -> dict:
    try:
        return prediction_service.predict(ticker).to_dict()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (KeyError, ValueError, AssertionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except YahooFinanceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@api_router.get("/broker-targets/{ticker}")
def broker_targets(ticker: str) -> dict:
    try:
        return broker_service.get_targets(ticker).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
