from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class DadosDeMercadoError(RuntimeError):
    """Base error for Dados de Mercado API failures."""


class AuthenticationError(DadosDeMercadoError):
    """Raised when the API token is invalid or lacks permissions."""


@dataclass(frozen=True)
class DadosDeMercadoClient:
    token: str
    base_url: str = "https://api.dadosdemercado.com.br/v1"
    timeout: int = 30
    max_retries: int = 3
    backoff_seconds: float = 2.0

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self.token}"}

        for attempt in range(self.max_retries + 1):
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout)

            if response.status_code == 200:
                return response.json()

            if response.status_code in {401, 403}:
                raise AuthenticationError(
                    f"API request failed with {response.status_code}. "
                    "Check DDM_API_TOKEN and account permissions."
                )

            if response.status_code == 429 and attempt < self.max_retries:
                sleep_for = self.backoff_seconds * (attempt + 1)
                LOGGER.warning("Rate limit reached for %s. Retrying in %.1fs.", url, sleep_for)
                time.sleep(sleep_for)
                continue

            if response.status_code >= 500 and attempt < self.max_retries:
                sleep_for = self.backoff_seconds * (attempt + 1)
                LOGGER.warning("Server error %s for %s. Retrying in %.1fs.", response.status_code, url, sleep_for)
                time.sleep(sleep_for)
                continue

            raise DadosDeMercadoError(
                f"API request failed with {response.status_code} for {url}: {response.text}"
            )

        raise DadosDeMercadoError(f"API request failed after retries for {url}")

    def companies(self) -> list[dict[str, Any]]:
        return self._as_list(self.get("/companies"))

    def balances(self, cvm_code: int, statement_type: str) -> list[dict[str, Any]]:
        return self._as_list(
            self.get(f"/companies/{cvm_code}/balances", params={"statement_type": statement_type})
        )

    def incomes(self, cvm_code: int, statement_type: str, period_type: str = "ttm") -> list[dict[str, Any]]:
        return self._as_list(
            self.get(
                f"/companies/{cvm_code}/incomes",
                params={"statement_type": statement_type, "period_type": period_type},
            )
        )

    def cash_flows(self, cvm_code: int, statement_type: str, period_type: str = "ttm") -> list[dict[str, Any]]:
        return self._as_list(
            self.get(
                f"/companies/{cvm_code}/cash_flows",
                params={"statement_type": statement_type, "period_type": period_type},
            )
        )

    def ratios(self, cvm_code: int, statement_type: str, period_type: str = "ttm") -> list[dict[str, Any]]:
        return self._as_list(
            self.get(
                f"/companies/{cvm_code}/ratios",
                params={"statement_type": statement_type, "period_type": period_type},
            )
        )

    def shares(self, cvm_code: int) -> dict[str, Any] | None:
        payload = self.get(f"/companies/{cvm_code}/shares")
        return payload if isinstance(payload, dict) else None

    def tickers(self, cvm_code: int) -> list[dict[str, Any]]:
        return self._as_list(self.get(f"/companies/{cvm_code}/tickers"))

    @staticmethod
    def _as_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        return []
