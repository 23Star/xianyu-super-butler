"""会话头像与昵称的兜底。

闲鱼的会话接口不返回买家头像（avatar / avatarUrl / senderAvatar 都是空），
reminderTitle 也常缺失或是纯数字，会话列表因此是一排灰色占位加「闲鱼用户 123456」。
这里用 DiceBear 按用户 ID 生成确定性头像、并从消息体补昵称，同时保证平台真给了
头像时不被占位覆盖。
"""

import unittest

from app.xianyu_im import make_avatar_url, parse_conversation
from utils.risk_control import COOLDOWN_STEPS


def build_raw(extension=None, last_extension=None):
    return {
        "singleChatConversation": {
            "cid": "chat-1@goofish",
            "pairFirst": "111@goofish",
            "pairSecond": "222@goofish",
            "extension": extension if extension is not None else {},
        },
        "lastMessage": {"message": {"extension": last_extension or {}}},
        "modifyTime": 1700000000,
        "redPoint": 0,
    }


class AvatarUrlTests(unittest.TestCase):
    def test_is_deterministic_for_same_user(self):
        # 同一买家每次都要是同一张图，否则列表刷新一次换一个脸
        self.assertEqual(make_avatar_url("2216001"), make_avatar_url("2216001"))

    def test_differs_between_users(self):
        self.assertNotEqual(make_avatar_url("2216001"), make_avatar_url("2216002"))

    def test_empty_seed_returns_empty(self):
        for empty in ("", "   ", None):
            self.assertEqual(make_avatar_url(empty), "")

    def test_seed_is_url_escaped(self):
        url = make_avatar_url("a b&c=d")
        # 未转义的 & 会把 seed 截断，导致不同用户共用一张头像
        self.assertNotIn("a b&c=d", url)
        self.assertIn("a%20b%26c%3Dd", url)


class ConversationAvatarTests(unittest.TestCase):
    def test_falls_back_to_generated_avatar(self):
        conversation = parse_conversation(build_raw(), "111")

        self.assertTrue(conversation["otherUserAvatar"])
        self.assertEqual(conversation["otherUserAvatar"], make_avatar_url("222"))

    def test_platform_avatar_wins_over_placeholder(self):
        conversation = parse_conversation(
            build_raw(extension={"avatar": "//img.alicdn.com/real.jpg"}), "111"
        )

        # 平台给了真实头像就必须用真实的，占位只是兜底
        self.assertEqual(conversation["otherUserAvatar"], "//img.alicdn.com/real.jpg")

    def test_sender_avatar_wins_over_placeholder(self):
        conversation = parse_conversation(
            build_raw(last_extension={
                "senderUserId": "222@goofish",
                "senderAvatar": "//img.alicdn.com/sender.jpg",
            }),
            "111",
        )

        self.assertEqual(conversation["otherUserAvatar"], "//img.alicdn.com/sender.jpg")


class ConversationNicknameTests(unittest.TestCase):
    def test_uses_reminder_title_when_usable(self):
        conversation = parse_conversation(
            build_raw(last_extension={
                "senderUserId": "222@goofish",
                "reminderTitle": "买家小李",
            }),
            "111",
        )

        self.assertEqual(conversation["otherUserName"], "买家小李")

    def test_falls_back_to_sender_nick(self):
        # reminderTitle 缺失时改用消息体里的昵称，避免只能显示「闲鱼用户 222」
        conversation = parse_conversation(
            build_raw(last_extension={
                "senderUserId": "222@goofish",
                "senderNick": "买家小王",
            }),
            "111",
        )

        self.assertEqual(conversation["otherUserName"], "买家小王")

    def test_numeric_nickname_is_rejected(self):
        conversation = parse_conversation(
            build_raw(last_extension={
                "senderUserId": "222@goofish",
                "reminderTitle": "123456",
                "senderNick": "654321",
            }),
            "111",
        )

        # 纯数字不是昵称，留空让前端显示「闲鱼用户 xxx」
        self.assertEqual(conversation["otherUserName"], "")

    def test_nickname_from_other_sender_is_ignored(self):
        # 最后一条是自己发的，其中的昵称不能安到对方头上
        conversation = parse_conversation(
            build_raw(last_extension={
                "senderUserId": "111@goofish",
                "senderNick": "我自己",
            }),
            "111",
        )

        self.assertEqual(conversation["otherUserName"], "")


class CooldownTests(unittest.TestCase):
    def test_steps_are_one_to_twenty_minutes(self):
        self.assertEqual(COOLDOWN_STEPS, (60, 180, 300, 600, 1200))

    def test_steps_increase_monotonically(self):
        self.assertEqual(list(COOLDOWN_STEPS), sorted(COOLDOWN_STEPS))


if __name__ == "__main__":
    unittest.main()
