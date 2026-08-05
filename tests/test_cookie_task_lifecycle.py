import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.cookie_manager import CookieManager


class CookieTaskLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_patch = patch("app.cookie_manager.db_manager")
        self.db = self.db_patch.start()
        self.db.get_all_cookies.return_value = {}
        self.db.get_all_keywords.return_value = {}
        self.db.get_all_cookie_status.return_value = {}
        self.db.get_cookie_details.return_value = {"user_id": 7}
        self.manager = CookieManager(asyncio.get_running_loop())

        async def wait_forever(*_args, **_kwargs):
            await asyncio.sleep(3600)

        self.manager._run_xianyu = AsyncMock(side_effect=wait_forever)

    async def asyncTearDown(self):
        for task in self.manager.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.manager.tasks.values(), return_exceptions=True)
        self.db_patch.stop()

    async def test_new_account_task_is_registered(self):
        task = await self.manager._ensure_cookie_task_async("account-1", "cookie")

        self.assertIs(task, self.manager.tasks["account-1"])
        self.assertEqual(self.manager.get_task_state("account-1"), "running")

    async def test_running_task_can_be_restarted(self):
        first_task = await self.manager._ensure_cookie_task_async("account-1", "cookie")
        second_task = await self.manager._ensure_cookie_task_async(
            "account-1", "new-cookie", restart=True
        )

        self.assertTrue(first_task.cancelled())
        self.assertIs(second_task, self.manager.tasks["account-1"])
        self.assertEqual(self.manager.cookies["account-1"], "new-cookie")

    async def test_disabled_account_updates_cookie_without_starting(self):
        self.manager.cookie_status["account-1"] = False

        task = await self.manager._ensure_cookie_task_async("account-1", "cookie")

        self.assertIsNone(task)
        self.assertNotIn("account-1", self.manager.tasks)
        self.assertEqual(self.manager.cookies["account-1"], "cookie")

    async def test_completed_task_can_start_again(self):
        completed = asyncio.create_task(asyncio.sleep(0))
        await completed
        self.manager.tasks["account-1"] = completed
        self.manager.cookies["account-1"] = "cookie"

        restarted = await self.manager._ensure_cookie_task_async("account-1")

        self.assertIsNot(restarted, completed)
        self.assertEqual(self.manager.get_task_state("account-1"), "running")


if __name__ == "__main__":
    unittest.main()
