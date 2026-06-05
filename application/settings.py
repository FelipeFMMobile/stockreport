from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
SITE_RAW_ROOT = DATA_ROOT / "site" / "raw"
MODEL_EXPORT_ROOT = PROJECT_ROOT / "reports" / "model_export" / "stock_variation_classifier"
MODEL_PATH = MODEL_EXPORT_ROOT / "model.joblib"
FEATURE_CONTRACT_PATH = MODEL_EXPORT_ROOT / "feature_contract.json"

INVESTING_SLUGS = {
    "ABEV3": "ambev-pn",
    "B3SA3": "b3-on-nm",
    "BBAS3": "brasil-on",
    "BBDC3": "bradesco-on",
    "BBDC4": "bradesco-pn",
    "BBSE3": "bb-seguridade-on",
    "BPAC11": "btgp-banco-unit",
    "BRAP4": "bradespar-pn",
    "BRFS3": "brf-sa",
    "BRKM5": "braskem-pna",
    "CCRO3": "ccr-sa",
    "CMIG4": "cemig-pn",
    "CMIN3": "csn-mineracao-on",
    "CSAN3": "cosan-on",
    "CSNA3": "sid-nacional-on",
    "CYRE3": "cyrela-realt-on",
    "ELET3": "eletrobras-on",
    "ELET6": "eletrobras-pnb",
    "EMBR3": "embraer-on",
    "ENEV3": "eneva-on",
    "EQTL3": "equatorial-energia-on",
    "GGBR4": "gerdau-pn",
    "HAPV3": "hapvida-on",
    "ITSA4": "itausa-pn",
    "ITUB4": "itauunibanco-pn",
    "JBSS3": "jbs-on",
    "KLBN11": "klabin-sa-unit",
    "LREN3": "lojas-renner-on",
    "MGLU3": "magaz-luiza-on",
    "PETR3": "petrobras-on",
    "PETR4": "petrobras-pn",
    "PRIO3": "prio-sa",
    "RADL3": "raiadrogasil-on",
    "RAIL3": "rumo-log-on",
    "RENT3": "localiza-on",
    "SANB11": "santander-br-unit",
    "SBSP3": "sabesp-on",
    "SUZB3": "suzano-papel-e-celulose-sa",
    "TIMS3": "tim-participacoes-on-nm",
    "UGPA3": "ultrapar-on",
    "VALE3": "vale-on",
    "VBBR3": "vibra-energia-on",
    "WEGE3": "weg-on",
}

