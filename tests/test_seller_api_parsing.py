import unittest

from utils.order_status_rules import normalize_order_status
from utils.xianyu_seller_api import XianyuSellerAPI, parse_sold_order


class ParseSoldOrderTests(unittest.TestCase):
    @staticmethod
    def _item(**overrides):
        """构造一条 sold.get 返回的订单，字段类型与真实响应一致。"""
        item = {
            # 接口返回的 orderId / itemId / buyerId 都是整数
            "commonData": {
                "orderId": 9900000000000000003,
                "itemId": 8800000000003,
                "orderStatus": "待发货",
                "createTime": "2026-08-09 12:00:00",
                "paySuccessTime": "2026-08-09 12:01:00",
                "sellerRateStatus": 4,
                "inRefund": False,
            },
            "buyerInfoVO": {
                "buyerId": 7700000000001,
                "userNick": "buyer-nick",
                "name": "收货人",
                "phone": "13800000000",
                "address": "某省某市某区某路 1 号",
                "isPrivacy": False,
            },
            "priceVO": {
                "totalPrice": "99.80",
                "auctionPrice": "49.90",
                "buyNum": 2,
                "postFee": "0.00",
                "discountFee": "0.00",
                "confirmFee": "",
                "refundFee": "",
            },
            "itemVO": {"title": "测试商品"},
            "rightVO": {
                "btnList": [
                    {"tradeAction": "LOGISTICS_SEND", "name": "去发货"},
                    {"tradeAction": "CLOSE_ORDER", "name": "关闭订单"},
                ]
            },
        }
        for section, values in overrides.items():
            item.setdefault(section, {}).update(values)
        return item

    def test_numeric_ids_are_converted_to_string(self):
        """整数 ID 必须转成字符串，否则落库后与消息链路的订单号对不上。"""
        parsed = parse_sold_order(self._item())

        self.assertEqual(parsed["order_id"], "9900000000000000003")
        self.assertEqual(parsed["item_id"], "8800000000003")
        self.assertEqual(parsed["buyer_id"], "7700000000001")
        self.assertIsInstance(parsed["order_id"], str)

    def test_amount_uses_total_price_not_unit_price(self):
        """多件订单的金额取成交总额，而不是单价。"""
        parsed = parse_sold_order(self._item())

        self.assertEqual(parsed["amount"], "99.80")
        self.assertEqual(parsed["auction_price"], "49.90")
        self.assertEqual(parsed["buy_num"], 2)

    def test_buy_num_defaults_to_one_when_missing(self):
        parsed = parse_sold_order(self._item(priceVO={"buyNum": None}))

        self.assertEqual(parsed["buy_num"], 1)

    def test_chinese_status_maps_to_canonical_status(self):
        """sold.get 返回中文状态，需能被现有归一化规则识别。"""
        cases = {
            "待发货": "pending_ship",
            "交易成功": "completed",
            "交易关闭": "cancelled",
        }
        for text, expected in cases.items():
            parsed = parse_sold_order(self._item(commonData={"orderStatus": text}))
            self.assertEqual(parsed["status_text"], text)
            self.assertEqual(
                normalize_order_status("", parsed["status_text"]),
                expected,
                f"状态 {text} 归一化结果不符",
            )

    def test_receiver_info_comes_from_buyer_info(self):
        parsed = parse_sold_order(self._item())

        self.assertEqual(parsed["receiver_name"], "收货人")
        self.assertEqual(parsed["receiver_phone"], "13800000000")
        self.assertEqual(parsed["receiver_address"], "某省某市某区某路 1 号")
        self.assertFalse(parsed["is_privacy"])

    def test_trade_actions_are_collected(self):
        parsed = parse_sold_order(self._item())

        self.assertEqual(parsed["trade_actions"], ["LOGISTICS_SEND", "CLOSE_ORDER"])

    def test_missing_sections_do_not_raise(self):
        parsed = parse_sold_order({})

        self.assertEqual(parsed["order_id"], "")
        self.assertEqual(parsed["amount"], "")
        self.assertEqual(parsed["buy_num"], 1)
        self.assertEqual(parsed["trade_actions"], [])


class BuildSearchParamTests(unittest.TestCase):
    def test_only_provided_fields_are_included(self):
        param = XianyuSellerAPI.build_search_param(
            create_start="2026-08-01", create_end="2026-08-09"
        )

        self.assertEqual(
            param, {"createStartTime": "2026-08-01", "createEndTime": "2026-08-09"}
        )

    def test_empty_input_returns_empty_dict(self):
        self.assertEqual(XianyuSellerAPI.build_search_param(), {})


if __name__ == "__main__":
    unittest.main()
