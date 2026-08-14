"""浏览器并发限流。

背景：项目里有多处需要拉起 headless Chromium（扫码登录、Cookie 刷新、
账号资料与商品详情抓取）。这些调用点原先各自独立启动浏览器，信号量也都建在
账号实例内部，于是挂几个账号就可能同时冒出几个 Chromium —— 多个账号的定时
Cookie 刷新一旦撞在同一分钟，这种情况几乎必然发生。

一个 headless Chromium 冷启动就要占满一个核数十秒。在 J1800 这类双核低压
CPU 上，两三个并存就足以把整机拖到 99%，启动变慢又导致任务继续堆积，形成雪崩。

这里提供一个进程内全局信号量，所有浏览器启动都从这里取槽位，用完自动归还。
槽位数按机器实际配置推算，弱机强制单开。
"""
import asyncio
import os
import threading
from contextlib import contextmanager
from typing import Any, Dict, Optional

from loguru import logger

# 允许通过环境变量强制指定，方便排查问题或应对推算不准的机器
_ENV_KEY = 'MAX_CONCURRENT_BROWSERS'

# 底层用线程信号量而不是 asyncio 版本：滑块验证走的是同步 Playwright，
# 跑在独立线程里，与异步任务共用同一台机器的 CPU。两边各建一套信号量的话，
# 总数就会翻倍，限流也就失去意义。
_semaphore: Optional[threading.Semaphore] = None
_semaphore_lock = threading.Lock()
_limit: Optional[int] = None

# 等待空闲浏览器的上限。低配机器上一次浏览器任务可能要一两分钟，
# 排队本身是正常的；但等过这个时间基本说明有任务卡死了，
# 与其无限期挂着，不如报错让上层记录并重试。
_ACQUIRE_TIMEOUT = 300


def _detect_total_memory_gb() -> Optional[float]:
    """物理内存（GB）。取不到时返回 None，由调用方只按 CPU 判断。"""
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return None


def get_limit() -> int:
    """允许同时运行的浏览器数量。

    浏览器是这里最重的资源消耗方，一个 headless Chromium 冷启动就要吃满一个核
    数十秒；并发拉起既拖慢彼此，也让滑块验证更容易失败。所以按机器实际配置放行，
    弱机一律单开——排队只是慢一点，挤爆了整机卡死，连正常的消息收发都会受影响。

    推算不准时可用环境变量 MAX_CONCURRENT_BROWSERS 覆盖。
    """
    global _limit
    if _limit is not None:
        return _limit

    forced = (os.getenv(_ENV_KEY) or '').strip()
    if forced:
        try:
            _limit = max(1, int(forced))
            logger.info(f"浏览器并发上限由 {_ENV_KEY} 指定为 {_limit}")
            return _limit
        except ValueError:
            logger.warning(f"{_ENV_KEY} 取值无效: {forced!r}，改用自动推算")

    cpu_count = os.cpu_count() or 2
    memory_gb = _detect_total_memory_gb()

    # 双核或 4G 以内：只能单开。这类配置多见于低价 NAS 和入门小主机，
    # 同时跑两个浏览器就会明显卡顿，甚至把整机拖到无法响应。
    if cpu_count <= 2 or (memory_gb is not None and memory_gb <= 4.5):
        _limit = 1
    elif cpu_count <= 4 or (memory_gb is not None and memory_gb <= 8.5):
        _limit = 2
    else:
        _limit = 3

    memory_desc = f"{memory_gb:.1f}G" if memory_gb is not None else "未知"
    logger.info(f"浏览器并发上限: {_limit}（CPU {cpu_count} 核，内存 {memory_desc}）")
    return _limit


def _get_semaphore() -> threading.Semaphore:
    global _semaphore
    if _semaphore is None:
        with _semaphore_lock:
            if _semaphore is None:
                _semaphore = threading.Semaphore(get_limit())
    return _semaphore


class LimitedBrowser:
    """给浏览器对象套一层，close() 时把槽位还回去。

    这样调用方原有的 `finally: await browser.close()` 不用改写，
    也就不会出现「忘记归还槽位」导致后续启动被永久卡住的情况。
    其余属性一律透传，用起来与原对象无差别。
    """

    def __init__(self, browser: Any, semaphore: threading.Semaphore, purpose: str):
        self._browser = browser
        self._semaphore = semaphore
        self._purpose = purpose
        self._released = False
        self._release_lock = threading.Lock()

    def _release(self) -> None:
        with self._release_lock:
            if not self._released:
                self._released = True
                self._semaphore.release()

    async def close(self, *args, **kwargs):
        try:
            return await self._browser.close(*args, **kwargs)
        finally:
            self._release()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._browser, name)


async def launch_browser(
    playwright: Any,
    launch_options: Optional[Dict[str, Any]] = None,
    purpose: str = '浏览器任务',
) -> LimitedBrowser:
    """取到槽位后再启动浏览器；没有空位就等着。

    调用方必须像以前一样在 finally 里 close()，槽位随之归还。
    """
    semaphore = _get_semaphore()

    # 在线程里等待，避免占着事件循环不放导致消息收发一起卡住
    acquired = await asyncio.to_thread(semaphore.acquire, True, _ACQUIRE_TIMEOUT)
    if not acquired:
        raise TimeoutError(
            f"{purpose}: 等待浏览器空闲超过 {_ACQUIRE_TIMEOUT} 秒。"
            "可能有浏览器任务卡住未退出，或机器性能不足以支撑当前账号数量。"
        )

    try:
        browser = await playwright.chromium.launch(**(launch_options or {}))
    except BaseException:
        # 启动失败要立刻归还，否则槽位会被永久占住
        semaphore.release()
        raise

    return LimitedBrowser(browser, semaphore, purpose)


@contextmanager
def browser_slot(purpose: str = '浏览器任务'):
    """同步版槽位。供滑块验证这类跑在线程里的同步 Playwright 使用。

    用法::

        with browser_slot("滑块验证"):
            browser = playwright.chromium.launch(...)
            ...
    """
    semaphore = _get_semaphore()
    acquired = semaphore.acquire(True, _ACQUIRE_TIMEOUT)
    if not acquired:
        raise TimeoutError(
            f"{purpose}: 等待浏览器空闲超过 {_ACQUIRE_TIMEOUT} 秒。"
            "可能有浏览器任务卡住未退出，或机器性能不足以支撑当前账号数量。"
        )
    try:
        yield
    finally:
        semaphore.release()


def acquire_slot(purpose: str = '浏览器任务') -> None:
    """同步取槽位。用于滑块验证这类跑在线程里、启动与关闭分处两个方法的场景。

    取到之后必须调用 release_slot 归还，否则后续任务会一直排队。
    """
    semaphore = _get_semaphore()
    if not semaphore.acquire(True, _ACQUIRE_TIMEOUT):
        raise TimeoutError(
            f"{purpose}: 等待浏览器空闲超过 {_ACQUIRE_TIMEOUT} 秒。"
            "可能有浏览器任务卡住未退出，或机器性能不足以支撑当前账号数量。"
        )


def release_slot(purpose: str = '浏览器任务') -> None:
    """归还 acquire_slot 取得的槽位。重复调用会被忽略调用方自行保证配对。"""
    try:
        _get_semaphore().release()
    except ValueError:
        # 归还次数多于取用次数，说明配对有误；记录但不影响主流程
        logger.warning(f"{purpose}: 浏览器槽位重复归还，已忽略")
