"""防止「未知商品、无金额」的空白订单落库。

回归两条路径：
1. 浏览器兜底抓到的是空白页（page_empty=True），fetch_order_detail_info 仍把
   全空字段写进数据库，之后再也不会被补全。
2. 账号作为买家下的单（例如测试号买东西）：卖家端 sold.get 查不到、商品也不在
   本账号商品列表里，交易卡片快照仍被当成卖出订单建单。
"""

import asyncio
import sys
import types
import unittest
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

from XianyuAutoAsync import XianyuLive

ORDER = "3316998400000000001"


def _make_live():
    live = XianyuLive.__new__(XianyuLive)
    live.cookie_id = "acc_blank"
    live.cookies_str = "k=v"
    live._order_detail_locks = defaultdict(asyncio.Lock)
    live._order_detail_lock_times = {}
    live.order_status_handler = None
    return live


class EmptyDetailPageTests(unittest.TestCase):
    def _fetch(self, browser_result):
        live = _make_live()
        fake_db = MagicMock()
        fake_db.get_cookie_by_id.return_value = {"id": live.cookie_id}
        # 浏览器抓取模块依赖 playwright；用替身模块隔离，只验证落库判断
        fetcher = types.ModuleType("utils.order_detail_fetcher")
        fetcher.fetch_order_detail_simple = AsyncMock(return_value=browser_result)
        with patch("app.db_manager.db_manager", fake_db), patch(
            "utils.seller_order_sync.fetch_order_detail_direct", AsyncMock(return_value=None)
        ), patch.dict(sys.modules, {"utils.order_detail_fetcher": fetcher}):
            result = asyncio.run(live.fetch_order_detail_info(ORDER, "item1", "buyer1"))
        return result, fake_db

    def test_empty_page_is_not_written(self):
        result, fake_db = self._fetch({"order_id": ORDER, "page_empty": True, "amount": ""})
        self.assertTrue(result["page_empty"], "调用方仍需拿到 page_empty 标记")
        fake_db.insert_or_update_order.assert_not_called()

    def test_rendered_page_is_written(self):
        _result, fake_db = self._fetch(
            {"order_id": ORDER, "page_empty": False, "amount": "88.00", "spec_value": "M"}
        )
        fake_db.insert_or_update_order.assert_called_once()
        self.assertEqual(fake_db.insert_or_update_order.call_args.kwargs["amount"], "88.00")


class UnownedOrderItemTests(unittest.TestCase):
    def setUp(self):
        self.live = _make_live()
        self.fake_db = MagicMock()
        self.patcher = patch("app.db_manager.db_manager", self.fake_db)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_item_missing_from_account_is_unowned(self):
        self.fake_db.get_item_info.return_value = None
        self.assertTrue(self.live._is_unowned_order_item("1023456789"))
        self.fake_db.get_item_info.assert_called_once_with("acc_blank", "1023456789")

    def test_own_item_is_owned(self):
        self.fake_db.get_item_info.return_value = {"item_id": "1023456789"}
        self.assertFalse(self.live._is_unowned_order_item("1023456789"))

    def test_uncertain_cases_default_to_owned(self):
        """拿不准时照常建单，不能因为判断失误丢掉真实卖出的订单。"""
        self.assertFalse(self.live._is_unowned_order_item(None))
        self.assertFalse(self.live._is_unowned_order_item(""))
        self.assertFalse(self.live._is_unowned_order_item("auto_123_1700000000"))
        self.fake_db.get_item_info.side_effect = RuntimeError("db locked")
        self.assertFalse(self.live._is_unowned_order_item("1023456789"))


if __name__ == "__main__":
    unittest.main()
