"""滑块流程的超时兜底。

回归的是这个故障：Playwright 的 mouse.move / bounding_box 没有超时参数，页面无
响应时会无限期阻塞在 CDP 往返上 —— 实测卡了 6 分钟，直到浏览器被关掉才抛出
「Mouse.up: Target page, context or browser has been closed」。这期间浏览器不关、
全局槽位不归还，而槽位只有一个，后续每个浏览器任务都得先卡满等待超时。

看门狗只能靠杀浏览器进程：Playwright 同步 API 绑定在创建它的线程上，从定时器
线程调用 playwright.stop() 会直接抛「Cannot switch to a different thread」。
"""

import threading
import time
import unittest
from unittest.mock import patch

from utils import xianyu_slider_stealth as slider


def make_instance(user_id="acc"):
    instance = slider.XianyuSliderStealth.__new__(slider.XianyuSliderStealth)
    instance.user_id = instance.pure_user_id = user_id
    instance.playwright = None
    return instance


class WatchdogTests(unittest.TestCase):
    def test_kills_browser_process_on_timeout(self):
        instance = make_instance()
        called = threading.Event()

        with patch.object(
            slider.XianyuSliderStealth, '_kill_browser_process',
            side_effect=lambda: (called.set(), True)[1],
        ):
            timer = instance._start_watchdog(0.3)
            self.addCleanup(timer.cancel)
            # 杀掉进程后，阻塞中的 CDP 调用才会报错返回，主流程得以归还槽位
            self.assertTrue(called.wait(timeout=3))

    def test_never_calls_playwright_api_from_timer_thread(self):
        """看门狗不得触碰 Playwright 同步 API。"""
        instance = make_instance()

        class ExplodingPlaywright:
            def stop(self):
                raise AssertionError(
                    "看门狗调用了 Playwright 同步 API —— 跨线程会抛 "
                    "Cannot switch to a different thread，等于兜底失效"
                )

        instance.playwright = ExplodingPlaywright()
        done = threading.Event()

        with patch.object(
            slider.XianyuSliderStealth, '_kill_browser_process',
            side_effect=lambda: (done.set(), True)[1],
        ):
            timer = instance._start_watchdog(0.3)
            self.addCleanup(timer.cancel)
            self.assertTrue(done.wait(timeout=3))

    def test_cancelled_watchdog_does_not_fire(self):
        instance = make_instance()
        called = threading.Event()

        with patch.object(
            slider.XianyuSliderStealth, '_kill_browser_process',
            side_effect=lambda: (called.set(), True)[1],
        ):
            instance._start_watchdog(0.3).cancel()
            time.sleep(0.8)

        # 流程正常结束后取消，绝不能把下一次的浏览器误杀
        self.assertFalse(called.is_set())

    def test_survives_kill_failure(self):
        instance = make_instance()
        done = threading.Event()

        def boom():
            done.set()
            raise RuntimeError('无法枚举进程')

        with patch.object(slider.XianyuSliderStealth, '_kill_browser_process', side_effect=boom):
            timer = instance._start_watchdog(0.3)
            self.addCleanup(timer.cancel)
            time.sleep(0.8)

        # 杀进程失败时看门狗自身不能崩掉，否则线程异常会被静默吞掉
        self.assertTrue(done.is_set())

    def test_timer_is_daemon(self):
        timer = make_instance()._start_watchdog(30)
        self.addCleanup(timer.cancel)
        # 非守护线程会让进程退出时挂住 30 秒
        self.assertTrue(timer.daemon)

    def test_default_timeout_is_sane(self):
        # 正常一轮 10-40 秒，3 次重试也够；太短会误杀正在进行的验证
        self.assertGreaterEqual(slider.SLIDER_RUN_TIMEOUT, 120)
        self.assertLessEqual(slider.SLIDER_RUN_TIMEOUT, 600)


class KillBrowserProcessTests(unittest.TestCase):
    def test_matches_only_own_user_data_dir(self):
        """只能杀本账号的浏览器，不能误伤用户自己开的或别的账号。"""
        instance = make_instance("2217097925130")
        other = make_instance("9999999999999")

        killed = []

        class FakeProc:
            def __init__(self, cmdline):
                self.info = {'pid': 1, 'cmdline': cmdline}

            def kill(self):
                killed.append(self.info['cmdline'])

        procs = [
            FakeProc(['chrome', f'--user-data-dir=/app/browser_data/slider_{instance.pure_user_id}']),
            FakeProc(['chrome', f'--user-data-dir=/app/browser_data/slider_{other.pure_user_id}']),
            FakeProc(['chrome', '--user-data-dir=/Users/me/Library/Application Support/Google/Chrome']),
        ]

        import psutil
        with patch.object(psutil, 'process_iter', return_value=procs):
            result = instance._kill_browser_process()

        self.assertTrue(result)
        self.assertEqual(len(killed), 1, f"误杀了其他浏览器: {killed}")
        self.assertIn(instance.pure_user_id, ' '.join(killed[0]))

    def test_returns_false_when_nothing_matches(self):
        instance = make_instance("2217097925130")

        import psutil
        with patch.object(psutil, 'process_iter', return_value=[]):
            self.assertFalse(instance._kill_browser_process())


if __name__ == "__main__":
    unittest.main()
