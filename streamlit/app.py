"""
Mobi Scanner — Streamlit Dashboard
====================================
Visualização interativa de dados imobiliários.

Lê exclusivamente de marts.* no PostgreSQL.
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Mobi Scanner",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styles ───────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    .kpi-card {
        background: #1e1e2e;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        border: 1px solid #313244;
    }
    .kpi-value { font-size: 2rem; font-weight: bold; color: #cba6f7; }
    .kpi-label { font-size: 0.9rem; color: #a6adc8; margin-top: 4px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Database connection ───────────────────────────────────────────────────────
@st.cache_resource
def get_engine():
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB", "mobi_scanner")
    user = os.getenv("POSTGRES_USER", "mobi")
    pwd  = os.getenv("POSTGRES_PASSWORD", "mobi123")
    url  = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=300)
def load_preco_bairro() -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(
            text("SELECT * FROM marts.preco_bairro ORDER BY preco_m2_medio DESC"),
            conn,
        )


@st.cache_data(ttl=300)
def load_historico() -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(
            text("SELECT * FROM marts.historico_preco ORDER BY data_ref"),
            conn,
        )


@st.cache_data(ttl=300)
def load_listings(filters: dict) -> pd.DataFrame:
    conditions = ["1=1"]
    params: dict = {}

    if filters.get("cidade"):
        conditions.append("cidade = :cidade")
        params["cidade"] = filters["cidade"]
    if filters.get("bairro"):
        conditions.append("bairro = :bairro")
        params["bairro"] = filters["bairro"]
    if filters.get("quartos_min"):
        conditions.append("quartos >= :quartos_min")
        params["quartos_min"] = filters["quartos_min"]
    if filters.get("preco_min"):
        conditions.append("preco >= :preco_min")
        params["preco_min"] = filters["preco_min"]
    if filters.get("preco_max"):
        conditions.append("preco <= :preco_max")
        params["preco_max"] = filters["preco_max"]
    if filters.get("area_min"):
        conditions.append("area_m2 >= :area_min")
        params["area_min"] = filters["area_min"]
    if filters.get("area_max"):
        conditions.append("area_m2 <= :area_max")
        params["area_max"] = filters["area_max"]

    where = " AND ".join(conditions)
    sql = text(f"""
        SELECT id, titulo, preco, area_m2, preco_m2, quartos, vagas,
               bairro, cidade, portal, data_coleta, url
        FROM staging.stg_apartamentos
        WHERE {where}
        ORDER BY preco_m2
        LIMIT 2000
    """)
    with get_engine().connect() as conn:
        return pd.read_sql(sql, conn, params=params)


# ── Load data ─────────────────────────────────────────────────────────────────
try:
    df_bairro   = load_preco_bairro()
    df_historico = load_historico()
    data_ok = True
except Exception as exc:
    data_ok = False
    error_msg = str(exc)

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🏢 Mobi Scanner")
st.caption("Inteligência imobiliária em tempo real — apartamentos à venda")

if not data_ok:
    st.error(
        f"Não foi possível conectar ao banco de dados.\n\n"
        f"Execute o pipeline primeiro: `docker compose up scraper` seguido de `dbt run`.\n\n"
        f"Erro: `{error_msg}`"
    )
    st.stop()

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filtros")

    cidades = sorted(df_bairro["cidade"].dropna().unique().tolist())
    cidade_sel = st.selectbox("Cidade", options=["Todas"] + cidades)

    bairros_disponiveis = (
        sorted(df_bairro[df_bairro["cidade"] == cidade_sel]["bairro"].unique().tolist())
        if cidade_sel != "Todas"
        else sorted(df_bairro["bairro"].dropna().unique().tolist())
    )
    bairro_sel = st.selectbox("Bairro", options=["Todos"] + bairros_disponiveis)

    quartos_min = st.slider("Mínimo de quartos", 1, 5, 1)

    col1, col2 = st.columns(2)
    preco_min = col1.number_input("Preço mín (R$)", value=200_000, step=50_000)
    preco_max = col2.number_input("Preço máx (R$)", value=3_000_000, step=100_000)

    col3, col4 = st.columns(2)
    area_min = col3.number_input("Área mín (m²)", value=30, step=10)
    area_max = col4.number_input("Área máx (m²)", value=500, step=20)

    st.divider()
    if st.button("Atualizar dados", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── Apply filters ─────────────────────────────────────────────────────────────
filters = {
    "cidade":     None if cidade_sel == "Todas" else cidade_sel,
    "bairro":     None if bairro_sel == "Todos" else bairro_sel,
    "quartos_min": quartos_min,
    "preco_min":   preco_min,
    "preco_max":   preco_max,
    "area_min":    area_min,
    "area_max":    area_max,
}

df_listings = load_listings(filters)

# Filter bairro summary for selected city
df_bairro_filtered = df_bairro.copy()
if cidade_sel != "Todas":
    df_bairro_filtered = df_bairro_filtered[df_bairro_filtered["cidade"] == cidade_sel]
if bairro_sel != "Todos":
    df_bairro_filtered = df_bairro_filtered[df_bairro_filtered["bairro"] == bairro_sel]

df_hist_filtered = df_historico.copy()
if cidade_sel != "Todas":
    df_hist_filtered = df_hist_filtered[df_hist_filtered["cidade"] == cidade_sel]

# ── KPI Cards ─────────────────────────────────────────────────────────────────
st.subheader("Resumo do mercado")
k1, k2, k3, k4, k5 = st.columns(5)

total    = len(df_listings)
preco_avg = df_listings["preco"].mean() if total else 0
m2_avg   = df_listings["preco_m2"].mean() if total else 0
preco_min_val = df_listings["preco"].min() if total else 0
preco_max_val = df_listings["preco"].max() if total else 0


def fmt_brl(v: float) -> str:
    if v >= 1_000_000:
        return f"R$ {v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"R$ {v/1_000:.0f}k"
    return f"R$ {v:.0f}"


k1.metric("Anúncios encontrados", f"{total:,}".replace(",", "."))
k2.metric("Preço médio",          fmt_brl(preco_avg))
k3.metric("Preço/m² médio",       f"R$ {m2_avg:,.0f}/m²".replace(",", "."))
k4.metric("Menor preço",          fmt_brl(preco_min_val))
k5.metric("Maior preço",          fmt_brl(preco_max_val))

st.divider()

# ── Charts row ────────────────────────────────────────────────────────────────
col_bar, col_ts = st.columns([1.2, 1])

with col_bar:
    st.subheader("Preço/m² por bairro")
    if df_bairro_filtered.empty:
        st.info("Nenhum dado disponível para os filtros selecionados.")
    else:
        top_n = df_bairro_filtered.nlargest(20, "preco_m2_medio")
        fig_bar = px.bar(
            top_n,
            x="preco_m2_medio",
            y="bairro",
            orientation="h",
            color="preco_m2_medio",
            color_continuous_scale="Purpor",
            labels={"preco_m2_medio": "R$/m²", "bairro": "Bairro"},
            text_auto=".0f",
        )
        fig_bar.update_layout(
            showlegend=False,
            coloraxis_showscale=False,
            margin=dict(l=0, r=0, t=0, b=0),
            height=420,
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

with col_ts:
    st.subheader("Evolução do preço médio")
    if df_hist_filtered.empty or len(df_hist_filtered) < 2:
        st.info("Histórico insuficiente para exibir série temporal.")
    else:
        fig_ts = px.line(
            df_hist_filtered,
            x="data_ref",
            y="preco_medio",
            color="cidade",
            labels={"data_ref": "Data", "preco_medio": "Preço médio (R$)", "cidade": "Cidade"},
            markers=True,
        )
        fig_ts.update_layout(
            margin=dict(l=0, r=0, t=0, b=0),
            height=420,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_ts, use_container_width=True)

# ── Bubble chart: preço vs área ───────────────────────────────────────────────
st.subheader("Distribuição: Preço × Área")
if not df_listings.empty:
    sample = df_listings.sample(min(500, len(df_listings)), random_state=42)
    fig_scatter = px.scatter(
        sample,
        x="area_m2",
        y="preco",
        color="bairro",
        size="quartos",
        hover_data=["titulo", "preco_m2", "vagas", "portal"],
        labels={"area_m2": "Área (m²)", "preco": "Preço (R$)"},
        opacity=0.7,
        height=450,
    )
    fig_scatter.update_layout(
        showlegend=True,
        legend=dict(orientation="v", x=1.01),
        margin=dict(l=0, r=0, t=0, b=0),
    )
    st.plotly_chart(fig_scatter, use_container_width=True)

# ── Data table ────────────────────────────────────────────────────────────────
st.subheader("Anúncios")
if df_listings.empty:
    st.info("Nenhum anúncio encontrado com os filtros atuais.")
else:
    display_cols = ["titulo", "preco", "area_m2", "preco_m2", "quartos", "vagas", "bairro", "cidade", "portal", "data_coleta"]
    df_display = df_listings[display_cols].copy()
    df_display.columns = ["Título", "Preço (R$)", "Área (m²)", "R$/m²", "Quartos", "Vagas", "Bairro", "Cidade", "Portal", "Data"]

    st.dataframe(
        df_display,
        use_container_width=True,
        height=400,
        column_config={
            "Preço (R$)": st.column_config.NumberColumn(format="R$ {:,.0f}"),
            "R$/m²":      st.column_config.NumberColumn(format="R$ {:,.0f}/m²"),
            "Área (m²)":  st.column_config.NumberColumn(format="{:.1f} m²"),
        },
    )

    csv = df_listings.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Exportar CSV",
        data=csv,
        file_name="mobi_scanner_export.csv",
        mime="text/csv",
    )

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption("Mobi Scanner | Dados de marts.preco_bairro e marts.historico_preco | Pipeline: Scraper → DBT → Streamlit")
