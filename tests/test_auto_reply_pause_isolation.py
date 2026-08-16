"""人工接入暂停不得跨账号串号。

回归的是这个故障：AutoReplyPauseManager 是全局单例，而 paused_chats 只用
chat_id 做键。chat_id 标识的是一个会话，当用户自己的两个账号正好是同一个会话
的两端时（测试自动回复最常见的做法），双方拿到的是同一个 chat_id。于是 A 账号
手动发一条消息，就把 B 账号对该会话的自动回复一起停掉，表现为「关键词明明配好
了却完全不回」，而唯一线索是一行 info 级日志。

实测：酷灵(2217097925130) 在后台手动发言 → 耶比(2214101806408) 收到「测试」，
命中精确关键词，却被判 chat_paused 跳过。
"""

import time
import unittest
from unittest.mock import patch

from XianyuAutoAsync import AutoReplyPauseManager

ACC_A = '2217097925130'
ACC_B = '2214101806408'
SHARED_CHAT = '65456990156'


def make_manager(pause_minutes=10):
    """构造管理器，并把「读账号暂停时长」固定下来，避免依赖数据库。"""
    manager = AutoReplyPauseManager()
    patcher = patch('app.db_manager.db_manager.get_cookie_pause_duration',
                    return_value=pause_minutes)
    patcher.start()
    return manager, patcher


class CrossAccountIsolationTests(unittest.TestCase):
    def setUp(self):
        self.manager, self._patcher = make_manager()

    def tearDown(self):
        self._patcher.stop()

    def test_pause_does_not_leak_to_other_account(self):
        """A 手动发言，不得暂停 B 在同一 chat_id 上的自动回复。"""
        self.manager.pause_chat(SHARED_CHAT, ACC_A)

        self.assertTrue(self.manager.is_chat_paused(SHARED_CHAT, ACC_A))
        self.assertFalse(
            self.manager.is_chat_paused(SHARED_CHAT, ACC_B),
            "另一个账号的自动回复被误暂停了"
        )

    def test_remaining_time_is_per_account(self):
        self.manager.pause_chat(SHARED_CHAT, ACC_A)

        self.assertGreater(self.manager.get_remaining_pause_time(SHARED_CHAT, ACC_A), 0)
        self.assertEqual(self.manager.get_remaining_pause_time(SHARED_CHAT, ACC_B), 0)

    def test_both_accounts_can_pause_independently(self):
        self.manager.pause_chat(SHARED_CHAT, ACC_A)
        self.manager.pause_chat(SHARED_CHAT, ACC_B)

        self.assertTrue(self.manager.is_chat_paused(SHARED_CHAT, ACC_A))
        self.assertTrue(self.manager.is_chat_paused(SHARED_CHAT, ACC_B))
        self.assertEqual(len(self.manager.paused_chats), 2)

    def test_different_chats_same_account_isolated(self):
        self.manager.pause_chat(SHARED_CHAT, ACC_A)

        self.assertFalse(self.manager.is_chat_paused('99999999', ACC_A))


class PauseExpiryTests(unittest.TestCase):
    def setUp(self):
        self.manager, self._patcher = make_manager()

    def tearDown(self):
        self._patcher.stop()

    def test_expired_pause_releases(self):
        self.manager.pause_chat(SHARED_CHAT, ACC_A)
        # 直接把到期时间拨到过去，避免真的等 10 分钟
        key = self.manager._key(ACC_A, SHARED_CHAT)
        self.manager.paused_chats[key] = time.time() - 1

        self.assertFalse(self.manager.is_chat_paused(SHARED_CHAT, ACC_A))
        self.assertNotIn(key, self.manager.paused_chats, "过期记录未被清除")

    def test_cleanup_only_removes_expired(self):
        self.manager.pause_chat(SHARED_CHAT, ACC_A)
        self.manager.pause_chat(SHARED_CHAT, ACC_B)
        self.manager.paused_chats[self.manager._key(ACC_A, SHARED_CHAT)] = time.time() - 1

        self.manager.cleanup_expired_pauses()

        self.assertFalse(self.manager.is_chat_paused(SHARED_CHAT, ACC_A))
        self.assertTrue(self.manager.is_chat_paused(SHARED_CHAT, ACC_B))


class PauseDisabledTests(unittest.TestCase):
    def test_zero_minutes_means_never_pause(self):
        """暂停时长设为 0 表示不暂停，此时不应写入任何记录。"""
        manager, patcher = make_manager(pause_minutes=0)
        try:
            manager.pause_chat(SHARED_CHAT, ACC_A)
            self.assertFalse(manager.is_chat_paused(SHARED_CHAT, ACC_A))
            self.assertEqual(manager.paused_chats, {})
        finally:
            patcher.stop()


if __name__ == "__main__":
    unittest.main()
