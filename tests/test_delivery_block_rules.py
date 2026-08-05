import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from app.services.delivery_block_rules import (
    DeliveryBlockRuleService,
    resolve_delivery_action,
)


class RuleTestDatabase:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = threading.RLock()
        self.conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL
            );
            CREATE TABLE cookies (
                id TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                user_id INTEGER NOT NULL
            );
            CREATE TABLE orders (
                order_id TEXT PRIMARY KEY,
                item_id TEXT,
                buyer_id TEXT,
                order_status TEXT,
                cookie_id TEXT
            );
            CREATE TABLE delivery_block_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                rule_code TEXT NOT NULL,
                enabled INTEGER DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 99,
                block_reason TEXT DEFAULT '',
                auto_close_order INTEGER DEFAULT 0,
                only_card_after_close INTEGER DEFAULT 0,
                excluded_item_ids TEXT DEFAULT '[]',
                config TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account_id, rule_code)
            );
            CREATE TABLE personal_blacklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                account_id TEXT,
                buyer_id TEXT NOT NULL,
                buyer_nick TEXT DEFAULT '',
                item_id TEXT,
                reason TEXT DEFAULT '',
                is_enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    def get_cookie_details(self, account_id):
        row = self.conn.execute(
            "SELECT id, user_id FROM cookies WHERE id = ?",
            (account_id,),
        ).fetchone()
        return {"id": row[0], "user_id": row[1]} if row else None

    def close(self):
        self.conn.close()


class DeliveryBlockRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = RuleTestDatabase(os.path.join(self.temp_dir.name, "rules.db"))
        self.owner_id = 1
        self.manager.conn.execute(
            "INSERT INTO users (id, username) VALUES (?, ?)",
            (self.owner_id, "admin"),
        )
        self.manager.conn.executemany(
            "INSERT INTO cookies (id, value, user_id) VALUES (?, ?, ?)",
            [
                ("seller-a", "cookie-a", self.owner_id),
                ("seller-b", "cookie-b", self.owner_id),
            ],
        )
        self.manager.conn.commit()
        self.service = DeliveryBlockRuleService(self.manager)

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def add_order(self, order_id, account_id, buyer_id, status="pending_ship", item_id="item-1"):
        self.manager.conn.execute(
            """
            INSERT INTO orders (order_id, cookie_id, buyer_id, order_status, item_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_id, account_id, buyer_id, status, item_id),
        )
        self.manager.conn.commit()

    def enable_rule(self, account_id, rule_code, **changes):
        return self.service.update_rule(
            account_id,
            rule_code,
            {"enabled": True, **changes},
        )

    def test_rules_are_disabled_by_default(self):
        rules = self.service.list_rules("seller-a")
        self.assertEqual(len(rules), 5)
        self.assertTrue(all(not rule["enabled"] for rule in rules))

    def test_only_card_is_disabled_when_auto_close_is_off(self):
        rule = self.service.update_rule(
            "seller-a",
            "personal_blacklist",
            {
                "auto_close_order": False,
                "only_card_after_close": True,
            },
        )
        self.assertFalse(rule["auto_close_order"])
        self.assertFalse(rule["only_card_after_close"])

    def test_blacklist_buyer_id_cannot_be_cleared(self):
        entry = self.service.add_blacklist(
            self.owner_id,
            {
                "account_id": "seller-a",
                "buyer_id": "buyer-1",
            },
        )

        with self.assertRaisesRegex(ValueError, "buyer_id 不能为空"):
            self.service.update_blacklist(
                self.owner_id,
                entry["id"],
                {"buyer_id": "   "},
            )

    def test_rule_priority_and_excluded_items_cannot_be_null(self):
        with self.assertRaisesRegex(ValueError, "priority 不能为空"):
            self.service.update_rule(
                "seller-a",
                "buyer_has_order",
                {"priority": None},
            )

        with self.assertRaisesRegex(ValueError, "excluded_item_ids 不能为空"):
            self.service.update_rule(
                "seller-a",
                "buyer_has_order",
                {"excluded_item_ids": None},
            )

    def test_personal_blacklist_has_priority_and_supports_excluded_items(self):
        self.add_order("current", "seller-a", "buyer-1")
        self.add_order("previous", "seller-a", "buyer-1")
        self.service.add_blacklist(
            self.owner_id,
            {
                "account_id": "seller-a",
                "buyer_id": "buyer-1",
                "reason": "风险买家",
            },
        )
        self.enable_rule("seller-a", "personal_blacklist")
        self.enable_rule("seller-a", "buyer_has_order")

        result = self.service.evaluate("seller-a", "current", "buyer-1", "item-1")
        self.assertEqual(result["rule_code"], "personal_blacklist")
        self.assertIn("风险买家", result["reason"])

        self.service.update_rule(
            "seller-a",
            "personal_blacklist",
            {"excluded_item_ids": ["item-1"]},
        )
        result = self.service.evaluate("seller-a", "current", "buyer-1", "item-1")
        self.assertEqual(result["rule_code"], "buyer_has_order")

    def test_blacklist_supports_product_account_and_global_scopes(self):
        self.enable_rule("seller-a", "personal_blacklist")
        self.enable_rule("seller-b", "personal_blacklist")
        self.service.add_blacklist(
            self.owner_id,
            {
                "account_id": "seller-a",
                "item_id": "item-1",
                "buyer_id": "product-buyer",
            },
        )
        self.service.add_blacklist(
            self.owner_id,
            {
                "account_id": "seller-a",
                "buyer_id": "account-buyer",
            },
        )
        self.service.add_blacklist(
            self.owner_id,
            {
                "buyer_id": "global-buyer",
            },
        )

        product_result = self.service.evaluate(
            "seller-a", "order-1", "product-buyer", "item-1"
        )
        self.assertEqual(product_result["extra_data"]["level"], "商品级")
        self.assertFalse(
            self.service.evaluate(
                "seller-a", "order-2", "product-buyer", "item-2"
            )["hit"]
        )

        account_result = self.service.evaluate(
            "seller-a", "order-3", "account-buyer", "item-2"
        )
        self.assertEqual(account_result["extra_data"]["level"], "账号级")
        self.assertFalse(
            self.service.evaluate(
                "seller-b", "order-4", "account-buyer", "item-2"
            )["hit"]
        )

        global_result = self.service.evaluate(
            "seller-b", "order-5", "global-buyer", "item-2"
        )
        self.assertEqual(global_result["extra_data"]["level"], "用户级")

    def test_buyer_credit_threshold_and_api_failure_fail_open(self):
        self.enable_rule(
            "seller-a",
            "buyer_credit_zero",
            config={"threshold": 2},
        )

        self.assertFalse(
            self.service.evaluate(
                "seller-a",
                "current",
                "buyer-credit",
                "item-1",
                buyer_rating_count=None,
            )["hit"]
        )
        self.assertFalse(
            self.service.evaluate(
                "seller-a",
                "current",
                "buyer-credit",
                "item-1",
                buyer_rating_count=-1,
            )["hit"]
        )

        blocked = self.service.evaluate(
            "seller-a",
            "current",
            "buyer-credit",
            "item-1",
            buyer_rating_count=2,
        )
        self.assertEqual(blocked["rule_code"], "buyer_credit_zero")
        self.assertEqual(blocked["extra_data"]["threshold"], 2)

        allowed = self.service.evaluate(
            "seller-a",
            "current",
            "buyer-credit",
            "item-1",
            buyer_rating_count=3,
        )
        self.assertFalse(allowed["hit"])

    def test_cancelled_order_does_not_trigger_existing_order_rule(self):
        self.add_order("current", "seller-a", "buyer-2")
        self.add_order("cancelled", "seller-a", "buyer-2", status="cancelled")
        self.enable_rule("seller-a", "buyer_has_order")

        result = self.service.evaluate("seller-a", "current", "buyer-2", "item-1")
        self.assertFalse(result["hit"])

    def test_global_and_unconfirmed_rules_use_local_order_state(self):
        self.add_order("current", "seller-a", "buyer-3")
        self.add_order("other-account", "seller-b", "buyer-3", status="completed")
        self.enable_rule("seller-a", "buyer_has_order_global")

        result = self.service.evaluate("seller-a", "current", "buyer-3", "item-1")
        self.assertEqual(result["rule_code"], "buyer_has_order_global")

        self.service.update_rule(
            "seller-a",
            "buyer_has_order_global",
            {"enabled": False},
        )
        self.add_order("shipped", "seller-a", "buyer-4", status="shipped")
        self.add_order("new", "seller-a", "buyer-4")
        self.enable_rule("seller-a", "buyer_unconfirmed", config={"min_count": 1})
        result = self.service.evaluate("seller-a", "new", "buyer-4", "item-1")
        self.assertEqual(result["rule_code"], "buyer_unconfirmed")


class DeliveryProtectionActionTests(unittest.TestCase):
    @staticmethod
    def block_result(**changes):
        return {
            "hit": True,
            "rule_code": "personal_blacklist",
            "rule_name": "个人黑名单",
            "reason": "命中黑名单",
            "block_reason": "该订单暂不发货",
            "auto_close_order": True,
            "only_card_after_close": True,
            "extra_data": {},
            **changes,
        }

    def test_close_success_can_continue_with_cards_only(self):
        self.assertEqual(
            resolve_delivery_action(self.block_result(), order_closed=True),
            "card_only",
        )

    def test_close_failure_blocks_delivery(self):
        self.assertEqual(
            resolve_delivery_action(self.block_result(), order_closed=False),
            "block",
        )

    def test_automatic_and_manual_delivery_share_the_same_guard(self):
        root = Path(__file__).resolve().parents[1]
        automatic_source = (root / "XianyuAutoAsync.py").read_text(encoding="utf-8")
        manual_source = (root / "app" / "reply_server.py").read_text(encoding="utf-8")

        self.assertIn("await self.apply_delivery_block_rules(", automatic_source)
        self.assertIn("await self.close_order_by_seller(order_id)", automatic_source)
        self.assertIn("resolve_delivery_action(result, order_closed)", automatic_source)
        self.assertIn(
            "await live_instance.apply_delivery_block_rules(",
            manual_source,
        )


if __name__ == "__main__":
    unittest.main()
