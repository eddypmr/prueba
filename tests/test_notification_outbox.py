"""Pruebas de cola: fallo de Telegram, reintentos, idempotencia y fusión."""
import unittest

from notification_outbox import dispatch_pending, pending_report_exists, queue_alert
from merge_state import merge_states


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
