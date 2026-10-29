"""Tests HeroFreaks: solo display EN realmente comprable genera aviso."""
import unittest
from unittest.mock import Mock
from herofreaks_source import find_product_link, analyze_product, check_herofreaks

URL = "https://herofreaks.com/comprar/juegos-de-cartas/one-piece-card-game/eb05-display/"
TITLE = "Extra Booster Display – Heroines Edition Vol.2 EB-05: One Piece Card Game"

def product(inner, title=TITLE, lang="English"):
    return (f'<div class="product type-product">'
            f'<div class="summary entry-summary"><h1 class="product_title">{title}</h1>'
            f'{inner}</div>'
            f'<table class="woocommerce-product-attributes">'
            f'<tr><th>Idioma</th><td>{lang}</td></tr></table></div>')

class HeroFreaksTests(unittest.TestCase):
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

    def test_catalog_without_product_is_not_stock(self):
        session = Mock()
        session.get.return_value = Mock(status_code=200, url="https://herofreaks.com/one-piece-card-game/",
                                         text="<html><h1>One Piece Card Game</h1>"+" catálogo "*200+"</html>")
        self.assertEqual(check_herofreaks(session, "EB05")["status"], "BUSCANDO")

    def test_paused_source_never_fetches_blocked_shop(self):
        session=Mock()
        result=check_herofreaks(session, "EB05")
        self.assertFalse(result["ok"])
        self.assertIn("403", result["reason"])
        session.get.assert_not_called()

    def test_403_never_confirms_stock(self):
        session=Mock()
        session.get.return_value=Mock(status_code=403,url="https://herofreaks.com/one-piece-card-game/",text="")
        self.assertFalse(check_herofreaks(session, "EB05")["ok"])

if __name__ == "__main__":
    unittest.main()
