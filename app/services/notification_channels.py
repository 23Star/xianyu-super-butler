"""Shared notification-channel validation and normalization helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


NOTIFICATION_CHANNEL_REQUIRED_FIELDS = {
    "dingtalk": ("webhook_url",),
    "feishu": ("webhook_url",),
    "bark": ("device_key",),
    "email": ("smtp_server", "smtp_port", "email_user", "email_password", "recipient_email"),
    "webhook": ("webhook_url",),
    "wechat": ("webhook_url",),
    "telegram": ("bot_token", "chat_id"),
}

NOTIFICATION_CHANNEL_TYPE_ALIASES = {
    "ding_talk": "dingtalk",
    "lark": "feishu",
}

SUPPORTED_NOTIFICATION_CHANNEL_TYPES = frozenset(NOTIFICATION_CHANNEL_REQUIRED_FIELDS)


class NotificationChannelConfigError(ValueError):
    """A safe, user-facing channel configuration error."""

    code = "notification_config_invalid"
    category = "config"


def normalize_channel_type(channel_type: Any) -> str:
    normalized = str(channel_type or "").strip().lower()
    return NOTIFICATION_CHANNEL_TYPE_ALIASES.get(normalized, normalized)


def parse_channel_config(config: Any) -> dict[str, Any]:
    """Parse a persisted JSON config or accept an already parsed mapping."""
    if isinstance(config, Mapping):
        return dict(config)
    if isinstance(config, bytes):
        config = config.decode("utf-8", errors="replace")
    if not isinstance(config, str) or not config.strip():
        raise NotificationChannelConfigError("通知渠道配置必须是有效的 JSON")
    try:
        parsed = json.loads(config)
    except (TypeError, json.JSONDecodeError) as exc:
        raise NotificationChannelConfigError("通知渠道配置必须是有效的 JSON") from exc
    if not isinstance(parsed, dict):
        raise NotificationChannelConfigError("通知渠道配置必须是 JSON 对象")
    return parsed


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_channel_config(channel_type: Any, config: Any) -> tuple[str, dict[str, Any]]:
    """Return a canonical type and config, raising without exposing secrets."""
    normalized_type = normalize_channel_type(channel_type)
    if normalized_type not in NOTIFICATION_CHANNEL_REQUIRED_FIELDS:
        raise NotificationChannelConfigError("不支持的通知渠道类型")

    config_data = parse_channel_config(config)
    missing_fields = [
        field
        for field in NOTIFICATION_CHANNEL_REQUIRED_FIELDS[normalized_type]
        if _is_blank(config_data.get(field))
    ]
    if missing_fields:
        raise NotificationChannelConfigError(
            f"通知渠道配置缺少字段: {', '.join(missing_fields)}"
        )

    if normalized_type == "email":
        try:
            smtp_port = int(config_data["smtp_port"])
        except (TypeError, ValueError) as exc:
            raise NotificationChannelConfigError("SMTP 端口必须是数字") from exc
        if not 1 <= smtp_port <= 65535:
            raise NotificationChannelConfigError("SMTP 端口必须在 1-65535 之间")
        config_data["smtp_port"] = smtp_port

    if normalized_type == "webhook":
        http_method = str(config_data.get("http_method", "POST")).strip().upper()
        if http_method not in {"POST", "PUT"}:
            raise NotificationChannelConfigError("Webhook 请求方法仅支持 POST 或 PUT")
        config_data["http_method"] = http_method

        headers = config_data.get("headers")
        if isinstance(headers, str) and headers.strip():
            try:
                headers = json.loads(headers)
            except json.JSONDecodeError as exc:
                raise NotificationChannelConfigError(
                    "Webhook 请求头必须是有效的 JSON 对象"
                ) from exc
            if not isinstance(headers, dict):
                raise NotificationChannelConfigError("Webhook 请求头必须是 JSON 对象")
            config_data["headers"] = headers
        elif headers is not None and not isinstance(headers, dict):
            raise NotificationChannelConfigError("Webhook 请求头必须是 JSON 对象")

    return normalized_type, config_data


def validate_notification_channel(
    name: Any,
    channel_type: Any,
    config: Any,
) -> tuple[str, str, str]:
    """Validate a channel record and return its persisted canonical form."""
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise NotificationChannelConfigError("通知渠道名称不能为空")
    if len(normalized_name) > 80:
        raise NotificationChannelConfigError("通知渠道名称不能超过 80 个字符")

    normalized_type, config_data = validate_channel_config(channel_type, config)
    return (
        normalized_name,
        normalized_type,
        json.dumps(config_data, ensure_ascii=False, separators=(",", ":")),
    )


__all__ = [
    "NOTIFICATION_CHANNEL_REQUIRED_FIELDS",
    "NOTIFICATION_CHANNEL_TYPE_ALIASES",
    "SUPPORTED_NOTIFICATION_CHANNEL_TYPES",
    "NotificationChannelConfigError",
    "normalize_channel_type",
    "parse_channel_config",
    "validate_channel_config",
    "validate_notification_channel",
]
