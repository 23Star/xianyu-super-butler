# -*- coding: utf-8 -*-
"""Ydisks 风格滑块方案（生产验证版轨迹 + 严格成功判定）。

移植自 Christ9038/Ydisks-Xianyu-Helper 的 internal/browser/slider.go
（Go + playwright-go），该实现在生产环境持续迭代出「快节奏一口气拖到底」
的行为契约，演进过程记录在其 docs/slider-captcha-frozen-spec.md：

- 最初 6 点 480-900ms → 用户实测缺人工节奏，改 8-12 点 1.1-2.1s
- 逐段拖动改为连续事件流（相邻事件 ≤ 30ms，后又收紧到 15ms）
- 最终提速一倍到 550-1050ms —— 当前阿里 nc 接受快节奏连续拖动

与旧拟人方案（2.5-4 秒、40-85% 距离甩出后回弹）的关键差异：

1. 三段式锚点（加速 26-34% / 匀速 / 减速 24-32%），仅 8-12 个高层点
2. 尾部受控微超调 4-20px（页面控件在轨道边界钳位，拖不出轨）
3. 无回拉、无中段停顿、无迟疑
4. Y 轴完整正弦 S 形，峰峰值精确缩放到滑轨高度的一半，首末点归零
5. 锚点展开为连续微移动事件流，间隔 ≤ 15ms，段内正弦节奏调制
6. mouse.up 后在滑块元素上补发合成 click（nc 前端确认事件）
7. 成功判定增加「全新非空 x5sec」：拖动前快照旧值，旧值重复不算成功
"""

import math
import random
import time

# 连续微移动事件的最大间隔（秒）。提速后仍须呈连续轨迹。
CONTINUOUS_EVENT_MAX_INTERVAL = 0.015
# 按下到释放的目标墙钟范围（秒）。
MOVEMENT_MIN_DURATION = 0.550
MOVEMENT_MAX_DURATION = 1.050


def random_float(min_value, max_value):
    return min_value + random.random() * (max_value - min_value)


def generate_trajectory(distance, vertical_span):
    """生成标准 NC 的单调三阶段曲线锚点。

    distance 是按钮可用移动距离；vertical_span 是 Y 轴峰峰值。
    锚点之间由连续微移动连接，末点落到受控超调终点。
    """
    # 高层鼠标移动采样数：8-12 点，避免固定轨迹特征
    requested_steps = 8 + random.randint(0, 4)
    # 各采样点的基础等待秒数；实际总时长由展开时的墙钟预算补偿
    average_delay = random_float(0.045, 0.085)
    # 加速/减速段占轨迹比例，余量构成中速段
    accel_ratio = random_float(0.26, 0.34)
    decel_ratio = random_float(0.24, 0.32)
    accel_steps = max(2, round(requested_steps * accel_ratio))
    decel_steps = max(2, round(requested_steps * decel_ratio))
    constant_steps = max(2, requested_steps - accel_steps - decel_steps)

    # 鼠标终点超出可用滑轨的像素量；页面控件会在轨道边界钳位
    overshoot = random_float(4, 20)
    target_distance = distance + overshoot
    accel_distance = target_distance * random_float(0.24, 0.34)
    constant_distance = target_distance * random_float(0.46, 0.56)
    decel_distance = target_distance - accel_distance - constant_distance

    points = []
    # 加速段：二次曲线
    for step in range(1, accel_steps + 1):
        progress = step / accel_steps
        points.append({
            "x": accel_distance * progress * progress,
            "y": 0.0,
            "delay": average_delay * random_float(0.70, 1.20),
        })
    # 中速段：线性前进，间隔刻意保留差异
    for step in range(1, constant_steps + 1):
        progress = step / constant_steps
        points.append({
            "x": accel_distance + constant_distance * progress,
            "y": 0.0,
            "delay": average_delay * random_float(0.65, 1.25),
        })
    # 减速段：二次缓出
    for step in range(1, decel_steps + 1):
        progress = step / decel_steps
        points.append({
            "x": accel_distance + constant_distance
                 + decel_distance * (1 - (1 - progress) ** 2),
            "y": 0.0,
            "delay": average_delay * random_float(0.90, 1.55),
        })

    apply_continuous_vertical_drift(points, vertical_span)
    if points:
        points[-1]["x"] = target_distance
    return points


def apply_continuous_vertical_drift(points, vertical_span):
    """把 Y 坐标改为连续正弦 S 形曲线。

    vertical_span 是轨迹实际达到的 Y 轴峰峰值；不足三个点或非正值时
    保留水平路径作为降级行为。
    """
    if len(points) < 3 or vertical_span <= 0:
        return
    direction = 1.0 if random.randint(0, 1) == 0 else -1.0
    point_count = len(points) - 1
    raw_y = []
    min_y, max_y = math.inf, -math.inf
    for i in range(len(points)):
        progress = i / point_count
        value = math.sin(2 * math.pi * progress)
        raw_y.append(value)
        min_y = min(min_y, value)
        max_y = max(max_y, value)
    # 把离散采样的实际峰峰值精确缩放到请求值
    scale = vertical_span / (max_y - min_y)
    centre = (min_y + max_y) / 2
    for i, point in enumerate(points):
        point["y"] = direction * (raw_y[i] - centre) * scale
    points[0]["y"] = 0.0
    points[-1]["y"] = 0.0


def expand_continuous_trajectory(points, target_duration):
    """把稀疏锚点展开为连续事件流，避免鼠标在锚点处肉眼可见地停住。

    target_duration 是按下到释放的目标总时长（秒）。
    返回 [(dx, dy, delay), ...]，delay 不超过连续事件允许的最大间隔。
    """
    total_weight = sum(p["delay"] for p in points)
    if not points or target_duration <= 0 or total_weight <= 0:
        return []
    expanded = []
    previous = {"x": 0.0, "y": 0.0}
    for point in points:
        segment_duration = target_duration * point["delay"] / total_weight
        # 本段事件数：按 15ms 上限预留 1.34 倍节奏变化空间，至少 2 个
        event_count = max(2, math.ceil(
            segment_duration / CONTINUOUS_EVENT_MAX_INTERVAL * 1.34))
        # 段内正弦节奏：平滑快慢变化而非逐点抖动
        rhythm_phase = random_float(0, 2 * math.pi)
        rhythm_rate = random_float(0.8, 1.6)
        event_weights = []
        weight_total = 0.0
        for event_index in range(event_count):
            progress = event_index / max(1, event_count - 1)
            weight = 1 + 0.22 * math.sin(
                2 * math.pi * rhythm_rate * progress + rhythm_phase)
            event_weights.append(weight)
            weight_total += weight
        for event_index in range(1, event_count + 1):
            progress = event_index / event_count
            event_delay = (segment_duration
                           * event_weights[event_index - 1] / weight_total)
            expanded.append((
                previous["x"] + (point["x"] - previous["x"]) * progress,
                previous["y"] + (point["y"] - previous["y"]) * progress,
                event_delay,
            ))
        previous = point
    return expanded


def build_ydisks_trajectory(distance, vertical_span):
    """组合入口：锚点生成 + 连续流展开。

    返回 [(dx, dy, delay), ...] 元组列表，与 replay_trajectory 的
    轨迹格式兼容（delay 为相对上一点的间隔秒数）。
    """
    anchors = generate_trajectory(distance, vertical_span)
    target = random_float(MOVEMENT_MIN_DURATION, MOVEMENT_MAX_DURATION)
    trajectory = expand_continuous_trajectory(anchors, target)
    total_delay = sum(p[2] for p in trajectory)
    return trajectory, target, total_delay


def get_vertical_span(slider_button, slider_track):
    """Y 轴峰峰值：优先滑轨实际高度的一半，降级按钮高度的一半。"""
    span = 0.0
    try:
        track_box = slider_track.bounding_box()
        if track_box and track_box.get("height", 0) > 0:
            span = track_box["height"] / 2
    except Exception:
        pass
    if span <= 0:
        try:
            button_box = slider_button.bounding_box()
            if button_box and button_box.get("height", 0) > 0:
                span = button_box["height"] / 2
        except Exception:
            pass
    return span


def x5sec_value_set(cookies):
    """收集当前所有非空 x5sec 的值（拖动前快照用）。"""
    values = set()
    for cookie in cookies or []:
        name = (cookie.get("name") or "").lower()
        value = (cookie.get("value") or "").strip()
        if name == "x5sec" and value:
            values.add(value)
    return values


def has_fresh_x5sec(cookies, previous_values):
    """判定是否出现了快照之外的全新非空 x5sec。

    旧值重复不算成功 —— 验证页可能带着旧 x5sec 反复跳转，只有平台
    新签发的值才是真正的通行凭证。
    """
    for cookie in cookies or []:
        name = (cookie.get("name") or "").lower()
        value = (cookie.get("value") or "").strip()
        if name == "x5sec" and value and value not in (previous_values or set()):
            return True
    return False


def wait_for_strict_success(page, context, previous_values,
                            timeout=5.0, interval=0.4,
                            punish_markers=("punish", "x5step=2",
                                            "action=captcha", "purecaptcha",
                                            "/captcha")):
    """轮询严格成功判定：全新非空 x5sec + URL 已离开 punish。

    返回 True/False。这是 Ydisks 的双条件判定，配合拖动前快照使用。
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            cookies = context.cookies()
            url = (page.url or "").lower()
            if has_fresh_x5sec(cookies, previous_values) and not any(
                    marker in url for marker in punish_markers):
                return True
        except Exception:
            pass
        if time.monotonic() + interval > deadline:
            return False
        time.sleep(interval)


# ---------------------------------------------------------------------------
# 失败恢复状态机（移植自 Ydisks slider.go:635-763）
#
# 核心规则：已拖动后失败，绝不 reload —— reload 会丢弃平台重新生成的
# 滑块状态并加重风控。改为点击页面上的失败按钮，并确认滑块按钮回到
# 轨道起点 ±3px（元素重新出现 ≠ 控件可用，必须以归位为准）。
# ---------------------------------------------------------------------------

# 失败按钮选择器，按优先级排列（Ydisks clickRetry）
RETRY_CONTROL_SELECTORS = (
    "#nc_1_refresh1",
    ".nc_iconfont.btn_refresh",
    ".errloading",
    "[class*='refresh']",
)

# nc-container 仅当文本包含这些词时才允许点击，防止误触初始容器触发拖动
RETRY_CONTAINER_TEXT_MARKERS = ("重试", "刷新", "失败", "retry", "refresh", "failed")


def _iter_frames(page):
    yield page
    for frame in (page.frames or []):
        if frame != page.main_frame:
            yield frame


def find_retry_control(page):
    """按优先级查找失败恢复控件，返回 (frame, element) 或 (None, None)。"""
    for selector in RETRY_CONTROL_SELECTORS:
        for frame in _iter_frames(page):
            try:
                element = frame.query_selector(selector)
                if element and element.is_visible():
                    return frame, element
            except Exception:
                continue
    # 容器选择器需要文本佐证才可点
    for frame in _iter_frames(page):
        try:
            element = frame.query_selector(".nc-container")
            if element and element.is_visible():
                text = (element.text_content() or "").lower()
                if any(marker in text for marker in RETRY_CONTAINER_TEXT_MARKERS):
                    return frame, element
        except Exception:
            continue
    return None, None


def slider_at_origin(slider_button, slider_track, tolerance_px=3.0):
    """确认滑块按钮已回到轨道起点 ±tolerance_px。

    用按钮与轨道的 bounding box X 差值判定 —— 元素重新出现不代表控件
    已复位，未归位时直接再拖等于在坏控件上空拖。
    """
    try:
        button_box = slider_button.bounding_box()
        track_box = slider_track.bounding_box()
        if not button_box or not track_box:
            return False
        return abs(button_box["x"] - track_box["x"]) <= tolerance_px
    except Exception:
        return False


def recover_after_failed_drag(page, button_wait=0.8, reset_timeout=4.0):
    """已拖动失败后的恢复：点失败按钮 → 等滑块归位。

    返回 (recovered: bool, slider_button, slider_track)。
    归位确认成功时返回的元素可直接用于下一次拖动。
    控件可能延迟出现：button_wait 内轮询查找，期间不刷新页面。
    """
    deadline = time.monotonic() + button_wait
    frame = element = None
    while True:
        frame, element = find_retry_control(page)
        if element is not None:
            break
        if time.monotonic() >= deadline:
            return False, None, None
        time.sleep(0.15)

    try:
        element.click(timeout=2000)
    except Exception:
        return False, None, None

    # 等按钮与轨道重新出现并归位
    reset_deadline = time.monotonic() + reset_timeout
    while time.monotonic() < reset_deadline:
        time.sleep(0.3)
        for search_frame in _iter_frames(page):
            try:
                button = search_frame.query_selector("#nc_1_n1z")
                track = search_frame.query_selector("#nc_1_n1t")
                if button and track and button.is_visible() and track.is_visible():
                    if slider_at_origin(button, track):
                        return True, button, track
                    # 可见但未归位，继续等
                    break
            except Exception:
                continue
    return False, None, None


# ---------------------------------------------------------------------------
# 页面四分类（移植自 Ydisks token_captcha.go:348-363）
#
# 直接错误页：无可见滑块 + 正文含错误标记 → 立即终止，不重试不进
# 备用引擎，避免在坏掉的挑战上继续消耗风控额度。
# ---------------------------------------------------------------------------

DIRECT_ERROR_MARKERS = (
    "验证失败", "系统繁忙", "请稍后重试", "访问异常", "请求失败",
    "服务出错", "操作过于频繁", "verify failed", "system busy",
    "try again later", "too many requests", "server error",
    "网络异常", "加载失败", "页面不存在", "链接已过期",
)


def page_is_direct_error(page):
    """判定当前验证页是否为直接错误页（无可拖滑块的失败终态）。"""
    try:
        for frame in _iter_frames(page):
            try:
                button = frame.query_selector("#nc_1_n1z")
                if button and button.is_visible():
                    return False  # 有可见滑块，不是直接错误页
            except Exception:
                continue
        text = (page.content() or "")
        if any(marker in text for marker in DIRECT_ERROR_MARKERS):
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# 无头指纹规范化（移植自 Ydisks lifecycle_pool.go:20-83, 254-280）
#
# 哲学：完全不伪造指纹 —— 随机覆盖 canvas/WebGL/平台只会让同一账号
# 每次续期呈现不同设备指纹，本身就是强风控信号。只做最小规范化：
# 页面级 CDP Emulation.setUserAgentOverride 携带 userAgentMetadata，
# 使 navigator.userAgentData 高熵值与 UA / HTTP 头三处一致
# （无头被识破的正是这三处互相矛盾）。
# ---------------------------------------------------------------------------

def _brands_from_sec_ch_ua(sec_ch_ua):
    """把 SEC_CH_UA 头解析为 CDP userAgentMetadata 的 brands 列表。"""
    brands = []
    for part in sec_ch_ua.split(","):
        part = part.strip()
        if '";v="' in part:
            brand, _, version = part.partition('";v="')
            brands.append({
                "brand": brand.strip().lstrip('"'),
                "version": version.rstrip('"'),
            })
    return brands


def apply_page_fingerprint_override(context, page, ua=None, sec_ch_ua=None):
    """页面级 CDP 指纹覆盖：UA + Client Hints 元数据一次到位。

    context 级 user_agent 只改 UA 字符串，navigator.userAgentData 仍会
    泄漏无头特征；CDP session 必须保持附着（detach 后会还原）。
    返回 cdp_session（调用方需持有引用防止被回收）。
    """
    try:
        from utils.user_agents import CHROME_UA, SEC_CH_UA as DEFAULT_SEC_CH_UA
        ua = ua or CHROME_UA
        sec_ch_ua = sec_ch_ua or DEFAULT_SEC_CH_UA
    except ImportError:
        return None

    brands = _brands_from_sec_ch_ua(sec_ch_ua)
    if not brands:
        return None
    # fullVersion 取真实 Chrome 品牌（brands[0] 是 GREASE，版本恒为 99）
    chrome_entry = next(
        (b for b in brands if b["brand"] == "Google Chrome"), brands[-1])
    full_version = chrome_entry.get("version", "151")
    full_version_list = [
        {"brand": b["brand"], "version": b["version"]} for b in brands
    ]
    metadata = {
        "brands": brands,
        "fullVersionList": full_version_list,
        "fullVersion": full_version,
        "platform": "Windows",
        "platformVersion": "15.0.0",
        "architecture": "x86",
        "model": "",
        "mobile": False,
        "bitness": "64",
        "wow64": False,
    }
    try:
        cdp_session = context.new_cdp_session(page)
        cdp_session.send("Emulation.setUserAgentOverride", {
            "userAgent": ua,
            "userAgentMetadata": metadata,
        })
        return cdp_session
    except Exception:
        return None
