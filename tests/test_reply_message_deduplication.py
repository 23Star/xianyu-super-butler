"""Exercise deduplication through the incoming sync envelope, without network I/O."""

import asyncio
import base64
import json
import unittest
from unittest.mock import AsyncMock, patch

from XianyuAutoAsync import XianyuLive


class ReplyMessageDeduplicationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.live = XianyuLive.__new__(XianyuLive)
        self.live.cookie_id = "test-seller"
        self.live.myid = "seller"
        self.live.order_status_handler = None
        self.live.processed_message_ids = {}
        self.live.processed_message_ids_lock = asyncio.Lock()
        self.live.message_expire_time = 3600
        self.live.processed_message_ids_max_size = 100
        self.live.message_debounce_lock = asyncio.Lock()
        self.live.message_debounce_tasks = {}
        self.live.message_debounce_delay = 0
        self.tasks = []
        self.live._create_tracked_task = self.track_task
        self.live.send_notification = AsyncMock()
        self.live._process_chat_message_reply = AsyncMock()
        self.websocket = AsyncMock()

    def track_task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task

    async def receive(self, message_id, timestamp):
        details = {
            "senderUserId": "buyer",
            "reminderContent": "你好",
            "reminderUrl": "fleamarket://message_chat?itemId=item-1",
        }
        if message_id:
            details["bizTag"] = json.dumps({"messageId": message_id})
        message = {"1": {"2": "chat-1@goofish", "5": timestamp, "10": details}}
        encoded = base64.b64encode(json.dumps(message).encode()).decode()
        envelope = {
            "headers": {"mid": "transport-id"},
            "body": {"syncPushPackage": {"data": [{"data": encoded}]}},
        }
        with patch("app.cookie_manager.manager", None), patch(
            "app.db_manager.db_manager.matches_message_filter", return_value=None
        ):
            await self.live.handle_message(envelope, self.websocket)
            if self.tasks:
                await asyncio.gather(*self.tasks)

    async def test_new_messages_with_identical_text_both_reach_reply(self):
        await self.receive("message-1", 1791861543000)
        await self.receive("message-2", 1791861695000)
        self.assertEqual(self.live._process_chat_message_reply.await_count, 2)
        self.assertEqual(set(self.live.processed_message_ids), {"message-1", "message-2"})

    async def test_redelivery_of_same_message_is_ignored(self):
        await self.receive("message-1", 1791861543000)
        await self.receive("message-1", 1791861543000)
        self.live._process_chat_message_reply.assert_awaited_once()

    async def test_missing_id_uses_actual_message_timestamp(self):
        await self.receive(None, 1791861543000)
        await self.receive(None, 1791861695000)
        self.assertEqual(self.live._process_chat_message_reply.await_count, 2)
        self.assertNotIn("chat-1_你好_0", self.live.processed_message_ids)
