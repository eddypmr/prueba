"""Pruebas de disponibilidad JSON-LD: un producto no puede contaminar a otro."""
import json
import unittest

from monitor import (
    detect_direct_status,
    structured_availability,
    target_context_status,
)


def page(*objects, content=""):
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps({"@context": "https://schema.org", "@graph": list(objects)})
        + "</script></head><body>"
        + content
        + "</body></html>"
    )


def product(name, availability, **other):
    return {
        "@type": "Product",
        "name": name,
        "offers": {"@type": "Offer", "availability": availability},
        **other,
    }


class JsonLdStockTests(unittest.TestCase):
    def test_matches_eb05_only(self):
        html = page(
            product("One Piece EB-05 Booster Box", "https://schema.org/OutOfStock"),
            product("One Piece OP-18 Booster Box", "https://schema.org/InStock"),
        )
        self.assertEqual(structured_availability(html, "EB05"), "NO_DISPONIBLE")
        self.assertEqual(structured_availability(html, "OP18"), "DISPONIBLE")

    def test_op18_does_not_inherit_instock_from_recommendation(self):
        html = page(
            product("One Piece EB-05", "https://schema.org/InStock"),
            product("One Piece OP-18", "https://schema.org/OutOfStock"),
        )
        self.assertEqual(target_context_status(html, "", "OP18"), "NO_DISPONIBLE")

    def test_unrelated_product_never_implies_stock(self):
        html = page(product("One Piece OP-17", "https://schema.org/InStock"))
        self.assertIsNone(structured_availability(html, "OP18"))
        self.assertEqual(target_context_status(html, "", "OP18"), "DESCONOCIDO")
        self.assertEqual(detect_direct_status(html, "", "OP18"), "DESCONOCIDO")

    def test_matching_product_by_sku_suffix(self):
        html = page(product("Booster box", "https://schema.org/InStock", sku="EB05_EN_DISPLAY"))
        self.assertEqual(structured_availability(html, "EB05"), "DISPONIBLE")
        self.assertIsNone(structured_availability(html, "OP18"))

    def test_matching_product_by_url(self):
        html = page(product(
            "Caja de 24 sobres", "https://schema.org/OutOfStock",
            url="https://example.test/one-piece-op-18-english",
        ))
        self.assertEqual(structured_availability(html, "OP18"), "NO_DISPONIBLE")

    def test_english_op18_name(self):
        html = page(product("The Dominance of God - Booster Box", "https://schema.org/InStock"))
        self.assertEqual(structured_availability(html, "OP18"), "DISPONIBLE")

    def test_conflicting_offers_are_ambiguous(self):
        html = page({
            "@type": "Product", "name": "One Piece OP-18",
            "offers": [
                {"@type": "Offer", "availability": "https://schema.org/InStock"},
                {"@type": "Offer", "availability": "https://schema.org/OutOfStock"},
            ],
        })
        self.assertIsNone(structured_availability(html, "OP18"))

    def test_preorder_does_not_mean_confirmed_stock(self):
        html = page(product("One Piece OP-18", "https://schema.org/PreOrder"))
        self.assertIsNone(structured_availability(html, "OP18"))

    def test_invalid_jsonld_is_ignored(self):
        html = '<script type="application/ld+json">{not JSON</script>'
        self.assertIsNone(structured_availability(html, "EB05"))

    def test_unidentified_product_is_not_assumed_from_page(self):
        html = page(product("Trading Card Box", "https://schema.org/InStock"))
        self.assertIsNone(structured_availability(html, "EB05"))

    def test_conflicting_identity_is_not_trusted(self):
        html = page(product(
            "One Piece EB-05 / OP-18 bundle",
            "https://schema.org/InStock",
        ))
        self.assertIsNone(structured_availability(html, "EB05"))
        self.assertIsNone(structured_availability(html, "OP18"))

    def test_list_at_top_level_and_nested_graph(self):
        html = (
            '<script type="application/ld+json">'
            + json.dumps([
                {"@graph": [product("One Piece OP-18", "https://schema.org/OutOfStock")]},
                product("One Piece EB-05", "https://schema.org/InStock"),
            ])
            + '</script>'
        )
        self.assertEqual(structured_availability(html, "EB05"), "DISPONIBLE")
        self.assertEqual(structured_availability(html, "OP18"), "NO_DISPONIBLE")


if __name__ == "__main__":
    unittest.main()
