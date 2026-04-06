# Docker Compose — Explicação Detalhada

Este documento explica linha a linha o que o arquivo `docker-compose.yml` faz e por que cada configuração existe.

---

## Sumário

1. [Versão do Compose](#1-versão-do-compose)
2. [Ancora compartilhada do Airflow](#2-ancora-compartilhada-do-airflow)
3. [Serviço: postgres](#3-serviço-postgres)
4. [Serviço: airflow-init](#4-serviço-airflow-init)
5. [Serviço: airflow-webserver](#5-serviço-airflow-webserver)
6. [Serviço: airflow-scheduler](#6-serviço-airflow-scheduler)
7. [Serviço: scraper](#7-serviço-scraper)
8. [Serviço: streamlit](#8-serviço-streamlit)
9. [Volumes](#9-volumes)
10. [Ordem de inicialização (resumo visual)](#10-ordem-de-inicialização-resumo-visual)
11. [Dockerfile customizado do Airflow](#11-dockerfile-customizado-do-airflow)

---

## 1. Versão do Compose

```yaml
version: "3.9"
```

Define qual versão da especificação do Docker Compose está sendo usada. A versão `3.9` é a mais recente do formato v3 e suporta todos os recursos usados aqui: `healthcheck`, `depends_on` com `condition`, âncoras YAML (`&` e `<<:`), e `x-` extensões customizadas.

---

## 2. Ancora compartilhada do Airflow

```yaml
x-airflow-common: &airflow-common
  build:
    context: ./airflow
    dockerfile: Dockerfile
  environment: &airflow-common-env
    AIRFLOW__CORE__EXECUTOR: LocalExecutor
    AIRFLOW__CORE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@postgres/airflow
    AIRFLOW__CORE__FERNET_KEY: ""
    AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: "true"
    AIRFLOW__CORE__LOAD_EXAMPLES: "false"
    AIRFLOW__API__AUTH_BACKENDS: "airflow.api.auth.backend.basic_auth"
    AIRFLOW__SCHEDULER__ENABLE_HEALTH_CHECK: "true"
    POSTGRES_HOST: postgres
    POSTGRES_PORT: 5432
    POSTGRES_DB: mobi_scanner
    POSTGRES_USER: ${POSTGRES_USER:-mobi}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-mobi123}
  volumes:
    - ./dags:/opt/airflow/dags
    - ./dbt:/opt/airflow/dbt
    - ./scraper:/opt/airflow/scraper
    - airflow_logs:/opt/airflow/logs
    - airflow_plugins:/opt/airflow/plugins
  user: "${AIRFLOW_UID:-50000}:0"
  depends_on:
    postgres:
      condition: service_healthy
```

### O que é isso?

O prefixo `x-` marca uma **extensão customizada** do Compose — um bloco de configuração reutilizável que não corresponde a nenhum serviço real. O `&airflow-common` cria uma **âncora YAML**: um apelido que pode ser referenciado em outros lugares com `<<: *airflow-common`, evitando repetição de código nos três serviços do Airflow (`airflow-init`, `airflow-webserver`, `airflow-scheduler`).

### Linha a linha

```yaml
build:
  context: ./airflow
  dockerfile: Dockerfile
```

Em vez de usar a imagem oficial do Docker Hub diretamente, todos os serviços do Airflow são construídos a partir de um **Dockerfile customizado** localizado em `./airflow/Dockerfile`. Isso é necessário para pré-instalar dependências Python (como o DBT) sem depender de instalação em tempo de execução.

> Por que não usar `image: apache/airflow:2.9.2-python3.11` diretamente? Veja a seção [11. Dockerfile customizado do Airflow](#11-dockerfile-customizado-do-airflow) para a explicação completa do problema que essa decisão resolve.

---

```yaml
AIRFLOW__CORE__EXECUTOR: LocalExecutor
```
Define o **executor** do Airflow. O `LocalExecutor` roda as tasks em subprocessos na mesma máquina, sem precisar de Redis ou Celery. Ideal para desenvolvimento e ambientes com um único nó.

---

```yaml
AIRFLOW__CORE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@postgres/airflow
```
String de conexão com o banco de **metadados do Airflow** (armazena DAGs, execuções, logs, usuários). Usa um banco separado (`airflow`) no mesmo servidor PostgreSQL, com usuário/senha próprios (`airflow:airflow`). O hostname `postgres` é o nome do serviço Docker — o Compose cria uma rede interna onde os containers se comunicam pelo nome do serviço.

---

```yaml
AIRFLOW__CORE__FERNET_KEY: ""
```
Chave usada para criptografar credenciais salvas no banco do Airflow (como senhas de conexões). Está vazia aqui pois não há credenciais sensíveis armazenadas. Em produção, deve ser preenchida com uma chave gerada por `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

---

```yaml
AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: "true"
```
Novos DAGs começam **pausados** por padrão. Sem isso, o Airflow tentaria executar o DAG imediatamente ao detectá-lo, o que poderia causar execuções indesejadas na inicialização.

---

```yaml
AIRFLOW__CORE__LOAD_EXAMPLES: "false"
```
Desativa os DAGs de exemplo que vêm com o Airflow por padrão (HelloWorld, Tutorial, etc.). Mantém a interface limpa com apenas o DAG do projeto.

---

```yaml
AIRFLOW__API__AUTH_BACKENDS: "airflow.api.auth.backend.basic_auth"
```
Habilita autenticação HTTP Basic na API REST do Airflow. Necessário para que o webserver valide login/senha (`admin/admin`).

---

```yaml
AIRFLOW__SCHEDULER__ENABLE_HEALTH_CHECK: "true"
```
Ativa o endpoint de health check do scheduler em `localhost:8974/health`. Permite que o Docker Compose monitore se o scheduler está vivo e funcionando.

---

```yaml
POSTGRES_HOST: postgres
POSTGRES_PORT: 5432
POSTGRES_DB: mobi_scanner
POSTGRES_USER: ${POSTGRES_USER:-mobi}
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-mobi123}
```
Variáveis de ambiente que o scraper Python e o DAG do Airflow usam para se conectar ao banco `mobi_scanner` (onde ficam os dados do projeto, separado do banco de metadados do Airflow).

A sintaxe `${POSTGRES_USER:-mobi}` significa: use o valor da variável de ambiente `POSTGRES_USER` se ela existir, caso contrário use `mobi` como padrão. Os valores vêm do arquivo `.env`.

---

```yaml
volumes:
  - ./dags:/opt/airflow/dags
  - ./dbt:/opt/airflow/dbt
  - ./scraper:/opt/airflow/scraper
  - airflow_logs:/opt/airflow/logs
  - airflow_plugins:/opt/airflow/plugins
```

Monta pastas do host dentro do container:

| Volume | O que faz |
|--------|-----------|
| `./dags → /opt/airflow/dags` | O Airflow detecta automaticamente arquivos Python nessa pasta como DAGs. Editar `pipeline_dag.py` no host reflete imediatamente no container. |
| `./dbt → /opt/airflow/dbt` | Disponibiliza os modelos DBT dentro do container para o DAG executar `dbt run`. |
| `./scraper → /opt/airflow/scraper` | Disponibiliza o `scraper.py` para o DAG executar via `BashOperator`. |
| `airflow_logs` | Volume nomeado Docker para persistir os logs das execuções de tasks entre reinicializações. |
| `airflow_plugins` | Volume para plugins customizados do Airflow (não usado agora, mas esperado pelo Airflow). |

---

```yaml
user: "${AIRFLOW_UID:-50000}:0"
```
Define o **usuário e grupo** com que o processo do Airflow roda dentro do container. O Airflow requer que o processo tenha UID específico para ter permissão de escrita nos volumes. O padrão `50000` é o recomendado pela documentação oficial. O grupo `0` (root) é necessário para acesso a determinados recursos do sistema.

No Linux, se `AIRFLOW_UID` não estiver definido, pode causar problemas de permissão nos volumes. Por isso o `.env` deve ter `AIRFLOW_UID=50000`.

---

```yaml
depends_on:
  postgres:
    condition: service_healthy
```
O Airflow só sobe **depois que o PostgreSQL estiver saudável** (healthcheck passando). Sem isso, o Airflow tentaria conectar ao banco antes dele estar pronto e falharia.

---

## 3. Serviço: postgres

```yaml
postgres:
  image: postgres:15-alpine
  container_name: mobi_postgres
  environment:
    POSTGRES_USER: ${POSTGRES_USER:-mobi}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-mobi123}
    POSTGRES_DB: mobi_scanner
    POSTGRES_MULTIPLE_DATABASES: "mobi_scanner,airflow"
  volumes:
    - postgres_data:/var/lib/postgresql/data
    - ./postgres/init.sql:/docker-entrypoint-initdb.d/01_init.sql
    - ./postgres/create_airflow_db.sh:/docker-entrypoint-initdb.d/00_create_airflow_db.sh
  ports:
    - "5432:5432"
  healthcheck:
    test: ["CMD", "pg_isready", "-U", "${POSTGRES_USER:-mobi}", "-d", "mobi_scanner"]
    interval: 10s
    retries: 5
    start_period: 10s
  restart: unless-stopped
```

### Linha a linha

```yaml
image: postgres:15-alpine
```
Usa o PostgreSQL 15 na variante `alpine` — uma imagem Linux minimalista que resulta em container menor e mais rápido para inicializar.

---

```yaml
container_name: mobi_postgres
```
Nomeia o container explicitamente. Sem isso, o Docker geraria um nome aleatório como `mobi_scanner-postgres-1`. O nome fixo facilita comandos manuais como `docker exec -it mobi_postgres psql`.

---

```yaml
POSTGRES_USER: ${POSTGRES_USER:-mobi}
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-mobi123}
POSTGRES_DB: mobi_scanner
```
Variáveis que a imagem oficial do PostgreSQL usa para criar o usuário e banco padrão na primeira inicialização. O banco `mobi_scanner` é criado automaticamente.

---

```yaml
POSTGRES_MULTIPLE_DATABASES: "mobi_scanner,airflow"
```
Variável **customizada** (não nativa do PostgreSQL) que o script `create_airflow_db.sh` lê para criar múltiplos bancos. O PostgreSQL só cria um banco por padrão (`POSTGRES_DB`), mas o Airflow precisa de um banco separado (`airflow`) para seus metadados.

---

```yaml
volumes:
  - postgres_data:/var/lib/postgresql/data
  - ./postgres/init.sql:/docker-entrypoint-initdb.d/01_init.sql
  - ./postgres/create_airflow_db.sh:/docker-entrypoint-initdb.d/00_create_airflow_db.sh
```

| Volume | O que faz |
|--------|-----------|
| `postgres_data` | Volume nomeado Docker que persiste os dados do banco entre reinicializações. Sem isso, todos os dados seriam perdidos ao parar o container. |
| `init.sql → 01_init.sql` | Script executado automaticamente na **primeira vez** que o container sobe. Cria os schemas (`raw`, `staging`, `marts`) e as tabelas. O prefixo `01_` define a ordem de execução. |
| `create_airflow_db.sh → 00_create_airflow_db.sh` | Script executado antes do `init.sql` (prefixo `00_`). Cria o banco `airflow` com usuário/senha próprios (`airflow:airflow`) para os metadados do Airflow. |

> **Importante:** os scripts em `docker-entrypoint-initdb.d/` só são executados quando o volume de dados está **vazio** (primeira execução). Se o volume `postgres_data` já existir com dados, eles são ignorados.

---

```yaml
ports:
  - "5432:5432"
```
Expõe a porta 5432 do container no host. Formato `HOST:CONTAINER`. Isso permite acessar o banco de fora do Docker com ferramentas como DBeaver, psql local, ou DataGrip em `localhost:5432`.

---

```yaml
healthcheck:
  test: ["CMD", "pg_isready", "-U", "${POSTGRES_USER:-mobi}", "-d", "mobi_scanner"]
  interval: 10s
  retries: 5
  start_period: 10s
```

Define como o Docker verifica se o PostgreSQL está pronto para aceitar conexões:

| Campo | Valor | Significado |
|-------|-------|-------------|
| `test` | `pg_isready ...` | Comando que retorna 0 se o banco aceitar conexões, diferente de 0 se não |
| `interval` | `10s` | Verifica a cada 10 segundos |
| `retries` | `5` | Após 5 falhas consecutivas, marca o container como `unhealthy` |
| `start_period` | `10s` | Aguarda 10 segundos antes de começar a verificar (tempo para o banco inicializar) |

Este healthcheck é fundamental: os serviços `airflow-init`, `scraper` e `streamlit` dependem do status `healthy` do postgres para iniciar.

---

```yaml
restart: unless-stopped
```
O container reinicia automaticamente se cair, exceto se foi parado manualmente com `docker compose down`. Garante que o banco se recupere de falhas sem intervenção manual.

---

## 4. Serviço: airflow-init

```yaml
airflow-init:
  <<: *airflow-common
  container_name: airflow_init
  entrypoint: /bin/bash
  command:
    - -c
    - |
      airflow db migrate &&
      airflow users create \
        --username admin \
        --firstname Admin \
        --lastname User \
        --role Admin \
        --email admin@mobi.local \
        --password admin || true
  environment:
    <<: *airflow-common-env
    AIRFLOW__CORE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@postgres/airflow
  depends_on:
    postgres:
      condition: service_healthy
```

### O que faz

O `airflow-init` é um **container de inicialização único** — roda uma vez, executa as configurações necessárias e encerra. Os outros serviços do Airflow só sobem após ele completar com sucesso.

### Linha a linha

```yaml
<<: *airflow-common
```
Herda toda a configuração da âncora `airflow-common` (build, volumes, user, depends_on). O `<<:` é o operador de **merge YAML** — incorpora todas as chaves do bloco referenciado.

---

```yaml
entrypoint: /bin/bash
command:
  - -c
  - |
    airflow db migrate &&
    airflow users create \
      --username admin \
      ...
      --password admin || true
```

Sobrescreve o entrypoint padrão da imagem Airflow para rodar um script shell diretamente:

- **`airflow db migrate`** — cria ou atualiza todas as tabelas de metadados do Airflow no banco `airflow`. É o equivalente a uma migration de banco de dados.
- **`airflow users create ...`** — cria o usuário `admin` com senha `admin` e role de administrador.
- **`|| true`** — se o usuário já existir (execuções seguintes), o comando falharia mas o `|| true` ignora o erro e deixa o container encerrar com sucesso.

---

```yaml
environment:
  <<: *airflow-common-env
  AIRFLOW__CORE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@postgres/airflow
```

Herda as variáveis comuns e **sobrescreve** a string de conexão SQL para apontar ao banco `airflow` (com usuário/senha `airflow:airflow`). Isso é necessário porque o `airflow db migrate` precisa conectar ao banco de metadados do Airflow, não ao banco `mobi_scanner` do projeto.

---

## 5. Serviço: airflow-webserver

```yaml
airflow-webserver:
  <<: *airflow-common
  container_name: airflow_webserver
  command: webserver
  ports:
    - "8080:8080"
  healthcheck:
    test: ["CMD", "curl", "--fail", "http://localhost:8080/health"]
    interval: 30s
    timeout: 10s
    retries: 5
    start_period: 30s
  restart: unless-stopped
  depends_on:
    airflow-init:
      condition: service_completed_successfully
```

### O que faz

Sobe a interface web do Airflow — a UI que você acessa no navegador em `http://localhost:8080` para visualizar DAGs, disparar execuções e ver logs.

### Linha a linha

```yaml
command: webserver
```
Instrui o container Airflow a iniciar o componente `webserver` (servidor web Flask/Gunicorn). Cada serviço do Airflow usa a mesma imagem mas um `command` diferente para determinar qual componente rodar.

---

```yaml
ports:
  - "8080:8080"
```
Expõe a porta do webserver no host. Acesse em `http://localhost:8080`.

---

```yaml
healthcheck:
  test: ["CMD", "curl", "--fail", "http://localhost:8080/health"]
  interval: 30s
  timeout: 10s
  retries: 5
  start_period: 30s
```

O endpoint `/health` retorna HTTP 200 quando o webserver está pronto. O intervalo é de 30s (mais generoso que o do postgres) pois o Airflow demora mais para inicializar — precisa carregar todos os DAGs e configurações antes de ficar disponível.

---

```yaml
depends_on:
  airflow-init:
    condition: service_completed_successfully
```
O webserver só sobe **após o `airflow-init` encerrar com código 0** (sucesso). Isso garante que o banco de metadados já está migrado e o usuário admin já existe antes do webserver tentar acessá-los.

---

## 6. Serviço: airflow-scheduler

```yaml
airflow-scheduler:
  <<: *airflow-common
  container_name: airflow_scheduler
  command: scheduler
  healthcheck:
    test: ["CMD", "curl", "--fail", "http://localhost:8974/health"]
    interval: 30s
    timeout: 10s
    retries: 5
    start_period: 30s
  restart: unless-stopped
  depends_on:
    airflow-init:
      condition: service_completed_successfully
```

### O que faz

O scheduler é o **coração do Airflow** — fica continuamente monitorando os DAGs, verificando os horários de execução (cron) e disparando as tasks quando necessário. Sem ele, nenhum DAG roda automaticamente.

### Diferença do webserver

O scheduler **não tem porta exposta** — ele não serve tráfego HTTP para o usuário. Ele se comunica internamente com o banco de metadados do Airflow para registrar e atualizar o estado das execuções.

```yaml
healthcheck:
  test: ["CMD", "curl", "--fail", "http://localhost:8974/health"]
```
A porta `8974` é o endpoint de health interno do scheduler (diferente do webserver que usa 8080). Só existe porque `AIRFLOW__SCHEDULER__ENABLE_HEALTH_CHECK: "true"` foi configurado na âncora comum.

---

## 7. Serviço: scraper

```yaml
scraper:
  build:
    context: ./scraper
    dockerfile: Dockerfile
  container_name: mobi_scraper
  environment:
    POSTGRES_HOST: postgres
    POSTGRES_PORT: 5432
    POSTGRES_DB: mobi_scanner
    POSTGRES_USER: ${POSTGRES_USER:-mobi}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-mobi123}
    SCRAPER_MODE: ${SCRAPER_MODE:-demo}
  depends_on:
    postgres:
      condition: service_healthy
  restart: "no"
```

### O que faz

Roda o `scraper.py` — coleta anúncios de apartamentos e grava em `raw.apartamentos`. **Roda uma vez e encerra** (diferente dos outros serviços que ficam rodando continuamente).

### Linha a linha

```yaml
build:
  context: ./scraper
  dockerfile: Dockerfile
```
Em vez de usar uma imagem pronta do Docker Hub, **constrói uma imagem local** a partir do `Dockerfile` na pasta `./scraper`. O `context` define a pasta raiz usada durante o build — apenas arquivos dentro dela ficam disponíveis para o `COPY` no Dockerfile.

---

```yaml
SCRAPER_MODE: ${SCRAPER_MODE:-demo}
```
Controla o modo de operação do scraper:
- `demo` (padrão) — gera 300 anúncios sintéticos sem acessar a internet
- `olx` — raspa anúncios reais do OLX Brasil

---

```yaml
restart: "no"
```
**Crucial:** diferente dos outros serviços, o scraper **não reinicia** ao encerrar. Se usasse `unless-stopped`, ficaria em loop infinito raspando e reiniciando. O `"no"` garante que ele roda uma vez e para. As execuções periódicas são responsabilidade do Airflow DAG.

---

## 8. Serviço: streamlit

```yaml
streamlit:
  build:
    context: ./streamlit
    dockerfile: Dockerfile
  container_name: mobi_streamlit
  environment:
    POSTGRES_HOST: postgres
    POSTGRES_PORT: 5432
    POSTGRES_DB: mobi_scanner
    POSTGRES_USER: ${POSTGRES_USER:-mobi}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-mobi123}
  ports:
    - "8501:8501"
  depends_on:
    postgres:
      condition: service_healthy
  restart: unless-stopped
```

### O que faz

Sobe o dashboard Streamlit e o mantém disponível continuamente em `http://localhost:8501`. Lê os dados das tabelas `marts.*` no PostgreSQL.

### Pontos relevantes

```yaml
depends_on:
  postgres:
    condition: service_healthy
```
O Streamlit depende apenas do banco estar saudável — **não** depende do scraper nem do DBT. Isso significa que ele sobe mesmo com as tabelas `marts.*` vazias. Se não houver dados, exibe uma mensagem de erro orientando o usuário a rodar o pipeline.

```yaml
restart: unless-stopped
```
Reinicia automaticamente se o processo Streamlit cair (por exemplo, por uma exceção não tratada), sem precisar de intervenção manual.

---

## 9. Volumes

```yaml
volumes:
  postgres_data:
  airflow_logs:
  airflow_plugins:
```

Declara os **volumes nomeados** usados pelos serviços. Volumes nomeados são gerenciados pelo Docker (ficam em `/var/lib/docker/volumes/` no Linux) e persistem mesmo após `docker compose down`.

| Volume | Usado por | O que persiste |
|--------|-----------|----------------|
| `postgres_data` | `postgres` | Todos os dados do banco (raw, staging, marts) |
| `airflow_logs` | Todos os serviços Airflow | Logs de execução das tasks |
| `airflow_plugins` | Todos os serviços Airflow | Plugins customizados do Airflow |

### Diferença entre volume nomeado e bind mount

```yaml
# Bind mount — pasta do host mapeada no container
- ./dags:/opt/airflow/dags

# Volume nomeado — gerenciado pelo Docker
- airflow_logs:/opt/airflow/logs
```

- **Bind mount** (`./pasta:...`): você vê e edita os arquivos diretamente no host. Usado para código-fonte (DAGs, modelos DBT, scraper) para que mudanças no editor reflitam imediatamente no container.
- **Volume nomeado** (`nome:...`): gerenciado pelo Docker, não fica visível diretamente no sistema de arquivos do host. Usado para dados que precisam persistir mas não precisam ser editados (banco de dados, logs).

### Apagar volumes (reset completo)

```bash
docker compose down -v
```

Isso apaga `postgres_data`, `airflow_logs` e `airflow_plugins`. O banco será recriado do zero na próxima subida, com os scripts de inicialização rodando novamente.

---

## 10. Ordem de inicialização (resumo visual)

```
docker compose up
       │
       ▼
  [postgres]
  Aguarda healthcheck (pg_isready)
       │
       ├──────────────────────────────┐
       ▼                              ▼
 [airflow-init]                  [scraper]      [streamlit]
 db migrate + criar admin        roda e encerra  sobe e fica
       │
       ├──────────────────┐
       ▼                  ▼
[airflow-webserver]  [airflow-scheduler]
localhost:8080       monitora DAGs e agendamentos
```

**Por que o scraper e o streamlit não dependem do airflow-init?**

Porque eles só precisam do banco de dados — não precisam dos metadados do Airflow. Fazer o scraper esperar pelo Airflow atrasaria desnecessariamente a coleta inicial de dados.

**Por que o webserver e o scheduler esperam pelo airflow-init?**

Porque ambos precisam que o banco de metadados do Airflow (`airflow.db`) já esteja com as tabelas criadas (`airflow db migrate`) antes de tentar ler DAGs, execuções e usuários.

---

## 11. Dockerfile customizado do Airflow

### Por que existe

A versão original do `docker-compose.yml` usava a variável `_PIP_ADDITIONAL_REQUIREMENTS` do Airflow para instalar pacotes extras:

```yaml
# versão antiga — problemática
_PIP_ADDITIONAL_REQUIREMENTS: "psycopg2-binary dbt-postgres==1.8.0 requests beautifulsoup4 lxml"
```

Essa abordagem causava **dois problemas sérios**:

**Problema 1 — Loop de falha na inicialização**

O `dbt-postgres` tem como dependência o pacote `psycopg2` (versão que compila do código-fonte), diferente do `psycopg2-binary` (versão pré-compilada). Para compilar o `psycopg2`, o pip precisa do `pg_config` — um binário que faz parte do pacote de desenvolvimento do PostgreSQL (`libpq-dev`). A imagem base do Airflow não inclui essa biblioteca de sistema, então o pip falhava com:

```
Error: pg_config executable not found.
```

Como `restart: unless-stopped` estava ativo, o container reiniciava, tentava instalar de novo, falhava de novo — **loop infinito**.

**Problema 2 — Lentidão em toda inicialização**

A variável `_PIP_ADDITIONAL_REQUIREMENTS` instala os pacotes **toda vez que o container inicia**, não apenas na primeira. Isso significava que a cada `docker compose up`, os três serviços do Airflow (init, webserver, scheduler) rodavam `pip install` em paralelo, instalando dezenas de dependências do DBT novamente — mesmo que nada tivesse mudado.

---

### A solução: `airflow/Dockerfile`

```dockerfile
FROM apache/airflow:2.9.2-python3.11

USER root

# Instala libpq-dev (necessário para compilar psycopg2)
# e gcc (compilador C exigido pelo build do psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
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
```

### Linha a linha

```dockerfile
FROM apache/airflow:2.9.2-python3.11
```
Parte da imagem oficial do Airflow como base — não reinventa a roda, apenas adiciona o que falta.

---

```dockerfile
USER root
```
Muda temporariamente para o usuário `root` dentro do container. Necessário porque instalar pacotes de sistema com `apt-get` requer permissões de administrador. A imagem do Airflow roda com um usuário sem privilégios por padrão (`airflow`).

---

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*
```

Instala as dependências de sistema necessárias para compilar o `psycopg2`:

| Pacote | Para que serve |
|--------|---------------|
| `libpq-dev` | Headers e bibliotecas de desenvolvimento do PostgreSQL. Fornece o `pg_config` que o pip precisa para compilar o `psycopg2`. |
| `gcc` | Compilador C. O `psycopg2` é uma extensão C do Python — precisa ser compilado da fonte. |

O `--no-install-recommends` evita instalar pacotes sugeridos desnecessários, mantendo a imagem menor. O `rm -rf /var/lib/apt/lists/*` apaga o cache do apt após a instalação, reduzindo ainda mais o tamanho final da imagem.

---

```dockerfile
USER airflow
```
Volta para o usuário `airflow` antes de instalar os pacotes Python. Boa prática de segurança: nunca rodar o processo principal como root. O `pip install` funciona normalmente com o usuário `airflow` pois instala no diretório local do usuário (`~/.local`).

---

```dockerfile
RUN pip install --no-cache-dir \
    psycopg2-binary==2.9.9 \
    "dbt-postgres==1.8.0" \
    requests==2.31.0 \
    beautifulsoup4==4.12.3 \
    lxml==5.2.2
```

Instala os pacotes Python com **versões fixadas** (`==`) para garantir que o comportamento seja sempre o mesmo independentemente de quando a imagem for construída. O `--no-cache-dir` evita que o pip guarde arquivos temporários de download dentro da imagem, mantendo-a menor.

---

### Comparação antes e depois

| | Antes (`_PIP_ADDITIONAL_REQUIREMENTS`) | Depois (Dockerfile customizado) |
|--|--|--|
| Quando instala | **Toda vez** que o container inicia | Apenas no `docker build` (uma vez) |
| `pg_config` disponível | Não — causava falha e loop | Sim — `libpq-dev` instalado via apt |
| Tempo de `docker compose up` | Lento (pip install sempre) | Rápido (pacotes já na imagem) |
| Confiabilidade | Frágil — pip pode falhar a qualquer momento | Estável — imagem já testada e pronta |
| Recomendado para produção | Não (o próprio Airflow avisa) | Sim |

### Como rebuildar a imagem

Se você alterar o `Dockerfile` ou quiser forçar a reinstalação dos pacotes:

```bash
docker compose build airflow-webserver
docker compose up
```

Ou para rebuildar tudo do zero:

```bash
docker compose down
docker compose build --no-cache
docker compose up
```
