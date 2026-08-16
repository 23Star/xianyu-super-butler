"""反检测脚本必须真的在页面里生效。

回归的是这个故障：17.5KB 的注入脚本顶层重复声明了 `const originalQuery`
（伪装 Permissions API 的那段被复制了两遍）。这是解析期 SyntaxError ——
整段脚本一行都没执行过，navigator.webdriver 始终暴露为 true。

而 add_init_script 遇到解析失败只会冒一个 pageerror，不抛异常，于是日志里
「已添加反检测脚本」照常打印，问题藏了很久：滑块视觉上拖得过去，服务端一看
webdriver 就继续拦，账号永远卡在 FAIL_SYS_USER_VALIDATE。

同类隐患不止一处：webdriver 和 maxTouchPoints 曾被 Object.defineProperty
各定义两次，而默认 configurable 为 false，第二次必然抛 TypeError 再次中断。
所以这里不验证「脚本长什么样」，只验证「注入后页面里的效果」。
"""

import unittest

from utils.xianyu_slider_stealth import XianyuSliderStealth

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def build_script():
    inst = XianyuSliderStealth.__new__(XianyuSliderStealth)
    inst.pure_user_id = 'test'
    return inst, inst._get_stealth_script(inst._get_random_browser_features())


class StealthScriptSyntaxTests(unittest.TestCase):
    """不启动浏览器也能守住的部分。"""

    def test_no_duplicate_toplevel_declaration(self):
        """顶层 const/let 不得重名 —— 重名即整段脚本失效。"""
        import re

        _, script = build_script()
        # 顶层声明的缩进与脚本首行一致；函数体内的声明缩进更深，不参与判定
        names = re.findall(r'^\s{0,16}(?:const|let)\s+([A-Za-z_$][\w$]*)',
                           script, re.MULTILINE)
        duplicates = {n for n in names if names.count(n) > 1}
        self.assertEqual(duplicates, set(), f"顶层重复声明: {duplicates}")

    def test_user_agent_not_forged(self):
        """不再伪造 UA：只改字符串会和 Client Hints、内核版本对不上。"""
        inst, script = build_script()
        self.assertIsNone(inst._get_random_browser_features()['user_agent'])
        self.assertNotIn('userAgent', script)

    def test_time_apis_untouched(self):
        """不得改动 Date / Performance —— 曾经的 `Date = function(...)` 会丢掉
        Date.now / Date.parse / Date.UTC 这些静态方法。"""
        _, script = build_script()
        self.assertNotIn('Date = function', script)
        self.assertNotIn('Performance.prototype.now', script)

    def test_mouse_listeners_untouched(self):
        """不得把 mousemove 监听塞进 setTimeout：滑块靠同步处理指针事件计算
        轨迹，异步化会直接破坏拖动判定。"""
        _, script = build_script()
        self.assertNotIn('addEventListener = function', script)


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, "需要 playwright")
class StealthScriptEffectTests(unittest.TestCase):
    """真正注入到页面里，验证效果而非文本。"""

    @classmethod
    def setUpClass(cls):
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()

    def _probe(self, expression):
        _, script = build_script()
        ctx = self._browser.new_context()
        ctx.add_init_script(script)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("about:blank")
        try:
            return page.evaluate(expression), errors
        finally:
            ctx.close()

    def test_script_runs_without_error(self):
        _, errors = self._probe("() => 1")
        self.assertEqual(errors, [], f"注入脚本报错: {errors}")

    def test_webdriver_is_hidden(self):
        """核心诉求：注入后 navigator.webdriver 不能是 true。"""
        value, _ = self._probe("() => navigator.webdriver")
        self.assertNotEqual(value, True)

    def test_date_now_still_callable(self):
        value, _ = self._probe(
            "() => typeof Date.now === 'function' && typeof Date.now() === 'number'"
        )
        self.assertTrue(value, "Date.now 被脚本破坏了")

    def test_native_functions_stay_native(self):
        """保留原生实现：包装过的函数 toString 不含 [native code]，本身就是特征。"""
        value, _ = self._probe("""() => ({
            addEventListener: EventTarget.prototype.addEventListener.toString(),
            toDataURL: HTMLCanvasElement.prototype.toDataURL.toString(),
        })""")
        for name, source in value.items():
            self.assertIn('native code', source, f"{name} 被包装成了非原生实现")


if __name__ == "__main__":
    unittest.main()
