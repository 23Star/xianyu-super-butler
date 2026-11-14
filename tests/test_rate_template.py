"""自动评价必须使用买家互动页保存的文案。

回归的是这个故障：买家互动页把评价文案存为 auto_rate_template，执行端却读
auto_rate_content，用户编辑的文案从未生效，评价永远是内置默认句。
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from XianyuAutoAsync import XianyuLive

ORDER = "3300000000000000001"


def _sold_item(actions=None, seller_rate_status=0):
    return {
        "commonData": {"orderId": ORDER, "sellerRateStatus": seller_rate_status},
        "rightVO": {"btnList": [{"tradeAction": a} for a in (actions or [])]},
    }


class RateTemplateTests(unittest.TestCase):
    def setUp(self):
        self.live = XianyuLive.__new__(XianyuLive)
        self.live.cookie_id = "acc_interaction"
        self.live.cookies_str = "k=v"
        self.live._auto_rated_orders = set()
        self.live._auto_flowered_orders = set()

        self.settings = {}
        self.fake_db = MagicMock()
        self.fake_db.get_system_setting.side_effect = self.settings.get

        self.api = MagicMock()
        self.api.cookies_str = "k=v"
        self.api.close = AsyncMock()
        self.api.create_rate = AsyncMock(return_value={"success": True})
        self.api.require_flower = AsyncMock(return_value={})
        self.items = [_sold_item()]
        self.api.get_sold_orders = AsyncMock(side_effect=lambda **_: {"items": self.items})

        self.patches = [
            patch("app.db_manager.db_manager", self.fake_db),
            patch("utils.xianyu_seller_api.XianyuSellerAPI", return_value=self.api),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _run(self, rate_on=False, flower_on=False):
        return asyncio.run(self.live._run_buyer_interactions(rate_on, flower_on))

    def test_rate_uses_template_saved_by_settings_page(self):
        self.settings["auto_rate_template"] = "装备完好收到，感谢支持"
        self._run(rate_on=True)
        self.assertEqual(
            self.api.create_rate.await_args.kwargs["feedback"], "装备完好收到，感谢支持"
        )

    def test_rate_falls_back_to_legacy_key_then_default(self):
        self.settings["auto_rate_content"] = "旧键文案"
        self._run(rate_on=True)
        self.assertEqual(self.api.create_rate.await_args.kwargs["feedback"], "旧键文案")

        self.settings.clear()
        self.live._auto_rated_orders.clear()
        self._run(rate_on=True)
        self.assertEqual(
            self.api.create_rate.await_args.kwargs["feedback"], "感谢惠顾，欢迎下次光临！"
        )



if __name__ == "__main__":
    unittest.main()
