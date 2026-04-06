-- =============================================================
-- Mobi Scanner — PostgreSQL Initialization
-- Creates schemas and the raw layer table
-- =============================================================

-- ── Schemas ──────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;

-- ── Raw layer ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raw.apartamentos (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url         TEXT NOT NULL,
    titulo      TEXT,
    preco       NUMERIC(15, 2),
    area_m2     NUMERIC(10, 2),
    quartos     INTEGER,
    vagas       INTEGER,
    bairro      TEXT,
    cidade      TEXT,
    portal      TEXT,           -- 'olx' | 'zap' | 'vivareal' | 'demo'
    data_coleta TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT apartamentos_url_unique UNIQUE (url)
);

-- Index for common filter patterns
CREATE INDEX IF NOT EXISTS idx_apartamentos_cidade   ON raw.apartamentos (cidade);
CREATE INDEX IF NOT EXISTS idx_apartamentos_bairro   ON raw.apartamentos (bairro);
CREATE INDEX IF NOT EXISTS idx_apartamentos_data     ON raw.apartamentos (data_coleta);
CREATE INDEX IF NOT EXISTS idx_apartamentos_preco    ON raw.apartamentos (preco);

-- ── Staging layer (populated by DBT) ─────────────────────────
-- DBT will CREATE OR REPLACE these; we pre-create them so
-- Streamlit and other readers never see a "table not found" error.

CREATE TABLE IF NOT EXISTS staging.stg_apartamentos (
    id          UUID,
    url         TEXT,
    titulo      TEXT,
    preco       NUMERIC(15, 2),
    area_m2     NUMERIC(10, 2),
    preco_m2    NUMERIC(15, 2),
    quartos     INTEGER,
    vagas       INTEGER,
    bairro      TEXT,
    cidade      TEXT,
    portal      TEXT,
    data_coleta DATE
);

-- ── Marts layer (populated by DBT) ───────────────────────────
CREATE TABLE IF NOT EXISTS marts.preco_bairro (
    bairro          TEXT,
    cidade          TEXT,
    preco_medio     NUMERIC(15, 2),
    preco_m2_medio  NUMERIC(15, 2),
    total_anuncios  INTEGER,
    data_ref        DATE
);

CREATE TABLE IF NOT EXISTS marts.historico_preco (
    data_ref        DATE,
    cidade          TEXT,
    preco_medio     NUMERIC(15, 2),
    preco_m2_medio  NUMERIC(15, 2),
    total_anuncios  INTEGER
);

-- ── Grants ───────────────────────────────────────────────────
GRANT ALL ON SCHEMA raw     TO PUBLIC;
GRANT ALL ON SCHEMA staging TO PUBLIC;
GRANT ALL ON SCHEMA marts   TO PUBLIC;
GRANT ALL ON ALL TABLES IN SCHEMA raw     TO PUBLIC;
GRANT ALL ON ALL TABLES IN SCHEMA staging TO PUBLIC;
GRANT ALL ON ALL TABLES IN SCHEMA marts   TO PUBLIC;
