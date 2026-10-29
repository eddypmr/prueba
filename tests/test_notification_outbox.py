"""Pruebas de cola: fallo de Telegram, reintentos, idempotencia y fusión."""
import unittest

from notification_outbox import dispatch_pending, pending_report_exists, queue_alert
from merge_state import merge_states
from monitor import (build_status_report, telegram_product_message,
                     notify_if_transition, notify_op18_transition)


class TelegramPresentationTests(unittest.TestCase):
    def test_available_message_tells_user_to_enter(self):
        msg = telegram_product_message(
            "EB-05", "GARHIS", "DISPONIBLE",
            "https://garhis.es/eb-05", "129,95 €")
        self.assertTrue(msg.startswith("🟢 EB-05 DISPONIBLE — ENTRA AHORA"))
        self.assertIn("129,95 €", msg)
        self.assertIn("https://garhis.es/eb-05", msg)

    def test_out_of_stock_message_tells_user_not_to_enter(self):
        msg = telegram_product_message(
            "EB-05", "GARHIS", "NO_DISPONIBLE",
            "https://garhis.es/eb-05")
        self.assertTrue(msg.startswith("🔴 EB-05 AGOTADO"))
        self.assertNotIn("ENTRA AHORA", msg)

    def test_unverified_listing_is_not_a_buy_alert(self):
        msg = telegram_product_message(
            "OP-18", "METROPOLIS_CENTER", "DESCONOCIDO",
            "https://metropolis-center.com/")
        self.assertTrue(msg.startswith("🟡 OP-18"))
        self.assertIn("STOCK SIN CONFIRMAR", msg)
        self.assertNotIn("ENTRA AHORA", msg)

    def test_summary_never_marks_out_of_stock_as_available(self):
        result = build_status_report({
            "GARHIS": {"healthy": True, "status": "NO_DISPONIBLE"},
            "KABURI": {"healthy": True, "status": "DISPONIBLE",
                       "price": "200 €"},
            "HEROFREAKS": {"healthy": False, "status": "DESCONOCIDO"},
        })
        self.assertIn("🟢 EB-05 · Kaburi · 200 €", result)
        self.assertIn("🔴 Agotado: Garhis", result)
        self.assertIn("⚪ No verificable: Herofreaks", result)
        self.assertNotIn("🟢 EB-05 · Garhis", result)
        self.assertIn("Solo 🟢 indica compra habilitada", result)

    def test_only_confirmed_transition_is_buy_alert(self):
        state = {}
        previous = {"mode": "direct", "status": "NO_DISPONIBLE"}
        current = {"mode": "direct", "status": "DISPONIBLE",
                   "last_changed": "t1", "url": "https://garhis.es/eb05"}
        notify_if_transition("GARHIS", previous, current, state)
        alert = next(iter(state["_outbox"].values()))
        self.assertIn("ENTRA AHORA", alert["message"])

        state2 = {}
        current2 = dict(current, status="DESCONOCIDO")
        notify_op18_transition("KABURI", previous, current2, state2)
        self.assertNotIn("_outbox", state2)


class NotificationOutboxTests(unittest.TestCase):
    def test_failed_send_retains_pending_until_next_run(self):
        state = {}
        queue_alert(state, "OP18_KABURI", "2026-10-16T10:00:00Z", "Stock OP-18")
        dispatch_pending(state, sender=lambda _: False)
        item = next(iter(state["_outbox"].values()))
        self.assertIsNone(item["sent_at"])
        self.assertEqual(item["attempts"], 1)
        self.assertEqual(dispatch_pending(state, sender=lambda _: True), (1, 0))
        self.assertIsNotNone(item["sent_at"])
        self.assertEqual(item["attempts"], 2)

    def test_duplicate_run_cannot_queue_same_transition_twice(self):
        state = {}
        for _ in range(3):
            queue_alert(state, "EB05_GARHIS", "2026-10-16T10:00:00Z", "Stock EB-05")
        self.assertEqual(len(state["_outbox"]), 1)

    def test_new_transition_queues_new_alert(self):
        state = {}
        queue_alert(state, "EB05_GARHIS", "a", "Stock EB-05")
        queue_alert(state, "EB05_GARHIS", "b", "Stock EB-05")
        self.assertEqual(len(state["_outbox"]), 2)

    def test_success_is_not_resent(self):
        state = {}
        queue_alert(state, "OP18_KABURI", "a", "Stock OP-18")
        dispatch_pending(state, sender=lambda _: True)
        called = []
        dispatch_pending(state, sender=lambda msg: called.append(msg))
        self.assertEqual(called, [])

    def test_failure_stops_batch_and_preserves_remaining_alerts(self):
        state = {}
        queue_alert(state, "EB05_A", "a", "a")
        queue_alert(state, "EB05_B", "b", "b")
        self.assertEqual(dispatch_pending(state, sender=lambda _: False), (0, 2))

    def test_delivered_receipt_survives_remote_merge(self):
        fresh = {}
        queue_alert(fresh, "EB05_GARHIS", "x", "text")
        delivered = {"_outbox": {k: dict(v) for k, v in fresh["_outbox"].items()}}
        delivered_item = next(iter(delivered["_outbox"].values()))
        delivered_item["sent_at"] = "2026-10-16T11:11:00Z"
        merged = merge_states(fresh, delivered)
        self.assertEqual(next(iter(merged["_outbox"].values()))["sent_at"],
                         "2026-10-16T11:11:00Z")

    def test_new_pending_not_discarded_when_remote_has_old_alert(self):
        local = {}
        queue_alert(local, "OP18_B", "b", "b")
        remote = {}
        queue_alert(remote, "EB05_A", "a", "a")
        self.assertEqual(len(merge_states(local, remote)["_outbox"]), 2)

    def test_successful_report_sets_report_timestamp(self):
        state = {}
        queue_alert(state, "status_report", "period1", "report", kind="report")
        self.assertTrue(pending_report_exists(state))
        dispatch_pending(state, sender=lambda _: True)
        self.assertFalse(pending_report_exists(state))
        self.assertIsNotNone(state["_meta"]["last_status_report"])

    def test_unsent_report_blocks_a_second_queued_report(self):
        state = {}
        queue_alert(state, "status_report", "period1", "report", kind="report")
        self.assertTrue(pending_report_exists(state))

    def test_send_exception_keeps_alert_pending(self):
        state = {}
        queue_alert(state, "EB05_GARHIS", "x", "text")
        def offline(_):
            raise RuntimeError("offline")
        self.assertEqual(dispatch_pending(state, sender=offline), (0, 1))

    def test_older_state_cannot_erase_newer_store_state(self):
        result = merge_states(
            {"KABURI": {"last_changed": "2026-10-14T00:00:00+00:00", "status": "NO_DISPONIBLE"}},
            {"KABURI": {"last_changed": "2026-10-16T00:00:00+00:00", "status": "DISPONIBLE"}},
        )
        self.assertEqual(result["KABURI"]["status"], "DISPONIBLE")

    def test_persist_callback_is_invoked_on_failure(self):
        state = {}
        queue_alert(state, "EB05_GARHIS", "x", "text")
        snapshots = []
        dispatch_pending(state, sender=lambda _: False,
                         persist=lambda value: snapshots.append(dict(value["_outbox"])))
        self.assertEqual(len(snapshots), 1)


if __name__ == "__main__":
    unittest.main()
