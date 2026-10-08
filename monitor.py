#!/usr/bin/env python3
import html as html_lib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


STATE_FILE = Path("state.json")

# Keepalive: sin cambios de lógica; valida el trigger por push del monitor.


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)

DIRECT_PRODUCTS = {
    "GARHIS": "https://garhis.es/trading-card-games/8968-booster-box-display-eb-05-24-sobres-ingles-one-piece-card-game-810199502779.html",
    "KABURI": "https://www.kaburi.es/One-Piece-Tcg-Eb05-Booster-Box-Ingl%C3%A9s.html",
    "GAMERIA": "https://gameria.es/juegos-de-cartas/one-piece-card-game-eb-05-caja-20167.html",
}

GAMERIA_CATEGORY_URL = "https://gameria.es/47-one-piece-card-game"
JINA_READER_PREFIX = "https://r.jina.ai/"

DISCOVERY_PAGES = {
    "INGENIO_BCN": {
        "url": "https://www.ingeniobcn.com/etiqueta-producto/one-piece/",
        "force_browser": False,
        "max_pages": 8,
        "required_patterns": [r"one\s*piece"],
    },
    "METROPOLIS_CENTER": {
        "url": "https://metropolis-center.com/es/catalogo/juegos-de-cartas/one-piece",
        "force_browser": True,
        "max_pages": 8,
        "required_patterns": [r"one\s*piece"],
    },
    "MATHOM": {
        "url": "https://mathom.es/es/6900-one-piece-card-game",
        "force_browser": False,
        "max_pages": 8,
        "required_patterns": [r"one\s*piece"],
    },
    "ZACATRUS": {
        "url": "https://zacatrus.es/catalogsearch/result/?q=one+piece",
        "force_browser": False,
        "max_pages": 8,
        "required_patterns": [r"one\s*piece"],
    },
    "PAPER_DEALER": {
        "url": "https://www.paperdealer.eu/collections/one-piece-tcg",
        "force_browser": False,
        "max_pages": 8,
        "required_patterns": [r"one\s*piece"],
    },
}

EB05_PATTERNS = [
    re.compile(r"\bEB[\s_-]*0?5\b", re.I),
    re.compile(r"\bEXTRA[\s_-]*BOOSTER[\s_-]*(?:EB[\s_-]*)?0?5\b", re.I),
    re.compile(r"\bEXTRA[\s_-]*BOOSTER[\s_-]*5\b", re.I),
]

UNAVAILABLE_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in (
        r"no\s+disponible",
        r"sin\s+stock",
        r"fuera\s+de\s+stock",
        r"agotado",
        r"sin\s+existencias",
        r"en\s+reposici[oó]n",
        r"sold\s*out",
        r"out\s+of\s+stock",
        r"unavailable",
    )
]

BUY_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in (
        r"añadir\s+(?:a\s+la\s+)?cesta",
        r"añadir\s+(?:al\s+)?carrito",
        r"comprar",
        r"add\s+to\s+cart",
        r"buy\s+now",
        r"add-to-cart",
    )
]

BLOCKED_PATTERNS = (
    r"access denied",
    r"verify you are human",
    r"just a moment",
    r"checking your browser",
    r"captcha",
)

PRODUCT_NODE_SELECTORS = (
    "article",
    ".product-miniature",
    ".product",
    ".product-item",
    ".js-product-miniature",
    ".product-card",
    ".card-product",
    "li.product",
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SEND_TEST_NOTIFICATION = os.getenv("SEND_TEST_NOTIFICATION", "false").lower() == "true"
STATUS_REPORT_INTERVAL_HOURS = int(os.getenv("STATUS_REPORT_INTERVAL_HOURS", "12"))


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("ℹ️ Telegram no configurado; aviso mostrado solo en logs.")
        return False

    endpoint = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            endpoint,
            data={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
        response.raise_for_status()
        print("📲 Aviso enviado por Telegram.")
        return True
    except Exception as exc:
        print(f"⚠️ No se pudo enviar Telegram: {exc}")
        return False


def build_http_session():
    session = requests.Session()
    retries = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET", "HEAD")),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    return session


class BrowserFetcher:
    """Reutiliza una única instancia de Chromium durante toda la ejecución."""

    def __init__(self):
        self.playwright = None
        self.browser = None

    def _ensure_started(self):
        if self.browser is not None:
            return

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

    def fetch(self, url):
        self._ensure_started()
        context = self.browser.new_context(
            user_agent=USER_AGENT,
            locale="es-ES",
            viewport={"width": 1440, "height": 1100},
        )
        page = context.new_page()

        def rendered_snapshot():
            """
            Devuelve el HTML más las señales que ve el navegador ya renderizado.
            Algunas tiendas pintan disponibilidad mediante JS/CSS y page.content()
            por sí solo no siempre refleja el mismo texto que ve el usuario.
            """
            markup = page.content()

            try:
                body_text = page.locator("body").inner_text(timeout=5000)
            except Exception:
                body_text = ""

            try:
                runtime_signals = page.evaluate(
                    """() => {
                        const selectors = [
                          '#product-availability',
                          '.product-availability',
                          '[itemprop="availability"]',
                          '.availability',
                          '.stock',
                          '[class*="availability"]',
                          '[id*="availability"]',
                          '[class*="stock"]',
                          '[id*="stock"]',
                          '.product-actions',
                          '.product-add-to-cart',
                          '[data-button-action="add-to-cart"]',
                          'button',
                          'input[type="submit"]'
                        ];

                        const nodes = [...new Set(
                          selectors.flatMap(s => [...document.querySelectorAll(s)])
                        )];

                        return nodes.map(el => {
                          const before = getComputedStyle(el, '::before').content || '';
                          const after = getComputedStyle(el, '::after').content || '';
                          const style = getComputedStyle(el);
                          const className =
                            typeof el.className === 'string' ? el.className : '';
                          const ariaDisabled =
                            el.getAttribute('aria-disabled') || '';
                          const isDisabled =
                            el.matches(':disabled') ||
                            el.hasAttribute('disabled') ||
                            ariaDisabled.toLowerCase() === 'true' ||
                            /(^|\\s)(disabled|is-disabled)(\\s|$)/i.test(className) ||
                            style.pointerEvents === 'none';

                          return [
                            el.innerText || '',
                            el.textContent || '',
                            el.getAttribute('aria-label') || '',
                            el.getAttribute('title') || '',
                            el.getAttribute('value') || '',
                            className,
                            ariaDisabled,
                            isDisabled ? 'disabled' : '',
                            'pointer-events=' + style.pointerEvents,
                            'opacity=' + style.opacity,
                            before,
                            after
                          ].join(' ');
                        }).join('\n');
                    }"""
                )
            except Exception:
                runtime_signals = ""

            rendered = "\n".join(
                part for part in (body_text, runtime_signals) if part
            )

            if rendered:
                injected = (
                    '<div id="__monitor_runtime_signals">'
                    + html_lib.escape(rendered)
                    + "</div>"
                )
                if "</body>" in markup:
                    markup = markup.replace("</body>", injected + "</body>", 1)
                else:
                    markup += injected

            return markup

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)

            try:
                page.wait_for_load_state("networkidle", timeout=7000)
            except Exception:
                pass

            page.wait_for_timeout(1500)
            return rendered_snapshot(), "Playwright/Chromium + DOM", page.url

        except PlaywrightTimeoutError:
            # Algunos comercios dejan recursos colgados y nunca completan
            # DOMContentLoaded. Primero intentamos aprovechar el DOM parcial.
            try:
                partial = rendered_snapshot()
                if partial and len(partial) > 1000:
                    return (
                        partial,
                        "Playwright/Chromium + DOM (timeout parcial)",
                        page.url or url,
                    )
            except Exception:
                pass

            # Segundo intento ligero: basta con que el servidor empiece a
            # entregar el documento; después dejamos unos segundos al JS.
            try:
                page.goto(url, wait_until="commit", timeout=20000)
                page.wait_for_timeout(4000)
                return (
                    rendered_snapshot(),
                    "Playwright/Chromium + DOM (retry)",
                    page.url or url,
                )
            except Exception:
                return None, "Playwright timeout", url

        except Exception as exc:
            return None, f"Playwright error: {exc}", url

        finally:
            context.close()

    def close(self):
        if self.browser is not None:
            self.browser.close()
            self.browser = None

        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None


def http_fetch(session, url):
    try:
        response = session.get(url, timeout=30, allow_redirects=True)

        if response.status_code == 200 and len(response.text) > 500:
            return response.text, f"HTTP {response.status_code}", response.url

        return None, f"HTTP {response.status_code}", response.url

    except requests.RequestException as exc:
        return None, f"HTTP error: {exc}", url


def get_html(session, browser, url, force_browser=False):
    if not force_browser:
        html, via, final_url = http_fetch(session, url)
        if html:
            return html, via, final_url

    return browser.fetch(url)


def jina_reader_fetch(session, url):
    """Fallback gratuito para sitios que bloquean IPs de GitHub Actions."""
    reader_url = f"{JINA_READER_PREFIX}{url}"

    try:
        response = session.get(
            reader_url,
            headers={
                "Accept": "text/plain",
                "X-No-Cache": "true",
                "X-Cache-Tolerance": "0",
                "X-Engine": "browser",
                "DNT": "1",
            },
            timeout=60,
            allow_redirects=True,
        )

        if response.status_code == 200 and len(response.text) > 200:
            return response.text, "Jina Reader (fresh)"

        return None, f"Jina Reader HTTP {response.status_code}"

    except requests.RequestException as exc:
        return None, f"Jina Reader error: {exc}"


def visible_text(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    return " ".join(soup.stripped_strings)


def has_eb05(text):
    return any(pattern.search(text or "") for pattern in EB05_PATTERNS)


def looks_blocked(text):
    return any(re.search(pattern, text or "", re.I) for pattern in BLOCKED_PATTERNS)


def structured_availability(html):
    lower_html = (html or "").lower()

    if re.search(
        r'availability["\s:]+[^}]{0,180}(outofstock|soldout)',
        lower_html,
        re.I,
    ):
        return "NO_DISPONIBLE"

    if re.search(
        r'availability["\s:]+[^}]{0,180}instock',
        lower_html,
        re.I,
    ):
        return "DISPONIBLE"

    return None


def detect_direct_status(html, text):
    structured = structured_availability(html)

    if structured:
        return structured

    unavailable = any(pattern.search(text or "") for pattern in UNAVAILABLE_PATTERNS)
    buy_signal = any(pattern.search(text or "") for pattern in BUY_PATTERNS)

    if unavailable:
        return "NO_DISPONIBLE"

    if buy_signal:
        return "DISPONIBLE"

    # No usamos "POSIBLE_STOCK": ausencia de una señal clara no equivale
    # a reposición y no debe generar falsos positivos.
    return "DESCONOCIDO"


def target_context_status(html, text):
    """
    Resuelve el stock de una ficha individual conocida.

    En una ficha directa sí podemos usar señales explícitas de toda la página
    como último fallback, porque ya sabemos que la URL corresponde a EB-05.
    En páginas de categoría NO se usa esta función.
    """
    structured = structured_availability(html)
    if structured:
        return structured

    soup = BeautifulSoup(html, "html.parser")

    # En una ficha individual conocida, un control de compra explícitamente
    # deshabilitado es una señal fuerte de no disponibilidad. Esto cubre
    # tiendas como Garhis, que muestran "Añadir a la cesta" pero desactivado.
    purchase_controls = soup.select(
        "button, input[type='submit'], a.add-to-cart, "
        "[data-button-action='add-to-cart']"
    )
    enabled_buy_control = False

    for node in purchase_controls:
        descriptor = " ".join(
            [
                " ".join(node.stripped_strings),
                node.get("title", "") or "",
                node.get("aria-label", "") or "",
                node.get("value", "") or "",
            ]
        )
        if not any(pattern.search(descriptor) for pattern in BUY_PATTERNS):
            continue

        classes = [str(x).lower() for x in (node.get("class") or [])]
        disabled = (
            node.has_attr("disabled")
            or str(node.get("aria-disabled", "")).lower() == "true"
            or "disabled" in classes
            or "is-disabled" in classes
        )

        if disabled:
            return "NO_DISPONIBLE"

        enabled_buy_control = True

    # Playwright inyecta además las señales del DOM ya renderizado como texto.
    # Si vemos un botón de compra seguido de "disabled", mantenemos el mismo
    # criterio aunque el atributo no estuviera presente en page.content().
    disabled_buy_patterns = (
        r"añadir\s+(?:a\s+la\s+)?cesta.{0,160}\bdisabled\b",
        r"añadir\s+(?:al\s+)?carrito.{0,160}\bdisabled\b",
        r"add\s+to\s+cart.{0,160}\bdisabled\b",
        r"buy\s+now.{0,160}\bdisabled\b",
    )
    if any(re.search(pattern, text or "", re.I | re.S) for pattern in disabled_buy_patterns):
        return "NO_DISPONIBLE"

    # Bloques habituales de disponibilidad/compra en Prestashop,
    # WooCommerce y plantillas similares.
    selectors = (
        "#product-availability",
        ".product-availability",
        "[itemprop='availability']",
        ".availability",
        ".stock",
        ".product-actions",
        ".product-add-to-cart",
        ".add-to-cart",
        ".product-information",
    )

    for selector in selectors:
        for node in soup.select(selector):
            node_text = " ".join(node.stripped_strings)
            if not node_text:
                continue

            if any(pattern.search(node_text) for pattern in UNAVAILABLE_PATTERNS):
                return "NO_DISPONIBLE"

            # Solo consideramos compra disponible si el elemento no está
            # deshabilitado de forma explícita.
            disabled = (
                node.has_attr("disabled")
                or node.get("aria-disabled") == "true"
                or "disabled" in (node.get("class") or [])
            )
            if not disabled and any(pattern.search(node_text) for pattern in BUY_PATTERNS):
                return "DISPONIBLE"

    # Segundo intento: una ventana amplia alrededor de cada aparición de EB-05.
    for pattern in EB05_PATTERNS:
        for match in pattern.finditer(text or ""):
            start = max(0, match.start() - 1800)
            end = min(len(text), match.end() + 3500)
            window = text[start:end]

            if any(p.search(window) for p in UNAVAILABLE_PATTERNS):
                return "NO_DISPONIBLE"

            if any(p.search(window) for p in BUY_PATTERNS):
                return "DISPONIBLE"

    # Último fallback SOLO para fichas individuales conocidas:
    # una señal explícita de agotado en la página tiene prioridad.
    if any(pattern.search(text or "") for pattern in UNAVAILABLE_PATTERNS):
        return "NO_DISPONIBLE"

    if enabled_buy_control:
        return "DISPONIBLE"

    # Para marcar disponible exigimos un control de compra accionable,
    # no solo la palabra "Comprar" perdida en recomendaciones o navegación.
    actionable_selectors = (
        "button:not([disabled])",
        "input[type='submit']:not([disabled])",
        "a.add-to-cart",
        "button.add-to-cart:not([disabled])",
        "[data-button-action='add-to-cart']:not([disabled])",
    )

    for selector in actionable_selectors:
        for node in soup.select(selector):
            node_text = " ".join(node.stripped_strings)
            descriptor = " ".join(
                [
                    node_text,
                    node.get("title", "") or "",
                    node.get("aria-label", "") or "",
                    node.get("value", "") or "",
                ]
            )

            if any(pattern.search(descriptor) for pattern in BUY_PATTERNS):
                return "DISPONIBLE"

    return "DESCONOCIDO"


def extract_price(text):
    if not text:
        return None

    patterns = (
        r"(?<!\d)(\d{1,4}(?:[.,]\d{2})?)\s*€",
        r"€\s*(\d{1,4}(?:[.,]\d{2})?)",
    )

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return f"{match.group(1).replace('.', ',')} €"

    return None


def same_site(url_a, url_b):
    try:
        a = urlparse(url_a).hostname or ""
        b = urlparse(url_b).hostname or ""
        return a.lower().removeprefix("www.") == b.lower().removeprefix("www.")
    except Exception:
        return False


def best_product_link(node, base_url):
    anchors = list(node.find_all("a", href=True))

    # Primero preferimos un enlace cuyo texto/href también identifique EB-05.
    for anchor in anchors:
        href = urljoin(base_url, anchor.get("href", ""))
        descriptor = " ".join(
            [
                anchor.get_text(" ", strip=True),
                anchor.get("title", "") or "",
                href,
            ]
        )
        if has_eb05(descriptor) and same_site(base_url, href):
            return href

    # Si la tarjeta ya es inequívocamente EB-05, usamos su primer enlace interno.
    for anchor in anchors:
        href = urljoin(base_url, anchor.get("href", ""))
        if href.startswith(("http://", "https://")) and same_site(base_url, href):
            return href

    return None


def extract_eb05_candidate(html, page_url):
    """
    Devuelve la tarjeta/ficha concreta de EB-05 si aparece en el catálogo.
    Analizamos la tarjeta, no todo el documento, para evitar que el stock de
    productos recomendados contamine el resultado.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = set()

    for selector in PRODUCT_NODE_SELECTORS:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)

            text = " ".join(node.stripped_strings)
            hrefs = " ".join(
                urljoin(page_url, a.get("href", ""))
                for a in node.find_all("a", href=True)
            )

            if not has_eb05(f"{text} {hrefs}"):
                continue

            product_url = best_product_link(node, page_url) or page_url
            return {
                "product_url": product_url,
                "product_name": text[:220] if text else "One Piece EB-05",
                "price": extract_price(text),
                "status": detect_direct_status(str(node), text),
                "source_url": page_url,
            }

    # Algunas tiendas no usan tarjetas de producto reconocibles. En ese caso
    # buscamos un enlace individual que contenga EB-05.
    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, anchor.get("href", ""))
        descriptor = " ".join(
            [
                anchor.get_text(" ", strip=True),
                anchor.get("title", "") or "",
                href,
            ]
        )

        if not has_eb05(descriptor) or not same_site(page_url, href):
            continue

        parent = anchor
        for _ in range(4):
            if not getattr(parent, "parent", None):
                break
            parent = parent.parent
            parent_text = " ".join(parent.stripped_strings)
            if len(parent_text) >= 80:
                break

        block_text = " ".join(parent.stripped_strings)
        block_html = str(parent)
        return {
            "product_url": href,
            "product_name": anchor.get_text(" ", strip=True)[:220]
            or block_text[:220]
            or "One Piece EB-05",
            "price": extract_price(block_text),
            "status": detect_direct_status(block_html, block_text),
            "source_url": page_url,
        }

    # Último fallback: detectamos el texto y devolvemos la propia página.
    page_text = visible_text(html)
    for pattern in EB05_PATTERNS:
        match = pattern.search(page_text)
        if match:
            start = max(0, match.start() - 550)
            end = min(len(page_text), match.end() + 650)
            window = page_text[start:end]
            return {
                "product_url": page_url,
                "product_name": window[:220],
                "price": extract_price(window),
                "status": detect_direct_status(window, window),
                "source_url": page_url,
            }

    return None


def find_next_page(html, current_url):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    candidates.extend(soup.select('a[rel~="next"][href]'))
    candidates.extend(
        soup.select(
            "a.next[href], a.page-next[href], "
            ".pagination-next a[href], .next a[href], "
            "li.next a[href], a[aria-label*='Next'][href], "
            "a[aria-label*='Siguiente'][href]"
        )
    )

    if not candidates:
        for anchor in soup.find_all("a", href=True):
            label = " ".join(
                [
                    anchor.get_text(" ", strip=True),
                    anchor.get("aria-label", "") or "",
                    anchor.get("title", "") or "",
                ]
            ).strip()
            if re.fullmatch(r"(siguiente|next|›|»|>)", label, re.I):
                candidates.append(anchor)

    for anchor in candidates:
        next_url = urljoin(current_url, anchor.get("href", ""))
        if same_site(current_url, next_url) and next_url != current_url:
            return next_url

    return None


def validate_catalog(html, text, config, final_url):
    if looks_blocked(text):
        return False, "página anti-bot/captcha"

    # No aceptamos una redirección hacia otro dominio.
    expected_url = config.get("url", "")
    if final_url and expected_url and not same_site(expected_url, final_url):
        return False, f"redirección inesperada a {final_url}"

    # Rechazamos errores evidentes, aunque el servidor responda HTTP 200.
    error_patterns = (
        r"\b404\b.{0,80}(not found|no encontrado|página no encontrada)",
        r"(not found|no encontrado|página no encontrada).{0,80}\b404\b",
        r"service unavailable",
        r"temporarily unavailable",
    )
    if any(re.search(pattern, text or "", re.I | re.S) for pattern in error_patterns):
        return False, "la tienda devolvió una página de error"

    required = config.get("required_patterns", [])
    if not required or any(re.search(pattern, text or "", re.I) for pattern in required):
        return True, None

    # La URL canónica también sirve como identidad del catálogo. Por ejemplo
    # /one-piece equivale al encabezado "One Piece" aunque el HTML dinámico no
    # repita literalmente ese texto.
    url_identity = re.sub(
        r"[-_+%/]+",
        " ",
        (final_url or expected_url or "").lower(),
    )
    if required and any(re.search(pattern, url_identity, re.I) for pattern in required):
        if len(text or "") >= 300:
            return True, None

    # Muchas tiendas cargan partes del catálogo por JS o cambian el encabezado.
    # Si seguimos en el dominio correcto y el DOM tiene estructura real de
    # catálogo/productos/paginación, la consideramos una respuesta válida.
    soup = BeautifulSoup(html or "", "html.parser")
    structural_selectors = (
        "article",
        ".product",
        ".products",
        ".product-item",
        ".product-miniature",
        ".js-product-miniature",
        ".woocommerce-loop-product",
        "li.product",
        ".pagination",
        "nav.pagination",
        "a[rel~='next']",
    )

    if any(soup.select_one(selector) for selector in structural_selectors):
        return True, None

    # Último criterio: contenido sustancial en el dominio correcto. Es mejor
    # seguir buscando y no declarar un falso fallo por una cabecera dinámica.
    if len(text or "") >= 1200 and final_url and same_site(expected_url, final_url):
        return True, None

    return False, "respondió, pero no pude validar estructura de catálogo"


def discover_eb05(session, browser, store, config):
    """
    Recorre la paginación real del catálogo hasta max_pages.
    Si encuentra EB-05 devuelve su URL individual, nombre, precio y stock.
    """
    current_url = config["url"]
    visited = set()
    max_pages = config.get("max_pages", 8)
    force_browser = config.get("force_browser", False)
    pages_checked = 0
    last_via = ""

    while current_url and current_url not in visited and pages_checked < max_pages:
        visited.add(current_url)
        pages_checked += 1

        html, via, final_url = get_html(
            session,
            browser,
            current_url,
            force_browser=force_browser,
        )
        last_via = via

        if not html:
            return {
                "ok": False,
                "connected": False if pages_checked == 1 else True,
                "healthy": False,
                "note": f"falló página {pages_checked} ({via})",
                "pages_checked": pages_checked,
            }

        text = visible_text(html)
        valid, problem = validate_catalog(
            html,
            text,
            config,
            final_url or current_url,
        )

        if not valid and not via.startswith("Playwright"):
            browser_html, browser_via, browser_final_url = browser.fetch(current_url)
            if browser_html:
                browser_text = visible_text(browser_html)
                browser_valid, browser_problem = validate_catalog(
                    browser_html,
                    browser_text,
                    config,
                    browser_final_url or current_url,
                )
                if browser_valid:
                    html = browser_html
                    text = browser_text
                    via = browser_via
                    final_url = browser_final_url
                    valid = True
                    problem = None
                else:
                    problem = browser_problem

        if not valid:
            return {
                "ok": False,
                "connected": True,
                "healthy": False,
                "note": problem,
                "via": via,
                "pages_checked": pages_checked,
            }

        candidate = extract_eb05_candidate(html, final_url or current_url)
        if candidate:
            candidate.update(
                {
                    "ok": True,
                    "connected": True,
                    "healthy": True,
                    "via": via,
                    "pages_checked": pages_checked,
                }
            )
            return candidate

        next_url = find_next_page(html, final_url or current_url)
        if not next_url or next_url in visited:
            return {
                "ok": True,
                "connected": True,
                "healthy": True,
                "candidate": None,
                "via": via,
                "pages_checked": pages_checked,
            }

        current_url = next_url

    # Si llegamos al límite con otra página pendiente, no afirmamos BUSCANDO
    # como resultado completo: la exploración ha quedado incompleta.
    if current_url and current_url not in visited:
        return {
            "ok": False,
            "connected": True,
            "healthy": False,
            "note": f"límite de paginación alcanzado ({max_pages} páginas)",
            "via": last_via,
            "pages_checked": pages_checked,
        }

    return {
        "ok": True,
        "connected": True,
        "healthy": True,
        "candidate": None,
        "via": last_via,
        "pages_checked": pages_checked,
    }


def analyze_known_product(session, browser, url, force_browser=False):
    html, via, final_url = get_html(
        session,
        browser,
        url,
        force_browser=force_browser,
    )

    if not html:
        return None, via, final_url

    text = visible_text(html)

    if looks_blocked(text):
        return None, f"{via}; anti-bot/captcha", final_url

    # Una ficha EB-05 conocida debe seguir identificando el producto.
    # El URL también cuenta porque algunas tiendas renderizan el nombre por JS.
    if not has_eb05(f"{text} {final_url or url}"):
        return None, f"{via}; contenido inesperado", final_url

    candidate = extract_eb05_candidate(html, final_url or url)
    page_status = target_context_status(html, text)

    if candidate:
        # Para fichas conocidas damos prioridad a la disponibilidad de la
        # propia página (JSON-LD / contexto EB-05) sobre una tarjeta/anchor
        # demasiado estrecha.
        if page_status != "DESCONOCIDO":
            candidate["status"] = page_status
        if not candidate.get("price"):
            candidate["price"] = extract_price(text)

        if candidate.get("status") != "DESCONOCIDO":
            return candidate, via, final_url

    elif page_status != "DESCONOCIDO":
        return {
            "product_url": final_url or url,
            "product_name": "One Piece EB-05",
            "price": extract_price(text),
            "status": page_status,
            "source_url": final_url or url,
        }, via, final_url

    # Si el navegador/HTML cargó la ficha pero no conseguimos resolver stock,
    # hacemos un último intento textual gratuito desde otra infraestructura.
    reader_text, reader_via = jina_reader_fetch(session, final_url or url)
    reader_candidate = detect_known_product_from_reader(
        reader_text,
        final_url or url,
    )
    if reader_candidate:
        return reader_candidate, f"{via} + {reader_via}", final_url

    if candidate:
        return candidate, via, final_url

    return {
        "product_url": final_url or url,
        "product_name": "One Piece EB-05",
        "price": extract_price(text),
        "status": page_status,
        "source_url": final_url or url,
    }, via, final_url


def detect_known_product_from_reader(text, url):
    """
    Fallback textual para una ficha individual conocida.
    Como la URL ya es del EB-05, aquí sí podemos usar señales explícitas de
    toda la respuesta sin confundirnos con otro producto del catálogo.
    """
    if not text or not has_eb05(f"{text} {url}"):
        return None

    status = detect_direct_status(text, text)
    if status == "DESCONOCIDO":
        return None

    return {
        "product_url": url,
        "product_name": "One Piece EB-05",
        "price": extract_price(text),
        "status": status,
        "source_url": url,
    }


def detect_gameria_from_reader(text):
    for pattern in EB05_PATTERNS:
        match = pattern.search(text or "")
        if match:
            start = max(0, match.start() - 700)
            end = min(len(text), match.end() + 900)
            window = text[start:end]
            return {
                "product_url": DIRECT_PRODUCTS["GAMERIA"],
                "product_name": "One Piece EB-05",
                "price": extract_price(window),
                "status": detect_direct_status(window, window),
                "source_url": GAMERIA_CATEGORY_URL,
            }

    return None


def state_signature(entry):
    return (
        entry.get("mode"),
        entry.get("status"),
        entry.get("url"),
        entry.get("product_url"),
        entry.get("product_name"),
        entry.get("price"),
    )


def build_state_entry(
    mode,
    status,
    url,
    previous,
    product_url=None,
    product_name=None,
    price=None,
):
    entry = {
        "mode": mode,
        "status": status,
        "url": url,
    }

    if product_url:
        entry["product_url"] = product_url
    if product_name:
        entry["product_name"] = product_name
    if price:
        entry["price"] = price

    previous_signature = state_signature(previous)
    new_signature = state_signature(entry)

    if previous_signature == new_signature and previous.get("last_changed"):
        entry["last_changed"] = previous["last_changed"]
    else:
        entry["last_changed"] = utc_now()

    return entry


def notify_if_transition(store, previous, new_entry):
    old_status = previous.get("status")
    new_status = new_entry.get("status")
    old_mode = previous.get("mode")
    new_mode = new_entry.get("mode")
    old_product_url = previous.get("product_url")
    new_product_url = new_entry.get("product_url")
    url = new_product_url or new_entry.get("url")
    price = new_entry.get("price")
    price_line = f"\n💶 {price}" if price else ""

    product_appeared = (
        new_mode == "discovered_product"
        and (
            old_mode != "discovered_product"
            or (new_product_url and old_product_url != new_product_url)
        )
    )

    # Importante: si la primera lectura ya encuentra una ficha disponible,
    # avisamos en lugar de convertirla silenciosamente en baseline.
    if not previous or old_status is None:
        if new_status == "DISPONIBLE":
            send_telegram(
                f"🚨 ONE PIECE EB-05 DISPONIBLE\n\n"
                f"🏪 {store}\n"
                f"✅ Primera lectura y ya hay señales de compra/stock."
                f"{price_line}\n\n{url}"
            )
        elif new_mode == "discovered_product":
            send_telegram(
                f"🆕 EB-05 DETECTADO EN UNA TIENDA\n\n"
                f"🏪 {store}\n"
                f"Estado inicial: {new_status}"
                f"{price_line}\n\n{url}"
            )
        return

    if product_appeared:
        if new_status == "DISPONIBLE":
            send_telegram(
                f"🚨 NUEVA FICHA EB-05 Y ESTÁ DISPONIBLE\n\n"
                f"🏪 {store}\n"
                f"✅ Se ha descubierto la ficha del producto y tiene señales de compra."
                f"{price_line}\n\n{url}"
            )
        else:
            send_telegram(
                f"🆕 EB-05 HA APARECIDO EN UNA TIENDA\n\n"
                f"🏪 {store}\n"
                f"Estado detectado: {new_status}"
                f"{price_line}\n\n{url}"
            )
        return

    if old_status == new_status:
        return

    if new_status == "DISPONIBLE":
        send_telegram(
            f"🚨 ONE PIECE EB-05 DISPONIBLE\n\n"
            f"🏪 {store}\n"
            f"✅ Se detectan señales de compra/stock."
            f"{price_line}\n\n{url}"
        )

    # DESCONOCIDO no genera alerta de reposición: evitamos falsos positivos.


STATUS_LABELS = {
    "NO_DISPONIBLE": "sin stock",
    "DISPONIBLE": "DISPONIBLE",
    "DESCONOCIDO": "estado no concluyente",
    "BUSCANDO": "buscando EB-05",
}


def status_report_due(state):
    meta = state.get("_meta", {})
    last_report = meta.get("last_status_report")

    if not last_report:
        return True

    try:
        last_dt = datetime.fromisoformat(last_report)
    except (TypeError, ValueError):
        return True

    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)

    return datetime.now(timezone.utc) - last_dt >= timedelta(
        hours=STATUS_REPORT_INTERVAL_HOURS
    )


def build_status_report(results):
    total = len(DIRECT_PRODUCTS) + len(DISCOVERY_PAGES)
    healthy = sum(1 for item in results.values() if item.get("healthy"))
    connected = sum(1 for item in results.values() if item.get("connected"))

    if healthy == total:
        headline = "✅ Todo funciona correctamente y todas las páginas responden."
    elif connected == total:
        headline = (
            f"⚠️ El monitor conecta con las {total} tiendas, "
            f"pero {total - healthy} comprobación(es) no pudieron validarse del todo."
        )
    else:
        headline = (
            f"⚠️ El monitor está activo. {connected}/{total} tiendas respondieron; "
            f"{total - connected} no respondieron correctamente."
        )

    lines = ["🩺 ESTADO MONITOR ONE PIECE EB-05", "", headline, ""]

    ordered_stores = list(DIRECT_PRODUCTS.keys()) + list(DISCOVERY_PAGES.keys())

    for store in ordered_stores:
        item = results.get(store)

        if not item:
            lines.append(f"⚠️ {store} — sin resultado en esta ejecución")
            continue

        if item.get("healthy"):
            status = STATUS_LABELS.get(item.get("status"), item.get("status", "OK"))
            via = item.get("via", "")
            pages = item.get("pages_checked")
            pages_text = f" · {pages} pág." if pages and pages > 1 else ""
            price = item.get("price")
            price_text = f" · {price}" if price else ""
            via_text = f" · {via}" if via else ""
            lines.append(
                f"✅ {store} — {status}{price_text}{pages_text}{via_text}"
            )
        elif item.get("connected"):
            note = item.get("note", "respuesta recibida, pero no validada")
            lines.append(f"⚠️ {store} — {note}")
        else:
            note = item.get("note", "sin conexión")
            lines.append(f"❌ {store} — {note}")

    lines.extend(
        [
            "",
            "🔎 Catálogos: búsqueda con paginación + seguimiento de ficha detectada",
            f"📋 Informe de estado: cada {STATUS_REPORT_INTERVAL_HOURS} horas",
        ]
    )

    return "\n".join(lines)


def update_store_state(state, store, new_entry):
    previous = state.get(store, {})
    notify_if_transition(store, previous, new_entry)

    if previous != new_entry:
        state[store] = new_entry
        return True

    return False


def monitor_direct_store(session, browser, store, url, state, run_results):
    previous = state.get(store, {})

    candidate, via, final_url = analyze_known_product(
        session,
        browser,
        url,
        force_browser=False,
    )

    # Gameria tiene un tratamiento especial porque actualmente corta
    # conexiones provenientes de GitHub Actions.
    if candidate is None and store == "GAMERIA":
        first_error = via
        html, category_via, category_final_url = get_html(
            session,
            browser,
            GAMERIA_CATEGORY_URL,
            force_browser=False,
        )

        if html:
            text = visible_text(html)

            if not looks_blocked(text):
                candidate = extract_eb05_candidate(
                    html,
                    category_final_url or GAMERIA_CATEGORY_URL,
                )
                if candidate:
                    via = category_via
                    print("ℹ️ GAMERIA: usando categoría One Piece como fallback")

        if candidate is None:
            reader_text, reader_via = jina_reader_fetch(session, GAMERIA_CATEGORY_URL)

            if reader_text:
                candidate = detect_gameria_from_reader(reader_text)
                if candidate:
                    via = reader_via

        if candidate is None:
            print(
                f"❓ {store}: no se pudo analizar ficha/categoría/Reader "
                f"({first_error}; categoría: {category_via}; reader: {reader_via})"
            )
            run_results[store] = {
                "connected": False,
                "healthy": False,
                "note": "Gameria no es accesible desde GitHub Actions",
            }
            return False

    if candidate is None:
        print(f"❓ {store}: no se pudo analizar ({via})")
        run_results[store] = {
            "connected": False,
            "healthy": False,
            "note": f"no respondió o contenido inesperado ({via})",
        }
        return False

    new_entry = build_state_entry(
        mode="direct",
        status=candidate["status"],
        url=candidate.get("product_url") or final_url or url,
        previous=previous,
        product_url=candidate.get("product_url") or final_url or url,
        product_name=candidate.get("product_name"),
        price=candidate.get("price"),
    )

    if new_entry["status"] == "DESCONOCIDO":
        print(
            f"❓ {store}: ficha cargada pero el runner no puede resolver "
            f"el estado de stock [{via}]"
        )
        run_results[store] = {
            "connected": True,
            "healthy": False,
            "status": "DESCONOCIDO",
            "via": via,
            "note": "ficha accesible, pero el stock no es visible desde GitHub Actions",
        }
        # No sustituimos un estado fiable anterior por uno no concluyente.
        return False

    print(f"{store}: {new_entry['status']} [{via}]")
    run_results[store] = {
        "connected": True,
        "healthy": True,
        "status": new_entry["status"],
        "via": via,
        "price": new_entry.get("price"),
    }

    return update_store_state(state, store, new_entry)


def monitor_discovery_store(session, browser, store, config, state, run_results):
    previous = state.get(store, {})

    # Si en una ejecución anterior ya descubrimos la ficha concreta,
    # primero la vigilamos directamente. Si desaparece o falla, volvemos
    # automáticamente al catálogo y la buscamos de nuevo.
    previous_product_url = previous.get("product_url")
    if previous.get("mode") == "discovered_product" and previous_product_url:
        candidate, via, _ = analyze_known_product(
            session,
            browser,
            previous_product_url,
            force_browser=False,
        )

        if candidate:
            new_entry = build_state_entry(
                mode="discovered_product",
                status=candidate["status"],
                url=config["url"],
                previous=previous,
                product_url=candidate.get("product_url") or previous_product_url,
                product_name=candidate.get("product_name")
                or previous.get("product_name"),
                price=candidate.get("price"),
            )

            print(
                f"{store}: {new_entry['status']} "
                f"[ficha descubierta · {via}]"
            )
            run_results[store] = {
                "connected": True,
                "healthy": True,
                "status": new_entry["status"],
                "via": f"ficha directa · {via}",
                "price": new_entry.get("price"),
            }

            return update_store_state(state, store, new_entry)

        print(
            f"ℹ️ {store}: la ficha guardada no pudo verificarse; "
            "se vuelve a recorrer el catálogo."
        )

    discovery = discover_eb05(session, browser, store, config)

    if not discovery.get("ok"):
        print(f"❓ {store}: {discovery.get('note')}")
        run_results[store] = {
            "connected": discovery.get("connected", False),
            "healthy": False,
            "via": discovery.get("via", ""),
            "note": discovery.get("note", "búsqueda incompleta"),
            "pages_checked": discovery.get("pages_checked"),
        }
        return False

    candidate = discovery.get("candidate")

    # candidate también puede venir directamente en el dict de discovery.
    if discovery.get("product_url"):
        candidate = discovery

    if candidate:
        new_entry = build_state_entry(
            mode="discovered_product",
            status=candidate["status"],
            url=config["url"],
            previous=previous,
            product_url=candidate.get("product_url"),
            product_name=candidate.get("product_name"),
            price=candidate.get("price"),
        )

        print(
            f"{store}: EB-05 encontrado → {new_entry['status']} "
            f"[{discovery.get('via')} · pág. {discovery.get('pages_checked')}]"
        )
        run_results[store] = {
            "connected": True,
            "healthy": True,
            "status": new_entry["status"],
            "via": discovery.get("via", ""),
            "price": new_entry.get("price"),
            "pages_checked": discovery.get("pages_checked"),
        }

        return update_store_state(state, store, new_entry)

    new_entry = build_state_entry(
        mode="discovery",
        status="BUSCANDO",
        url=config["url"],
        previous=previous,
    )

    print(
        f"{store}: BUSCANDO "
        f"[{discovery.get('via')} · {discovery.get('pages_checked')} pág.]"
    )
    run_results[store] = {
        "connected": True,
        "healthy": True,
        "status": "BUSCANDO",
        "via": discovery.get("via", ""),
        "pages_checked": discovery.get("pages_checked"),
    }

    return update_store_state(state, store, new_entry)


def main():
    state = load_state()
    changed = False
    run_results = {}
    session = build_http_session()
    browser = BrowserFetcher()

    print(f"=== EB-05 monitor | {utc_now()} ===")

    try:
        if SEND_TEST_NOTIFICATION:
            send_telegram(
                "✅ Test correcto: el monitor EB-05 puede enviarte avisos por Telegram."
            )

        for store, url in DIRECT_PRODUCTS.items():
            if monitor_direct_store(
                session,
                browser,
                store,
                url,
                state,
                run_results,
            ):
                changed = True

        for store, config in DISCOVERY_PAGES.items():
            if monitor_discovery_store(
                session,
                browser,
                store,
                config,
                state,
                run_results,
            ):
                changed = True

        if status_report_due(state):
            report = build_status_report(run_results)
            print("📋 Informe de estado periódico:")
            print(report)

            if send_telegram(report):
                meta = state.setdefault("_meta", {})
                meta["last_status_report"] = utc_now()
                changed = True
                print("✅ Informe periódico enviado y registrado.")
            else:
                print("⚠️ Informe periódico pendiente; se reintentará.")

        save_state(state)

        if changed:
            print("💾 state.json actualizado.")
        else:
            print("Sin cambios de estado.")

        return 0

    finally:
        browser.close()
        session.close()


if __name__ == "__main__":
    sys.exit(main())
