"""商品同步：没有分组的账号不能被判成失败。

回归的是这个故障：某账号的分组发现接口返回 `itemGroupList: None`，代码在
「先拿分组、再用 groupId 查列表」的第一步就返回 {'error': ...}，上层按
`not result.get('success')` 抛 HTTP 502，用户只看到一句
「Request failed with status code 502」。

而实测那次响应里 cardList 已经带着这个账号的 17 件商品 —— 数据早在手上，
只是没有分组信息。totalCount 还谎报 0。

同时固定另一个同类隐患：只有正常路径设了 `'success': True`，所有提前返回都没设，
所以「所有分组均为 0 件」这个早就存在的分支同样会 502。
"""

import asyncio
import json
import unittest

from XianyuAutoAsync import XianyuLive

COOKIES = 'unb=123456; _m_h5_tk=abc_1700000000000; _m_h5_tk_enc=x; cookie2=y'


def make_card(item_id, title='商品', price='9.9'):
    """构造一个与真实响应同构的最小 cardList 元素。"""
    return {
        'cardType': 1000,
        'cardData': {
            'auctionType': 'b',
            'categoryId': 50023914,
            'itemId': item_id,
            'title': title,
            'priceInfo': {'price': price},
            'detailParams': {'itemId': item_id, 'title': title},
        },
    }


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status = 200
        self.headers = {}
        self.cookies = {}

    async def json(self, *args, **kwargs):
        return self._payload

    async def text(self):
        return json.dumps(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    """按调用顺序回放预设响应，并记下每次请求的 data。"""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.requests = []

    async def close(self):
        return None

    def post(self, url, params=None, data=None, **kwargs):
        self.requests.append(json.loads(data['data']) if data else None)
        payload = self._payloads.pop(0) if self._payloads else {'ret': ['SUCCESS::调用成功'], 'data': {}}
        return _FakeResponse(payload)


def build_live(payloads):
    live = XianyuLive(cookies_str=COOKIES, cookie_id='acc', user_id=1)
    live.session = _FakeSession(payloads)

    # 入库会顺带用浏览器逐个抓商品详情。这里只验证同步的判定逻辑，
    # 打桩掉它，免得测试真去开 Chromium（实测会拖到 30 秒以上）。
    async def fake_save(items_list):
        return len(items_list or [])

    live.save_items_list_to_db = fake_save
    return live


def run(coro):
    return asyncio.run(coro)


class NoItemGroupTests(unittest.TestCase):
    """分组为空，但响应里带着商品。"""

    def test_items_in_discovery_response_are_used(self):
        payload = {
            'ret': ['SUCCESS::调用成功'],
            'data': {
                'itemGroupList': None,
                'totalCount': 0,          # 闲鱼这里会谎报 0
                'nextPage': False,
                'cardList': [make_card('1073694491706'), make_card('1075377269288')],
            },
        }
        live = build_live([payload])
        try:
            result = run(live.get_item_list_info(1, 20))
        finally:
            run(live.close_session())

        self.assertTrue(result.get('success'), f"被判成失败: {result.get('error')}")
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(result['current_count'], 2)
        self.assertNotIn('error', result)

    def test_missing_group_key_behaves_the_same(self):
        """实测真实响应里 itemGroupList 这个键是缺失的，不是显式 null。
        两种形态都要走同一条兜底路径。"""
        payload = {
            'ret': ['SUCCESS::调用成功'],
            'data': {'totalCount': 0, 'cardList': [make_card('1'), make_card('2')]},
        }
        live = build_live([payload])
        try:
            result = run(live.get_item_list_info(1, 20))
        finally:
            run(live.close_session())

        self.assertTrue(result.get('success'))
        self.assertEqual(len(result['items']), 2)

    def test_no_second_request_is_made(self):
        """没有 groupId 可用，不该再去查一次列表接口。"""
        payload = {
            'ret': ['SUCCESS::调用成功'],
            'data': {'itemGroupList': None, 'totalCount': 0, 'cardList': [make_card('1')]},
        }
        live = build_live([payload])
        session = live.session   # close_session() 会把 live.session 置空
        try:
            run(live.get_item_list_info(1, 20))
        finally:
            run(live.close_session())

        self.assertEqual(len(session.requests), 1)
        self.assertTrue(session.requests[0]['needGroupInfo'])

    def test_lying_total_count_is_reconciled(self):
        payload = {
            'ret': ['SUCCESS::调用成功'],
            'data': {'itemGroupList': None, 'totalCount': 0,
                     'cardList': [make_card('1'), make_card('2'), make_card('3')]},
        }
        live = build_live([payload])
        try:
            result = run(live.get_item_list_info(1, 20))
        finally:
            run(live.close_session())

        self.assertEqual(result['total_count'], 3)
        self.assertEqual(result['api_total_count'], 0)
        self.assertTrue(result['count_reconciled'])

    def test_empty_groups_without_items_is_success_but_not_confirmed(self):
        """连商品也没有：算成功的空同步，但不能确认为空 ——
        confirmed_empty 会让上层把库里已有商品全标成已下架。"""
        payload = {
            'ret': ['SUCCESS::调用成功'],
            'data': {'itemGroupList': None, 'totalCount': 0, 'cardList': []},
        }
        live = build_live([payload])
        try:
            result = run(live.get_item_list_info(1, 20))
        finally:
            run(live.close_session())

        self.assertTrue(result.get('success'))
        self.assertEqual(result['items'], [])
        self.assertFalse(
            result['confirmed_empty'],
            "分组为空也可能是接口抖动，不能据此清空商品状态"
        )


class AllGroupsEmptyTests(unittest.TestCase):
    """分组存在但都是 0 件 —— 这个分支原先也漏了 success。"""

    def test_success_flag_is_present(self):
        payload = {
            'ret': ['SUCCESS::调用成功'],
            'data': {
                'itemGroupList': [
                    {'groupName': '在售', 'groupId': 1, 'itemNumber': 0},
                    {'groupName': '已下架', 'groupId': 2, 'itemNumber': 0},
                ],
                'totalCount': 0,
            },
        }
        live = build_live([payload])
        try:
            result = run(live.get_item_list_info(1, 20))
        finally:
            run(live.close_session())

        self.assertTrue(result.get('success'), "缺少 success 会被上层抛成 502")
        self.assertEqual(result['items'], [])

    def test_confirmed_empty_is_true_here(self):
        """闲鱼明确回了分组、且都是 0 件，这才算确认为空。"""
        payload = {
            'ret': ['SUCCESS::调用成功'],
            'data': {
                'itemGroupList': [{'groupName': '在售', 'groupId': 1, 'itemNumber': 0}],
                'totalCount': 0,
            },
        }
        live = build_live([payload])
        try:
            result = run(live.get_item_list_info(1, 20))
        finally:
            run(live.close_session())

        self.assertTrue(result['confirmed_empty'])


class SuccessKeyContractTests(unittest.TestCase):
    """上层只认 success，任何「成功但没商品」的返回都必须带齐字段。"""

    REQUIRED = (
        'success', 'items', 'current_count', 'total_count', 'api_total_count',
        'group_declared_count', 'count_reconciled', 'saved_count', 'next_page',
        'confirmed_empty', 'group_name', 'account_id',
    )

    def test_empty_result_has_all_keys_upstream_reads(self):
        payload = {
            'ret': ['SUCCESS::调用成功'],
            'data': {'itemGroupList': None, 'totalCount': 0, 'cardList': []},
        }
        live = build_live([payload])
        try:
            result = run(live.get_item_list_info(1, 20))
        finally:
            run(live.close_session())

        missing = [k for k in self.REQUIRED if k not in result]
        self.assertEqual(missing, [], f"缺少字段: {missing}")


if __name__ == '__main__':
    unittest.main()
