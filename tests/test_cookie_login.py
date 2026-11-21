import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.cookie_login import CookieLoginError, login_with_cookie, parse_login_cookie, verify_login_cookie


COOKIE = "unb=123456; cookie2=test-session; _m_h5_tk=test-token_123; extra=a=b%2Fc"


class CookieParsingTests(unittest.TestCase):
    def test_accepts_header_prefix_trailing_separator_and_encoded_values(self):
        fields = parse_login_cookie("Cookie: " + COOKIE + ";")
        self.assertEqual(fields["unb"], "123456")
        self.assertEqual(fields["extra"], "a=b%2Fc")

    def test_rejects_malformed_or_incomplete_input_without_echoing_it(self):
        for cookie in (
            "", "cookie2=private-value", "unb=abc; cookie2=private-value",
            "unb=123456; cookie2=", COOKIE + "; broken",
            COOKIE + "; cookie2=another-private-value", COOKIE + "\r\nInjected: secret",
            COOKIE + "; extra2=white space", COOKIE + "; quote=\"secret\"",
            COOKIE + "; oversized=" + "s" * 32768,
        ):
            with self.subTest(cookie_length=len(cookie)):
                with self.assertRaises(CookieLoginError) as error:
                    parse_login_cookie(cookie)
                self.assertNotIn("private-value", str(error.exception))
                self.assertNotIn("test-session", str(error.exception))


class CookieLoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rows = {}
        self.db = Mock()
        self.db.lock = threading.RLock()
        self.db.get_all_cookies.side_effect = lambda: {key: row["cookie"] for key, row in self.rows.items()}
        self.db.get_cookie_owner_user.side_effect = lambda key: self.rows[key]["owner"]
        self.db.get_cookie_status.side_effect = lambda key: self.rows[key].get("enabled", True)

        def save(key, cookie_value, user_id):
            self.rows.setdefault(key, {"owner": user_id})["cookie"] = cookie_value
            return True

        self.db.update_cookie_account_info.side_effect = save
        self.manager = Mock()
        self.manager.cookie_status = {}
        self.manager.ensure_cookie_task.return_value = None
        self.verifier = AsyncMock(side_effect=lambda cookie, _guard: cookie)
        self.verify_patch = patch("app.cookie_login.verify_login_cookie", self.verifier)
        self.verify_patch.start()
        self.addCleanup(self.verify_patch.stop)

    async def login(self, **kwargs):
        return await login_with_cookie(COOKIE, 7, self.db, self.manager, **kwargs)

    async def test_new_account_uses_verified_cookie_and_does_not_claim_listening(self):
        refreshed = COOKIE.replace("test-token", "refreshed-token")
        self.verifier.side_effect = None
        self.verifier.return_value = refreshed
        result = await self.login()
        self.assertTrue(result["is_new_account"])
        self.assertEqual(result["account_id"], "123456")
        self.assertEqual(self.rows["123456"]["cookie"], refreshed)
        self.manager.ensure_cookie_task.assert_called_once_with(
            "123456", refreshed, user_id=7, restart=True, save_to_db=False,
        )
        self.assertNotIn("监听成功", result["message"])
        self.assertNotIn("test-session", str(result))

    async def test_relogin_reuses_legacy_id_and_preserves_settings(self):
        self.rows["my-account"] = {"owner": 7, "cookie": COOKIE,
                                   "remark": "测试账号", "pause_duration": 10, "enabled": False}
        self.manager.cookie_status["my-account"] = False
        result = await self.login()
        self.assertFalse(result["is_new_account"])
        self.assertEqual(result["account_id"], "my-account")
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.rows["my-account"]["remark"], "测试账号")
        self.assertEqual(self.rows["my-account"]["pause_duration"], 10)
        self.assertFalse(result["connection_started"])
        self.assertFalse(self.manager.cookie_status["my-account"])
        # 相同 Cookie 也必须重启，才能恢复已结束的监听任务。
        self.assertTrue(self.manager.ensure_cookie_task.call_args.kwargs["restart"])

    async def test_invalid_cookie_does_not_replace_existing_login(self):
        self.rows["123456"] = {"owner": 7, "cookie": COOKIE}
        self.verifier.side_effect = CookieLoginError("Cookie 已失效")
        with self.assertRaises(CookieLoginError):
            await self.login()
        self.assertEqual(self.rows["123456"]["cookie"], COOKIE)
        self.db.update_cookie_account_info.assert_not_called()
        self.manager.ensure_cookie_task.assert_not_called()

    async def test_foreign_owner_is_rejected_before_contacting_xianyu(self):
        self.rows["someone-else"] = {"owner": 8, "cookie": COOKIE}
        with self.assertRaises(CookieLoginError) as error:
            await self.login()
        self.assertEqual(error.exception.status_code, 403)
        self.verifier.assert_not_awaited()
        self.db.update_cookie_account_info.assert_not_called()

    async def test_wrong_cookie_cannot_replace_target_account(self):
        self.rows["my-account"] = {"owner": 7, "cookie": "unb=999999; cookie2=old-session"}
        with self.assertRaisesRegex(CookieLoginError, "不一致"):
            await self.login(account_id="my-account")
        self.verifier.assert_not_awaited()

    async def test_id_collision_cannot_overwrite_different_account(self):
        self.rows["123456"] = {"owner": 7, "cookie": "unb=999999; cookie2=old-session"}
        with self.assertRaises(CookieLoginError):
            await self.login()
        self.db.update_cookie_account_info.assert_not_called()

    async def test_ownership_is_checked_again_after_verification(self):
        async def take_ownership(cookie, _guard):
            self.rows["new-binding"] = {"owner": 8, "cookie": COOKIE}
            return cookie

        self.verifier.side_effect = take_ownership
        with self.assertRaises(CookieLoginError) as error:
            await self.login()
        self.assertEqual(error.exception.status_code, 403)
        self.db.update_cookie_account_info.assert_not_called()

    async def test_manager_failure_reports_saved_login_and_connection_failure(self):
        self.manager.ensure_cookie_task.side_effect = RuntimeError("contains test-session")
        result = await self.login()
        self.assertTrue(result["success"])
        self.assertFalse(result["connection_started"])
        self.assertIn("监听启动失败", result["message"])
        self.assertNotIn("test-session", str(result))

    async def test_waits_for_local_manager_restart_not_long_lived_listener(self):
        async def restart():
            await asyncio.sleep(0)
            return "listener-created"

        task = asyncio.create_task(restart())
        self.manager.ensure_cookie_task.return_value = task
        await self.login()
        self.assertTrue(task.done())

    async def test_unavailable_manager_does_not_save_or_validate(self):
        with self.assertRaises(CookieLoginError) as error:
            await login_with_cookie(COOKIE, 7, self.db, None)
        self.assertEqual(error.exception.status_code, 503)
        self.verifier.assert_not_awaited()
        self.db.update_cookie_account_info.assert_not_called()


class OfficialCookieVerificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = Mock()
        self.client.cookies_str = COOKIE.replace("test-token", "refreshed-token")
        self.client._call_buyer = AsyncMock(return_value={"data": {"userId": "123456"}})
        self.context = AsyncMock()
        self.context.__aenter__.return_value = self.client
        self.client_patch = patch("utils.xianyu_seller_api.XianyuSellerAPI", return_value=self.context)
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    async def test_official_identity_and_refreshed_tokens_are_used(self):
        value = await verify_login_cookie(COOKIE, "test-guard")
        self.assertIn("refreshed-token", value)
        self.client._call_buyer.assert_awaited_once_with(
            "mtop.taobao.idlemessage.pc.loginuser.get", {}, timeout=10,
        )

    async def test_rejects_mismatched_identity(self):
        self.client._call_buyer.return_value = {"data": {"userId": "999999"}}
        with self.assertRaisesRegex(CookieLoginError, "账号身份"):
            await verify_login_cookie(COOKIE, "test-guard")

    async def test_upstream_errors_never_expose_credentials(self):
        from utils.xianyu_seller_api import SellerApiError

        for error, status in (
            (SellerApiError("test", ["FAIL_SYS_SESSION_EXPIRED::" + COOKIE]), 400),
            (SellerApiError("test", ["FAIL_SYS_USER_VALIDATE::" + COOKIE]), 409),
            (TimeoutError(COOKIE), 502),
        ):
            with self.subTest(status=status):
                self.client._call_buyer.side_effect = error
                with self.assertRaises(CookieLoginError) as caught:
                    await verify_login_cookie(COOKIE, "test-guard")
                self.assertEqual(caught.exception.status_code, status)
                self.assertNotIn("test-session", str(caught.exception))


class CookieLoginEndpointTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app import reply_server
        from app.db_manager import DBManager

        self.server = reply_server
        self.db = DBManager(":memory:")
        self.addCleanup(self.db.close)
        self.manager = Mock(cookie_status={})
        self.manager.ensure_cookie_task.return_value = None
        self.app = FastAPI()
        self.app.add_api_route("/cookie-login", reply_server.cookie_login, methods=["POST"])
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        patches = [
            patch.object(reply_server, "db_manager", self.db),
            patch.object(reply_server.cookie_manager, "manager", self.manager),
            patch("app.cookie_login.verify_login_cookie", AsyncMock(side_effect=lambda cookie, _guard: cookie)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def authenticate(self):
        self.app.dependency_overrides[self.server.get_current_user] = lambda: {"user_id": 1, "username": "tester"}

    def test_authentication_is_required(self):
        response = self.client.post("/cookie-login", json={"cookie": COOKIE})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("test-session", response.text)

    def test_real_database_relogin_preserves_account_settings(self):
        self.authenticate()
        self.db.save_cookie("legacy-id", COOKIE.replace("test-session", "old-session"), 1)
        self.db.conn.execute("UPDATE cookies SET remark=?, pause_duration=?, auto_confirm=? WHERE id=?",
                             ("保留备注", 15, 0, "legacy-id"))
        self.db.conn.commit()
        self.db.save_cookie_status("legacy-id", False)
        before = self.db.get_cookie_details("legacy-id")
        before["value"] = COOKIE

        response = self.client.post("/cookie-login", json={"cookie": COOKIE, "account_id": "legacy-id"})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["account_id"], "legacy-id")
        self.assertFalse(response.json()["enabled"])
        self.assertEqual(self.db.get_cookie_details("legacy-id"), before)
        self.assertEqual(len(self.db.get_all_cookies()), 1)
        self.assertNotIn("test-session", response.text)

    def test_malformed_requests_never_echo_input(self):
        self.authenticate()
        for payload in ({"cookie": {"private": COOKIE}}, [COOKIE], {"cookie": COOKIE, "account_id": [COOKIE]}):
            response = self.client.post("/cookie-login", json=payload)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn("test-session", response.text)
        response = self.client.post("/cookie-login", content='{"cookie":"' + COOKIE,
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("test-session", response.text)


if __name__ == "__main__":
    unittest.main()
