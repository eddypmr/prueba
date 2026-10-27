"""Guardas conservadoras para displays ingleses y reservas One Piece TCG."""
import re
from bs4 import BeautifulSoup

CODES = {
    "EB05": re.compile(r"(?<![a-z0-9])eb[\s_-]*0?5(?![a-z0-9])", re.I),
    "OP18": re.compile(r"(?<![a-z0-9])op[\s_-]*0?18(?![a-z0-9])", re.I),
}
EN = re.compile(r"(?<![a-z])(?:ingl[eé]s|english)(?![a-z])", re.I)
JP = re.compile(r"(?<![a-z])(?:japon[eé]s|japanese|jap[oó]n)(?![a-z])", re.I)
INVALID = re.compile(
    r"\b(?:case|mini\s*case|gift\s*collection|starter\s*deck|blister|"
    r"sleeves|fundas|carpeta|album|single\s*pack|sobre\s*individual|"
    r"desprecintad[ao]s?|opened|sin\s*precintar)\b", re.I
)
PACK24 = re.compile(r"\b24\s*(?:sobres?|packs?|boosters?)\b", re.I)
BOX = re.compile(
    r"\b(?:booster[\s_-]*box|booster[\s_-]*display|"
    r"extra[\s_-]*booster[\s_-]*display|display|"
    r"caja\s*(?:de\s*)?24\s*(?:sobres?|packs?))\b", re.I
)
OTHER_PACK = re.compile(r"(?<![a-z0-9_-])(?:6|8|10|12|18|36)\s*(?:sobres?|packs?|boosters?)\b", re.I)
PREORDER = re.compile(r"\b(?:pre[\s-]?order|preventa|pre[\s-]?venta|"
                      r"reserva(?:r|da|do)?|pr[eé][\s-]?commande)\b", re.I)


def is_english_display(identity, code):
    """Identidad de tarjeta o título, nunca el texto entero del catálogo."""
    identity = identity or ""
    return bool(
        code in CODES
        and CODES[code].search(identity)
        and EN.search(identity)
        and BOX.search(identity)
        and not JP.search(identity)
        and not INVALID.search(identity)
        and not (OTHER_PACK.search(identity) and not PACK24.search(identity))
    )


def direct_page_identity(html, url):
    """No usar banners, recomendaciones ni contenido de otros artículos."""
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    meta = soup.find("meta", attrs={"property": "og:title"})
    return " ".join((
        h1.get_text(" ", strip=True) if h1 else "",
        meta.get("content", "") if meta else "",
        url or "",
    ))


def preorder_marker(html, text=""):
    """Un badge PREORDER o 'Disponibilidad: RESERVA' invalida stock inmediato."""
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    meta = soup.find("meta", attrs={"property": "og:title"})
    if any(PREORDER.search(s) for s in (
        h1.get_text(" ", strip=True) if h1 else "",
        meta.get("content", "") if meta else "",
    )):
        return True
    return bool(re.search(r"\bdisponibilidad\s*:\s*(?:reserva|preventa|pre[\s-]?order)\b",
                          text or "", re.I))


def guarded_stock(html, text, url, code, raw_status):
    if not is_english_display(direct_page_identity(html, url), code):
        return "DESCONOCIDO"
    return "PREVENTA" if preorder_marker(html, text) else raw_status
