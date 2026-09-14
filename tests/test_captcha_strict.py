"""滑块严格判定的回归测试。

对照 Ydisks 的生产契约，把三条通过条件钉死：

1. 必须是**新的** `x5sec` —— 旧值不算、只有挑战标记不算；
2. 必须**已经离开** punish / captcha 验证页；
3. 同名 Cookie 按**域优先级**取值，别让 `.goofish.com` 的旧值盖掉
   `h5api.m.goofish.com` 刚签发的新值。

这三条各自对应一个已发生过的线上故障，所以每条都要有正反两面的断言。
"""

import unittest

from utils.captcha_strict import (
    CHALLENGE_COOKIE_NAMES,
    collect_x5sec_values,
    describe_verification_failure,
    has_fresh_x5sec,
    is_challenge_cookie_name,
    is_direct_error_page,
    is_verification_page_expired,
    is_x5_cookie_name,
    merge_captcha_cookies,
    pick_manual_verification_url,
    select_newest_x5_cookies,
    still_on_punish_url,
    verification_passed,
)


def cookie(name, value, domain=".goofish.com"):
    return {"name": name, "value": value, "domain": domain, "path": "/"}


class FakeCookie:
    """Playwright Cookie 是对象而不是字典，两条路径都要覆盖。"""

    def __init__(self, name, value, domain=".goofish.com"):
        self.name = name
        self.value = value
        self.domain = domain


class X5CookieNameTests(unittest.TestCase):
    def test_recognizes_x5_family(self):
        for name in ("x5sec", "X5Sec", "x5secdata", "x5sectag", "x5step"):
            self.assertTrue(is_x5_cookie_name(name), name)

    def test_rejects_unrelated_cookies(self):
        for name in ("unb", "_m_h5_tk", "cookie2", ""):
            self.assertFalse(is_x5_cookie_name(name), name)

    def test_challenge_names_exclude_the_pass_credential(self):
        # x5sec 是通过凭证，绝不能进清理名单，否则刚拿到的通行证会被删掉
        self.assertFalse(is_challenge_cookie_name("x5sec"))
        for name in CHALLENGE_COOKIE_NAMES:
            self.assertTrue(is_challenge_cookie_name(name), name)


class CollectX5SecTests(unittest.TestCase):
    def test_reads_dicts_and_objects(self):
        values = collect_x5sec_values([cookie("x5sec", "abc"), FakeCookie("X5Sec", "def")])
        self.assertEqual(set(values.values()), {"abc", "def"})

    def test_reads_cookie_string(self):
        """调用方常直接传 self.cookies_str，字符串路径必须能解析出值。

        只遍历字符串会逐字符走一遍并静默返回空集合，于是「必须是新 x5sec」
        退化成「有 x5sec 就算通过」—— 正好把要修的故障放回来。
        """
        values = collect_x5sec_values("unb=123; x5sec=old-token; _m_h5_tk=tk")

        self.assertEqual(values, {"x5sec": "old-token"})

    def test_string_without_x5sec_is_empty(self):
        self.assertEqual(collect_x5sec_values("unb=123; _m_h5_tk=tk"), {})

    def test_ignores_empty_values(self):
        self.assertEqual(collect_x5sec_values([cookie("x5sec", "  ")]), {})
        self.assertEqual(collect_x5sec_values("x5sec="), {})

    def test_ignores_non_x5sec(self):
        self.assertEqual(collect_x5sec_values([cookie("x5secdata", "challenge")]), {})

    def test_fresh_check_works_with_cookie_string_before(self):
        # 字符串快照 + 对象列表，是生产调用链上的真实组合
        self.assertFalse(has_fresh_x5sec("x5sec=old", [cookie("x5sec", "old")]))
        self.assertTrue(has_fresh_x5sec("x5sec=old", [cookie("x5sec", "new")]))


class FreshX5SecTests(unittest.TestCase):
    def test_old_value_is_not_fresh(self):
        """核心回归：旧 x5sec 必须判失败，否则等于无条件判成功。"""
        before = {"x5sec": "old-token"}
        after = [cookie("x5sec", "old-token"), cookie("x5secdata", "challenge")]

        self.assertFalse(has_fresh_x5sec(before, after))

    def test_new_value_is_fresh(self):
        before = {"x5sec": "old-token"}
        after = [cookie("x5sec", "brand-new-token")]

        self.assertTrue(has_fresh_x5sec(before, after))

    def test_no_previous_value_and_new_one_counts(self):
        self.assertTrue(has_fresh_x5sec({}, [cookie("x5sec", "fresh")]))

    def test_challenge_markers_alone_are_not_enough(self):
        """x5secdata / x5sectag 永远存在，不能当通过证据。"""
        after = [cookie("x5secdata", "challenge"), cookie("x5sectag", "999")]

        self.assertFalse(has_fresh_x5sec({}, after))

    def test_accepts_plain_containers_for_before(self):
        # 调用方可能传 set / list，不能只支持 dict
        self.assertFalse(has_fresh_x5sec(["old-token"], [cookie("x5sec", "old-token")]))
        self.assertTrue(has_fresh_x5sec(["old-token"], [cookie("x5sec", "new-token")]))


class PunishUrlTests(unittest.TestCase):
    def test_detects_all_punish_markers(self):
        for url in (
            "https://passport.goofish.com/punish?x5secdata=1",
            "https://x/punish?action=captcha",
            "https://x/page?x5step=2",
            "https://x/purecaptcha",
            "https://x/h5/mtop.taobao.idlemessage.pc.login.token/1.0/captcha",
        ):
            self.assertTrue(still_on_punish_url(url), url)

    def test_normal_url_is_not_punish(self):
        self.assertFalse(still_on_punish_url("https://www.goofish.com/im"))
        self.assertFalse(still_on_punish_url(""))

    def test_case_insensitive(self):
        self.assertTrue(still_on_punish_url("https://X/PUNISH"))


class VerificationPassedTests(unittest.TestCase):
    def test_requires_both_new_x5sec_and_left_page(self):
        before = {"x5sec": "old"}
        after = [cookie("x5sec", "new")]

        self.assertTrue(verification_passed(before, after, "https://www.goofish.com/im"))

    def test_fails_when_still_on_punish_even_with_new_x5sec(self):
        """拿到新 x5sec 但页面没跳走 —— 服务端没放行，不能算通过。"""
        before = {"x5sec": "old"}
        after = [cookie("x5sec", "new")]

        self.assertFalse(
            verification_passed(before, after, "https://passport.goofish.com/punish?x5secdata=1")
        )

    def test_fails_when_x5sec_is_stale(self):
        after = [cookie("x5sec", "old")]

        self.assertFalse(verification_passed({"x5sec": "old"}, after, "https://www.goofish.com/im"))

    def test_container_gone_is_not_proof(self):
        """容器消失只说明前端组件收起，没有新 x5sec 就不算通过。"""
        self.assertFalse(verification_passed({}, [], "https://www.goofish.com/im"))


class DomainPriorityTests(unittest.TestCase):
    def test_subdomain_value_wins_over_parent_domain(self):
        """x5sec 由 h5api 子域签发，合并时必须让子域的新值胜出。"""
        cookies = [
            cookie("x5sec", "stale-from-parent", domain=".goofish.com"),
            cookie("x5sec", "fresh-from-subdomain", domain="h5api.m.goofish.com"),
        ]

        selected = select_newest_x5_cookies(cookies)

        self.assertEqual(selected["x5sec"], "fresh-from-subdomain")

    def test_order_does_not_matter(self):
        forward = select_newest_x5_cookies([
            cookie("x5sec", "fresh", domain="h5api.m.goofish.com"),
            cookie("x5sec", "stale", domain=".goofish.com"),
        ])
        backward = select_newest_x5_cookies([
            cookie("x5sec", "stale", domain=".goofish.com"),
            cookie("x5sec", "fresh", domain="h5api.m.goofish.com"),
        ])

        self.assertEqual(forward["x5sec"], backward["x5sec"])

    def test_keeps_each_x5_name(self):
        selected = select_newest_x5_cookies([
            cookie("x5sec", "s"),
            cookie("x5secdata", "d"),
            cookie("x5sectag", "t"),
        ])

        self.assertEqual(set(selected), {"x5sec", "x5secdata", "x5sectag"})

    def test_skips_empty_and_unrelated(self):
        selected = select_newest_x5_cookies([
            cookie("x5sec", ""),
            cookie("unb", "123"),
        ])

        self.assertEqual(selected, {})


class MergeCaptchaCookiesTests(unittest.TestCase):
    BASE = "unb=123; _m_h5_tk=tk_1; cookie2=c2; x5secdata=old-challenge"

    def test_keeps_non_x5_fields(self):
        """丢了 unb / _m_h5_tk 会直接掉线，一个都不能少。"""
        merged, _ = merge_captcha_cookies(self.BASE, [cookie("x5sec", "new")])

        self.assertIn("unb=123", merged)
        self.assertIn("_m_h5_tk=tk_1", merged)
        self.assertIn("cookie2=c2", merged)

    def test_clears_challenge_after_new_x5sec(self):
        merged, fresh = merge_captcha_cookies(self.BASE, [cookie("x5sec", "new-token")])

        self.assertEqual(fresh.get("x5sec"), "new-token")
        self.assertIn("x5sec=new-token", merged)
        self.assertNotIn("x5secdata", merged)

    def test_keeps_challenge_when_no_x5sec(self):
        """还没拿到 x5sec 时挑战标记要留着 —— 靠它定位惩罚页。"""
        merged, _ = merge_captcha_cookies(self.BASE, [cookie("x5secdata", "new-challenge")])

        self.assertIn("x5secdata=new-challenge", merged)

    def test_challenge_resent_by_browser_is_kept(self):
        """本次浏览器又下发了同名挑战值，以新值为准，不能删。"""
        merged, _ = merge_captcha_cookies(
            self.BASE, [cookie("x5sec", "new"), cookie("x5secdata", "fresh-challenge")]
        )

        self.assertIn("x5secdata=fresh-challenge", merged)

    def test_handles_empty_base(self):
        merged, fresh = merge_captcha_cookies("", [cookie("x5sec", "new")])

        self.assertEqual(merged, "")
        self.assertEqual(fresh, {})

    def test_handles_browser_without_x5(self):
        merged, fresh = merge_captcha_cookies(self.BASE, [cookie("unb", "999")])

        self.assertEqual(merged, self.BASE)
        self.assertEqual(fresh, {})


class PageStateTests(unittest.TestCase):
    def test_detects_expired_link_page(self):
        self.assertTrue(is_verification_page_expired("抱歉，页面访问出现了问题"))
        self.assertFalse(is_verification_page_expired("<html>正常页面</html>"))

    def test_detects_direct_error_page(self):
        for text in ("安全验证未通过", "系统繁忙，请稍后重试", "Something went wrong"):
            self.assertTrue(is_direct_error_page(text), text)

    def test_normal_page_is_not_error(self):
        self.assertFalse(is_direct_error_page("请按住滑块，拖动到最右边"))

    def test_empty_text_is_not_error(self):
        self.assertFalse(is_direct_error_page(""))


class FailureDescriptionTests(unittest.TestCase):
    def test_reports_missing_new_x5sec(self):
        reason = describe_verification_failure({"x5sec": "old"}, [cookie("x5sec", "old")], "https://x/im")

        self.assertIn("未出现新的 x5sec", reason)

    def test_reports_still_on_punish(self):
        reason = describe_verification_failure(
            {"x5sec": "old"},
            [cookie("x5sec", "new")],
            "https://passport.goofish.com/punish?x5secdata=1",
        )

        self.assertIn("仍停在验证地址", reason)

    def test_empty_when_passed(self):
        reason = describe_verification_failure({"x5sec": "old"}, [cookie("x5sec", "new")], "https://x/im")

        self.assertEqual(reason, "")


class ManualUrlSelectionTests(unittest.TestCase):
    def test_prefers_live_url(self):
        self.assertEqual(
            pick_manual_verification_url("https://live/punish", "https://stored/punish"),
            "https://live/punish",
        )

    def test_falls_back_to_stored(self):
        self.assertEqual(
            pick_manual_verification_url(None, "https://stored/punish"),
            "https://stored/punish",
        )

    def test_none_when_both_missing(self):
        self.assertIsNone(pick_manual_verification_url("", "  "))


if __name__ == "__main__":
    unittest.main()
