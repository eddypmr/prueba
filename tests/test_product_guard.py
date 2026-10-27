"""No confundir otros artículos ni preventas con stock confirmado."""
import unittest
from product_guard import is_english_display, direct_page_identity, guarded_stock

class ProductGuardTests(unittest.TestCase):
    def test_eb05_display(self):
        self.assertTrue(is_english_display("EB-05 Booster Box Display (24 sobres) Inglés", "EB05"))
    def test_op18_display(self):
        self.assertTrue(is_english_display("One Piece OP-18 Booster Box Inglés", "OP18"))
    def test_wrong_set(self):
        self.assertFalse(is_english_display("OP-18 Display 24 sobres English", "EB05"))
    def test_missing_english(self):
        self.assertFalse(is_english_display("EB-05 Display 24 sobres", "EB05"))
    def test_japanese(self):
        self.assertFalse(is_english_display("EB-05 Booster Box 24 sobres Japonés", "EB05"))
    def test_single_pack(self):
        self.assertFalse(is_english_display("EB-05 Booster Pack individual English", "EB05"))
    def test_case(self):
        self.assertFalse(is_english_display("EB-05 CASE 12 boxes English", "EB05"))
    def test_wrong_size(self):
        self.assertFalse(is_english_display("EB-05 Display 12 sobres inglés", "EB05"))
    def test_unsealed(self):
        self.assertFalse(is_english_display("EB-05 Display inglés desprecintada", "EB05"))
    def test_other_product_in_body(self):
        html="<h1>OP-17 Display 24 sobres inglés</h1><p>OP-18 Display inglés en stock</p>"
        self.assertFalse(is_english_display(direct_page_identity(html, "https://shop.test/op17"), "OP18"))
    def test_bandua_preorder_overrides_instock(self):
        html="<h1>Booster Box Display EB-05 (24 sobres) Inglés (PREORDER)</h1>"
        self.assertEqual(guarded_stock(html, "En stock 8", "https://shop.test/eb-05-display", "EB05", "DISPONIBLE"), "PREVENTA")
    def test_turol_reserva_overrides_instock(self):
        html="<h1>EB-05 Booster Display 24 sobres Inglés</h1>"
        t="Disponibilidad: RESERVA. APROX 30/10; Disponibilidad: EN STOCK"
        self.assertEqual(guarded_stock(html, t, "https://shop.test/item", "EB05", "DISPONIBLE"), "PREVENTA")
    def test_confirmed_stock_unchanged(self):
        html="<h1>EB-05 Booster Box 24 sobres Inglés</h1>"
        self.assertEqual(guarded_stock(html, "Añadir al carrito", "https://shop.test/eb05", "EB05", "DISPONIBLE"), "DISPONIBLE")
    def test_non_display_status_unknown(self):
        html="<h1>EB-05 1 sobre Inglés</h1>"
        self.assertEqual(guarded_stock(html, "En stock", "https://shop.test/item", "EB05", "DISPONIBLE"), "DESCONOCIDO")

if __name__ == "__main__":
    unittest.main()
