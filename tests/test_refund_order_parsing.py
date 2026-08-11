import unittest

from utils.order_status_rules import normalize_order_status
from utils.xianyu_seller_api import parse_refund_order


class ParseRefundOrderTests(unittest.TestCase):
    @staticmethod
    def _item(**overrides):
        """构造一条 refund.list 返回的退款单，字段与真实响应一致。"""
        item = {
            "commonData": {
                "orderId": 9900000000000000002,
                "itemId": 8800000000001,
                "orderStatus": "未发货退款",
                "createTime": "2026-08-05 11:47:18",
                "refundStatus": 5,
            },
            # 退款接口不返回收货信息，只有买家标识
            "buyerInfoVO": {"buyerId": 660000001, "userNick": "buyer"},
            # 注意没有 totalPrice 和 confirmFee
            "priceVO": {"auctionPrice": "80.00", "buyNum": 1, "refundFee": "80.00"},
            "itemVO": {"title": "测试商品"},
            "refundInfoVO": {
                "refundId": 5500000000000000001,
                "reason": "双方协商一致",
                "refundStatus": "已退款买家¥80.00（待发货）",
            },
        }
        for section, values in overrides.items():
            item.setdefault(section, {}).update(values)
        return item

    def test_amount_is_unit_price_times_quantity(self):
        """缺少 totalPrice 时按单价乘件数估算成交额。"""
        parsed = parse_refund_order(
            self._item(priceVO={"auctionPrice": "3.00", "buyNum": 50})
        )

        self.assertEqual(parsed["amount"], "150.00")
        self.assertEqual(parsed["auction_price"], "3.00")
        self.assertEqual(parsed["buy_num"], 50)

    def test_confirm_fee_is_zero_so_refunds_never_count_as_revenue(self):
        """退款单的卖家实收必须为 0，否则会被计入营收。"""
        parsed = parse_refund_order(self._item())

        self.assertEqual(parsed["confirm_fee"], "0.00")
        self.assertEqual(parsed["refund_fee"], "80.00")
        self.assertTrue(parsed["in_refund"])

    def test_numeric_ids_are_converted_to_string(self):
        parsed = parse_refund_order(self._item())

        self.assertEqual(parsed["order_id"], "9900000000000000002")
        self.assertEqual(parsed["item_id"], "8800000000001")
        self.assertEqual(parsed["buyer_id"], "660000001")

    def test_no_receiver_info_is_exposed(self):
        """退款接口没有收货信息，不应凭空产生这些字段。"""
        parsed = parse_refund_order(self._item())

        for key in ("receiver_name", "receiver_phone", "receiver_address"):
            self.assertNotIn(key, parsed)

    def test_refund_status_never_maps_to_valid_order_status(self):
        """所有退款状态文案都必须归一化为 refunding，不能落进计入营收的状态。"""
        revenue_statuses = {"pending_ship", "shipped", "completed"}
        for text in ("未发货退款", "已发货退款", "退货退款"):
            parsed = parse_refund_order(self._item(commonData={"orderStatus": text}))
            status = normalize_order_status("", parsed["status_text"])
            self.assertEqual(status, "refunding", f"状态 {text} 归一化错误")
            self.assertNotIn(status, revenue_statuses)

    def test_missing_price_does_not_raise(self):
        parsed = parse_refund_order({"commonData": {"orderId": 1}})

        self.assertEqual(parsed["order_id"], "1")
        self.assertEqual(parsed["amount"], "")
        self.assertEqual(parsed["buy_num"], 1)

    def test_non_numeric_price_falls_back_to_raw_value(self):
        parsed = parse_refund_order(
            self._item(priceVO={"auctionPrice": "面议", "buyNum": 1})
        )

        self.assertEqual(parsed["amount"], "面议")


if __name__ == "__main__":
    unittest.main()
