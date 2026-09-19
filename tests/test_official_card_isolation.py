"""官方卡片消息隔离：卡片只承载平台状态，不能进入任何回复链路。

回归的是这个故障：买家确认收货并评价后，闲鱼推送「我完成了评价」官方卡片。
卡片的 senderUserId 是买家、reminderContent 是卡片标题，和普通聊天消息长得
一模一样，于是物流 Agent 把它当成询价，自动发出了一条报价；同一时段
「买家已确认收货，交易成功」的工作台卡片也被通用 AI 回了一句。
"""

import base64
import json
import unittest
from unittest import mock

from app.xianyu_im import parse_message
from utils.message_utils import is_official_card_message
from XianyuAutoAsync import XianyuLive

MY_ID = "2222597651726"
BUYER_ID = "2200780192922"
CHAT_ID = "63884496409"


def _evaluation_card() -> dict:
    card = {
        "contentType": 26,
        "dxCard": {
            "item": {
                "main": {
                    "exContent": {
                        "title": "我完成了评价",
                        "desc": "期待你的评价",
                        "button": {"text": "去评价"},
                    },
                    "targetUrl": (
                        "fleamarket://order_detail?id=5127686100128074200&role=Seller"
                    ),
                }
            },
            "template": {"name": "idlefish_message_trade_chat_card"},
        },
    }
    return {
        "1": {
            "1": {"1": f"{BUYER_ID}@goofish"},
            "2": f"{CHAT_ID}@goofish",
            "5": 1789128921651,
            "6": {
                "1": 101,
                "3": {
                    "1": "",
                    "2": "[我完成了评价]",
                    "3": "",
                    "4": 26,
                    "5": json.dumps(card, ensure_ascii=False),
                },
            },
            "10": {
                "bizTag": json.dumps(
                    {"sourceId": "C2C:BpR10W4X1Pdp", "taskName": "期待评价_卖家"},
                    ensure_ascii=False,
                ),
                "detailNotice": "[我完成了评价]",
                "extJson": json.dumps(
                    {
                        "msgArg1": "MsgCard",
                        "messageId": "b923a19f29164f67bcca61ceb4f84698",
                        "contentType": "26",
                        "updateKey": (
                            f"{CHAT_ID}:5127686100128074200:10:BUYER_RATE_SELLER:26"
                        ),
                    },
                    ensure_ascii=False,
                ),
                "reminderContent": "[我完成了评价]",
                "reminderTitle": "我完成了评价",
                "senderUserId": BUYER_ID,
                "sessionType": "1",
            },
        },
        "3": {"needPush": "false"},
    }


def _workbench_card() -> dict:
    """工作台通知卡片：「买家已确认收货，交易成功」。"""
    card = {
        "contentType": 28,
        "dxCard": {
            "item": {
                "main": {
                    "exContent": {"title": "买家已确认收货，交易成功"},
                }
            },
            "template": {"name": "notify_center_trade_card"},
        },
    }
    return {
        "1": {
            "2": "64966072040@goofish",
            "6": {"1": 101, "3": {"2": "[卡片消息]", "4": 28, "5": json.dumps(card)}},
            "10": {
                "extJson": json.dumps({"msgArg1": "MsgCard", "messageId": "card-1"}),
                "reminderContent": "[卡片消息]",
                "reminderTitle": "工作台通知",
                "senderUserId": "2222216136891",
                "sessionType": "53",
            },
        },
    }


def _plain_text_message() -> dict:
    return {
        "1": {
            "1": {"1": f"{BUYER_ID}@goofish"},
            "2": f"{CHAT_ID}@goofish",
            "6": {"1": 101, "3": {"2": "运费多少钱", "4": 1, "5": ""}},
            "10": {
                "bizTag": json.dumps(
                    {"sourceId": "S:1", "messageId": "plain-1"}
                ),
                "extJson": json.dumps(
                    {"quickReply": "1", "messageId": "plain-1", "tag": "u"}
                ),
                "reminderContent": "运费多少钱",
                "reminderTitle": "买家",
                "senderUserId": BUYER_ID,
                "sessionType": "1",
            },
        },
    }


class OfficialCardDetectionTests(unittest.TestCase):
    def test_detects_evaluation_card(self):
        self.assertTrue(is_official_card_message(_evaluation_card()))

    def test_detects_workbench_trade_card(self):
        self.assertTrue(is_official_card_message(_workbench_card()))

    def test_detects_msg_tips(self):
        message = {
            "1": {
                "6": {"3": {"2": "[买家确认收货，交易成功]", "4": 14}},
                "10": {
                    "extJson": json.dumps(
                        {"msgArg1": "MsgTips", "contentType": "14"}
                    ),
                    "reminderContent": "[买家确认收货，交易成功]",
                    "senderUserId": BUYER_ID,
                },
            },
        }
        self.assertTrue(is_official_card_message(message))

    def test_plain_chat_message_is_not_card(self):
        message = _plain_text_message()
        self.assertFalse(is_official_card_message(message))

    def test_rejects_malformed_messages(self):
        for message in (
            {},
            None,
            {"1": "4299791431660.PNM"},
            {"1": {"10": {"reminderContent": "你好"}}},
        ):
            self.assertFalse(is_official_card_message(message))


class OfficialCardRenderTests(unittest.TestCase):
    def test_history_card_keeps_card_type_and_title(self):
        card = json.loads(_evaluation_card()["1"]["6"]["3"]["5"])
        payload = base64.b64encode(
            json.dumps(card, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")
        parsed = parse_message(
            {
                "message": {
                    "messageId": "card-msg-1",
                    "createAt": 1789128921651,
                    "extension": {
                        "senderUserId": f"{BUYER_ID}@goofish",
                        "reminderTitle": "买家",
                    },
                    "content": {"custom": {"type": 26, "data": payload}},
                }
            },
            MY_ID,
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["type"], "card")
        self.assertEqual(parsed["text"], "我完成了评价\n期待你的评价")
        self.assertFalse(parsed["isSelf"])

    def test_dynamic_card_without_title_still_renders_as_card(self):
        card = {
            "contentType": 26,
            "dxCard": {
                "item": {"main": {"exContent": {"button": {"text": "查看评价"}}}},
                "template": {"name": "idlefish_message_trade_chat_card"},
            },
        }
        payload = base64.b64encode(
            json.dumps(card, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")
        parsed = parse_message(
            {
                "message": {
                    "messageId": "card-msg-2",
                    "createAt": 1789128921651,
                    "extension": {"senderUserId": f"{BUYER_ID}@goofish"},
                    "content": {
                        "custom": {
                            "type": 26,
                            "data": payload,
                            "summary": "[我完成了评价]",
                        }
                    },
                }
            },
            MY_ID,
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["type"], "card")
        self.assertEqual(parsed["text"], "[我完成了评价]")


class OfficialCardReplyIsolationTests(unittest.IsolatedAsyncioTestCase):
    def _live(self) -> XianyuLive:
        live = object.__new__(XianyuLive)
        live.cookie_id = MY_ID
        live._safe_str = str
        live.get_logistics_reply = mock.AsyncMock()
        live.get_api_reply = mock.AsyncMock()
        live.get_keyword_reply = mock.AsyncMock()
        live.get_ai_reply = mock.AsyncMock()
        live.get_default_reply = mock.AsyncMock()
        return live

    async def test_reply_pipeline_never_touches_official_card(self):
        live = self._live()

        await live._process_chat_message_reply(
            _evaluation_card(),
            None,
            "买家",
            BUYER_ID,
            "[我完成了评价]",
            "1059371444032",
            CHAT_ID,
            "2026-09-11 20:15:21",
        )

        live.get_logistics_reply.assert_not_awaited()
        live.get_api_reply.assert_not_awaited()
        live.get_keyword_reply.assert_not_awaited()
        live.get_ai_reply.assert_not_awaited()
        live.get_default_reply.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
