import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import reply_server


class QrLoginFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reply_server.qr_check_processed.clear()

    def tearDown(self):
        reply_server.qr_check_processed.clear()

    async def test_fast_persistence_returns_account_before_cookie_enhancement(self):
        manager = Mock()
        manager.add_cookie.return_value = None
        current_user = {"user_id": 7, "username": "tester"}

        with (
            patch.object(reply_server.db_manager, "get_all_cookies", return_value={}),
            patch.object(reply_server.db_manager, "save_cookie", return_value=True) as save_cookie,
            patch.object(reply_server.cookie_manager, "manager", manager),
        ):
            result = await reply_server.process_qr_login_cookies(
                "unb=account-1; cookie2=test-value",
                "account-1",
                current_user,
            )

        self.assertEqual(result["account_id"], "account-1")
        self.assertTrue(result["is_new_account"])
        self.assertEqual(result["cookie_field_count"], 2)
        save_cookie.assert_called_once()
        manager.add_cookie.assert_called_once()

    async def test_mismatched_account_identifier_is_rejected_before_save(self):
        current_user = {"user_id": 7, "username": "tester"}

        with patch.object(reply_server.db_manager, "save_cookie") as save_cookie:
            with self.assertRaisesRegex(ValueError, "账号标识不一致"):
                await reply_server.process_qr_login_cookies(
                    "unb=cookie-account; cookie2=test-value",
                    "response-account",
                    current_user,
                )

        save_cookie.assert_not_called()

    async def test_session_becomes_success_while_enhancement_is_still_running(self):
        session_id = "session-fast-success"
        enhancement_release = asyncio.Event()

        async def wait_for_release(**_):
            await enhancement_release.wait()

        account_info = {
            "account_id": "account-1",
            "is_new_account": True,
            "real_cookie_refreshed": False,
            "cookie_field_count": 2,
            "_manager_operation": None,
        }

        with (
            patch.object(
                reply_server,
                "process_qr_login_cookies",
                new=AsyncMock(return_value=account_info),
            ),
            patch.object(
                reply_server,
                "_enhance_qr_login_cookies",
                side_effect=wait_for_release,
            ),
        ):
            task = asyncio.create_task(
                reply_server._process_qr_login_session(
                    session_id,
                    {"cookies": "unb=account-1; cookie2=test-value", "unb": "account-1"},
                    {"user_id": 7, "username": "tester"},
                )
            )

            for _ in range(20):
                if session_id in reply_server.qr_check_processed:
                    break
                await asyncio.sleep(0)

            result = reply_server.qr_check_processed[session_id]["result"]
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["account_ready"])
            self.assertEqual(result["cookie_refresh_status"], "processing")
            self.assertFalse(task.done())

            enhancement_release.set()
            await task


if __name__ == "__main__":
    unittest.main()
