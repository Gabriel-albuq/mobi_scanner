#!/bin/bash
# Creates the airflow database and user before the main init.sql runs
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER airflow WITH PASSWORD 'airflow';
    CREATE DATABASE airflow OWNER airflow;
    GRANT ALL PRIVILEGES ON DATABASE airflow TO airflow;
EOSQL
