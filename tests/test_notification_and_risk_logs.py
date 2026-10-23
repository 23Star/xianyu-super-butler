import json
import os
import sqlite3
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


class NotificationRuleValidationTests(unittest.TestCase):
    def test_normalizes_rule_name_and_event_types(self):
        from app.reply_server import validate_notification_rule

        name, events = validate_notification_rule(
            "  仅关键  ", ["buyer_message", "delivery_failed"]
        )
        self.assertEqual(name, "仅关键")
        self.assertEqual(events, ["delivery_failed", "buyer_message"])

        name, events = validate_notification_rule("", [])
        self.assertIsNone(name)
        self.assertIsNone(events)

        with self.assertRaisesRegex(ValueError, "不能超过"):
            validate_notification_rule("x" * 81, None)
        with self.assertRaisesRegex(ValueError, "不支持"):
            validate_notification_rule("规则", ["bogus"])


class NotificationEventDefinitionTests(unittest.TestCase):
    def test_resolve_event_type_maps_notification_types(self):
        from app.notification_events import normalize_event_types, resolve_event_type

        self.assertEqual(resolve_event_type("face_verification"), "captcha_manual")
        self.assertEqual(resolve_event_type("password_login_success"), "login_success")
        self.assertEqual(resolve_event_type("unknown_type"), "cookie_invalid")

    def test_normalize_event_types_orders_and_validates(self):
        from app.notification_events import normalize_event_types

        self.assertEqual(
            normalize_event_types(["buyer_message", "delivery_failed"]),
            ["delivery_failed", "buyer_message"],
        )
        self.assertEqual(normalize_event_types("delivery_failed"), ["delivery_failed"])
        self.assertIsNone(normalize_event_types([]))
        self.assertIsNone(normalize_event_types(""))
        with self.assertRaisesRegex(ValueError, "不支持"):
            normalize_event_types(["not_exists"])


class MessageNotificationRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DBManager(os.path.join(self.temp_dir.name, "rules.db"))
        cursor = self.manager.conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) "
            "VALUES ('rule-user', 'rule@example.test', 'hash')"
        )
        self.user_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO cookies (id, value, user_id) VALUES ('rule-account', 'cookie', ?)",
            (self.user_id,),
        )
        cursor.execute(
            "INSERT INTO notification_channels (name, type, config, user_id) "
            "VALUES ('rule-channel', 'bark', '{}', ?)",
            (self.user_id,),
        )
        self.channel_id = cursor.lastrowid
        self.manager.conn.commit()

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def test_account_supports_multiple_rules_per_channel(self):
        all_rule = self.manager.create_notification_rule(
            "rule-account", self.channel_id, "全部通知"
        )
        critical_rule = self.manager.create_notification_rule(
            "rule-account", self.channel_id, "仅关键", ["delivery_failed"]
        )

        failure_rules = self.manager.get_account_notifications(
            "rule-account", event_type="delivery_failed"
        )
        self.assertEqual({rule["id"] for rule in failure_rules}, {all_rule, critical_rule})

        message_rules = self.manager.get_account_notifications(
            "rule-account", event_type="buyer_message"
        )
        self.assertEqual([rule["id"] for rule in message_rules], [all_rule])

    def test_update_rule_events_and_ownership(self):
        rule_id = self.manager.create_notification_rule(
            "rule-account", self.channel_id, "仅关键", ["delivery_failed"]
        )
        self.assertTrue(
            self.manager.update_notification_rule(
                rule_id, "仅关键", ["buyer_message"], True, self.user_id
            )
        )
        rules = self.manager.get_account_notifications(
            "rule-account", event_type="buyer_message"
        )
        self.assertEqual([rule["id"] for rule in rules], [rule_id])

        self.assertTrue(
            self.manager.update_notification_rule(rule_id, "仅关键", [], False, self.user_id)
        )
        rule = self.manager.get_notification_rule(rule_id, self.user_id)
        self.assertFalse(rule["enabled"])
        self.assertIsNone(rule["event_types"])

        self.assertFalse(
            self.manager.update_notification_rule(
                rule_id, "越权", None, True, self.user_id + 999
            )
        )
        self.assertIsNone(self.manager.get_notification_rule(rule_id, self.user_id + 999))

    def test_set_message_notification_preserves_filters(self):
        self.manager.set_message_notification(
            "rule-account", self.channel_id, True, "保留规则", ["delivery_failed"]
        )
        self.manager.set_message_notification("rule-account", self.channel_id, False)

        rules = self.manager.get_account_notifications("rule-account")
        self.assertEqual(len(rules), 1)
        self.assertFalse(rules[0]["enabled"])
        self.assertEqual(rules[0]["name"], "保留规则")
        self.assertEqual(rules[0]["event_types"], ["delivery_failed"])


class MessageNotificationMigrationTests(unittest.TestCase):
    def test_legacy_binding_table_is_rebuilt(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = os.path.join(temp_dir.name, "legacy.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript('''
                CREATE TABLE message_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cookie_id TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    enabled BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(cookie_id, channel_id)
                );
                INSERT INTO message_notifications (cookie_id, channel_id, enabled)
                VALUES ('legacy-account', 1, 1);
                CREATE TABLE system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO system_settings (key, value) VALUES ('db_version', '1.6');
            ''')
            conn.commit()
        finally:
            conn.close()

        manager = DBManager(db_path)
        try:
            indexes = manager.conn.execute(
                "PRAGMA index_list(message_notifications)"
            ).fetchall()
            unique_indexes = [
                row for row in indexes if len(row) > 3 and row[2] and row[3] == 'u'
            ]
            self.assertEqual(unique_indexes, [])

            columns = {
                row[1]
                for row in manager.conn.execute(
                    "PRAGMA table_info(message_notifications)"
                ).fetchall()
            }
            self.assertIn("name", columns)
            self.assertIn("event_types", columns)

            cursor = manager.conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash) "
                "VALUES ('legacy-user', 'legacy@example.test', 'hash')"
            )
            user_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO cookies (id, value, user_id) VALUES ('legacy-account', 'cookie', ?)",
                (user_id,),
            )
            cursor.execute(
                "INSERT INTO notification_channels (name, type, config, user_id) "
                "VALUES ('legacy-channel', 'bark', '{}', ?)",
                (user_id,),
            )
            manager.conn.commit()

            rules = manager.get_account_notifications("legacy-account")
            self.assertEqual(len(rules), 1)
            self.assertIsNone(rules[0]["event_types"])
            self.assertTrue(rules[0]["enabled"])

            second_id = manager.create_notification_rule(
                "legacy-account", 1, "第二条", ["buyer_message"]
            )
            self.assertTrue(second_id)
            self.assertEqual(len(manager.get_account_notifications("legacy-account")), 2)
        finally:
            manager.close()


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
