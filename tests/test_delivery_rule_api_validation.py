import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.reply_server import _validate_delivery_rule_scope


class DeliveryRuleApiValidationTests(unittest.TestCase):
    def _validate(self, delivery_count):
        with (
            patch("app.reply_server.db_manager.get_card_by_id", return_value={"id": 1}),
            patch(
                "app.reply_server.db_manager.get_all_cookies",
                return_value={"seller-a": "cookie"},
            ),
            patch(
                "app.reply_server.db_manager.get_item_info",
                return_value={"item_id": "item-1"},
            ),
        ):
            return _validate_delivery_rule_scope(
                {
                    "card_id": 1,
                    "cookie_id": "seller-a",
                    "item_id": "item-1",
                    "delivery_count": delivery_count,
                },
                user_id=1,
            )

    def test_accepts_positive_integer_delivery_count(self):
        self.assertEqual(self._validate(2)[4], 2)

    def test_rejects_zero_delivery_count(self):
        with self.assertRaises(HTTPException) as context:
            self._validate(0)

        self.assertEqual(context.exception.status_code, 400)

    def test_rejects_fractional_delivery_count(self):
        with self.assertRaises(HTTPException) as context:
            self._validate(1.5)

        self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
