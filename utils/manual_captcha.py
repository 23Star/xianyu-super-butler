"""人工完成滑块验证。

实测发现自动识别已经能把滑块拖到目标位置（误差 0.3px 以内），但服务端仍
判定失败 —— 拦的是行为特征而不是位置精度，因此继续加大自动重试不会有结果。

项目里本来就有远程控制通道（``utils.captcha_remote_control`` 负责推屏和
转发鼠标事件，``static/captcha_control.html`` 是操作页面），但一直没有代码
调用它。这个模块把它接起来：打开登录页，等人在浏览器里完成验证，然后取回
新的 Cookie。

与 ``utils.xianyu_slider_stealth`` 的区别是那边用同步 Playwright，无法和
异步的远程通道共享 page 对象，所以这里独立起一个异步浏览器。
"""

import asyncio
import time
from typing import Any, Dict, Optional

from loguru import logger
from utils import browser_limit

LOGIN_URL = "https://www.goofish.com/"

# 人工操作需要时间，但也不能无限占用浏览器
DEFAULT_TIMEOUT = 300

# 等待滑块真正出现的最长时间（秒）。惩罚页加载本身就要几秒，
# 等不到说明 x5secdata 已失效或该账号当前已不在风控状态。
CAPTCHA_PRESENT_TIMEOUT = 20


def get_verification_url(cookie_id: str) -> Optional[str]:
    """从风控日志里取该账号最近一次滑块惩罚的 URL。

    惩罚 URL（``...punish?x5secdata=...&x5step=2&action=captcha``）是 Token
    刷新响应里 ``data.url`` 返回的，写进了 ``risk_control_logs.event_description``。
    只有导航到这个 URL 才会真正弹出滑块 —— 导航首页（原实现的 LOGIN_URL）不会。

    x5secdata 有有效期（约 1 小时），过期后导航会跳到空白页。所以这里只是
    兜底：会话内若触发实时 Token 刷新拿到新 URL 更好，拿不到才用它。
    """
    import re
    import sqlite3
    from app.db_manager import db_manager

    try:
        with db_manager.lock:
            cur = db_manager.conn.cursor()
            cur.execute(
                "SELECT event_description FROM risk_control_logs "
                "WHERE cookie_id=? AND event_type='slider_captcha' "
                "ORDER BY id DESC LIMIT 1",
                (cookie_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.debug(f"【{cookie_id}】读取惩罚 URL 失败: {exc}")
        return None

    if not row or not row[0]:
        return None
    m = re.search(r"URL: (\S+)", row[0])
    url = m.group(1) if m else None
    if url and ("punish" in url or "action=captcha" in url):
        logger.info(f"【{cookie_id}】从风控日志取到惩罚 URL")
        return url
    return None


async def _fetch_live_verification_url(cookie_id: str, cookies_str: str) -> Optional[str]:
    """主动触发一次 Token 刷新，从响应里拿新鲜的惩罚 URL。

    账号处于风控时，``mtop.taobao.idlemessage.pc.login.token`` 接口会在
    ``data.url`` 返回滑块惩罚页地址；账号正常时返回 accessToken，没有该字段。

    这里只读 URL、**不调用** XianyuLive 的自动解滑块流程（那条路径实测失败），
    避免在人工处理前又被自动重试一遍。
    """
    import json
    import time
    import aiohttp
    from app.config import API_ENDPOINTS
    from utils.xianyu_utils import trans_cookies, generate_sign, generate_device_id

    try:
        cd = trans_cookies(cookies_str)
        if "_m_h5_tk" not in cd:
            return None
        token = cd["_m_h5_tk"].split("_")[0]
        if not token:
            return None

        ts = str(int(time.time() * 1000))
        params = {
            "jsv": "2.7.2", "appKey": "34839810", "t": ts, "sign": "", "v": "1.0",
            "type": "originaljson", "accountSite": "xianyu", "dataType": "json",
            "timeout": "20000", "api": "mtop.taobao.idlemessage.pc.login.token",
            "sessionOption": "AutoLoginOnly",
            "dangerouslySetWindvaneParams": "%5Bobject%20Object%5D",
            "smToken": "token", "queryToken": "sm", "sm": "sm",
            "spm_cnt": "a21ybx.im.0.0", "spm_pre": "a21ybx.home.sidebar.1.4c053da6vYwnmf",
            "log_id": "4c053da6vYwnmf",
        }
        device_id = generate_device_id(cd.get("unb", ""))
        data_val = json.dumps(
            {"appKey": "444e9908a51d1cb236a27862abc769c9", "deviceId": device_id}
        )
        params["sign"] = generate_sign(params["t"], token, data_val)

        headers = {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/139.0.0.0 Safari/537.36"
            ),
            "referer": "https://www.goofish.com/",
            "origin": "https://www.goofish.com",
            "cookie": cookies_str,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                API_ENDPOINTS.get("token"),
                params=params,
                data={"data": data_val},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                payload = json.loads(text)
                ret = payload.get("ret", [])
                if any("SUCCESS" in str(r) for r in ret):
                    # 成功返回 accessToken —— 账号当前不在风控，无惩罚页
                    return None
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                url = data.get("url")
                if url and ("punish" in url or "action=captcha" in url):
                    logger.info(f"【{cookie_id}】实时刷新拿到惩罚 URL")
                    return url
        return None
    except Exception as exc:
        logger.debug(f"【{cookie_id}】实时获取惩罚 URL 失败: {exc}")
        return None


async def open_manual_session(
    cookie_id: str,
    cookies_str: str,
    timeout: int = DEFAULT_TIMEOUT,
    headless: bool = True,
) -> Dict[str, Any]:
    """打开一个人工验证会话，等待人在浏览器里完成滑块。

    Args:
        timeout: 等待人工操作的秒数，超时后放弃并关闭浏览器。
        headless: 默认无头 —— 页面通过远程通道推给用户，不需要本地窗口。

    Returns:
        ``{"success": bool, "cookies_str": str, "message": str, "session_id": str}``。
        成功时 ``cookies_str`` 是完成验证后的新 Cookie，调用方应保存。
    """
    from playwright.async_api import async_playwright

    from utils.captcha_remote_control import captcha_controller

    session_id = str(cookie_id)
    result: Dict[str, Any] = {
        "success": False,
        "cookies_str": cookies_str,
        "message": "",
        "session_id": session_id,
    }

    playwright = None
    browser = None
    context = None
    refresh_task = None
    try:
        playwright = await async_playwright().start()
        browser = await browser_limit.launch_browser(
            playwright,
            {'headless': headless, 'args': [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]},
            "人工验证码",
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
        )

        if cookies_str:
            await context.add_cookies(_to_playwright_cookies(cookies_str))

        page = await context.new_page()

        # 惩罚页 URL 优先：只有导航到它才会弹出滑块。
        # 原实现导航到闲鱼首页，首页没有滑块 → check_completion 立刻误判
        # “已完成” → 浏览器秒关，用户连上控制页时会话已不存在。
        #
        # 先触发一次实时 Token 刷新拿最新 URL（账号正在风控才返回）；拿不到
        # 再退回 DB 里最近一次惩罚 URL（可能已过期，等滑块时会发现）。
        verification_url = await _fetch_live_verification_url(cookie_id, cookies_str)
        if not verification_url:
            verification_url = get_verification_url(cookie_id)
        if not verification_url:
            result["message"] = "未找到该账号的滑块惩罚 URL，无法开启人工验证"
            logger.warning(f"【{cookie_id}】{result['message']}")
            return result

        try:
            await page.goto(verification_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            logger.warning(f"【{cookie_id}】导航惩罚页失败: {exc}")
        # 给验证组件一点渲染时间，否则截图可能是空白
        await asyncio.sleep(2)

        # 等滑块真正出现再建会话 —— 找不到滑块说明 x5secdata 已失效，
        # 此时即使建了会话也拖不出结果，尽早告知用户更合适。
        captcha_appeared = await _wait_for_captcha_present(page, timeout=CAPTCHA_PRESENT_TIMEOUT)
        if not captcha_appeared:
            result["message"] = (
                "已导航到惩罚页但未检测到滑块（x5secdata 可能已过期），"
                "请让账号重新触发风控后重试"
            )
            logger.warning(f"【{cookie_id}】{result['message']}")
            return result

        await captcha_controller.create_session(session_id, page)
        # 持续推送截图，让用户能看到自己的拖动效果
        refresh_task = asyncio.create_task(
            captcha_controller.auto_refresh_screenshot(session_id, interval=1.0)
        )

        logger.warning(
            f"【{cookie_id}】已开启人工验证会话，请在 {timeout} 秒内于"
            f" /static/captcha_control.html?session={session_id} 完成验证"
        )

        # 关键：会话期间浏览器必须保持存活，等用户拖完才返回。
        # 原实现在这里死等 timeout，且 check_completion 在无滑块时误判完成
        # 直接秒关 —— 改为“滑块出现后，持续等待它消失（完成）或超时”。
        deadline = time.monotonic() + timeout
        completed = False
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            try:
                if await captcha_controller.check_completion(session_id):
                    completed = True
                    break
            except Exception as exc:
                logger.debug(f"【{cookie_id}】检查验证完成状态失败: {exc}")

        if not completed:
            result["message"] = f"人工验证超时（{timeout} 秒内未完成）"
            logger.warning(f"【{cookie_id}】{result['message']}")
            return result

        new_cookies = _from_playwright_cookies(await context.cookies())
        if not new_cookies:
            result["message"] = "验证已完成但未取到 Cookie"
            return result

        result["success"] = True
        result["cookies_str"] = new_cookies
        result["message"] = "人工验证完成"
        logger.info(f"【{cookie_id}】人工验证完成，已取得新 Cookie")
        return result
    except Exception as exc:
        result["message"] = f"人工验证会话异常: {exc}"
        logger.error(f"【{cookie_id}】{result['message']}")
        return result
    finally:
        if refresh_task and not refresh_task.done():
            refresh_task.cancel()
        try:
            from utils.captcha_remote_control import captcha_controller

            await captcha_controller.close_session(session_id)
        except Exception:
            pass
        for closer in (context, browser):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:
                    pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass


async def _wait_for_captcha_present(page, timeout: int = CAPTCHA_PRESENT_TIMEOUT) -> bool:
    """等页面里出现可见的滑块/验证码元素。

    原实现不区分“页面没有滑块”和“滑块验证完成” —— 首页没滑块，于是
    check_completion 误判完成。这里显式等滑块出现，避免把“没弹出滑块”
    当成“已完成”。
    """
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError  # noqa: F401

    # 与 captcha_remote_control.check_completion 用同一组选择器，保证判断一致
    selectors = [
        "#nocaptcha",
        "#scratch-captcha-btn",
        ".scratch-captcha-container",
        ".scratch-captcha-slider",
        '[id*="captcha"]',
        ".nc-container",
    ]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # 先查主页面，再查 iframe（阿里滑块通常包在 iframe 里）
        for frame in page.frames:
            for selector in selectors:
                try:
                    element = await frame.query_selector(selector)
                    if element and await element.is_visible():
                        logger.info(f"检测到滑块元素: {selector} (frame: {frame.url[:80]})")
                        return True
                except Exception:
                    continue
        await asyncio.sleep(1)
    return False


def _to_playwright_cookies(cookies_str: str) -> list:
    """把 Cookie 字符串转成 Playwright 需要的结构。"""
    cookies = []
    for part in cookies_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": ".goofish.com",
            "path": "/",
        })
    return cookies


def _from_playwright_cookies(cookies: list) -> str:
    """把 Playwright 的 Cookie 列表拼回字符串。"""
    pairs = []
    for cookie in cookies or []:
        name = cookie.get("name")
        if not name:
            continue
        pairs.append(f"{name}={cookie.get('value', '')}")
    return "; ".join(pairs)
