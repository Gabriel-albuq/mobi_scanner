# Mobi Scanner — Documentação Completa

> Plataforma de inteligência imobiliária que coleta, processa e visualiza dados de apartamentos à venda em portais brasileiros.

---

## Sumário

1. [O que é o Mobi Scanner](#1-o-que-é-o-mobi-scanner)
2. [Como o projeto funciona](#2-como-o-projeto-funciona)
3. [Arquitetura e serviços](#3-arquitetura-e-serviços)
4. [Modelo de dados](#4-modelo-de-dados)
5. [Pré-requisitos](#5-pré-requisitos)
6. [Configuração inicial](#6-configuração-inicial)
7. [Subindo o projeto](#7-subindo-o-projeto)
8. [Usando o sistema](#8-usando-o-sistema)
9. [Rodando o pipeline manualmente](#9-rodando-o-pipeline-manualmente)
10. [Comandos de debug e manutenção](#10-comandos-de-debug-e-manutenção)
11. [Estrutura de arquivos](#11-estrutura-de-arquivos)
12. [Perguntas frequentes](#12-perguntas-frequentes)

---

## 1. O que é o Mobi Scanner

O Mobi Scanner automatiza todo o processo de coleta e análise do mercado imobiliário:

- **Coleta** anúncios de apartamentos em portais como OLX (ou gera dados sintéticos para testes)
- **Processa** os dados brutos com limpeza, normalização e cálculo de métricas via DBT
- **Visualiza** tudo em um dashboard interativo no Streamlit com mapas, gráficos e filtros

O sistema é completamente containerizado — sobe com um único comando `docker compose up` e não requer nada instalado além do Docker.

---

## 2. Como o projeto funciona

O dado percorre um caminho linear e unidirecional:

```
Scraper (Python)
      │
      │  Grava anúncios brutos
      ▼
PostgreSQL — schema raw
      │
      │  Airflow dispara diariamente
      ▼
DBT — transformações em 3 camadas
      │  raw → staging → marts
      ▼
Streamlit Dashboard
      │  Lê de marts.*
      ▼
Usuário vê os dados no navegador
```

### Fluxo passo a passo

**1. Scraper coleta os dados**

O scraper Python roda no container `mobi_scraper` e grava os anúncios na tabela `raw.apartamentos`. Ele opera em dois modos controlados pela variável de ambiente `SCRAPER_MODE`:

| Modo | Descrição |
|------|-----------|
| `demo` (padrão) | Gera 300 anúncios sintéticos realistas sem precisar de internet. Ideal para testes. |
| `olx` | Raspa anúncios reais do OLX Brasil (São Paulo e Rio de Janeiro). Requer conectividade. |

O scraper é **idempotente**: usa `INSERT ... ON CONFLICT (url) DO NOTHING`, então rodar múltiplas vezes nunca gera duplicatas.

**2. DBT transforma os dados**

O DBT aplica três camadas de transformação no PostgreSQL:

| Camada | Schema | O que faz |
|--------|--------|-----------|
| Fonte | `raw` | Dados brutos do scraper, sem alteração |
| Staging | `staging` | Limpa tipos, remove outliers, calcula preço/m², normaliza texto |
| Marts | `marts` | Agrega por bairro e cria série temporal de preços |

**3. Airflow orquestra tudo**

O DAG `mobi_scanner_pipeline` roda automaticamente todo dia às 06:00 (horário de Brasília) na sequência:

```
verify_db → run_scraper → dbt_deps → dbt_run → dbt_test
```

**4. Streamlit exibe o dashboard**

O dashboard lê exclusivamente das tabelas `marts.*` e exibe:
- KPI cards (total de anúncios, preço médio, preço/m², menor e maior preço)
- Gráfico de barras com ranking de bairros por preço/m²
- Série temporal de evolução do preço médio por cidade
- Scatter plot de Preço × Área colorido por bairro
- Tabela filtrável com todos os anúncios e botão de exportação CSV

---

## 3. Arquitetura e serviços

### Serviços Docker

| Container | Imagem | Porta | Função |
|-----------|--------|-------|--------|
| `mobi_postgres` | postgres:15-alpine | 5432 | Banco de dados principal |
| `airflow_init` | apache/airflow:2.9.2 | — | Inicializa o banco do Airflow (roda uma vez) |
| `airflow_webserver` | apache/airflow:2.9.2 | 8080 | Interface web do Airflow |
| `airflow_scheduler` | apache/airflow:2.9.2 | — | Agendador de DAGs |
| `mobi_scraper` | build local | — | Scraper Python (roda e encerra) |
| `mobi_streamlit` | build local | 8501 | Dashboard Streamlit |

### Ordem de inicialização

O Docker Compose garante a ordem via `depends_on` e `healthcheck`:

```
postgres (healthy)
    ├── airflow-init (completed successfully)
    │       ├── airflow-webserver
    │       └── airflow-scheduler
    ├── scraper
    └── streamlit
```

---

## 4. Modelo de dados

### `raw.apartamentos` — dados brutos

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | UUID | Identificador único gerado automaticamente |
| `url` | TEXT | URL do anúncio (chave de deduplicação) |
| `titulo` | TEXT | Título do anúncio |
| `preco` | NUMERIC(15,2) | Preço em R$ |
| `area_m2` | NUMERIC(10,2) | Área em m² |
| `quartos` | INTEGER | Número de quartos |
| `vagas` | INTEGER | Número de vagas de garagem |
| `bairro` | TEXT | Bairro (texto bruto do portal) |
| `cidade` | TEXT | Cidade |
| `portal` | TEXT | Origem: `olx`, `zap`, `vivareal`, `demo` |
| `data_coleta` | TIMESTAMP TZ | Data e hora da coleta |

### `staging.stg_apartamentos` — dados limpos

Mesmos campos de `raw.apartamentos`, com as seguintes transformações aplicadas:

- Preços fora do intervalo R$50k–R$50M são descartados como outliers
- Áreas fora do intervalo 15m²–2000m² são descartadas
- Quartos inválidos (< 1 ou > 20) são descartados
- Bairro e cidade normalizados com `INITCAP(TRIM(...))`
- Campo extra `preco_m2` calculado como `preco / area_m2`
- `data_coleta` convertida para o fuso de São Paulo

### `marts.preco_bairro` — agregação por bairro

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `bairro` | TEXT | Bairro normalizado |
| `cidade` | TEXT | Cidade |
| `preco_medio` | NUMERIC | Preço médio dos anúncios |
| `preco_m2_medio` | NUMERIC | Preço médio por m² |
| `preco_minimo` | NUMERIC | Menor preço encontrado |
| `preco_maximo` | NUMERIC | Maior preço encontrado |
| `total_anuncios` | INTEGER | Quantidade de anúncios |
| `data_ref` | DATE | Data de referência (mais recente do bairro) |

### `marts.historico_preco` — série temporal

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `data_ref` | DATE | Data de coleta |
| `cidade` | TEXT | Cidade |
| `preco_medio` | NUMERIC | Preço médio do dia |
| `preco_m2_medio` | NUMERIC | Preço/m² médio do dia |
| `total_anuncios` | INTEGER | Anúncios coletados naquele dia |

---

## 5. Pré-requisitos

Instale antes de começar:

| Ferramenta | Versão mínima | Link |
|------------|---------------|------|
| Docker Desktop | 4.x+ | https://www.docker.com/products/docker-desktop |
| Docker Compose | v2 (incluído no Docker Desktop) | — |

**No Windows:** o Docker Desktop requer WSL2 habilitado. Durante a instalação do Docker Desktop, ele solicitará ativar o WSL2 automaticamente.

Verifique se está tudo ok:

```bash
docker --version       # Docker version 25.x.x
docker compose version # Docker Compose version v2.x.x
```

---

## 6. Configuração inicial

### Criar o arquivo `.env`

Na raiz do projeto, crie o arquivo `.env` a partir do exemplo:

```bash
cp .env.example .env
```

Conteúdo do `.env`:

```env
# ── PostgreSQL ────────────────────────────────────────────────
POSTGRES_USER=mobi
POSTGRES_PASSWORD=mobi123
POSTGRES_DB=mobi_scanner

# ── Scraper ───────────────────────────────────────────────────
# demo  → gera 300 anúncios sintéticos (padrão, sem acesso à internet)
# olx   → raspa OLX Brasil (requer conectividade)
SCRAPER_MODE=demo

# ── Airflow ───────────────────────────────────────────────────
AIRFLOW_UID=50000
```

Os valores padrão já funcionam sem nenhuma alteração. O `SCRAPER_MODE=demo` é recomendado para o primeiro uso.

---

## 7. Subindo o projeto

### Primeira execução (build das imagens)

```bash
docker compose up --build
```

O `--build` compila as imagens do scraper e do Streamlit. Nas execuções seguintes não é necessário.

### Execuções seguintes

```bash
docker compose up
```

### Subir em background (sem travar o terminal)

```bash
docker compose up -d
```

### O que acontece durante a inicialização

```
[1] postgres sobe e executa init.sql
        → Cria os schemas: raw, staging, marts
        → Cria as tabelas: raw.apartamentos, staging.stg_apartamentos, marts.*

[2] airflow-init inicializa o banco do Airflow e cria o usuário admin

[3] airflow-webserver e airflow-scheduler sobem
        → Aguarde ~2-3 minutos até o webserver estar disponível

[4] scraper roda e encerra
        → Gera 300 anúncios (modo demo) e grava em raw.apartamentos
        → Idempotente: re-executar não duplica dados

[5] streamlit sobe e fica disponível em localhost:8501
        → OBS: o dashboard exige que dbt run tenha sido executado
           (as tabelas marts.* precisam ter dados)
```

### Verificar se tudo está rodando

```bash
docker compose ps
```

Saída esperada (após inicialização completa):

```
NAME                   STATUS
airflow_scheduler      running
airflow_webserver      running (healthy)
mobi_postgres          running (healthy)
mobi_scraper           exited (0)       ← normal, scraper roda e encerra
mobi_streamlit         running (healthy)
```

---

## 8. Usando o sistema

### Dashboard Streamlit

Acesse: **http://localhost:8501**

Funcionalidades disponíveis:

| Seção | Descrição |
|-------|-----------|
| **KPI Cards** | Total de anúncios, preço médio, preço/m² médio, menor e maior preço |
| **Preço/m² por bairro** | Gráfico de barras com os 20 bairros mais caros |
| **Evolução do preço** | Série temporal por cidade (requer dados de múltiplos dias) |
| **Distribuição Preço × Área** | Scatter plot interativo com hover detalhado |
| **Tabela de anúncios** | Lista filtrável com exportação para CSV |

**Filtros disponíveis na barra lateral:**
- Cidade
- Bairro
- Mínimo de quartos
- Faixa de preço (mín/máx)
- Faixa de área em m² (mín/máx)

O botão **"Atualizar dados"** limpa o cache e recarrega do banco.

> **Nota:** se o dashboard mostrar erro de conexão, é porque o `dbt run` ainda não foi executado e as tabelas `marts.*` estão vazias. Veja a seção abaixo.

### Airflow UI

Acesse: **http://localhost:8080**

- **Usuário:** `admin`
- **Senha:** `admin`

No Airflow você pode:
- Ver o DAG `mobi_scanner_pipeline` e seu histórico de execuções
- Disparar o pipeline manualmente (botão de play)
- Inspecionar os logs de cada tarefa
- Ver quais tasks falharam e re-executar individualmente

---

## 9. Rodando o pipeline manualmente

### Opção A — Via Airflow UI (recomendado)

1. Acesse http://localhost:8080
2. Na lista de DAGs, encontre `mobi_scanner_pipeline`
3. Clique no botão de **play** (Trigger DAG) no canto direito
4. Acompanhe a execução no **Graph View** ou **Grid View**

O pipeline executa as seguintes tasks em sequência:

```
verify_db_connection → run_scraper → dbt_deps → dbt_run → dbt_test
```

### Opção B — Executar cada etapa manualmente via terminal

**Rodar apenas o scraper:**

```bash
docker compose run --rm scraper
```

**Rodar o DBT dentro do container do Airflow:**

```bash
# dbt run (executa as transformações)
docker exec airflow_scheduler bash -c \
  "cd /opt/airflow/dbt && dbt run --profiles-dir /opt/airflow/dbt --target prod"

# dbt test (valida a qualidade dos dados)
docker exec airflow_scheduler bash -c \
  "cd /opt/airflow/dbt && dbt test --profiles-dir /opt/airflow/dbt --target prod"
```

**Sequência completa manual (equivalente ao DAG):**

```bash
# 1. Rodar o scraper
docker compose run --rm scraper

# 2. Executar transformações DBT
docker exec airflow_scheduler bash -c \
  "cd /opt/airflow/dbt && dbt deps --profiles-dir /opt/airflow/dbt && \
   dbt run --profiles-dir /opt/airflow/dbt --target prod"

# 3. Validar dados com testes DBT
docker exec airflow_scheduler bash -c \
  "cd /opt/airflow/dbt && dbt test --profiles-dir /opt/airflow/dbt --target prod"
```

Após executar o `dbt run`, o dashboard Streamlit em http://localhost:8501 já terá dados para exibir.

---

## 10. Comandos de debug e manutenção

### Ver logs de um serviço

```bash
docker compose logs postgres        # logs do banco
docker compose logs scraper         # logs do scraper
docker compose logs streamlit       # logs do dashboard
docker compose logs airflow-webserver
docker compose logs airflow-scheduler
```

Seguir logs em tempo real:

```bash
docker compose logs -f airflow-scheduler
```

### Acessar o banco de dados

```bash
docker exec -it mobi_postgres psql -U mobi -d mobi_scanner
```

Consultas úteis dentro do psql:

```sql
-- Ver quantos anúncios foram coletados
SELECT count(*) FROM raw.apartamentos;

-- Ver anúncios por portal
SELECT portal, count(*) FROM raw.apartamentos GROUP BY portal;

-- Ver dados da staging
SELECT * FROM staging.stg_apartamentos LIMIT 10;

-- Ver resumo por bairro
SELECT * FROM marts.preco_bairro ORDER BY preco_m2_medio DESC LIMIT 20;

-- Ver série histórica
SELECT * FROM marts.historico_preco ORDER BY data_ref DESC;
```

### Rodar o scraper em modo OLX (dados reais)

Edite o `.env` e altere:

```env
SCRAPER_MODE=olx
```

Depois reinicie o scraper:

```bash
docker compose up scraper
```

> O modo OLX raspa até 5 páginas de São Paulo e Rio de Janeiro com rate limiting (2,5–5s entre requisições). Os seletores CSS podem quebrar se o OLX mudar o layout.

### Parar os serviços

```bash
# Para tudo, preserva os dados
docker compose down

# Para tudo e apaga os volumes (banco zerado)
docker compose down -v
```

### Recriar um container específico

```bash
docker compose up -d --force-recreate streamlit
```

### Rebuild de uma imagem específica

```bash
docker compose build scraper
docker compose build streamlit
```

### Verificar saúde dos containers

```bash
docker compose ps
docker inspect mobi_postgres --format='{{.State.Health.Status}}'
```

---

## 11. Estrutura de arquivos

```
mobi_scanner/
│
├── docker-compose.yml          # Orquestração de todos os serviços
├── .env.example                # Template de variáveis de ambiente
├── .env                        # Variáveis locais (não commitar)
│
├── postgres/
│   ├── init.sql                # Cria schemas e tabelas na primeira subida
│   └── create_airflow_db.sh    # Cria o banco do Airflow separado
│
├── scraper/
│   ├── scraper.py              # Scraper Python (modo demo e OLX)
│   ├── requirements.txt        # Dependências Python do scraper
│   └── Dockerfile              # Imagem do container do scraper
│
├── dags/
│   └── pipeline_dag.py         # DAG do Airflow (scrape → dbt run → dbt test)
│
├── dbt/
│   ├── dbt_project.yml         # Configuração do projeto DBT
│   ├── profiles.yml            # Conexão com o PostgreSQL
│   ├── packages.yml            # Pacotes DBT externos
│   └── models/
│       ├── sources.yml         # Declara raw.apartamentos como fonte
│       ├── staging/
│       │   ├── stg_apartamentos.sql   # Limpeza e normalização
│       │   └── schema.yml             # Testes de qualidade (staging)
│       └── marts/
│           ├── preco_bairro.sql       # Agregação por bairro
│           ├── historico_preco.sql    # Série temporal por cidade
│           └── schema.yml             # Testes de qualidade (marts)
│
├── streamlit/
│   ├── app.py                  # Dashboard Streamlit
│   ├── requirements.txt        # Dependências Python do dashboard
│   └── Dockerfile              # Imagem do container do Streamlit
│
└── .llm/
    └── prd.md                  # Product Requirements Document
```

---

## 12. Perguntas frequentes

**O dashboard mostra erro de conexão com o banco. O que fazer?**

O banco está vazio ou o DBT ainda não rodou. Execute:

```bash
docker compose run --rm scraper
docker exec airflow_scheduler bash -c \
  "cd /opt/airflow/dbt && dbt run --profiles-dir /opt/airflow/dbt --target prod"
```

Depois clique em "Atualizar dados" no Streamlit.

---

**O gráfico de "Evolução do preço" não aparece. Por quê?**

O histórico de preços precisa de dados de pelo menos 2 dias diferentes. No modo demo, todos os anúncios têm a data do dia em que o scraper rodou. Para ver o gráfico, rode o scraper em dias diferentes.

---

**O scraper OLX não coleta nada. O que acontece?**

O OLX pode ter mudado o layout HTML. O scraper usa seletores CSS como `section[data-ds-component='DS-AdCard']`. Se esses seletores pararem de funcionar, o log vai exibir:

```
Nenhum card encontrado na página X — layout mudou?
```

Nesse caso, inspecione o HTML atual do OLX e atualize os seletores em `scraper/scraper.py`.

---

**Quero mudar as credenciais do banco. Como faço?**

Edite o `.env` com as novas credenciais antes de subir pela primeira vez. Se o banco já foi criado, é preciso apagar os volumes e recriar:

```bash
docker compose down -v
# edite .env
docker compose up --build
```

---

**Posso rodar o dashboard fora do Docker para desenvolvimento?**

Sim. Com o banco rodando via Docker, você pode rodar o Streamlit localmente:

```bash
cd streamlit
pip install -r requirements.txt

POSTGRES_HOST=localhost \
POSTGRES_PORT=5432 \
POSTGRES_DB=mobi_scanner \
POSTGRES_USER=mobi \
POSTGRES_PASSWORD=mobi123 \
streamlit run app.py
```

---

**Como adicionar um novo portal de scraping?**

1. Crie uma função `scrape_nomedoportal()` em `scraper/scraper.py` seguindo o padrão de `scrape_olx()`
2. Adicione o novo modo no bloco `if/elif` da função `main()`
3. Adicione o novo valor ao `.env.example` nos comentários de `SCRAPER_MODE`
4. Atualize os testes DBT em `dbt/models/staging/schema.yml` se o novo portal tiver campos diferentes
