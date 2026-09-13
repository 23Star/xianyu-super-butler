"""通知事件类型注册表。

集中定义可订阅的通知事件、优先级以及内部通知类型到事件类型的映射，
供发送端按账号通知规则过滤和前端勾选共用。
"""

import json
from typing import Any, Dict, List, Optional

PRIORITY_ORDER = ("critical", "warning", "info")

PRIORITY_LABELS = {
    "critical": "关键",
    "warning": "重要",
    "info": "一般",
}

DEFAULT_EVENT_TYPE = "cookie_invalid"

EVENT_DEFINITIONS: List[Dict[str, str]] = [
    {
        "id": "captcha_manual",
        "label": "人工验证提醒",
        "priority": "critical",
        "description": "滑块、人脸或扫码验证需要人工处理",
    },
    {
        "id": "cookie_invalid",
        "label": "Token/Cookie 异常",
        "priority": "critical",
        "description": "Token 刷新失败、Cookie 失效或更新失败",
    },
    {
        "id": "delivery_failed",
        "label": "自动发货失败",
        "priority": "critical",
        "description": "未找到发货规则、发货异常或未完整完成",
    },
    {
        "id": "delivery_timeout",
        "label": "发货超时告警",
        "priority": "critical",
        "description": "待发货订单即将超时或已经超时",
    },
    {
        "id": "login_failed",
        "label": "登录失败",
        "priority": "critical",
        "description": "账号密码错误导致登录失败",
    },
    {
        "id": "delivery_confirm_failed",
        "label": "平台确认发货失败",
        "priority": "warning",
        "description": "卡券已发送，但闲鱼平台确认发货失败需要手动处理",
    },
    {
        "id": "instance_restart_failed",
        "label": "实例重启失败",
        "priority": "warning",
        "description": "Cookie 更新后实例重启失败",
    },
    {
        "id": "delivery_success",
        "label": "自动发货成功",
        "priority": "info",
        "description": "卡券发送成功，含多数量订单和仅发卡券场景",
    },
    {
        "id": "login_success",
        "label": "登录/验证成功",
        "priority": "info",
        "description": "密码登录成功、滑块验证成功等",
    },
    {
        "id": "buyer_message",
        "label": "买家消息",
        "priority": "info",
        "description": "收到买家私聊消息",
    },
]

EVENT_IDS = [item["id"] for item in EVENT_DEFINITIONS]

TOKEN_NOTIFICATION_EVENT_MAP = {
    "token_refresh": "cookie_invalid",
    "token_refresh_exception": "cookie_invalid",
    "token_scheduled_refresh_failed": "cookie_invalid",
    "token_init_failed": "cookie_invalid",
    "cookie_validation_failed": "cookie_invalid",
    "cookie_update_failed": "cookie_invalid",
    "db_update_failed": "cookie_invalid",
    "cookie_id_missing": "cookie_invalid",
    "no_credentials": "cookie_invalid",
    "captcha_max_retries_exceeded": "captcha_manual",
    "captcha_manual_required": "captcha_manual",
    "captcha_verification_failed": "captcha_manual",
    "captcha_dependency_missing": "captcha_manual",
    "captcha_execution_error": "captcha_manual",
    "face_verification": "captcha_manual",
    "captcha_success_db_update_failed": "cookie_invalid",
    "captcha_success_auto_update": "login_success",
    "password_login_success": "login_success",
    "instance_restart_failed": "instance_restart_failed",
}


def get_event_definitions() -> List[Dict[str, str]]:
    return [dict(item) for item in EVENT_DEFINITIONS]


def get_priority_definitions() -> List[Dict[str, str]]:
    return [
        {"id": priority, "label": PRIORITY_LABELS[priority]}
        for priority in PRIORITY_ORDER
    ]


def resolve_event_type(notification_type: str) -> str:
    """把 Token/Cookie 类通知的内部类型映射为可订阅事件类型。"""
    key = (notification_type or "").strip()
    return TOKEN_NOTIFICATION_EVENT_MAP.get(key, DEFAULT_EVENT_TYPE)


def normalize_event_types(event_types: Any) -> Optional[List[str]]:
    """校验并规范化订阅列表；返回 None 表示订阅全部事件。"""
    if event_types is None:
        return None
    if isinstance(event_types, bytes):
        event_types = event_types.decode("utf-8", errors="ignore")
    if isinstance(event_types, str):
        text = event_types.strip()
        if not text:
            return None
        try:
            event_types = json.loads(text)
        except json.JSONDecodeError:
            event_types = [item.strip() for item in text.split(",") if item.strip()]
    if isinstance(event_types, (list, tuple, set)):
        selected = {str(item).strip() for item in event_types if str(item).strip()}
        unknown = sorted(selected - set(EVENT_IDS))
        if unknown:
            raise ValueError(f"不支持的通知事件类型: {', '.join(unknown)}")
        ordered = [event_id for event_id in EVENT_IDS if event_id in selected]
        return ordered or None
    raise ValueError("通知事件类型必须是数组或 JSON 数组")


def parse_event_types(raw: Any) -> Optional[List[str]]:
    """读取数据库中的订阅列表；数据异常时按订阅全部处理。"""
    try:
        return normalize_event_types(raw)
    except ValueError:
        return None


def serialize_event_types(event_types: Any) -> Optional[str]:
    normalized = normalize_event_types(event_types)
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False)
