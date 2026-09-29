# -*- coding: utf-8 -*-
"""测试发信端点：表单值校验、参数透传与失败原因回传。

端点函数内是 `from app.db_manager import db_manager` 局部导入，
patch 模块属性即可把请求打到 temp 库，不污染真实库。
"""

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from app.db_manager import DBManager
from app.reply_server import EmailTestIn, send_email_test


class EmailTestEndpointTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.db = DBManager(os.path.join(self._temp.name, "email_test.db"))
        # SMTP 不真发信，默认成功；个别用例自行改返回值
        self.db.send_test_email = mock.AsyncMock(return_value=(True, "测试邮件已发送"))
        patcher = mock.patch("app.db_manager.db_manager", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        try:
            self.db.conn.close()
        finally:
            self._temp.cleanup()

    def _call(self, **payload):
        return asyncio.run(send_email_test(EmailTestIn(**payload), mock.Mock()))

    def test_rejects_invalid_recipient(self):
        resp = self._call(to="not-an-email", smtp_server="smtp.qq.com", smtp_port=587,
                          smtp_user="a@qq.com", smtp_password="code")
        self.assertFalse(resp["success"])
        self.assertIn("收件邮箱", resp["message"])
        self.db.send_test_email.assert_not_awaited()

    def test_rejects_incomplete_smtp_fields(self):
        resp = self._call(to="a@b.com", smtp_server="", smtp_port=0,
                          smtp_user="", smtp_password="")
        self.assertFalse(resp["success"])
        self.assertIn("完整填写", resp["message"])
        self.db.send_test_email.assert_not_awaited()

    def test_forwards_form_values_with_saved_tls_flags(self):
        # TLS/SSL 不在表单里，应沿用库里的设置（默认 TLS 开、SSL 关）
        self.db.get_system_setting = mock.Mock(side_effect=lambda key: {
            "smtp_use_tls": "true", "smtp_use_ssl": "false"}.get(key))
        resp = self._call(to="a@b.com", smtp_server="smtp.qq.com", smtp_port=465,
                          smtp_user="a@qq.com", smtp_password="auth-code",
                          smtp_from="")
        self.assertTrue(resp["success"])
        self.db.send_test_email.assert_awaited_once_with(
            "a@b.com", "smtp.qq.com", 465, "a@qq.com", "auth-code",
            "a@qq.com",  # smtp_from 为空时回退到发件邮箱
            True, False)

    def test_passes_failure_reason_through(self):
        self.db.send_test_email = mock.AsyncMock(
            return_value=(False, "SMTP 认证失败：请核对发件邮箱与密码/授权码"))
        resp = self._call(to="a@b.com", smtp_server="smtp.qq.com", smtp_port=587,
                          smtp_user="a@qq.com", smtp_password="bad")
        self.assertFalse(resp["success"])
        self.assertIn("认证失败", resp["message"])


if __name__ == "__main__":
    unittest.main()
