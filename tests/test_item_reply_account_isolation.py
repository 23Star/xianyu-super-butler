"""商品专属回复跨账号隔离的回归测试（issue #102 后端部分）。

覆盖三个层面：
1. 自动回复链路（XianyuAutoAsync.get_default_reply）：A 账号不得串用 B 账号的
   商品专属回复；商品回复内容为空时不得覆盖账号默认回复。
2. item_replay 表迁移：历史重复行按 (cookie_id, item_id) 去重并建唯一索引，
   update_item_reply 改为 upsert 后不再产生重复行。
3. 商品回复列表：item_info 唯一键是 (cookie_id, item_id)，同 item_id 多账号
   时不得出现重复行/串标题。
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from XianyuAutoAsync import XianyuLive
from app.db_manager import DBManager

ACC_A = 'cookie-a'
ACC_B = 'cookie-b'
ITEM_1 = 'item-1001'


def make_db():
    """每个用例独立临时库，避免用例间共享状态。"""
    temp_dir = tempfile.TemporaryDirectory()
    db = DBManager(os.path.join(temp_dir.name, 'xianyu.db'))
    return temp_dir, db


def insert_item_reply(db, cookie_id, item_id, reply_content):
    db.conn.execute(
        "INSERT INTO item_replay (item_id, cookie_id, reply_content) VALUES (?, ?, ?)",
        (item_id, cookie_id, reply_content),
    )
    db.conn.commit()


def insert_default_reply(db, cookie_id, reply_content):
    db.conn.execute(
        "INSERT INTO default_replies (cookie_id, enabled, reply_content) VALUES (?, 1, ?)",
        (cookie_id, reply_content),
    )
    db.conn.commit()


class GetDefaultReplyItemIsolationTests(unittest.IsolatedAsyncioTestCase):
    """子问题1：get_default_reply 的商品专属回复必须按账号隔离。"""

    def setUp(self):
        self._temp_dir, self.db = make_db()
        self.addCleanup(self._temp_dir.cleanup)
        self.addCleanup(self.db.close)
        patcher = patch('app.db_manager.db_manager', self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def make_live(cookie_id):
        live = XianyuLive.__new__(XianyuLive)
        live.cookie_id = cookie_id
        return live

    async def test_other_account_item_reply_not_used(self):
        """B 配了商品专属回复时，A 的默认回复不得被 B 的内容顶掉。"""
        insert_item_reply(self.db, ACC_B, ITEM_1, 'B账号专属回复')
        insert_default_reply(self.db, ACC_A, 'A默认回复')

        result = await self.make_live(ACC_A).get_default_reply(
            '买家', 'buyer-1', '你好', 'chat-1', item_id=ITEM_1
        )

        self.assertIsNotNone(result)
        self.assertEqual(result['text'], 'A默认回复')

    async def test_empty_item_reply_does_not_override_default(self):
        """A 自己的商品回复内容为空时，应回退到账号默认回复而不是发空消息。"""
        insert_item_reply(self.db, ACC_B, ITEM_1, 'B账号专属回复')
        insert_item_reply(self.db, ACC_A, ITEM_1, '')
        insert_default_reply(self.db, ACC_A, 'A默认回复')

        result = await self.make_live(ACC_A).get_default_reply(
            '买家', 'buyer-1', '你好', 'chat-1', item_id=ITEM_1
        )

        self.assertIsNotNone(result)
        self.assertEqual(result['text'], 'A默认回复')

    async def test_own_item_reply_still_wins_with_placeholders(self):
        """A 自己的商品专属回复仍生效，且变量替换不被绕过。"""
        insert_item_reply(self.db, ACC_A, ITEM_1, '你好 {send_user_name}，商品{item_id}')
        insert_default_reply(self.db, ACC_A, 'A默认回复')

        result = await self.make_live(ACC_A).get_default_reply(
            '小明', 'buyer-1', '在吗', 'chat-1', item_id=ITEM_1
        )

        self.assertIsNotNone(result)
        self.assertEqual(result['text'], '你好 小明，商品' + ITEM_1)


class ItemReplayUniqueMigrationTests(unittest.TestCase):
    """子问题2：重复行去重迁移 + 唯一索引。"""

    def test_legacy_duplicates_deduped_and_unique_index_created(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, 'legacy.db')
            connection = sqlite3.connect(db_path)
            cursor = connection.cursor()
            cursor.execute(
                """
                CREATE TABLE item_replay (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    cookie_id TEXT NOT NULL,
                    reply_content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # 并发写入留下的重复行：同 (cookie_id, item_id) 两行
            cursor.execute(
                "INSERT INTO item_replay (item_id, cookie_id, reply_content, updated_at) "
                "VALUES (?, ?, ?, '2024-01-01 00:00:00')",
                (ITEM_1, ACC_A, '旧内容'),
            )
            cursor.execute(
                "INSERT INTO item_replay (item_id, cookie_id, reply_content, updated_at) "
                "VALUES (?, ?, ?, '2024-06-01 00:00:00')",
                (ITEM_1, ACC_A, '新内容'),
            )
            cursor.execute(
                "INSERT INTO item_replay (item_id, cookie_id, reply_content) VALUES (?, ?, ?)",
                ('item-2002', ACC_B, 'B的回复'),
            )
            connection.commit()
            connection.close()

            manager = DBManager(db_path)
            try:
                rows = manager.conn.execute(
                    "SELECT id, reply_content FROM item_replay WHERE cookie_id = ? AND item_id = ?",
                    (ACC_A, ITEM_1),
                ).fetchall()
                # 只保留最近写入的一条
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0], 2)
                self.assertEqual(rows[0][1], '新内容')
                # 其他账号的行不受影响
                self.assertEqual(
                    manager.conn.execute(
                        "SELECT COUNT(*) FROM item_replay WHERE cookie_id = ?", (ACC_B,)
                    ).fetchone()[0],
                    1,
                )
                # 唯一索引已建立
                index_row = manager.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_item_replay_unique'"
                ).fetchone()
                self.assertIsNotNone(index_row)
            finally:
                manager.close()

    def test_reopening_db_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, 'xianyu.db')
            manager = DBManager(db_path)
            manager.update_item_reply(ACC_A, ITEM_1, '内容')
            manager.close()

            manager = DBManager(db_path)
            try:
                count = manager.conn.execute(
                    "SELECT COUNT(*) FROM item_replay WHERE cookie_id = ? AND item_id = ?",
                    (ACC_A, ITEM_1),
                ).fetchone()[0]
                self.assertEqual(count, 1)
            finally:
                manager.close()


class UpdateItemReplyUpsertTests(unittest.TestCase):
    """子问题2：update_item_reply 改为 upsert 后的行为。"""

    def setUp(self):
        self._temp_dir, self.db = make_db()
        self.addCleanup(self._temp_dir.cleanup)
        self.addCleanup(self.db.close)

    def test_repeated_updates_keep_single_row(self):
        self.db.update_item_reply(ACC_A, ITEM_1, '第一次')
        self.db.update_item_reply(ACC_A, ITEM_1, '第二次')

        rows = self.db.conn.execute(
            "SELECT reply_content FROM item_replay WHERE cookie_id = ? AND item_id = ?",
            (ACC_A, ITEM_1),
        ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], '第二次')
        self.assertEqual(self.db.get_item_reply(ACC_A, ITEM_1)['reply_content'], '第二次')

    def test_same_item_two_accounts_stored_separately(self):
        self.db.update_item_reply(ACC_A, ITEM_1, 'A的回复')
        self.db.update_item_reply(ACC_B, ITEM_1, 'B的回复')

        self.assertEqual(self.db.get_item_reply(ACC_A, ITEM_1)['reply_content'], 'A的回复')
        self.assertEqual(self.db.get_item_reply(ACC_B, ITEM_1)['reply_content'], 'B的回复')
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM item_replay WHERE item_id = ?", (ITEM_1,)
            ).fetchone()[0],
            2,
        )


class ItemReplyListJoinTests(unittest.TestCase):
    """子问题3：同 item_id 多账号时列表 JOIN 不重复、不串标题。"""

    def setUp(self):
        self._temp_dir, self.db = make_db()
        self.addCleanup(self._temp_dir.cleanup)
        self.addCleanup(self.db.close)

    def insert_item_info(self, cookie_id, item_id, title):
        self.db.conn.execute(
            "INSERT INTO item_info (cookie_id, item_id, item_title) VALUES (?, ?, ?)",
            (cookie_id, item_id, title),
        )
        self.db.conn.commit()

    def test_same_item_two_accounts_no_duplicate_rows(self):
        self.insert_item_info(ACC_A, ITEM_1, 'A的商品标题')
        self.insert_item_info(ACC_B, ITEM_1, 'B的商品标题')
        insert_item_reply(self.db, ACC_A, ITEM_1, 'A的回复')
        insert_item_reply(self.db, ACC_B, ITEM_1, 'B的回复')

        rows_a = self.db.get_itemReplays_by_cookie(ACC_A)
        rows_b = self.db.get_itemReplays_by_cookie(ACC_B)

        self.assertEqual(len(rows_a), 1)
        self.assertEqual(rows_a[0]['item_title'], 'A的商品标题')
        self.assertEqual(rows_a[0]['reply_content'], 'A的回复')

        self.assertEqual(len(rows_b), 1)
        self.assertEqual(rows_b[0]['item_title'], 'B的商品标题')
        self.assertEqual(rows_b[0]['reply_content'], 'B的回复')

    def test_reply_without_item_info_kept_with_null_title(self):
        """商品不在 item_info（LEFT JOIN）时仍应返回该行，标题为空。"""
        insert_item_reply(self.db, ACC_A, ITEM_1, 'A的回复')

        rows = self.db.get_itemReplays_by_cookie(ACC_A)

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['item_title'])
        self.assertEqual(rows[0]['reply_content'], 'A的回复')


if __name__ == '__main__':
    unittest.main()
