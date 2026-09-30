#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


STATE_FILE = Path("state.json")

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

DISCOVERY_PAGES = {
    "INGENIO_BCN": {
        "url": "https://www.ingeniobcn.com/etiqueta-producto/one-piece/",
        "force_browser": False,
    },
    "METROPOLIS_CENTER": {
        "url": "https://metropolis-center.com/es/catalogo/juegos-de-cartas/one-piece",
        "force_browser": True,
    },
    "MATHOM": {
        "url": "https://mathom.es/es/6900-one-piece-card-game",
        "force_browser": False,
    },
    "ZACATRUS": {
        "url": "https://zacatrus.es/catalogsearch/result/?q=one+piece",
        "force_browser": False,
    },
    "PAPER_DEALER": {
        "url": "https://www.paperdealer.eu/collections/one-piece-tcg",
        "force_browser": False,
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

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SEND_TEST_NOTIFICATION = os.getenv("SEND_TEST_NOTIFICATION", "false").lower() == "true"


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


def http_fetch(url):
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
            },
            timeout=30,
            allow_redirects=True,
        )

        if response.status_code == 200 and len(response.text) > 500:
            return response.text, f"HTTP {response.status_code}"

        return None, f"HTTP {response.status_code}"

    except requests.RequestException as exc:
        return None, f"HTTP error: {exc}"


def browser_fetch(url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        page = browser.new_page(
            user_agent=USER_AGENT,
            locale="es-ES",
            viewport={"width": 1440, "height": 1100},
        )

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3500)
            return page.content(), "Playwright/Chromium"

        except PlaywrightTimeoutError:
            try:
                return page.content(), "Playwright/Chromium (timeout parcial)"
            except Exception:
                return None, "Playwright timeout"

        except Exception as exc:
            return None, f"Playwright error: {exc}"

        finally:
            browser.close()


def get_html(url, force_browser=False):
    if not force_browser:
        html, via = http_fetch(url)
        if html:
            return html, via

    return browser_fetch(url)


def visible_text(html):
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    return " ".join(soup.stripped_strings)


def has_eb05(text):
    return any(pattern.search(text) for pattern in EB05_PATTERNS)


def structured_availability(html):
    """
    Intenta obtener InStock/OutOfStock de datos estructurados de la ficha.
    Es más fiable que buscar un texto genérico de 'Comprar' en toda la página.
    """
    lower_html = html.lower()

    if re.search(
        r'availability["\s:]+[^}]{0,150}(outofstock|soldout)',
        lower_html,
        re.I,
    ):
        return "NO_DISPONIBLE"

    if re.search(
        r'availability["\s:]+[^}]{0,150}instock',
        lower_html,
        re.I,
    ):
        return "DISPONIBLE"

    return None


def detect_gameria_category_status(html):
    """
    Gameria a veces corta la conexión a la ficha desde IPs de datacenter.
    Como fallback, buscamos EB-05 dentro de la tarjeta de producto de su
    categoría One Piece y analizamos solo esa tarjeta.
    """
    soup = BeautifulSoup(html, "html.parser")

    selectors = [
        "article",
        ".product-miniature",
        ".product",
        ".product-item",
        ".js-product-miniature",
    ]

    seen = set()

    for selector in selectors:
        for node in soup.select(selector):
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)

            text = " ".join(node.stripped_strings)

            if has_eb05(text):
                return detect_direct_status(str(node), text)

    # Fallback por ventana de texto si la plantilla no usa las clases anteriores.
    text = visible_text(html)

    for pattern in EB05_PATTERNS:
        match = pattern.search(text)
        if match:
            start = max(0, match.start() - 450)
            end = min(len(text), match.end() + 450)
            window = text[start:end]
            return detect_direct_status(window, window)

    return None


def looks_blocked(text):
    blocked_patterns = (
        r"access denied",
        r"verify you are human",
        r"just a moment",
        r"checking your browser",
        r"captcha",
    )
    return any(re.search(pattern, text, re.I) for pattern in blocked_patterns)


def detect_direct_status(html, text):
    structured = structured_availability(html)

    if structured:
        return structured

    unavailable = any(pattern.search(text) for pattern in UNAVAILABLE_PATTERNS)
    buy_signal = any(pattern.search(text) for pattern in BUY_PATTERNS)

    # Si la propia ficha declara explícitamente que está agotada,
    # no interpretamos un "Comprar" de navegación/recomendaciones como stock.
    if unavailable:
        return "NO_DISPONIBLE"

    if buy_signal:
        return "DISPONIBLE"

    return "POSIBLE_STOCK"


def notify_if_transition(store, old_status, new_status, url):
    # Primera ejecución: crea la línea base pero no molesta con alertas.
    if old_status is None or old_status == new_status:
        return

    if new_status == "DISPONIBLE":
        send_telegram(
            f"🚨 ONE PIECE EB-05 DISPONIBLE\n\n"
            f"🏪 {store}\n"
            f"✅ Se detectan señales de compra/stock.\n\n"
            f"{url}"
        )

    elif new_status == "POSIBLE_STOCK" and old_status == "NO_DISPONIBLE":
        send_telegram(
            f"⚠️ POSIBLE REPOSICIÓN EB-05\n\n"
            f"🏪 {store}\n"
            f"Ya no se detecta claramente el estado de agotado.\n"
            f"Conviene revisar la ficha.\n\n"
            f"{url}"
        )

    elif new_status == "EB05_ENCONTRADO" and old_status == "BUSCANDO":
        send_telegram(
            f"🆕 EB-05 HA APARECIDO EN UNA TIENDA\n\n"
            f"🏪 {store}\n"
            f"Se ha detectado EB-05 / EB05 / Extra Booster 05 en el catálogo.\n\n"
            f"{url}"
        )


def build_state_entry(mode, status, url, previous):
    previous_status = previous.get("status")

    if previous_status == status and previous.get("last_changed"):
        last_changed = previous["last_changed"]
    else:
        last_changed = utc_now()

    return {
        "mode": mode,
        "status": status,
        "url": url,
        "last_changed": last_changed,
    }


def main():
    state = load_state()
    changed = False

    print(f"=== EB-05 monitor | {utc_now()} ===")

    if SEND_TEST_NOTIFICATION:
        send_telegram(
            "✅ Test correcto: el monitor EB-05 puede enviarte avisos por Telegram."
        )

    for store, url in DIRECT_PRODUCTS.items():
        html, via = get_html(url)

        # Gameria bloquea a veces la ficha individual desde runners cloud.
        # En ese caso usamos su categoría One Piece, donde también aparece
        # la tarjeta EB-05 con el estado de stock.
        if not html and store == "GAMERIA":
            html, via = get_html(GAMERIA_CATEGORY_URL)

            if html:
                new_status = detect_gameria_category_status(html)
                if new_status is None:
                    print(f"❓ {store}: categoría cargada pero EB-05 no apareció [{via}]")
                    continue
                text = visible_text(html)
                print(f"ℹ️ {store}: usando categoría One Piece como fallback")
            else:
                print(f"❓ {store}: no se pudo cargar ficha ni categoría ({via})")
                continue
        else:
            if not html:
                print(f"❓ {store}: no se pudo cargar ({via})")
                continue

            text = visible_text(html)

            if looks_blocked(text):
                print(f"❓ {store}: página anti-bot/captcha detectada [{via}]")
                continue

            new_status = detect_direct_status(html, text)
        previous = state.get(store, {})
        old_status = previous.get("status")

        print(f"{store}: {new_status} [{via}]")
        notify_if_transition(store, old_status, new_status, url)

        new_entry = build_state_entry(
            mode="direct",
            status=new_status,
            url=url,
            previous=previous,
        )

        if previous != new_entry:
            state[store] = new_entry
            changed = True

    for store, config in DISCOVERY_PAGES.items():
        url = config["url"]
        html, via = get_html(url, force_browser=config["force_browser"])

        if not html:
            print(f"❓ {store}: no se pudo cargar ({via})")
            continue

        text = visible_text(html)

        if looks_blocked(text):
            print(f"❓ {store}: página anti-bot/captcha detectada [{via}]")
            continue

        new_status = "EB05_ENCONTRADO" if has_eb05(text) else "BUSCANDO"
        previous = state.get(store, {})
        old_status = previous.get("status")

        print(f"{store}: {new_status} [{via}]")
        notify_if_transition(store, old_status, new_status, url)

        new_entry = build_state_entry(
            mode="discovery",
            status=new_status,
            url=url,
            previous=previous,
        )

        if previous != new_entry:
            state[store] = new_entry
            changed = True

    save_state(state)

    if changed:
        print("💾 state.json actualizado.")
    else:
        print("Sin cambios de estado.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
