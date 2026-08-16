"""账号请求去重与连接健康检查。

回归两类会把界面拖住或打到限流的问题：

1. 会话/消息列表在前端轮询，多标签页并发时同一份数据被反复透传到闲鱼，
   账号很快被打到限流（429 flow controled）。
2. 浏览器标签页长期挂后台后 WebSocket 进入"半开"（TCP 还连着、应用层已不通），
   此时发请求会一路等到超时：内层 15 秒 + 外层 25 秒，用户要等约 40 秒才看到 504。
"""

import asyncio
import unittest

from app.reply_server import _AccountRequestDedup, _is_account_connection_alive


class FakeState:
    def __init__(self, value):
        self.value = value


class FakeWebSocket:
    def __init__(self, closed=False):
        self.closed = closed


class FakeInstance:
    def __init__(self, state='connected', ws=None):
        self.connection_state = FakeState(state)
        self.ws = ws


class ConnectionAliveTests(unittest.TestCase):
    def test_connected_with_open_socket_is_alive(self):
        instance = FakeInstance('connected', FakeWebSocket(closed=False))
        self.assertTrue(_is_account_connection_alive(instance))

    def test_half_open_socket_is_not_alive(self):
        # 状态说 connected，但连接已被对端关闭 —— 这正是"半开"，
        # 只看 connection_state 会把它当成可用，然后卡 40 秒
        instance = FakeInstance('connected', FakeWebSocket(closed=True))
        self.assertFalse(_is_account_connection_alive(instance))

    def test_missing_socket_is_not_alive(self):
        self.assertFalse(_is_account_connection_alive(FakeInstance('connected', None)))

    def test_reconnecting_state_is_not_alive(self):
        instance = FakeInstance('reconnecting', FakeWebSocket(closed=False))
        self.assertFalse(_is_account_connection_alive(instance))

    def test_socket_without_closed_attribute_is_treated_as_alive(self):
        class NoClosedFlag:
            pass

        # 不同 websockets 版本属性不一致，缺失时不能误判为断开
        instance = FakeInstance('connected', NoClosedFlag())
        self.assertTrue(_is_account_connection_alive(instance))


class RequestDedupTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_identical_requests_run_once(self):
        dedup = _AccountRequestDedup()
        calls = 0

        async def factory():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return {'ok': True}

        results = await asyncio.gather(*[dedup.run('same-key', factory) for _ in range(10)])

        # 10 个并发请求只应向闲鱼发一次
        self.assertEqual(calls, 1)
        self.assertTrue(all(r == {'ok': True} for r in results))

    async def test_result_is_cached_within_ttl(self):
        dedup = _AccountRequestDedup()
        calls = 0

        async def factory():
            nonlocal calls
            calls += 1
            return {'n': calls}

        first = await dedup.run('k', factory)
        second = await dedup.run('k', factory)

        self.assertEqual(calls, 1)
        self.assertEqual(first, second)

    async def test_different_keys_are_not_shared(self):
        dedup = _AccountRequestDedup()
        calls = 0

        async def factory():
            nonlocal calls
            calls += 1
            return calls

        await dedup.run('a', factory)
        await dedup.run('b', factory)

        self.assertEqual(calls, 2)

    async def test_throttled_result_gets_longer_ttl(self):
        dedup = _AccountRequestDedup()

        async def factory():
            return {'reason': 'flow controled'}

        await dedup.run('k', factory)
        expire_at, _ = dedup._cache['k']

        # 命中限流时要缓存更久，避免继续冲击已被限流的账号
        import time
        remaining = expire_at - time.monotonic()
        self.assertGreater(remaining, _AccountRequestDedup.NORMAL_TTL)

    async def test_exception_is_not_cached(self):
        dedup = _AccountRequestDedup()
        calls = 0

        async def factory():
            nonlocal calls
            calls += 1
            raise RuntimeError('boom')

        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await dedup.run('k', factory)

        # 失败不能被缓存，否则一次偶发错误会把接口"锁死"整个 TTL
        self.assertEqual(calls, 2)
        self.assertNotIn('k', dedup._cache)

    async def test_cache_is_pruned(self):
        dedup = _AccountRequestDedup()

        async def factory():
            return 1

        for i in range(_AccountRequestDedup.MAX_ENTRIES + 20):
            await dedup.run(f'key-{i}', factory)

        self.assertLessEqual(len(dedup._cache), _AccountRequestDedup.MAX_ENTRIES)


if __name__ == '__main__':
    unittest.main()
