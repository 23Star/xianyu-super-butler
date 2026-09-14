"""浏览器身份单一来源的回归。

回归的是这个故障：同一套凭证在四个子系统里各带一份硬编码头，Chrome 版本
分别写成 120（登录）、133（令牌刷新/心跳）、138（发货/过验证码）、139
（部分新代码）。同一个账号登录时报 120、刷令牌变 133、拖滑块又变 138 ——
跨请求指纹版本跳变。

这里钉住三件事：

1. ``user_agent()`` 与 ``sec_ch_ua()`` 的版本号**永远一致**；
2. 版本解析、一致性判断、以及不一致时的提示都正确；
3. 四条链路确实走的是同一个来源，而不是各自又抄了一份字面量。
"""

import re
import unittest
from pathlib import Path

from utils.browser_identity import (
    CHROME_MAJOR,
    chrome_major,
    client_hint_headers,
    describe_headless_exposure,
    describe_identity_problem,
    describe_version_mismatch,
    parse_chrome_major,
    request_headers,
    sec_ch_ua,
    user_agent,
    version_matches,
)


class ConsistencyTests(unittest.TestCase):
    def test_ua_and_client_hints_share_one_version(self):
        """UA 说 138、Client Hints 说 133 这种自相矛盾必须不可能出现。"""
        ua_major = parse_chrome_major(user_agent())
        # 只看真实品牌：GREASE 品牌（Not(A:Brand）按规范带的是 v="99"，
        # 它不参与版本校验，混进来会让断言恒假。
        real_brand_majors = set(
            re.findall(r'"(?:Google Chrome|Chromium)";v="(\d+)"', sec_ch_ua())
        )

        self.assertEqual(ua_major, CHROME_MAJOR)
        self.assertEqual(real_brand_majors, {CHROME_MAJOR})

    def test_client_hints_keep_a_grease_brand(self):
        """GREASE 品牌必须保留且版本是 99，不能"顺手统一"成主版本。"""
        self.assertIn('"Not(A:Brand";v="99"', sec_ch_ua())

    def test_client_hint_headers_are_complete(self):
        headers = client_hint_headers()

        self.assertEqual(set(headers), {"sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"})
        self.assertEqual(headers["sec-ch-ua"], sec_ch_ua())
        self.assertEqual(headers["sec-ch-ua-mobile"], "?0")
        self.assertEqual(headers["sec-ch-ua-platform"], '"Windows"')

    def test_request_headers_pair_ua_with_hints(self):
        headers = request_headers()

        self.assertEqual(headers["user-agent"], user_agent())
        self.assertEqual(headers["sec-ch-ua"], sec_ch_ua())

    def test_ua_looks_like_a_real_desktop_chrome(self):
        ua = user_agent()

        self.assertIn("Mozilla/5.0", ua)
        self.assertIn("Windows NT 10.0", ua)
        self.assertIn("AppleWebKit/537.36", ua)
        self.assertIn("Safari/537.36", ua)
        # 无头标记绝不能出现在对外身份里
        self.assertNotIn("HeadlessChrome", ua)

    def test_grease_brand_is_not_a_stable_custom_brand(self):
        """固定的非 GREASE 品牌本身是自动化特征。"""
        self.assertIn("Not(A:Brand", sec_ch_ua())


class ParseTests(unittest.TestCase):
    def test_parses_major_from_ua(self):
        self.assertEqual(
            parse_chrome_major("Mozilla/5.0 ... Chrome/138.0.0.0 Safari/537.36"),
            "138",
        )

    def test_parses_other_versions(self):
        for version in ("120", "133", "139", "142"):
            ua = f"Mozilla/5.0 (Windows NT 10.0) Chrome/{version}.0.0.0 Safari/537.36"
            self.assertEqual(parse_chrome_major(ua), version)

    def test_returns_none_when_absent(self):
        for value in ("", None, "Mozilla/5.0 Firefox/130.0", "Chrome/abc"):
            self.assertIsNone(parse_chrome_major(value), repr(value))


class VersionMatchTests(unittest.TestCase):
    def test_matching_version(self):
        self.assertTrue(version_matches(f"Chrome/{CHROME_MAJOR}.0.0.0 Safari/537.36"))

    def test_mismatching_version(self):
        self.assertFalse(version_matches("Chrome/120.0.0.0 Safari/537.36"))

    def test_unparsable_is_not_a_match(self):
        self.assertFalse(version_matches("no version here"))

    def test_explicit_expected_version(self):
        self.assertTrue(version_matches("Chrome/120.0.0.0", expected_major="120"))


class MismatchMessageTests(unittest.TestCase):
    def test_silent_when_versions_agree(self):
        self.assertEqual(describe_version_mismatch(f"Chrome/{CHROME_MAJOR}.0.0.0"), "")

    def test_silent_when_unparsable(self):
        # 解析不到就别报警：宁可不提示，也不要因为读不到 UA 刷一屏假告警
        self.assertEqual(describe_version_mismatch(""), "")
        self.assertEqual(describe_version_mismatch("Firefox/130.0"), "")

    def test_reports_actual_and_expected(self):
        message = describe_version_mismatch("Chrome/142.0.0.0 Safari/537.36")

        self.assertIn("142", message)          # 实测值
        self.assertIn(CHROME_MAJOR, message)   # 声明值
        self.assertIn("CHROME_MAJOR", message)  # 告诉人改哪里


class HeadlessExposureTests(unittest.TestCase):
    def test_detects_headless_chrome_marker(self):
        message = describe_headless_exposure("HeadlessChrome/142.0.0.0 Safari/537.36")

        self.assertIn("无头标记", message)

    def test_silent_for_normal_ua(self):
        self.assertEqual(describe_headless_exposure(f"Chrome/{CHROME_MAJOR}.0.0.0"), "")
        self.assertEqual(describe_headless_exposure(""), "")

    def test_headless_ua_is_not_parsed_as_a_matching_version(self):
        """回归：`Chrome/(\\d+)` 会命中 HeadlessChrome 的子串，
        把无头浏览器误判成"版本一致"，从而漏掉真正的问题。"""
        self.assertIsNone(parse_chrome_major("HeadlessChrome/142.0.0.0 Safari/537.36"))
        self.assertFalse(version_matches("HeadlessChrome/138.0.0.0"))

    def test_headless_marker_outranks_version_match(self):
        """带无头标记时不能因为版本号相同就静默。"""
        ua = f"HeadlessChrome/{CHROME_MAJOR}.0.0.0 Safari/537.36"

        self.assertEqual(describe_version_mismatch(ua), "")  # 版本本身说不出问题
        self.assertNotEqual(describe_identity_problem(ua), "")  # 但身份有问题


class FlowWiringTests(unittest.TestCase):
    """四条链路必须真的引用同一个来源，不能又抄一份字面量。"""

    REPO = Path(__file__).resolve().parent.parent

    # 登录 / 令牌刷新 / 心跳 / 发货 / 过验证码 五条链路上所有发请求的模块。
    # 新增发请求的模块时把它加进来，否则又会悄悄长出第四份硬编码。
    WIRED_MODULES = (
        "utils/qr_login.py",                 # 登录
        "utils/refresh_util.py",             # 令牌刷新
        "utils/xianyu_seller_api.py",        # 发货
        "utils/order_detail_fetcher.py",     # 发货
        "utils/manual_captcha.py",           # 过验证码（人工）
        "utils/xianyu_slider_stealth.py",    # 过验证码（自动）
        "utils/browser_pool.py",             # 过验证码（浏览器池）
        "utils/slider_patch.py",             # 过验证码（补丁路径）
        "utils/item_polish.py",              # 发货（商品擦亮）
        "utils/item_search.py",              # 发货（商品检索）
        "utils/image_uploader.py",           # 发货（图片卡券）
        "app/reply_server.py",               # 登录 / 过验证码接口
        "XianyuAutoAsync.py",                # 令牌刷新 / 心跳 / 发货
    )

    def _read(self, relative: str) -> str:
        return (self.REPO / relative).read_text(encoding="utf-8")

    def test_every_wired_module_uses_shared_identity(self):
        missing = [
            path for path in self.WIRED_MODULES
            if "browser_identity" not in self._read(path)
        ]

        self.assertEqual(missing, [], f"这些模块没有引用统一来源: {missing}")

    def test_order_detail_fetcher_sends_a_user_agent(self):
        """只发 Client Hints 不发 UA 是明显异常指纹。"""
        text = self._read("utils/order_detail_fetcher.py")

        self.assertIn('"user-agent"', text)

    def test_no_stale_hardcoded_ua_left_in_wired_modules(self):
        """五条链路里不该再有任何硬编码 UA 残留。

        历史版本分别写成 120（登录）、133（令牌刷新/心跳）、138 与 139
        （发货/过验证码），这正是跨请求指纹跳变的来源。
        """
        leftovers = []
        for path in self.WIRED_MODULES:
            text = self._read(path)
            for i, line in enumerate(text.splitlines(), 1):
                if re.search(r"Chrome/\d+\.0\.0\.0", line):
                    # /reg 的 DingTalk 协议 ua 字段声明的是 IM 客户端身份，
                    # 不是浏览器指纹，故意保留。
                    if '"ua":' in line:
                        continue
                    leftovers.append(f"{path}:{i}")

        self.assertEqual(leftovers, [], f"仍有硬编码 UA: {leftovers}")

    def test_config_websocket_version_matches_shared_identity(self):
        """global_config.yml 是 YAML，没法 import，只能靠断言盯住一致性。"""
        config = self._read("global_config.yml")

        self.assertIn(f"Chrome/{CHROME_MAJOR}.0.0.0", config)
        self.assertNotIn("Chrome/133.0.0.0", config)
        self.assertNotIn("Chrome/120.0.0.0", config)

    def test_config_client_hints_match_its_user_agent(self):
        """配置文件里 UA 和 sec-ch-ua 也必须同版本。"""
        config = self._read("global_config.yml")
        ua_versions = set(re.findall(r"Chrome/(\d+)\.0\.0\.0", config))
        hint_versions = set(re.findall(r'v="(\d+)"', config))

        self.assertEqual(ua_versions, {CHROME_MAJOR})
        self.assertIn(CHROME_MAJOR, hint_versions)


if __name__ == "__main__":
    unittest.main()
