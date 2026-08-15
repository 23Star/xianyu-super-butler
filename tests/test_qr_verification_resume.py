"""扫码登录遇到手机验证（人脸/短信）后能否继续走到成功。

回归的是这个故障：用户扫码后被要求人脸验证，在手机上做完了，网页却一直停在
「请完成验证」。原因是监控协程一进验证态就 break，没有人再去轮询 query.do ——
而登录态恰恰是在验证完成后的那一轮响应里下发的。
"""

import asyncio
import unittest

from utils.qr_login import QRLoginManager, QRLoginSession


class FakeResponse:
    """模拟 newlogin/qrcode/query.do 的响应。"""

    def __init__(self, status, iframe=False, cookies=None, iframe_url=None):
        self._status = status
        self._iframe = iframe
        self._iframe_url = iframe_url or "https://passport.goofish.com/verify?x=1"
        self.cookies = cookies or {}

    def json(self):
        data = {"qrCodeStatus": self._status}
        if self._iframe:
            data["iframeRedirect"] = True
            data["iframeRedirectUrl"] = self._iframe_url
        return {"content": {"data": data}}


LOGGED_IN = {"unb": "22334455", "cookie2": "abc"}


class QrVerificationResumeTests(unittest.IsolatedAsyncioTestCase):
    async def _run_monitor(self, responses):
        """按脚本喂响应，跑完监控协程，返回 (manager, session, 是否出现过验证态)。"""
        manager = QRLoginManager()
        session = QRLoginSession("s1")
        manager.sessions["s1"] = session

        pending = iter(responses)
        saw_verification = False

        async def fake_poll(_session):
            try:
                return next(pending)
            except StopIteration:
                # 脚本放完后维持登录成功，避免协程空转到超时
                return FakeResponse("CONFIRMED", cookies=LOGGED_IN)

        manager._poll_qrcode_status = fake_poll

        task = asyncio.create_task(manager._monitor_qr_status("s1"))
        for _ in range(300):
            if session.status == "verification_required":
                saw_verification = True
            if task.done():
                break
            await asyncio.sleep(0.01)
        await asyncio.wait_for(task, timeout=10)

        return manager, session, saw_verification

    async def test_login_completes_after_user_finishes_phone_verification(self):
        # 连续 3 轮要求验证，之后用户完成验证，响应带回登录 Cookie
        manager, session, saw_verification = await self._run_monitor(
            [FakeResponse("CONFIRMED", iframe=True)] * 3
            + [FakeResponse("CONFIRMED", cookies=LOGGED_IN)]
        )

        self.assertTrue(saw_verification, "未进入验证态，用例没有覆盖到目标链路")
        self.assertEqual(manager.get_session_status("s1")["status"], "success")
        self.assertEqual(session.unb, "22334455")

    async def test_verification_extends_session_lifetime_once(self):
        _, session, _ = await self._run_monitor(
            [FakeResponse("CONFIRMED", iframe=True)] * 4
            + [FakeResponse("CONFIRMED", cookies=LOGGED_IN)]
        )

        # 人脸验证要掏手机、扫码、刷脸，原本 5 分钟不够；但只应延长一次
        self.assertEqual(session.expire_time, 600)
        self.assertTrue(session.verification_extended)

    async def test_blank_status_during_verification_is_not_treated_as_cancel(self):
        # 验证期间远端可能短暂返回空状态，不能当成"用户取消"把会话打死
        manager, _, _ = await self._run_monitor(
            [
                FakeResponse("CONFIRMED", iframe=True),
                FakeResponse(None),
                FakeResponse(None),
                FakeResponse("CONFIRMED", cookies=LOGGED_IN),
            ]
        )

        self.assertEqual(manager.get_session_status("s1")["status"], "success")

    async def test_plain_login_is_unaffected(self):
        manager, session, saw_verification = await self._run_monitor(
            [
                FakeResponse("NEW"),
                FakeResponse("SCANED"),
                FakeResponse("CONFIRMED", cookies=LOGGED_IN),
            ]
        )

        self.assertFalse(saw_verification)
        self.assertEqual(manager.get_session_status("s1")["status"], "success")
        # 没进验证态就不该延长会话寿命
        self.assertEqual(session.expire_time, 300)

    async def test_cancel_before_verification_still_ends_session(self):
        manager, _, _ = await self._run_monitor([FakeResponse("SCANED"), FakeResponse(None)])

        self.assertEqual(manager.get_session_status("s1")["status"], "cancelled")

    def test_verification_qr_code_is_generated_and_cached(self):
        manager = QRLoginManager()
        session = QRLoginSession("s2")
        session.status = "verification_required"
        session.verification_url = "https://passport.goofish.com/verify?x=1"
        manager.sessions["s2"] = session

        first = manager.get_session_status("s2")
        second = manager.get_session_status("s2")

        self.assertTrue(first["verification_qr_code_url"].startswith("data:image/png;base64,"))
        self.assertEqual(first["verification_url"], session.verification_url)
        # 前端每秒轮询，URL 没变就不该重复画图
        self.assertIs(
            first["verification_qr_code_url"],
            second["verification_qr_code_url"],
        )


if __name__ == "__main__":
    unittest.main()
