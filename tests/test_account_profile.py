import unittest

from XianyuAutoAsync import XianyuLive


class AccountProfileTests(unittest.TestCase):
    def test_parses_public_profile_from_semantic_snapshot(self):
        snapshot = {
            "title": "酷灵超算工作室_闲鱼",
            "body_lines": [
                "酷灵超算工作室",
                "订单",
                "酷灵超算工作室",
                "新疆维吾尔自治区",
                "116粉丝",
                "20关注",
                "本店已缴1000保证！纯绿~，私信留言人工查看",
                "编辑资料",
            ],
            "images": [
                {
                    "src": (
                        "//img.alicdn.com/bao/uploaded/i4/"
                        "O1CN01idJNMn1nlawxMM3Vr_!!4611686018427384330"
                        "-0-mtopupload.jpg"
                    ),
                    "class_name": "avatar--dynamic",
                    "natural_width": 1109,
                    "natural_height": 1094,
                }
            ],
        }

        profile = XianyuLive._parse_account_profile_snapshot(
            snapshot,
            "2217097925130",
        )

        self.assertEqual(profile["nickname"], "酷灵超算工作室")
        self.assertEqual(profile["location"], "新疆维吾尔自治区")
        self.assertEqual(profile["followers"], 116)
        self.assertEqual(profile["following"], 20)
        self.assertEqual(
            profile["bio"],
            "本店已缴1000保证！纯绿~，私信留言人工查看",
        )
        self.assertTrue(profile["avatar_url"].startswith("https://"))

    def test_profile_count_supports_wan_unit(self):
        self.assertEqual(XianyuLive._parse_profile_count("1.2万"), 12000)
        self.assertEqual(XianyuLive._parse_profile_count("1,234"), 1234)
        self.assertIsNone(XianyuLive._parse_profile_count(""))


if __name__ == "__main__":
    unittest.main()
