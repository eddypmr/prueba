"""Monitor adicional de LOGPOSE: nuevas expansiones sin falsas alertas de stock.

LOGPOSE es un COMPARADOR. Su 'Disponible' puede ser una PREVENTA y sus
actualizaciones no son en tiempo real. Por seguridad, esta fase solo registra
fichas para revisión; nunca envía Telegram ni escribe state.json.
"""
import re
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

BASE_URL = "https://tcglogpose.com"
WATCHED_SETS = {
    "EB05": "EB-05",
    "OP18": "OP-18",
}
# Fichas identificadas de BOOSTER BOX EN, no sobres, cajas JP ni cases:
# EB-05: /428 sobre, /429 box EN, /430 case EN, /431 box JP.
# OP-18: /452 sobre, /453 box EN (según el orden del listado).
# El identificador debe verificarse en el HTML real antes de añadir otro set.
WATCHED_PRODUCT_PATHS = {"EB-05": "/producto/429", "OP-18": "/producto/453"}

CODE_RE = re.compile(r"\b(?:EB|OP)[-_ ]?0?\d{1,2}\b", re.I)
DISPLAY_RE = re.compile(r"(?:extra\s+)?booster\s+box|booster\s+display", re.I)
CASE_RE = re.compile(r"\bbox\s+case\b|\bcase\b", re.I)
EN_RE = re.compile(r"(?<!\w)(?:EN|English|ingl[eé]s)(?!\w)", re.I)
PRICE_RE = re.compile(r"\b(?:desde|precio\s+desde|más\s+barato)\s*([\d.,]+)\s*€", re.I)
PRODUCT_HREF_RE = re.compile(r"^/producto/\d+(?:/)?$")


def search_url(set_code):
    """Permite añadir OP-19 o EB-06 editando solo WATCHED_SETS."""
    return f"{BASE_URL}/buscar?{urlencode({'setCode': set_code})}"


def parse_comparator(html, expected_code):
    """Extrae SOLO displays EN; ignora sobres, cajas japonesas y cases.

    La disponibilidad es orientativa, no prueba stock inmediato.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    found = []
    visited = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").split("?")[0]
        absolute = urljoin(BASE_URL, href)
        parsed = urlparse(absolute)
        if parsed.hostname != urlparse(BASE_URL).hostname:
            continue
        if not PRODUCT_HREF_RE.match(parsed.path):
            continue
        if parsed.path.rstrip("/") != WATCHED_PRODUCT_PATHS.get(expected_code):
            # Evita tarjetas cuyo texto mezcla otras variantes o accesorios.
            continue
        if absolute in visited:
            continue
        visited.add(absolute)
        label = anchor.get_text(" ", strip=True)
        # Usar exclusivamente la ficha enlazada, no el cuerpo de la página.
        if not re.search(re.escape(expected_code).replace(r"\-", r"[-_ ]?"), label, re.I):
            continue
        if not DISPLAY_RE.search(label) or CASE_RE.search(label):
            continue
        if not EN_RE.search(label):
            continue

        # Contexto mínimo: contenedor de tarjeta, nunca el listado entero.
        card = anchor
        for _ in range(3):
            parent = getattr(card, "parent", None)
            if parent is None or parent.name in ("body", "main", "html"):
                break
            parent_text = parent.get_text(" ", strip=True)
            if len(parent_text) > 600:
                break
            card = parent
            if "Disponible" in parent_text or "Agotado" in parent_text:
                break
        card_text = card.get_text(" ", strip=True)
        # El catálogo puede mostrar preventas como disponibles y combinar
        # etiquetas de tarjetas adyacentes. Nunca inferir stock desde aquí.
        status = "LISTADO_COMPARADOR"
        price = PRICE_RE.search(card_text)
        found.append({
            "name": label[:200],
            "url": absolute,
            "status": status,
            "price": price.group(1) + " €" if price else None,
        })
    return found


def check_one(session, code, set_code):
    url = search_url(set_code)
    try:
        response = session.get(url, timeout=12, allow_redirects=True)
        parsed = urlparse(response.url)
        if response.status_code != 200 or parsed.hostname != "tcglogpose.com":
            print(f"🔎 LOGPOSE_{code}: sin lectura válida (HTTP {response.status_code})")
            return {"ok": False, "reason": f"HTTP {response.status_code}", "products": []}
        if len(response.text) < 350:
            print(f"🔎 LOGPOSE_{code}: página incompleta")
            return {"ok": False, "reason": "HTML insuficiente", "products": []}
        matches = parse_comparator(response.text, set_code)
        if not matches:
            # Puede ser renderizado JavaScript, bloqueo o cambio en el HTML.
            print(f"🔎 LOGPOSE_{code}: HTML recibido, display EN no verificable")
            return {"ok": False, "reason": "Sin fichas EN verificables", "products": []}
        for product in matches:
            print(
                f"🔎 LOGPOSE_{code}: {product['status']} · "
                f"{product['price'] or 'sin precio'} · {product['url']} "
                "(comparador, NO stock confirmado)"
            )
        return {"ok": True, "products": matches}
    except Exception as exc:
        # No exponer detalles de peticiones ni datos privados en logs.
        print(f"🔎 LOGPOSE_{code}: error de conexión ({type(exc).__name__})")
        return {"ok": False, "reason": type(exc).__name__, "products": []}


def run_comparator_checks(session):
    """Lectura solo informativa: jamás se afirma stock real de las tiendas."""
    results = {}
    for code, set_code in WATCHED_SETS.items():
        results[code] = check_one(session, code, set_code)
    return results


def format_comparator_report(results):
    """Resumen cada 12 h: distinguir listados de disponibilidad confirmada."""
    lines = ["", "📊 LOGPOSE · datos orientativos (pueden ser preventas)"]
    for code, set_code in WATCHED_SETS.items():
        result = (results or {}).get(code) or {}
        products = result.get("products") or []
        if result.get("ok") and products:
            product = products[0]
            label = "Listado en comparador" if product["status"] == "LISTADO_COMPARADOR" else "Sin stock según comparador"
            lines.append(
                f"• {set_code} display EN: {label} · "
                f"{product.get('price') or 'sin precio'}"
            )
            lines.append(product["url"])
        else:
            lines.append(f"• {set_code}: no verificable · {search_url(set_code)}")
    lines.append("Antes de comprar, comprobar stock y tipo de venta en la tienda.")
    return "\n".join(lines)
