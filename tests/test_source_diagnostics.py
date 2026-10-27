"""Las fuentes en diagnóstico no pueden afirmar disponibilidad."""
import unittest
from unittest.mock import Mock
from diagnose_sources import inspect_html, diagnostic_check, DIAGNOSTIC_TARGETS

class SourceDiagnosticsTests(unittest.TestCase):
    def test_turol_reserva_ambiguous_labels(self):
        html = ('<h1>EB-05 Extra Booster Display 24 sobres Inglés</h1>'
                '<p>Disponibilidad: RESERVA. APROX 30/10/2026</p>'
                '<p>Disponibilidad: EN STOCK</p>'
                '<p>Disponibilidad: PRODUCTO AGOTADO</p>')
        self.assertEqual(inspect_html(html, DIAGNOSTIC_TARGETS["TUROL_EB05"]["url"], "EB05"), "PREVENTA")

    def test_bandua_preorder_and_stock(self):
        html = '<h1>Booster Box Display EB-05 (24 sobres) Inglés (PREORDER)</h1><p>En stock 8 Artículos</p>'
        self.assertEqual(inspect_html(html, DIAGNOSTIC_TARGETS["BANDUA_EB05"]["url"], "EB05"), "PREVENTA")

    def test_op18_valid_but_not_authorized_to_alert(self):
        html = "<h1>OP-18 Booster Display 24 Packs Inglés</h1><p>Añadir al carrito</p>"
        self.assertEqual(inspect_html(html, DIAGNOSTIC_TARGETS["TUROL_OP18"]["url"], "OP18"), "SIN_CONFIRMAR")

    def test_other_product_rejected(self):
        html = "<h1>OP-17 Booster Display 24 Packs Inglés</h1><p>OP-18 disponible</p>"
        self.assertEqual(inspect_html(html, "https://example.test/op-17", "OP18"), "IDENTIDAD_NO_VERIFICADA")

    def test_http_403_stays_diagnostic(self):
        session=Mock()
        session.get.return_value=Mock(status_code=403,url=DIAGNOSTIC_TARGETS["BANDUA_EB05"]["url"])
        self.assertEqual(diagnostic_check(session, "BANDUA_EB05", DIAGNOSTIC_TARGETS["BANDUA_EB05"]), "ERROR_HTTP_O_REDIRECCION")

    def test_no_stock_status_even_when_buy_button(self):
        html="<h1>EB-05 Booster Box 24 sobres Inglés</h1><button>Añadir al carrito</button>"
        self.assertNotEqual(inspect_html(html, "https://example.test/eb05", "EB05"), "DISPONIBLE")

    def test_paused_turol_never_makes_http_requests(self):
        from diagnose_sources import run_diagnostics
        session = Mock()
        run_diagnostics(session)
        requested = [call.args[0] for call in session.get.call_args_list]
        self.assertFalse(any("turolgames" in url for url in requested))


if __name__ == "__main__":
    unittest.main()
