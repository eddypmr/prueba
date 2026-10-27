"""LOGPOSE es un comparador: no confundir reservas/cases/sobres con stock."""
import unittest
from unittest.mock import Mock
from logpose_sources import WATCHED_SETS, search_url, parse_comparator, check_one, format_comparator_report

HTML = """
<html><body><main>
 <article><a href="/producto/429">EB-05 · EN Extra Booster Box: One Piece Heroines EB-05 EN</a>
 <span>Disponible · en 10 tiendas Precio desde 119,95 €</span></article>
 <article><a href="/producto/430">EB-05 · EN Extra Booster Box Case: Heroines EB-05 EN</a>
 <span>Disponible · en 4 tiendas</span></article>
 <article><a href="/producto/431">EB-05 · JP Extra Booster Box: Heroines EB-05 JP</a></article>
 <article><a href="/producto/432">EB-05 · EN Extra Booster Pack EB-05 EN</a></article>
 <article><a href="/producto/470">OP-18 · EN Booster Box: The Dominance of God OP-18 EN</a>
 <span>Agotado en todas · en 6 tiendas</span></article>
</main></body></html>
"""

class LogposeSourcesTests(unittest.TestCase):
    def test_urls_for_two_sets(self):
        self.assertEqual(search_url(WATCHED_SETS["EB05"]),
                         "https://tcglogpose.com/buscar?setCode=EB-05")
        self.assertEqual(search_url(WATCHED_SETS["OP18"]),
                         "https://tcglogpose.com/buscar?setCode=OP-18")

    def test_only_english_display_no_case_no_pack(self):
        items = parse_comparator(HTML, "EB-05")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://tcglogpose.com/producto/429")

    def test_comparator_available_does_not_mean_confirmed_stock(self):
        item = parse_comparator(HTML, "EB-05")[0]
        self.assertEqual(item["status"], "LISTADO_COMPARADOR")
        self.assertNotEqual(item["status"], "DISPONIBLE")
        self.assertEqual(item["price"], "119,95 €")

    def test_op18_separate(self):
        item = parse_comparator(HTML, "OP-18")[0]
        self.assertEqual(item["status"], "LISTADO_COMPARADOR")

    def test_misleading_sibling_card_cannot_be_selected(self):
        html = ('<article><a href="/producto/428">'
                'EB-05 EN Extra Booster Box (24 sobres) EB-05 EN'
                '</a></article>'
                '<article><a href="/producto/429">'
                'EB-05 EN Extra Booster Box EB-05 EN'
                '</a></article>')
        products = parse_comparator(html, "EB-05")
        self.assertEqual([p["url"] for p in products],
                         ["https://tcglogpose.com/producto/429"])

    def test_ignores_off_domain_product_link(self):
        html = '<a href="https://phishing.test/producto/499">EB-05 · EN Booster Box EB-05 EN</a>'
        self.assertEqual(parse_comparator(html, "EB-05"), [])

    def test_periodic_report_is_explicitly_not_stock_confirmation(self):
        results = {"EB05": {"ok": True, "products": [{
            "status": "LISTADO_COMPARADOR", "price": "119,95 €",
            "url": "https://tcglogpose.com/producto/429"
        }]}}
        report = format_comparator_report(results)
        self.assertIn("pueden ser preventas", report)
        self.assertIn("Listado en comparador", report)
        self.assertIn("OP-18: no verificable", report)
        self.assertNotIn("✅ EB-05 DISPONIBLE", report)

    def test_invalid_response_does_not_raise_stock_alert(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=403, url=search_url("EB-05"), text="Forbidden"
        )
        result = check_one(session, "EB05", "EB-05")
        self.assertFalse(result["ok"])
        self.assertEqual(result["products"], [])

if __name__ == "__main__":
    unittest.main()
