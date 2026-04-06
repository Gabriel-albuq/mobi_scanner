"""
Mobi Scanner — Airflow DAG
==========================
Pipeline completo: scrape → dbt run → dbt test

Schedules:
  - Execução diária às 06:00 (horário de Brasília / UTC-3)

Operadores:
  - BashOperator  : executa o scraper Python e os comandos DBT
  - PythonOperator: verifica saúde do banco antes de iniciar
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_ARGS = {
    "owner": "mobi",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

# ── Env vars passados para todos os BashOperators ─────────────────────────────
PG_ENV = {
    "POSTGRES_HOST": os.getenv("POSTGRES_HOST", "postgres"),
    "POSTGRES_PORT": os.getenv("POSTGRES_PORT", "5432"),
    "POSTGRES_DB": os.getenv("POSTGRES_DB", "mobi_scanner"),
    "POSTGRES_USER": os.getenv("POSTGRES_USER", "mobi"),
    "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD", "mobi123"),
    "SCRAPER_MODE": os.getenv("SCRAPER_MODE", "demo"),
}

DBT_DIR = "/opt/airflow/dbt"
SCRAPER_SCRIPT = "/opt/airflow/scraper/scraper.py"


# ── Health check ──────────────────────────────────────────────────────────────
def check_db_connection(**context):  # noqa: ANN001
    import psycopg2  # noqa: PLC0415

    conn = psycopg2.connect(
        host=PG_ENV["POSTGRES_HOST"],
        port=int(PG_ENV["POSTGRES_PORT"]),
        dbname=PG_ENV["POSTGRES_DB"],
        user=PG_ENV["POSTGRES_USER"],
        password=PG_ENV["POSTGRES_PASSWORD"],
    )
    conn.close()
    print("Conexão com PostgreSQL OK.")


# ── DAG definition ────────────────────────────────────────────────────────────
with DAG(
    dag_id="mobi_scanner_pipeline",
    description="Pipeline completo: scrape → DBT run → DBT test",
    default_args=DEFAULT_ARGS,
    schedule_interval="0 9 * * *",   # 06:00 BRT = 09:00 UTC
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["mobi", "imóveis", "etl"],
) as dag:

    # 1 — Verifica conectividade com o banco
    verify_db = PythonOperator(
        task_id="verify_db_connection",
        python_callable=check_db_connection,
    )

    # 2 — Executa o scraper
    run_scraper = BashOperator(
        task_id="run_scraper",
        bash_command=f"python {SCRAPER_SCRIPT}",
        env=PG_ENV,
    )

    # 3 — Instala dependências DBT (garante que o profile está disponível)
    dbt_deps = BashOperator(
        task_id="dbt_deps",
        bash_command=f"cd {DBT_DIR} && dbt deps --profiles-dir {DBT_DIR}",
        env={**PG_ENV, "DBT_PROFILES_DIR": DBT_DIR},
    )

    # 4 — Executa as transformações DBT
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=(
            f"cd {DBT_DIR} && dbt run "
            f"--profiles-dir {DBT_DIR} "
            f"--project-dir {DBT_DIR} "
            "--target prod"
        ),
        env={**PG_ENV, "DBT_PROFILES_DIR": DBT_DIR},
    )

    # 5 — Executa os testes de qualidade DBT
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=(
            f"cd {DBT_DIR} && dbt test "
            f"--profiles-dir {DBT_DIR} "
            f"--project-dir {DBT_DIR} "
            "--target prod"
        ),
        env={**PG_ENV, "DBT_PROFILES_DIR": DBT_DIR},
    )

    # ── Dependências ──────────────────────────────────────────────────────────
    verify_db >> run_scraper >> dbt_deps >> dbt_run >> dbt_test
