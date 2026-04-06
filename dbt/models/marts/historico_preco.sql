{{
    config(
        materialized='table',
        schema='marts'
    )
}}

/*
  Mart: historico_preco
  ----------------------
  Série temporal diária do preço médio por cidade.
  Usado pelo gráfico de evolução de preços no dashboard.
*/

with base as (
    select
        data_coleta as data_ref,
        cidade,
        preco,
        preco_m2
    from {{ ref('stg_apartamentos') }}
    where
        cidade is not null
        and cidade != ''
),

daily as (
    select
        data_ref,
        cidade,
        round(avg(preco), 2)      as preco_medio,
        round(avg(preco_m2), 2)   as preco_m2_medio,
        count(*)::integer         as total_anuncios
    from base
    group by data_ref, cidade
)

select * from daily
order by data_ref, cidade
