# -*- coding: utf-8 -*-
"""auth_protection 单元测试：发码限流 + 登录失败追踪（mock 单调时钟推进）。"""

import unittest
from unittest import mock

from app.services.auth_protection import (
    EmailCodeSendLimiter,
    LoginFailureTracker,
)


class EmailCodeSendLimiterTests(unittest.TestCase):
    def test_cooldown_within_60s(self):
        limiter = EmailCodeSendLimiter()
        with mock.patch("app.services.auth_protection.time.monotonic", return_value=1000.0):
            self.assertIsNone(limiter.acquire("a@b.com"))
        # 59 秒后仍在冷却内
        with mock.patch("app.services.auth_protection.time.monotonic", return_value=1059.0):
            wait = limiter.acquire("a@b.com")
            self.assertIsNotNone(wait)
            self.assertGreater(wait, 0)

    def test_cooldown_expired_allows_resend(self):
        limiter = EmailCodeSendLimiter()
        with mock.patch("app.services.auth_protection.time.monotonic", return_value=1000.0):
            limiter.acquire("a@b.com")
        with mock.patch("app.services.auth_protection.time.monotonic", return_value=1061.0):
            self.assertIsNone(limiter.acquire("a@b.com"))

    def test_daily_limit(self):
        limiter = EmailCodeSendLimiter()
        base = 1000.0
        for i in range(10):
            with mock.patch(
                    "app.services.auth_protection.time.monotonic",
                    return_value=base + i * 120):
                self.assertIsNone(limiter.acquire("a@b.com"), f"第 {i + 1} 次应放行")
        # 第 11 次即使过了冷却也达日上限
        with mock.patch(
                "app.services.auth_protection.time.monotonic",
                return_value=base + 10 * 120):
            self.assertIsNotNone(limiter.acquire("a@b.com"))

    def test_different_emails_independent(self):
        limiter = EmailCodeSendLimiter()
        with mock.patch("app.services.auth_protection.time.monotonic", return_value=1000.0):
            limiter.acquire("a@b.com")
        with mock.patch("app.services.auth_protection.time.monotonic", return_value=1000.5):
            self.assertIsNone(limiter.acquire("c@d.com"))

    def test_email_key_normalized(self):
        limiter = EmailCodeSendLimiter()
        with mock.patch("app.services.auth_protection.time.monotonic", return_value=1000.0):
            limiter.acquire("A@B.com")
        with mock.patch("app.services.auth_protection.time.monotonic", return_value=1000.5):
            self.assertIsNotNone(limiter.acquire("a@b.com"))


class LoginFailureTrackerTests(unittest.TestCase):
    def test_threshold_triggers_captcha(self):
        tracker = LoginFailureTracker(threshold=3)
        key = "victim"
        self.assertFalse(tracker.requires_captcha(key))
        tracker.record_failure(key)
        tracker.record_failure(key)
        self.assertFalse(tracker.requires_captcha(key))
        tracker.record_failure(key)
        self.assertTrue(tracker.requires_captcha(key))

    def test_success_resets(self):
        tracker = LoginFailureTracker(threshold=3)
        key = "victim"
        for _ in range(3):
            tracker.record_failure(key)
        tracker.reset(key)
        self.assertFalse(tracker.requires_captcha(key))

    def test_decay_clears_old_failures(self):
        tracker = LoginFailureTracker(threshold=3, decay_seconds=900)
        key = "victim"
        with mock.patch("app.services.auth_protection.time.monotonic", return_value=1000.0):
            for _ in range(3):
                tracker.record_failure(key)
        # 15 分钟后衰减，不再要求验证码
        with mock.patch("app.services.auth_protection.time.monotonic", return_value=1901.0):
            self.assertFalse(tracker.requires_captcha(key))

    def test_key_normalized(self):
        tracker = LoginFailureTracker(threshold=1)
        tracker.record_failure("Admin")
        self.assertTrue(tracker.requires_captcha("admin"))


if __name__ == "__main__":
    unittest.main()
