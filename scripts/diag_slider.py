"""滑块失败诊断：拖拽全过程截图 + 页面文本，用于分析失败原因。

用法:
    .venv/bin/python scripts/diag_slider.py <cookie_id>
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from app.db_manager import db_manager
from utils.manual_captcha import _fetch_live_verification_url, _to_playwright_cookies

SHOT_DIR = "/tmp/slider_diag"


async def main():
    cookie_id = sys.argv[1] if len(sys.argv) > 1 else "3797978771"
    os.makedirs(SHOT_DIR, exist_ok=True)

    cookies_str = db_manager.get_all_cookies().get(cookie_id)
    url = await _fetch_live_verification_url(cookie_id, cookies_str)
    if not url:
        print("❌ 账号不在风控，无滑块可诊断")
        return 1

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            os.path.abspath(f"browser_data/diag_{cookie_id}"),
            channel="chrome",
            headless=False,
            no_viewport=True,
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        await ctx.add_cookies(_to_playwright_cookies(cookies_str))
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        await page.screenshot(path=f"{SHOT_DIR}/1_初始.png")
        print(f"页面标题: {await page.title()!r}")

        # 找滑块：优先主页面，其次各 frame
        target = page
        btn = await page.query_selector("#nc_1_n1z, .nc_iconfont, .btn_slide")
        if not btn:
            for fr in page.frames:
                try:
                    b = await fr.query_selector("#nc_1_n1z, .nc_iconfont, .btn_slide")
                except Exception:
                    continue
                if b:
                    btn, target = b, fr
                    print(f"滑块在 iframe: {fr.url[:80]}")
                    break
        if not btn:
            print("❌ 未找到滑块按钮")
            await ctx.close()
            return 1

        box = await btn.bounding_box()
        track = await target.query_selector("#nc_1_n1t, .nc_scale, .scale_text")
        tbox = await track.bounding_box() if track else None
        print(f"按钮: {box}")
        print(f"轨道: {tbox}")

        distance = (tbox["width"] - box["width"]) if tbox else 258
        sx = box["x"] + box["width"] / 2
        sy = box["y"] + box["height"] / 2
        print(f"计算滑动距离: {distance:.1f}px")

        # 用生产轨迹拖一次
        from utils.xianyu_slider_stealth import XianyuSliderStealth as S
        gen = S.__new__(S)
        gen.pure_user_id = cookie_id
        gen.enable_learning = False
        gen.success_history_file = f"trajectory_history/{cookie_id}_success.json"
        gen.last_trajectory_params = {}
        gen.trajectory_params = {
            "total_steps_range": [70, 95], "base_delay_range": [0.007, 0.012],
            "jitter_x_range": [-1, 1], "jitter_y_range": [-3, 3],
            "slow_factor_range": [8, 12], "acceleration_phase": 0.1,
            "fast_phase": 0.75, "slow_start_ratio_base": 1.0,
            "completion_usage_rate": 0.05, "avg_completion_steps": 1.0,
            "trajectory_length_stats": [], "learning_enabled": False,
        }
        traj = gen._generate_physics_trajectory(distance)

        await page.mouse.move(sx - 20, sy - 8, steps=6)
        await asyncio.sleep(0.2)
        await page.mouse.move(sx, sy, steps=4)
        await asyncio.sleep(0.15)
        await page.mouse.down()
        await asyncio.sleep(0.08)

        last = sx
        t0 = time.time()
        for x, y, d in traj:
            cx, cy = sx + x, sy + y
            await page.mouse.move(cx, cy)
            last = cx
            await asyncio.sleep(d)
        await asyncio.sleep(0.15)
        await page.mouse.up()
        print(f"拖拽完成，耗时 {time.time() - t0:.2f}s，终点偏移 {last - sx:.0f}px")

        await asyncio.sleep(1)
        await page.screenshot(path=f"{SHOT_DIR}/2_拖后1秒.png")
        await asyncio.sleep(3)
        await page.screenshot(path=f"{SHOT_DIR}/3_拖后4秒.png")

        # 抓所有可见文本，看平台提示什么
        texts = []
        for fr in page.frames:
            try:
                t = (await fr.inner_text("body")).strip()
                if t:
                    texts.append(f"[{fr.url[:60]}]\n{t[:300]}")
            except Exception:
                continue
        print("\n=== 页面文本 ===")
        for t in texts:
            print(t)

        print(f"\n截图已存 {SHOT_DIR}/")
        await asyncio.sleep(2)
        await ctx.close()
        return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    sys.exit(asyncio.run(main()))
