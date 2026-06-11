# StockReport

Aplicacao para estimar preco-alvo de acoes da bolsa brasileira com base em um modelo treinado sobre series historicas da variacao dos papeis apos balancos e resultados trimestrais.

<img width="740" height="860" alt="Captura de Tela 2026-06-09 às 17 35 18" src="https://github.com/user-attachments/assets/0be9603a-bfc2-4172-8d73-697506b2c048" />

## Visao geral

O StockReport consulta tickers da B3, exibe a cotacao atual, monta fundamentos financeiros a partir da base local e executa um modelo de classificacao para projetar uma faixa de retorno esperada. A partir dessa classificacao, a aplicacao calcula um preco-alvo de 12 meses e compara o resultado com fontes publicas de recomendacao quando disponiveis.

## Aplicacao web local

A aplicacao em `application/` roda localmente e combina interface web com API para analise de tickers.

A aplicacao roda em um unico processo:

- FastAPI atende as rotas `GET/POST /api/*`.
- Flask atende a interface web em `/`.

### Configurar ambiente

Crie e ative um ambiente virtual, depois instale o projeto com as dependencias de desenvolvimento:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Variaveis opcionais:

- `STOCKREPORT_ENABLE_INVESTING=1`: habilita o fallback legado do Investing.com. Por padrao fica desativado porque a fonte costuma retornar bloqueios `403`.

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

## Author 
Felipe Menezes, SÊnior iOS and Mobile Developer, Software Enginieer
[![Swift](https://img.shields.io/badge/Linkedin-profile-blue)](https://www.linkedin.com/in/felipe-menezes-dev)
