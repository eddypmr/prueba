"""HeroFreaks: detección conservadora de Booster Boxes EN en WooCommerce.

Solo la ficha real puede confirmar stock. Catálogos, preventas y
productos recomendados nunca generan alertas.
"""
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from product_guard import is_english_display, preorder_marker

ROOT = "https://herofreaks.com"
CATALOGS = (
    ROOT + "/one-piece-card-game/",
    ROOT + "/proximamente/",
)
SETS = {"EB05": "EB-05", "OP18": "OP-18"}
# El 29/10/2026 GitHub Actions recibió HTTP 403 en ambos catálogos.
# Reintentamos en cada ejecución: si persiste el bloqueo, el resultado será
# DESCONOCIDO y nunca se notificará stock sin validar la ficha real.
PAUSED_FROM_GITHUB = False
TARGET = {
    "EB05": re.compile(r"(?<![a-z0-9])eb[\s_-]*0?5(?![a-z0-9])", re.I),
    "OP18": re.compile(r"(?<![a-z0-9])op[\s_-]*0?18(?![a-z0-9])", re.I),
}
BOX = re.compile(r"\b(?:booster[\s-]*box|(?:extra\s+)?booster\s+display|display\s+booster)\b", re.I)
INVALID = re.compile(
    r"\b(?:case|sobres?\s+individual(?:es)?|booster\s+pack|starter|"
    r"japon[eé]s|japanese|desprecintad[ao]s?)\b", re.I
)


def is_target_listing(title, code):
    return bool(
        TARGET[code].search(title or "")
        and BOX.search(title or "")
        and not INVALID.search(title or "")
    )


def same_shop(url):
    try:
        return urlparse(url).scheme == "https" and (
            urlparse(url).hostname or ""
        ).lower().removeprefix("www.") == "herofreaks.com"
    except ValueError:
        return False


def find_product_link(html, page_url, code):
    """Busca enlace de ficha dentro de una tarjeta o un título de producto."""
    soup = BeautifulSoup(html or "", "html.parser")
    selectors = (
        "li.product", "article.product", ".product-small",
        ".products .product", ".woocommerce ul.products li",
    )
    for selector in selectors:
        for card in soup.select(selector):
            heading = card.select_one(
                "h2.woocommerce-loop-product__title, "
                "h2.product-title, h3.product-title, h2, h3"
            )
            title = heading.get_text(" ", strip=True) if heading else ""
            if not title:
                title = card.get_text(" ", strip=True)[:300]
            if not is_target_listing(title, code):
                continue
            for a in card.select("a[href]"):
                url = urljoin(page_url, a["href"])
                if same_shop(url) and "/comprar/" in urlparse(url).path:
                    return url
    # Títulos con enlace pero estructura de catálogo distinta.
    for anchor in soup.select("a[href]"):
        title = anchor.get_text(" ", strip=True)
        if not is_target_listing(title, code):
            continue
        url = urljoin(page_url, anchor["href"])
        if same_shop(url) and "/comprar/" in urlparse(url).path:
            return url
    return None


def analyze_product(html, url, code):
    """Disponible SOLO con un producto EN verificado y compra habilitada."""
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.select_one("h1.product_title, h1.entry-title, h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    if not is_target_listing(title, code):
        return "DESCONOCIDO", None

    details = soup.select_one(
        "table.woocommerce-product-attributes, "
        ".woocommerce-product-attributes, .product_meta"
    )
    details_text = details.get_text(" ", strip=True) if details else ""
    # HeroFreaks suele poner «Idioma: English» en atributos del producto.
    identity = f"{title} {details_text} {url}"
    if not is_english_display(identity, code):
        return "DESCONOCIDO", title

    summary = soup.select_one("div.summary, .summary.entry-summary")
    summary_text = summary.get_text(" ", strip=True) if summary else ""
    # Detectar etiquetas en el contexto del PRODUCTO, no banners globales.
    badges = soup.select("div.product .preventa, div.product .preorder, "
                         "div.product .product-label, div.product span.onsale")
    badge_text = " ".join(n.get_text(" ", strip=True) for n in badges)
    if preorder_marker(f"<h1>{title}</h1>", summary_text) or re.search(
        r"\b(?:preventa|pre[\s-]?order|reserva)\b", badge_text, re.I
    ):
        return "PREVENTA", title

    product = soup.select_one("div.product.type-product, div.product")
    if product is None:
        return "DESCONOCIDO", title
    stock = product.select_one("p.stock, .stock.out-of-stock, .stock.in-stock")
    stock_text = stock.get_text(" ", strip=True) if stock else ""
    out_of_stock = bool(
        stock and (
            "out-of-stock" in (stock.get("class") or [])
            or re.search(r"\b(?:sin existencias|agotado|sin stock|out of stock)\b",
                         stock_text, re.I)
        )
    )
    if out_of_stock or "outofstock" in product.get("class", []):
        return "NO_DISPONIBLE", title
    if re.search(r"\b(?:av[ií]same cuando est[eé] disponible|sin existencias)\b",
                 summary_text, re.I):
        return "NO_DISPONIBLE", title

    # Este botón debe ser el de la ficha, no la cabecera/recomendaciones.
    btn = product.select_one(
        "form.cart button.single_add_to_cart_button, "
        "form.cart button[name='add-to-cart']"
    )
    if btn and not btn.has_attr("disabled") and not (
        btn.get("aria-disabled") == "true"
        or any("disabled" in str(v).lower() for v in btn.get("class", []))
    ):
        return "DISPONIBLE", title
    return "DESCONOCIDO", title


def diagnose_page(html, code):
    """Diagnóstico agregado, sin registrar contenido de la página."""
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body = soup.get_text(" ", strip=True)
    challenge = bool(re.search(
        r"just a moment|checking your browser|verify you are human|"
        r"attention required|cf-challenge|captcha|access denied|"
        r"comprobando (?:tu|su) navegador|verifica que eres humano",
        (title + " " + body[:2500] + " " + (html or "")[:4000]).lower()
    ))
    cards = len(soup.select("li.product, article.product, .products .product"))
    products = len(soup.select("div.product.type-product, form.cart"))
    links = len(soup.select('a[href*="/comprar/"]'))
    if challenge:
        kind = "ANTIBOT"
    elif cards or products or links:
        kind = "CATALOGO_O_FICHA"
    elif not html or len(html) < 1000:
        kind = "HTML_INCOMPLETO"
    else:
        kind = "SIN_ESTRUCTURA_PRODUCTOS"
    return kind, cards, products, links


def check_herofreaks(session, code, browser=None):
    """Busca producto y comprueba ficha; errores nunca eliminan stock histórico."""
    if PAUSED_FROM_GITHUB:
        print(f"🔎 HEROFREAKS_{code}: PAUSADO (HTTP 403 desde GitHub; revisar manual)")
        return {"ok": False, "status": "DESCONOCIDO", "url": CATALOGS[0],
                "reason": "Bloqueo HTTP 403 desde GitHub"}
    product_url = None
    at_least_one_catalog = False

    def fetch_page(url):
        try:
            response = session.get(url, timeout=12)
            if response.status_code == 200 and same_shop(response.url):
                return response.text, response.url, "HTTP"
            print(f"🔎 HEROFREAKS_{code}: HTTP {response.status_code}")
            if response.status_code != 403 or browser is None:
                return None, url, "HTTP"
        except Exception as exc:
            print(f"🔎 HEROFREAKS_{code}: error HTTP {type(exc).__name__}")
            return None, url, "HTTP"

        html, via, final_url = browser.fetch(url)
        if html:
            kind, cards, products, links = diagnose_page(html, code)
            print(f"🩺 HEROFREAKS_{code}: {kind} "
                  f"(tarjetas={cards}, fichas={products}, enlaces={links}, "
                  f"bytes={len(html)}, origen={via})")
            if kind == "ANTIBOT":
                return None, url, via
        if html and same_shop(final_url) and len(html) > 1000:
            print(f"🔎 HEROFREAKS_{code}: fallback HTML recibido ({via})")
            return html, final_url, via
        print(f"🔎 HEROFREAKS_{code}: fallback sin acceso verificable ({via})")
        return None, url, via
    for url in CATALOGS:
        html, final_url, via = fetch_page(url)
        if not html or "one piece" not in html.lower() or len(html) < 1000:
            continue
        kind, cards, products, links = diagnose_page(html, code)
        if kind != "CATALOGO_O_FICHA":
            print(f"🩺 HEROFREAKS_{code}: catálogo no verificable ({kind})")
            continue
        at_least_one_catalog = True
        product_url = find_product_link(html, final_url, code)
        if product_url:
            break
    if not product_url:
        if at_least_one_catalog:
            return {"ok": True, "status": "BUSCANDO", "url": CATALOGS[0]}
        return {"ok": False, "status": "DESCONOCIDO", "url": CATALOGS[0]}
    html, final_url, via = fetch_page(product_url)
    if not html:
        return {"ok": False, "status": "DESCONOCIDO", "url": product_url}
    status, title = analyze_product(html, final_url, code)
    return {"ok": status != "DESCONOCIDO", "status": status,
            "url": final_url, "name": title, "via": via}
