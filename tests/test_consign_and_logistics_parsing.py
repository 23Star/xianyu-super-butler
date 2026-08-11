import unittest

from utils.xianyu_seller_api import parse_consign_render, parse_logistics_trace


class ParseConsignRenderTests(unittest.TestCase):
    @staticmethod
    def _data(**overrides):
        """构造 consign.page.render 的响应，结构与真实返回一致。"""
        data = {
            "bizOrderInfoList": [
                {
                    "buyerInfoVO": {
                        "address": "某省某市某区某路 1 号",
                        "name": "收货人",
                        "phone": "13800000000",
                        "userNick": "buyer",
                    },
                    "commonData": {
                        "itemId": 8800000000001,
                        "orderId": "9900000000000000001",
                        "needSerialNumber": False,
                        "needUploadReport": False,
                    },
                    "itemVO": {
                        # 商品 ID 和规格混在同一个列表里
                        "itemInfoLines": [
                            {"key": "商品ID", "value": "8800000000001"},
                            {"key": "规格", "value": "软件安装包/序列号/激活码"},
                        ],
                        "title": "测试商品",
                    },
                    "priceVO": {"auctionPrice": "80.00", "buyNum": 1},
                }
            ],
            "supportConsignType": ["DUMMY_CONSIGN", "OFFLINE_CONSIGN"],
        }
        data.update(overrides)
        return data

    def test_extracts_spec_and_skips_item_id_line(self):
        """规格是自动发货的依据，必须从 itemInfoLines 里挑出来而非误取商品ID。"""
        parsed = parse_consign_render(self._data())

        self.assertEqual(parsed["spec_name"], "规格")
        self.assertEqual(parsed["spec_value"], "软件安装包/序列号/激活码")

    def test_receiver_info_is_extracted(self):
        parsed = parse_consign_render(self._data())

        self.assertEqual(parsed["receiver_name"], "收货人")
        self.assertEqual(parsed["receiver_phone"], "13800000000")
        self.assertEqual(parsed["receiver_address"], "某省某市某区某路 1 号")

    def test_support_consign_type_is_exposed(self):
        """虚拟发货需要确认订单支持 DUMMY_CONSIGN。"""
        parsed = parse_consign_render(self._data())

        self.assertIn("DUMMY_CONSIGN", parsed["support_consign_type"])

    def test_falls_back_to_top_level_buyer_info(self):
        """订单级缺少买家信息时回退到顶层。"""
        data = self._data()
        data["bizOrderInfoList"][0].pop("buyerInfoVO")
        data["buyerInfoVO"] = {"name": "顶层收货人", "phone": "13900000000"}

        parsed = parse_consign_render(data)

        self.assertEqual(parsed["receiver_name"], "顶层收货人")

    def test_only_item_id_line_yields_empty_spec(self):
        data = self._data()
        data["bizOrderInfoList"][0]["itemVO"]["itemInfoLines"] = [
            {"key": "商品ID", "value": "123"}
        ]

        parsed = parse_consign_render(data)

        self.assertEqual(parsed["spec_name"], "")
        self.assertEqual(parsed["spec_value"], "")

    def test_empty_response_does_not_raise(self):
        parsed = parse_consign_render({})

        self.assertEqual(parsed["order_id"], "")
        self.assertEqual(parsed["buy_num"], 1)
        self.assertEqual(parsed["support_consign_type"], [])


class ParseLogisticsTraceTests(unittest.TestCase):
    @staticmethod
    def _data(**overrides):
        data = {
            "detailViewList": [
                {
                    "tradeIdAsString": "9900000000000000001",
                    "orderCode": "LP00000000000000",
                    # status 是结构体，不是字符串
                    "status": {
                        "statusCode": "CREATE",
                        "statusDesc": "已下单",
                        "statusSeq": 0,
                    },
                    "detailList": [
                        {
                            "time": "2026-08-04 23:08:15",
                            "desc": "商品已经下单",
                            "action": "CREATE",
                            "statusDesc": "已下单",
                        }
                    ],
                }
            ]
        }
        data.update(overrides)
        return data

    def test_status_uses_readable_description(self):
        """status 是字典，应取 statusDesc 而不是把整个字典字符串化。"""
        parsed = parse_logistics_trace(self._data())

        self.assertEqual(parsed["status"], "已下单")

    def test_mail_no_and_nodes_are_extracted(self):
        parsed = parse_logistics_trace(self._data())

        self.assertEqual(parsed["mail_no"], "LP00000000000000")
        self.assertEqual(len(parsed["nodes"]), 1)
        self.assertEqual(parsed["latest"]["desc"], "商品已经下单")

    def test_plain_string_status_still_works(self):
        data = self._data()
        data["detailViewList"][0]["status"] = "运输中"

        self.assertEqual(parse_logistics_trace(data)["status"], "运输中")

    def test_empty_response_does_not_raise(self):
        parsed = parse_logistics_trace({})

        self.assertEqual(parsed["nodes"], [])
        self.assertIsNone(parsed["latest"])
        self.assertEqual(parsed["package_count"], 0)


if __name__ == "__main__":
    unittest.main()
