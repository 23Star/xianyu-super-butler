"""自动收花必须接上 extract_received_flower_order。

extract_received_flower_order 已能从真实卡片里解析订单号（见
test_received_flower_card.py），但消息主流程仍按「收到小红花」字样匹配
send_message，而真实卡片标题是「你人真不错，送你闲鱼小红花」，所以自动收花
从未触发。这里固定住收花动作本身的开关、去重和失败重试语义。
"""

import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from XianyuAutoAsync import XianyuLive

ORDER = "5127422834001165401"


class AutoReceiveFlowerTests(unittest.TestCase):
    def setUp(self):
        self.live = XianyuLive.__new__(XianyuLive)
        self.live.cookie_id = "acc_flower"
        self.live.cookies_str = "k=v"

        self.flags = {"auto_receive_flower_enabled": True}
        self.fake_db = MagicMock()
        self.fake_db.get_buyer_interaction_settings.side_effect = lambda _cid: dict(self.flags)

        self.api = MagicMock()
        self.api.cookies_str = "k=v"
        self.api.close = AsyncMock()
        self.api.receive_flower = AsyncMock(return_value={})

        self.patches = [
            patch("app.db_manager.db_manager", self.fake_db),
            patch("utils.xianyu_seller_api.XianyuSellerAPI", return_value=self.api),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_message_handler_uses_card_parser(self):
        source = inspect.getsource(XianyuLive)
        self.assertIn("extract_received_flower_order(message)", source)
        self.assertNotIn("'收到小红花' in str(send_message)", source)

    def test_receives_once_per_order(self):
        self.assertTrue(asyncio.run(self.live._auto_receive_flower(ORDER)))
        self.assertFalse(asyncio.run(self.live._auto_receive_flower(ORDER)))
        self.api.receive_flower.assert_awaited_once_with(ORDER)
        self.api.close.assert_awaited()

    def test_disabled_switch_does_nothing(self):
        self.flags["auto_receive_flower_enabled"] = False
        self.assertFalse(asyncio.run(self.live._auto_receive_flower(ORDER)))
        self.api.receive_flower.assert_not_called()

    def test_failure_is_retried_on_next_card(self):
        self.api.receive_flower.side_effect = [RuntimeError("boom"), {}]
        self.assertFalse(asyncio.run(self.live._auto_receive_flower(ORDER)))
        self.assertTrue(asyncio.run(self.live._auto_receive_flower(ORDER)))
        self.assertEqual(self.api.receive_flower.await_count, 2)
        self.assertEqual(self.api.close.await_count, 2)


if __name__ == "__main__":
    unittest.main()
