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


if __name__ == "__main__":
    unittest.main()
