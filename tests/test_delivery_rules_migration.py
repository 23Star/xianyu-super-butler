import os
import sqlite3
import tempfile
import unittest

from app.db_manager import DBManager


class DeliveryRulesMigrationTests(unittest.TestCase):
    def test_adds_user_id_when_version_is_already_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "legacy.db")
            connection = sqlite3.connect(db_path)
            cursor = connection.cursor()
            cursor.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO users (username, email, password_hash, role)
                VALUES ('admin', 'admin@localhost', 'hash', 'admin')
                """
            )
            cursor.execute(
                """
                CREATE TABLE system_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO system_settings (key, value, description)
                VALUES ('db_version', '1.5', 'database version')
                """
            )
            cursor.execute(
                """
                CREATE TABLE delivery_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    card_id INTEGER NOT NULL
                )
                """
            )
            cursor.execute(
                "INSERT INTO delivery_rules (keyword, card_id) VALUES ('test-product', 1)"
            )
            connection.commit()
            connection.close()

            manager = DBManager(db_path)
            try:
                columns = {
                    row[1]
                    for row in manager.conn.execute("PRAGMA table_info(delivery_rules)")
                }
                migrated_user_id = manager.conn.execute(
                    "SELECT user_id FROM delivery_rules WHERE keyword = 'test-product'"
                ).fetchone()[0]
            finally:
                manager.close()

            for column_name in (
                "user_id",
                "cookie_id",
                "item_id",
                "delivery_count",
                "enabled",
                "description",
                "delivery_times",
                "created_at",
                "updated_at",
            ):
                self.assertIn(column_name, columns)
            self.assertEqual(migrated_user_id, 1)


if __name__ == "__main__":
    unittest.main()
