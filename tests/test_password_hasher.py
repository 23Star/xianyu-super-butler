# -*- coding: utf-8 -*-
"""password_hasher 单元测试：bcrypt 生成/校验 + 遗留 SHA-256 兼容路由。"""

import hashlib
import unittest

from app.password_hasher import (
    BCRYPT_ROUNDS,
    hash_password,
    is_bcrypt_hash,
    verify_password,
)


class PasswordHasherTests(unittest.TestCase):
    def test_hash_produces_bcrypt_format(self):
        stored = hash_password("secret123")
        self.assertTrue(stored.startswith("$2"))
        self.assertIn(f"$2b${BCRYPT_ROUNDS}$", stored)
        self.assertTrue(is_bcrypt_hash(stored))

    def test_hash_is_salted(self):
        # 同一密码两次哈希应产生不同结果（随机盐）
        self.assertNotEqual(hash_password("secret123"), hash_password("secret123"))

    def test_verify_bcrypt_true_false(self):
        stored = hash_password("secret123")
        self.assertTrue(verify_password("secret123", stored))
        self.assertFalse(verify_password("wrong1234", stored))

    def test_verify_legacy_sha256(self):
        legacy = hashlib.sha256("oldpass1".encode()).hexdigest()
        self.assertFalse(is_bcrypt_hash(legacy))
        self.assertTrue(verify_password("oldpass1", legacy))
        self.assertFalse(verify_password("wrong1234", legacy))

    def test_overlong_password_rejected(self):
        # bcrypt 只处理 72 字节，超长必须显式拒绝而非静默截断
        with self.assertRaises(ValueError):
            hash_password("x" * 73)

    def test_verify_with_empty_or_corrupt_hash(self):
        self.assertFalse(verify_password("anypass1", ""))
        self.assertFalse(verify_password("anypass1", None))
        # 格式损坏的 bcrypt 串不抛异常
        self.assertFalse(verify_password("anypass1", "$2b$10$corrupted"))


if __name__ == "__main__":
    unittest.main()
