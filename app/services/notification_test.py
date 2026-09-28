"""账号通知规则的测试发送服务。

向一条规则绑定的渠道发送真实测试消息，用于排查通知链路连通性。
刻意不做"发送前必须启用"的校验：停用的规则/渠道也要能测，
否则用户改完配置只能先启用才能验证，反而更容易漏报。
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from typing import Any, Callable, Dict, Optional

from app.services.notification_channels import NotificationChannelConfigError
from app.services.notification_sender import (
    NotificationNetworkError,
    NotificationProviderRejected,
    NotificationSendTimeout,
)


class NotificationTestError(Exception):
    """测试发送失败，code 对前端稳定，status_code 对 HTTP 状态。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 502,
        retry_after: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after

    def detail(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message}


class NotificationTestRateLimiter:
    """按 (rule_id, user_id) 维度的滑动窗口限流，防止测试端点被刷。"""

    def __init__(self, limit: int = 10, window_seconds: int = 60) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._hits: Dict[tuple, deque] = defaultdict(deque)

    def acquire(self, key: tuple) -> Optional[int]:
        """尝试占用一个名额；被限流时返回建议的重试等待秒数。"""
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window_seconds:
            hits.popleft()
        if len(hits) >= self.limit:
            return self.window_seconds
        hits.append(now)
        return None


def build_test_message(cookie_id: str) -> str:
    """构造测试消息模板，{request_id} 由服务层填充以便追踪。"""
    return (
        "【闲鱼超级管家】通知测试\n"
        f"账号：{cookie_id}\n"
        "追踪 ID：{request_id}\n"
        "收到本消息说明该渠道通知链路畅通。"
    )


# 进程级共享限流器：测试端点对所有用户共用同一配额池
notification_test_rate_limiter = NotificationTestRateLimiter(limit=10, window_seconds=60)


class NotificationTestService:
    """发送通知测试消息并输出脱敏审计日志。"""

    def __init__(
        self,
        db: Any,
        sender: Any = None,
        limiter: Optional[NotificationTestRateLimiter] = None,
        log_fn: Optional[Callable[..., None]] = None,
    ) -> None:
        self.db = db
        self.sender = sender
        self.limiter = limiter

        if log_fn is not None:
            self._log = log_fn
        else:
            from loguru import logger

            self._log = lambda level, message, user: getattr(logger, level)(message)

    def _log_safe(self, level: str, message: str, operator: Optional[dict]) -> None:
        """审计日志只输出结构性字段，绝不携带渠道配置（内含 webhook token 等敏感值）。"""
        try:
            self._log(level, message, operator)
        except TypeError:
            # loguru 风格的 log_fn 只接受 (level, message)
            self._log(level, message)

    async def send_rule_test(
        self,
        rule_id: int,
        user_id: int,
        operator: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        target = self.db.get_notification_test_target(rule_id, user_id)
        if not target:
            raise NotificationTestError(
                "notification_rule_not_found",
                "通知规则不存在或无权限",
                status_code=404,
            )

        if self.limiter is not None:
            retry_after = self.limiter.acquire((int(rule_id), int(user_id)))
            if retry_after is not None:
                raise NotificationTestError(
                    "notification_rate_limited",
                    "测试发送过于频繁，请稍后再试",
                    status_code=429,
                    retry_after=retry_after,
                )

        request_id = secrets.token_hex(6)
        message = build_test_message(target["cookie_id"]).format(request_id=request_id)

        self._log_safe(
            "info",
            f"source=notification_test rule_id={rule_id} request_id={request_id} result=started",
            operator,
        )

        try:
            if self.sender is None:
                raise NotificationTestError(
                    "notification_send_failed",
                    "通知发送器未初始化",
                    status_code=503,
                )
            receipt = await self.sender.send(
                target["channel_type"],
                target["channel_config"],
                message,
            )
            if not receipt:
                raise NotificationTestError(
                    "notification_send_failed",
                    "通知测试发送失败，请稍后重试",
                    status_code=502,
                )
        except NotificationChannelConfigError:
            raise NotificationTestError(
                "notification_config_invalid",
                "通知渠道配置不完整，请先补全再测试",
                status_code=400,
            )
        except NotificationSendTimeout:
            raise NotificationTestError(
                "notification_send_timeout",
                "通知渠道响应超时，请检查网络或稍后重试",
                status_code=504,
            )
        except NotificationProviderRejected as exc:
            status = getattr(exc, "status_code", None) or 502
            raise NotificationTestError(
                "notification_provider_rejected",
                "通知渠道拒绝了本次请求",
                status_code=status,
            )
        except NotificationNetworkError:
            raise NotificationTestError(
                "notification_send_failed",
                "通知渠道网络异常，请稍后重试",
                status_code=502,
            )
        except NotificationTestError:
            raise
        except Exception:
            # 未知异常的消息可能包含敏感值，不回显给前端，只给稳定文案
            raise NotificationTestError(
                "notification_send_failed",
                "通知测试发送失败，请稍后重试",
                status_code=502,
            )

        self._log_safe(
            "info",
            f"source=notification_test rule_id={rule_id} request_id={request_id} "
            f"channel_id={target['channel_id']} result=success",
            operator,
        )

        return {
            "success": True,
            "request_id": request_id,
            "channel": {
                "id": target["channel_id"],
                "name": target["channel_name"],
                "type": target["channel_type"],
            },
            "rule_enabled": bool(target.get("enabled")),
            "channel_enabled": bool(target.get("channel_enabled")),
        }
