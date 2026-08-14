"""只取新鲜的滑块惩罚 URL，不打开任何浏览器。

拿到 URL 后可放进用户的真实 Chrome 里人工完成验证 ——
Playwright 启动的 Chromium 指纹已被阿里识破，真人拖动同样失败。

用法:
    .venv/bin/python scripts/get_punish_url.py <cookie_id>
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from app.db_manager import db_manager
from utils.manual_captcha import _fetch_live_verification_url


async def main():
    if len(sys.argv) < 2:
        print("用法: .venv/bin/python scripts/get_punish_url.py <cookie_id>")
        return 1

    cookie_id = sys.argv[1]
    cookies_str = db_manager.get_all_cookies().get(cookie_id)
    if not cookies_str:
        print(f"❌ 数据库里没有账号 {cookie_id} 的 Cookie")
        return 1

    url = await _fetch_live_verification_url(cookie_id, cookies_str)
    if not url:
        print(f"❌ 未拿到惩罚 URL —— 账号 {cookie_id} 当前不在风控状态")
        return 1

    print(url)
    return 0


if __name__ == "__main__":
    logger.remove()
    sys.exit(asyncio.run(main()))
