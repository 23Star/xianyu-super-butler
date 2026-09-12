import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.db_manager import DBManager
from app.delivery_template import (
    build_card_delivery_payload,
    build_segments,
    is_template_enabled,
    normalize_images,
    parse_segments,
    render_template,
    send_payload,
    serialize_segments,
)


class DeliveryTemplateRenderingTests(unittest.TestCase):
    def test_render_replaces_known_tokens_and_keeps_unknown(self):
        rendered = render_template(
            "订单 {订单号} 的卡密：{发货内容}，未知：{不存在}",
            {"订单号": "A1", "发货内容": "CARD-1"},
        )

        self.assertEqual("订单 A1 的卡密：CARD-1，未知：{不存在}", rendered)

    def test_build_segments_splits_and_keeps_marker_order(self):
        images = {"1": "/static/uploads/a.png", "2": "/static/uploads/b.png"}

        segments = build_segments("第一段{分隔符}图一{图片1}图二{图片2}", images)

        self.assertEqual(
            [
                {"type": "text", "content": "第一段"},
                {"type": "text", "content": "图一"},
                {"type": "image", "url": "/static/uploads/a.png", "card_id": None},
                {"type": "text", "content": "图二"},
                {"type": "image", "url": "/static/uploads/b.png", "card_id": None},
            ],
            segments,
        )

    def test_unknown_image_token_is_kept_as_text(self):
        segments = build_segments("卡密{图片9}", {"1": "/static/uploads/a.png"})

        self.assertEqual([{"type": "text", "content": "卡密{图片9}"}], segments)

    def test_serialize_and_parse_roundtrip(self):
        segments = [
            {"type": "text", "content": "你好"},
            {"type": "image", "url": "/static/uploads/a.png", "card_id": None},
            {"type": "text", "content": "请查收"},
        ]

        payload = serialize_segments(segments)

        self.assertEqual(segments, parse_segments(payload))

    def test_parse_legacy_image_marker_keeps_card_id(self):
        segments = parse_segments("__IMAGE_SEND__12|/static/uploads/a.png")

        self.assertEqual(
            [{"type": "image", "url": "/static/uploads/a.png", "card_id": 12}],
            segments,
        )

    def test_parse_plain_text_returns_single_segment(self):
        self.assertEqual(
            [{"type": "text", "content": "CODE-1"}],
            parse_segments("CODE-1"),
        )

    def test_normalize_images_accepts_prefixed_keys_and_json(self):
        self.assertEqual(
            {"1": "/static/uploads/a.png", "2": "/static/uploads/b.png"},
            normalize_images('{"1": "/static/uploads/a.png", "图片2": "/static/uploads/b.png"}'),
        )

    def test_is_template_enabled_supports_prefixed_rule_fields(self):
        self.assertTrue(
            is_template_enabled({
                "card_delivery_template": "内容 {发货内容}",
                "card_delivery_template_enabled": 1,
            })
        )
        self.assertFalse(
            is_template_enabled({
                "card_delivery_template": "  ",
                "card_delivery_template_enabled": 1,
            })
        )


class DeliveryTemplatePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DBManager(os.path.join(self.temp_dir.name, "cards.db"))
        cursor = self.manager.conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO users (id, username, email, password_hash)
            VALUES (1, 'owner', 'owner@example.com', 'x')
            """
        )
        self.manager.conn.commit()

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def test_create_and_get_card_with_template_fields(self):
        card_id = self.manager.create_card(
            name="batch",
            card_type="data",
            data_content="CODE-1\nCODE-2",
            delivery_template="您好 {订单号}{分隔符}{发货内容}{图片1}",
            delivery_template_enabled=True,
            delivery_template_images={"1": "/static/uploads/a.png"},
            user_id=1,
        )

        card = self.manager.get_card_by_id(card_id, 1)

        self.assertTrue(card["delivery_template_enabled"])
        self.assertEqual("您好 {订单号}{分隔符}{发货内容}{图片1}", card["delivery_template"])
        self.assertEqual({"1": "/static/uploads/a.png"}, card["delivery_template_images"])
        self.assertEqual(1, len(self.manager.get_all_cards(1)))

    def test_update_card_can_clear_template(self):
        card_id = self.manager.create_card(
            name="batch",
            card_type="data",
            data_content="CODE-1",
            delivery_template="旧文案",
            delivery_template_enabled=True,
            delivery_template_images={"1": "/static/uploads/a.png"},
            user_id=1,
        )

        self.manager.update_card(
            card_id,
            delivery_template="",
            delivery_template_enabled=False,
            delivery_template_images={},
            user_id=1,
        )

        card = self.manager.get_card_by_id(card_id, 1)
        self.assertFalse(card["delivery_template_enabled"])
        self.assertEqual("", card["delivery_template"])
        self.assertEqual({}, card["delivery_template_images"])

    def test_legacy_rule_query_exposes_template_fields(self):
        card_id = self.manager.create_card(
            name="batch",
            card_type="data",
            data_content="CODE-1",
            delivery_template="{发货内容}",
            delivery_template_enabled=True,
            delivery_template_images={"1": "/static/uploads/a.png"},
            user_id=1,
        )
        self.manager.create_delivery_rule(
            "会员", card_id, user_id=1, cookie_id="seller-1"
        )

        rules = self.manager.get_delivery_rules_for_item(
            "会员商品", "seller-1", "item-1"
        )

        self.assertEqual(1, len(rules))
        self.assertEqual("{发货内容}", rules[0]["card_delivery_template"])
        self.assertTrue(rules[0]["card_delivery_template_enabled"])
        self.assertEqual(
            {"1": "/static/uploads/a.png"},
            rules[0]["card_delivery_template_images"],
        )


class DeliveryTemplateFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DBManager(os.path.join(self.temp_dir.name, "flow.db"))
        cursor = self.manager.conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO users (id, username, email, password_hash)
            VALUES (1, 'owner', 'owner@example.com', 'x')
            """
        )
        cursor.execute(
            "INSERT INTO cookies (id, value, user_id) VALUES ('seller-1', 'cookie', 1)"
        )
        cursor.execute(
            """
            INSERT INTO item_info (cookie_id, item_id, item_title, item_detail)
            VALUES ('seller-1', 'item-1', 'Subscription', 'detail')
            """
        )
        cursor.execute(
            """
            INSERT INTO cards (name, type, data_content, enabled, user_id)
            VALUES ('batch', 'data', 'CODE-1\nCODE-2', 1, 1)
            """
        )
        self.card_id = cursor.lastrowid
        self.manager.conn.commit()
        self.manager.create_delivery_rule(
            "Subscription", self.card_id, user_id=1, cookie_id="seller-1"
        )

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def _deliver(self):
        from XianyuAutoAsync import XianyuLive

        live = object.__new__(XianyuLive)
        live.cookie_id = "seller-1"
        live.order_status_handler = None
        live.save_item_info_to_db = AsyncMock()

        with patch("app.db_manager.db_manager", self.manager):
            return asyncio.run(
                live._auto_delivery(
                    "item-1",
                    "Subscription",
                    "order-1",
                    "buyer-1",
                )
            )

    def test_auto_delivery_renders_template_with_parameters_and_images(self):
        self.manager.update_card(
            self.card_id,
            delivery_template="您好 {订单号}，卡密如下：\n{发货内容}{分隔符}使用图：{图片1}",
            delivery_template_enabled=True,
            delivery_template_images={"1": "/static/uploads/tutorial.png"},
            user_id=1,
        )

        payload = self._deliver()

        self.assertEqual(
            [
                {"type": "text", "content": "您好 order-1，卡密如下：\nCODE-1"},
                {"type": "text", "content": "使用图："},
                {"type": "image", "url": "/static/uploads/tutorial.png", "card_id": None},
            ],
            parse_segments(payload),
        )

    def test_auto_delivery_appends_content_when_template_misses_token(self):
        self.manager.update_card(
            self.card_id,
            delivery_template="感谢购买，请尽快使用。",
            delivery_template_enabled=True,
            delivery_template_images={},
            user_id=1,
        )

        payload = self._deliver()

        self.assertEqual(
            [{"type": "text", "content": "感谢购买，请尽快使用。\n\nCODE-1"}],
            parse_segments(payload),
        )

    def test_auto_delivery_falls_back_to_description_when_disabled(self):
        cursor = self.manager.conn.cursor()
        cursor.execute(
            "UPDATE cards SET description = ? WHERE id = ?",
            ("合计：{DELIVERY_CONTENT}", self.card_id),
        )
        self.manager.conn.commit()

        payload = self._deliver()

        self.assertEqual("合计：CODE-1", payload)


class DeliveryTemplateSenderTests(unittest.TestCase):
    class _FakeLive:
        def __init__(self):
            self.calls = []

        async def send_msg(self, websocket, chat_id, buyer_id, content):
            self.calls.append(("text", content))

        async def send_image_msg(self, websocket, chat_id, buyer_id, image_url, card_id=None):
            self.calls.append(("image", image_url, card_id))

    def test_send_payload_sends_segments_in_order(self):
        live = self._FakeLive()
        payload = serialize_segments([
            {"type": "text", "content": "第一段"},
            {"type": "image", "url": "/static/uploads/a.png", "card_id": None},
            {"type": "text", "content": "第二段"},
        ])

        sent = asyncio.run(
            send_payload(live, object(), "chat", "buyer", payload, interval=0)
        )

        self.assertEqual(3, sent)
        self.assertEqual(
            [
                ("text", "第一段"),
                ("image", "/static/uploads/a.png", None),
                ("text", "第二段"),
            ],
            live.calls,
        )

    def test_send_payload_rejects_empty(self):
        live = self._FakeLive()

        with self.assertRaises(ValueError):
            asyncio.run(send_payload(live, object(), "chat", "buyer", "", interval=0))


if __name__ == "__main__":
    unittest.main()
