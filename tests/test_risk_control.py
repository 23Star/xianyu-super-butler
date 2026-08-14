import asyncio
import time
import unittest

from utils import risk_control
from utils.risk_control import (
    AccountGuard,
    RiskControlBlocked,
    RiskControlRegistry,
    guarded_call,
    is_risk_control_error,
)
from app.reply_server import classify_verification_event


class RiskControlDetectionTests(unittest.TestCase):
    def test_verification_event_types_are_classified(self):
        self.assertEqual(
            classify_verification_event('slider_captcha action=captcha')[0],
            'slider',
        )
        self.assertEqual(classify_verification_event('需要人脸 face verify')[0], 'face')
        self.assertEqual(classify_verification_event('扫码 QR login')[0], 'qr')
        self.assertEqual(classify_verification_event('', blocked=True)[0], 'risk_control')
        self.assertEqual(classify_verification_event('')[0], 'none')

    def test_platform_risk_messages_are_detected(self):
        """这些是实测收到的风控响应，必须能识别出来。"""
        for message in (
            "RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试",
            "FAIL_SYS_USER_VALIDATE",
            "FAIL_SYS_FLOW_LIMIT::请求过于频繁",
        ):
            self.assertTrue(is_risk_control_error(message), message)

    def test_normal_errors_are_not_treated_as_risk_control(self):
        """令牌过期是正常轮换，误判成风控会让账号白白冷却。"""
        for message in (
            "SUCCESS::调用成功",
            "FAIL_SYS_TOKEN_EXPIRED::令牌过期",
            "FAIL_SYS_TOKEN_EXOIRED::令牌过期",
            "FAIL_BIZ_COMMON_PARAM_NULL::缺少必填参数",
            "",
            None,
        ):
            self.assertFalse(is_risk_control_error(message), repr(message))


class AccountGuardTests(unittest.TestCase):
    def test_cooldown_grows_with_consecutive_hits(self):
        """连续命中风控时冷却时间要递增，否则起不到退避作用。"""
        guard = AccountGuard("acc")

        first = guard.trip("RGV587_ERROR")
        second = guard.trip("RGV587_ERROR")
        third = guard.trip("RGV587_ERROR")

        self.assertLess(first, second)
        self.assertLess(second, third)
        self.assertEqual(guard.consecutive_hits, 3)

    def test_reset_clears_block(self):
        guard = AccountGuard("acc")
        guard.trip("RGV587_ERROR")
        self.assertTrue(guard.is_blocked)

        guard.reset()

        self.assertFalse(guard.is_blocked)
        self.assertEqual(guard.consecutive_hits, 0)

    def test_rate_limit_paces_requests(self):
        """令牌用尽后必须等待，不能无限放行。"""
        guard = AccountGuard("acc", rate_per_minute=60)  # 每秒 1 个
        guard._tokens = 1

        async def run():
            start = time.monotonic()
            await guard.acquire()  # 用掉仅有的令牌
            await guard.acquire()  # 需要等待补充
            return time.monotonic() - start

        elapsed = asyncio.run(run())
        self.assertGreaterEqual(elapsed, 0.8)


class GuardedCallTests(unittest.TestCase):
    def setUp(self):
        # 用独立注册表，避免污染全局状态
        self._original = risk_control.registry
        risk_control.registry = RiskControlRegistry(rate_per_minute=600)

    def tearDown(self):
        risk_control.registry = self._original

    def test_risk_control_error_trips_breaker_and_blocks_next_call(self):
        async def failing():
            raise RuntimeError("RGV587_ERROR::被挤爆啦")

        async def run():
            with self.assertRaises(RuntimeError):
                await guarded_call("acc", failing)
            # 熔断后第二次调用应被直接拦截，而不是再打一次接口
            with self.assertRaises(RiskControlBlocked):
                await guarded_call("acc", failing)

        asyncio.run(run())

    def test_normal_error_does_not_trip_breaker(self):
        async def failing():
            raise RuntimeError("FAIL_BIZ_COMMON_PARAM_NULL")

        async def run():
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    await guarded_call("acc2", failing)
            self.assertFalse(risk_control.registry.get("acc2").is_blocked)

        asyncio.run(run())

    def test_success_resets_previous_hits(self):
        async def ok():
            return "done"

        async def run():
            guard = risk_control.registry.get("acc3")
            guard.consecutive_hits = 2

            result = await guarded_call("acc3", ok)

            self.assertEqual(result, "done")
            self.assertEqual(guard.consecutive_hits, 0)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
