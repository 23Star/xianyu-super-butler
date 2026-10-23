"""自动收小红花：识别「买家赠送小红花」卡片并解析订单号。

回归的是这个故障：卡片标题是「你人真不错，送你闲鱼小红花」，里面既没有
「收到小红花」字样，也没有订单号，旧逻辑按提醒文案匹配永远不触发自动收花。
订单号实际在卡片 targetUrl 的 orderId 参数和 extJson 的 updateKey 里。
"""

import json
import unittest

from utils.message_utils import extract_received_flower_order

ORDER_ID = "5127422834001165401"
CHAT_ID = "63884496409"


def _card(target_url: str, title: str = "你人真不错，送你闲鱼小红花") -> str:
    return json.dumps(
        {
            "contentType": 26,
            "dxCard": {
                "item": {
                    "main": {
                        "exContent": {
                            "title": title,
                            "button": {"text": "立即收下", "targetUrl": target_url},
                        }
                    }
                }
            },
        },
        ensure_ascii=False,
    )


class ReceivedFlowerCardTests(unittest.TestCase):
    def test_extracts_order_from_real_received_card(self):
        """真实卡片：标题无订单号，订单号在 targetUrl 和 updateKey 里。"""
        message = {
            "1": {
                "6": {
                    "3": {
                        "2": "你人真不错，送你闲鱼小红花",
                        "5": _card(
                            "https://h5.m.goofish.com/wow/moyu/moyu-project/temp-pages/"
                            "pages/red-flower-play?kun=true&opaque=false&role=seller"
                            f"&confirm=false&orderId={ORDER_ID}"
                        ),
                    }
                },
                "10": {
                    "bizTag": json.dumps(
                        {
                            "sourceId": "RED_FLOWER:6Vn9xthdWg5D",
                            "taskName": "收到小红花-卖家",
                        },
                        ensure_ascii=False,
                    ),
                    "extJson": json.dumps(
                        {
                            "updateKey": f"{CHAT_ID}:{ORDER_ID}:received_red_flower",
                            "messageId": "dbec8689fbba42aa8578a97aba1e2908",
                        },
                        ensure_ascii=False,
                    ),
                    "reminderContent": "你人真不错，送你闲鱼小红花",
                },
            },
            "3": {"needPush": "true"},
        }
        self.assertEqual(extract_received_flower_order(message), ORDER_ID)

    def test_extracts_order_from_update_key_only(self):
        """没有卡片 JSON 时，仍能从 extJson 的 received_red_flower 标记里取订单号。"""
        message = {
            "1": {
                "10": {
                    "extJson": json.dumps(
                        {"updateKey": f"{CHAT_ID}:{ORDER_ID}:received_red_flower"}
                    )
                }
            }
        }
        self.assertEqual(extract_received_flower_order(message), ORDER_ID)

    def test_ignores_seller_request_card(self):
        """卖家发给买家的「求送小红花」卡片不能触发收花。"""
        message = {
            "1": {
                "6": {
                    "3": {
                        "2": "可以送我闲鱼小红花吗～",
                        "5": _card(
                            "https://h5.m.goofish.com/wow/moyu/moyu-project/temp-pages/"
                            f"pages/red-flower-play?role=buyer&orderId={ORDER_ID}",
                            title="求送小红花",
                        ),
                    }
                },
                "10": {
                    "bizTag": json.dumps({"taskName": "求送小红花-买家"}, ensure_ascii=False),
                    "extJson": json.dumps(
                        {"updateKey": f"{CHAT_ID}:{ORDER_ID}:want_red_flower"}
                    ),
                    "reminderContent": "可以送我闲鱼小红花吗～",
                },
            }
        }
        self.assertIsNone(extract_received_flower_order(message))

    def test_ignores_plain_message(self):
        self.assertIsNone(extract_received_flower_order({"1": {"10": {"reminderContent": "你好"}}}))
        self.assertIsNone(extract_received_flower_order({}))
        self.assertIsNone(extract_received_flower_order({"1": "4299791431660.PNM"}))


if __name__ == "__main__":
    unittest.main()
