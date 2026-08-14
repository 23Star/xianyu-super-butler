"""闲鱼平台风控的熔断与限流。

实测教训：账号被平台判定为异常后（``RGV587_ERROR::哎哟喂,被挤爆啦``），
如果继续按原节奏重试，风控不会自行解除 —— 反而因为持续请求一直延长。
一次事故里重试风暴达到每分钟 670~970 次请求，持续两小时未恢复。

这里提供两层保护：

- **熔断**：命中风控特征后，该账号进入冷却期，期间拒绝一切主动请求，
  冷却时间按连续命中次数指数增长。
- **限流**：令牌桶控制每个账号的请求速率，多账号并发时也不会突发。

两者都是进程内状态，重启后重置 —— 这是可接受的，因为重启本身会间隔较久。
"""

import asyncio
import time
from typing import Dict

from loguru import logger


# 平台风控与限流的特征串
RISK_CONTROL_MARKERS = (
    "RGV587_ERROR",
    "FAIL_SYS_USER_VALIDATE",
    "哎哟喂",
    "被挤爆",
    "FAIL_SYS_FLOW_LIMIT",
    "请稍后重试",
    "SM::",
)

# 熔断的冷却时间阶梯（秒）：连续命中越多，等得越久
COOLDOWN_STEPS = (300, 900, 1800, 3600, 7200)


def is_risk_control_error(message) -> bool:
    """判断一段错误文本是否来自平台风控或限流。"""
    text = str(message or "")
    return any(marker in text for marker in RISK_CONTROL_MARKERS)


class AccountGuard:
    """单个账号的熔断状态与限流令牌桶。"""

    def __init__(self, cookie_id: str, rate_per_minute: int = 30):
        self.cookie_id = cookie_id
        self.rate_per_minute = max(1, rate_per_minute)

        # 熔断
        self.blocked_until = 0.0
        self.consecutive_hits = 0
        self.last_hit_reason = ""

        # 令牌桶：容量等于每分钟配额，按秒匀速补充
        self._tokens = float(self.rate_per_minute)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    # ---------------- 熔断 ----------------

    @property
    def is_blocked(self) -> bool:
        return time.monotonic() < self.blocked_until

    @property
    def remaining_seconds(self) -> int:
        return max(0, int(self.blocked_until - time.monotonic()))

    def trip(self, reason: str = "") -> int:
        """命中风控，进入冷却。返回本次冷却秒数。"""
        step = min(self.consecutive_hits, len(COOLDOWN_STEPS) - 1)
        cooldown = COOLDOWN_STEPS[step]
        self.consecutive_hits += 1
        self.blocked_until = time.monotonic() + cooldown
        self.last_hit_reason = str(reason or "")[:200]
        logger.warning(
            f"【{self.cookie_id}】命中平台风控，暂停主动请求 {cooldown} 秒"
            f"（连续第 {self.consecutive_hits} 次）: {self.last_hit_reason[:80]}"
        )
        return cooldown

    def reset(self) -> None:
        """请求成功，解除熔断计数。"""
        if self.consecutive_hits or self.blocked_until:
            logger.info(f"【{self.cookie_id}】风控状态已解除")
        self.consecutive_hits = 0
        self.blocked_until = 0.0
        self.last_hit_reason = ""

    # ---------------- 限流 ----------------

    async def acquire(self) -> None:
        """取一个令牌，不足时等待。"""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._last_refill = now
                self._tokens = min(
                    float(self.rate_per_minute),
                    self._tokens + elapsed * (self.rate_per_minute / 60.0),
                )
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                # 补足一个令牌所需的时间
                await asyncio.sleep((1 - self._tokens) * (60.0 / self.rate_per_minute))

    def snapshot(self) -> Dict[str, object]:
        return {
            "cookie_id": self.cookie_id,
            "blocked": self.is_blocked,
            "remaining_seconds": self.remaining_seconds,
            "consecutive_hits": self.consecutive_hits,
            "reason": self.last_hit_reason,
        }


class RiskControlRegistry:
    """按账号维护 :class:`AccountGuard`。"""

    def __init__(self, rate_per_minute: int = 30):
        self.rate_per_minute = rate_per_minute
        self._guards: Dict[str, AccountGuard] = {}

    def get(self, cookie_id: str) -> AccountGuard:
        guard = self._guards.get(cookie_id)
        if guard is None:
            guard = AccountGuard(cookie_id, self.rate_per_minute)
            self._guards[cookie_id] = guard
        return guard

    def snapshot(self) -> Dict[str, Dict[str, object]]:
        return {cid: guard.snapshot() for cid, guard in self._guards.items()}


class RiskControlBlocked(Exception):
    """账号处于风控冷却期，调用方应跳过本次操作。"""

    def __init__(self, cookie_id: str, remaining: int, reason: str = ""):
        self.cookie_id = cookie_id
        self.remaining = remaining
        self.reason = reason
        super().__init__(
            f"账号 {cookie_id} 处于风控冷却期，还需 {remaining} 秒"
            + (f"（{reason}）" if reason else "")
        )


# 全局注册表：默认每账号每分钟 30 次主动请求
registry = RiskControlRegistry(rate_per_minute=30)


async def guarded_call(cookie_id: str, coro_factory):
    """在熔断和限流保护下执行一次接口调用。

    Args:
        coro_factory: 无参可调用，返回待执行的协程。用工厂而不是协程对象，
            是为了在熔断时不创建未 await 的协程。

    Raises:
        RiskControlBlocked: 账号处于冷却期。
    """
    guard = registry.get(cookie_id)
    if guard.is_blocked:
        raise RiskControlBlocked(
            cookie_id, guard.remaining_seconds, guard.last_hit_reason
        )

    await guard.acquire()
    try:
        result = await coro_factory()
    except Exception as exc:
        if is_risk_control_error(exc):
            guard.trip(str(exc))
        raise
    guard.reset()
    return result
