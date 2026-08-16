"""「需重新扫码」这个终态标记的置位与清除。

回归两个故障：

1. `FAIL_SYS_TOKEN_EXOIRED::令牌过期` 和 `FAIL_SYS_SESSION_EXPIRED::Session过期`
   曾被同一个 if 一起打上「需重新扫码」。但令牌过期是可恢复的 —— 失败响应本身
   就会 set-cookie 下发新的 _m_h5_tk，重签一次就好。实测紧接着的下一次刷新
   直接返回 SUCCESS，账号完全正常，界面却提示用户重扫。

2. 标记只置不清。账号恢复连接、订单和消息都在同步之后，界面依旧挂着
   「需重新扫码」，把用户引去做一次没必要的扫码。

这里不跑真实网络，只针对分类与清除逻辑本身。
"""

import json
import unittest


TOKEN_EXPIRED = {'ret': ['FAIL_SYS_TOKEN_EXOIRED::令牌过期']}
SESSION_EXPIRED = {'ret': ['FAIL_SYS_SESSION_EXPIRED::Session过期']}
SUCCESS = {'ret': ['SUCCESS::调用成功'], 'data': {'accessToken': 'tk'}}
RISK_CONTROL = {
    'ret': ['FAIL_SYS_USER_VALIDATE', 'RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试']
}


def classify(res_json):
    """复刻 refresh_token 里的判定，返回 (是否令牌过期, 是否会话过期)。"""
    text = json.dumps(res_json, ensure_ascii=False, separators=(',', ':'))
    session_expired = 'Session过期' in text
    token_expired = '令牌过期' in text
    # 令牌过期只在「不是会话过期」时才走可恢复分支
    return (token_expired and not session_expired), session_expired


class ExpiryClassificationTests(unittest.TestCase):
    def test_token_expiry_is_recoverable(self):
        """令牌过期不得被判成需重新扫码。"""
        recoverable, terminal = classify(TOKEN_EXPIRED)
        self.assertTrue(recoverable)
        self.assertFalse(terminal, "令牌过期被误判为登录态过期")

    def test_session_expiry_is_terminal(self):
        recoverable, terminal = classify(SESSION_EXPIRED)
        self.assertTrue(terminal)
        self.assertFalse(recoverable)

    def test_risk_control_is_neither(self):
        """风控要走滑块，不能落进这两个分支。"""
        recoverable, terminal = classify(RISK_CONTROL)
        self.assertFalse(recoverable)
        self.assertFalse(terminal)

    def test_success_is_neither(self):
        recoverable, terminal = classify(SUCCESS)
        self.assertFalse(recoverable)
        self.assertFalse(terminal)

    def test_both_present_prefers_terminal(self):
        """两个词同时出现时，以不可恢复的会话过期为准，避免无意义重试。"""
        both = {'ret': ['FAIL_SYS_SESSION_EXPIRED::Session过期', '令牌过期']}
        recoverable, terminal = classify(both)
        self.assertTrue(terminal)
        self.assertFalse(recoverable)


class ReloginFlagLifecycleTests(unittest.TestCase):
    """标记必须能被清除 —— 只置不清比不置更糟：它让用户去重扫一个正常账号。"""

    class FakeInstance:
        def __init__(self):
            self.needs_relogin = False
            self.relogin_reason = ''

        def mark_session_expired(self):
            self.needs_relogin = True
            self.relogin_reason = '闲鱼登录态已过期，请重新扫码登录'

        def on_token_success(self):
            self.needs_relogin = False
            self.relogin_reason = ''

    def test_flag_cleared_after_successful_refresh(self):
        inst = self.FakeInstance()
        inst.mark_session_expired()
        self.assertTrue(inst.needs_relogin)

        inst.on_token_success()

        self.assertFalse(inst.needs_relogin)
        self.assertEqual(inst.relogin_reason, '')

    def test_source_clears_flag_on_success(self):
        """源码层面确认：成功路径真的清了标记，而不是只在测试里模拟。"""
        import inspect
        import XianyuAutoAsync

        source = inspect.getsource(XianyuAutoAsync.XianyuLive.refresh_token)
        success_marker = 'self.last_token_refresh_status = "success"'
        self.assertIn(success_marker, source)

        after_success = source.split(success_marker, 1)[1]
        # 成功之后、函数返回 new_token 之前必须清标记
        upto_return = after_success.split('return new_token', 1)[0]
        self.assertIn('self.needs_relogin = False', upto_return,
                      "Token 刷新成功后没有清除「需重新扫码」标记")


if __name__ == "__main__":
    unittest.main()
