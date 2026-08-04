import json
import os
import tempfile
import unittest

from app.db_manager import DBManager
from app.reply_server import validate_notification_channel


class NotificationChannelValidationTests(unittest.TestCase):
    def test_normalizes_alias_and_email_port(self):
        name, channel_type, config = validate_notification_channel(
            "  运维钉钉  ",
            "ding_talk",
            json.dumps({"webhook_url": "https://example.test/hook"}),
        )

        self.assertEqual(name, "运维钉钉")
        self.assertEqual(channel_type, "dingtalk")
        self.assertEqual(json.loads(config)["webhook_url"], "https://example.test/hook")

        _, _, email_config = validate_notification_channel(
            "邮箱",
            "email",
            json.dumps({
                "smtp_server": "smtp.example.test",
                "smtp_port": "587",
                "email_user": "sender@example.test",
                "email_password": "secret",
                "recipient_email": "owner@example.test",
            }),
        )
        self.assertEqual(json.loads(email_config)["smtp_port"], 587)

    def test_rejects_unknown_type_and_invalid_config(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            validate_notification_channel("测试", "qq", "{}")

        with self.assertRaisesRegex(ValueError, "缺少字段"):
            validate_notification_channel("测试", "telegram", "{}")

        with self.assertRaisesRegex(ValueError, "请求头"):
            validate_notification_channel(
                "Webhook",
                "webhook",
                json.dumps({"webhook_url": "https://example.test", "headers": "[]"}),
            )


class RiskControlLogIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DBManager(os.path.join(self.temp_dir.name, "risk.db"))
        cursor = self.manager.conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (username, email, password_hash)
            VALUES ('other-user', 'other@example.test', 'hash')
            """
        )
        self.other_user_id = cursor.lastrowid
        self.admin_user_id = cursor.execute(
            "SELECT id FROM users WHERE username = 'admin'"
        ).fetchone()[0]
        cursor.executemany(
            "INSERT INTO cookies (id, value, user_id) VALUES (?, ?, ?)",
            [
                ("admin-account", "cookie-a", self.admin_user_id),
                ("other-account", "cookie-b", self.other_user_id),
            ],
        )
        self.manager.conn.commit()
        self.manager.add_risk_control_log("admin-account", processing_status="success")
        self.manager.add_risk_control_log("other-account", processing_status="failed")

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def test_list_and_count_are_scoped_by_user(self):
        admin_logs = self.manager.get_risk_control_logs(user_id=self.admin_user_id)
        other_logs = self.manager.get_risk_control_logs(user_id=self.other_user_id)

        self.assertEqual([log["cookie_id"] for log in admin_logs], ["admin-account"])
        self.assertEqual([log["cookie_id"] for log in other_logs], ["other-account"])
        self.assertEqual(self.manager.get_risk_control_logs_count(user_id=self.admin_user_id), 1)
        self.assertEqual(self.manager.get_risk_control_logs_count(user_id=self.other_user_id), 1)
        self.assertEqual(self.manager.get_risk_control_logs_count(), 2)

    def test_list_and_count_filter_by_processing_status(self):
        success_logs = self.manager.get_risk_control_logs(
            user_id=self.admin_user_id,
            processing_status="success",
        )
        failed_logs = self.manager.get_risk_control_logs(
            user_id=self.admin_user_id,
            processing_status="failed",
        )

        self.assertEqual([log["cookie_id"] for log in success_logs], ["admin-account"])
        self.assertEqual(failed_logs, [])
        self.assertEqual(
            self.manager.get_risk_control_logs_count(
                user_id=self.admin_user_id,
                processing_status="success",
            ),
            1,
        )
        self.assertEqual(
            self.manager.get_risk_control_logs_count(
                user_id=self.admin_user_id,
                processing_status="failed",
            ),
            0,
        )

    def test_delete_enforces_ownership_when_user_is_provided(self):
        other_log_id = self.manager.conn.execute(
            "SELECT id FROM risk_control_logs WHERE cookie_id = 'other-account'"
        ).fetchone()[0]

        self.assertFalse(
            self.manager.delete_risk_control_log(other_log_id, user_id=self.admin_user_id)
        )
        self.assertTrue(
            self.manager.delete_risk_control_log(other_log_id, user_id=self.other_user_id)
        )


if __name__ == "__main__":
    unittest.main()
