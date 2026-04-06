"""
Mobi Scanner — Scraper
======================
Coleta anúncios de apartamentos de portais imobiliários brasileiros e
persiste os dados brutos em raw.apartamentos (PostgreSQL).

Modos de operação (env SCRAPER_MODE):
  demo  — gera dados sintéticos realistas para testes (padrão)
  olx   — raspa OLX Brasil (olx.com.br)

O scraper é idempotente: usa INSERT ... ON CONFLICT (url) DO NOTHING,
então re-executar nunca gera duplicatas.
"""

from __future__ import annotations

import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Iterator

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("mobi.scraper")

# ── Config ───────────────────────────────────────────────────────────────────
POSTGRES_DSN = (
    f"host={os.getenv('POSTGRES_HOST', 'localhost')} "
    f"port={os.getenv('POSTGRES_PORT', '5432')} "
    f"dbname={os.getenv('POSTGRES_DB', 'mobi_scanner')} "
    f"user={os.getenv('POSTGRES_USER', 'mobi')} "
    f"password={os.getenv('POSTGRES_PASSWORD', 'mobi123')}"
)

SCRAPER_MODE = os.getenv("SCRAPER_MODE", "demo")

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# ── Data model ───────────────────────────────────────────────────────────────

Listing = dict  # typed alias for readability


# ── Demo data generator ──────────────────────────────────────────────────────

_BAIRROS: dict[str, list[str]] = {
    "São Paulo": [
        "Pinheiros", "Vila Madalena", "Moema", "Itaim Bibi", "Brooklin",
        "Lapa", "Perdizes", "Santana", "Campo Belo", "Vila Olímpia",
        "Higienópolis", "Bela Vista", "Consolação", "Jardins", "Tatuapé",
    ],
    "Rio de Janeiro": [
        "Copacabana", "Ipanema", "Leblon", "Botafogo", "Flamengo",
        "Tijuca", "Barra da Tijuca", "Recreio", "Jacarepaguá", "Grajaú",
    ],
    "Curitiba": [
        "Batel", "Água Verde", "Centro", "Boa Vista", "Portão",
        "Santa Felicidade", "Bacacheri", "Cabral", "Mercês", "Bigorrilho",
    ],
}

_PORTALS = ["olx", "zap", "vivareal"]


def _rand_price(bairro: str, cidade: str) -> float:
    """Gera preço realista por bairro."""
    base: dict[str, float] = {
        "São Paulo": 650_000,
        "Rio de Janeiro": 750_000,
        "Curitiba": 480_000,
    }
    noble = {"Leblon", "Ipanema", "Jardins", "Itaim Bibi", "Moema", "Batel"}
    multiplier = 1.8 if bairro in noble else 1.0
    city_base = base.get(cidade, 500_000)
    return round(random.gauss(city_base * multiplier, city_base * 0.2), -3)


def generate_demo_listings(n: int = 200) -> list[dict]:
    """Gera n anúncios sintéticos com distribuição realista."""
    rows = []
    for i in range(n):
        cidade = random.choice(list(_BAIRROS.keys()))
        bairro = random.choice(_BAIRROS[cidade])
        quartos = random.choices([1, 2, 3, 4], weights=[15, 35, 35, 15])[0]
        area = round(random.gauss(quartos * 28, 15), 1)
        area = max(25.0, area)
        preco = _rand_price(bairro, cidade)
        portal = random.choice(_PORTALS)
        slug = f"{bairro.lower().replace(' ', '-')}-{i}"
        rows.append({
            "link":                 f"https://{portal}.com.br/imoveis/apartamento-{slug}",
            "bairro":               bairro,
            "rua":                  None,
            "valor":                preco,
            "condominio":           None,
            "iptu":                 None,
            "metragem":             area,
            "quartos":              quartos,
            "banheiros":            None,
            "vagas":                random.choices([0, 1, 2], weights=[20, 50, 30])[0],
            "descricao":            f"Apartamento {quartos} quartos em {bairro}, {cidade}",
            "data_hora_atualizacao": datetime.now(timezone.utc),
        })
    return rows


# ── OLX scraper ───────────────────────────────────────────────────────────────

OLX_CITIES = [
    "https://www.olx.com.br/imoveis/venda/apartamentos/estado-sp/sao-paulo-e-regiao",
    "https://www.olx.com.br/imoveis/venda/apartamentos/estado-rj/rio-de-janeiro-e-regiao",
]

# ── ZAP Imóveis scraper ───────────────────────────────────────────────────────

def _build_zap_urls() -> list[str]:
    """
    Gera a lista de URLs de busca dividindo o intervalo de preços em fatias.
    Lê ZAP_BASE_URL, ZAP_MIN_VALUE, ZAP_MAX_VALUE e ZAP_STEP_VALUE do .env.

    Exemplo com step=20000, min=80000:
      fatia 1: precoMinimo=80000  & precoMaximo=99999
      fatia 2: precoMinimo=100000 & precoMaximo=119999
      ...
    """
    base_url  = os.getenv("ZAP_BASE_URL", "")
    min_val   = int(os.getenv("ZAP_MIN_VALUE",  "80000"))
    max_val   = int(os.getenv("ZAP_MAX_VALUE",  "2000000"))
    step      = int(os.getenv("ZAP_STEP_VALUE", "20000"))

    if not base_url:
        raise ValueError("ZAP_BASE_URL não definida no .env")

    urls = []
    current = min_val
    while current < max_val:
        preco_min = current
        preco_max = current + step - 1
        url = base_url.replace("var_min", str(preco_min)).replace("var_max", str(preco_max))
        urls.append(url)
        current += step

    log.info("ZAP: %d intervalos de preço gerados (R$%s → R$%s, step R$%s)",
             len(urls), f"{min_val:,}", f"{max_val:,}", f"{step:,}")
    return urls

_BAIRROS_RECIFE = [
    "Boa Viagem", "Casa Forte", "Espinheiro", "Graças", "Madalena",
    "Pina", "Aflitos", "Parnamirim", "Ilha do Retiro", "Rosarinho",
    "Torre", "Jaqueira", "Poço da Panela", "Apipucos", "Monteiro",
    "Várzea", "Cidade Universitária", "Imbiribeira", "Iputinga",
    "Cordeiro", "Encruzilhada", "Tamarineira", "Santana", "Derby",
    "Soledade", "Zumbi", "Caxangá", "Dois Irmãos", "Tejipió",
]


DEBUG = os.getenv("SCRAPER_DEBUG", "false").lower() == "true"


def _human_scroll(page_browser) -> None:
    """Rola a página em etapas simulando comportamento humano."""
    height = page_browser.evaluate("document.body.scrollHeight")
    step = random.randint(300, 600)
    pos = 0
    while pos < height:
        pos += step
        page_browser.evaluate(f"window.scrollTo(0, {pos})")
        page_browser.wait_for_timeout(random.randint(100, 300))
    # pausa final no rodapé antes de clicar em próxima
    page_browser.wait_for_timeout(random.randint(800, 1500))


CLOUDFLARE_STRATEGY = os.getenv("CLOUDFLARE_STRATEGY", "wait")  # "wait" | "reopen"


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

_VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 720},
]

_TIMEZONES = [
    "America/Recife",
    "America/Sao_Paulo",
    "America/Fortaleza",
    "America/Maceio",
]


def _new_browser_page(p, Stealth, incognito: bool = False):
    """
    Cria um novo browser, context e page com stealth aplicado.
    Randomiza user-agent, viewport e timezone a cada chamada.
    Se incognito=True, abre em modo anônimo (sem cookies, histórico ou cache).
    """
    args = ["--disable-blink-features=AutomationControlled"]
    if incognito:
        args.append("--incognito")

    browser = p.chromium.launch(
        headless=not DEBUG,
        args=args,
    )
    context = browser.new_context(
        user_agent=random.choice(_USER_AGENTS),
        locale="pt-BR",
        viewport=random.choice(_VIEWPORTS),
        timezone_id=random.choice(_TIMEZONES),
        extra_http_headers={
            "Referer": "https://www.google.com.br/",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    page_browser = context.new_page()
    Stealth().apply_stealth_sync(page_browser)
    return browser, page_browser


def _handle_cloudflare(page_browser, page_num: int):
    """
    Estratégia 'wait': aguarda e tenta continuar no mesmo navegador.
    Retorna blocked: bool
    """
    log.warning("Cloudflare detectado na página %d — aguardando...", page_num)
    page_browser.wait_for_timeout(random.randint(5000, 10000))
    if "Attention Required" in page_browser.title():
        log.error("Bloqueio persistente do Cloudflare. Encerrando.")
        return True
    return False


def scrape_zap(max_pages: int | None = 5) -> Iterator[Listing]:
    """
    max_pages: número máximo de páginas a raspar.
               Passe None para raspar todas as páginas até o fim.
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    log.info(
        "Estratégia anti-Cloudflare: %s | Páginas: %s",
        CLOUDFLARE_STRATEGY,
        max_pages if max_pages is not None else "todas",
    )

    all_links: list[str] = []
    tempo_inicio_total = time.time()

    with sync_playwright() as p:
        browser = None
        page_browser = None

        for base_url in _build_zap_urls():
            if browser:
                browser.close()
            browser, page_browser = _new_browser_page(p, Stealth, incognito=True)
            url = base_url
            page = 0

            while max_pages is None or page < max_pages:
                page += 1
                tempo_inicio_pagina = time.time()
                log.info("ZAP → página %d: %s", page, url)

                page_browser.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page_browser.wait_for_selector("[data-cy='rp-property-cd']", timeout=15000)
                except Exception:
                    pass

                # Rola suavemente até o fim para revelar o botão de próxima página
                _human_scroll(page_browser)

                if DEBUG:
                    input(f"[DEBUG] Página {page} — inspecione o navegador e pressione ENTER para continuar...")

                html = page_browser.content()
                soup = BeautifulSoup(html, "lxml")

                cards = soup.select("[data-cy='rp-property-cd']")
                log.info("Página %d — %d cards encontrados", page, len(cards))

                if not cards:
                    cloudflare_detected = "Attention Required" in page_browser.title()
                    if cloudflare_detected and CLOUDFLARE_STRATEGY == "reopen":
                        log.warning("Cloudflare na página %d — reabrindo sessão...", page)
                        browser.close()
                        browser, page_browser = _new_browser_page(p, Stealth, incognito=True)
                        page_browser.goto(url, wait_until="domcontentloaded", timeout=30000)
                        try:
                            page_browser.wait_for_selector("[data-cy='rp-property-cd']", timeout=15000)
                        except Exception:
                            pass
                        _human_scroll(page_browser)
                        html = page_browser.content()
                        soup = BeautifulSoup(html, "lxml")
                        cards = soup.select("[data-cy='rp-property-cd']")
                        log.info("Página %d (retry) — %d cards encontrados", page, len(cards))
                    elif cloudflare_detected and CLOUDFLARE_STRATEGY == "wait":
                        blocked = _handle_cloudflare(page_browser, page)
                        if blocked:
                            break

                if not cards:
                    log.warning("Nenhum card na página %d — pulando intervalo", page)
                    break

                for card in cards:
                    try:
                        
                        # Tipo 1: card normal com link direto  <a href="..." title="...">
                        # Tipo 2: card agrupado sem link       <a role="button">
                        link_tag = card.select_one("a[href]")
                        if link_tag:
                            href = link_tag["href"]
                            if not href.startswith("http"):
                                href = "https://www.zapimoveis.com.br" + href
                            descricao = link_tag.get("title", "").strip()
                        else:
                            # card agrupado — sem URL direta
                            href = None
                            span_desc = card.select_one("[data-cy='rp-cardProperty-location-txt'] span")
                            descricao = span_desc.get_text(strip=True) if span_desc else ""

                        # Bairro: pega apenas o texto direto do h2, ignorando o span filho
                        # O h2 tem: <span>descrição curta</span> + texto "Bairro, Cidade"
                        bairro_tag = card.select_one("[data-cy='rp-cardProperty-location-txt']")
                        if bairro_tag:
                            # Remove o span interno (descrição) e pega só o texto restante
                            span = bairro_tag.find("span")
                            if span:
                                span.decompose()
                            bairro_full = bairro_tag.get_text(strip=True)  # "Maurício de Nassau, Caruaru"
                            bairro = bairro_full.split(",")[0].strip()
                        else:
                            bairro = ""

                        rua_tag = card.select_one("[data-cy='rp-cardProperty-street-txt']")
                        rua = rua_tag.get_text(strip=True) if rua_tag else ""

                        price_box = card.select_one("[data-cy='rp-cardProperty-price-txt']")
                        if price_box:
                            ps = price_box.find_all("p")
                            valor_txt  = ps[0].get_text(strip=True) if len(ps) > 0 else ""
                            extras_txt = ps[1].get_text(strip=True) if len(ps) > 1 else ""
                        else:
                            valor_txt = extras_txt = ""

                        # "R$ 579.000" → 579000.0
                        # "Cond. R$ 450" → 450.0  /  "IPTU R$ 132" → 132.0
                        def _parse_brl(txt: str) -> float | None:
                            import re
                            m = re.search(r"[\d.,]+", txt.replace(".", "").replace(",", "."))
                            if not m:
                                return None
                            try:
                                return float(m.group())
                            except ValueError:
                                return None

                        valor = _parse_brl(valor_txt)

                        # "Cond. R$ 450 • IPTU R$ 132"
                        cond = iptu = None
                        for part in extras_txt.split("•"):
                            part = part.strip()
                            if "Cond" in part:
                                cond = _parse_brl(part)
                            elif "IPTU" in part:
                                iptu = _parse_brl(part)

                        # Para campos numéricos: pega apenas os dígitos do último
                        # nó de texto (ignora o <span class="sr-only"> que tem texto descritivo)
                        def _last_text(cy: str) -> str:
                            tag = card.select_one(f"[data-cy='{cy}']")
                            if not tag:
                                return ""
                            # Remove spans sr-only (textos acessíveis como "Tamanho do imóvel")
                            for sr in tag.find_all("span", class_="sr-only"):
                                sr.decompose()
                            return tag.get_text(strip=True)

                        def _parse_int(cy: str) -> int | None:
                            txt = _last_text(cy)
                            digits = "".join(c for c in txt if c.isdigit())
                            return int(digits) if digits else None

                        def _parse_float_area(cy: str) -> float | None:
                            txt = _last_text(cy)
                            clean = txt.replace("m²", "").replace(",", ".").strip()
                            try:
                                return float(clean)
                            except ValueError:
                                return None

                        metragem  = _parse_float_area("rp-cardProperty-propertyArea-txt")
                        quartos   = _parse_int("rp-cardProperty-bedroomQuantity-txt")
                        banheiros = _parse_int("rp-cardProperty-bathroomQuantity-txt")
                        vagas     = _parse_int("rp-cardProperty-parkingSpacesQuantity-txt")

                        img_tag = card.select_one("[data-cy='rp-cardProperty-image-img'] img")
                        imagem_url = img_tag["src"] if img_tag and img_tag.get("src") else None

                        all_links.append({
                            "link":       href,
                            "imagem_url": imagem_url,
                            "bairro":     bairro,
                            "rua":        rua,
                            "valor":      valor,
                            "condominio": cond,
                            "iptu":       iptu,
                            "metragem":   metragem,
                            "quartos":    quartos,
                            "banheiros":  banheiros,
                            "vagas":      vagas,
                            "descricao":  descricao,
                        })
                    except Exception as exc:
                        log.debug("Erro ao parsear card: %s", exc)
                        continue

                elapsed_pagina = time.time() - tempo_inicio_pagina
                log.info("Página %d — %d imóveis acumulados | tempo: %.1fs", page, len(all_links), elapsed_pagina)

                next_tag = soup.select_one("a[aria-label='próxima página']")
                if not next_tag or next_tag.get("aria-disabled") == "true":
                    log.info("Última página atingida na página %d", page)
                    break

                next_href = next_tag["href"]
                url = "https://www.zapimoveis.com.br" + next_href if not next_href.startswith("http") else next_href

                # reopen: fecha o navegador e abre nova sessão anônima direto na próxima página
                if CLOUDFLARE_STRATEGY == "reopen":
                    log.info("Reopen: fechando navegador e abrindo incógnito para página %d...", page + 1)
                    browser.close()
                    browser, page_browser = _new_browser_page(p, Stealth, incognito=True)
                else:
                    time.sleep(random.uniform(2.0, 4.0))

        browser.close()

    import pandas as pd
    from sqlalchemy import create_engine

    elapsed_total = time.time() - tempo_inicio_total
    log.info("Total de imóveis coletados: %d | tempo total: %.1fs", len(all_links), elapsed_total)

    df = pd.DataFrame(all_links, columns=[
        "link", "imagem_url", "bairro", "rua", "valor", "condominio",
        "iptu", "metragem", "quartos", "banheiros", "vagas", "descricao",
    ])
    df["data_hora_atualizacao"] = datetime.now(timezone.utc)

    print("\n── Primeiros 10 imóveis coletados ──")
    print(df.head(10).to_string(index=False))
    print()

    # Grava no banco — cria a tabela se não existir, substitui os dados existentes
    engine = create_engine(
        f"postgresql+psycopg2://"
        f"{os.getenv('POSTGRES_USER', 'mobi')}:{os.getenv('POSTGRES_PASSWORD', 'mobi123')}"
        f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB', 'mobi_scanner')}"
    )
    df.to_sql(
        name="apartamentos_resumo",
        con=engine,
        schema="raw",
        if_exists="replace",
        index=False,
    )
    log.info("Tabela raw.apartamentos_resumo atualizada com %d registros.", len(df))

    return iter([])


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get(url: str, session: requests.Session) -> requests.Response:
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp


def _parse_olx_price(text: str) -> float | None:
    try:
        clean = text.replace("R$", "").replace(".", "").replace(",", ".").strip()
        return float(clean)
    except (ValueError, AttributeError):
        return None


def _parse_olx_number(text: str) -> int | None:
    try:
        digits = "".join(c for c in text if c.isdigit())
        return int(digits) if digits else None
    except (ValueError, TypeError):
        return None


def scrape_olx(max_pages: int = 3) -> Iterator[Listing]:
    session = requests.Session()
    session.headers.update(HEADERS)

    for base_url in OLX_CITIES:
        for page in range(1, max_pages + 1):
            url = f"{base_url}?o={page}" if page > 1 else base_url
            log.info("OLX → %s", url)
            try:
                resp = _get(url, session)
            except Exception as exc:
                log.warning("Falha ao buscar %s: %s", url, exc)
                break

            soup = BeautifulSoup(resp.text, "lxml")

            # OLX uses data-ds-component="AD_CARD" or section[data-testid]
            cards = soup.select("section[data-ds-component='DS-AdCard']")
            if not cards:
                cards = soup.select("li[data-ds-component='DS-AdCard']")
            if not cards:
                log.warning("Nenhum card encontrado na página %d — layout mudou?", page)
                break

            for card in cards:
                try:
                    link_tag = card.select_one("a[href]")
                    if not link_tag:
                        continue
                    href: str = link_tag["href"]
                    if not href.startswith("http"):
                        href = "https://www.olx.com.br" + href

                    title_tag = card.select_one("h2, [data-ds-component='DS-Text']")
                    titulo = title_tag.get_text(strip=True) if title_tag else ""

                    price_tag = card.select_one("[data-ds-component='DS-Price'], .price")
                    preco = _parse_olx_price(price_tag.get_text()) if price_tag else None

                    details = card.select("[data-ds-component='DS-AdDetails'] span, .detail-value")
                    area_m2 = quartos = vagas = None
                    for d in details:
                        txt = d.get_text(strip=True).lower()
                        if "m²" in txt or "m2" in txt:
                            area_m2 = _parse_olx_number(txt)
                        elif "quarto" in txt or "dorm" in txt:
                            quartos = _parse_olx_number(txt)
                        elif "vaga" in txt:
                            vagas = _parse_olx_number(txt)

                    location_tag = card.select_one("[data-ds-component='DS-Location'], .location")
                    location_text = location_tag.get_text(strip=True) if location_tag else ""
                    parts = [p.strip() for p in location_text.split(",")]
                    bairro = parts[0] if parts else ""
                    cidade = parts[1] if len(parts) > 1 else ""

                    yield {
                        "id": str(uuid.uuid4()),
                        "url": href,
                        "titulo": titulo[:500],
                        "preco": preco,
                        "area_m2": area_m2,
                        "quartos": quartos,
                        "vagas": vagas,
                        "bairro": bairro[:200],
                        "cidade": cidade[:200],
                        "portal": "olx",
                        "data_coleta": datetime.now(timezone.utc),
                    }
                except Exception as exc:
                    log.debug("Erro ao parsear card: %s", exc)
                    continue

            # Rate limiting — simula comportamento humano
            time.sleep(random.uniform(2.5, 5.0))


# ── Database persistence ──────────────────────────────────────────────────────

def save_to_db(df) -> None:
    """Grava o DataFrame em raw.apartamentos_resumo, substituindo os dados existentes."""
    from sqlalchemy import create_engine
    engine = create_engine(
        f"postgresql+psycopg2://"
        f"{os.getenv('POSTGRES_USER', 'mobi')}:{os.getenv('POSTGRES_PASSWORD', 'mobi123')}"
        f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB', 'mobi_scanner')}"
    )
    df.to_sql(
        name="apartamentos_resumo",
        con=engine,
        schema="raw",
        if_exists="replace",
        index=False,
    )
    log.info("Tabela raw.apartamentos_resumo atualizada com %d registros.", len(df))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import pandas as pd

    log.info("Mobi Scanner iniciando — modo: %s", SCRAPER_MODE)

    if SCRAPER_MODE == "demo":
        rows = generate_demo_listings(n=300)
        log.info("Gerados %d anúncios de demonstração", len(rows))
        df = pd.DataFrame(rows)
        print("\n── Primeiros 10 imóveis (demo) ──")
        print(df.head(10).to_string(index=False))
        print()
        save_to_db(df)

    elif SCRAPER_MODE == "zap":
        _raw = os.getenv("ZAP_MAX_PAGES", "5")
        max_pages = None if _raw.lower() == "all" else int(_raw)
        list(scrape_zap(max_pages=max_pages))  # salva internamente via save_to_db

    else:
        raise ValueError(f"SCRAPER_MODE inválido: {SCRAPER_MODE!r}. Use 'demo' ou 'zap'.")

    log.info("Scraper concluído com sucesso.")


if __name__ == "__main__":
    main()
