"""对比真实鼠标事件与 Playwright CDP 注入事件的字段差异。

服务器部署无法使用系统级鼠标，只能让 CDP 事件本身通过检测。
本脚本找出两者的可观测差异，作为补丁依据。

用法:
    .venv/bin/python scripts/probe_mouse_events.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>mouse probe</title>
<style>
  body{font-family:-apple-system,sans-serif;margin:0}
  #pad{width:100%;height:320px;background:#f5f5f5;border-bottom:2px solid #333;
       display:flex;align-items:center;justify-content:center;font-size:20px;color:#666}
  #out{padding:12px;font:12px monospace;white-space:pre}
</style></head><body>
<div id="pad">请在这个灰色区域里【左右移动鼠标】几秒</div>
<div id="out">等待鼠标移动...</div>
<script>
window.__real = [];
window.__cdp = [];
window.__mode = 'real';
function cap(e){
  const rec = {
    type: e.type,
    isTrusted: e.isTrusted,
    movementX: e.movementX, movementY: e.movementY,
    clientX: e.clientX, clientY: e.clientY,
    screenX: e.screenX, screenY: e.screenY,
    pageX: e.pageX, pageY: e.pageY,
    buttons: e.buttons,
    pressure: e.pressure !== undefined ? e.pressure : null,
    pointerType: e.pointerType || null,
    pointerId: e.pointerId !== undefined ? e.pointerId : null,
    tiltX: e.tiltX !== undefined ? e.tiltX : null,
    width: e.width !== undefined ? e.width : null,
    height: e.height !== undefined ? e.height : null,
    tsFrac: +(e.timeStamp % 1).toFixed(6),
    coalesced: e.getCoalescedEvents ? e.getCoalescedEvents().length : null,
    hasSourceCap: !!e.sourceCapabilities
  };
  (window.__mode === 'real' ? window.__real : window.__cdp).push(rec);
  document.getElementById('out').textContent =
    'real: ' + window.__real.length + ' 条   cdp: ' + window.__cdp.length + ' 条';
}
document.addEventListener('mousemove', cap, true);
document.addEventListener('pointermove', cap, true);
</script></body></html>
"""


def summarize(name, recs):
    if not recs:
        return f"{name}: 无数据"
    mm = [r for r in recs if r["type"] == "mousemove"]
    pm = [r for r in recs if r["type"] == "pointermove"]
    src = mm or pm
    if not src:
        return f"{name}: 无移动事件"

    def col(k):
        return [r[k] for r in src if r.get(k) is not None]

    mvx = col("movementX")
    lines = [
        f"  样本数        : mousemove={len(mm)} pointermove={len(pm)}",
        f"  isTrusted     : {set(r['isTrusted'] for r in src)}",
        f"  movementX 范围: {min(mvx) if mvx else 'N/A'} ~ {max(mvx) if mvx else 'N/A'}"
        f"  (全为0: {all(v == 0 for v in mvx) if mvx else 'N/A'})",
        f"  screenX-clientX 差: {set(r['screenX'] - r['clientX'] for r in src[:20])}",
        f"  screenY-clientY 差: {set(r['screenY'] - r['clientY'] for r in src[:20])}",
        f"  pressure      : {set(col('pressure')) if col('pressure') else 'N/A'}",
        f"  pointerType   : {set(col('pointerType')) if col('pointerType') else 'N/A'}",
        f"  width/height  : {set(col('width')) if col('width') else 'N/A'}"
        f" / {set(col('height')) if col('height') else 'N/A'}",
        f"  coalesced 数量: {set(col('coalesced')) if col('coalesced') else 'N/A'}",
        f"  timeStamp 小数: {'有小数' if any(r['tsFrac'] > 0 for r in src) else '全为整数(可疑)'}",
        f"  sourceCapabilities: {set(r['hasSourceCap'] for r in src)}",
    ]
    return f"{name}:\n" + "\n".join(lines)


async def main():
    from playwright.async_api import async_playwright

    path = os.path.abspath("/tmp/mouse_probe.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(TEST_PAGE)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            os.path.abspath("browser_data/probe"),
            channel="chrome",
            headless=False,
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(f"file://{path}")

        print("\n窗口已打开。请在灰色区域里【左右移动鼠标】约 5 秒...")
        for i in range(30):
            await asyncio.sleep(1)
            n = await page.evaluate("window.__real.length")
            if n >= 40:
                print(f"✅ 已采集 {n} 条真实事件")
                break
            if i % 5 == 4:
                print(f"  已采集 {n} 条，继续移动鼠标...")
        else:
            n = await page.evaluate("window.__real.length")
            if n == 0:
                print("❌ 未采集到真实鼠标事件")
                await ctx.close()
                return 1

        # 切换到 CDP 模式，用 Playwright 注入
        await page.evaluate("window.__mode = 'cdp'")
        print("\n正在用 Playwright CDP 注入鼠标移动...")
        for i in range(60):
            await page.mouse.move(300 + i * 5, 160 + (i % 7))
            await asyncio.sleep(0.015)

        real = await page.evaluate("window.__real")
        cdp = await page.evaluate("window.__cdp")

        print("\n" + "=" * 60)
        print(summarize("【真实硬件鼠标】", real))
        print()
        print(summarize("【Playwright CDP 注入】", cdp))
        print("=" * 60)

        with open("/tmp/mouse_probe_result.json", "w", encoding="utf-8") as f:
            json.dump({"real": real[:60], "cdp": cdp[:60]}, f, ensure_ascii=False, indent=2)
        print("\n原始数据已存 /tmp/mouse_probe_result.json")

        await asyncio.sleep(2)
        await ctx.close()
        return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(asyncio.run(main()))
