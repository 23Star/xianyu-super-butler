"""物流报价第五步的系统日志与外部通知发布器。

图节点保持同步，发布器因此提供同步入口，并在需要时安全地等待账号实例
的异步 ``send_system_notification``。通知失败只记录自身错误，不改变报价
决策结果。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from loguru import logger

from utils.log_sanitizer import redact_sensitive_text

LOGISTICS_QUOTE_EVENT_TYPE = "logistics_quote"
_DEDUP_TTL_SECONDS = 300
_DEDUP_LOCK = threading.Lock()
_PUBLISHED_KEYS: dict[str, float] = {}

# 这些原因表示计费链路本身失败；其余人工动作统一归入转人工事件。
_FAILURE_REASONS = {
    "workflow_failed",
    "render_failed",
    "model_failed",
    "model_not_configured",
    "account_not_found",
    "no_rate_book",
    "send_failed",
}
_MANUAL_REASONS = {
    "route_not_found",
    "template_unresolved",
    "ambiguous_city",
    "missing_city",
    "manual_required",
}
_REASON_CODES = {
    "workflow_failed": "WORKFLOW_FAILED",
    "render_failed": "RENDER_FAILED",
    "model_failed": "MODEL_FAILED",
    "model_not_configured": "MODEL_NOT_CONFIGURED",
    "account_not_found": "ACCOUNT_NOT_FOUND",
    "no_rate_book": "RATE_BOOK_MISSING",
    "route_not_found": "ROUTE_NOT_FOUND",
    "template_unresolved": "TEMPLATE_UNRESOLVED",
    "ambiguous_city": "AMBIGUOUS_CITY",
    "missing_city": "MISSING_CITY",
    "send_failed": "SEND_FAILED",
    "manual_required": "MANUAL_REQUIRED",
}


def clear_notification_dedup() -> None:
    """清空进程内幂等缓存（测试或服务重载时使用）。"""
    with _DEDUP_LOCK:
        _PUBLISHED_KEYS.clear()


def quote_request_id(
    account_id: str = "",
    message_id: str = "",
    chat_id: str = "",
    item_id: str = "",
    thread_id: str = "",
) -> str:
    """为一次报价请求生成不包含原始业务标识的稳定键。"""
    raw = "\x1f".join(
        str(value or "")
        for value in (account_id, message_id, chat_id, item_id, thread_id)
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"lq-{digest}"


def build_logistics_quote_event(
    *,
    account_id: str,
    message_id: str = "",
    chat_id: str = "",
    item_id: str = "",
    thread_id: str = "",
    decision_action: str = "",
    reason: str = "",
    reason_code: str | None = None,
    retryable: bool | None = None,
    required_action: str = "",
    quote_request_id_value: str = "",
    mode: str = "",
    created_at: str | None = None,
) -> dict[str, Any] | None:
    """把 Agent 决策转换为可发布事件；普通成功/忽略结果返回 ``None``。"""
    reason_key = str(reason or "").strip().lower()
    if reason_key in _FAILURE_REASONS:
        status, event_action = "failed", "quote_failed"
    elif reason_key in _MANUAL_REASONS or decision_action == "manual":
        status, event_action = "manual_required", "transfer_manual"
    else:
        return None

    if retryable is None:
        retryable = reason_key in {"workflow_failed", "model_failed", "send_failed"}
    request_id = str(quote_request_id_value or "").strip()[:96]
    if not request_id:
        request_id = quote_request_id(account_id, message_id, chat_id, item_id, thread_id)
    return {
        "event": LOGISTICS_QUOTE_EVENT_TYPE,
        "stage": 5,
        "status": status,
        "action": event_action,
        "decision_action": str(decision_action or ""),
        "account_id": str(account_id or ""),
        "message_id": str(message_id or ""),
        "chat_id": str(chat_id or ""),
        "item_id": str(item_id or ""),
        "thread_id": str(thread_id or ""),
        "quote_request_id": request_id,
        "reason_code": str(reason_code or _REASON_CODES.get(reason_key, reason_key.upper() or "UNKNOWN")),
        "reason": str(reason or "unknown"),
        "retryable": bool(retryable),
        "required_action": required_action or _required_action(reason_key),
        "mode": str(mode or ""),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }


def format_logistics_quote_message(event: Mapping[str, Any]) -> str:
    """格式化脱敏通知正文，避免写入地址、手机号或凭据。"""
    status = str(event.get("status") or "")
    account = _mask_identifier(event.get("account_id"))
    session_value = event.get("chat_id") or event.get("thread_id") or event.get("message_id")
    session = _mask_identifier(session_value)
    reason = _safe_text(event.get("reason") or event.get("reason_code") or "unknown")
    code = _safe_text(event.get("reason_code") or "UNKNOWN")
    request_id = _safe_text(event.get("quote_request_id") or "unknown")
    if status == "failed":
        return (
            "source=logistics_quote 【物流报价失败】"
            f"账号：{account} 会话：{session} 阶段：第5步 "
            f"原因：{reason} 错误码：{code} "
            f"可重试：{'是' if event.get('retryable') else '否'} 请求：{request_id}"
        )
    return (
        "source=logistics_quote 【物流报价转人工】"
        f"账号：{account} 会话：{session} 阶段：第5步 "
        f"原因：{reason} 待处理：{_safe_text(event.get('required_action') or '人工复核报价')} "
        f"请求：{request_id}"
    )


def publish_logistics_quote_event(
    event: Mapping[str, Any] | None,
    *,
    db: Any = None,
    log_fn: Callable[[str, str, Mapping[str, Any] | None], Any] | None = None,
    account_instance: Any = None,
    account_instance_resolver: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """发布一次物流报价异常事件并返回发布结果。

    ``log_fn``、``account_instance`` 和解析器均可注入，避免服务层导入应用
    组装模块造成循环依赖，也让通知路径可以在没有在线账号时继续落日志。
    """
    if not event or event.get("event") != LOGISTICS_QUOTE_EVENT_TYPE:
        return {"published": False, "reason": "not_logistics_quote_event"}
    if event.get("status") not in {"failed", "manual_required"}:
        return {"published": False, "reason": "not_actionable"}

    request_id = str(event.get("quote_request_id") or "")
    action = str(event.get("action") or "")
    dedup_key = f"{request_id}:{action}"
    if _already_published(dedup_key):
        return {"published": False, "deduplicated": True, "quote_request_id": request_id}

    message = format_logistics_quote_message(event)
    level = "error" if event.get("status") == "failed" else "warning"
    user_info = _resolve_user_info(db, str(event.get("account_id") or ""))
    sink = log_fn or log_with_user
    try:
        sink(level, message, user_info)
    except Exception as exc:  # noqa: BLE001 - 日志故障也不能阻断报价
        logger.error(f"source=logistics_quote 系统日志写入失败：{_safe_text(exc)}")

    decision_action = str(event.get("decision_action") or "")
    if decision_action == "draft":
        return {
            "published": True,
            "external_sent": False,
            "reason": "draft",
            "quote_request_id": request_id,
        }

    instance = account_instance
    if instance is None:
        resolver = account_instance_resolver or resolve_account_instance
        try:
            instance = resolver(str(event.get("account_id") or ""))
        except Exception as exc:  # noqa: BLE001 - 账号解析失败只记日志
            _log_notification_error(
                f"source=logistics_quote 无法获取账号实例：{_safe_text(exc)}",
                user_info,
                sink,
            )
            return {"published": True, "external_sent": False, "reason": "instance_error"}

    if instance is None:
        _log_notification_warning("source=logistics_quote 未找到账号实例，跳过外部通知", user_info, sink)
        return {"published": True, "external_sent": False, "reason": "instance_missing"}

    try:
        result = instance.send_system_notification(
            message, event_type=LOGISTICS_QUOTE_EVENT_TYPE
        )
        sent = _run_awaitable(result)
        sent_count = int(sent or 0)
        if sent_count == 0:
            _log_notification_warning(
                "source=logistics_quote 未配置可用通知渠道，未发送外部通知",
                user_info,
                sink,
            )
        return {
            "published": True,
            "external_sent": sent_count > 0,
            "sent_channels": sent_count,
            "quote_request_id": request_id,
        }
    except Exception as exc:  # noqa: BLE001 - 通知失败不得覆盖报价结果
        _log_notification_error(
            f"source=logistics_quote 外部通知发送失败：{_safe_text(exc)}",
            user_info,
            sink,
        )
        return {
            "published": True,
            "external_sent": False,
            "reason": "notification_error",
            "quote_request_id": request_id,
        }


def log_with_user(level: str, message: str, user_info: Mapping[str, Any] | None = None) -> None:
    """延迟解析应用日志出口，避免 ``reply_server`` 与 Agent 循环导入。"""
    try:
        from app.reply_server import log_with_user as app_log_with_user
    except Exception:  # pragma: no cover - 独立脚本/单元测试环境
        getattr(logger, level.lower(), logger.info)(message)
    else:
        app_log_with_user(level, message, dict(user_info) if user_info else None)


def resolve_account_instance(account_id: str) -> Any:
    """按账号 ID 查找运行中的闲鱼实例。"""
    if not account_id:
        return None
    try:
        from XianyuAutoAsync import XianyuLive

        return XianyuLive.get_instance(account_id)
    except Exception:
        return None


def _already_published(key: str) -> bool:
    now = time.monotonic()
    with _DEDUP_LOCK:
        expired = [item for item, timestamp in _PUBLISHED_KEYS.items() if now - timestamp >= _DEDUP_TTL_SECONDS]
        for item in expired:
            _PUBLISHED_KEYS.pop(item, None)
        if key in _PUBLISHED_KEYS:
            return True
        _PUBLISHED_KEYS[key] = now
        return False


def _resolve_user_info(db: Any, account_id: str) -> dict[str, Any] | None:
    if db is None or not account_id:
        return None
    try:
        user_id = db.get_cookie_owner_user(account_id)
        if user_id is None:
            return None
        user = db.get_user_by_id(user_id) if hasattr(db, "get_user_by_id") else None
        return {
            "user_id": user_id,
            "username": (user or {}).get("username", "system"),
        }
    except Exception:
        return None


def _required_action(reason: str) -> str:
    return {
        "route_not_found": "确认线路或报价表",
        "template_unresolved": "修复回复模板",
        "ambiguous_city": "确认收货城市",
        "missing_city": "确认收货城市",
    }.get(reason, "人工复核报价")


def _mask_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    return f"id:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:10]}"


def _safe_text(value: Any, limit: int = 180) -> str:
    text = redact_sensitive_text(value).replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"(?<!\d)1\d{10}(?!\d)", "<已脱敏手机号>", text)
    text = re.sub(r"https?://\S+", "<已脱敏链接>", text)
    # 只保留原因摘要，避免把完整省市街道或买家原文带入通知。
    text = re.sub(
        r"[\u4e00-\u9fff]{2,}(?:省|市|区|县|镇|乡|路|街|号)[\u4e00-\u9fff0-9\-]*",
        "<已脱敏地址>",
        text,
    )
    return text[:limit] or "unknown"


def _run_awaitable(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    result: list[Any] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(value))
        except BaseException as exc:  # pragma: no cover - defensive bridge
            error.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0] if result else None


def _log_notification_warning(
    message: str,
    user_info: Mapping[str, Any] | None,
    sink: Callable[[str, str, Mapping[str, Any] | None], Any] | None = None,
) -> None:
    try:
        (sink or log_with_user)("warning", message, user_info)
    except Exception as exc:  # pragma: no cover - logging fallback
        logger.warning(f"{message}；日志失败：{_safe_text(exc)}")


def _log_notification_error(
    message: str,
    user_info: Mapping[str, Any] | None,
    sink: Callable[[str, str, Mapping[str, Any] | None], Any] | None = None,
) -> None:
    try:
        (sink or log_with_user)("error", message, user_info)
    except Exception as exc:  # pragma: no cover - logging fallback
        logger.error(f"{message}；日志失败：{_safe_text(exc)}")


__all__ = [
    "LOGISTICS_QUOTE_EVENT_TYPE",
    "build_logistics_quote_event",
    "clear_notification_dedup",
    "format_logistics_quote_message",
    "publish_logistics_quote_event",
    "quote_request_id",
    "resolve_account_instance",
]
