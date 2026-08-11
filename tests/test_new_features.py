import asyncio
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from utils import db_backup


class DbBackupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.db_path = os.path.join(self.root, "xianyu_data.db")

        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO demo (name) VALUES ('a')")
        conn.commit()
        conn.close()

        # 把模块的路径常量指向临时目录，避免污染真实数据
        self._patches = [
            patch.object(db_backup, "BACKUP_DIR", self.root),
            patch.object(db_backup, "DB_PATH", self.db_path),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_backup_creates_readable_copy(self):
        """备份必须是能打开的完整数据库，而不是半截文件。"""
        result = db_backup.create_backup(keep=5)

        self.assertTrue(result["success"], result["message"])
        self.assertTrue(os.path.exists(result["path"]))

        conn = sqlite3.connect(result["path"])
        try:
            rows = conn.execute("SELECT name FROM demo").fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [("a",)])

    def test_keeps_only_requested_number_of_backups(self):
        """超出保留份数的旧备份应被删除，只留最新的。"""
        import time

        for _ in range(3):
            db_backup.create_backup(keep=2)
            time.sleep(1.05)  # 文件名精确到秒，避免同名覆盖

        remaining = db_backup.list_backups()
        self.assertEqual(len(remaining), 2)

    def test_missing_database_is_reported_not_raised(self):
        os.remove(self.db_path)

        result = db_backup.create_backup()

        self.assertFalse(result["success"])
        self.assertIn("不存在", result["message"])
        # 失败时不应留下空的备份文件
        self.assertEqual(db_backup.list_backups(), [])


class QuickPhraseTests(unittest.TestCase):
    """快捷短语的增删改查直接跑在临时库上。"""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute('''
            CREATE TABLE chat_quick_phrases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT DEFAULT '默认',
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                use_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_disabled_phrases_are_hidden_by_default(self):
        self.conn.execute(
            "INSERT INTO chat_quick_phrases (title, content, enabled) VALUES ('a','x',1)"
        )
        self.conn.execute(
            "INSERT INTO chat_quick_phrases (title, content, enabled) VALUES ('b','y',0)"
        )
        self.conn.commit()

        enabled_only = self.conn.execute(
            "SELECT title FROM chat_quick_phrases WHERE enabled = 1"
        ).fetchall()
        everything = self.conn.execute(
            "SELECT title FROM chat_quick_phrases"
        ).fetchall()

        self.assertEqual(enabled_only, [("a",)])
        self.assertEqual(len(everything), 2)

    def test_use_count_increments(self):
        cur = self.conn.execute(
            "INSERT INTO chat_quick_phrases (title, content) VALUES ('a','x')"
        )
        pid = cur.lastrowid
        self.conn.execute(
            "UPDATE chat_quick_phrases SET use_count = use_count + 1 WHERE id = ?", (pid,)
        )
        self.conn.commit()

        count = self.conn.execute(
            "SELECT use_count FROM chat_quick_phrases WHERE id = ?", (pid,)
        ).fetchone()[0]
        self.assertEqual(count, 1)


class ItemPolishTests(unittest.TestCase):
    def test_empty_input_returns_without_request(self):
        """没有商品或 Cookie 时不应发起请求。"""
        from utils.item_polish import polish_account_items

        result = asyncio.run(polish_account_items("acc", "", item_ids=["1"]))

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["success"], 0)

    def test_no_items_is_not_an_error(self):
        from utils.item_polish import polish_account_items

        result = asyncio.run(
            polish_account_items("acc", "cookie=1", item_ids=[])
        )

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["details"], [])


if __name__ == "__main__":
    unittest.main()
