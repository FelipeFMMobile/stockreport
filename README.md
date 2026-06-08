# StockReport

Aplicacao para estimar preco-alvo de acoes da bolsa brasileira com base em um modelo treinado sobre series historicas da variacao dos papeis apos balancos e resultados trimestrais.

## Visao geral

O StockReport consulta tickers da B3, exibe a cotacao atual, monta fundamentos financeiros a partir da base local e executa um modelo de classificacao para projetar uma faixa de retorno esperada. A partir dessa classificacao, a aplicacao calcula um preco-alvo de 12 meses e compara o resultado com fontes publicas de recomendacao quando disponiveis.

## Aplicacao web local

A aplicacao em `application/` roda localmente e combina interface web com API para analise de tickers.

A aplicacao roda em um unico processo:

- FastAPI atende as rotas `GET/POST /api/*`.
- Flask atende a interface web em `/`.

### Requisitos da aplicacao

Antes de executar a aplicacao, confirme que estes arquivos existem:

- `data/site/raw/{TICKER}/indicadores.csv`
- `data/site/raw/{TICKER}/balancos.csv`
- `data/site/raw/{TICKER}/resultados.csv`
- `reports/model_export/stock_variation_classifier/model.joblib`
- `reports/model_export/stock_variation_classifier/feature_contract.json`

Os CSVs por ticker podem ser gerados com:

```bash
stock-report --source site
```

O modelo exportado e o contrato de features sao usados pela rota de analise. A aplicacao monta as features a partir do ultimo trimestre disponivel na base local e envia exatamente as colunas definidas em `feature_contract.json`.

### Configurar ambiente

Crie e ative um ambiente virtual, depois instale o projeto com as dependencias de desenvolvimento:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Variaveis opcionais:

- `BRAPI_TOKEN`: habilita a consulta agregada da brapi para preco-alvo, consenso e numero de analistas.
- `STOCKREPORT_ENABLE_INVESTING=1`: habilita o fallback legado do Investing.com. Por padrao fica desativado porque a fonte costuma retornar bloqueios `403`.

Exemplo:

```bash
export BRAPI_TOKEN="seu_token_brapi"
```

### Executar aplicacao

Para teste local com recarregamento automatico:

```bash
uvicorn application.main:app --host 127.0.0.1 --port 8000 --reload
```

Se estiver usando o binario do ambiente virtual:

```bash
.venv/bin/python -m uvicorn application.main:app --host 127.0.0.1 --port 8000 --reload
```

Abra no navegador:

```text
http://127.0.0.1:8000
```

### APIs disponiveis

#### `GET /api/health`

Verifica se a API esta no ar.

```bash
curl http://127.0.0.1:8000/api/health
```

Resposta esperada:

```json
{"status": "ok"}
```

#### `GET /api/quote/{ticker}`

Consulta cotacao atual do ticker pela API de chart do Yahoo Finance.

Exemplo:

```bash
curl http://127.0.0.1:8000/api/quote/PETR4
```

Campos principais da resposta:

- `ticker`
- `yahoo_symbol`
- `name`
- `current_price`
- `currency`
- `updated_at`
- `previous_close`
- `change_value`
- `change_pct`
- `status`

#### `GET /api/fundamentals/{ticker}`

Le a base local em `data/site/raw/{TICKER}`, identifica o ultimo trimestre disponivel e monta os fundamentos usados pelo modelo.

Exemplo:

```bash
curl http://127.0.0.1:8000/api/fundamentals/PETR4
```

Campos principais da resposta:

- `ticker`
- `period`
- `features`
- `raw_values`
- `missing_features`
- `source_dir`

#### `POST /api/analysis/{ticker}`

Executa a analise de alvo do ticker. A rota monta os fundamentos, carrega `model.joblib`, prediz a classe `NH/N/S/P/PH`, calcula probabilidades quando o modelo suporta `predict_proba` e calcula o preco-alvo de 12 meses.

Exemplo:

```bash
curl -X POST http://127.0.0.1:8000/api/analysis/PETR4
```

Campos principais da resposta:

- `ticker`
- `period`
- `predicted_class`
- `predicted_class_meaning`
- `probabilities`
- `target_price_12m`
- `target_return_pct`
- `target_base_price`
- `prediction_status`
- `feature_missing_count`
- `missing_features`
- `current_price`
- `price_currency`
- `model_name`
- `fundamentals`

A regra de preco-alvo usa o fechamento do ultimo trimestre (`price_end_close`) e o limite superior da classe prevista:

- `NH`: -10%
- `N`: -3%
- `S`: +3%
- `P`: +10%
- `PH`: +10%

#### `GET /api/broker-targets/{ticker}`

Consulta preco-alvo e recomendacoes de fontes externas. A rota usa um agregador multi-fonte:

1. brapi, quando `BRAPI_TOKEN` esta configurado.
2. Yahoo Finance `quoteSummary`, como fallback agregado.
3. Paginas publicas de corretoras: XP, BB-BI/InvesTalk e BTG Pactual.
4. Investing.com apenas se `STOCKREPORT_ENABLE_INVESTING=1`.

Exemplo:

```bash
curl http://127.0.0.1:8000/api/broker-targets/ITUB4
```

Campos principais da resposta:

- `ticker`
- `source`
- `source_url`
- `consensus`
- `analyst_count`
- `average_target`
- `high_target`
- `low_target`
- `median_target`
- `recommendations`
- `status`
- `warning`
- `sources`

Cada item de `sources` informa o resultado por fonte (`success`, `partial`, `error` ou `unsupported`). Falhas de fontes publicas nao derrubam a API; elas aparecem em `warning` e `sources`.

## Observacoes

- Arquivos temporarios, ambientes virtuais e caches Python sao ignorados pelo Git.
- Dados sensiveis ou credenciais nao devem ser versionados.
