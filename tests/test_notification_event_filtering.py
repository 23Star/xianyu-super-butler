"""通知规则勾选的事件类型必须在发送时生效。

回归的是这个故障：规则里勾选的事件类型（例如 Bark 只订阅「人工验证提醒」）
保存进了数据库，但发送端调用 get_account_notifications 时从不传 event_type，
所有规则都会收到所有事件 —— 只想收预警的 Bark 也被普通买家私聊刷屏。
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.db_manager import DBManager
from XianyuAutoAsync import XianyuLive

ACCOUNT = "acc_notify"


class NotificationEventFilteringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DBManager(str(Path(self.tmp.name) / "test.db"))
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO cookies (id, value, user_id) VALUES (?, ?, ?)",
                (ACCOUNT, "k=v", 1),
            )
            self.db.conn.commit()
        bark = self.db.create_notification_channel(
            "bark", "bark", json.dumps({"device_key": "x"}), user_id=1
        )
        webhook = self.db.create_notification_channel(
            "hook", "webhook", json.dumps({"webhook_url": "http://example.invalid"}), user_id=1
        )
        # Bark 只订阅预警；Webhook 只订阅买家消息和发货成功
        self.db.create_notification_rule(
            ACCOUNT, bark, "预警", event_types=["captcha_manual", "cookie_invalid", "delivery_failed"]
        )
        self.db.create_notification_rule(
            ACCOUNT, webhook, "消息", event_types=["buyer_message", "delivery_success"]
        )

        self.live = XianyuLive.__new__(XianyuLive)
        self.live.cookie_id = ACCOUNT
        self.live.notification_lock = asyncio.Lock()
        self.live.last_notification_time = {}
        self.live.notification_cooldown = 300
        self.live.token_refresh_notification_cooldown = 10800
        self.live._send_bark_notification = AsyncMock()
        self.live._send_webhook_notification = AsyncMock()

        self.patcher = patch("app.db_manager.db_manager", self.db)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        try:
            self.db.conn.close()
        finally:
            self.tmp.cleanup()

    def test_rule_filter_respects_event_type(self):
        rules = self.db.get_account_notifications(ACCOUNT, event_type="buyer_message")
        self.assertEqual([r["channel_type"] for r in rules], ["webhook"])

    def test_buyer_message_skips_alert_only_channel(self):
        asyncio.run(
            self.live.send_notification("买家", "123", "你好，还在吗", "item1", "chat1")
        )
        self.live._send_bark_notification.assert_not_called()
        self.live._send_webhook_notification.assert_awaited_once()

    def test_delivery_success_and_failure_route_separately(self):
        asyncio.run(
            self.live.send_delivery_failure_notification(
                "买家", "123", "item1", "发货成功", "chat1", event_type="delivery_success"
            )
        )
        self.live._send_bark_notification.assert_not_called()
        self.live._send_webhook_notification.assert_awaited_once()

        self.live._send_webhook_notification.reset_mock()
        asyncio.run(
            self.live.send_delivery_failure_notification(
                "买家", "123", "item1", "未找到匹配的发货规则", "chat1"
            )
        )
        self.live._send_bark_notification.assert_awaited_once()
        self.live._send_webhook_notification.assert_not_called()

    def test_rule_without_selection_still_receives_everything(self):
        """没勾选任何事件的旧规则保持原行为：订阅全部。"""
        legacy = self.db.create_notification_channel(
            "legacy", "bark", json.dumps({"device_key": "y"}), user_id=1
        )
        self.db.create_notification_rule(ACCOUNT, legacy, "全部", event_types=None)
        rules = self.db.get_account_notifications(ACCOUNT, event_type="buyer_message")
        self.assertEqual(sorted(r["channel_name"] for r in rules), ["hook", "legacy"])


if __name__ == "__main__":
    unittest.main()
