"""评价/求花开关必须按账号生效。

回归的是这个故障：两个开关原先存在全局 system_settings 里，一开就是所有账号
一起开，用户无法只对部分账号启用。而这两个动作对买家有不可撤销的实际影响
（评价不可撤销、求花会发消息），误开的代价由买家侧承担。

同时固定住迁移语义：升级时用原全局值给已有账号做初值，避免行为突变；
之后新增的账号默认关闭。
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db_manager import DBManager


class PerAccountFlagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DBManager(str(Path(self.tmp.name) / 'test.db'))
        self._add_account('accA')
        self._add_account('accB')

    def tearDown(self):
        try:
            self.db.conn.close()
        finally:
            self.tmp.cleanup()

    def _add_account(self, cookie_id):
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO cookies (id, value, user_id) VALUES (?, ?, ?)",
                (cookie_id, 'k=v', 1)
            )
            self.db.conn.commit()

    def test_columns_exist_after_migration(self):
        with self.db.lock:
            cols = {r[1] for r in self.db.conn.execute("PRAGMA table_info(cookies)")}
        self.assertIn('auto_rate_enabled', cols)
        self.assertIn('auto_flower_enabled', cols)
        self.assertIn('auto_thanks_enabled', cols)

    def test_thanks_flag_is_independent(self):
        """收货致谢和另外两项互不影响。"""
        self.db.update_buyer_interaction_settings('accA', auto_thanks_enabled=True)

        flags = self.db.get_buyer_interaction_settings('accA')
        self.assertTrue(flags['auto_thanks_enabled'])
        self.assertFalse(flags['auto_rate_enabled'])
        self.assertFalse(flags['auto_flower_enabled'])
        self.assertFalse(
            self.db.get_buyer_interaction_settings('accB')['auto_thanks_enabled']
        )

    def test_thanks_defaults_off_for_new_column(self):
        """新增的开关不能因为迁移就默认打开 —— 它会给买家发消息。"""
        self.assertFalse(
            self.db.get_buyer_interaction_settings('accA')['auto_thanks_enabled']
        )

    def test_default_is_off(self):
        """有实际影响的动作默认关闭。"""
        flags = self.db.get_buyer_interaction_settings('accA')
        self.assertFalse(flags['auto_rate_enabled'])
        self.assertFalse(flags['auto_flower_enabled'])

    def test_enabling_one_account_does_not_affect_another(self):
        """这是原先全局开关的核心问题。"""
        self.db.update_buyer_interaction_settings('accA', auto_flower_enabled=True)

        self.assertTrue(self.db.get_buyer_interaction_settings('accA')['auto_flower_enabled'])
        self.assertFalse(self.db.get_buyer_interaction_settings('accB')['auto_flower_enabled'])

    def test_two_flags_are_independent(self):
        self.db.update_buyer_interaction_settings(
            'accA', auto_rate_enabled=True, auto_flower_enabled=False
        )
        flags = self.db.get_buyer_interaction_settings('accA')
        self.assertTrue(flags['auto_rate_enabled'])
        self.assertFalse(flags['auto_flower_enabled'])

    def test_partial_update_keeps_other_flag(self):
        self.db.update_buyer_interaction_settings(
            'accA', auto_rate_enabled=True, auto_flower_enabled=True
        )
        self.db.update_buyer_interaction_settings('accA', auto_flower_enabled=False)

        flags = self.db.get_buyer_interaction_settings('accA')
        self.assertTrue(flags['auto_rate_enabled'], "只改求花却把评价也关了")
        self.assertFalse(flags['auto_flower_enabled'])

    def test_all_three_can_be_set_at_once(self):
        self.db.update_buyer_interaction_settings(
            'accA', auto_rate_enabled=True, auto_flower_enabled=True,
            auto_thanks_enabled=True
        )
        flags = self.db.get_buyer_interaction_settings('accA')
        self.assertEqual(
            flags,
            {'auto_rate_enabled': True, 'auto_flower_enabled': True,
             'auto_thanks_enabled': True},
        )

    def test_unknown_account_reads_as_off(self):
        """读不到就按关闭处理 —— 不可撤销的动作不能靠猜。"""
        flags = self.db.get_buyer_interaction_settings('不存在的账号')
        self.assertFalse(flags['auto_rate_enabled'])
        self.assertFalse(flags['auto_flower_enabled'])


class LegacyGlobalInheritanceTests(unittest.TestCase):
    """升级不能悄悄改变行为：原来全局开着，升级后所有账号应继续是开着的。"""

    def test_existing_accounts_inherit_global_on(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            db_path = Path(tmp.name) / 'legacy.db'
            db = DBManager(str(db_path))

            # 造出「迁移前」的状态：删掉新列，写回旧的全局开关
            with db.lock:
                db.conn.execute("ALTER TABLE cookies RENAME TO cookies_old")
                cols = [r[1] for r in db.conn.execute("PRAGMA table_info(cookies_old)")
                        if r[1] not in ('auto_rate_enabled', 'auto_flower_enabled')]
                col_list = ','.join(cols)
                db.conn.execute(f"CREATE TABLE cookies AS SELECT {col_list} FROM cookies_old")
                db.conn.execute("DROP TABLE cookies_old")
                db.conn.execute(
                    "INSERT INTO cookies (id, value, user_id) VALUES (?, ?, ?)",
                    ('legacyAcc', 'k=v', 1))
                db.conn.commit()
            db.set_system_setting('auto_rate_enabled', 'true')
            db.set_system_setting('auto_flower_enabled', 'true')

            with db.lock:
                cursor = db.conn.cursor()
                db._migrate_buyer_interaction_per_account(cursor)
                db.conn.commit()

            flags = db.get_buyer_interaction_settings('legacyAcc')
            self.assertTrue(flags['auto_rate_enabled'], "升级后评价开关被悄悄关掉了")
            self.assertTrue(flags['auto_flower_enabled'], "升级后求花开关被悄悄关掉了")
            db.conn.close()
        finally:
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
