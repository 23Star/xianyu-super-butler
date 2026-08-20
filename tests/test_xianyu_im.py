import base64
import json
import unittest

from app.xianyu_im import (
    make_image_content,
    make_video_content,
    parse_conversation,
    parse_message,
)


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
                        "messageId": "msg-last",
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
        self.assertEqual(result["lastMessageId"], "msg-last")
        self.assertEqual(result["unreadCount"], 2)
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

    def test_parse_https_image_message(self):
        payload = base64.b64encode(
            json.dumps({
                "contentType": 2,
                "image": {"pics": [{"url": "http://gw.alicdn.com/a.jpg"}]},
            }).encode("utf-8")
        ).decode("utf-8")
        result = parse_message(
            {
                "message": {
                    "messageId": "image-1",
                    "createAt": 123456,
                    "extension": {"senderUserId": "buyer-1@goofish"},
                    "content": {"custom": {"data": payload}},
                }
            },
            "seller-1",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "image")
        self.assertEqual(result["images"], ["https://gw.alicdn.com/a.jpg"])
        self.assertIsNone(result["audio"])
        self.assertIsNone(result["video"])

    def test_parse_media_id_image_message(self):
        import msgpack
        from utils.im_media import resolve_media

        encoded = base64.urlsafe_b64encode(
            msgpack.packb([0, 1000, 600, 800], use_bin_type=True)
        ).decode().rstrip("=")
        media_id = f"@{encoded}"
        payload = base64.b64encode(
            json.dumps({
                "contentType": 2,
                "image": {"pics": [{"url": media_id}]},
            }).encode("utf-8")
        ).decode("utf-8")
        result = parse_message(
            {
                "message": {
                    "messageId": "image-2",
                    "createAt": 123456,
                    "extension": {"senderUserId": "buyer-1@goofish"},
                    "content": {"custom": {"data": payload}},
                }
            },
            "seller-1",
            "down.im.dingtalk.cn",
        )
        self.assertEqual(result["type"], "image")
        self.assertEqual(result["images"], [resolve_media(media_id)["url"]])

    def test_parse_audio_message(self):
        payload = base64.b64encode(
            json.dumps({
                "contentType": 3,
                "audio": {
                    "url": "https://gw.alicdn.com/a.amr",
                    "durationMs": 3200,
                },
            }).encode("utf-8")
        ).decode("utf-8")
        result = parse_message(
            {
                "message": {
                    "messageId": "audio-1",
                    "createAt": 123456,
                    "extension": {"senderUserId": "buyer-1@goofish"},
                    "content": {"custom": {"data": payload}},
                }
            },
            "seller-1",
        )
        self.assertEqual(result["type"], "audio")
        self.assertEqual(result["audio"]["url"], "https://gw.alicdn.com/a.amr")
        self.assertEqual(result["audio"]["durationMs"], 3200)
        self.assertEqual(result["text"], "")

    def test_parse_video_message(self):
        payload = base64.b64encode(
            json.dumps({
                "contentType": 4,
                "video": {
                    "url": "https://gw.alicdn.com/a.mp4",
                    "poster": "https://gw.alicdn.com/p.jpg",
                    "width": 1280,
                    "height": 720,
                },
            }).encode("utf-8")
        ).decode("utf-8")
        result = parse_message(
            {
                "message": {
                    "messageId": "video-1",
                    "createAt": 123456,
                    "extension": {"senderUserId": "buyer-1@goofish"},
                    "content": {"custom": {"data": payload}},
                }
            },
            "seller-1",
        )
        self.assertEqual(result["type"], "video")
        self.assertEqual(result["video"]["url"], "https://gw.alicdn.com/a.mp4")
        self.assertEqual(result["video"]["poster"], "https://gw.alicdn.com/p.jpg")
        self.assertEqual(result["video"]["width"], 1280)

    def test_conversation_summaries_for_media(self):
        from app.xianyu_im import extract_message_summary

        def last_message(payload):
            encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
            return {"content": {"custom": {"data": encoded}}}

        self.assertEqual(
            extract_message_summary(last_message({
                "contentType": 2,
                "image": {"pics": [{"url": "https://gw.alicdn.com/a.jpg"}]},
            })),
            "[图片]",
        )
        self.assertEqual(
            extract_message_summary(last_message({
                "contentType": 3,
                "audio": {"url": "https://gw.alicdn.com/a.amr"},
            })),
            "[语音]",
        )
        self.assertEqual(
            extract_message_summary(last_message({
                "contentType": 4,
                "video": {"url": "https://gw.alicdn.com/a.mp4"},
            })),
            "[视频]",
        )

    def test_make_image_content(self):
        payload = make_image_content("https://gw.alicdn.com/a.jpg", 640, 480)
        self.assertEqual(payload["contentType"], 2)
        self.assertEqual(payload["image"]["pics"][0]["url"], "https://gw.alicdn.com/a.jpg")
        self.assertEqual(payload["image"]["pics"][0]["width"], 640)
        self.assertEqual(payload["image"]["pics"][0]["height"], 480)

    def test_make_video_content(self):
        payload = make_video_content("https://gw.alicdn.com/a.mp4", 1280, 720, 5400)
        self.assertEqual(payload["contentType"], 4)
        self.assertEqual(payload["video"]["url"], "https://gw.alicdn.com/a.mp4")
        self.assertEqual(payload["video"]["width"], 1280)
        self.assertEqual(payload["video"]["durationMs"], 5400)


if __name__ == "__main__":
    unittest.main()
