{{
    config(
        materialized='view',
        schema='staging'
    )
}}

/*
  Staging: stg_apartamentos
  --------------------------
  - Normaliza tipos
  - Remove registros sem preço ou área
  - Calcula preço/m²
  - Normaliza bairro e cidade (trim + title case)
  - Filtra outliers extremos (preço < R$50k ou > R$50M, área < 15m² ou > 2000m²)
*/

with source as (
    select * from {{ source('raw', 'apartamentos') }}
),

cleaned as (
    select
        id,
        url,
        trim(titulo)                                            as titulo,

        -- Preço: cast para numeric, descarta nulos
        case
            when preco is null then null
            when preco < 50000 then null    -- outlier baixo
            when preco > 50000000 then null -- outlier alto
            else round(preco::numeric, 2)
        end                                                     as preco,

        -- Área: cast, descarta menores que 15m²
        case
            when area_m2 is null then null
            when area_m2 < 15 then null
            when area_m2 > 2000 then null
            else round(area_m2::numeric, 2)
        end                                                     as area_m2,

        -- Quartos: valores razoáveis entre 1 e 20
        case
            when quartos is null then null
            when quartos < 1 then null
            when quartos > 20 then null
            else quartos::integer
        end                                                     as quartos,

        coalesce(vagas::integer, 0)                             as vagas,

        -- Normalização de texto
        initcap(trim(bairro))                                   as bairro,
        initcap(trim(cidade))                                   as cidade,

        lower(portal)                                           as portal,
        (data_coleta at time zone 'America/Sao_Paulo')::date   as data_coleta

    from source
    where
        url is not null
        and preco is not null
        and preco > 50000
        and area_m2 is not null
        and area_m2 > 15
),

with_metrics as (
    select
        *,
        round(preco / nullif(area_m2, 0), 2) as preco_m2
    from cleaned
)

select * from with_metrics
