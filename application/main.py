from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware

from .api import api_router
from .web import create_flask_app

app = FastAPI(title="StockReport B3 Analysis", version="0.1.0")
app.include_router(api_router)
app.mount("/", WSGIMiddleware(create_flask_app()))

