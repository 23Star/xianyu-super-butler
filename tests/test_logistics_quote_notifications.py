"""物流报价第五步事件发布测试。"""

import unittest
from app.services.logistics_agent.notifications import (
    build_logistics_quote_event,
    clear_notification_dedup,
    format_logistics_quote_message,
    publish_logistics_quote_event,
)


class _Db:
    def get_cookie_owner_user(self, account_id):
        return 7 if account_id == "account-1" else None

    def get_user_by_id(self, user_id):
        return {"username": "seller"}


class _Account:
    def __init__(self, result=1, error=None):
        self.calls = []
        self.result = result
        self.error = error

    async def send_system_notification(self, message, event_type=""):
        self.calls.append((message, event_type))
        if self.error:
            raise self.error
        return self.result


class LogisticsQuoteNotificationTests(unittest.TestCase):
    def setUp(self):
        clear_notification_dedup()
        self.logs = []
        self.log_fn = lambda level, message, user: self.logs.append((level, message, user))

    def tearDown(self):
        clear_notification_dedup()

    def _event(self, **overrides):
        values = {
            "account_id": "account-1",
            "message_id": "message-1",
            "chat_id": "buyer-chat-1",
            "item_id": "item-1",
            "thread_id": "prod:account-1:buyer-chat-1:item-1",
            "decision_action": "manual",
            "reason": "route_not_found",
        }
        values.update(overrides)
        return build_logistics_quote_event(**values)

    def test_failure_is_logged_and_notified_once(self):
        account = _Account(result=2)
        event = self._event(
            decision_action="manual",
            reason="workflow_failed",
            retryable=True,
        )
        result = publish_logistics_quote_event(
            event, db=_Db(), log_fn=self.log_fn, account_instance=account
        )
        duplicate = publish_logistics_quote_event(
            event, db=_Db(), log_fn=self.log_fn, account_instance=account
        )

        self.assertEqual(result["sent_channels"], 2)
        self.assertFalse(duplicate["published"])
        self.assertTrue(duplicate["deduplicated"])
        self.assertEqual(len(account.calls), 1)
        self.assertEqual(account.calls[0][1], "logistics_quote")
        self.assertEqual(self.logs[0][0], "error")
        self.assertEqual(self.logs[0][2], {"user_id": 7, "username": "seller"})

    def test_manual_event_uses_warning_and_masks_sensitive_values(self):
        account = _Account()
        event = self._event(reason="route_not_found")
        message = format_logistics_quote_message(event)
        self.assertIn("source=logistics_quote", message)
        self.assertNotIn("buyer-chat-1", message)
        self.assertNotIn("account-1", message)
        self.assertNotIn("江西省赣州市", format_logistics_quote_message({**event, "reason": "江西省赣州市 13800138000"}))

        result = publish_logistics_quote_event(
            event, db=_Db(), log_fn=self.log_fn, account_instance=account
        )
        self.assertTrue(result["external_sent"])
        self.assertEqual(self.logs[0][0], "warning")
        self.assertIn("物流报价转人工", self.logs[0][1])

    def test_draft_is_logged_but_does_not_notify(self):
        account = _Account()
        event = self._event(decision_action="draft", reason="workflow_failed")
        result = publish_logistics_quote_event(
            event, db=_Db(), log_fn=self.log_fn, account_instance=account
        )
        self.assertTrue(result["published"])
        self.assertFalse(result["external_sent"])
        self.assertEqual(result["reason"], "draft")
        self.assertEqual(account.calls, [])
        self.assertEqual(self.logs[0][0], "error")

    def test_channel_failure_keeps_event_result_and_logs_separately(self):
        account = _Account(error=RuntimeError("channel down"))
        event = self._event(reason="render_failed", decision_action="manual")
        result = publish_logistics_quote_event(
            event, db=_Db(), log_fn=self.log_fn, account_instance=account
        )
        self.assertTrue(result["published"])
        self.assertFalse(result["external_sent"])
        self.assertEqual(len(self.logs), 2)
        self.assertEqual(self.logs[0][0], "error")
        self.assertIn("外部通知发送失败", self.logs[1][1])

    def test_success_and_unknown_reasons_are_not_actionable(self):
        self.assertIsNone(
            build_logistics_quote_event(
                account_id="account-1", decision_action="reply", reason="quoted"
            )
        )
        result = publish_logistics_quote_event(
            {"event": "other"}, log_fn=self.log_fn
        )
        self.assertFalse(result["published"])
        self.assertEqual(self.logs, [])


if __name__ == "__main__":
    unittest.main()
