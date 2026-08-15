"""滑块流程的超时兜底。

回归的是这个故障：Playwright 的 mouse.move / bounding_box 没有超时参数，页面无
响应时会无限期阻塞在 CDP 往返上 —— 实测卡了 6 分钟，直到浏览器被关掉才抛出
「Mouse.up: Target page, context or browser has been closed」。这期间浏览器不关、
全局槽位不归还，而槽位只有一个，后续每个浏览器任务都得先卡满等待超时。
"""

import threading
import time
import unittest

from utils import xianyu_slider_stealth as slider


class FakePlaywright:
    """记录 stop() 是否被调用。"""

    def __init__(self, raises=False):
        self.stopped = threading.Event()
        self._raises = raises

    def stop(self):
        self.stopped.set()
        if self._raises:
            raise RuntimeError("driver 已经死了")


def make_instance(playwright=None):
    instance = slider.XianyuSliderStealth.__new__(slider.XianyuSliderStealth)
    instance.user_id = instance.pure_user_id = "acc"
    instance.playwright = playwright
    return instance


class WatchdogTests(unittest.TestCase):
    def test_stops_playwright_driver_on_timeout(self):
        playwright = FakePlaywright()
        timer = make_instance(playwright)._start_watchdog(0.3)
        self.addCleanup(timer.cancel)

        # 停掉 driver 会让阻塞中的 CDP 调用抛错，主流程才能走进 finally 归还槽位
        self.assertTrue(playwright.stopped.wait(timeout=3))

    def test_cancelled_watchdog_does_not_fire(self):
        playwright = FakePlaywright()
        make_instance(playwright)._start_watchdog(0.3).cancel()
        time.sleep(0.8)

        # 流程正常结束后取消，绝不能把下一次的浏览器误杀
        self.assertFalse(playwright.stopped.is_set())

    def test_survives_missing_playwright(self):
        timer = make_instance(None)._start_watchdog(0.2)
        self.addCleanup(timer.cancel)
        time.sleep(0.6)  # 不抛异常即为通过

    def test_survives_stop_failure(self):
        playwright = FakePlaywright(raises=True)
        timer = make_instance(playwright)._start_watchdog(0.2)
        self.addCleanup(timer.cancel)

        # driver 已死时 stop() 会抛错，看门狗自己不能因此崩掉
        self.assertTrue(playwright.stopped.wait(timeout=3))

    def test_timer_is_daemon(self):
        playwright = FakePlaywright()
        timer = make_instance(playwright)._start_watchdog(30)
        self.addCleanup(timer.cancel)

        # 非守护线程会让进程退出时挂住 30 秒
        self.assertTrue(timer.daemon)

    def test_default_timeout_is_sane(self):
        # 正常一轮 10-40 秒，3 次重试也够；太短会误杀正在进行的验证
        self.assertGreaterEqual(slider.SLIDER_RUN_TIMEOUT, 120)
        self.assertLessEqual(slider.SLIDER_RUN_TIMEOUT, 600)


if __name__ == "__main__":
    unittest.main()
