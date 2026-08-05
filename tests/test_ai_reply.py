import asyncio
import unittest
from unittest.mock import Mock, patch

from app.ai_reply_engine import AIReplyEngine
from app.reply_server import _public_ai_reply_settings


class AIReplyEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = AIReplyEngine()

    def test_plain_text_custom_prompt_is_supported(self):
        prompt = self.engine._resolve_system_prompt("不要承诺库存，回复保持简短。", "default")

        self.assertIn("不要承诺库存", prompt)
        self.assertIn("资深电商卖家", prompt)

    def test_reply_is_normalized_and_limited(self):
        reply = self.engine._normalize_reply('  "你好，   现货可拍。"  ')
        long_reply = self.engine._normalize_reply("答" * 500)

        self.assertEqual(reply, "你好， 现货可拍。")
        self.assertEqual(len(long_reply), 300)

    def test_generate_reply_uses_model_without_logging_or_returning_empty_content(self):
        settings = {
            "ai_enabled": True,
            "model_name": "test-model",
            "api_key": "secret",
            "base_url": "https://example.invalid/v1",
            "max_discount_percent": 10,
            "max_discount_amount": 100,
            "max_bargain_rounds": 3,
            "custom_prompts": "回复保持简短。",
        }

        with (
            patch.object(self.engine, "is_ai_enabled", return_value=True),
            patch.object(self.engine, "detect_intent", return_value="default"),
            patch.object(
                self.engine,
                "save_conversation",
                side_effect=["2026-08-04 10:00:00", "2026-08-04 10:00:01"],
            ) as save_conversation,
            patch.object(
                self.engine,
                "_get_recent_user_messages",
                return_value=[{"content": "有货吗", "created_at": "2026-08-04 10:00:00"}],
            ),
            patch.object(self.engine, "get_conversation_context", return_value=[]),
            patch.object(self.engine, "get_bargain_count", return_value=0),
            patch.object(self.engine, "_is_dashscope_api", return_value=False),
            patch.object(self.engine, "_is_gemini_api", return_value=False),
            patch.object(self.engine, "_create_openai_client", return_value=Mock()),
            patch.object(
                self.engine,
                "_call_openai_api",
                return_value='  "有货，可以直接拍。"  ',
            ) as call_openai,
            patch("app.ai_reply_engine.db_manager.get_ai_reply_settings", return_value=settings),
        ):
            reply = self.engine.generate_reply(
                message="有货吗",
                item_info={"title": "测试商品", "price": 10, "desc": "测试"},
                chat_id="chat-1",
                cookie_id="account-1",
                user_id="buyer-1",
                item_id="item-1",
                skip_wait=True,
            )

        self.assertEqual(reply, "有货，可以直接拍。")
        self.assertEqual(save_conversation.call_count, 2)
        messages = call_openai.call_args.args[2]
        self.assertEqual(
            [entry["content"] for entry in messages if entry["role"] == "user"],
            ["有货吗"],
        )

    def test_context_roles_are_preserved_and_scoped_to_item(self):
        settings = {
            "ai_enabled": True,
            "model_name": "test-model",
            "api_key": "secret",
            "base_url": "https://example.invalid/v1",
            "max_discount_percent": 10,
            "max_discount_amount": 100,
            "max_bargain_rounds": 3,
            "context_enabled": True,
            "context_message_limit": 8,
            "context_expire_minutes": 60,
            "custom_prompts": "",
        }
        history = [
            {"role": "user", "content": "支持多久？"},
            {"role": "assistant", "content": "支持一周。"},
        ]

        with (
            patch.object(self.engine, "is_ai_enabled", return_value=True),
            patch.object(self.engine, "detect_intent", return_value="default"),
            patch.object(
                self.engine, "save_conversation",
                side_effect=["2026-08-04 10:00:00", "2026-08-04 10:00:01"],
            ),
            patch.object(
                self.engine, "_get_recent_user_messages",
                return_value=[{"content": "怎么使用？", "created_at": "2026-08-04 10:00:00"}],
            ),
            patch.object(self.engine, "get_conversation_context", return_value=history) as get_context,
            patch.object(self.engine, "get_bargain_count", return_value=0),
            patch.object(self.engine, "_is_dashscope_api", return_value=False),
            patch.object(self.engine, "_is_gemini_api", return_value=False),
            patch.object(self.engine, "_create_openai_client", return_value=Mock()),
            patch.object(self.engine, "_call_openai_api", return_value="按说明激活即可。") as call_openai,
            patch("app.ai_reply_engine.db_manager.get_ai_reply_settings", return_value=settings),
        ):
            self.engine.generate_reply(
                "怎么使用？", {"title": "周卡", "price": 80, "desc": "独享"},
                "chat-1", "account-1", "buyer-1", "item-9", True,
            )

        self.assertEqual(get_context.call_args.kwargs["item_id"], "item-9")
        self.assertEqual(get_context.call_args.kwargs["limit"], 8)
        self.assertEqual(get_context.call_args.kwargs["max_age_minutes"], 60)
        messages = call_openai.call_args.args[2]
        self.assertEqual(
            [(entry["role"], entry["content"]) for entry in messages[1:]],
            [
                ("user", "支持多久？"),
                ("assistant", "支持一周。"),
                ("user", "怎么使用？"),
            ],
        )

    def test_disabled_context_does_not_query_history(self):
        settings = {
            "ai_enabled": True,
            "model_name": "test-model",
            "api_key": "secret",
            "base_url": "https://example.invalid/v1",
            "max_bargain_rounds": 3,
            "context_enabled": False,
            "custom_prompts": "",
        }
        with (
            patch.object(self.engine, "is_ai_enabled", return_value=True),
            patch.object(self.engine, "detect_intent", return_value="default"),
            patch.object(
                self.engine, "save_conversation",
                side_effect=["2026-08-04 10:00:00", "2026-08-04 10:00:01"],
            ),
            patch.object(
                self.engine, "_get_recent_user_messages",
                return_value=[{"content": "你好", "created_at": "2026-08-04 10:00:00"}],
            ),
            patch.object(self.engine, "get_conversation_context") as get_context,
            patch.object(self.engine, "get_bargain_count", return_value=0),
            patch.object(self.engine, "_is_dashscope_api", return_value=False),
            patch.object(self.engine, "_is_gemini_api", return_value=False),
            patch.object(self.engine, "_create_openai_client", return_value=Mock()),
            patch.object(self.engine, "_call_openai_api", return_value="你好"),
            patch("app.ai_reply_engine.db_manager.get_ai_reply_settings", return_value=settings),
        ):
            self.engine.generate_reply("你好", {}, "chat", "account", "buyer", "item", True)
        get_context.assert_not_called()

    def test_gemini_preserves_multi_turn_roles(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "可以"}]}}]
        }
        settings = {"api_key": "secret", "model_name": "gemini-test"}
        messages = [
            {"role": "system", "content": "系统规则"},
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "第一答"},
            {"role": "user", "content": "第二问"},
        ]
        with patch("app.ai_reply_engine.requests.post", return_value=response) as post:
            result = self.engine._call_gemini_api(settings, messages)

        self.assertEqual(result, "可以")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(
            [entry["role"] for entry in payload["contents"]],
            ["user", "model", "user"],
        )
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "系统规则")

    def test_system_and_order_events_bypass_ai(self):
        for message in (
            "[我已拍下，待付款]",
            "[已付款，待发货]",
            "[退款成功，钱款已原路退返]",
            "快给ta一个评价吧~",
        ):
            self.assertTrue(self.engine.is_system_or_order_event(message))

        with (
            patch.object(self.engine, "is_ai_enabled", return_value=True),
            patch.object(self.engine, "save_conversation") as save,
        ):
            result = self.engine.generate_reply(
                "[已付款，待发货]", {}, "chat", "account", "buyer", "item", True
            )
        self.assertIsNone(result)
        save.assert_not_called()

    def test_public_settings_never_return_api_key(self):
        result = _public_ai_reply_settings({
            "ai_enabled": True,
            "api_key": "top-secret",
            "model_name": "test-model",
        })

        self.assertEqual(result["api_key"], "")
        self.assertTrue(result["api_key_configured"])


class AIReplyAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_wrapper_runs_sync_generation_off_event_loop(self):
        def slow_reply(*_args):
            import time
            time.sleep(0.05)
            return "完成"

        with patch.object(self.engine, "generate_reply", side_effect=slow_reply):
            marker = []
            task = asyncio.create_task(
                self.engine.generate_reply_async(
                    "消息", {}, "chat", "account", "buyer", "item", True
                )
            )
            await asyncio.sleep(0)
            marker.append("event-loop-responsive")
            result = await task

        self.assertEqual(marker, ["event-loop-responsive"])
        self.assertEqual(result, "完成")

    def setUp(self):
        self.engine = AIReplyEngine()


if __name__ == "__main__":
    unittest.main()
