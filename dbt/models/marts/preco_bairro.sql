{{
    config(
        materialized='table',
        schema='marts'
    )
}}

/*
  Mart: preco_bairro
  ------------------
  Agrega métricas de preço por bairro + cidade, para a data mais recente
  de coleta disponível em cada bairro.

  Usado pelo dashboard Streamlit para:
  - Mapa de calor de preço/m² por bairro
  - Ranking de bairros mais caros/baratos
  - KPI cards
*/

with base as (
    select
        bairro,
        cidade,
        preco,
        preco_m2,
        data_coleta
    from {{ ref('stg_apartamentos') }}
    where
        bairro is not null
        and bairro != ''
        and cidade is not null
        and cidade != ''
),

-- Data mais recente por bairro
latest_date as (
    select
        bairro,
        cidade,
        max(data_coleta) as data_ref
    from base
    group by bairro, cidade
),

aggregated as (
    select
        b.bairro,
        b.cidade,
        round(avg(b.preco), 2)      as preco_medio,
        round(avg(b.preco_m2), 2)   as preco_m2_medio,
        round(min(b.preco), 2)      as preco_minimo,
        round(max(b.preco), 2)      as preco_maximo,
        count(*)::integer           as total_anuncios,
        ld.data_ref
    from base b
    inner join latest_date ld
        on b.bairro = ld.bairro
        and b.cidade = ld.cidade
    group by b.bairro, b.cidade, ld.data_ref
)

select * from aggregated
order by cidade, preco_m2_medio desc
