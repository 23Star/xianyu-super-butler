"""物流 Agent 发送路径回归：连续消息必须走带服务端确认的 IM 接口。"""

import unittest
from types import SimpleNamespace
from unittest import mock

from XianyuAutoAsync import XianyuLive


class LogisticsSendPathTests(unittest.IsolatedAsyncioTestCase):
    def _live(self):
        live = object.__new__(XianyuLive)
        live.cookie_id = "acc1"
        live._safe_str = str
        live._extract_message_id = lambda message_data: "m1"
        return live

    def _decision(self, messages):
        return SimpleNamespace(
            action="reply", messages=list(messages), reason="quoted",
            state_version=1, book_sha256="book",
        )

    async def _run(self, live, decision, send_im_text):
        agent = mock.Mock()
        agent.handle_message.return_value = decision
        agent.claim_send.return_value = True
        with mock.patch("app.services.logistics_agent.LogisticsQuoteAgent", return_value=agent), \
             mock.patch("app.db_manager.db_manager", mock.Mock()):
            live.send_im_text = send_im_text
            result = await live.get_logistics_reply(
                {}, "买家", "buyer1", "江苏到上海，130kg", "item1", "chat1", websocket=mock.Mock(),
            )
        return result, agent

    async def test_reply_messages_use_confirmed_im_send(self):
        live = self._live()
        sent = []

        async def fake_send_im_text(cid, toid, text):
            sent.append((cid, toid, text))

        async def forbidden_send_msg(*args, **kwargs):
            raise AssertionError("物流报价不能使用未确认的 websocket send_msg")

        live.send_msg = forbidden_send_msg
        result, agent = await self._run(live, self._decision(["报价消息", "补差价", "引导拍下"]), fake_send_im_text)

        self.assertTrue(result["send"])
        self.assertEqual([item[2] for item in sent], ["报价消息", "补差价", "引导拍下"])
        self.assertTrue(agent.mark_send_result.call_args.kwargs["success"])

    async def test_send_exception_marks_failure(self):
        live = self._live()

        async def failing_send_im_text(cid, toid, text):
            raise RuntimeError("平台拒绝")

        result, agent = await self._run(live, self._decision(["报价消息", "补差价"]), failing_send_im_text)

        self.assertFalse(result["send"])
        self.assertEqual(result["reason"], "send_failed")
        self.assertFalse(agent.mark_send_result.call_args.kwargs["success"])

    async def test_send_blocked_by_claim_gate(self):
        live = self._live()
        sent = []

        async def fake_send_im_text(cid, toid, text):
            sent.append(text)

        agent = mock.Mock()
        agent.handle_message.return_value = self._decision(["报价消息"])
        agent.claim_send.return_value = False
        with mock.patch("app.services.logistics_agent.LogisticsQuoteAgent", return_value=agent), \
             mock.patch("app.db_manager.db_manager", mock.Mock()):
            result = await live.get_logistics_reply(
                {}, "买家", "buyer1", "江苏到上海，130kg", "item1", "chat1", websocket=mock.Mock(),
            )

        self.assertFalse(result["send"])
        self.assertEqual(result["reason"], "send_blocked")
        self.assertEqual(sent, [])


class GenerateUuidTests(unittest.TestCase):
    def test_uuid_is_unique_per_call(self):
        from utils.xianyu_utils import generate_uuid

        first, second = generate_uuid(), generate_uuid()
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


if __name__ == "__main__":
    unittest.main()
