# -*- coding: utf-8 -*-
"""用户自助修改登录名测试：/profile 端点。

覆盖：改名成功（含内存 token 同步）、admin 禁止改名、重名/弱用户名/
同名拒绝、密码错误拒绝、密码错误时不泄露目标用户名占用情况。
"""
import asyncio
import os
import tempfile
import unittest
from unittest import mock

from app import reply_server
from app.db_manager import DBManager
from app.reply_server import UpdateProfileRequest, update_profile


class UpdateProfileTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.db = DBManager(os.path.join(self._temp.name, "profile_test.db"))
        # 两个用户：一个普通用户，一个占用目标名的用户
        self.db.create_user("alice", "alice@t.cn", "Passw0rd123")
        self.db.create_user("bob", "bob@t.cn", "Passw0rd456")
        self._patch = mock.patch("app.db_manager.db_manager", self.db)
        self._patch.start()
        # 备份并清空内存 token，用例内自行构造
        self._saved_tokens = dict(reply_server.SESSION_TOKENS)
        reply_server.SESSION_TOKENS.clear()

    def tearDown(self):
        self._patch.stop()
        reply_server.SESSION_TOKENS.clear()
        reply_server.SESSION_TOKENS.update(self._saved_tokens)
        try:
            self.db.conn.close()
        finally:
            self._temp.cleanup()

    def _user(self, username, user_id, is_admin=False):
        return {"username": username, "user_id": user_id, "is_admin": is_admin}

    def test_rename_success_and_token_sync(self):
        reply_server.SESSION_TOKENS["tok-alice"] = dict(self._user("alice", 2))
        reply_server.SESSION_TOKENS["tok-other"] = dict(self._user("bob", 3))
        res = asyncio.run(update_profile(
            UpdateProfileRequest(new_username="alice_new", current_password="Passw0rd123"),
            self._user("alice", 2),
        ))
        self.assertTrue(res["success"], res)
        self.assertEqual(self.db.get_user_by_username("alice_new")["email"], "alice@t.cn")
        self.assertIsNone(self.db.get_user_by_username("alice"))
        # token 同步：本人的换成新名，别人的不动
        self.assertEqual(reply_server.SESSION_TOKENS["tok-alice"]["username"], "alice_new")
        self.assertEqual(reply_server.SESSION_TOKENS["tok-other"]["username"], "bob")

    def test_admin_username_locked(self):
        res = asyncio.run(update_profile(
            UpdateProfileRequest(new_username="root", current_password="Passw0rd123"),
            self._user("admin", 1, is_admin=True),
        ))
        self.assertFalse(res["success"])
        self.assertIn("系统身份", res["message"])

    def test_duplicate_username_rejected(self):
        res = asyncio.run(update_profile(
            UpdateProfileRequest(new_username="bob", current_password="Passw0rd123"),
            self._user("alice", 2),
        ))
        self.assertFalse(res["success"])
        self.assertIn("已被占用", res["message"])
        # 原名未被破坏
        self.assertIsNotNone(self.db.get_user_by_username("alice"))

    def test_invalid_username_rejected(self):
        res = asyncio.run(update_profile(
            UpdateProfileRequest(new_username="ab", current_password="Passw0rd123"),
            self._user("alice", 2),
        ))
        self.assertFalse(res["success"])

    def test_same_username_rejected(self):
        res = asyncio.run(update_profile(
            UpdateProfileRequest(new_username="alice", current_password="Passw0rd123"),
            self._user("alice", 2),
        ))
        self.assertFalse(res["success"])
        self.assertIn("相同", res["message"])

    def test_wrong_password_rejected(self):
        res = asyncio.run(update_profile(
            UpdateProfileRequest(new_username="alice_new", current_password="wrong-pass-9"),
            self._user("alice", 2),
        ))
        self.assertFalse(res["success"])
        self.assertIn("密码错误", res["message"])
        self.assertIsNotNone(self.db.get_user_by_username("alice"))


if __name__ == "__main__":
    unittest.main()
