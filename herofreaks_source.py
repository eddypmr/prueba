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
# Ficha real facilitada por el usuario. Sin query params, cookies ni sesión.
DIRECT_PRODUCT_URLS = {
    "EB05": (ROOT + "/comprar/juegos-de-cartas/one-piece-card-game/"
             "extra-booster-display-heroines-edition-vol-2-eb-05-one-piece-card-game/"),
}

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
    """Solo la ficha principal: nunca botones de productos relacionados."""
    soup = BeautifulSoup(html or "", "html.parser")
    product = soup.select_one(
        "div.elementor-location-single.product.type-product, "
        "div.product.type-product"
    )
    if product is None:
        return "DESCONOCIDO", None

    h1 = product.select_one("h1.product_title, h1.entry-title")
    title = h1.get_text(" ", strip=True) if h1 else ""
    if not is_target_listing(title, code):
        return "DESCONOCIDO", None

    details = product.select_one(
        "table.woocommerce-product-attributes, "
        ".woocommerce-product-attributes, .product_meta"
    )
    details_text = details.get_text(" ", strip=True) if details else ""
    if not is_english_display(f"{title} {details_text} {url}", code):
        return "DESCONOCIDO", title

    # El HTML real de Elementor tiene la clase outofstock en el contenedor
    # principal y el mensaje dentro del widget del botón de compra.
    purchase_widget = product.select_one(
        ".elementor-widget-woocommerce-product-add-to-cart"
    )
    purchase_area = purchase_widget or product
    stock = purchase_area.select_one("p.stock")
    stock_text = stock.get_text(" ", strip=True) if stock else ""
    out_of_stock = (
        "outofstock" in product.get("class", [])
        or (stock is not None and (
            "out-of-stock" in stock.get("class", [])
            or bool(re.search(
                r"\b(?:sin existencias|agotad[oa]|sin stock|out of stock)\b",
                stock_text, re.I
            ))
        ))
    )
    if out_of_stock:
        return "NO_DISPONIBLE", title

    # No confundir el formulario de lista de espera con un botón de compra.
    if purchase_area.select_one(".yith-wcwtl-output"):
        return "NO_DISPONIBLE", title

    summary = product.select_one(
        "div.summary, .summary.entry-summary, "
        ".woocommerce-product-details__short-description"
    )
    summary_text = summary.get_text(" ", strip=True) if summary else ""
    badge_nodes = product.select(
        ".jet-listing-dynamic-field__content, "
        ".elementor-button-text, .preventa, .preorder"
    )
    badge_preorder = any(re.search(
        r"^\s*(?:preventa|pre[\s-]?order|reserva)\b",
        el.get_text(" ", strip=True), re.I
    ) for el in badge_nodes)
    if badge_preorder or preorder_marker(f"<h1>{title}</h1>", summary_text):
        return "PREVENTA", title

    # Requiere botón habilitado dentro del formulario cart de ESTE producto.
    # Los a.add_to_cart_button de recomendaciones quedan fuera.
    btn = purchase_area.select_one(
        "form.cart button.single_add_to_cart_button, "
        "form.cart button[name='add-to-cart']"
    )
    if (btn and not btn.has_attr("disabled")
            and btn.get("aria-disabled") != "true"
            and not any("disabled" in str(v).lower()
                        for v in btn.get("class", []))):
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


def check_herofreaks(session, code, browser=None, direct_url=None):
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
    # Primero la ficha EB-05 exacta: evita depender de catálogos bloqueados.
    if direct_url and same_shop(direct_url):
        html, final_url, via = fetch_page(direct_url)
        if html:
            status, title = analyze_product(html, final_url, code)
            if status != "DESCONOCIDO":
                print(f"🔎 HEROFREAKS_{code}: ficha directa → {status} ({via})")
                return {"ok": True, "status": status, "url": final_url,
                        "name": title, "via": via}
            print(f"🔎 HEROFREAKS_{code}: ficha directa sin stock verificable")

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
