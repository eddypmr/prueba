"""Saruman: JSON de Shopify, displays ingleses y alertas conservadoras."""
import unittest
from unittest.mock import Mock
from saruman_sources import parse_shopify_products, check_saruman, CATALOG_URL

def prod(title, handle="one-piece-producto", available=True, body="",
         variants=None):
    return {
        "title": title, "handle": handle, "body_html": body,
        "variants": variants if variants is not None else [
            {"title": "Default Title", "available": available, "price": "135.00"}
        ],
    }

class SarumanTests(unittest.TestCase):
    def test_eb05_display_confirmed(self):
        x = parse_shopify_products({"products":[
            prod("ONE PIECE EB-05 Booster Box 24 sobres INGLÉS", "eb05-display")
        ]})
        self.assertEqual(x["EB05"]["status"], "DISPONIBLE")
        self.assertEqual(x["EB05"]["price"], "135.00 €")
        self.assertEqual(x["OP18"]["status"], "BUSCANDO")

    def test_op18_no_stock(self):
        x = parse_shopify_products({"products":[
            prod("One Piece OP-18 Booster Display English", "op-18", False)
        ]})
        self.assertEqual(x["OP18"]["status"], "NO_DISPONIBLE")

    def test_preorder_even_if_available(self):
        x = parse_shopify_products({"products":[
            prod("RESERVA One Piece OP-18 Booster Box Inglés", "op18", True)
        ]})
        self.assertEqual(x["OP18"]["status"], "PREVENTA")

    def test_preorder_in_description(self):
        x = parse_shopify_products({"products":[
            prod("One Piece EB-05 Booster Box English", "eb05",
                 True, "<p>Disponible en PREVENTA, entrega en noviembre</p>")
        ]})
        self.assertEqual(x["EB05"]["status"], "PREVENTA")

    def test_wrong_formats_excluded(self):
        items=[
            prod("One Piece EB-05 SOBRE Inglés", "eb05-sobre"),
            prod("One Piece EB-05 Booster Box Japonés", "eb05-jp"),
            prod("One Piece EB-05 Booster Box Case English", "eb05-case"),
            prod("ONE PIECE OP-18 PRESENTACIÓN torneo", "op18-torneo"),
            prod("ONE PIECE OP-18 Booster Box desprecintada inglés", "op18-open"),
        ]
        x=parse_shopify_products({"products":items})
        self.assertEqual(x["EB05"]["status"], "BUSCANDO")
        self.assertEqual(x["OP18"]["status"], "BUSCANDO")

    def test_variant_stock_not_confused(self):
        x=parse_shopify_products({"products":[
            prod("One Piece EB-05 Booster Box", "eb05", variants=[
                {"title":"Japonés", "available":True, "price":"75.00"},
                {"title":"Inglés", "available":False, "price":"140.00"}
            ])
        ]})
        self.assertEqual(x["EB05"]["status"], "NO_DISPONIBLE")

    def test_shopify_backorder_not_stock(self):
        x=parse_shopify_products({"products":[
            prod("ONE PIECE EB-05 Booster Box Inglés", "eb05", variants=[
                {"title":"Default Title", "available":True, "price":"140.00",
                 "inventory_policy":"continue","inventory_quantity":0}
            ])
        ]})
        self.assertEqual(x["EB05"]["status"], "NO_DISPONIBLE")

    def test_malformed_data_no_false_stock(self):
        with self.assertRaises(ValueError):
            parse_shopify_products({"error":"blocked"})

    def test_failed_http_does_not_claim_stock(self):
        session=Mock()
        session.get.return_value=Mock(status_code=403, url=CATALOG_URL)
        result=check_saruman(session)
        self.assertFalse(result["EB05"]["ok"])
        self.assertFalse(result["OP18"]["ok"])

    def test_catalog_one_request_both_sets(self):
        session=Mock()
        session.get.return_value=Mock(
            status_code=200,url=CATALOG_URL,
            json=lambda: {"products": [
                prod("One Piece EB-05 Booster Box English","eb05"),
                prod("One Piece OP-18 Booster Display Inglés","op18",False)
            ]}
        )
        result=check_saruman(session)
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(result["EB05"]["status"], "DISPONIBLE")
        self.assertEqual(result["OP18"]["status"], "NO_DISPONIBLE")

if __name__ == "__main__":
    unittest.main()
