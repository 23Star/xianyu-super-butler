# -*- coding: utf-8 -*-
"""邮箱验证码与图形验证码的错误次数上限/一次性/重发作废测试。

全部使用 temp-dir DBManager 实例，不触碰真实库。
"""

import os
import tempfile
import time
import unittest

from app.db_manager import DBManager


class EmailCodeAttemptsTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.db = DBManager(os.path.join(self._temp.name, "code_test.db"))

    def tearDown(self):
        try:
            self.db.conn.close()
        finally:
            self._temp.cleanup()

    def test_correct_code_passes_once(self):
        self.db.save_verification_code("a@b.com", "123456", "register")
        self.assertTrue(self.db.verify_email_code("a@b.com", "123456", "register"))
        # 一次性：正确码第二次不再有效
        self.assertFalse(self.db.verify_email_code("a@b.com", "123456", "register"))

    def test_five_wrong_attempts_destroy_code(self):
        self.db.save_verification_code("a@b.com", "654321", "register")
        for i in range(4):
            self.assertFalse(self.db.verify_email_code("a@b.com", "000000", "register"))
        # 第 5 次错误把码销毁，此后正确码也无效
        self.assertFalse(self.db.verify_email_code("a@b.com", "000000", "register"))
        self.assertFalse(self.db.verify_email_code("a@b.com", "654321", "register"))

    def test_resend_invalidates_old_code(self):
        self.db.save_verification_code("a@b.com", "111111", "register")
        self.db.save_verification_code("a@b.com", "222222", "register")
        # 重发后旧活码失效，只有新码有效
        self.assertFalse(self.db.verify_email_code("a@b.com", "111111", "register"))
        self.assertTrue(self.db.verify_email_code("a@b.com", "222222", "register"))

    def test_expired_code_rejected(self):
        # 直接写过期时间戳模拟超时
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                "INSERT INTO email_verifications (email, code, type, expires_at, used) "
                "VALUES (?, ?, ?, ?, FALSE)",
                ("a@b.com", "333333", "register", time.time() - 1))
            self.db.conn.commit()
        self.assertFalse(self.db.verify_email_code("a@b.com", "333333", "register"))

    def test_type_isolation(self):
        self.db.save_verification_code("a@b.com", "444444", "register")
        self.assertFalse(self.db.verify_email_code("a@b.com", "444444", "login"))
        self.assertTrue(self.db.verify_email_code("a@b.com", "444444", "register"))


class CaptchaAttemptsTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.db = DBManager(os.path.join(self._temp.name, "captcha_test.db"))

    def tearDown(self):
        try:
            self.db.conn.close()
        finally:
            self._temp.cleanup()

    def test_verify_success_deletes_code(self):
        self.db.save_captcha("sess-1", "ABCD")
        self.assertTrue(self.db.verify_captcha("sess-1", "abcd"))  # 大小写不敏感
        # 一次性：同一码不能复用
        self.assertFalse(self.db.verify_captcha("sess-1", "abcd"))

    def test_five_wrong_attempts_destroy_captcha(self):
        self.db.save_captcha("sess-2", "WXYZ")
        for i in range(4):
            self.assertFalse(self.db.verify_captcha("sess-2", "AAAA"))
        # 第 5 次错误销毁，正确码也无效
        self.assertFalse(self.db.verify_captcha("sess-2", "AAAA"))
        self.assertFalse(self.db.verify_captcha("sess-2", "wxyz"))

    def test_resave_replaces_old_code(self):
        self.db.save_captcha("sess-3", "ABCD")
        self.db.save_captcha("sess-3", "EFGH")
        self.assertFalse(self.db.verify_captcha("sess-3", "abcd"))
        self.assertTrue(self.db.verify_captcha("sess-3", "efgh"))

    def test_missing_session_rejected(self):
        self.assertFalse(self.db.verify_captcha("no-such", "ABCD"))


if __name__ == "__main__":
    unittest.main()
