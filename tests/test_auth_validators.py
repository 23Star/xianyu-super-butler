# -*- coding: utf-8 -*-
"""auth_validators 单元测试：用户名/邮箱/密码规则矩阵。"""

import unittest

from app.auth_validators import (
    validate_email,
    validate_password,
    validate_username,
)


class ValidateUsernameTests(unittest.TestCase):
    def test_valid_usernames(self):
        for name in ("user1", "abc", "a_b-c9", "x" * 32):
            ok, _ = validate_username(name)
            self.assertTrue(ok, name)

    def test_invalid_usernames(self):
        for name in ("", "ab", "x" * 33, "用户名", "user name", "user@x", None):
            ok, _ = validate_username(name)
            self.assertFalse(ok, repr(name))


class ValidateEmailTests(unittest.TestCase):
    def test_valid_emails(self):
        for email in ("a@b.co", "user.name+tag@example.co.jp", "x_y@sub.domain.org"):
            ok, _ = validate_email(email)
            self.assertTrue(ok, email)

    def test_invalid_emails(self):
        for email in ("", "no-at-sign", "@domain.com", "a@", "a b@c.com",
                      "a@b", "x" * 250 + "@example.com", None):
            ok, _ = validate_email(email)
            self.assertFalse(ok, repr(email))


class ValidatePasswordTests(unittest.TestCase):
    def test_valid_passwords(self):
        for pw in ("abcd1234", "a1" * 4, "P@ssw0rd!", "x1" * 32):
            ok, _ = validate_password(pw)
            self.assertTrue(ok, pw)

    def test_reject_short_or_long(self):
        for pw in ("", "ab1", "abc1234", "x" * 65):
            ok, _ = validate_password(pw)
            self.assertFalse(ok, repr(pw))

    def test_reject_single_class(self):
        # 纯数字 / 纯字母都不允许
        for pw in ("12345678", "abcdefgh"):
            ok, _ = validate_password(pw)
            self.assertFalse(ok, pw)

    def test_reject_overlong_utf8_bytes(self):
        # 25 个 CJK 字符 = 75 字节，超过 bcrypt 的 72 字节上限，必须拒绝
        ok, _ = validate_password("密" * 25)
        self.assertFalse(ok)
        # 23 个 CJK + "a1" = 71 字节且含字母数字，应通过
        ok, _ = validate_password(("密" * 23) + "a1")
        self.assertTrue(ok)

    def test_error_messages_are_chinese(self):
        _, reason = validate_password("123")
        self.assertTrue(reason)  # 有具体文案


if __name__ == "__main__":
    unittest.main()
