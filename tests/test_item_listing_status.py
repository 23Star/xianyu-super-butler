"""商品上下架状态的校准。

回归的是这个故障：商品同步只做 upsert，从不处理「闲鱼接口已经不再返回」的
商品，item_info 表里也没有状态字段。于是下架或删除的商品永久留在列表里，和
在售的长得一模一样 —— 实测账号有 4 行，接口只返回 3 件，第 4 件是上一次同步
的残留，用户既分不清也筛不掉。

校准只标记、不删除：专属发货配置挂在商品上，删行会一起丢掉，而且闲鱼接口
偶发少返回时会造成不可恢复的误删。
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db_manager import DBManager


class ListingStatusReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / 'test.db'
        self.db = DBManager(str(db_path))
        self._seed()

    def tearDown(self):
        try:
            self.db.conn.close()
        finally:
            self.tmp.cleanup()

    def _seed(self):
        with self.db.lock:
            cur = self.db.conn.cursor()
            for item_id, title in (
                ('1043469615818', '小乔时之魔女无双皮肤'),
                ('1057192381080', '塑形裤'),
                ('1073831031460', '111'),
                ('1075711813212', '111'),
            ):
                cur.execute(
                    "INSERT INTO item_info (cookie_id, item_id, item_title) VALUES (?, ?, ?)",
                    ('acc', item_id, title),
                )
            self.db.conn.commit()

    def _status(self, item_id):
        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute(
                "SELECT listing_status FROM item_info WHERE cookie_id = ? AND item_id = ?",
                ('acc', item_id),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def _count(self):
        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM item_info WHERE cookie_id = ?", ('acc',))
            return cur.fetchone()[0]

    def test_migration_added_columns(self):
        with self.db.lock:
            cols = {r[1] for r in self.db.conn.execute("PRAGMA table_info(item_info)")}
        self.assertIn('listing_status', cols)
        self.assertIn('last_seen_at', cols)

    def test_missing_item_is_marked_off_shelf(self):
        stats = self.db.reconcile_item_listing_status(
            'acc', ['1043469615818', '1057192381080', '1073831031460']
        )

        self.assertEqual(stats['off_shelf'], 1)
        self.assertEqual(self._status('1075711813212'), 'off_shelf')
        for still_listed in ('1043469615818', '1057192381080', '1073831031460'):
            self.assertEqual(self._status(still_listed), 'on_sale')

    def test_nothing_is_deleted(self):
        """专属发货配置挂在商品上，行不能消失。"""
        self.db.reconcile_item_listing_status('acc', ['1043469615818'])
        self.assertEqual(self._count(), 4)

    def test_relisted_item_returns_to_on_sale(self):
        self.db.reconcile_item_listing_status('acc', ['1043469615818'])
        self.assertEqual(self._status('1075711813212'), 'off_shelf')

        self.db.reconcile_item_listing_status('acc', ['1043469615818', '1075711813212'])
        self.assertEqual(self._status('1075711813212'), 'on_sale')

    def test_last_seen_at_is_refreshed(self):
        self.db.reconcile_item_listing_status('acc', ['1043469615818'])
        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute(
                "SELECT last_seen_at FROM item_info WHERE cookie_id = ? AND item_id = ?",
                ('acc', '1043469615818'),
            )
            seen = cur.fetchone()[0]
        self.assertIsNotNone(seen)

    def test_already_off_shelf_is_not_recounted(self):
        """重复同步不该把同一件商品反复计成「新下架」。"""
        first = self.db.reconcile_item_listing_status('acc', ['1043469615818'])
        second = self.db.reconcile_item_listing_status('acc', ['1043469615818'])

        self.assertEqual(first['off_shelf'], 3)
        self.assertEqual(second['off_shelf'], 0)

    def test_empty_list_marks_everything_off_shelf(self):
        """接口确认为空时全部下架 —— 调用方必须先用 confirmed_empty 把关。"""
        stats = self.db.reconcile_item_listing_status('acc', [])

        self.assertEqual(stats['off_shelf'], 4)
        self.assertEqual(self._count(), 4)

    def test_other_account_is_untouched(self):
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO item_info (cookie_id, item_id, item_title) VALUES (?, ?, ?)",
                ('other', '999', '别的账号的商品'),
            )
            self.db.conn.commit()

        self.db.reconcile_item_listing_status('acc', [])

        with self.db.lock:
            cur = self.db.conn.cursor()
            cur.execute(
                "SELECT listing_status FROM item_info WHERE cookie_id = ? AND item_id = ?",
                ('other', '999'),
            )
            self.assertEqual(cur.fetchone()[0], 'on_sale')


if __name__ == '__main__':
    unittest.main()
