"""
浏览器实例池管理器
用于复用浏览器实例，减少浏览器启动次数，提升性能
"""
import asyncio
import time
import os
from typing import Dict, Optional, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
from loguru import logger
from collections import defaultdict


class BrowserPool:
    """
    浏览器实例池

    功能:
    - 按cookie_id维护浏览器实例
    - 复用同一账号的浏览器
    - 支持懒加载和自动清理
    - 超时自动关闭闲置浏览器
    """

    def __init__(self, max_size: int = 3, idle_timeout: int = 300):
        """
        初始化浏览器池

        Args:
            max_size: 最大浏览器实例数
            idle_timeout: 闲置超时时间（秒），默认5分钟
        """
        self.max_size = max_size
        self.idle_timeout = idle_timeout

        # 存储浏览器实例：{cookie_id: (playwright, browser, context, page, last_used_time)}
        self.pool: Dict[str, Tuple[Playwright, Browser, BrowserContext, Page, float]] = {}

        # 锁：确保同一cookie_id的浏览器不会被并发初始化
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        # 全局锁：保护pool的读写
        self._pool_lock = asyncio.Lock()

        logger.info(f"浏览器池初始化完成，最大实例数: {max_size}，闲置超时: {idle_timeout}秒")

    async def get_browser(
        self,
        cookie_id: str,
        cookie_string: str,
        headless: bool = True,
        create_new_page: bool = True
    ) -> Optional[Tuple[Browser, BrowserContext, Page]]:
        """
        获取浏览器实例（如果不存在则创建）

        Args:
            cookie_id: Cookie ID
            cookie_string: Cookie字符串
            headless: 是否无头模式
            create_new_page: 是否创建新页面（默认True，避免并发冲突）

        Returns:
            (browser, context, page) 元组，失败返回None
        """
        async with self._locks[cookie_id]:
            # 检查是否已存在该cookie_id的浏览器实例
            async with self._pool_lock:
                if cookie_id in self.pool:
                    playwright, browser, context, page, _ = self.pool[cookie_id]

                    # 检查浏览器是否仍然连接
                    if browser.is_connected():
                        try:
                            # 验证上下文是否可用
                            pages = context.pages
                            if not pages:
                                raise Exception("上下文没有可用页面")

                            # 更新最后使用时间
                            self.pool[cookie_id] = (playwright, browser, context, pages[0], time.time())

                            # 为每次请求创建新页面，避免并发导航冲突
                            if create_new_page:
                                new_page = await context.new_page()
                                logger.info(f"复用浏览器实例并创建新页面: {cookie_id}")
                                return browser, context, new_page
                            else:
                                logger.info(f"复用已存在的浏览器实例: {cookie_id}")
                                return browser, context, pages[0]
                        except Exception as e:
                            logger.warning(f"浏览器实例 {cookie_id} 不可用: {e}，将重新创建")
                            await self._close_browser_unsafe(cookie_id)
                    else:
                        logger.warning(f"浏览器实例 {cookie_id} 已断开连接，将重新创建")
                        await self._close_browser_unsafe(cookie_id)

            # 如果池已满，清理最旧的实例
            await self._ensure_pool_size()

            # 创建新的浏览器实例
            logger.info(f"创建新的浏览器实例: {cookie_id}")
            result = await self._create_browser(cookie_id, cookie_string, headless)

            if result:
                playwright, browser, context, page = result

                async with self._pool_lock:
                    self.pool[cookie_id] = (playwright, browser, context, page, time.time())

                logger.info(f"浏览器实例创建成功: {cookie_id}")
                return browser, context, page
            else:
                logger.error(f"浏览器实例创建失败: {cookie_id}")
                return None

    async def _create_browser(
        self,
        cookie_id: str,
        cookie_string: str,
        headless: bool = True
    ) -> Optional[Tuple[Playwright, Browser, BrowserContext, Page]]:
        """
        创建新的浏览器实例

        Args:
            cookie_id: Cookie ID
            cookie_string: Cookie字符串
            headless: 是否无头模式

        Returns:
            (playwright, browser, context, page) 元组，失败返回None
        """
        try:
            # 启动Playwright
            playwright = await async_playwright().start()

            # 浏览器启动参数（Docker环境优化）
            browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-features=TranslateUI',
                '--disable-ipc-flooding-protection',
                '--disable-extensions',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--hide-scrollbars',
                '--mute-audio',
                '--no-default-browser-check',
                '--no-pings'
            ]

            # Docker环境额外参数
            if os.getenv('DOCKER_ENV'):
                browser_args.extend([
                    '--disable-background-networking',
                    '--disable-client-side-phishing-detection',
                    '--disable-default-apps',
                    '--disable-hang-monitor',
                    '--disable-popup-blocking',
                    '--disable-prompt-on-repost',
                    '--disable-sync',
                    '--disable-web-resources',
                    '--metrics-recording-only',
                    '--safebrowsing-disable-auto-update',
                    '--enable-automation',
                    '--password-store=basic',
                    '--use-mock-keychain',
                    '--memory-pressure-off',
                    '--max_old_space_size=512',
                    '--disable-component-extensions-with-background-pages',
                    '--disable-features=TranslateUI,BlinkGenPropertyTrees',
                    '--disable-logging',
                    '--disable-permissions-api',
                    '--disable-notifications',
                    '--no-pings'
                ])

            # 启动浏览器
            browser = await playwright.chromium.launch(
                headless=headless,
                args=browser_args
            )

            # 创建浏览器上下文
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
            )

            # 设置Cookie
            cookies = []
            for cookie_pair in cookie_string.split('; '):
                if '=' in cookie_pair:
                    name, value = cookie_pair.split('=', 1)
                    cookies.append({
                        'name': name.strip(),
                        'value': value.strip(),
                        'domain': '.goofish.com',
                        'path': '/'
                    })

            await context.add_cookies(cookies)
            logger.info(f"已设置 {len(cookies)} 个Cookie")

            # 创建页面
            page = await context.new_page()

            # 不要手工伪造 sec-fetch-* / sec-ch-ua。浏览器会根据每个请求自动生成；
            # 固定写成 same-origin 会让从空白页进入订单详情时请求上下文不一致，
            # 闲鱼页面随后只返回空壳，订单金额和商品信息都无法渲染。

            # 等待浏览器完全初始化
            await asyncio.sleep(1)

            return playwright, browser, context, page

        except Exception as e:
            logger.error(f"创建浏览器实例失败: {e}")
            return None

    async def _ensure_pool_size(self):
        """确保池大小不超过最大限制，如果超过则清理最旧的实例"""
        async with self._pool_lock:
            while len(self.pool) >= self.max_size:
                # 找到最旧的实例（最后使用时间最早）
                oldest_cookie_id = None
                oldest_time = float('inf')

                for cookie_id, (_, _, _, _, last_used) in self.pool.items():
                    if last_used < oldest_time:
                        oldest_time = last_used
                        oldest_cookie_id = cookie_id

                if oldest_cookie_id:
                    logger.info(f"浏览器池已满，清理最旧的实例: {oldest_cookie_id}")
                    await self._close_browser_unsafe(oldest_cookie_id)
                else:
                    break

    async def _close_browser_unsafe(self, cookie_id: str):
        """
        关闭浏览器实例（不加锁，内部使用）

        Args:
            cookie_id: Cookie ID
        """
        if cookie_id not in self.pool:
            return

        playwright, browser, context, page, _ = self.pool[cookie_id]

        try:
            # 关闭页面
            if page:
                try:
                    await page.close()
                except Exception as e:
                    logger.debug(f"关闭页面失败: {e}")

            # 关闭上下文
            if context:
                try:
                    await context.close()
                except Exception as e:
                    logger.debug(f"关闭上下文失败: {e}")

            # 关闭浏览器
            if browser:
                try:
                    await browser.close()
                except Exception as e:
                    logger.debug(f"关闭浏览器失败: {e}")

            # 停止Playwright
            if playwright:
                try:
                    await playwright.stop()
                except Exception as e:
                    logger.debug(f"停止Playwright失败: {e}")

            logger.info(f"浏览器实例已关闭: {cookie_id}")
        except Exception as e:
            logger.error(f"关闭浏览器实例失败: {e}")
        finally:
            # 从池中移除
            del self.pool[cookie_id]

    async def close_browser(self, cookie_id: str):
        """
        关闭指定的浏览器实例

        Args:
            cookie_id: Cookie ID
        """
        async with self._pool_lock:
            await self._close_browser_unsafe(cookie_id)

    async def cleanup_idle_browsers(self):
        """清理闲置的浏览器实例"""
        current_time = time.time()
        to_close = []

        async with self._pool_lock:
            for cookie_id, (_, _, _, _, last_used) in self.pool.items():
                if current_time - last_used > self.idle_timeout:
                    to_close.append(cookie_id)

        # 关闭闲置的浏览器
        for cookie_id in to_close:
            logger.info(f"清理闲置的浏览器实例: {cookie_id}（闲置时间: {current_time - self.pool[cookie_id][4]:.2f}秒）")
            await self.close_browser(cookie_id)

    async def close_all(self):
        """关闭所有浏览器实例"""
        async with self._pool_lock:
            cookie_ids = list(self.pool.keys())

        for cookie_id in cookie_ids:
            await self.close_browser(cookie_id)

        logger.info("所有浏览器实例已关闭")

    def get_pool_status(self) -> Dict[str, any]:
        """
        获取池状态信息

        Returns:
            包含池状态的字典
        """
        current_time = time.time()
        status = {
            'total': len(self.pool),
            'max_size': self.max_size,
            'instances': []
        }

        for cookie_id, (_, browser, _, _, last_used) in self.pool.items():
            idle_time = current_time - last_used
            status['instances'].append({
                'cookie_id': cookie_id,
                'connected': browser.is_connected() if browser else False,
                'idle_time': idle_time,
                'last_used': last_used
            })

        return status


# 全局浏览器池实例（单例模式）
_global_browser_pool: Optional[BrowserPool] = None


def get_browser_pool(max_size: int = 3, idle_timeout: int = 300) -> BrowserPool:
    """
    获取全局浏览器池实例（单例模式）

    Args:
        max_size: 最大浏览器实例数
        idle_timeout: 闲置超时时间（秒）

    Returns:
        BrowserPool实例
    """
    global _global_browser_pool

    if _global_browser_pool is None:
        _global_browser_pool = BrowserPool(max_size=max_size, idle_timeout=idle_timeout)

    return _global_browser_pool
