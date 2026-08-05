import os
import tempfile
import unittest
from datetime import datetime, timedelta

from app.db_manager import DBManager
from app.product_automation import ProductAutomationService


class ProductAutomationServiceTest(unittest.TestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.db = DBManager(self.db_path)
        self.service = ProductAutomationService(self.db)
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO users (id, username, email, password_hash) VALUES (1, 'owner', 'owner@example.com', 'x')"
            )
            cursor.execute(
                """
                INSERT INTO cookies (id, value, user_id)
                VALUES ('account-1', 'cookie', 1)
                """
            )
            old_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.executemany(
                """
                INSERT INTO item_info (
                    cookie_id, item_id, item_title, item_description,
                    item_category, item_price, item_image, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("account-1", "item-1", "Kimi 周卡", "自动发货", "虚拟", "80", "https://img/1.jpg", old_date),
                    ("account-1", "item-2", "其他商品", "不匹配", "虚拟", "20", "", old_date),
                    ("account-1", "item-3", "Kimi 月卡", "近期有回复", "虚拟", "120", "", old_date),
                ],
            )
            cursor.execute(
                """
                INSERT INTO auto_reply_message_logs (
                    cookie_id, item_id, process_status, reply_strategy, send_status
                ) VALUES ('account-1', 'item-3', 'success', 'keyword', 'success')
                """
            )
            self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_filter_rule_writes_matching_material(self):
        rule = self.service.save_filter_rule(
            1,
            {
                "cookie_id": "account-1",
                "name": "Kimi 素材",
                "include_keywords": ["Kimi"],
                "exclude_keywords": ["月卡"],
                "min_price": 50,
                "daily_limit": 5,
                "enabled": True,
            },
        )

        result = self.service.run_filter_rule(1, rule["id"])
        materials = self.service.list_materials(1)

        self.assertIn("写入 1 件", result["summary"])
        self.assertEqual(1, len(materials))
        self.assertEqual("item-1", materials[0]["source_item_id"])
        self.assertEqual(["https://img/1.jpg"], materials[0]["images"])

    def test_delete_preview_skips_replied_and_ordered_items(self):
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                """
                INSERT INTO orders (order_id, item_id, cookie_id)
                VALUES ('order-1', 'item-1', 'account-1')
                """
            )
            self.db.conn.commit()
        rule = self.service.save_delete_rule(
            1,
            {
                "cookie_id": "account-1",
                "name": "旧商品预演",
                "min_publish_days": 30,
                "daily_limit": 10,
                "skip_reply_activity": True,
                "skip_order_activity": True,
                "enabled": False,
                "execution_mode": "dry_run",
            },
        )

        result = self.service.preview_delete_rule(1, rule["id"])
        skipped = {item["item_id"]: item["reason"] for item in result["skipped"]}

        self.assertEqual("dry_run", result["mode"])
        self.assertEqual(["item-2"], [item["item_id"] for item in result["candidates"]])
        self.assertEqual("存在订单记录", skipped["item-1"])
        self.assertEqual("存在自动回复活动", skipped["item-3"])

    def test_card_compensation_is_idempotent(self):
        rule = self.service.save_filter_rule(
            1,
            {
                "cookie_id": "account-1",
                "name": "全部素材",
                "daily_limit": 5,
                "enabled": True,
            },
        )
        self.service.run_filter_rule(1, rule["id"])
        material = self.service.list_materials(1)[0]
        self.service.update_material(
            1,
            material["id"],
            {
                "published_item_id": "published-1",
                "delivery_content": "兑换码 ABC",
            },
        )

        first = self.service.compensate_cards(1)
        second = self.service.compensate_cards(1)

        self.assertIn("完成绑定 1 条", first["summary"])
        self.assertIn("新增或修复 0 项", second["summary"])
        self.assertEqual(1, len(self.db.get_all_cards(1)))
        rules = self.db.get_all_delivery_rules(1)
        self.assertEqual(1, len(rules))
        self.assertEqual("published-1", rules[0]["keyword"])


if __name__ == "__main__":
    unittest.main()
