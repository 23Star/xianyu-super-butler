"""滑块验证的严格判定规则（对照 Ydisks 的生产契约重写）。

原实现把「滑块视觉上过了」当成通过，留下三个真实故障：

1. **旧 `x5sec` 被当成成功。** Cookie 里本来就有上次通过留下的 `x5sec`，
   只要判定「x5* 存在」就永远为真。表现为滑块拖过去了、页面也变了，
   账号却继续 `FAIL_SYS_USER_VALIDATE`（对应仓库 Issue #62）。
2. **过期的惩罚链接还在用。** `punish?x5secdata=...` 是一次性的、约 1 小时失效。
   过期后打开只会看到「抱歉，页面访问出现了问题」，用旧链接兜底等于白跑一次，
   还会因为反复访问验证页加重风控。
3. **同名 Cookie 被压成一个值。** `x5sec` 由 `h5api.m.goofish.com` 子域下发，
   与 `.goofish.com` 上的同名 Cookie 并存。扁平字典合并会丢掉域信息，
   把旧的覆盖上去（或反过来），服务端看到的仍是未通过状态。

所以这里把通过条件写成显式的三条，缺一不可：

- 浏览器上下文里出现了**相对拖动前快照全新的、非空的** `x5sec`；
- 当前页面**已经离开** punish/captcha URL；
- 合并回账号时按**域优先级**取新签发的那个值，并清掉挑战标记。

`.nc-container` 消失、滑块隐藏、成功图标出现都不能单独证明通过 —— 它们只说明
前端组件收起了，不代表服务端放行。
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

# punish 页 URL 的特征片段。任一命中说明服务端还没放行。
PUNISH_URL_MARKERS = (
    "punish",
    "x5step=2",
    "action=captcha",
    "purecaptcha",
    "/captcha",
)

# 惩罚链接失效时闲鱼返回的整页文案。命中说明 x5secdata 已过期。
EXPIRED_PAGE_MARKERS = (
    "抱歉，页面访问出现了问题",
    "抱歉,页面访问出现了问题",
)

# 页面没有任何可操作滑块、只显示错误时的文案。
# 这类页面继续 reload / 拖动 / 换引擎都没有意义，只会增加风控。
DIRECT_ERROR_MARKERS = (
    "验证失败",
    "安全验证未通过",
    "请求失败",
    "加载失败",
    "系统繁忙",
    "服务异常",
    "网络异常",
    "页面异常",
    "页面出错",
    "发生错误",
    "请稍后重试",
    "something's wrong",
    "something went wrong",
    "please refresh and try again",
    "try again later",
)

# 挑战标记：表示「这个请求还有一道验证没做完」。拿到 x5sec 后必须清掉，
# 否则闲鱼认为挑战仍未完成，继续返回 FAIL_SYS_USER_VALIDATE。
CHALLENGE_COOKIE_NAMES = ("x5secdata", "x5sectag", "x5step")

# `x5sec` 的实际签发域。域越具体越优先：合并同名 Cookie 时必须让子域的新值胜出。
DOMAIN_PRIORITY = (
    "h5api.m.goofish.com",
    ".h5api.m.goofish.com",
    ".goofish.com",
    "goofish.com",
    ".taobao.com",
)


def _lower(value) -> str:
    return str(value or "").strip().lower()


def is_x5_cookie_name(name: str) -> bool:
    """是否是 x5 系列 Cookie（含 x5sec / x5secdata / x5sectag / x5step）。"""
    lowered = _lower(name)
    return lowered.startswith("x5") or "x5sec" in lowered


def is_challenge_cookie_name(name: str) -> bool:
    """是否是「挑战标记」（不是通行凭证）。"""
    return _lower(name) in CHALLENGE_COOKIE_NAMES


def collect_x5sec_values(cookies) -> Dict[str, str]:
    """收集一份 Cookie 集合里所有非空的 `x5sec` 值。

    返回 ``{name: value}``。三种输入都接受：Playwright 的 Cookie 对象列表、
    普通字典列表，以及 ``"k=v; k2=v2"`` 字符串。这样调用方可以随手把
    ``self.cookies_str`` 或 ``context.cookies()`` 丢进来。

    字符串这条路径是必需的：如果只遍历字符串，会逐个字符走一遍并全部落空，
    静默返回空集合 —— 于是「必须是新 x5sec」退化成「有 x5sec 就算通过」，
    正好把这个模块要修的故障原样放回来。
    """
    if isinstance(cookies, (str, bytes)):
        cookies = [{"name": k, "value": v} for k, v in parse_cookie_string(cookies).items()]

    values: Dict[str, str] = {}
    for cookie in cookies or ():
        name, value = _cookie_pair(cookie)
        if not name:
            continue
        if _lower(name) == "x5sec" and str(value).strip():
            values[name] = str(value)
    return values


def _cookie_pair(cookie) -> tuple:
    """从 Playwright Cookie 对象或字典里取出 (name, value)。"""
    if cookie is None:
        return "", ""
    if isinstance(cookie, dict):
        return cookie.get("name") or "", cookie.get("value") or ""
    name = getattr(cookie, "name", None)
    if name is None:
        return "", ""
    return name, getattr(cookie, "value", "") or ""


def _stale_x5sec_values(before_values) -> set:
    """把「拖动前的旧 x5sec」归一成值集合。

    三种输入都要吃下：``collect_x5sec_values`` 的结果字典、值列表 / 集合，
    以及 ``"k=v; k2=v2"`` 字符串。

    字符串必须走解析，不能直接迭代：迭代字符串会逐字符拆开，
    旧值 ``old-token`` 于是不在集合里，旧值被误判成新值 —— 严格判定失效。
    """
    if isinstance(before_values, (str, bytes)):
        before_values = collect_x5sec_values(before_values)
    if isinstance(before_values, dict):
        return {str(v) for v in before_values.values() if str(v).strip()}
    return {str(v) for v in (before_values or ()) if str(v).strip()}


def has_fresh_x5sec(before_values, after_cookies) -> bool:
    """拖动后是否出现了**新的**非空 `x5sec`。

    ``before_values`` 是拖动前的旧值（``collect_x5sec_values`` 的结果、值集合，
    或 Cookie 字符串）。旧值原样出现一律不算成功 —— 这正是
    「滑块过了却一直 FAIL_SYS_USER_VALIDATE」的根因。
    """
    stale = _stale_x5sec_values(before_values)

    for name, value in collect_x5sec_values(after_cookies).items():
        if _lower(name) != "x5sec":
            continue
        if value in stale:
            continue
        return True
    return False


def still_on_punish_url(url) -> bool:
    """当前 URL 是否还停在 punish / captcha 验证页。"""
    lowered = _lower(url)
    if not lowered:
        return False
    return any(marker in lowered for marker in PUNISH_URL_MARKERS)


def is_verification_page_expired(content) -> bool:
    """页面内容是否表示惩罚链接已过期。"""
    text = str(content or "")
    return any(marker in text for marker in EXPIRED_PAGE_MARKERS)


def is_direct_error_page(text) -> bool:
    """页面正文是否表示「没有可用滑块、只有错误提示」。

    命中时应立即停止自动验证：继续 reload、拖动或切备用引擎都不会成功，
    只会让风控持续更久。
    """
    normalized = " ".join(str(text or "").lower().split())
    if not normalized:
        return False
    return any(marker.lower() in normalized for marker in DIRECT_ERROR_MARKERS)


def verification_passed(before_values, after_cookies, current_url) -> bool:
    """严格通过判定：新 `x5sec` **且** 已离开验证页。

    两个条件缺一不可。只看 Cookie 会把「服务端仍在验证页、但页面已经下发
    新挑战标记」误判成通过；只看 URL 会把「服务端没放行、前端组件收起」
    误判成通过。
    """
    if not has_fresh_x5sec(before_values, after_cookies):
        return False
    if still_on_punish_url(current_url):
        return False
    return True


def _domain_rank(domain) -> int:
    """域优先级：命中越靠前的域越优先。未列出的域排最后。"""
    lowered = _lower(domain)
    if not lowered:
        return len(DOMAIN_PRIORITY)
    for index, known in enumerate(DOMAIN_PRIORITY):
        if lowered == known:
            return index
    for index, known in enumerate(DOMAIN_PRIORITY):
        if lowered.endswith(known):
            return index
    return len(DOMAIN_PRIORITY)


def select_newest_x5_cookies(cookies: Iterable) -> Dict[str, str]:
    """按域优先级挑出每个 x5 Cookie 名最终应该采用的值。

    同名 Cookie 可能同时存在于 `h5api.m.goofish.com` 和 `.goofish.com`。
    直接遍历会让「后读到的」胜出，顺序不确定；这里显式按域优先级选择，
    让真正签发 `x5sec` 的子域值胜出。
    """
    chosen: Dict[str, tuple] = {}
    for cookie in cookies or ():
        name, value = _cookie_pair(cookie)
        if not name or not is_x5_cookie_name(name):
            continue
        if not str(value).strip():
            continue
        domain = cookie.get("domain", "") if isinstance(cookie, dict) else getattr(cookie, "domain", "") or ""
        rank = _domain_rank(domain)
        previous = chosen.get(name)
        if previous is None or rank < previous[0]:
            chosen[name] = (rank, str(value))
    return {name: value for name, (_, value) in chosen.items()}


def parse_cookie_string(cookies_str: str) -> Dict[str, str]:
    """把 ``"k=v; k2=v2"`` 解析成字典。

    这里自带一份解析而不复用 ``utils.xianyu_utils.trans_cookies``：那个模块
    在导入时要拉起 execjs / Node 运行时，而严格判定是纯字符串逻辑，
    不该被浏览器和 JS 运行时的可用性拖住（自动化环境和单测里都没有）。
    """
    parsed: Dict[str, str] = {}
    if not cookies_str:
        return parsed
    for part in str(cookies_str).split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            parsed[name] = value.strip()
    return parsed


def merge_captcha_cookies(
    base_cookies_str: str,
    browser_cookies: Iterable,
    clear_challenge: bool = True,
) -> tuple:
    """把浏览器里回收的 x5 系列 Cookie 合并回账号 Cookie 字符串。

    只动 x5 系列字段，其余字段一个都不碰 —— 丢了 `unb` / `_m_h5_tk`
    会直接掉线。返回 ``(合并后的字符串, {名称: 值})``。

    ``clear_challenge`` 为真且本次确实拿到了 `x5sec` 时，清掉 `x5secdata` /
    `x5sectag` / `x5step`：它们是「挑战未完成」的标记，留着会让服务端
    继续要求验证。本次浏览器又下发同名值时以新值为准，不删除。
    """
    if not base_cookies_str:
        return base_cookies_str, {}

    merged = parse_cookie_string(base_cookies_str)
    if not merged:
        return base_cookies_str, {}

    fresh = select_newest_x5_cookies(browser_cookies)

    for name, value in fresh.items():
        # 同名字段大小写可能不一致，先清掉旧的等价写法，避免出现两份
        for existing in [k for k in merged if _lower(k) == _lower(name) and k != name]:
            merged.pop(existing, None)
        merged[name] = value

    lowered = {_lower(k) for k in fresh}
    if clear_challenge and "x5sec" in lowered:
        for stale in CHALLENGE_COOKIE_NAMES:
            for name in [k for k in merged if _lower(k) == stale and _lower(k) not in lowered]:
                merged.pop(name, None)

    return "; ".join(f"{k}={v}" for k, v in merged.items()), fresh


def describe_verification_failure(before_values, after_cookies, current_url) -> str:
    """给日志用的一句话失败原因，便于线上定位卡在哪一步。"""
    if not has_fresh_x5sec(before_values, after_cookies):
        names = sorted(n for n, _ in collect_x5_cookies_for_log(after_cookies))
        return f"未出现新的 x5sec（当前 x5 字段: {names}）"
    if still_on_punish_url(current_url):
        return f"已拿到新 x5sec，但页面仍停在验证地址: {str(current_url)[:120]}"
    return ""


def collect_x5_cookies_for_log(cookies: Iterable) -> List[tuple]:
    """收集 x5 系列字段名和值长度，供日志脱敏输出。"""
    out = []
    for cookie in cookies or ():
        name, value = _cookie_pair(cookie)
        if name and is_x5_cookie_name(name):
            out.append((name, len(str(value))))
    return out


def pick_manual_verification_url(live_url: Optional[str], stored_url: Optional[str]) -> Optional[str]:
    """选择人工验证要打开的惩罚页地址。

    优先用实时刷新拿到的**新鲜**链接；只在拿不到时才退回库里存的历史链接。
    历史链接的 `x5secdata` 大概率已经失效，打开只会看到「页面访问出现了问题」，
    因此调用方拿到它之后必须先探测滑块是否真的出现。
    """
    if live_url and str(live_url).strip():
        return str(live_url).strip()
    if stored_url and str(stored_url).strip():
        return str(stored_url).strip()
    return None
