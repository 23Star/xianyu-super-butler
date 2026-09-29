# -*- coding: utf-8 -*-
"""注册/改密场景的账号字段格式校验（后端唯一真源）。

只做格式与强度校验，不查唯一性/存在性 —— 那些是数据库查询的事。
前端 frontend/lib/authValidation.ts 镜像同一套规则与文案，
让用户先在前端看到原因；这里的校验是防绕过 API 直调的最终防线。
"""

import re
from typing import Tuple

# 用户名：3-32 位字母/数字/下划线/连字符
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
# 邮箱：宽松正则（本地部分@域名.后缀），够用且不误杀合法地址
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# bcrypt 算法只处理前 72 字节，密码字节长度必须提前拦截
_PASSWORD_MAX_BYTES = 72
_PASSWORD_MAX_CHARS = 64


def validate_username(username: str) -> Tuple[bool, str]:
    """校验用户名格式。"""
    if not username or not isinstance(username, str):
        return False, "用户名不能为空"
    if not _USERNAME_PATTERN.match(username):
        return False, "用户名需为 3-32 位字母、数字、下划线或连字符"
    return True, ""


def validate_email(email: str) -> Tuple[bool, str]:
    """校验邮箱格式。"""
    if not email or not isinstance(email, str):
        return False, "邮箱不能为空"
    if len(email) > 254:
        return False, "邮箱地址过长"
    if not _EMAIL_PATTERN.match(email):
        return False, "邮箱格式不正确"
    return True, ""


def validate_password(password: str) -> Tuple[bool, str]:
    """校验密码强度：8-64 位且同时包含字母和数字。"""
    if not password or not isinstance(password, str):
        return False, "密码不能为空"
    if len(password) < 8:
        return False, "密码至少 8 位，且需同时包含字母和数字"
    if len(password) > _PASSWORD_MAX_CHARS:
        return False, f"密码最长 {_PASSWORD_MAX_CHARS} 位"
    if len(password.encode("utf-8")) > _PASSWORD_MAX_BYTES:
        return False, "密码过长（超过 72 字节），请缩短后重试"
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_letter and has_digit):
        return False, "密码至少 8 位，且需同时包含字母和数字"
    return True, ""
