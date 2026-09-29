# -*- coding: utf-8 -*-
"""用户密码 bcrypt 化 + 存量 SHA-256 透明升级的数据库级测试。

全部使用 temp-dir DBManager 实例，不触碰真实库。
"""

import hashlib
import os
import sqlite3
import tempfile
import unittest

from app.db_manager import DBManager
from app.password_hasher import is_bcrypt_hash


def _get_hash(db, username):
    with db.lock:
        cursor = db.conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
    return row[0] if row else None


def _insert_legacy_sha256_user(db, username, password):
    """模拟历史版本创建的无盐 SHA-256 用户。"""
    legacy = hashlib.sha256(password.encode()).hexdigest()
    with db.lock:
        cursor = db.conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, f"{username}@example.com", legacy))
        db.conn.commit()


class UserPasswordBcryptTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.db = DBManager(os.path.join(self._temp.name, "auth_test.db"))

    def tearDown(self):
        try:
            self.db.conn.close()
        finally:
            self._temp.cleanup()

    def test_create_user_stores_bcrypt(self):
        self.assertTrue(self.db.create_user("newuser", "new@example.com", "pass1234"))
        stored = _get_hash(self.db, "newuser")
        self.assertTrue(is_bcrypt_hash(stored), stored)
        self.assertTrue(self.db.verify_user_password("newuser", "pass1234"))
        self.assertFalse(self.db.verify_user_password("newuser", "wrong9999"))

    def test_legacy_sha256_login_upgrades_transparently(self):
        _insert_legacy_sha256_user(self.db, "legacy1", "oldpass99")
        self.assertFalse(is_bcrypt_hash(_get_hash(self.db, "legacy1")))

        # 遗留哈希登录成功
        self.assertTrue(self.db.verify_user_password("legacy1", "oldpass99"))
        # 登录后哈希应已透明升级为 bcrypt
        upgraded = _get_hash(self.db, "legacy1")
        self.assertTrue(is_bcrypt_hash(upgraded), upgraded)
        # 升级后再次登录仍成功（走 bcrypt 分支）
        self.assertTrue(self.db.verify_user_password("legacy1", "oldpass99"))

    def test_legacy_wrong_password_not_upgraded(self):
        _insert_legacy_sha256_user(self.db, "legacy2", "right123")
        self.assertFalse(self.db.verify_user_password("legacy2", "wrong123"))
        # 验证失败不触发升级
        self.assertFalse(is_bcrypt_hash(_get_hash(self.db, "legacy2")))

    def test_update_password_stores_bcrypt(self):
        _insert_legacy_sha256_user(self.db, "legacy3", "oldpass77")
        self.db.update_user_password("legacy3", "newpass88")
        stored = _get_hash(self.db, "legacy3")
        self.assertTrue(is_bcrypt_hash(stored))
        self.assertFalse(self.db.verify_user_password("legacy3", "oldpass77"))
        self.assertTrue(self.db.verify_user_password("legacy3", "newpass88"))

    def test_overlong_legacy_password_still_logs_in_without_upgrade(self):
        # 75 字节的遗留密码：SHA-256 可正常验证，但无法升级为 bcrypt
        long_pw = "密" * 25
        _insert_legacy_sha256_user(self.db, "legacy4", long_pw)
        self.assertTrue(self.db.verify_user_password("legacy4", long_pw))
        # 升级失败不影响登录，哈希保持遗留格式
        self.assertFalse(is_bcrypt_hash(_get_hash(self.db, "legacy4")))

    def test_admin_initial_password_is_bcrypt(self):
        # 全新库在 update_admin_user_id 里初始化的 admin 应直接是 bcrypt
        stored = _get_hash(self.db, "admin")
        self.assertIsNotNone(stored)
        self.assertTrue(is_bcrypt_hash(stored), stored)

    def test_inactive_user_cannot_login(self):
        self.db.create_user("blocked", "b@example.com", "pass1234")
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute("UPDATE users SET is_active = FALSE WHERE username = ?", ("blocked",))
            self.db.conn.commit()
        self.assertFalse(self.db.verify_user_password("blocked", "pass1234"))


if __name__ == "__main__":
    unittest.main()
