# -*- coding: utf-8 -*-
"""SMTP 发信回归测试（issue #92）。

覆盖两处修复：
1. From 头：发件人显示名含中文时必须按 RFC 2047 编码（=?utf-8?b?...?=），
   且地址完整可解析——裸拼非 ASCII 会被 QQ 邮箱等以 550 拒收；
2. 错误分类：550 等“服务器已应答并拒信”不得误报为“无法连接”。
"""

import asyncio
import os
import re
import smtplib
import tempfile
import unittest
from email.header import decode_header, make_header
from email.utils import parseaddr
from unittest import mock

from app.db_manager import DBManager
from app.services.notification_sender import (
    NotificationNetworkError,
    NotificationProviderRejected,
    NotificationSender,
)

# issue #92 中 QQ 邮箱拒收 From 头时返回的原文
QQ_REJECT_FROM = (
    b'The "From" header is missing or invalid. '
    b'Please follow RFC5322, RFC2047, RFC822 standard protocol.'
)


def _decode_display_name(from_value: str) -> str:
    """把 From 头值中的显示名（可能是 RFC 2047 编码词）无损解码回原文。"""
    name, _addr = parseaddr(from_value)
    return str(make_header(decode_header(name))) if name else ""


class SmtpFromHeaderTests(unittest.TestCase):
    """_send_email_via_smtp 构造的 From 头必须对中文显示名做 RFC 2047 编码。"""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.db = DBManager(os.path.join(self._temp.name, "smtp_from.db"))

    def tearDown(self):
        try:
            self.db.conn.close()
        finally:
            self._temp.cleanup()

    def _sent_message(self, smtp_from: str) -> str:
        """mock SMTP 后发一封邮件，返回 sendmail 收到的完整报文。"""
        with mock.patch("smtplib.SMTP") as smtp_cls:
            instance = smtp_cls.return_value
            ok = asyncio.run(self.db._send_email_via_smtp(
                "to@qq.com", "测试主题", "正文",
                "smtp.qq.com", 587, "from@qq.com", "auth-code",
                smtp_from, True, False))
        self.assertTrue(ok)
        _user, _recipients, message = instance.sendmail.call_args[0]
        return message

    def _from_header(self, smtp_from: str) -> str:
        message = self._sent_message(smtp_from)
        return next(line for line in message.splitlines()
                    if line.startswith("From:"))[len("From:"):].strip()

    def test_chinese_display_name_is_rfc2047_encoded(self):
        # issue #92 的原始复现：显示名填中文，QQ 邮箱 550 拒收
        from_value = self._from_header("闲鱼自动回复系统")
        # 必须是 “=?utf-8?...?= <地址>” 形式：编码词在前、地址完整在外
        self.assertRegex(
            from_value,
            r"^=\?utf-8\?[bB]\?[A-Za-z0-9+/=]+\?= <from@qq\.com>$")
        # 解码后应无损还原显示名与地址（formataddr 可逆）
        self.assertEqual(parseaddr(from_value)[1], "from@qq.com")
        self.assertEqual(_decode_display_name(from_value), "闲鱼自动回复系统")

    def test_chinese_display_name_with_explicit_address(self):
        # “显示名 <地址>” 写法：地址应原样保留在编码词之外
        from_value = self._from_header("闲鱼自动回复系统 <biz@qq.com>")
        self.assertRegex(
            from_value,
            r"^=\?utf-8\?[bB]\?[A-Za-z0-9+/=]+\?= <biz@qq\.com>$")
        self.assertEqual(parseaddr(from_value)[1], "biz@qq.com")
        self.assertEqual(_decode_display_name(from_value), "闲鱼自动回复系统")

    def test_ascii_display_name_is_not_encoded(self):
        from_value = self._from_header("Xianyu Butler")
        self.assertEqual(from_value, "Xianyu Butler <from@qq.com>")
        self.assertEqual(_decode_display_name(from_value), "Xianyu Butler")

    def test_bare_address_is_used_asis(self):
        # 只填邮箱地址时不加分隔显示名，From 头保持纯地址
        self.assertEqual(self._from_header("noreply@example.com"),
                         "noreply@example.com")
        # 空 smtp_from 时由调用方回退为发件邮箱，这里同样只应是地址
        self.assertEqual(self._from_header("from@qq.com"), "from@qq.com")


class SmtpErrorClassificationTests(unittest.TestCase):
    """send_test_email 不得把 550 拒信误报为“无法连接”（issue #92 问题 2）。"""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.db = DBManager(os.path.join(self._temp.name, "smtp_err.db"))

    def tearDown(self):
        try:
            self.db.conn.close()
        finally:
            self._temp.cleanup()

    def _send_test(self, side_effect=None):
        with mock.patch("smtplib.SMTP") as smtp_cls:
            if side_effect is not None:
                smtp_cls.return_value.sendmail.side_effect = side_effect
            return asyncio.run(self.db.send_test_email(
                "to@qq.com", "smtp.qq.com", 587,
                "from@qq.com", "auth-code", "闲鱼自动回复系统", True, False))

    def test_550_rejection_reports_smtp_error_not_connection(self):
        ok, message = self._send_test(
            smtplib.SMTPDataError(550, QQ_REJECT_FROM))
        self.assertFalse(ok)
        # 必须回显 SMTP 状态码与服务器原文，且不能再说“无法连接”
        self.assertIn("SMTP 服务器返回错误", message)
        self.assertIn("550", message)
        self.assertIn("From", message)
        self.assertNotIn("无法连接", message)

    def test_550_sender_refused_reports_smtp_error(self):
        ok, message = self._send_test(
            smtplib.SMTPSenderRefused(550, b"invalid from header", "from@qq.com"))
        self.assertFalse(ok)
        self.assertIn("550 invalid from header", message)
        self.assertNotIn("无法连接", message)

    def test_auth_error_keeps_dedicated_hint(self):
        ok, message = self._send_test(
            smtplib.SMTPAuthenticationError(535, b"authentication failed"))
        self.assertFalse(ok)
        self.assertIn("认证失败", message)

    def test_connection_error_still_reports_connect_hint(self):
        # 真正的连接失败仍应提示检查地址/端口/防火墙
        for exc in (ConnectionRefusedError("refused"), TimeoutError("timed out")):
            ok, message = self._send_test(exc)
            self.assertFalse(ok)
            self.assertIn("无法连接 smtp.qq.com:587", message)


class NotificationEmailErrorTests(unittest.TestCase):
    """通知渠道邮件发送：550 拒信应归类为服务端拒绝而非网络错误。"""

    EMAIL_CONFIG = {
        "smtp_server": "smtp.example.test",
        "smtp_port": 587,
        "email_user": "sender@example.test",
        "email_password": "password",
        "recipient_email": "recipient@example.test",
    }

    def _send_with(self, exc: Exception):
        def sender(_config, _message):
            raise exc

        async def run():
            return await NotificationSender(email_sender=sender).send(
                "email", self.EMAIL_CONFIG, "test")

        return asyncio.run(run())

    def test_550_rejection_is_provider_rejected(self):
        with self.assertRaises(NotificationProviderRejected) as ctx:
            self._send_with(smtplib.SMTPDataError(550, QQ_REJECT_FROM))
        # 不是网络错误，且带上 SMTP 状态码
        self.assertNotIsInstance(ctx.exception, NotificationNetworkError)
        self.assertEqual(ctx.exception.status_code, 550)
        self.assertIn("550", ctx.exception.public_message)

    def test_recipients_refused_is_provider_rejected(self):
        with self.assertRaises(NotificationProviderRejected):
            self._send_with(
                smtplib.SMTPRecipientsRefused(
                    {"recipient@example.test": (550, b"user unknown")}))

    def test_connection_error_is_network_error(self):
        with self.assertRaises(NotificationNetworkError):
            self._send_with(ConnectionRefusedError("refused"))


if __name__ == "__main__":
    unittest.main()
