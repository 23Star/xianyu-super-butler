import unittest

from app.order_status_handler import OrderStatusHandler
from utils.order_status_rules import (
    detect_order_status_from_text,
    get_order_status,
    is_stable_order_status,
    normalize_order_status,
)


class OrderStatusRulesTests(unittest.TestCase):
    def test_numeric_status_codes_are_normalized(self):
        self.assertEqual(normalize_order_status(2), "pending_ship")
        self.assertEqual(normalize_order_status(5), "refunding")
        self.assertEqual(normalize_order_status("6"), "cancelled")
        self.assertEqual(normalize_order_status("9"), "refunding")
        self.assertEqual(normalize_order_status(12), "cancelled")

    def test_unknown_code_uses_status_text(self):
        self.assertEqual(
            normalize_order_status("WAIT_SELLER", "等待卖家处理退款"),
            "refunding",
        )

    def test_unknown_code_with_conflicting_text_uses_priority_rules(self):
        self.assertEqual(
            normalize_order_status("WAIT_SELLER", "交易成功 退款申请中"),
            "refunding",
        )

    def test_refund_text_wins_over_historical_completed_text(self):
        self.assertEqual(
            detect_order_status_from_text("交易成功 退款申请中"),
            "refunding",
        )

    def test_shipped_text_wins_over_generic_paid_text(self):
        self.assertEqual(
            detect_order_status_from_text("买家已付款，卖家已发货，待买家确认收货"),
            "shipped",
        )

    def test_refund_success_is_terminal_cancelled(self):
        self.assertEqual(
            detect_order_status_from_text("退款成功，钱款已原路退返"),
            "cancelled",
        )

    def test_refund_cancelled_restores_pre_refund_status(self):
        handler = OrderStatusHandler()
        handler._record_status_history(
            "order-1",
            "pending_ship",
            "refunding",
            "refund requested",
        )
        self.assertEqual(handler._get_previous_status("order-1"), "pending_ship")

    def test_invalid_backward_transition_is_rejected(self):
        handler = OrderStatusHandler()
        self.assertFalse(
            handler._is_valid_status_transition("completed", "pending_ship")
        )

    def test_order_status_field_wins_over_legacy_status(self):
        self.assertEqual(
            get_order_status({
                "order_status": "pending_ship",
                "status": "completed",
            }),
            "pending_ship",
        )

    def test_legacy_status_remains_supported(self):
        self.assertEqual(get_order_status({"status": "3"}), "shipped")

    def test_stable_status_detection(self):
        self.assertTrue(is_stable_order_status("shipped"))
        self.assertTrue(is_stable_order_status(12))
        self.assertFalse(is_stable_order_status("refunding"))
        self.assertFalse(is_stable_order_status("unknown"))

    def test_refund_cancelled_without_history_has_no_fallback(self):
        handler = OrderStatusHandler()
        self.assertIsNone(handler._get_previous_status("missing-order"))


if __name__ == "__main__":
    unittest.main()
