"""校验并导入网页 Cookie，不在验证失败时覆盖原有账号。"""

import asyncio
import re
from typing import Optional


class CookieLoginError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def parse_login_cookie(value: str) -> dict[str, str]:
    """接受完整 Cookie 请求头；错误信息不包含任何凭据片段。"""
    if not isinstance(value, str) or not value.strip():
        raise CookieLoginError("请粘贴完整的闲鱼 Cookie")
    if len(value) > 32768 or any(ord(char) < 32 or ord(char) >= 127 for char in value):
        raise CookieLoginError("Cookie 过长或包含非法字符，请重新复制完整请求头")
    value = value.strip()
    if value.lower().startswith("cookie:"):
        value = value[7:].strip()
    fields = {}
    for part in value.split(";"):
        if not part.strip():
            continue
        name, separator, content = part.strip().partition("=")
        if (not separator or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
                or any(char in content for char in ' ",\\')):
            raise CookieLoginError("Cookie 格式不正确，请复制 Cookie 请求头的完整内容")
        if name in fields and fields[name] != content:
            raise CookieLoginError("Cookie 含有冲突字段，请重新复制")
        fields[name] = content
    if not re.fullmatch(r"[1-9][0-9]{0,23}", fields.get("unb", "")) or not fields.get("cookie2"):
        raise CookieLoginError("Cookie 缺少有效的 unb 或 cookie2，请从已登录的闲鱼网页重新复制")
    return fields


def _account_unb(value: str) -> str:
    # 旧账号可能使用自定义 ID，不能只按数据库主键识别同一闲鱼账号。
    return dict(part.strip().split("=", 1) for part in value.split(";") if "=" in part).get("unb", "")


def _resolve_account(db, user_id: int, unb: str, account_id: Optional[str]) -> tuple[str, bool]:
    cookies = db.get_all_cookies()
    matching = [key for key, value in cookies.items()
                if _account_unb(value) == unb or (key == unb and not _account_unb(value))]
    if unb in cookies and unb not in matching:
        raise CookieLoginError("账号标识与已有账号冲突，请检查已有账号配置", 409)
    if account_id is not None:
        if account_id not in cookies:
            raise CookieLoginError("该账号不存在，请刷新账号列表", 404)
        if db.get_cookie_owner_user(account_id) != user_id:
            raise CookieLoginError("无权更新该账号", 403)
        if account_id not in matching:
            raise CookieLoginError("Cookie 与当前闲鱼账号不一致，请使用该账号的 Cookie")
    if any(db.get_cookie_owner_user(key) != user_id for key in matching):
        raise CookieLoginError("该闲鱼账号已绑定其他用户", 403)
    return account_id or next(iter(matching), unb), not matching


async def verify_login_cookie(cookie: str, guard_id: str) -> str:
    """用官方当前登录用户接口校验身份，并保留响应刷新后的令牌。"""
    from utils import risk_control
    from utils.xianyu_seller_api import SellerApiError, XianyuSellerAPI

    try:
        async with XianyuSellerAPI(guard_id, cookie) as client:
            response = await asyncio.wait_for(
                client._call_buyer("mtop.taobao.idlemessage.pc.loginuser.get", {}, timeout=10),
                timeout=22,
            )
            expected = parse_login_cookie(cookie)["unb"]
            actual = str((response.get("data") or {}).get("userId") or "")
            if actual != expected:
                raise CookieLoginError("闲鱼未确认该 Cookie 的账号身份，请重新登录后复制")
            refreshed = parse_login_cookie(client.cookies_str)
            if refreshed["unb"] != expected:
                raise CookieLoginError("闲鱼返回的账号身份不一致，请重新登录后复制")
            return "; ".join(f"{key}={value}" for key, value in refreshed.items())
    except CookieLoginError:
        raise
    except risk_control.RiskControlBlocked:
        raise CookieLoginError("闲鱼要求安全验证或稍后重试，请在官方网页处理后重新复制 Cookie", 409) from None
    except SellerApiError as exc:
        if risk_control.is_risk_control_error("; ".join(exc.ret)):
            raise CookieLoginError("闲鱼要求安全验证，请在官方网页完成后重新复制 Cookie", 409) from None
        if any(marker in str(exc.ret) for marker in ("SESSION_EXPIRED", "TOKEN", "ILLEGAL_ACCESS", "VALIDATE")):
            raise CookieLoginError("Cookie 已失效或不完整，请在闲鱼网页重新登录后复制") from None
        raise CookieLoginError("闲鱼暂时无法校验登录状态，请稍后重试", 502) from None
    except Exception:
        raise CookieLoginError("连接闲鱼失败，请检查网络后重试", 502) from None


async def login_with_cookie(
    cookie: str, user_id: int, db, manager, account_id: Optional[str] = None,
) -> dict:
    if manager is None:
        raise CookieLoginError("账号服务尚未就绪，请稍后重试", 503)
    fields = parse_login_cookie(cookie)
    unb = fields["unb"]
    if account_id is not None and (not isinstance(account_id, str) or not account_id or len(account_id) > 128):
        raise CookieLoginError("账号标识不正确")
    with db.lock:
        _resolve_account(db, user_id, unb, account_id)

    normalized = "; ".join(f"{key}={value}" for key, value in fields.items())
    # 新凭据仅做一次身份校验，不受旧监听任务的冷却状态影响；校验失败仍遵守熔断。
    verified = await verify_login_cookie(normalized, f"cookie-login:{user_id}:{unb}")
    with db.lock:
        # 网络请求期间账号归属可能变化，落库前必须再次检查。
        resolved_id, is_new = _resolve_account(db, user_id, unb, account_id)
        if not db.update_cookie_account_info(resolved_id, cookie_value=verified, user_id=user_id):
            raise CookieLoginError("登录信息保存失败，请重试", 500)
        enabled = db.get_cookie_status(resolved_id)

    from utils import risk_control
    risk_control.registry.get(resolved_id).reset()
    try:
        manager.cookie_status.setdefault(resolved_id, enabled)
        operation = manager.ensure_cookie_task(
            resolved_id, verified, user_id=user_id, restart=True, save_to_db=False,
        )
        if asyncio.isfuture(operation) and operation.get_loop() is asyncio.get_running_loop():
            await operation
    except Exception:
        # Cookie 已校验并持久化，不能把启动失败误报成登录失败或监听成功。
        return {"success": True, "account_id": resolved_id, "is_new_account": is_new,
                "enabled": enabled, "connection_started": False,
                "message": "Cookie 已保存，但监听启动失败，请重新启用账号并检查账号状态"}
    return {"success": True, "account_id": resolved_id, "is_new_account": is_new,
            "enabled": enabled, "connection_started": enabled,
            "message": "Cookie 已保存，正在连接闲鱼，请查看账号状态" if enabled
            else "Cookie 已保存；该账号处于暂停状态，启用后开始监听"}
