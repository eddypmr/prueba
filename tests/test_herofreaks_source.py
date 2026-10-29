"""Tests HeroFreaks: solo display EN realmente comprable genera aviso."""
import unittest
from unittest.mock import Mock, patch
from herofreaks_source import find_product_link, analyze_product, check_herofreaks, diagnose_page

URL = "https://herofreaks.com/comprar/juegos-de-cartas/one-piece-card-game/eb05-display/"
TITLE = "Extra Booster Display – Heroines Edition Vol.2 EB-05: One Piece Card Game"

def product(inner, title=TITLE, lang="English"):
    return (f'<div class="product type-product">'
            f'<div class="summary entry-summary"><h1 class="product_title">{title}</h1>'
            f'{inner}</div>'
            f'<table class="woocommerce-product-attributes">'
            f'<tr><th>Idioma</th><td>{lang}</td></tr></table></div>')

class HeroFreaksTests(unittest.TestCase):
    def test_diagnostic_detects_antibot(self):
        html = "<html><title>Just a moment...</title><body>Checking your browser</body></html>"
        self.assertEqual(diagnose_page(html, "EB05")[0], "ANTIBOT")

    def test_diagnostic_detects_product_catalog(self):
        html = '<html><ul class="products"><li class="product">One Piece</li></ul></html>'
        self.assertEqual(diagnose_page(html, "EB05")[0], "CATALOGO_O_FICHA")

    def test_diagnostic_detects_empty_layout(self):
        html = "<html><body>" + "Información genérica " * 80 + "</body></html>"
        self.assertEqual(diagnose_page(html, "EB05")[0], "SIN_ESTRUCTURA_PRODUCTOS")

    def test_selects_display_not_single_pack(self):
        catalog = (
            '<html><body><h1>One Piece Card Game</h1><ul class="products">'
            '<li class="product"><a href="/comprar/sobre/"><h2>Extra Booster – '
            'Heroines Edition Vol.2 EB-05</h2></a></li>'
            f'<li class="product"><a href="{URL}"><h2>{TITLE}</h2></a></li>'
            '</ul></body></html>')
        self.assertEqual(find_product_link(catalog, "https://herofreaks.com/one-piece-card-game/", "EB05"), URL)

    def test_stock_requires_product_cart_button(self):
        html=product('<form class="cart"><button class="single_add_to_cart_button">Añadir al carrito</button></form>')
        self.assertEqual(analyze_product(html, URL, "EB05")[0], "DISPONIBLE")

    def test_no_global_cart_button(self):
        html=product('<p>Sin existencias</p>')+'<button class="single_add_to_cart_button">Comprar otro</button>'
        self.assertNotEqual(analyze_product(html, URL, "EB05")[0], "DISPONIBLE")

    def test_outofstock_even_if_cart_button(self):
        html=product('<p class="stock out-of-stock">Sin existencias</p><form class="cart"><button class="single_add_to_cart_button">Añadir al carrito</button></form>')
        self.assertEqual(analyze_product(html, URL, "EB05")[0], "NO_DISPONIBLE")

    def test_preventa_not_stock(self):
        html=product('<p>Disponibilidad: RESERVA</p><form class="cart"><button class="single_add_to_cart_button">Añadir al carrito</button></form>')
        self.assertEqual(analyze_product(html, URL, "EB05")[0], "PREVENTA")

    def test_wrong_language(self):
        html=product('<form class="cart"><button class="single_add_to_cart_button">Añadir</button></form>', lang="Japanese")
        self.assertNotEqual(analyze_product(html, URL, "EB05")[0], "DISPONIBLE")

    def test_wrong_set(self):
        html=product('<form class="cart"><button class="single_add_to_cart_button">Añadir</button></form>')
        self.assertNotEqual(analyze_product(html, URL, "OP18")[0], "DISPONIBLE")

    def test_generic_page_without_products_is_unknown(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=200, url="https://herofreaks.com/one-piece-card-game/",
            text="<html><h1>One Piece Card Game</h1>" + " catálogo " * 200 + "</html>"
        )
        with patch("herofreaks_source.PAUSED_FROM_GITHUB", False):
            result = check_herofreaks(session, "EB05")
        self.assertEqual(result["status"], "DESCONOCIDO")
        self.assertFalse(result["ok"])

    def test_valid_catalog_without_target_product_is_searching(self):
        session = Mock()
        catalog = (
            '<html><h1>One Piece Card Game</h1><ul class="products">'
            '<li class="product"><h2>One Piece starter deck</h2></li>'
            '</ul>' + ' one piece ' * 120 + '</html>'
        )
        session.get.return_value = Mock(
            status_code=200, url="https://herofreaks.com/one-piece-card-game/",
            text=catalog
        )
        with patch("herofreaks_source.PAUSED_FROM_GITHUB", False):
            result = check_herofreaks(session, "EB05")
        self.assertEqual(result["status"], "BUSCANDO")
        self.assertTrue(result["ok"])

    def test_antibot_page_never_counts_as_catalog(self):
        session = Mock()
        html = (
            '<html><title>Just a moment...</title><body>'
            'Checking your browser before visiting One Piece Card Game'
            + ' one piece ' * 120 + '</body></html>'
        )
        session.get.return_value = Mock(
            status_code=200, url="https://herofreaks.com/one-piece-card-game/",
            text=html
        )
        with patch("herofreaks_source.PAUSED_FROM_GITHUB", False):
            result = check_herofreaks(session, "EB05")
        self.assertEqual(result["status"], "DESCONOCIDO")
        self.assertFalse(result["ok"])

    def test_paused_source_never_fetches_blocked_shop(self):
        session=Mock()
        # La pausa solo se comprueba si se activa explícitamente.
        with patch("herofreaks_source.PAUSED_FROM_GITHUB", True):
            result=check_herofreaks(session, "EB05")
        self.assertFalse(result["ok"])
        self.assertIn("403", result["reason"])
        session.get.assert_not_called()

    def test_403_triggers_browser_fallback(self):
        session = Mock()
        session.get.return_value = Mock(status_code=403,
            url="https://herofreaks.com/one-piece-card-game/", text="")
        browser = Mock()
        catalog = ('<html><h1>One Piece Card Game</h1><ul class="products">'
                   f'<li class="product"><a href="{URL}"><h2>{TITLE}</h2></a></li>'
                   '</ul>' + ' one piece ' * 120 + '</html>')
        browser.fetch.side_effect = [
            (catalog, "Playwright/Chromium", "https://herofreaks.com/one-piece-card-game/"),
            (product('<form class="cart"><button class="single_add_to_cart_button">Comprar</button></form>') + '<div>' + ' contenido descriptivo ' * 80 + '</div>',
             "Playwright/Chromium", URL),
        ]
        result = check_herofreaks(session, "EB05", browser)
        self.assertEqual(result["status"], "DISPONIBLE")
        self.assertEqual(result["via"], "Playwright/Chromium")
        self.assertEqual(browser.fetch.call_count, 2)

    def test_403_browser_blocked_never_alerts(self):
        session = Mock()
        session.get.return_value = Mock(status_code=403,
            url="https://herofreaks.com/one-piece-card-game/", text="")
        browser = Mock()
        browser.fetch.return_value = (None, "Playwright error: blocked",
                                      "https://herofreaks.com/one-piece-card-game/")
        result = check_herofreaks(session, "EB05", browser)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "DESCONOCIDO")

    def test_elementor_snapshot_outofstock_and_related_buttons(self):
        # Basado en la estructura de la ficha real, sin cookies ni datos privados.
        html = (
            '<div class="elementor-location-single product type-product outofstock">'
            f'<h1 class="product_title entry-title">{TITLE}</h1>'
            '<span class="elementor-button-text">PREVENTA</span>'
            '<div class="elementor-widget-woocommerce-product-add-to-cart">'
            '<div class="elementor-add-to-cart elementor-product-simple">'
            '<p class="stock out-of-stock">Sin existencias</p>'
            '<div id="yith-wcwtl-output" class="yith-wcwtl-output">'
            '<p>¡Avísame cuando esté disponible!</p></div></div></div>'
            '<table class="woocommerce-product-attributes">'
            '<tr><th>Idioma</th><td>English</td></tr></table>'
            '<div class="related"><a class="add_to_cart_button" href="?add-to-cart=99">'
            'Añadir al carrito</a></div></div>'
        )
        self.assertEqual(analyze_product(html, URL, "EB05")[0], "NO_DISPONIBLE")

    def test_elementor_available_requires_own_cart(self):
        html = (
            '<div class="elementor-location-single product type-product instock">'
            f'<h1 class="product_title">{TITLE}</h1>'
            '<table class="woocommerce-product-attributes">'
            '<tr><th>Idioma</th><td>English</td></tr></table>'
            '<div class="elementor-widget-woocommerce-product-add-to-cart">'
            '<div class="elementor-add-to-cart elementor-product-simple">'
            '<p class="stock in-stock">Hay existencias</p>'
            '<form class="cart"><button type="submit" name="add-to-cart" '
            'class="single_add_to_cart_button">Añadir al carrito</button></form>'
            '</div></div></div>'
        )
        self.assertEqual(analyze_product(html, URL, "EB05")[0], "DISPONIBLE")

    def test_elementor_related_buy_buttons_do_not_confirm_stock(self):
        html = (
            '<div class="elementor-location-single product type-product">'
            f'<h1 class="product_title">{TITLE}</h1>'
            '<table class="woocommerce-product-attributes">'
            '<tr><th>Idioma</th><td>English</td></tr></table>'
            '<div class="elementor-widget-woocommerce-product-add-to-cart"></div>'
            '<a class="add_to_cart_button" href="?add-to-cart=99">'
            'Añadir al carrito</a></div>'
        )
        self.assertEqual(analyze_product(html, URL, "EB05")[0], "DESCONOCIDO")

    def test_elementor_preorder_badge_not_available(self):
        html = (
            '<div class="elementor-location-single product type-product instock">'
            f'<h1 class="product_title">{TITLE}</h1>'
            '<span class="elementor-button-text">PREVENTA</span>'
            '<table class="woocommerce-product-attributes">'
            '<tr><th>Idioma</th><td>English</td></tr></table>'
            '<div class="elementor-widget-woocommerce-product-add-to-cart">'
            '<form class="cart"><button class="single_add_to_cart_button">'
            'Añadir al carrito</button></form></div></div>'
        )
        self.assertEqual(analyze_product(html, URL, "EB05")[0], "PREVENTA")

    def test_known_direct_url_avoids_catalog_if_stock_confirmed(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=200, url=URL,
            text=('<div class="elementor-location-single product type-product outofstock">'
                  f'<h1 class="product_title">{TITLE}</h1>'
                  '<table class="woocommerce-product-attributes">'
                  '<tr><th>Idioma</th><td>English</td></tr></table>'
                  '<p class="stock out-of-stock">Sin existencias</p></div>')
        )
        result = check_herofreaks(session, "EB05", direct_url=URL)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "NO_DISPONIBLE")
        session.get.assert_called_once()

    def test_403_never_confirms_stock(self):
        session=Mock()
        session.get.return_value=Mock(status_code=403,url="https://herofreaks.com/one-piece-card-game/",text="")
        self.assertFalse(check_herofreaks(session, "EB05")["ok"])

if __name__ == "__main__":
    unittest.main()
