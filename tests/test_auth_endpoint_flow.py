# -*- coding: utf-8 -*-
"""认证端点流程测试：发码绑定图形码、注册校验、登录防爆破。

端点函数内是 `from app.db_manager import db_manager` 局部导入，
patch 模块属性即可把请求打到 temp 库，不污染真实库。
"""

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from app import reply_server
from app.db_manager import DBManager
from app.reply_server import (
    LoginRequest,
    RegisterRequest,
    SendCodeRequest,
    login,
    register,
    send_verification_code,
)


class AuthEndpointFlowTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.db = DBManager(os.path.join(self._temp.name, "flow_test.db"))
        # 每个用例独立的限流器，避免模块级单例状态串扰
        self.fresh_limiter = reply_server.email_code_send_limiter.__class__()
        self.fresh_tracker = reply_server.login_failure_tracker.__class__()
        self._patches = [
            mock.patch("app.db_manager.db_manager", self.db),
            mock.patch.object(reply_server, "email_code_send_limiter", self.fresh_limiter),
            mock.patch.object(reply_server, "login_failure_tracker", self.fresh_tracker),
        ]
        for p in self._patches:
            p.start()
        # SMTP 不真发信，直接成功
        self.db.send_verification_email = mock.AsyncMock(return_value=True)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        try:
            self.db.conn.close()
        finally:
            self._temp.cleanup()

    # ---------- send-verification-code ----------

    def test_send_code_requires_captcha_fields(self):
        resp = asyncio.run(send_verification_code(SendCodeRequest(
            email="a@b.com", type="register")))
        self.assertFalse(resp.success)
        self.assertIn("图形验证码", resp.message)

    def test_send_code_rejects_wrong_captcha_without_consuming_cooldown(self):
        self.db.save_captcha("sess-x", "ABCD")
        resp = asyncio.run(send_verification_code(SendCodeRequest(
            email="a@b.com", type="register",
            captcha_session_id="sess-x", captcha_code="ZZZZ")))
        self.assertFalse(resp.success)
        self.assertIn("图形验证码", resp.message)
        # 图形码失败不占邮箱冷却：立刻可用正确图形码再发
        self.db.save_captcha("sess-y", "EFGH")
        resp2 = asyncio.run(send_verification_code(SendCodeRequest(
            email="a@b.com", type="register",
            captcha_session_id="sess-y", captcha_code="efgh")))
        self.assertTrue(resp2.success, resp2.message)

    def test_send_code_success_sends_and_stores(self):
        self.db.save_captcha("sess-1", "ABCD")
        resp = asyncio.run(send_verification_code(SendCodeRequest(
            email="a@b.com", type="register",
            captcha_session_id="sess-1", captcha_code="abcd")))
        self.assertTrue(resp.success, resp.message)
        self.db.send_verification_email.assert_awaited_once()

    def test_send_code_cooldown_blocks_resend(self):
        self.db.save_captcha("s1", "AAAA")
        resp1 = asyncio.run(send_verification_code(SendCodeRequest(
            email="a@b.com", type="register",
            captcha_session_id="s1", captcha_code="aaaa")))
        self.assertTrue(resp1.success)
        self.db.save_captcha("s2", "BBBB")
        resp2 = asyncio.run(send_verification_code(SendCodeRequest(
            email="a@b.com", type="register",
            captcha_session_id="s2", captcha_code="bbbb")))
        self.assertFalse(resp2.success)
        self.assertIn("频繁", resp2.message)

    def test_send_code_rejects_invalid_email_format(self):
        self.db.save_captcha("s3", "CCCC")
        resp = asyncio.run(send_verification_code(SendCodeRequest(
            email="not-an-email", type="register",
            captcha_session_id="s3", captcha_code="cccc")))
        self.assertFalse(resp.success)

    def test_send_code_register_type_rejects_registered_email(self):
        self.db.create_user("exists", "a@b.com", "pass1234")
        self.db.save_captcha("s4", "DDDD")
        resp = asyncio.run(send_verification_code(SendCodeRequest(
            email="a@b.com", type="register",
            captcha_session_id="s4", captcha_code="dddd")))
        self.assertFalse(resp.success)
        self.assertIn("已被注册", resp.message)

    # ---------- register ----------

    def test_register_rejects_weak_password(self):
        resp = asyncio.run(register(RegisterRequest(
            username="weakpw", email="w@b.com", password="123")))
        self.assertFalse(resp.success)
        self.assertIn("密码", resp.message)
        # 格式错误不建用户
        self.assertIsNone(self.db.get_user_by_username("weakpw"))

    def test_register_rejects_bad_username(self):
        resp = asyncio.run(register(RegisterRequest(
            username="非法用户名", email="w@b.com", password="pass1234")))
        self.assertFalse(resp.success)
        self.assertIn("用户名", resp.message)

    def test_register_rejects_bad_email(self):
        resp = asyncio.run(register(RegisterRequest(
            username="okuser", email="bad-email", password="pass1234")))
        self.assertFalse(resp.success)
        self.assertIn("邮箱", resp.message)

    def test_register_wrong_code_creates_nothing(self):
        self.db.save_verification_code("w@b.com", "111111", "register")
        resp = asyncio.run(register(RegisterRequest(
            username="okuser", email="w@b.com",
            password="pass1234", verification_code="000000")))
        self.assertFalse(resp.success)
        self.assertIn("验证码", resp.message)
        self.assertIsNone(self.db.get_user_by_username("okuser"))

    def test_register_full_flow_succeeds(self):
        self.db.save_verification_code("ok@b.com", "222222", "register")
        resp = asyncio.run(register(RegisterRequest(
            username="okuser", email="ok@b.com",
            password="pass1234", verification_code="222222")))
        self.assertTrue(resp.success, resp.message)
        self.assertIsNotNone(self.db.get_user_by_username("okuser"))

    # ---------- login 防爆破 ----------

    def test_login_forces_captcha_after_three_failures(self):
        self.db.create_user("victim", "v@b.com", "right123")
        for i in range(3):
            resp = asyncio.run(login(LoginRequest(username="victim", password="wrong999")))
            self.assertFalse(resp.success)
            if i < 2:
                self.assertFalse(resp.captcha_required)
            else:
                self.assertTrue(resp.captcha_required)
        # 第 4 次：无图形码直接被拦，即使密码正确
        resp = asyncio.run(login(LoginRequest(username="victim", password="right123")))
        self.assertFalse(resp.success)
        self.assertTrue(resp.captcha_required)
        self.assertIn("图形验证", resp.message)
        # 带正确图形码后放行
        self.db.save_captcha("login-sess", "ABCD")
        resp = asyncio.run(login(LoginRequest(
            username="victim", password="right123",
            captcha_session_id="login-sess", captcha_code="abcd")))
        self.assertTrue(resp.success, resp.message)

    def test_login_success_resets_failure_tracker(self):
        self.db.create_user("reset1", "r@b.com", "right123")
        for _ in range(2):
            asyncio.run(login(LoginRequest(username="reset1", password="wrong999")))
        resp = asyncio.run(login(LoginRequest(username="reset1", password="right123")))
        self.assertTrue(resp.success)
        # 成功后计数清零，不再要求验证码
        self.assertFalse(self.fresh_tracker.requires_captcha("reset1"))


if __name__ == "__main__":
    unittest.main()
