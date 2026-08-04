import os
import sqlite3
import tempfile
import unittest

from app.db_manager import DBManager
from app.reply_server import validate_message_filter


class MessageFilterAndReplyLogTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DBManager(os.path.join(self.temp_dir.name, "messages.db"))
        cursor = self.manager.conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (username, email, password_hash)
            VALUES ('message-user', 'message@example.test', 'hash')
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

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def test_filter_matching_is_case_insensitive_and_type_specific(self):
        self.manager.create_message_filter(
            "admin-account", "System Notice", "skip_reply", self.admin_user_id
        )
        self.manager.create_message_filter(
            "admin-account", "Do Not Notify", "skip_notify", self.admin_user_id
        )

        self.assertEqual(
            self.manager.matches_message_filter(
                "admin-account", "SYSTEM NOTICE: updated", "skip_reply"
            ),
            "System Notice",
        )
        self.assertIsNone(
            self.manager.matches_message_filter(
                "admin-account", "Do Not Notify", "skip_reply"
            )
        )
        self.assertEqual(
            self.manager.matches_message_filter(
                "admin-account", "please do not notify me", "skip_notify"
            ),
            "Do Not Notify",
        )

    def test_disabled_filter_does_not_match(self):
        filter_id = self.manager.create_message_filter(
            "admin-account",
            "ignore me",
            "skip_reply",
            self.admin_user_id,
            enabled=False,
        )

        self.assertIsNone(
            self.manager.matches_message_filter(
                "admin-account", "ignore me", "skip_reply"
            )
        )
        self.manager.update_message_filter(
            filter_id, self.admin_user_id, enabled=True
        )
        self.assertEqual(
            self.manager.matches_message_filter(
                "admin-account", "ignore me", "skip_reply"
            ),
            "ignore me",
        )

    def test_duplicate_filter_is_rejected(self):
        self.manager.create_message_filter(
            "admin-account", "duplicate", "skip_reply", self.admin_user_id
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.manager.create_message_filter(
                "admin-account", "duplicate", "skip_reply", self.admin_user_id
            )

    def test_filter_crud_is_scoped_to_account_owner(self):
        filter_id = self.manager.create_message_filter(
            "other-account", "private", "skip_reply", self.other_user_id
        )

        self.assertEqual(self.manager.get_message_filters(self.admin_user_id), [])
        self.assertFalse(
            self.manager.update_message_filter(
                filter_id, self.admin_user_id, enabled=False
            )
        )
        self.assertFalse(
            self.manager.delete_message_filter(filter_id, self.admin_user_id)
        )
        self.assertTrue(
            self.manager.delete_message_filter(filter_id, self.other_user_id)
        )

    def test_reply_log_filters_and_user_isolation(self):
        admin_log_id = self.manager.add_auto_reply_log(
            cookie_id="admin-account",
            source_message="price please",
            process_status="success",
            reply_strategy="keyword",
            matched_keyword="price",
            reply_text="80",
            send_status="success",
        )
        self.manager.add_auto_reply_log(
            cookie_id="other-account",
            source_message="hello",
            process_status="failed",
            reply_strategy="ai",
            error_message="timeout",
            send_status="failed",
        )
        self.manager.update_auto_reply_log(
            admin_log_id,
            decision_reason="reply_sent",
        )

        admin_logs = self.manager.get_auto_reply_logs(
            self.admin_user_id,
            process_status="success",
            reply_strategy="keyword",
            keyword="price",
        )
        self.assertEqual([log["cookie_id"] for log in admin_logs], ["admin-account"])
        self.assertEqual(admin_logs[0]["decision_reason"], "reply_sent")
        self.assertEqual(
            self.manager.get_auto_reply_logs_count(
                self.admin_user_id, send_status="success"
            ),
            1,
        )
        self.assertEqual(
            self.manager.get_auto_reply_logs_count(self.other_user_id),
            1,
        )


class MessageFilterValidationTests(unittest.TestCase):
    def test_normalizes_values(self):
        self.assertEqual(
            validate_message_filter(
                " account-1 ", "  System Notice  ", " SKIP_REPLY "
            ),
            ("account-1", "System Notice", "skip_reply"),
        )

    def test_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "账号不能为空"):
            validate_message_filter("", "keyword", "skip_reply")
        with self.assertRaisesRegex(ValueError, "过滤关键词不能为空"):
            validate_message_filter("account-1", " ", "skip_reply")
        with self.assertRaisesRegex(ValueError, "无效的过滤类型"):
            validate_message_filter("account-1", "keyword", "unknown")
        with self.assertRaisesRegex(ValueError, "200"):
            validate_message_filter("account-1", "x" * 201, "skip_reply")


if __name__ == "__main__":
    unittest.main()
