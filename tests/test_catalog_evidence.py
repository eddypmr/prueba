"""Pruebas de calidad de catálogos: sin cambiar los estados de stock."""
import unittest

from monitor import catalog_evidence, validate_catalog


class CatalogEvidenceTests(unittest.TestCase):
    def test_cards_confirm_product_listing(self):
        html = '<h1>One Piece</h1><div class="product-item"><a href="/eb-05">EB-05</a></div>'
        evidence = catalog_evidence(html, "One Piece EB-05")
        self.assertEqual(evidence["quality"], "productos")
        self.assertEqual(evidence["product_cards"], 1)

    def test_long_but_generic_page_is_weak(self):
        html = "<h1>One Piece</h1><p>" + "texto legal " * 180 + "</p>"
        evidence = catalog_evidence(html, "One Piece " + "texto legal " * 180)
        self.assertEqual(evidence["quality"], "sin evidencia de productos")

    def test_explicit_empty_catalog_is_distinguished(self):
        evidence = catalog_evidence(
            "<h1>One Piece</h1><p>No hay productos disponibles</p>",
            "One Piece - No hay productos",
        )
        self.assertTrue(evidence["explicitly_empty"])
        self.assertEqual(evidence["quality"], "vacío explícito")

    def test_pagination_without_cards_is_flagged(self):
        html = '<nav class="pagination"><a href="/one-piece?page=2">2</a></nav>'
        evidence = catalog_evidence(html, "One Piece")
        self.assertEqual(evidence["quality"], "paginación sin tarjetas reconocidas")

    def test_structural_catalog_still_validates(self):
        html = '<h1>One Piece</h1><ul><li class="product"><a href="/a">Carta</a></li></ul>'
        valid, error = validate_catalog(
            html, "One Piece Carta",
            {"url": "https://example.org/one-piece", "required_patterns": [r"one\s*piece"]},
            "https://example.org/one-piece",
        )
        self.assertTrue(valid, error)

    def test_blocked_page_still_fails(self):
        valid, _ = validate_catalog(
            "<h1>Verify you are human</h1>",
            "Verify you are human",
            {"url": "https://example.org/one-piece", "required_patterns": [r"one\s*piece"]},
            "https://example.org/one-piece",
        )
        self.assertFalse(valid)

    def test_shared_catalog_rejects_weak_page(self):
        from unittest.mock import patch
        from monitor import discover_shared_catalog

        html = "<html><h1>One Piece</h1><p>Información de la tienda</p></html>"
        config = {"url": "https://example.org/one-piece",
                  "required_patterns": [r"one\s*piece"], "max_pages": 2}
        with patch("monitor.get_html", return_value=(html, "HTTP 200", config["url"])):
            found = discover_shared_catalog(None, None, "EXAMPLE", config, {})
        self.assertFalse(found["EB05"]["ok"])
        self.assertFalse(found["OP18"]["ok"])
        self.assertIn("sin tarjetas", found["EB05"]["note"])

    def test_shared_catalog_accepts_real_product_cards(self):
        from unittest.mock import patch
        from monitor import discover_shared_catalog

        html = ('<html><h1>One Piece</h1>'
                '<li class="product"><a href="/op-03">One Piece OP-03</a></li></html>')
        config = {"url": "https://example.org/one-piece",
                  "required_patterns": [r"one\s*piece"], "max_pages": 2}
        with patch("monitor.get_html", return_value=(html, "HTTP 200", config["url"])):
            found = discover_shared_catalog(None, None, "EXAMPLE", config, {})
        self.assertTrue(found["EB05"]["ok"])
        self.assertTrue(found["OP18"]["ok"])
        self.assertIsNone(found["EB05"]["candidate"])

    def test_shared_catalog_accepts_explicit_empty_listing(self):
        from unittest.mock import patch
        from monitor import discover_shared_catalog

        html = "<html><h1>One Piece</h1><p>No hay productos disponibles</p></html>"
        config = {"url": "https://example.org/one-piece",
                  "required_patterns": [r"one\s*piece"], "max_pages": 2}
        with patch("monitor.get_html", return_value=(html, "HTTP 200", config["url"])):
            found = discover_shared_catalog(None, None, "EXAMPLE", config, {})
        self.assertTrue(found["EB05"]["ok"])
        self.assertTrue(found["OP18"]["ok"])



    def test_metropolis_recovers_catalog_using_http_fallback(self):
        from unittest.mock import patch
        from monitor import discover_shared_catalog

        config = {"url": "https://metropolis-center.com/es/catalogo/juegos-de-cartas/one-piece",
                  "required_patterns": [r"one\s*piece"], "force_browser": True,
                  "max_pages": 2}
        browser_html = "<html><h1>One Piece</h1><p>Menu y categorías</p></html>"
        http_html = (
            "<html><h1>One Piece</h1>"
            '<div class="product-item"><a href="/op-17">One Piece OP-17</a></div>'
            "</html>"
        )
        with patch("monitor.get_html", return_value=(
            browser_html, "Playwright/Chromium + DOM", config["url"]
        )), patch("monitor.http_fetch", return_value=(
            http_html, "HTTP 200", config["url"]
        )) as http_mock:
            result = discover_shared_catalog(None, None, "METROPOLIS_CENTER", config, {})
        self.assertTrue(result["EB05"]["ok"])
        self.assertTrue(result["OP18"]["ok"])
        self.assertEqual(result["EB05"]["status"] if "status" in result["EB05"] else "BUSCANDO", "BUSCANDO")
        self.assertIn("HTTP 200", result["OP18"]["via"])
        http_mock.assert_called_once()

    def test_metropolis_http_fallback_without_cards_stays_unverifiable(self):
        from unittest.mock import patch
        from monitor import discover_shared_catalog

        config = {"url": "https://metropolis-center.com/es/catalogo/juegos-de-cartas/one-piece",
                  "required_patterns": [r"one\s*piece"], "force_browser": True,
                  "max_pages": 2}
        blank = "<html><h1>One Piece</h1><p>Solo navegación</p></html>"
        with patch("monitor.get_html", return_value=(
            blank, "Playwright/Chromium + DOM", config["url"]
        )), patch("monitor.http_fetch", return_value=(
            blank, "HTTP 200", config["url"]
        )):
            result = discover_shared_catalog(None, None, "METROPOLIS_CENTER", config, {})
        self.assertFalse(result["EB05"]["ok"])
        self.assertFalse(result["OP18"]["healthy"])

    def test_other_stores_do_not_use_extra_http_fallback(self):
        from unittest.mock import patch
        from monitor import discover_shared_catalog

        config = {"url": "https://example.org/one-piece", "max_pages": 1}
        blank = "<html><h1>One Piece</h1></html>"
        with patch("monitor.get_html", return_value=(
            blank, "HTTP 200", config["url"]
        )), patch("monitor.http_fetch") as http_mock:
            result = discover_shared_catalog(None, None, "EXAMPLE", config, {})
        http_mock.assert_not_called()
        self.assertFalse(result["EB05"]["ok"])



if __name__ == "__main__":
    unittest.main()
