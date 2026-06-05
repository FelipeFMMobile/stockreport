from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from .api import DadosDeMercadoClient
from .dataset import build_dataset, require_token
from .site_dataset import SiteDadosDeMercadoClient, build_site_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build B3 financial datasets from Dados de Mercado.")
    parser.add_argument(
        "--source",
        choices=["api", "site"],
        default="api",
        help="Data source to collect. Defaults to api.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Base output directory. Defaults to ./data.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Pause between different cvm_code values. Defaults to 1 second.",
    )
    parser.add_argument(
        "--ticker-limit",
        type=int,
        default=None,
        help="Limit the number of tickers collected when --source site is used. Useful for smoke tests.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

    if args.source == "site":
        client = SiteDadosDeMercadoClient()
        paths = build_site_dataset(
            client=client,
            output_dir=args.output_dir,
            sleep_seconds=args.sleep_seconds,
            ticker_limit=args.ticker_limit,
        )
    else:
        client = DadosDeMercadoClient(token=require_token(os.getenv("DDM_API_TOKEN")))
        paths = build_dataset(client=client, output_dir=args.output_dir, sleep_seconds=args.sleep_seconds)

    for name, path in paths.items():
        logging.info("Wrote %s dataset to %s", name, path)
