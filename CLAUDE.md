# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Mobi Scanner** is a real estate data intelligence platform that scrapes apartment listings from Brazilian property portals (OLX, ZAP Imóveis, Viva Real), processes them through a DBT pipeline, and serves interactive dashboards via Streamlit. The full PRD is at [.llm/prd.md](.llm/prd.md).

## Running the Stack

The entire environment is containerized and must be reproducible with a single command:

```bash
docker compose up
```

Services: `postgres`, `airflow` (via Astro CLI), `scraper`, `streamlit`.

## DBT Commands

```bash
dbt run          # execute transformations
dbt test         # run data quality checks
dbt compile      # check syntax without running
```

## Architecture

Data flows in one direction through four layers:

1. **Scraper (Python)** — Playwright or Scrapy crawls portals and loads raw records into `raw.apartamentos` in PostgreSQL. Must deduplicate by URL/ID and respect rate limits.

2. **Airflow DAGs** — Orchestrate the full pipeline: `scrape → load → dbt run → dbt test`. Uses Astro CLI with Docker.

3. **DBT transformations** — Three schema layers in PostgreSQL:
   - `raw` — verbatim scraper output
   - `staging` — type normalization, address parsing, deduplication
   - `marts` — aggregations (`marts.preco_bairro`: avg price/m² by neighborhood, `marts.historico_preco`: time series)

4. **Streamlit dashboard** — Reads exclusively from `marts.*` tables. Provides map, KPI cards, filterable table, and time-series chart.

## Key Data Model

`raw.apartamentos`: `id (UUID)`, `url`, `titulo`, `preco`, `area_m2`, `quartos`, `vagas`, `bairro`, `cidade`, `data_coleta`.

`marts.preco_bairro`: `bairro`, `preco_medio`, `preco_m2_medio`, `total_anuncios`, `data_ref`.

## Non-Functional Requirements

- Pipeline must be **idempotent** — re-running must not create duplicates
- DBT models must have `not_null`, `unique`, and `accepted_values` tests on key fields
- Scraper must simulate human behavior and respect portal rate limits
- Tech stack: Python 3.11+, PostgreSQL, Apache Airflow (Astro), DBT Core, Streamlit, Docker Compose
