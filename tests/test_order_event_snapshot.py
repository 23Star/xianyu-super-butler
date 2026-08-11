import unittest
from unittest.mock import Mock, patch

from XianyuAutoAsync import XianyuLive


class OrderEventSnapshotTests(unittest.TestCase):
    @staticmethod
    def _make_live(cookie_id: str, real_values: dict = None) -> XianyuLive:
        live = XianyuLive.__new__(XianyuLive)
        live.cookie_id = cookie_id
        live._pending_order_real_values = dict(real_values or {})
        return live

    def test_extracts_supported_transaction_status(self):
        message = {
            "1": {
                "10": {
                    "reminderContent": "[我已付款，等待你发货]",
                },
            },
        }

        self.assertEqual(
            XianyuLive._extract_order_event_status(message),
            "pending_ship",
        )

    def test_saves_real_values_from_seller_api(self):
        """卖家端接口的成交数据应原样落库，金额和数量不再按商品挂牌价推算。"""
        fake_db = Mock()
        fake_db.get_order_by_id.return_value = None
        fake_db.insert_or_update_order.return_value = True
        # 多件订单：单价 49.90 × 2 件 = 99.80，旧实现会错记为挂牌价 49.90
        live = self._make_live(
            "2217097925130",
            {
                "3315714027267035666": {
                    "amount": "99.80",
                    "buy_num": 2,
                    "auction_price": "49.90",
                    "confirm_fee": "",
                    "refund_fee": "99.80",
                    "post_fee": "0.00",
                    "receiver_name": "买家",
                    "receiver_phone": "13800000000",
                    "receiver_address": "某省某市某区某路 1 号",
                }
            },
        )
        message = {
            "1": {
                "2": "65134820995@goofish",
                "10": {
                    "reminderContent": "[我已拍下，待付款]",
                },
            },
        }

        with patch("app.db_manager.db_manager", fake_db):
            saved = live._save_order_event_snapshot(
                order_id="3315714027267035666",
                message=message,
                item_id="1070863591807",
                buyer_id="2214686388912",
            )

        self.assertTrue(saved)
        fake_db.insert_or_update_order.assert_called_once_with(
            order_id="3315714027267035666",
            item_id="1070863591807",
            buyer_id="2214686388912",
            quantity="2",
            amount="99.80",
            order_status="processing",
            cookie_id="2217097925130",
            created_at=None,
            chat_id="65134820995",
            buy_num=2,
            auction_price="49.90",
            confirm_fee=None,
            refund_fee="99.80",
            post_fee="0.00",
            receiver_name="买家",
            receiver_phone="13800000000",
            receiver_address="某省某市某区某路 1 号",
        )
        # 真值消费一次后应清空，避免同一订单的后续消息复用过期数据
        self.assertEqual(live._pending_order_real_values, {})

    def test_does_not_fabricate_amount_without_real_values(self):
        """接口不可用时只保留状态，不再回退到商品挂牌价。"""
        fake_db = Mock()
        fake_db.get_item_info.return_value = {"item_price": "¥0.01"}
        fake_db.get_order_by_id.return_value = None
        fake_db.insert_or_update_order.return_value = True
        live = self._make_live("2217097925130")

        with patch("app.db_manager.db_manager", fake_db):
            saved = live._save_order_event_snapshot(
                order_id="3315714027267035666",
                message={
                    "1": {
                        "2": "65134820995@goofish",
                        "10": {"reminderContent": "[我已拍下，待付款]"},
                    },
                },
                item_id="1070863591807",
                buyer_id="2214686388912",
            )

        self.assertTrue(saved)
        kwargs = fake_db.insert_or_update_order.call_args.kwargs
        self.assertIsNone(kwargs["amount"])
        self.assertIsNone(kwargs["quantity"])
        self.assertIsNone(kwargs["buy_num"])
        self.assertEqual(kwargs["order_status"], "processing")
        # 不应再查询商品表来凑金额
        fake_db.get_item_info.assert_not_called()

    def test_existing_order_details_are_not_overwritten_by_snapshot_defaults(self):
        fake_db = Mock()
        fake_db.get_order_by_id.return_value = {
            "item_id": "item-1",
            "buyer_id": "buyer-1",
            "quantity": "3",
            "amount": "72",
            "created_at": "2026-08-05 18:47:41",
        }
        fake_db.insert_or_update_order.return_value = True
        live = self._make_live("seller")

        with patch("app.db_manager.db_manager", fake_db):
            saved = live._save_order_event_snapshot(
                order_id="order-1",
                message={
                    "1": {
                        "2": "chat-1@goofish",
                        "10": {"reminderContent": "[你已发货]"},
                    },
                },
                item_id="item-1",
                buyer_id="buyer-1",
            )

        self.assertTrue(saved)
        fake_db.insert_or_update_order.assert_called_once_with(
            order_id="order-1",
            item_id=None,
            buyer_id=None,
            quantity=None,
            amount=None,
            order_status="shipped",
            cookie_id="seller",
            created_at=None,
            chat_id="chat-1",
            buy_num=None,
            auction_price=None,
            confirm_fee=None,
            refund_fee=None,
            post_fee=None,
            receiver_name=None,
            receiver_phone=None,
            receiver_address=None,
        )

    def test_ignores_non_transaction_messages(self):
        live = self._make_live("seller")

        self.assertFalse(
            live._save_order_event_snapshot(
                order_id="order-1",
                message={"1": {"10": {"reminderContent": "你好"}}},
            )
        )


if __name__ == "__main__":
    unittest.main()
