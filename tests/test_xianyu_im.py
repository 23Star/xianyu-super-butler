import base64
import json
import unittest

from app.xianyu_im import parse_conversation, parse_message


class XianyuImParserTests(unittest.TestCase):
    def test_parse_conversation(self):
        payload = base64.b64encode(
            json.dumps({"contentType": 1, "text": {"text": "你好"}}).encode("utf-8")
        ).decode("utf-8")
        result = parse_conversation(
            {
                "singleChatConversation": {
                    "cid": "chat-1@goofish",
                    "pairFirst": "buyer-1@goofish",
                    "pairSecond": "seller-1@goofish",
                    "extension": json.dumps({
                        "itemId": "item-1",
                        "itemTitle": "测试商品",
                    }),
                },
                "lastMessage": {
                    "message": {
                        "content": {"custom": {"data": payload}},
                        "extension": {
                            "senderUserId": "buyer-1@goofish",
                            "reminderTitle": "买家",
                        },
                    }
                },
                "modifyTime": 123456,
                "redPoint": 2,
            },
            "seller-1",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["cid"], "chat-1")
        self.assertEqual(result["otherUserId"], "buyer-1")
        self.assertEqual(result["otherUserName"], "买家")
        self.assertEqual(result["lastMessageSummary"], "你好")
        self.assertEqual(result["itemId"], "item-1")

    def test_parse_text_message(self):
        payload = base64.b64encode(
            json.dumps({"contentType": 1, "text": {"text": "测试消息"}}).encode("utf-8")
        ).decode("utf-8")
        result = parse_message(
            {
                "message": {
                    "messageId": "message-1",
                    "createAt": 123456,
                    "extension": {
                        "senderUserId": "seller-1@goofish",
                        "reminderTitle": "卖家",
                    },
                    "content": {"custom": {"data": payload}},
                }
            },
            "seller-1",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result["isSelf"])
        self.assertEqual(result["type"], "text")
        self.assertEqual(result["text"], "测试消息")

    def _text_message(self, text):
        payload = base64.b64encode(
            json.dumps({"contentType": 1, "text": {"text": text}}).encode("utf-8")
        ).decode("utf-8")
        return {
            "message": {
                "messageId": "message-1",
                "createAt": 123456,
                "extension": {"senderUserId": "buyer-1@goofish", "reminderTitle": "买家"},
                "content": {"custom": {"data": payload}},
            }
        }

    def test_order_status_placeholder_treated_as_system(self):
        # 订单状态提醒是 contentType=1 纯文本，须按系统消息渲染成居中卡片
        for text in ("[卖家已发货]", "[我已拍下，待付款]", "[卡片消息]", "[记得及时发货]", "[交易关闭]", "[我完成了评价]"):
            result = parse_message(self._text_message(text), "seller-1")
            self.assertIsNotNone(result)
            self.assertEqual(result["type"], "system", text)
            self.assertEqual(result["text"], text)

    def test_emoji_placeholder_stays_text(self):
        # [流泪] 这类表情也是短方括号文本，但不是系统消息，不能渲染成卡片
        for text in ("[流泪]", "[捂脸]", "[笑哭]", "[哈哈]", "[玫瑰]"):
            result = parse_message(self._text_message(text), "seller-1")
            self.assertIsNotNone(result)
            self.assertEqual(result["type"], "text", text)

    def test_normal_bracket_text_stays_text(self):
        # 带上下文的真人消息（括号只是片段）和超长括号文本不误判为系统消息
        for text in ("[哈哈]可以的", "[今天天气不错呀，我们出去走走逛逛逛逛逛呀]"):
            result = parse_message(self._text_message(text), "seller-1")
            self.assertIsNotNone(result)
            self.assertEqual(result["type"], "text", text)


if __name__ == "__main__":
    unittest.main()
