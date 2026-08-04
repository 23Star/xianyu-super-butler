import unittest

from XianyuAutoAsync import XianyuLive


class ItemImageExtractionTests(unittest.TestCase):
    def test_prefers_item_image_over_seller_avatar(self):
        card = {
            "seller": {
                "avatar": "https://img.alicdn.com/avatar.jpg",
            },
            "itemInfo": {
                "mainPic": {
                    "url": "//img.alicdn.com/bao/uploaded/example-xy_item.jpg_.webp",
                },
            },
        }

        image = XianyuLive._extract_item_image(card)

        self.assertEqual(
            image,
            "//img.alicdn.com/bao/uploaded/example-xy_item.jpg_.webp",
        )

    def test_normalize_item_card_keeps_image_from_outer_card(self):
        card = {
            "cardData": {
                "picInfo": {
                    "picUrl": "https://img.alicdn.com/bao/uploaded/item.jpg",
                },
                "itemInfo": {
                    "itemId": "123",
                    "title": "测试商品",
                    "priceInfo": {"price": "80", "preText": "¥"},
                },
            },
        }

        item = XianyuLive._normalize_item_card(card)

        self.assertEqual(item["item_image"], "https://img.alicdn.com/bao/uploaded/item.jpg")
        self.assertEqual(item["price_text"], "¥80")


if __name__ == "__main__":
    unittest.main()
