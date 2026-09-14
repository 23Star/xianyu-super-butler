"""浏览器身份（User-Agent 与 Client Hints）的单一来源。

## 为什么需要它

同一套凭证会在四个子系统里发请求，每个都自带一份硬编码头：

===========  ==========================
链路          改动前的 Chrome 版本
===========  ==========================
登录          ``120``（最旧）
令牌刷新      ``133``
心跳（WS）    ``133``
发货          ``138``
过验证码      ``138`` / ``139``
===========  ==========================

同一个账号登录时报 120、刷令牌变 133、拖滑块又变 138 —— 跨请求的指纹版本
在跳变。风控是拿会话维度做一致性校验的，这种跳变本身就是可疑信号；而
Chrome 120 已经是两年前的大版本，单独出现在登录这种最敏感的请求上。

## 做法

只保留一个版本常量，``user_agent()`` 和 ``sec_ch_ua()`` 都从它派生，
从结构上杜绝「UA 说 138、Client Hints 说 133」这类自相矛盾。

``detect_bundled_user_agent()`` 会尝试从随包 Chromium 读**实测** UA。
读到且与常量不一致时只告警、不改写返回值 —— 升级浏览器是被动的（跟着
playwright 版本走），静默跟随会让线上行为和本地测试看到的不是同一个身份。
告警的作用是把「该更新常量了」变成一条看得见的日志，而不是等风控变严了
再回来猜。
"""

from __future__ import annotations

import re
from typing import Dict, Optional

# 与随包 Chromium 对齐的 Chrome 大版本。升级 playwright（见 requirements.txt）
# 后浏览器版本会变，此时启动日志会给出实际值，改这一处即可全链路生效。
CHROME_MAJOR = "138"

_PLATFORM = "Windows"
_PLATFORM_TOKEN = "Windows NT 10.0; Win64; x64"

_USER_AGENT = (
    f"Mozilla/5.0 ({_PLATFORM_TOKEN}) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{CHROME_MAJOR}.0.0.0 Safari/537.36"
)

# Chromium 系的 GREASE 品牌。真实 Chrome 会随机化这个令牌，取值不参与校验，
# 但必须"看起来是 GREASE"而不是稳定的自定义品牌 —— 固定的非 GREASE 品牌
# 本身就是自动化特征。
_GREASE_BRAND = '"Not(A:Brand";v="99"'

_UA_MAJOR_RE = re.compile(r"(?<!Headless)Chrome/(\d+)\.", re.IGNORECASE)

# 无头标记。真实用户浏览器不会带这些字样。
HEADLESS_MARKERS = ("HeadlessChrome", "headless")


def user_agent() -> str:
    """全链路统一的 User-Agent。"""
    return _USER_AGENT


def chrome_major() -> str:
    """当前声明的 Chrome 大版本。"""
    return CHROME_MAJOR


def sec_ch_ua() -> str:
    """与 :func:`user_agent` 同版本的 ``sec-ch-ua``。

    严禁单独硬编码这个值：它和 UA 的版本号一旦不一致，服务端一眼就能看出
    Client Hints 是伪造的（真实浏览器不会自相矛盾）。
    """
    return (
        f'{_GREASE_BRAND}, "Google Chrome";v="{CHROME_MAJOR}", '
        f'"Chromium";v="{CHROME_MAJOR}"'
    )


def client_hint_headers() -> Dict[str, str]:
    """成套的 Client Hints 请求头，供各子系统直接展开。"""
    return {
        "sec-ch-ua": sec_ch_ua(),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": f'"{_PLATFORM}"',
    }


def request_headers() -> Dict[str, str]:
    """UA + Client Hints 的组合，供只缺这两项头的调用方补齐。"""
    return {"user-agent": user_agent(), **client_hint_headers()}


def parse_chrome_major(value: str) -> Optional[str]:
    """从任意 UA 字符串里解析 Chrome 大版本，解析不到返回 None。

    刻意排除 ``HeadlessChrome``：``Chrome/(\\d+)`` 会命中 ``HeadlessChrome/142.``
    里的子串，把无头浏览器误判成"版本一致"，从而漏掉真正的问题 ——
    UA 里带无头标记本身就该告警，不该被当成正常版本。
    """
    if not value:
        return None
    match = _UA_MAJOR_RE.search(str(value))
    return match.group(1) if match else None


def describe_headless_exposure(value: str) -> str:
    """UA 暴露无头标记时返回提示；正常或读不到时返回空串。

    无头 Chrome 的 UA 会写成 ``HeadlessChrome/142.0.0.0``，与真实桌面
    Chrome 的身份直接冲突。诊断里读到它说明启动参数没有去掉该标记，
    风控一眼可辨。
    """
    if not value:
        return ""
    lowered = str(value)
    for marker in HEADLESS_MARKERS:
        if marker.lower() in lowered.lower():
            return (
                f"实测 UA 暴露了无头标记（{marker}）：{str(value)[:120]}。"
                "真实用户浏览器不会带该字样，需要去掉它再对外发请求。"
            )
    return ""


def version_matches(actual_ua: str, expected_major: Optional[str] = None) -> bool:
    """实测 UA 的大版本是否与声明一致。"""
    expected = expected_major or CHROME_MAJOR
    parsed = parse_chrome_major(actual_ua)
    return parsed is not None and parsed == str(expected)


def describe_version_mismatch(actual_ua: str, expected_major: Optional[str] = None) -> str:
    """版本不一致时给一句可照做的提示；一致或解析不到时返回空串。"""
    expected = str(expected_major or CHROME_MAJOR)
    parsed = parse_chrome_major(actual_ua)
    if parsed is None:
        return ""
    if parsed == expected:
        return ""
    return (
        f"随包 Chromium 实测为 Chrome/{parsed}，"
        f"而 utils/browser_identity.py 声明的是 Chrome/{expected}。"
        f"请把 CHROME_MAJOR 改为 {parsed} —— 否则 HTTP 请求报的版本"
        f"和浏览器实际版本不一致，风控可据此识别。"
    )


def detect_bundled_user_agent(headless: bool = True) -> Optional[str]:
    """尽力从随包 Chromium 读实测 UA，失败返回 None。

    这条路径只在启动自检时走一次：读不到（没装浏览器、容器无显示）不应该
    影响主流程，因此全程吞异常。调用方拿到 None 时保持静默即可。
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                page = browser.new_page()
                return page.evaluate("() => navigator.userAgent")
            finally:
                browser.close()
    except Exception:
        return None


def describe_identity_problem(actual_ua: str, expected_major: Optional[str] = None) -> str:
    """把一次自检里能发现的身份问题合成一句提示；没问题时返回空串。

    两类问题都要报：版本与声明不一致、以及 UA 暴露无头标记。后者优先级更高 ——
    版本差一个大版本只是可疑，直接写着 HeadlessChrome 则等于自报家门。
    """
    headless = describe_headless_exposure(actual_ua)
    if headless:
        return headless
    return describe_version_mismatch(actual_ua, expected_major)


def verify_against_bundled_browser(logger=None, headless: bool = True) -> Optional[str]:
    """启动自检：比对声明版本与随包浏览器，不一致时返回提示文本。

    返回值交给调用方决定怎么呈现（打印或记日志），本函数只负责判定。
    """
    actual = detect_bundled_user_agent(headless=headless)
    if not actual:
        return None
    message = describe_identity_problem(actual)
    if message and logger is not None:
        try:
            logger.warning(message)
        except Exception:
            pass
    return message or None
