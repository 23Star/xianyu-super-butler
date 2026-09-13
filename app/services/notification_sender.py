"""Reliable, configuration-only notification delivery.

The existing account runtime sends notifications from ``XianyuLive`` and
intentionally swallows provider errors.  A test-send endpoint needs the
opposite contract: one channel call must produce a clear, non-sensitive
success or failure.  This service keeps that contract independent of account
runtime state so it can also be used by other server-side callers.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import inspect
import json
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp

from .notification_channels import (
    NotificationChannelConfigError,
    validate_channel_config,
)


class NotificationSendError(RuntimeError):
    """Base error with a stable public error code."""

    code = "notification_send_failed"
    category = "send_failed"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        category: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        if code:
            self.code = code
        if category:
            self.category = category
        self.public_message = message
        self.status_code = status_code


class NotificationSendTimeout(NotificationSendError):
    code = "notification_send_timeout"
    category = "timeout"

    def __init__(self) -> None:
        super().__init__("通知渠道请求超时，请稍后重试")


class NotificationProviderRejected(NotificationSendError):
    code = "notification_provider_rejected"
    category = "provider_rejected"

    def __init__(self, status_code: int | None = None) -> None:
        suffix = f"（HTTP {status_code}）" if status_code else ""
        super().__init__(f"第三方通知服务拒绝了请求{suffix}", status_code=status_code)


class NotificationNetworkError(NotificationSendError):
    code = "notification_send_failed"
    category = "network"

    def __init__(self) -> None:
        super().__init__("通知渠道发送失败，请检查网络或服务配置")


@dataclass(frozen=True)
class NotificationSendReceipt:
    channel_type: str
    status_code: int | None = None
    provider_code: str | int | None = None


_MAX_TIMEOUT_SECONDS = 30.0
_DEFAULT_TIMEOUT_SECONDS = 10.0
_EMAIL_SUBJECT = "闲鱼超级管家测试通知"


def _safe_url(url: Any) -> str:
    """Validate a provider URL without logging or exposing its query values."""
    if not isinstance(url, str):
        raise NotificationChannelConfigError("通知渠道地址必须是有效的 URL")
    value = url.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NotificationChannelConfigError("通知渠道地址必须使用 HTTP 或 HTTPS")
    return value


def _with_query(url: str, values: Mapping[str, Any]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in values.items()})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _provider_code(payload: Any, *keys: str) -> str | int | None:
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _is_success_code(value: Any, accepted: set[Any]) -> bool:
    if value is None:
        return True
    return value in accepted or str(value) in {str(item) for item in accepted}


class NotificationSender:
    """Send one message through one configured channel."""

    def __init__(
        self,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        *,
        session_factory: Callable[..., Any] | None = None,
        email_sender: Callable[[dict[str, Any], str], Any] | None = None,
    ) -> None:
        self.timeout_seconds = min(max(float(timeout_seconds), 1.0), _MAX_TIMEOUT_SECONDS)
        self.session_factory = session_factory or aiohttp.ClientSession
        self.email_sender = email_sender

    async def send(
        self,
        channel_type: Any,
        config: Any,
        message: str,
        *,
        request_id: str | None = None,
    ) -> NotificationSendReceipt:
        if not isinstance(message, str) or not message.strip():
            raise NotificationChannelConfigError("测试消息不能为空")

        normalized_type, config_data = validate_channel_config(channel_type, config)
        handlers = {
            "dingtalk": self._send_dingtalk,
            "feishu": self._send_feishu,
            "bark": self._send_bark,
            "email": self._send_email,
            "webhook": self._send_webhook,
            "wechat": self._send_wechat,
            "telegram": self._send_telegram,
        }
        handler = handlers[normalized_type]
        try:
            return await handler(config_data, message, request_id=request_id)
        except NotificationChannelConfigError:
            raise
        except NotificationSendError:
            raise
        except asyncio.TimeoutError as exc:
            raise NotificationSendTimeout() from exc
        except aiohttp.ClientError as exc:
            raise NotificationNetworkError() from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise NotificationNetworkError() from exc
        except Exception as exc:  # noqa: BLE001 - normalize provider implementation errors
            raise NotificationSendError(
                "通知渠道发送失败，请检查网络或服务配置"
            ) from exc

    async def _open_session(self) -> Any:
        # The default factory returns an async context manager.  Keeping the
        # factory injectable makes all provider branches straightforward to
        # mock without opening a socket in tests.
        try:
            session = self.session_factory(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds)
            )
        except TypeError:
            session = self.session_factory()
        if inspect.isawaitable(session):
            session = await session
        return session

    async def _request_json(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, Any]:
        safe_url = _safe_url(url)
        session_context = await self._open_session()
        try:
            async with session_context as session:
                request_method = getattr(session, method.lower())
                kwargs: dict[str, Any] = {"json": dict(payload)}
                if headers:
                    kwargs["headers"] = dict(headers)
                try:
                    response_context = request_method(safe_url, **kwargs)
                    if inspect.isawaitable(response_context):
                        response_context = await response_context
                    async with response_context as response:
                        status = int(getattr(response, "status", 0) or 0)
                        text_reader = getattr(response, "text", "")
                        raw_text = text_reader() if callable(text_reader) else text_reader
                        if inspect.isawaitable(raw_text):
                            raw_text = await raw_text
                        try:
                            body = json.loads(raw_text) if raw_text else None
                        except (TypeError, json.JSONDecodeError):
                            body = None
                        if not 200 <= status < 300:
                            raise NotificationProviderRejected(status)
                        return status, body
                except (asyncio.TimeoutError, TimeoutError) as exc:
                    raise NotificationSendTimeout() from exc
                except NotificationSendError:
                    raise
                except aiohttp.ClientError as exc:
                    raise NotificationNetworkError() from exc
        finally:
            close = getattr(session_context, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result

    async def _send_dingtalk(
        self, config: dict[str, Any], message: str, *, request_id: str | None = None
    ) -> NotificationSendReceipt:
        url = _safe_url(config.get("webhook_url") or config.get("config"))
        secret = str(config.get("secret") or "")
        if secret:
            timestamp = str(round(time.time() * 1000))
            sign_text = f"{timestamp}\n{secret}".encode("utf-8")
            sign = base64.b64encode(hmac.new(secret.encode("utf-8"), sign_text, hashlib.sha256).digest()).decode()
            url = _with_query(url, {"timestamp": timestamp, "sign": sign})
        status, body = await self._request_json(
            "POST",
            url,
            {"msgtype": "markdown", "markdown": {"title": _EMAIL_SUBJECT, "text": message}},
        )
        code = _provider_code(body, "errcode", "code")
        if not _is_success_code(code, {0, "0"}):
            raise NotificationProviderRejected(status)
        return NotificationSendReceipt("dingtalk", status, code)

    async def _send_feishu(
        self, config: dict[str, Any], message: str, *, request_id: str | None = None
    ) -> NotificationSendReceipt:
        url = _safe_url(config.get("webhook_url"))
        timestamp = str(int(time.time()))
        payload: dict[str, Any] = {
            "msg_type": "text",
            "content": {"text": message},
            "timestamp": timestamp,
        }
        secret = str(config.get("secret") or "")
        if secret:
            sign_text = f"{timestamp}\n{secret}".encode("utf-8")
            payload["sign"] = base64.b64encode(hmac.new(sign_text, b"", hashlib.sha256).digest()).decode()
        status, body = await self._request_json("POST", url, payload)
        code = _provider_code(body, "code", "errcode")
        if not _is_success_code(code, {0, "0"}):
            raise NotificationProviderRejected(status)
        return NotificationSendReceipt("feishu", status, code)

    async def _send_bark(
        self, config: dict[str, Any], message: str, *, request_id: str | None = None
    ) -> NotificationSendReceipt:
        server_url = _safe_url(config.get("server_url") or "https://api.day.app").rstrip("/")
        payload: dict[str, Any] = {
            "device_key": str(config["device_key"]),
            "title": str(config.get("title") or _EMAIL_SUBJECT),
            "body": message,
            "sound": str(config.get("sound") or "default"),
            "group": str(config.get("group") or "xianyu"),
        }
        for key in ("icon", "url"):
            if config.get(key):
                payload[key] = config[key]
        status, body = await self._request_json("POST", f"{server_url}/push", payload)
        code = _provider_code(body, "code", "errcode")
        if code is not None and not _is_success_code(code, {200, "200", 0, "0"}):
            raise NotificationProviderRejected(status)
        return NotificationSendReceipt("bark", status, code)

    async def _send_email(
        self, config: dict[str, Any], message: str, *, request_id: str | None = None
    ) -> NotificationSendReceipt:
        sender = self.email_sender or self._send_email_sync
        try:
            await asyncio.wait_for(
                self._run_email_sender(sender, config, message),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise NotificationSendTimeout() from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise NotificationProviderRejected() from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise NotificationNetworkError() from exc
        return NotificationSendReceipt("email", None)

    @staticmethod
    async def _run_email_sender(
        sender: Callable[[dict[str, Any], str], Any],
        config: dict[str, Any],
        message: str,
    ) -> Any:
        """Run sync SMTP code off-loop while still accepting async test doubles."""
        is_async = inspect.iscoroutinefunction(sender) or inspect.iscoroutinefunction(
            getattr(sender, "__call__", None)
        )
        if is_async:
            result = sender(config, message)
        else:
            result = await asyncio.to_thread(sender, config, message)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _send_email_sync(config: dict[str, Any], message: str) -> None:
        email = EmailMessage()
        email["Subject"] = _EMAIL_SUBJECT
        email["From"] = str(config["email_user"])
        email["To"] = str(config["recipient_email"])
        email.set_content(message)

        smtp_server = str(config["smtp_server"])
        smtp_port = int(config["smtp_port"])
        use_tls = bool(config.get("smtp_use_tls", smtp_port == 587))
        server: Any = None
        try:
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=_MAX_TIMEOUT_SECONDS)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=_MAX_TIMEOUT_SECONDS)
                if use_tls:
                    server.starttls()
            server.login(str(config["email_user"]), str(config["email_password"]))
            server.send_message(email)
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    try:
                        server.close()
                    except Exception:
                        pass

    async def _send_webhook(
        self, config: dict[str, Any], message: str, *, request_id: str | None = None
    ) -> NotificationSendReceipt:
        url = _safe_url(config.get("webhook_url"))
        headers = config.get("headers") or {}
        if not isinstance(headers, Mapping):
            raise NotificationChannelConfigError("Webhook 请求头必须是 JSON 对象")
        normalized_headers = {str(key): str(value) for key, value in headers.items()}
        method = str(config.get("http_method") or "POST").upper()
        payload = {
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "xianyu-auto-reply",
        }
        status, _ = await self._request_json(method, url, payload, headers=normalized_headers)
        return NotificationSendReceipt("webhook", status)

    async def _send_wechat(
        self, config: dict[str, Any], message: str, *, request_id: str | None = None
    ) -> NotificationSendReceipt:
        url = _safe_url(config.get("webhook_url"))
        status, body = await self._request_json(
            "POST", url, {"msgtype": "text", "text": {"content": message}}
        )
        code = _provider_code(body, "errcode", "code")
        if not _is_success_code(code, {0, "0"}):
            raise NotificationProviderRejected(status)
        return NotificationSendReceipt("wechat", status, code)

    async def _send_telegram(
        self, config: dict[str, Any], message: str, *, request_id: str | None = None
    ) -> NotificationSendReceipt:
        token = str(config["bot_token"])
        url = _safe_url(f"https://api.telegram.org/bot{token}/sendMessage")
        status, body = await self._request_json(
            "POST",
            url,
            {"chat_id": config["chat_id"], "text": message, "parse_mode": "HTML"},
        )
        if isinstance(body, Mapping) and body.get("ok") is False:
            raise NotificationProviderRejected(status)
        code = _provider_code(body, "error_code", "code")
        if code is not None and not _is_success_code(code, {0, "0"}):
            raise NotificationProviderRejected(status)
        return NotificationSendReceipt("telegram", status, code)


async def send_notification(
    channel_type: Any,
    config: Any,
    message: str,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    request_id: str | None = None,
) -> NotificationSendReceipt:
    """Convenience entry point for one-off callers and tests."""
    return await NotificationSender(timeout_seconds=timeout_seconds).send(
        channel_type, config, message, request_id=request_id
    )


async def send_channel_notification(
    channel_type: Any,
    config: Any,
    message: str,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    request_id: str | None = None,
) -> NotificationSendReceipt:
    """Backward-friendly alias describing the channel-oriented operation."""
    return await send_notification(
        channel_type,
        config,
        message,
        timeout_seconds=timeout_seconds,
        request_id=request_id,
    )


__all__ = [
    "NotificationNetworkError",
    "NotificationProviderRejected",
    "NotificationSendError",
    "NotificationSendReceipt",
    "NotificationSendTimeout",
    "NotificationSender",
    "send_channel_notification",
    "send_notification",
]
