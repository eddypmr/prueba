"""Monitor de displays ingleses One Piece en Saruman Games (Shopify).

Lee exclusivamente su catálogo público. Shopify "available" es comprabilidad,
no necesariamente entrega inmediata: las preventas y backorders no alertan.
Errores de red, JSON incompleto o identidad dudosa nunca indican agotado.
"""
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from product_guard import is_english_display

COLLECTION_URL = (
    "https://sarumangames.es/collections/"
    "one-piece-juego-de-cartas-coleccionables"
)
CATALOG_URL = COLLECTION_URL + "/products.json?limit=250"
CODES = ("EB05", "OP18")
CODE_PATTERN = {
    "EB05": re.compile(r"(?<![a-z0-9])eb[\s_-]*0?5(?![a-z0-9])", re.I),
    "OP18": re.compile(r"(?<![a-z0-9])op[\s_-]*0?18(?![a-z0-9])", re.I),
}
RESERVATION = re.compile(
    r"\b(?:pre[\s-]?order|pre[\s-]?venta|preventa|"
    r"reserva(?:r|do|da)?|pr[oó]ximamente|coming\s+soon)\b", re.I
)


def _product_result(product, code):
    """Valida set, idioma y display por variante; descarta otros formatos."""
    if not isinstance(product, dict):
        return None
    title = str(product.get("title") or "")
    handle = str(product.get("handle") or "")
    if not CODE_PATTERN[code].search(f"{title} {handle}"):
        return None

    variants = product.get("variants")
    if not isinstance(variants, list) or not variants:
        return None

    body = BeautifulSoup(str(product.get("body_html") or ""), "html.parser")
    description = body.get_text(" ", strip=True)[:3000]
    preorder = bool(RESERVATION.search(title) or RESERVATION.search(description))

    qualifying = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_title = str(variant.get("title") or "")
        # Los atributos de variante pueden especificar idioma o tamaño;
        # no buscar en recomendaciones, navegación ni otros productos.
        identity = f"{title} {handle.replace('-', ' ')} {variant_title}"
        if not is_english_display(identity, code):
            continue

        available = variant.get("available") is True
        # Shopify puede permitir backorders cuando inventory_policy=continue.
        inventory = variant.get("inventory_quantity")
        if variant.get("inventory_policy") == "continue":
            if not isinstance(inventory, (int, float)) or inventory <= 0:
                available = False

        if preorder:
            status = "PREVENTA"
        elif available:
            status = "DISPONIBLE"
        else:
            status = "NO_DISPONIBLE"

        price = variant.get("price")
        price_text = None
        if isinstance(price, (str, int, float)):
            try:
                price_text = f"{float(str(price).replace(',', '.')):.2f} €"
            except ValueError:
                pass

        qualifying.append({
            "status": status,
            "name": title[:220],
            "url": f"https://sarumangames.es/products/{handle}",
            "price": price_text,
        })

    if not qualifying:
        return None
    order = {"DISPONIBLE": 0, "PREVENTA": 1, "NO_DISPONIBLE": 2}
    qualifying.sort(key=lambda p: order[p["status"]])
    return qualifying[0]


def parse_shopify_products(data):
    """Cada expansión se evalúa independientemente dentro del mismo catálogo."""
    if not isinstance(data, dict) or not isinstance(data.get("products"), list):
        raise ValueError("Shopify catalog without products list")

    products = data["products"]
    outcomes = {}
    for code in CODES:
        found = []
        for product in products:
            result = _product_result(product, code)
            if result:
                found.append(result)
        if found:
            priority = {"DISPONIBLE": 0, "PREVENTA": 1, "NO_DISPONIBLE": 2}
            found.sort(key=lambda p: priority[p["status"]])
            outcomes[code] = {"ok": True, **found[0]}
        else:
            outcomes[code] = {
                "ok": True, "status": "BUSCANDO", "url": COLLECTION_URL,
                "name": None, "price": None,
            }
    return outcomes


def check_saruman(session):
    """Una solicitud compartida cada 30 min; respuesta inválida nunca alerta."""
    try:
        response = session.get(CATALOG_URL, timeout=15, allow_redirects=True)
        oldhost = urlparse(CATALOG_URL).hostname or ""
        newhost = urlparse(response.url).hostname or ""
        if response.status_code != 200 or oldhost != newhost:
            raise ValueError(f"HTTP {response.status_code} o dominio inesperado")
        data = response.json()
        result = parse_shopify_products(data)
        if len(data["products"]) >= 250:
            # El catálogo podría estar paginado; ignorar ausencias y evitar
            # declarar "BUSCANDO" si no hemos explorado todos los productos.
            for item in result.values():
                if item["status"] == "BUSCANDO":
                    item["ok"] = False
                    item["reason"] = "paginación incompleta"
        for code, item in result.items():
            print(
                f"SARUMAN_{code}: {item['status'] if item['ok'] else 'NO_VERIFICABLE'} "
                f"[Shopify JSON · {len(data['products'])} productos]"
            )
        return result
    except Exception as exc:
        print(f"⚠️ SARUMAN: catálogo no verificable ({type(exc).__name__}); estados intactos")
        return {
            code: {"ok": False, "status": "DESCONOCIDO", "url": COLLECTION_URL,
                   "reason": type(exc).__name__}
            for code in CODES
        }
