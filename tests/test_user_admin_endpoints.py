# -*- coding: utf-8 -*-
"""用户管理端点：禁用/启用、重置密码、删除的权限保护。

端点函数内是 `from app.db_manager import db_manager` 局部导入，
patch 模块属性即可生效。SESSION_TOKENS 是模块级内存表，测试注入
假 token 验证吊销，结束时清理干净。
"""

import unittest
from unittest import mock

from fastapi import HTTPException

from app.reply_server import (
    SESSION_TOKENS,
    PasswordResetIn,
    UserStatusIn,
    delete_user,
    reset_user_password,
    set_user_status,
)

ADMIN = {"user_id": 1, "username": "admin"}


def fake_user(user_id=2, username="buyer_a"):
    return {
        "id": user_id,
        "username": username,
        "email": f"{username}@x.com",
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-01 00:00:00",
    }


class UserAdminEndpointTests(unittest.TestCase):
    def setUp(self):
        self.db = mock.MagicMock()
        patcher = mock.patch("app.db_manager.db_manager", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _inject_token(self, user_id, suffix=""):
        token = f"tok-{user_id}{suffix}"
        SESSION_TOKENS[token] = {
            "user_id": user_id, "username": "u", "is_admin": False, "timestamp": 0,
        }
        self.addCleanup(SESSION_TOKENS.pop, token, None)
        return token

    # ---- set_user_status ----

    def test_status_rejects_missing_user(self):
        self.db.get_user_by_id = mock.Mock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            set_user_status(99, UserStatusIn(is_active=False), ADMIN)
        self.assertEqual(ctx.exception.status_code, 404)
        self.db.set_user_active.assert_not_called()

    def test_status_rejects_builtin_admin(self):
        self.db.get_user_by_id = mock.Mock(return_value=fake_user(1, "admin"))
        with self.assertRaises(HTTPException) as ctx:
            set_user_status(1, UserStatusIn(is_active=False), ADMIN)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("不可禁用", ctx.exception.detail)

    def test_status_updates_and_revokes_sessions(self):
        self.db.get_user_by_id = mock.Mock(return_value=fake_user())
        self.db.set_user_active = mock.Mock(return_value=True)
        self._inject_token(2)
        self._inject_token(2, "-b")

        resp = set_user_status(2, UserStatusIn(is_active=False), ADMIN)

        self.db.set_user_active.assert_called_once_with(2, False)
        self.assertEqual(resp["revoked_tokens"], 2)
        self.assertFalse(any(d["user_id"] == 2 for d in SESSION_TOKENS.values()))

    # ---- reset_user_password ----

    def test_password_rejects_weak_password(self):
        self.db.get_user_by_id = mock.Mock(return_value=fake_user())
        with self.assertRaises(HTTPException) as ctx:
            reset_user_password(2, PasswordResetIn(new_password="123"), ADMIN)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("密码", ctx.exception.detail)
        self.db.update_user_password.assert_not_called()

    def test_password_rejects_builtin_admin(self):
        self.db.get_user_by_id = mock.Mock(return_value=fake_user(1, "admin"))
        with self.assertRaises(HTTPException) as ctx:
            reset_user_password(1, PasswordResetIn(new_password="goodpass123"), ADMIN)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("系统设置", ctx.exception.detail)

    def test_password_resets_and_revokes_sessions(self):
        self.db.get_user_by_id = mock.Mock(return_value=fake_user())
        self.db.update_user_password = mock.Mock(return_value=True)
        token = self._inject_token(2)

        resp = reset_user_password(2, PasswordResetIn(new_password="goodpass123"), ADMIN)

        self.db.update_user_password.assert_called_once_with("buyer_a", "goodpass123")
        self.assertNotIn(token, SESSION_TOKENS)
        self.assertIn("强制下线", resp["message"])

    # ---- delete_user ----

    def test_delete_rejects_builtin_admin(self):
        # 另一个管理员会话试图删除内置 admin（非自己），也必须被拦下
        self.db.get_user_by_id = mock.Mock(return_value=fake_user(1, "admin"))
        with self.assertRaises(HTTPException) as ctx:
            delete_user(1, {"user_id": 2, "username": "other"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("不可删除", ctx.exception.detail)
        self.db.delete_user_and_data.assert_not_called()

    def test_delete_revokes_sessions(self):
        self.db.get_user_by_id = mock.Mock(return_value=fake_user())
        self.db.delete_user_and_data = mock.Mock(return_value=True)
        token = self._inject_token(2)

        resp = delete_user(2, ADMIN)

        self.db.delete_user_and_data.assert_called_once_with(2)
        self.assertNotIn(token, SESSION_TOKENS)
        self.assertIn("删除成功", resp["message"])


if __name__ == "__main__":
    unittest.main()
