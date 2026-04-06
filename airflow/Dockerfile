FROM apache/airflow:2.9.2-python3.11

USER root

# Instala libpq-dev (headers do PostgreSQL para compilar psycopg2)
# e build-essential (gcc + headers da libc padrão como stdlib.h)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Instala todos os pacotes extras em tempo de build,
# não em tempo de execução — mais rápido e mais confiável
RUN pip install --no-cache-dir \
    psycopg2-binary==2.9.9 \
    "dbt-postgres==1.8.0" \
    requests==2.31.0 \
    beautifulsoup4==4.12.3 \
    lxml==5.2.2
