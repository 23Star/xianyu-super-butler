# -*- coding: utf-8 -*-
"""fresh-captcha-url 端点的熔断解除接线测试。

用户手动过完滑块后「账号卡片迟迟不恢复」的根因：服务端仍按冷却期拒绝一切
主动请求，令牌永远拿不到，「请求成功 → 解除熔断」这条链走不通。修复=端点
拿到 punish 链接时立即 reset 该账号熔断，让心跳恢复探测。本测试锁住这条
接线，防止将来重构时悄悄断掉。
"""
import asyncio
import unittest
from unittest import mock

from app.reply_server import get_fresh_captcha_url


class _AsyncCM:
    """把一个已构造好的值包成 async with 上下文。"""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc_info):
        return False


def _make_aiohttp(payload):
    """伪造 aiohttp.ClientSession，post 任意参数都返回同一份 payload。"""
    response = mock.MagicMock()
    response.json = mock.AsyncMock(return_value=payload)
    session = mock.MagicMock()
    session.post = mock.MagicMock(return_value=_AsyncCM(response))
    return mock.MagicMock(return_value=_AsyncCM(session))


class FreshCaptchaUnblockTests(unittest.TestCase):
    def _run(self, payload, cookie_id='cid-1'):
        with mock.patch('aiohttp.ClientSession', _make_aiohttp(payload)), \
             mock.patch('app.reply_server.db_manager') as db, \
             mock.patch('utils.xianyu_utils.trans_cookies',
                        return_value={'_m_h5_tk': 'tk_abc'}), \
             mock.patch('utils.risk_control.registry') as registry:
            db.get_all_cookies.return_value = {cookie_id: '_m_h5_tk=tk_abc; x=1'}
            guard = registry.get.return_value
            result = asyncio.run(get_fresh_captcha_url(
                cookie_id, {'user_id': 7, 'username': 'alice'},
            ))
        return result, registry, guard

    def test_punish_link_clears_risk_block(self):
        result, registry, guard = self._run({
            'data': {'url': 'https://login.taobao.com/jump?punish=x5secdata&action=captcha'},
        })
        self.assertTrue(result['need_verify'], result)
        self.assertIn('punish', result['verification_url'])
        registry.get.assert_called_once_with('cid-1')
        guard.reset.assert_called_once()

    def test_already_recovered_skips_reset(self):
        """令牌接口直接给了 accessToken 说明风控已解除，不需要再动熔断。"""
        result, registry, guard = self._run({
            'data': {'accessToken': 'tok-ok'},
        })
        self.assertFalse(result['need_verify'], result)
        guard.reset.assert_not_called()


if __name__ == '__main__':
    unittest.main()
