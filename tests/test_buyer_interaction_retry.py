"""自动评价 / 自动求花的重试语义。

回归两个故障：
1. 订单暂时没有 REQUIRE_FLOWER 动作时也被记为「已求花」，之后动作开放了也
   不会再试 —— 表现为自动求花首轮之后一直是 0。
2. 评价/求花接口报错一次就被记为已处理，不再重试。
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from utils.xianyu_seller_api import SellerApiError
from XianyuAutoAsync import XianyuLive

ORDER = "3300000000000000001"


def _sold_item(actions=None, seller_rate_status=0):
    return {
        "commonData": {"orderId": ORDER, "sellerRateStatus": seller_rate_status},
        "rightVO": {"btnList": [{"tradeAction": a} for a in (actions or [])]},
    }


class BuyerInteractionRetryTests(unittest.TestCase):
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

    def test_flower_retried_once_action_becomes_available(self):
        self.items = [_sold_item(actions=[])]
        self.assertEqual(self._run(flower_on=True)["flowered"], 0)
        self.assertNotIn(ORDER, self.live._auto_flowered_orders)

        self.items = [_sold_item(actions=["REQUIRE_FLOWER"])]
        self.assertEqual(self._run(flower_on=True)["flowered"], 1)
        self.assertIn(ORDER, self.live._auto_flowered_orders)

        # 已求过的不再重复发
        self._run(flower_on=True)
        self.assertEqual(self.api.require_flower.await_count, 1)

    def test_failures_retry_up_to_limit(self):
        self.items = [_sold_item(actions=["REQUIRE_FLOWER"])]
        self.api.require_flower.side_effect = SellerApiError("mtop.x", ["FAIL"])
        self.api.create_rate.return_value = {"success": False, "fail_orders": ["x"]}

        for _ in range(XianyuLive.BUYER_INTERACTION_MAX_ATTEMPTS - 1):
            self._run(rate_on=True, flower_on=True)
            self.assertNotIn(ORDER, self.live._auto_flowered_orders)
            self.assertNotIn(ORDER, self.live._auto_rated_orders)

        self._run(rate_on=True, flower_on=True)
        self.assertIn(ORDER, self.live._auto_flowered_orders)
        self.assertIn(ORDER, self.live._auto_rated_orders)

        self._run(rate_on=True, flower_on=True)
        self.assertEqual(
            self.api.require_flower.await_count, XianyuLive.BUYER_INTERACTION_MAX_ATTEMPTS
        )
        self.assertEqual(
            self.api.create_rate.await_count, XianyuLive.BUYER_INTERACTION_MAX_ATTEMPTS
        )

    def test_already_rated_order_is_not_rated_again(self):
        self.items = [_sold_item(seller_rate_status=4)]
        self._run(rate_on=True)
        self.api.create_rate.assert_not_called()
        self.assertIn(ORDER, self.live._auto_rated_orders)


if __name__ == "__main__":
    unittest.main()
