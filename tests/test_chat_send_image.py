"""管家对话框发送图片：XianyuLive.send_im_image + POST /chat/send-image/{cookie_id}

覆盖：
- 本地文件先经 ImageUploader 上传闲鱼 CDN，再以 contentType=2 发出（走
  _send_im_request 请求/响应通道等回执，而不是老 send_image_msg 的 fire-and-forget）
- 已是 CDN 地址时跳过上传
- 上传失败 / 服务端回 reason 时抛错（调用方不能误以为发出去了）
- 端点：鉴权、非图片与超限 400、临时文件在调用期间存在且调用后被清理
"""

import asyncio
import base64
import json
import os
import tempfile
import unittest
from unittest import mock

# 必须先于 fastapi 导入：fastapi 的依赖链会加载 site-packages 里的 utils.py，
# 之后本地 utils 包（image_uploader 等）就再也 Import 不到了。
from XianyuAutoAsync import XianyuLive

from fastapi import HTTPException
from fastapi.testclient import TestClient

COOKIES_STR = "unb=10001; cookie2=abcdefg"
CID = "chat-1"
TOID = "20002"
CDN_URL = "https://img.alicdn.com/imgextra/i3/2f0a1b2c3d4e5f60718293a4b5c/.jpg"


def build_live() -> XianyuLive:
    """直接构造实例：只用到 cookies_str / myid / cookie_id / _send_im_request。"""
    return XianyuLive(cookies_str=COOKIES_STR, cookie_id="acc", user_id=1)


class _FakeUploader:
    """替身 ImageUploader：记录上传路径，按 result 返回 CDN 地址。"""

    def __init__(self, result: str = CDN_URL):
        self.result = result
        self.uploaded_paths = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def upload_image(self, image_path):
        self.uploaded_paths.append(image_path)
        return self.result


def _decode_image_payload(envelope):
    """把信封里 base64 的 content.custom.data 还原成闲鱼图片消息结构。"""
    return json.loads(base64.b64decode(envelope["content"]["custom"]["data"]).decode("utf-8"))


class SendImImageTests(unittest.TestCase):
    """XianyuLive.send_im_image 的行为。"""

    def setUp(self):
        self.live = build_live()
        self.sent = []

        async def fake_send_im_request(lwp, body, timeout=15):
            self.sent.append((lwp, body))
            return {"headers": {"mid": "m1"}, "body": {"messageId": "mid-1"}}

        self.live._send_im_request = fake_send_im_request

    def _temp_image(self, content=b"fake-png-bytes", suffix=".png"):
        fd, path = tempfile.mkstemp(prefix="test-image-", suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
        except Exception:
            os.unlink(path)
            raise
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def _patch_uploader(self, uploader):
        patcher = mock.patch(
            "utils.image_uploader.ImageUploader", lambda cookies_str: uploader
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_local_file_is_uploaded_then_sent_as_image_message(self):
        image_path = self._temp_image()
        uploader = _FakeUploader()
        self._patch_uploader(uploader)

        with mock.patch("utils.image_utils.image_manager") as image_manager:
            image_manager.get_image_size.return_value = (320, 240)
            asyncio.run(self.live.send_im_image(CID, TOID, image_path))

        # 先上传到闲鱼 CDN
        self.assertEqual(uploader.uploaded_paths, [image_path])
        # 再走请求/响应发出去，且只发一次
        self.assertEqual(len(self.sent), 1)
        lwp, body = self.sent[0]
        self.assertEqual(lwp, "/r/MessageSend/sendByReceiverScope")

        envelope, receivers = body
        payload = _decode_image_payload(envelope)
        self.assertEqual(payload["contentType"], 2)
        pic = payload["image"]["pics"][0]
        self.assertEqual(pic["url"], CDN_URL)
        self.assertEqual((pic["width"], pic["height"]), (320, 240))
        # 信封与 send_im_text 同形：custom 包装 + 收件人含买家和自己
        self.assertEqual(envelope["content"]["contentType"], 101)
        self.assertEqual(envelope["cid"], f"{CID}@goofish")
        self.assertEqual(
            receivers["actualReceivers"],
            [f"{TOID}@goofish", f"{self.live.myid}@goofish"],
        )

    def test_cdn_url_skips_upload(self):
        uploader = _FakeUploader()
        self._patch_uploader(uploader)

        asyncio.run(self.live.send_im_image(CID, TOID, CDN_URL))

        self.assertEqual(uploader.uploaded_paths, [])
        envelope, _ = self.sent[0][1]
        pic = _decode_image_payload(envelope)["image"]["pics"][0]
        self.assertEqual(pic["url"], CDN_URL)
        # 拿不到尺寸时退回 800x600，与 send_image_msg 的默认值一致
        self.assertEqual((pic["width"], pic["height"]), (800, 600))

    def test_upload_failure_raises_and_sends_nothing(self):
        uploader = _FakeUploader(result=None)
        self._patch_uploader(uploader)

        with self.assertRaises(RuntimeError):
            asyncio.run(self.live.send_im_image(CID, TOID, self._temp_image()))

        self.assertEqual(self.sent, [])

    def test_server_side_failure_raises(self):
        async def failing_request(lwp, body, timeout=15):
            return {"body": {"reason": "FAIL_SYS_TOKEN_EMPTY", "developerMessage": "token 失效"}}

        self.live._send_im_request = failing_request
        self._patch_uploader(_FakeUploader())

        with self.assertRaises(RuntimeError):
            asyncio.run(self.live.send_im_image(CID, TOID, self._temp_image()))

    def test_missing_local_file_raises(self):
        uploader = _FakeUploader()
        self._patch_uploader(uploader)

        with self.assertRaises(FileNotFoundError):
            asyncio.run(
                self.live.send_im_image(
                    CID, TOID, os.path.join(tempfile.gettempdir(), "no-such-image.png")
                )
            )

        self.assertEqual(uploader.uploaded_paths, [])
        self.assertEqual(self.sent, [])


class _StubInstance:
    """端点测试用的账号替身：记录 send_im_image 的入参与调用时文件状态。"""

    def __init__(self):
        self.captures = []

    async def send_im_image(self, cid, toid, image_path, width=None, height=None):
        with open(image_path, "rb") as handle:
            blob = handle.read()
        self.captures.append(
            {
                "cid": cid,
                "toid": toid,
                "image_path": image_path,
                "existed": os.path.exists(image_path),
                "blob": blob,
            }
        )
        return {"body": {"messageId": "mid-9"}}


class ChatSendImageEndpointTests(unittest.TestCase):
    """POST /chat/send-image/{cookie_id} 的行为。"""

    def setUp(self):
        from app import reply_server

        self.reply_server = reply_server
        self.client = TestClient(reply_server.app)
        reply_server.app.dependency_overrides[reply_server.get_current_user] = lambda: {
            "user_id": 1,
            "username": "tester",
        }
        self._owned_patcher = mock.patch.object(
            reply_server, "_get_owned_chat_account", lambda cookie_id, current_user: cookie_id
        )
        self._owned_patcher.start()

        self.stub = _StubInstance()

        async def fake_run(cookie_id, operation):
            return await operation(self.stub)

        self._loop_patcher = mock.patch.object(reply_server, "_run_on_account_loop", fake_run)
        self._loop_patcher.start()

    def tearDown(self):
        self._loop_patcher.stop()
        self._owned_patcher.stop()
        self.reply_server.app.dependency_overrides.clear()

    def _post(self, cid=" chat-1 ", to_user_id=" 20002 ",
              filename="demo.png", content_type="image/png", data=b"png-bytes"):
        return self.client.post(
            "/chat/send-image/cookie-a",
            data={"cid": cid, "to_user_id": to_user_id},
            files={"image": (filename, data, content_type)},
        )

    def test_success_sends_image_and_cleans_up_temp_file(self):
        response = self._post()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["messageId"], "mid-9")

        # 临时文件在交给账号实例之前存在、内容原样，之后必须被删掉
        self.assertEqual(len(self.stub.captures), 1)
        capture = self.stub.captures[0]
        self.assertEqual(capture["cid"], "chat-1")          # 前后空格被 strip
        self.assertEqual(capture["toid"], "20002")
        self.assertTrue(capture["existed"])
        self.assertEqual(capture["blob"], b"png-bytes")
        self.assertFalse(os.path.exists(capture["image_path"]))

    def test_rejects_non_image_content_type(self):
        response = self._post(filename="notes.txt", content_type="text/plain", data=b"hello")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stub.captures, [])

    def test_rejects_empty_file(self):
        response = self._post(data=b"")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stub.captures, [])

    def test_rejects_oversize_file(self):
        response = self._post(data=b"\0" * (10 * 1024 * 1024 + 1))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stub.captures, [])

    def test_rejects_blank_conversation_fields(self):
        # 空串由 FastAPI 的必填校验拦下（422，与文字端点 min_length=1 同口径）；
        # 全空格骗得过框架，靠 strip 后的业务校验兜住（400）。
        empty = self._post(to_user_id="")
        self.assertEqual(empty.status_code, 422)
        blank = self._post(cid="   ", to_user_id="  ")
        self.assertEqual(blank.status_code, 400)
        self.assertEqual(self.stub.captures, [])

    def test_rejects_account_not_owned(self):
        self._owned_patcher.stop()
        patcher = mock.patch.object(
            self.reply_server,
            "_get_owned_chat_account",
            mock.Mock(side_effect=HTTPException(status_code=403, detail="无权访问该闲鱼账号")),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        response = self._post()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.stub.captures, [])


if __name__ == "__main__":
    unittest.main()
