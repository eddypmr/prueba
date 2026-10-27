"""Fuentes candidatas: solo diagnóstico; NUNCA estados ni alertas Telegram."""
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from product_guard import direct_page_identity, is_english_display, preorder_marker
from logpose_sources import run_comparator_checks

DIAGNOSTIC_TARGETS = {
    "TUROL_EB05": {
        "paused": True,  # GitHub Actions devuelve HTTP 202; revisión manual.
        "code": "EB05",
        "url": "https://www.turolgames.com/es/one-piece-tcg/130163-one-piece-card-game-eb-05-extra-booster-display-24-booster-ingles",
    },
    "TUROL_OP18": {
        "paused": True,  # Evitar peticiones cada 30 min a sitio bloqueado.
        "code": "OP18",
        "url": "https://www.turolgames.com/es/one-piece-tcg/130240-one-piece-card-game-booster-display-op-18-24-packs-ingles",
    },
    "BANDUA_EB05": {
        "code": "EB05",
        "url": "https://banduawargames.com/es/one-piece-card-game/75233-booster-box-display-eb-05-24-sobres-ingles-one-piece-card-game.html",
    },
}


def inspect_html(html, url, code):
    """Solo evidencia; ninguna fuente nueva produce estado DISPONIBLE."""
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text(" ", strip=True)
    identity = direct_page_identity(html, url)
    if not is_english_display(identity, code):
        return "IDENTIDAD_NO_VERIFICADA"
    if preorder_marker(html, text):
        return "PREVENTA"
    # Un posible stock sin autorización para alertar requiere revisión
    # de selectores específicos del vendedor.
    return "SIN_CONFIRMAR"


def diagnostic_check(session, name, config):
    url = config["url"]
    try:
        response = session.get(url, timeout=12, allow_redirects=True)
        old_host = (urlparse(url).hostname or "").removeprefix("www.")
        new_host = (urlparse(response.url).hostname or "").removeprefix("www.")
        if response.status_code != 200 or old_host != new_host:
            result = "ERROR_HTTP_O_REDIRECCION"
            detail = f"HTTP {response.status_code}"
        elif len(response.text) < 500:
            result, detail = "PAGINA_INCOMPLETA", "HTML demasiado corto"
        else:
            result = inspect_html(response.text, response.url, config["code"])
            detail = "HTTP 200"
    except Exception as exc:
        result, detail = "ERROR_CONEXION", type(exc).__name__
    print(f"🧪 DIAG_{name}: {result} [{detail}] (sin alertas ni cambios de estado)")
    return result


def run_diagnostics(session):
    for name, config in DIAGNOSTIC_TARGETS.items():
        if config.get("paused"):
            print(f"🧪 DIAG_{name}: PAUSADO (HTTP 202 desde GitHub; revisión manual)")
            continue
        diagnostic_check(session, name, config)
    # Comparador adicional EB-05 / OP-18. No escribe estado ni envía alertas.
    return run_comparator_checks(session)
