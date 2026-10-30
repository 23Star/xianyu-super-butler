# -*- coding: utf-8 -*-
"""买家送花自动收花（领花）单测。

修复的缺陷（均有生产实证）：
1. 原判定 ``'收到小红花' in send_message`` 永远不命中——买家送花卡片文本是
   「你人真不错，送你闲鱼小红花」，既不含「收到小红花」也不含任何数字，
   自动收花在线上从未触发过；
2. 原取号 ``re.findall(r'\\d{6,24}', send_message)`` 从消息文本抓数字，而
   订单号只在卡片按钮 targetUrl 的 orderId= 与 extJson.updateKey 里；
3. 领花回执卡片「已收到小红花」是自发消息（senderUserId=卖家本人），会混进
   自发消息分支触发 pause_chat，把该会话自动回复暂停 10 分钟——每自动领一朵
   花就把买家接下来几分钟的话全憋回去；
4. 回执卡片本身含「收到小红花」，在原判定下会被当成待收花消息重复调用接口。

fixture 用 tests/fixtures/flower_messages.json 里从生产 chat_message_archive
**逐字导出**的真实消息锁结构——手搓 fixture 曾按错误结构（message['10']）
造过，导致单测全绿而线上从不触发。
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 隔离：必须在 import app.* 之前把 DB_PATH 指到临时库，否则模块级
# db_manager 单例会连生产 data/xianyu_data.db。用 mkdtemp 不用
# TemporaryDirectory：SQLite 持锁会导致退出清理 WinError 32。
_TMP = tempfile.mkdtemp(prefix='flower-test-')
os.environ['DB_PATH'] = str(Path(_TMP) / 'test.db')

import logging

logging.disable(logging.CRITICAL)
try:
    from loguru import logger as _loguru_logger

    _loguru_logger.remove()
except Exception:  # pragma: no cover
    pass

from app.db_manager import DBManager
from XianyuAutoAsync import XianyuLive

COOKIE = 'acc-flower'
ORDER_ID = '5127876325109104901'
CHAT_ID = '67745913640'

# 被测方法在函数内 `from app.db_manager import db_manager`（模块级单例）。
# 单例绑哪个库取决于首次 import 时 DB_PATH 的取值，而 pytest 会先加载
# tests/conftest.py，不能依赖 import 顺序：自建临时库 DBManager，测试时把
# app.db_manager.db_manager 属性替换掉，保证写不碰生产 data/。
_METHOD_DB = DBManager(str(Path(_TMP) / 'method.db'))

_FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'flower_messages.json'


def _real(kind: str) -> dict:
    """从生产库逐字导出的真实消息（防 fixture 结构造假）。"""
    with open(_FIXTURE, encoding='utf-8') as f:
        return json.load(f)[kind]['raw_json']


def _buyer_flower_message(order_id=ORDER_ID, chat_id=CHAT_ID, with_button=True,
                          with_update_key=True):
    """买家送花卡片（contentType=26 dxCard），按**真实**结构构造：

    顶层键是 '1'/'3'；消息详情（bizTag/extJson/senderUserId）在
    message['1']['10']；卡片 JSON 在 message['1']['6']['3']['5']。
    """
    ex_content = {
        'title': '你人真不错，送你闲鱼小红花',
        'desc': '买卖换真心，鼓励你一下~',
    }
    if with_button:
        ex_content['button'] = {
            'text': '立即收下',
            'targetUrl': (
                'https://h5.m.goofish.com/wow/moyu/moyu-project/temp-pages/'
                f'red-flower-play?kun=true&opaque=false&role=seller'
                f'&confirm=false&orderId={order_id}'
            ),
        }
    card = {'contentType': 26, 'dxCard': {'item': {'main': {'exContent': ex_content}}}}
    ext = {'contentType': '26'}
    if with_update_key:
        ext['updateKey'] = f'{chat_id}:{order_id}:received_red_flower'
    return {
        '1': {
            '1': {'1': '2654984885@goofish'},
            '2': f'{chat_id}@goofish',
            '6': {'1': 101, '3': {'2': '你人真不错，送你闲鱼小红花', '4': 26,
                                  '5': json.dumps(card, ensure_ascii=False)}},
            '10': {
                'senderUserId': '2654984885',
                'bizTag': json.dumps(
                    {'sourceId': 'RED_FLOWER:6Vn9xthdWg5D',
                     'taskName': '收到小红花-卖家'}, ensure_ascii=False),
                'extJson': json.dumps(ext, ensure_ascii=False),
            },
        },
        '3': {'needPush': 'false'},
    }


def _live():
    """绕过 __init__ 的轻量实例：只挂本组方法用到的属性。"""
    live = XianyuLive.__new__(XianyuLive)
    live.cookie_id = COOKIE
    live.cookies_str = 'k=v'
    live._auto_received_flowers = set()
    return live


class _FakeApi:
    """替身卖家端 API：记录领花调用，可模拟接口报错。"""

    calls = []
    fail = False

    def __init__(self, cookie_id, cookies_str):
        self.cookie_id = cookie_id

    async def receive_flower(self, order_id):
        if _FakeApi.fail:
            raise RuntimeError('接口报错')
        _FakeApi.calls.append(order_id)
        return {}

    async def close(self):
        pass


class RealMessageShapeTests(unittest.TestCase):
    """用生产库逐字导出的真实消息锁结构。"""

    def setUp(self):
        self.live = _live()

    def test_real_buyer_card_yields_order_id(self):
        msg = _real('buyer')
        self.assertEqual(
            self.live._extract_flower_order_id(msg), '5127876325109104901')

    def test_real_buyer_card_is_not_confirmation(self):
        """真实买家送花卡片不是领花回执（senderUserId 是买家）。"""
        msg = _real('buyer')
        self.assertFalse(self.live._is_flower_confirmation_card(msg))

    def test_real_confirm_card_yields_no_order_id(self):
        """真实领花回执卡片：带 RED_FLOWER 但取不到订单号，不得触发领取。"""
        msg = _real('confirm')
        self.assertEqual(self.live._extract_flower_order_id(msg), '')

    def test_real_confirm_card_detected_as_confirmation(self):
        """真实领花回执卡片必须被识别为回执（用于跳过自动回复暂停）。"""
        msg = _real('confirm')
        self.assertTrue(self.live._is_flower_confirmation_card(msg))

    def test_real_buyer_card_update_key_fallback(self):
        """真实买家卡片去掉按钮 URL 后，走 extJson.updateKey 取号。"""
        msg = _real('buyer')
        card = json.loads(msg['1']['6']['3']['5'])
        del card['dxCard']['item']['main']['exContent']['button']
        msg['1']['6']['3']['5'] = json.dumps(card, ensure_ascii=False)
        self.assertEqual(
            self.live._extract_flower_order_id(msg), '5127876325109104901')

    def test_top_level_10_key_is_not_used(self):
        """回归防护：顶层塞一个 '10' 也不该被采用（真实结构在 message['1']['10']）。"""
        msg = _real('buyer')
        msg['10'] = {'bizTag': '{"sourceId":"RED_FLOWER:fake"}'}
        self.assertEqual(
            self.live._extract_flower_order_id(msg), '5127876325109104901')


class LegacyDetectionRegressionTests(unittest.TestCase):
    """锁死旧判定的缺陷，防止回归。"""

    def setUp(self):
        self.live = _live()

    def test_buyer_card_text_has_no_digit_and_no_keyword(self):
        """买家送花卡片文本既不含「收到小红花」也不含 6-24 位数字。

        这正是原判定（'收到小红花' in send_message + re.findall 数字）完全
        失效的原因——按文本判断这条链路永远不可能工作。
        """
        import re

        msg = _real('buyer')
        card = json.loads(msg['1']['6']['3']['5'])
        text = card['dxCard']['item']['main']['exContent']['title']
        self.assertNotIn('收到小红花', text)
        self.assertIsNone(next((m for m in re.findall(r'\d{6,24}', text)), None))

    def test_confirmation_card_would_match_old_keyword(self):
        """回执卡片含「收到小红花」——旧判定会把它当待收花消息重复调用。"""
        msg = _real('confirm')
        self.assertIn('收到小红花', msg['1']['6']['3']['5'] and
                      json.loads(msg['1']['6']['3']['5'])
                      ['dxCard']['item']['main']['exContent']['title'])
        # 新实现必须不把它当送花消息
        self.assertEqual(self.live._extract_flower_order_id(msg), '')


class SyntheticMessageTests(unittest.TestCase):
    """合成消息的边界行为（结构正确性由 RealMessageShapeTests 保证）。"""

    def setUp(self):
        self.live = _live()

    def test_buyer_flower_card_button_url(self):
        self.assertEqual(
            self.live._extract_flower_order_id(_buyer_flower_message()), ORDER_ID)

    def test_buyer_flower_card_update_key(self):
        msg = _buyer_flower_message(with_button=False)
        self.assertEqual(self.live._extract_flower_order_id(msg), ORDER_ID)

    def test_confirmation_card_not_claimable(self):
        """领取成功后的自侧确认卡片：带 RED_FLOWER，但没有订单号。"""
        msg = _buyer_flower_message(with_button=False, with_update_key=False)
        self.assertEqual(self.live._extract_flower_order_id(msg), '')

    def test_confirmation_card_detected(self):
        msg = _buyer_flower_message(with_button=False, with_update_key=False)
        self.assertTrue(self.live._is_flower_confirmation_card(msg))

    def test_plain_message_not_claimable(self):
        self.assertEqual(self.live._extract_flower_order_id({'1': {}, '3': {}}), '')
        self.assertEqual(self.live._extract_flower_order_id('not-a-dict'), '')
        self.assertEqual(self.live._extract_flower_order_id({}), '')

    def test_plain_message_not_confirmation(self):
        self.assertFalse(self.live._is_flower_confirmation_card({'1': {}, '3': {}}))
        self.assertFalse(self.live._is_flower_confirmation_card('not-a-dict'))
        self.assertFalse(self.live._is_flower_confirmation_card({}))


class AutoReceiveFlowerTests(unittest.IsolatedAsyncioTestCase):
    """自动领花行为：开关、去重、失败重试、风控冷却。"""

    @classmethod
    def setUpClass(cls):
        with _METHOD_DB.lock:
            _METHOD_DB.conn.execute(
                "INSERT OR REPLACE INTO cookies (id, value, user_id) VALUES (?, ?, ?)",
                (COOKIE, 'k=v', 1),
            )
            _METHOD_DB.conn.commit()
        _METHOD_DB.update_buyer_interaction_settings(
            COOKIE, auto_receive_flower_enabled=True)

    def setUp(self):
        self.live = _live()
        _FakeApi.calls = []
        _FakeApi.fail = False
        patcher = mock.patch('app.db_manager.db_manager', _METHOD_DB)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_receive_called_when_switch_on(self):
        with mock.patch('utils.xianyu_seller_api.XianyuSellerAPI', _FakeApi):
            ok = await self.live._auto_receive_flower(ORDER_ID)
        self.assertTrue(ok)
        self.assertEqual(_FakeApi.calls, [ORDER_ID])

    async def test_dedup_same_order(self):
        with mock.patch('utils.xianyu_seller_api.XianyuSellerAPI', _FakeApi):
            await self.live._auto_receive_flower(ORDER_ID)
            ok = await self.live._auto_receive_flower(ORDER_ID)
        self.assertFalse(ok)
        self.assertEqual(_FakeApi.calls, [ORDER_ID])

    async def test_skipped_when_switch_off(self):
        _METHOD_DB.update_buyer_interaction_settings(
            COOKIE, auto_receive_flower_enabled=False)
        try:
            with mock.patch('utils.xianyu_seller_api.XianyuSellerAPI', _FakeApi):
                ok = await self.live._auto_receive_flower(ORDER_ID)
        finally:
            _METHOD_DB.update_buyer_interaction_settings(
                COOKIE, auto_receive_flower_enabled=True)
        self.assertFalse(ok)
        self.assertEqual(_FakeApi.calls, [])

    async def test_failure_not_marked_and_retryable(self):
        _FakeApi.fail = True
        with mock.patch('utils.xianyu_seller_api.XianyuSellerAPI', _FakeApi):
            ok = await self.live._auto_receive_flower(ORDER_ID)
        self.assertFalse(ok)
        # 失败不登记：后续同订单消息可以重试
        _FakeApi.fail = False
        with mock.patch('utils.xianyu_seller_api.XianyuSellerAPI', _FakeApi):
            ok = await self.live._auto_receive_flower(ORDER_ID)
        self.assertTrue(ok)
        self.assertEqual(_FakeApi.calls, [ORDER_ID])

    async def test_skipped_when_risk_control_blocked(self):
        blocked = mock.Mock()
        blocked.is_blocked = True
        with mock.patch('utils.risk_control.registry.get', return_value=blocked):
            with mock.patch('utils.xianyu_seller_api.XianyuSellerAPI', _FakeApi):
                ok = await self.live._auto_receive_flower(ORDER_ID)
        self.assertFalse(ok)
        self.assertEqual(_FakeApi.calls, [])


if __name__ == '__main__':
    unittest.main()
