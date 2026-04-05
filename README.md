# Mobi Scanner

Plataforma de inteligência imobiliária que coleta, processa e visualiza dados de apartamentos à venda em portais brasileiros.

## Stack

| Componente | Tecnologia |
|---|---|
| Scraping | Python 3.11 + requests + BeautifulSoup |
| Orquestração | Apache Airflow 2.9 |
| Transformação | DBT Core 1.8 |
| Banco de Dados | PostgreSQL 15 |
| Dashboard | Streamlit 1.35 |
| Containerização | Docker Compose |

## Início Rápido

```bash
# 1. Copie o .env
cp .env.example .env

# 2. Suba toda a stack
docker compose up

# URLs disponíveis após a inicialização:
# Dashboard  → http://localhost:8501
# Airflow UI → http://localhost:8080  (admin / admin)
```

## Modos do Scraper

| `SCRAPER_MODE` | Comportamento |
|---|---|
| `demo` (padrão) | Gera 300 anúncios sintéticos realistas — sem internet |
| `olx` | Raspa OLX Brasil (requer conectividade) |

## Pipeline Manual

```bash
# Executar scraper uma vez
docker compose run --rm scraper

# Executar DBT manualmente (dentro do container Airflow)
docker compose exec airflow-scheduler bash
dbt run --profiles-dir /opt/airflow/dbt --project-dir /opt/airflow/dbt
dbt test --profiles-dir /opt/airflow/dbt --project-dir /opt/airflow/dbt
```

## Arquitetura de Dados

```
raw.apartamentos          (scraper → insert)
       ↓
staging.stg_apartamentos  (DBT view — limpeza e normalização)
       ↓
marts.preco_bairro        (DBT table — preço médio por bairro)
marts.historico_preco     (DBT table — série temporal diária)
       ↓
Streamlit Dashboard
```

## DAG Airflow

`mobi_scanner_pipeline` — executa diariamente às 06:00 BRT:

```
verify_db → run_scraper → dbt_deps → dbt_run → dbt_test
```
