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


if __name__ == "__main__":
    unittest.main()
