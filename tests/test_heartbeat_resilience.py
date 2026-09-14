"""心跳与重连的健壮性回归。

对照上游原始项目（zhinianboke/xianyu-auto-reply）复核后补的三处：

1. **重连退避叠加抖动。** 纯确定性公式下，多账号在同一原因（闲鱼侧抖动）
   掉线后会算出同一个延迟，退避结束时一起回来，把这批连接再打掉一次 ——
   即"重连风暴"。抖动让它们自然错开。
2. **`ws.closed` 必须安全读取。** 连接对象半初始化或已回收时读属性会抛
   AttributeError，心跳循环把它当成"发送失败"累计，连续 3 次就停下，
   把一条其实还活着的连接判成断开。
3. **连接必须带库级 PING。** 应用层心跳只证明"我们还能往对端写"；TCP 假活
   （对端已不处理但我们还没收到 FIN）时，只有库级 PING/PONG 能发现连接已死。
"""

import unittest
from unittest import mock

from XianyuAutoAsync import XianyuLive


def make_instance(failures: int = 1):
    """构造一个只带退避计算所需字段的实例，避开真实网络与浏览器。"""
    instance = XianyuLive.__new__(XianyuLive)
    instance.cookie_id = "acc"
    instance.connection_failures = failures
    return instance


class RetryDelayJitterTests(unittest.TestCase):
    def test_normal_disconnect_delay_is_bounded(self):
        instance = make_instance(failures=1)
        delay = instance._calculate_retry_delay("no close frame received or sent")

        # 基础值 min(3*1, 15) = 3，叠加最多 30% 抖动
        self.assertGreaterEqual(delay, 3)
        self.assertLessEqual(delay, 3 * 1.3 + 0.05)

    def test_network_timeout_has_longer_base(self):
        short = make_instance(failures=3)
        with mock.patch("XianyuAutoAsync.random.uniform", return_value=0):
            ws_delay = short._calculate_retry_delay("no close frame received or sent")
            net_delay = short._calculate_retry_delay("Connection refused")

        self.assertEqual(ws_delay, 9)     # min(3*3, 15)
        self.assertEqual(net_delay, 30)   # min(10*3, 60)

    def test_risk_control_backoff_is_exponential(self):
        with mock.patch("XianyuAutoAsync.random.uniform", return_value=0):
            first = make_instance(failures=1)._calculate_retry_delay("RGV587_ERROR")
            third = make_instance(failures=3)._calculate_retry_delay("RGV587_ERROR")

        self.assertEqual(first, 60)
        self.assertEqual(third, 240)  # 60 * 2^2

    def test_risk_control_backoff_is_capped(self):
        with mock.patch("XianyuAutoAsync.random.uniform", return_value=0):
            delay = make_instance(failures=20)._calculate_retry_delay("FAIL_SYS_USER_VALIDATE")

        self.assertEqual(delay, 1800)  # 封顶 30 分钟

    def test_jitter_is_actually_applied(self):
        """抖动必须真的生效 —— 否则多账号仍会同时重连。"""
        instance = make_instance(failures=3)
        with mock.patch("XianyuAutoAsync.random.uniform", return_value=6.0) as mocked:
            delay = instance._calculate_retry_delay("no close frame received or sent")

        mocked.assert_called_once()
        self.assertEqual(delay, 15)  # 基础 9 + 抖动 6

    def test_jitter_upper_bound_is_thirty_percent(self):
        instance = make_instance(failures=3)
        captured = {}

        def fake_uniform(low, high):
            captured["low"], captured["high"] = low, high
            return 0

        with mock.patch("XianyuAutoAsync.random.uniform", side_effect=fake_uniform):
            instance._calculate_retry_delay("no close frame received or sent")

        self.assertEqual(captured["low"], 0)
        self.assertAlmostEqual(captured["high"], 9 * 0.3, places=5)

    def test_returns_float_for_sub_second_jitter(self):
        # 返回值参与 asyncio.sleep，整数化会把小的抖动抹掉
        delay = make_instance(failures=1)._calculate_retry_delay("no close frame received or sent")

        self.assertIsInstance(delay, float)


class IsWsClosedTests(unittest.TestCase):
    def test_none_is_closed(self):
        self.assertTrue(XianyuLive.is_ws_closed(None))

    def test_open_socket_is_not_closed(self):
        class Open:
            closed = False

        self.assertFalse(XianyuLive.is_ws_closed(Open()))

    def test_closed_socket_is_closed(self):
        class Shut:
            closed = True

        self.assertTrue(XianyuLive.is_ws_closed(Shut()))

    def test_attribute_error_is_treated_as_closed(self):
        """半初始化对象读 closed 会抛异常，必须兜住而不是向外冒。"""

        class Broken:
            @property
            def closed(self):
                raise AttributeError("no attribute 'closed'")

        self.assertTrue(XianyuLive.is_ws_closed(Broken()))

    def test_never_raises(self):
        class Exploding:
            @property
            def closed(self):
                raise RuntimeError("boom")

        # 任何异常都不能冒出去：调用方在心跳循环里，抛出去等于心跳直接崩
        self.assertTrue(XianyuLive.is_ws_closed(Exploding()))

    def test_heartbeat_uses_safe_check(self):
        """心跳发送与循环都必须走安全判定，不能再直接读 ws.closed。"""
        import inspect

        source = inspect.getsource(XianyuLive.send_heartbeat)
        self.assertIn("is_ws_closed", source)

        source = inspect.getsource(XianyuLive.heartbeat_loop)
        self.assertIn("is_ws_closed", source)
        self.assertNotIn("ws.closed", source)


class WebsocketConnectOptionsTests(unittest.TestCase):
    def test_connect_sets_ping_and_open_timeout(self):
        """库级 PING 与握手超时必须显式传入，否则半死连接永远发现不了。"""
        import inspect

        source = inspect.getsource(XianyuLive._create_websocket_connection)
        self.assertIn("ping_interval", source)
        self.assertIn("ping_timeout", source)
        self.assertIn("open_timeout", source)


if __name__ == "__main__":
    unittest.main()
