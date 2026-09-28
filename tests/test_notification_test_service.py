"""Unit coverage for account-notification test sends."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

from app.db_manager import DBManager
from app.services.notification_channels import NotificationChannelConfigError
from app.services.notification_sender import (
    NotificationNetworkError,
    NotificationProviderRejected,
    NotificationSendError,
    NotificationSendReceipt,
    NotificationSendTimeout,
    NotificationSender,
)
from app.services.notification_test import (
    NotificationTestError,
    NotificationTestRateLimiter,
    NotificationTestService,
    build_test_message,
)


class _Response:
    def __init__(self, status=200, body=None, text_value=None):
        self.status = status
        self.body = body
        self.text_value = text_value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def text(self):
        if self.text_value is not None:
            return self.text_value
        return json.dumps(self.body) if self.body is not None else ""


class _Session:
    def __init__(self, calls, response_factory):
        self.calls = calls
        self.response_factory = response_factory

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response_factory("POST", url, kwargs)

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return self.response_factory("PUT", url, kwargs)

    async def close(self):
        return None


class _SessionFactory:
    def __init__(self, response_factory):
        self.calls = []
        self.response_factory = response_factory

    def __call__(self, **_kwargs):
        return _Session(self.calls, self.response_factory)


class NotificationSenderTests(unittest.TestCase):
    def run_async(self, awaitable):
        return asyncio.run(awaitable)

    def test_all_supported_channels_use_one_safe_sender(self):
        configs = {
            "dingtalk": {"webhook_url": "https://example.test/dingtalk"},
            "feishu": {"webhook_url": "https://example.test/feishu"},
            "bark": {"device_key": "device-key", "server_url": "https://example.test"},
            "webhook": {"webhook_url": "https://example.test/webhook", "http_method": "PUT"},
            "wechat": {"webhook_url": "https://example.test/wechat"},
            "telegram": {"bot_token": "bot-token", "chat_id": "chat"},
        }
        email_config = {
            "smtp_server": "smtp.example.test",
            "smtp_port": 587,
            "email_user": "sender@example.test",
            "email_password": "password",
            "recipient_email": "recipient@example.test",
        }

        for channel_type, config in configs.items():
            def response_factory(_method, url, _kwargs):
                if "/push" in url:
                    return _Response(body={"code": 200})
                if "telegram.org" in url:
                    return _Response(body={"ok": True})
                if "wechat" in url:
                    return _Response(body={"errcode": 0})
                return _Response(body={"code": 0})

            factory = _SessionFactory(response_factory)
            receipt = self.run_async(
                NotificationSender(session_factory=factory).send(
                    channel_type, config, build_test_message("nt_test")
                )
            )
            self.assertEqual(receipt.channel_type, channel_type)
            self.assertEqual(receipt.status_code, 200)
            self.assertEqual(len(factory.calls), 1)

        email_calls = []
        receipt = self.run_async(
            NotificationSender(
                email_sender=lambda config, message: email_calls.append((config, message))
            ).send("email", email_config, "test")
        )
        self.assertEqual(receipt.channel_type, "email")
        self.assertEqual(len(email_calls), 1)

    def test_async_email_sender_is_supported(self):
        calls = []

        async def send_email(config, message):
            calls.append((config, message))

        receipt = self.run_async(
            NotificationSender(email_sender=send_email).send(
                "email",
                {
                    "smtp_server": "smtp.example.test",
                    "smtp_port": 587,
                    "email_user": "sender@example.test",
                    "email_password": "password",
                    "recipient_email": "recipient@example.test",
                },
                "test",
            )
        )
        self.assertEqual(receipt.channel_type, "email")
        self.assertEqual(len(calls), 1)

    def test_provider_status_and_timeout_are_normalized(self):
        rejected_factory = _SessionFactory(
            lambda _method, _url, _kwargs: _Response(status=503, body={"error": "private"})
        )
        with self.assertRaises(NotificationProviderRejected) as rejected:
            self.run_async(
                NotificationSender(session_factory=rejected_factory).send(
                    "webhook", {"webhook_url": "https://example.test"}, "test"
                )
            )
        self.assertEqual(rejected.exception.status_code, 503)

        def timeout_factory(_method, _url, _kwargs):
            raise asyncio.TimeoutError()

        with self.assertRaises(NotificationSendTimeout):
            self.run_async(
                NotificationSender(session_factory=_SessionFactory(timeout_factory)).send(
                    "webhook", {"webhook_url": "https://example.test"}, "test"
                )
            )

        with self.assertRaises(NotificationChannelConfigError):
            self.run_async(NotificationSender().send("telegram", {}, "test"))


class _TargetDB:
    def __init__(self, target=None):
        self.target = target
        self.calls = []

    def get_notification_test_target(self, rule_id, user_id):
        self.calls.append((rule_id, user_id))
        return self.target


class _RecordingSender:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result if result is not None else NotificationSendReceipt("webhook", 200)
        self.error = error

    async def send(self, channel_type, config, message):
        self.calls.append((channel_type, config, message))
        if self.error:
            raise self.error
        return self.result


def _target(**overrides):
    value = {
        "id": 7,
        "cookie_id": "account-1",
        "channel_id": 11,
        "channel_name": "测试渠道",
        "channel_type": "webhook",
        "channel_config": {"webhook_url": "https://example.test/hook", "token": "secret"},
        "enabled": False,
        "channel_enabled": False,
    }
    value.update(overrides)
    return value


class NotificationTestServiceTests(unittest.TestCase):
    def run_async(self, awaitable):
        return asyncio.run(awaitable)

    def test_success_allows_disabled_rule_and_channel_and_audits_without_secrets(self):
        logs = []
        sender = _RecordingSender()
        service = NotificationTestService(
            _TargetDB(_target()),
            sender=sender,
            limiter=NotificationTestRateLimiter(limit=3),
            log_fn=lambda level, message, user: logs.append((level, message, user)),
        )

        result = self.run_async(service.send_rule_test(7, 42, {"user_id": 42, "username": "seller"}))

        self.assertTrue(result["success"])
        self.assertEqual(result["channel"]["id"], 11)
        self.assertIn(result["request_id"], sender.calls[0][2])
        self.assertEqual([entry[0] for entry in logs], ["info", "info"])
        self.assertTrue(all("secret" not in entry[1] for entry in logs))
        self.assertTrue(all("token" not in entry[1] for entry in logs))

    def test_unauthorized_target_does_not_send(self):
        sender = _RecordingSender()
        service = NotificationTestService(_TargetDB(None), sender=sender)
        with self.assertRaises(NotificationTestError) as raised:
            self.run_async(service.send_rule_test(7, 99))
        self.assertEqual(raised.exception.code, "notification_rule_not_found")
        self.assertEqual(sender.calls, [])

    def test_false_sender_result_is_failure(self):
        service = NotificationTestService(
            _TargetDB(_target()),
            sender=_RecordingSender(result=False),
        )
        with self.assertRaises(NotificationTestError) as raised:
            self.run_async(service.send_rule_test(7, 42))
        self.assertEqual(raised.exception.code, "notification_send_failed")

    def test_failures_map_to_stable_codes_and_rate_limit(self):
        cases = [
            (NotificationChannelConfigError("bad"), "notification_config_invalid", 400),
            (NotificationSendTimeout(), "notification_send_timeout", 504),
            (NotificationProviderRejected(502), "notification_provider_rejected", 502),
            (NotificationNetworkError(), "notification_send_failed", 502),
            (RuntimeError("provider secret"), "notification_send_failed", 502),
        ]
        for error, code, status in cases:
            service = NotificationTestService(_TargetDB(_target()), sender=_RecordingSender(error=error))
            with self.assertRaises(NotificationTestError) as raised:
                self.run_async(service.send_rule_test(7, 42))
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(raised.exception.status_code, status)

        sender = _RecordingSender()
        service = NotificationTestService(
            _TargetDB(_target()),
            sender=sender,
            limiter=NotificationTestRateLimiter(limit=3),
        )
        for _ in range(3):
            self.run_async(service.send_rule_test(7, 42))
        with self.assertRaises(NotificationTestError) as raised:
            self.run_async(service.send_rule_test(7, 42))
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(len(sender.calls), 3)


class NotificationTestTargetDBTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DBManager(os.path.join(self.temp_dir.name, "notification-test.db"))
        cursor = self.manager.conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES ('owner', 'owner@example.test', 'hash')"
        )
        self.user_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO cookies (id, value, user_id) VALUES ('account-1', 'cookie', ?)",
            (self.user_id,),
        )
        cursor.execute(
            "INSERT INTO notification_channels (name, type, config, enabled, user_id) "
            "VALUES ('channel', 'webhook', ?, 0, ?)",
            (json.dumps({"webhook_url": "https://example.test"}), self.user_id),
        )
        self.channel_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO message_notifications (cookie_id, channel_id, enabled) VALUES ('account-1', ?, 0)",
            (self.channel_id,),
        )
        self.rule_id = cursor.lastrowid
        self.manager.conn.commit()

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def test_target_query_checks_both_owners_and_keeps_disabled_flags(self):
        target = self.manager.get_notification_test_target(self.rule_id, self.user_id)
        self.assertEqual(target["channel_id"], self.channel_id)
        self.assertFalse(target["enabled"])
        self.assertFalse(target["channel_enabled"])
        self.assertIsNone(self.manager.get_notification_test_target(self.rule_id, self.user_id + 1))


if __name__ == "__main__":
    unittest.main()
