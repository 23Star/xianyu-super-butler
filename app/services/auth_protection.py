# -*- coding: utf-8 -*-
"""认证环节的进程内防刷状态。

两个组件都只持有短周期状态（分钟级冷却 / 15 分钟衰减），
进程重启清零可接受 —— 与 SESSION_TOKENS 一致的取舍。
持久化到数据库反而会给攻击者"重启即重置"之外的额外复杂度。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Dict, Optional


class EmailCodeSendLimiter:
    """邮箱验证码发送限流：同邮箱 60s 冷却 + 24h 滑动窗口日上限。"""

    def __init__(
        self,
        cooldown_seconds: int = 60,
        daily_limit: int = 10,
        window_seconds: int = 86400,
    ) -> None:
        self.cooldown_seconds = max(1, int(cooldown_seconds))
        self.daily_limit = max(1, int(daily_limit))
        self.window_seconds = max(1, int(window_seconds))
        self._sends: Dict[str, deque] = defaultdict(deque)

    def acquire(self, email: str) -> Optional[int]:
        """尝试占用一次发送名额。

        返回 None 表示放行；否则返回建议的等待秒数（冷却剩余或窗口到期）。
        """
        now = time.monotonic()
        key = (email or "").strip().lower()
        sends = self._sends[key]
        while sends and now - sends[0] >= self.window_seconds:
            sends.popleft()
        if sends and now - sends[-1] < self.cooldown_seconds:
            return int(self.cooldown_seconds - (now - sends[-1])) + 1
        if len(sends) >= self.daily_limit:
            return int(self.window_seconds - (now - sends[0])) + 1
        sends.append(now)
        # 内存上限 = 24h 内出现过的独立邮箱数（正常场景可忽略），
        # 窗口外记录在该邮箱下次 acquire 时惰性清理
        return None


class LoginFailureTracker:
    """登录失败计数：连续失败达阈值后要求图形验证码。

    15 分钟内无新失败自动衰减归零，成功登录立即清零。
    """

    def __init__(self, threshold: int = 3, decay_seconds: int = 900) -> None:
        self.threshold = max(1, int(threshold))
        self.decay_seconds = max(1, int(decay_seconds))
        self._failures: Dict[str, deque] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque:
        failures = self._failures[key]
        while failures and now - failures[0] >= self.decay_seconds:
            failures.popleft()
        return failures

    def requires_captcha(self, key: str) -> bool:
        """该账号是否已连续失败达到阈值、需要先过图形验证码。"""
        failures = self._prune((key or "").strip().lower(), time.monotonic())
        return len(failures) >= self.threshold

    def record_failure(self, key: str) -> None:
        failures = self._failures[(key or "").strip().lower()]
        failures.append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop((key or "").strip().lower(), None)


# 进程级共享实例：所有认证端点共用同一配额池
email_code_send_limiter = EmailCodeSendLimiter()
login_failure_tracker = LoginFailureTracker()
