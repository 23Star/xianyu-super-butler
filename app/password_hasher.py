# -*- coding: utf-8 -*-
"""密码哈希工具：bcrypt 为主，兼容历史无盐 SHA-256。

历史版本用无盐 SHA-256 hexdigest 存密码，可被彩虹表直接反查。
现统一改为 bcrypt（自带盐 + 慢哈希）。存量哈希不做批量迁移 ——
SHA-256 无法在不知道明文的情况下转换，只能借用户登录时的明文
透明升级（见 db_manager.verify_user_password）。

刻意不用 passlib：环境里的 passlib 1.7.4 与 bcrypt 5.x 不兼容
（bcrypt.__about__ 已移除），直接封装 bcrypt 模块更稳。

rounds 固定 10：约 50-100ms/次，弱 CPU 的 NAS 设备也可接受；
调高会拖慢每次登录，收益边际（YAGNI，不做可配）。
"""

import hashlib
import hmac

import bcrypt

BCRYPT_ROUNDS = 10

# bcrypt 算法只处理前 72 字节，超长部分静默截断会给人"密码越长越安全"
# 的错觉，这里直接拒绝并要求改用合规长度（正常路径已被校验器拦截）
_BCRYPT_MAX_PASSWORD_BYTES = 72


def is_bcrypt_hash(stored: str) -> bool:
    """判断库中哈希是否已是 bcrypt 格式。"""
    return bool(stored) and stored.startswith(("$2a$", "$2b$", "$2y$"))


def hash_password(plain: str) -> str:
    """生成 bcrypt 哈希；超过 72 字节的密码抛 ValueError。"""
    encoded = (plain or "").encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError("密码过长（超过 72 字节），请缩短后重试")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, stored: str) -> bool:
    """校验密码：bcrypt 哈希走 checkpw，遗留 SHA-256 走常数时间比较。"""
    if not stored:
        return False
    encoded = (plain or "").encode("utf-8")
    if is_bcrypt_hash(stored):
        try:
            return bcrypt.checkpw(encoded, stored.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            return False
    # 遗留无盐 SHA-256：用 hmac.compare_digest 避免时序侧信道
    legacy = hashlib.sha256(encoded).hexdigest()
    return hmac.compare_digest(legacy, stored)
