"""人工滑块训练器 —— 打开真实滑块，录制你的鼠标轨迹作为学习样本。

用法:
    .venv/bin/python scripts/train_slider.py <cookie_id>

流程:
    1. 实时刷新 Token 拿新鲜惩罚 URL（仅 1 次请求）
    2. 打开可见浏览器窗口导航过去，绝不自动拖拽
    3. 页面注入监听器录制你的真实鼠标轨迹
    4. 你亲手拖过后：回收新 Cookie + 把轨迹写入学习库

学习库攒够 3 条成功记录后，XianyuSliderStealth._optimize_trajectory_params
会自动接管，后续自动验证即按你的真实手感生成轨迹。
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from app.db_manager import db_manager
from utils.manual_captcha import (
    _fetch_live_verification_url,
    _from_playwright_cookies,
    _to_playwright_cookies,
    get_verification_url,
)

# 页面内轨迹录制器：只读事件，不干预页面行为
RECORDER_SCRIPT = """
window.__slider_track = [];
window.__slider_state = {dragging: false, startX: null, startY: null, t0: null};
document.addEventListener('mousedown', (e) => {
    window.__slider_state.dragging = true;
    window.__slider_state.startX = e.clientX;
    window.__slider_state.startY = e.clientY;
    window.__slider_state.t0 = performance.now();
    window.__slider_track = [];
}, true);
document.addEventListener('mousemove', (e) => {
    const s = window.__slider_state;
    if (!s.dragging) return;
    window.__slider_track.push({
        x: e.clientX - s.startX,
        y: e.clientY - s.startY,
        t: performance.now() - s.t0
    });
}, true);
document.addEventListener('mouseup', () => {
    window.__slider_state.dragging = false;
}, true);
"""

CAPTCHA_SELECTORS = ".nc-container, #nc_1_n1z, .nc_scale, .nc_wrapper"


def _analyze(track: list) -> dict:
    """把原始轨迹点换算成学习库需要的运动学参数。"""
    if len(track) < 5:
        return {}

    xs = [p["x"] for p in track]
    ys = [p["y"] for p in track]
    ts = [p["t"] for p in track]

    total_ms = ts[-1] - ts[0]
    steps = len(track)
    base_delay = (total_ms / 1000.0) / max(steps - 1, 1)

    # 逐点速度，用于定位峰值位置（人手的钟形包络峰值通常在 30-60%）
    speeds = []
    for i in range(1, len(track)):
        dt = (ts[i] - ts[i - 1]) / 1000.0
        if dt > 0:
            speeds.append((xs[i] - xs[i - 1]) / dt)
    peak_ratio = (speeds.index(max(speeds)) / len(speeds)) if speeds else 0.5

    distance = max(xs) if xs else 0
    final_x = xs[-1]
    overshoot = distance - final_x

    return {
        "distance": round(final_x, 2),
        "total_steps": steps,
        "base_delay": round(base_delay, 5),
        "jitter_x_range": [round(min(0, min(xs[i] - xs[i - 1] for i in range(1, len(xs)))), 2), 2],
        "jitter_y_range": [round(min(ys), 2), round(max(ys), 2)],
        "slow_factor": 10,
        "acceleration_phase": round(peak_ratio, 3),
        "fast_phase": round(min(0.95, peak_ratio + 0.35), 3),
        "slow_start_ratio": 1.0,
        "trajectory_point_count": steps,
        "final_left_px": round(final_x, 2),
        "completion_used": overshoot > 0.5,
        "completion_steps": 3 if overshoot > 0.5 else 0,
        "_peak_ratio": round(peak_ratio, 3),
        "_duration_s": round(total_ms / 1000.0, 2),
        "_sample_hz": round(steps / max(total_ms / 1000.0, 0.001), 1),
        "_overshoot_px": round(overshoot, 2),
        "_y_drift_px": round(max(ys) - min(ys), 2),
    }


def _save_sample(cookie_id: str, record: dict):
    """写入 XianyuSliderStealth 使用的学习库。"""
    path = f"trajectory_history/{cookie_id}_success.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)

    history = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    entry = {k: v for k, v in record.items() if not k.startswith("_")}
    entry.update({
        "timestamp": time.time(),
        "user_id": cookie_id,
        "success": True,
        "source": "human_recorded",
    })
    history.append(entry)
    history = history[-100:]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    return path, len(history)


async def main():
    if len(sys.argv) < 2:
        print("用法: .venv/bin/python scripts/train_slider.py <cookie_id>")
        return 1

    cookie_id = sys.argv[1]
    cookies_str = db_manager.get_all_cookies().get(cookie_id)
    if not cookies_str:
        print(f"❌ 数据库里没有账号 {cookie_id} 的 Cookie")
        return 1

    print(f"\n账号: {cookie_id}")
    print("正在实时刷新 Token 获取新鲜惩罚 URL（1 次请求）...")

    url = await _fetch_live_verification_url(cookie_id, cookies_str)
    if url:
        print("✅ 拿到实时惩罚 URL")
    else:
        url = get_verification_url(cookie_id)
        if not url:
            print("❌ 未能获取惩罚 URL —— 账号当前可能不在风控状态")
            return 1
        print("⚠️ 实时获取失败，回退到数据库中的历史 URL（可能已过期）")

    from playwright.async_api import async_playwright

    # 用系统真实 Chrome + 持久化用户目录。
    # Playwright 自带的 Chromium（Chrome for Testing）指纹会被阿里 nc 识破，
    # 实测真人拖动同样判定失败，与轨迹无关。
    profile_dir = os.path.abspath(f"browser_data/train_{cookie_id}")
    os.makedirs(profile_dir, exist_ok=True)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            profile_dir,
            channel="chrome",  # 系统安装的正式版 Chrome，而非 Chromium
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        await ctx.add_init_script(RECORDER_SCRIPT)
        await ctx.add_cookies(_to_playwright_cookies(cookies_str))

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        title = await page.title()
        captcha = await page.query_selector(CAPTCHA_SELECTORS)

        print(f"页面标题: {title!r}")
        if not captcha:
            body = ""
            try:
                body = (await page.inner_text("body"))[:150].strip()
            except Exception:
                pass
            print("❌ 滑块未出现 —— 惩罚 URL 已失效或账号不在风控")
            if body:
                print(f"   页面内容: {body}")
            print("\n不做任何写入。浏览器保持 30 秒供查看...")
            await asyncio.sleep(30)
            await ctx.close()
            return 1

        print("✅ 滑块已出现！")
        print("\n" + "=" * 56)
        print("  请在浏览器窗口里【亲手拖动滑块】完成验证")
        print("  你的鼠标轨迹会被录制，作为自动验证的学习样本")
        print("=" * 56 + "\n")

        # 等待滑块消失 = 验证通过。先确认它存在过，避免误判。
        # 轨迹必须在等待过程中持续快照 —— 验证通过瞬间 iframe 会被销毁，事后读不到。
        passed = False
        waited = 0
        recorded_track = []
        for i in range(900):  # 最长 30 分钟
            await asyncio.sleep(2)
            waited += 2

            # 每轮快照一次所有 frame 的轨迹，保留最长的一份
            for frame in page.frames:
                try:
                    candidate = await frame.evaluate("window.__slider_track || []")
                except Exception:
                    continue
                if candidate and len(candidate) > len(recorded_track):
                    recorded_track = candidate

            try:
                el = await page.query_selector(CAPTCHA_SELECTORS)
                visible = await el.is_visible() if el else False
            except Exception:
                visible = False
            if not visible:
                passed = True
                break
            # 每分钟提示一次，避免以为脚本卡死
            if waited % 60 == 0:
                print(
                    f"  ⏳ 等待拖动中... 已等 {waited // 60} 分钟"
                    f"（已录到 {len(recorded_track)} 个轨迹点）",
                    flush=True,
                )

        if not passed:
            print("⏱️ 等待超时，未检测到验证通过。不做任何写入。")
            await ctx.close()
            return 1

        print("🎉 验证通过！")

        # 取回录制的轨迹：滑块常位于 iframe 内，需遍历所有 frame 找到有数据的那个。
        # 验证通过后 iframe 可能已被销毁，因此在等待循环里持续快照，这里取最后一份。
        track = recorded_track
        if not track:
            for frame in page.frames:
                try:
                    candidate = await frame.evaluate("window.__slider_track || []")
                except Exception:
                    continue
                if candidate and len(candidate) > len(track):
                    track = candidate

        stats = _analyze(track)
        if stats:
            print("\n  ── 你的拖拽特征 ──")
            print(f"  采样点数 : {stats['total_steps']}")
            print(f"  拖拽耗时 : {stats['_duration_s']} 秒")
            print(f"  采样频率 : {stats['_sample_hz']} Hz")
            print(f"  峰值速度 : 出现在 {stats['_peak_ratio'] * 100:.0f}% 处")
            print(f"  滑动距离 : {stats['distance']} px")
            print(f"  超调回拉 : {stats['_overshoot_px']} px")
            print(f"  Y 轴漂移 : {stats['_y_drift_px']} px")

            path, count = _save_sample(cookie_id, stats)
            print(f"\n✅ 样本已写入 {path}（累计 {count} 条）")
            if count >= 3:
                print("   ✨ 已达 3 条阈值 —— 自动验证将开始按你的手感生成轨迹")
            else:
                print(f"   还需 {3 - count} 条样本才能启用学习（再跑几次本脚本）")
        else:
            print("\n⚠️ 未录到有效轨迹（可能滑块在 iframe 内，或用了键盘操作）")
            print("   Cookie 仍会正常回收")

        # 回收新 Cookie —— 此时确认过滑块出现且消失，是真通过
        # x5sec 由 h5api.m.goofish.com 子域下发，必须按域优先级去重，
        # 否则父域 .goofish.com 的同名旧值会把验证凭证覆盖掉。
        raw_cookies = await ctx.cookies()
        merged = {}
        for ck in sorted(raw_cookies, key=lambda c: len(c.get("domain", ""))):
            # 域名越长越具体，排在后面覆盖父域同名值
            if ck.get("name"):
                merged[ck["name"]] = ck.get("value", "")
        new_cookies = "; ".join(f"{k}={v}" for k, v in merged.items())

        got_x5sec = "x5sec" in merged
        print(f"   回收字段数: {len(merged)}  含 x5sec: {'✅' if got_x5sec else '❌'}")

        if new_cookies and len(new_cookies) > 200:
            db_manager.save_cookie(cookie_id, new_cookies)
            print(f"✅ 新 Cookie 已写回数据库（{len(new_cookies)} 字符）")
        else:
            print("⚠️ 回收到的 Cookie 异常，跳过写入以免损坏原数据")

        await asyncio.sleep(3)
        await ctx.close()
        return 0


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(line_buffering=True)  # 强制行缓冲，输出立即可见
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    sys.exit(asyncio.run(main()))
