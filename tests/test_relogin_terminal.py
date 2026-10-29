"""Execute real XianyuLive methods without import-time DB/network/log side effects."""
import ast
import asyncio
import json
from pathlib import Path
import time
import types
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / 'XianyuAutoAsync.py'
METHODS = {
    '_safe_str', '_set_connection_state', '_is_relogin_terminal',
    '_relogin_cooldown_remaining', '_mark_relogin_required',
    '_clear_relogin_required', '_record_password_login_failure',
    '_notify_relogin_required', '_hold_relogin_terminal',
    '_try_password_login_refresh', 'refresh_token', 'token_refresh_loop', 'cookie_refresh_loop', 'main',
}


def load_live():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    state = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ConnectionState')
    live = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'XianyuLive')
    live.body = [n for n in live.body if (isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in {'_last_password_login_time', '_password_login_cooldown',
        '_password_login_fail_threshold', '_relogin_cooldown_seconds'} for t in n.targets)) or
                 isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in METHODS]
    from enum import Enum
    namespace = dict(Enum=Enum, asyncio=asyncio, time=time, json=json,
                     logger=mock.Mock(), WEBSOCKET_HEADERS={},
                     generate_sign=lambda *args: 'test-sign', SEC_CH_UA='test', CHROME_UA='test',
                     API_ENDPOINTS={'token': 'https://test.invalid/token'}, sys=__import__('sys'),
                     log_captcha_event=mock.Mock(),
                     trans_cookies=lambda value: dict(pair.strip().split('=', 1)
                                                     for pair in value.split(';') if '=' in pair))
    exec(compile(ast.Module(body=[state, live], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['XianyuLive'], namespace


class StopProbe(BaseException):
    pass


class ReloginTerminalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.Live, self.ns = load_live()
        self.live = self.Live()
        self.live.cookie_id = 'test-account'
        self.live.cookies_str = 'cookie2=old'
        self.live.cookies = {'cookie2': 'old'}
        self.live.connection_state = self.ns['ConnectionState'].DISCONNECTED
        self.live.connection_failures = 0
        self.live.needs_relogin = False
        self.live.relogin_reason = ''
        self.live.ws = None
        self.live.send_token_refresh_notification = mock.AsyncMock()
        self.live._update_cookies_and_restart = mock.AsyncMock(return_value=True)
        self.db = mock.Mock()
        self.db.get_cookie_details.return_value = {
            'cookie_value': 'cookie2=old', 'username': 'test-user', 'password': 'test-password',
        }
        self.slider = mock.Mock()
        self.slider.login_with_password_playwright.return_value = None
        modules = {
            'app.db_manager': types.SimpleNamespace(db_manager=self.db),
            'utils.xianyu_slider_stealth': types.SimpleNamespace(XianyuSliderStealth=mock.Mock(return_value=self.slider)),
            'app.cookie_manager': types.SimpleNamespace(manager=None),
        }
        patcher = mock.patch.dict('sys.modules', modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = 10000.0
        patcher = mock.patch.object(time, 'time', side_effect=lambda: self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def attempt(self):
        self.clock += 61
        return await self.live._try_password_login_refresh()

    async def test_three_real_failures_enter_terminal_and_fourth_never_launches_browser(self):
        for _ in range(3):
            self.assertFalse(await self.attempt())
        self.assertTrue(self.live.needs_relogin)
        self.assertEqual(self.live.password_login_failures, 3)
        self.assertEqual(self.live.connection_state, self.ns['ConnectionState'].FAILED)
        self.clock += 3600  # 冷却过期也不能自动启动第四次登录。
        self.assertFalse(await self.attempt())
        self.assertEqual(self.slider.login_with_password_playwright.call_count, 3)
        self.assertEqual(self.live.send_token_refresh_notification.await_count, 1)

    async def test_login_exception_counts_as_one_attempt(self):
        self.slider.login_with_password_playwright.side_effect = RuntimeError('browser failed')
        await self.attempt()
        self.assertEqual(getattr(self.live, 'password_login_failures', 0), 1)

    async def test_cancelled_login_is_not_counted_as_failed_credentials(self):
        self.slider.login_with_password_playwright.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.attempt()
        self.assertEqual(getattr(self.live, 'password_login_failures', 0), 0)
        self.assertFalse(self.live.needs_relogin)

    async def test_cooldown_skip_does_not_count_failure(self):
        await self.attempt()
        await self.live._try_password_login_refresh()
        self.assertEqual(getattr(self.live, 'password_login_failures', 0), 1)
        self.assertEqual(self.slider.login_with_password_playwright.call_count, 1)

    async def test_missing_credentials_does_not_count_browser_failure(self):
        self.db.get_cookie_details.return_value['password'] = ''
        await self.attempt()
        self.assertEqual(getattr(self.live, 'password_login_failures', 0), 0)
        self.assertFalse(self.live.needs_relogin)
        self.slider.login_with_password_playwright.assert_not_called()

    async def test_late_browser_success_cannot_unlock_new_manual_terminal(self):
        def login(**kwargs):
            self.live._mark_relogin_required('another attempt reached terminal')
            return {'cookie2': 'late'}
        self.slider.login_with_password_playwright.side_effect = login
        self.assertFalse(await self.attempt())
        self.assertTrue(self.live.needs_relogin)
        self.live._update_cookies_and_restart.assert_not_awaited()

    async def test_success_breaks_failure_streak(self):
        await self.attempt()
        self.slider.login_with_password_playwright.return_value = {'cookie2': 'new'}
        self.assertTrue(await self.attempt())
        self.assertEqual(getattr(self.live, 'password_login_failures', -1), 0)
        self.assertFalse(self.live.needs_relogin)

    async def session_expired_response(self):
        live = self.live
        live.max_captcha_verification_count = 3
        live.last_message_received_time = 0
        live.device_id = 'test-device'
        live._need_captcha_verification = lambda payload: False
        response = mock.Mock()
        response.headers = {}
        response.status = 200
        response.json = mock.AsyncMock(return_value={'ret': ['FAIL_SYS_SESSION_EXPIRED::Session过期']})
        response_cm = mock.MagicMock()
        response_cm.__aenter__.return_value = response
        session = mock.Mock()
        session.post.return_value = response_cm
        session_cm = mock.MagicMock()
        session_cm.__aenter__.return_value = session
        guard = mock.Mock(is_blocked=False)
        risk = types.SimpleNamespace(registry=types.SimpleNamespace(get=lambda _: guard))
        aiohttp = types.SimpleNamespace(ClientSession=lambda: session_cm, ClientTimeout=lambda **kwargs: None)
        self.ns['aiohttp'] = aiohttp
        with mock.patch.dict('sys.modules', {'utils': types.SimpleNamespace(risk_control=risk)}):
            self.assertIsNone(await live.refresh_token())

    async def test_session_expired_without_credentials_enters_manual_terminal(self):
        self.db.get_cookie_details.return_value['password'] = ''
        await self.session_expired_response()
        self.assertTrue(self.live.needs_relogin)
        self.assertEqual(self.live.last_token_refresh_status, 'relogin_required')
        self.assertEqual(self.live.connection_state, self.ns['ConnectionState'].FAILED)
        self.slider.login_with_password_playwright.assert_not_called()

    async def test_session_expired_first_browser_failure_is_not_terminal(self):
        await self.session_expired_response()
        self.assertFalse(self.live.needs_relogin)
        self.assertEqual(self.live.password_login_failures, 1)

    async def test_session_expired_during_cooldown_is_not_manual_terminal(self):
        self.Live._last_password_login_time[self.live.cookie_id] = self.clock
        await self.session_expired_response()
        self.assertFalse(self.live.needs_relogin)
        self.slider.login_with_password_playwright.assert_not_called()

    async def test_cookie_update_failure_after_browser_success_is_not_manual_terminal(self):
        self.slider.login_with_password_playwright.return_value = {'cookie2': 'new'}
        self.live._update_cookies_and_restart.return_value = False
        await self.session_expired_response()
        self.assertFalse(self.live.needs_relogin)
        self.assertEqual(self.live.password_login_failures, 0)

    async def test_successful_token_refresh_resets_failure_streak(self):
        await self.token_success_response(False)

    async def test_inflight_token_success_cannot_unlock_new_manual_terminal(self):
        await self.token_success_response(True)

    async def token_success_response(self, enter_terminal):
        live = self.live
        live.password_login_failures = 2
        live.connection_failures = 4
        live.max_captcha_verification_count = 3
        live.last_message_received_time = 0
        live.device_id = 'test-device'
        response = mock.Mock(headers={}, status=200)
        async def payload():
            if enter_terminal:
                live._mark_relogin_required('new manual terminal')
            return {'ret': ['SUCCESS::调用成功'], 'data': {'accessToken': 'new-token'}}
        response.json = payload
        response_cm = mock.MagicMock()
        response_cm.__aenter__.return_value = response
        session = mock.Mock()
        session.post.return_value = response_cm
        session_cm = mock.MagicMock()
        session_cm.__aenter__.return_value = session
        risk = types.SimpleNamespace(registry=types.SimpleNamespace(get=lambda _: mock.Mock(is_blocked=False)))
        self.ns['aiohttp'] = types.SimpleNamespace(ClientSession=lambda: session_cm, ClientTimeout=lambda **kwargs: None)
        with mock.patch.dict('sys.modules', {'utils': types.SimpleNamespace(risk_control=risk)}):
            result = await live.refresh_token()
        if enter_terminal:
            self.assertIsNone(result)
            self.assertTrue(live.needs_relogin, 'late automatic response unlocked manual terminal')
            return
        self.assertEqual(result, 'new-token')
        self.assertEqual(live.password_login_failures, 0)
        self.assertEqual(live.connection_failures, 4, 'Token success must not reset failed WS initialization')
        self.assertFalse(live.needs_relogin)

    async def test_background_loop_does_not_send_retry_notice_after_terminal(self):
        self.live.token_refresh_interval = 1
        self.live.last_token_refresh_time = 0
        self.live.token_retry_interval = 600
        self.live.ws = types.SimpleNamespace(closed=False, close=mock.AsyncMock())
        async def refresh():
            self.live._mark_relogin_required('manual login required')
            return None
        self.live.refresh_token = refresh
        self.live._interruptible_sleep = mock.AsyncMock(side_effect=StopProbe())
        try:
            await self.live.token_refresh_loop()
        except StopProbe:
            self.fail('terminal background loop kept scheduling retries')
        self.live.send_token_refresh_notification.assert_not_awaited()
        self.live.ws.close.assert_awaited_once()

    async def test_cookie_loop_cancellation_cancels_inflight_browser_child(self):
        live = self.live
        live.cookie_refresh_enabled = True
        live.last_cookie_refresh_time = 0
        live.cookie_refresh_interval = 1
        live.last_message_received_time = 0
        live.message_cookie_refresh_cooldown = 0
        live.cookie_refresh_lock = asyncio.Lock()
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def refresh(_):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        live._execute_cookie_refresh = refresh
        async def sleep(_):
            await asyncio.sleep(3600)
        live._interruptible_sleep = sleep
        before = set(asyncio.all_tasks())
        loop_task = asyncio.create_task(live.cookie_refresh_loop())
        try:
            await asyncio.wait_for(started.wait(), 1)
            loop_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await loop_task
            self.assertTrue(cancelled.is_set(), 'browser refresh outlived cancelled periodic task')
        finally:
            remaining = set(asyncio.all_tasks()) - before
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)

    async def test_terminal_blocks_token_network_even_after_cooldown(self):
        self.live._mark_relogin_required('manual login required')
        self.clock += 3600
        client = mock.Mock(side_effect=AssertionError('terminal must not request token'))
        self.ns['aiohttp'] = types.SimpleNamespace(ClientSession=client)
        self.assertIsNone(await self.live.refresh_token())
        self.assertEqual(self.live.last_token_refresh_status, 'relogin_required')
        self.assertTrue(self.live.needs_relogin)
        client.assert_not_called()

    async def test_manual_cookie_update_releases_hold_but_elapsed_time_alone_does_not(self):
        self.live._mark_relogin_required('manual login required')
        self.clock += 3600
        self.live._cancel_background_tasks = mock.AsyncMock()
        sleeps = []
        async def wait(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1:
                self.assertTrue(self.live.needs_relogin)
                self.db.get_cookie_details.return_value['cookie_value'] = 'cookie2=manual'
            elif len(sleeps) > 2:
                raise StopProbe()
        self.live._interruptible_sleep = wait
        try:
            await self.live._hold_relogin_terminal()
        except StopProbe:
            self.fail('manual Cookie update never released terminal')
        self.assertFalse(self.live.needs_relogin)
        self.assertEqual(self.live.cookies, {'cookie2': 'manual'})
        self.assertEqual(self.live.password_login_failures, 0)
        self.assertEqual(self.live.connection_state, self.ns['ConnectionState'].DISCONNECTED)

    async def test_connection_failure_loop_keeps_streak_instead_of_restarting_instance(self):
        live = self.live
        live.max_connection_failures = 1
        live.base_url = 'wss://test.invalid'
        live.current_token = None
        live.background_tasks = set()
        for name in ('heartbeat_task', 'token_refresh_task', 'cleanup_task', 'cookie_refresh_task'):
            setattr(live, name, None)
        live.create_session = mock.AsyncMock()
        live.close_session = mock.AsyncMock()
        live._unregister_instance = mock.Mock()
        live._cancel_background_tasks = mock.AsyncMock()
        live._reset_background_tasks = mock.Mock()
        live._calculate_retry_delay = lambda _: 1
        live._create_websocket_connection = mock.AsyncMock(side_effect=RuntimeError('connect failed'))
        live._restart_instance = mock.AsyncMock(side_effect=StopProbe())
        async def wait(seconds):
            self.clock += 61
            if live.needs_relogin:
                raise StopProbe()
        live._interruptible_sleep = wait
        with mock.patch.object(asyncio, 'sleep', side_effect=wait):
            with self.assertRaises(StopProbe):
                await live.main()
        self.assertTrue(live.needs_relogin, 'main restarted before failure streak reached threshold')
        self.assertEqual(live.password_login_failures, 3)
        live._restart_instance.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
