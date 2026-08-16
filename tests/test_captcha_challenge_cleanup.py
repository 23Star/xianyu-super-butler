"""人机验证挑战标记的清理。

回归的是这个故障：滑块明明过了（Cookie 里已有 x5sec），账号却一直
`FAIL_SYS_USER_VALIDATE`，重新扫码也没用。

原因是保存 Cookie 时只做新增和覆盖、从不删除：x5secdata / x5sectag 这类
"挑战标记"表示"这个请求还有一道验证没做完"，而 x5sec 才是通过凭证。
两者同时存在时闲鱼认为挑战仍未完成，于是继续要求验证。
"""

import unittest

from utils.xianyu_utils import (
    CAPTCHA_CHALLENGE_COOKIES,
    drop_stale_captcha_challenge,
    trans_cookies,
)


def build(**pairs) -> str:
    return "; ".join(f"{k}={v}" for k, v in pairs.items())


class DropStaleChallengeTests(unittest.TestCase):
    def test_removes_challenge_markers_once_passed(self):
        cookies = build(unb='123', x5sec='pass-token', x5secdata='challenge', x5sectag='999')

        result = trans_cookies(drop_stale_captcha_challenge(cookies))

        # x5sec 要留，挑战标记必须清掉
        self.assertEqual(result.get('x5sec'), 'pass-token')
        self.assertNotIn('x5secdata', result)
        self.assertNotIn('x5sectag', result)

    def test_keeps_other_cookies_intact(self):
        cookies = build(unb='123', cookie2='c2', _m_h5_tk='tk_1', x5sec='pass', x5secdata='ch')

        result = trans_cookies(drop_stale_captcha_challenge(cookies))

        # 只动挑战标记，其他字段一个都不能少 —— 少了 unb / _m_h5_tk 会直接掉线
        self.assertEqual(result.get('unb'), '123')
        self.assertEqual(result.get('cookie2'), 'c2')
        self.assertEqual(result.get('_m_h5_tk'), 'tk_1')

    def test_keeps_challenge_when_not_passed_yet(self):
        # 还没拿到 x5sec 时挑战标记有用：要靠它定位惩罚页
        cookies = build(unb='123', x5secdata='challenge', x5sectag='999')

        self.assertEqual(drop_stale_captcha_challenge(cookies), cookies)

    def test_is_idempotent(self):
        cookies = build(unb='123', x5sec='pass')

        self.assertEqual(drop_stale_captcha_challenge(cookies), cookies)

    def test_handles_empty_input(self):
        for empty in ('', None):
            self.assertEqual(drop_stale_captcha_challenge(empty), empty)

    def test_case_insensitive_marker_names(self):
        cookies = build(unb='1', X5Sec='pass', X5SecData='challenge')

        result = trans_cookies(drop_stale_captcha_challenge(cookies))

        self.assertNotIn('X5SecData', result)
        self.assertEqual(result.get('X5Sec'), 'pass')

    def test_challenge_cookie_list_is_explicit(self):
        # x5sec 本身绝不能进这个清理名单，否则通过凭证会被一起删掉
        self.assertNotIn('x5sec', CAPTCHA_CHALLENGE_COOKIES)
        self.assertIn('x5secdata', CAPTCHA_CHALLENGE_COOKIES)


if __name__ == '__main__':
    unittest.main()
