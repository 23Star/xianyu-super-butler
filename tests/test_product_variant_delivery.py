import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.db_manager import DBManager
from app.specification import DEFAULT_SPEC_KEY, canonicalize_specification


class ProductVariantDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DBManager(os.path.join(self.temp_dir.name, "variants.db"))
        cursor = self.manager.conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO users (id, username, email, password_hash)
            VALUES (1, 'owner', 'owner@example.com', 'x')
            """
        )
        cursor.execute(
            """
            INSERT OR IGNORE INTO users (id, username, email, password_hash)
            VALUES (2, 'other', 'other@example.com', 'x')
            """
        )
        cursor.execute(
            "INSERT INTO cookies (id, value, user_id) VALUES ('seller-1', 'cookie', 1)"
        )
        cursor.execute(
            """
            INSERT INTO item_info (cookie_id, item_id, item_title)
            VALUES ('seller-1', 'item-1', 'Subscription')
            """
        )
        self.weekly_card = self._insert_card(cursor, 1, "weekly", "WEEKLY")
        self.monthly_card = self._insert_card(cursor, 1, "monthly", "MONTHLY")
        self.other_user_card = self._insert_card(cursor, 2, "foreign", "FOREIGN")
        self.manager.conn.commit()

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    @staticmethod
    def _insert_card(cursor, user_id, name, content):
        cursor.execute(
            """
            INSERT INTO cards (name, type, text_content, enabled, user_id)
            VALUES (?, 'text', ?, 1, ?)
            """,
            (name, content, user_id),
        )
        return cursor.lastrowid

    def _save_multi(self, *, enabled=True):
        return self.manager.save_item_delivery_config(
            user_id=1,
            cookie_id="seller-1",
            item_id="item-1",
            enabled=enabled,
            is_multi_spec=True,
            variants=[
                {
                    "display_name": "Weekly exclusive",
                    "spec_text": "period=weekly | version=exclusive",
                    "platform_sku_id": "sku-weekly",
                    "card_id": self.weekly_card,
                    "delivery_count": 2,
                    "enabled": True,
                    "binding_enabled": True,
                },
                {
                    "display_name": "Monthly shared",
                    "spec_text": "period=monthly | version=shared",
                    "platform_sku_id": "sku-monthly",
                    "card_id": self.monthly_card,
                    "delivery_count": 1,
                    "enabled": True,
                    "binding_enabled": True,
                },
            ],
        )

    def test_reordered_and_full_width_specifications_share_canonical_key(self):
        expected_key, expected_payload = canonicalize_specification(
            "period=weekly | version=exclusive"
        )

        reordered_key, reordered_payload = canonicalize_specification(
            "version：exclusive；period：weekly"
        )
        full_width_key, full_width_payload = canonicalize_specification(
            "version＝exclusive｜period＝weekly"
        )

        self.assertEqual(expected_key, reordered_key)
        self.assertEqual(expected_key, full_width_key)
        self.assertEqual(expected_payload, reordered_payload)
        self.assertEqual(expected_payload, full_width_payload)

    def test_conflicting_duplicate_dimension_is_invalid(self):
        key, payload = canonicalize_specification(
            "period=weekly | period=monthly"
        )

        self.assertEqual("", key)
        self.assertEqual({}, payload)

    def test_duplicate_canonical_specifications_are_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.save_item_delivery_config(
                user_id=1,
                cookie_id="seller-1",
                item_id="item-1",
                enabled=True,
                is_multi_spec=True,
                variants=[
                    {
                        "spec_text": "period=weekly | version=exclusive",
                        "card_id": self.weekly_card,
                    },
                    {
                        "spec_text": "version=exclusive | period=weekly",
                        "card_id": self.monthly_card,
                    },
                ],
            )

    def test_duplicate_platform_sku_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.save_item_delivery_config(
                user_id=1,
                cookie_id="seller-1",
                item_id="item-1",
                enabled=True,
                is_multi_spec=True,
                variants=[
                    {
                        "spec_text": "period=weekly",
                        "platform_sku_id": "sku-1",
                        "card_id": self.weekly_card,
                    },
                    {
                        "spec_text": "period=monthly",
                        "platform_sku_id": "sku-1",
                        "card_id": self.monthly_card,
                    },
                ],
            )

    def test_card_from_another_user_cannot_be_bound(self):
        with self.assertRaises(ValueError):
            self.manager.save_item_delivery_config(
                user_id=1,
                cookie_id="seller-1",
                item_id="item-1",
                enabled=True,
                is_multi_spec=False,
                variants=[{"card_id": self.other_user_card}],
            )

    def test_each_specification_resolves_its_own_card_and_quantity(self):
        self._save_multi()

        weekly = self.manager.resolve_item_delivery_binding(
            "seller-1",
            "item-1",
            spec_text="version=exclusive | period=weekly",
        )
        monthly = self.manager.resolve_item_delivery_binding(
            "seller-1",
            "item-1",
            platform_sku_id="sku-monthly",
            spec_text="period=monthly | version=shared",
        )

        self.assertTrue(weekly["matched"])
        self.assertEqual(self.weekly_card, weekly["card_id"])
        self.assertEqual(2, weekly["delivery_count"])
        self.assertTrue(monthly["matched"])
        self.assertEqual(self.monthly_card, monthly["card_id"])
        self.assertEqual(1, monthly["delivery_count"])

    def test_missing_unknown_and_conflicting_specifications_block_delivery(self):
        self._save_multi()

        missing = self.manager.resolve_item_delivery_binding("seller-1", "item-1")
        unknown = self.manager.resolve_item_delivery_binding(
            "seller-1",
            "item-1",
            spec_text="period=yearly | version=exclusive",
        )
        unknown_sku = self.manager.resolve_item_delivery_binding(
            "seller-1",
            "item-1",
            platform_sku_id="unknown-sku",
            spec_text="period=weekly | version=exclusive",
        )
        conflicting = self.manager.resolve_item_delivery_binding(
            "seller-1",
            "item-1",
            platform_sku_id="sku-weekly",
            spec_text="period=monthly | version=shared",
        )

        self.assertEqual("missing_specification", missing["reason"])
        self.assertEqual("unknown_specification", unknown["reason"])
        self.assertEqual("unknown_specification", unknown_sku["reason"])
        self.assertEqual("conflicting_specification", conflicting["reason"])
        self.assertFalse(any(
            result["matched"]
            for result in (missing, unknown, unknown_sku, conflicting)
        ))

    def test_disabled_config_variant_binding_and_card_block_delivery(self):
        config = self._save_multi(enabled=False)
        weekly_variant = config["variants"][0]

        result = self.manager.resolve_item_delivery_binding(
            "seller-1", "item-1", platform_sku_id="sku-weekly"
        )
        self.assertEqual("config_disabled", result["reason"])

        cursor = self.manager.conn.cursor()
        cursor.execute(
            "UPDATE item_delivery_configs SET enabled = 1 WHERE cookie_id = ? AND item_id = ?",
            ("seller-1", "item-1"),
        )
        cursor.execute(
            "UPDATE product_variants SET enabled = 0 WHERE id = ?",
            (weekly_variant["id"],),
        )
        self.manager.conn.commit()
        result = self.manager.resolve_item_delivery_binding(
            "seller-1", "item-1", platform_sku_id="sku-weekly"
        )
        self.assertEqual("variant_disabled", result["reason"])

        cursor.execute(
            "UPDATE product_variants SET enabled = 1 WHERE id = ?",
            (weekly_variant["id"],),
        )
        cursor.execute(
            "UPDATE variant_delivery_bindings SET enabled = 0 WHERE id = ?",
            (weekly_variant["binding_id"],),
        )
        self.manager.conn.commit()
        result = self.manager.resolve_item_delivery_binding(
            "seller-1", "item-1", platform_sku_id="sku-weekly"
        )
        self.assertEqual("binding_disabled", result["reason"])

        cursor.execute(
            "UPDATE variant_delivery_bindings SET enabled = 1 WHERE id = ?",
            (weekly_variant["binding_id"],),
        )
        cursor.execute(
            "UPDATE cards SET enabled = 0 WHERE id = ?",
            (self.weekly_card,),
        )
        self.manager.conn.commit()
        result = self.manager.resolve_item_delivery_binding(
            "seller-1", "item-1", platform_sku_id="sku-weekly"
        )
        self.assertEqual("card_disabled", result["reason"])

    def test_ordinary_product_always_resolves_default_variant(self):
        config = self.manager.save_item_delivery_config(
            user_id=1,
            cookie_id="seller-1",
            item_id="item-1",
            enabled=True,
            is_multi_spec=False,
            variants=[
                {
                    "spec_text": "ignored=value",
                    "platform_sku_id": "ignored-sku",
                    "card_id": self.weekly_card,
                    "delivery_count": 3,
                }
            ],
        )

        result = self.manager.resolve_item_delivery_binding(
            "seller-1",
            "item-1",
            spec_text="period=anything",
            platform_sku_id="unknown-sku",
        )

        self.assertEqual(DEFAULT_SPEC_KEY, config["variants"][0]["canonical_spec_key"])
        self.assertTrue(result["matched"])
        self.assertEqual(self.weekly_card, result["card_id"])
        self.assertEqual(3, result["delivery_count"])

    def test_new_config_presence_distinguishes_legacy_fallback_from_blocking(self):
        legacy = self.manager.resolve_item_delivery_binding("seller-1", "item-1")
        self.assertFalse(legacy["configured"])
        self.assertEqual("not_configured", legacy["reason"])

        self._save_multi()
        blocked = self.manager.resolve_item_delivery_binding(
            "seller-1",
            "item-1",
            spec_text="period=unknown",
        )

        self.assertTrue(blocked["configured"])
        self.assertFalse(blocked["matched"])
        self.assertEqual("unknown_specification", blocked["reason"])

    def test_deleting_product_removes_config_variants_and_bindings(self):
        self._save_multi()

        self.assertTrue(self.manager.delete_item_info("seller-1", "item-1"))

        cursor = self.manager.conn.cursor()
        for table in (
            "item_delivery_configs",
            "product_variants",
            "variant_delivery_bindings",
        ):
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            self.assertEqual(0, cursor.fetchone()[0], table)

    def test_batch_inventory_shortage_consumes_nothing(self):
        cursor = self.manager.conn.cursor()
        cursor.execute(
            """
            INSERT INTO cards (name, type, data_content, enabled, user_id)
            VALUES ('batch', 'data', 'CODE-1\nCODE-2', 1, 1)
            """
        )
        card_id = cursor.lastrowid
        self.manager.conn.commit()

        consumed = self.manager.consume_batch_data_batch(card_id, 3)

        self.assertIsNone(consumed)
        cursor.execute("SELECT data_content FROM cards WHERE id = ?", (card_id,))
        self.assertEqual("CODE-1\nCODE-2", cursor.fetchone()[0])

    def test_batch_inventory_consumes_exact_quantity_in_one_update(self):
        cursor = self.manager.conn.cursor()
        cursor.execute(
            """
            INSERT INTO cards (name, type, data_content, enabled, user_id)
            VALUES ('batch', 'data', 'CODE-1\nCODE-2\nCODE-3', 1, 1)
            """
        )
        card_id = cursor.lastrowid
        self.manager.conn.commit()

        consumed = self.manager.consume_batch_data_batch(card_id, 2)

        self.assertEqual(["CODE-1", "CODE-2"], consumed)
        cursor.execute("SELECT data_content FROM cards WHERE id = ?", (card_id,))
        self.assertEqual("CODE-3", cursor.fetchone()[0])

    def test_delivery_flow_does_not_partially_consume_batch_inventory(self):
        from XianyuAutoAsync import XianyuLive

        cursor = self.manager.conn.cursor()
        cursor.execute(
            """
            UPDATE item_info
            SET item_detail = 'detail'
            WHERE cookie_id = 'seller-1' AND item_id = 'item-1'
            """
        )
        cursor.execute(
            """
            INSERT INTO cards (name, type, data_content, enabled, user_id)
            VALUES ('batch', 'data', 'CODE-1\nCODE-2\nCODE-3', 1, 1)
            """
        )
        card_id = cursor.lastrowid
        self.manager.conn.commit()
        self.manager.save_item_delivery_config(
            user_id=1,
            cookie_id="seller-1",
            item_id="item-1",
            enabled=True,
            is_multi_spec=False,
            variants=[{"card_id": card_id, "delivery_count": 2}],
        )

        live = object.__new__(XianyuLive)
        live.cookie_id = "seller-1"
        live.save_item_info_to_db = AsyncMock()
        delivery_context = {}

        with patch("app.db_manager.db_manager", self.manager):
            content = asyncio.run(
                live._auto_delivery(
                    "item-1",
                    "Subscription",
                    "order-1",
                    "buyer-1",
                    delivery_context=delivery_context,
                    requested_item_quantity=2,
                )
            )

        self.assertIsNone(content)
        cursor.execute("SELECT data_content FROM cards WHERE id = ?", (card_id,))
        self.assertEqual("CODE-1\nCODE-2\nCODE-3", cursor.fetchone()[0])

    def test_delivery_flow_preloads_full_batch_inventory_once(self):
        from XianyuAutoAsync import XianyuLive

        cursor = self.manager.conn.cursor()
        cursor.execute(
            """
            UPDATE item_info
            SET item_detail = 'detail'
            WHERE cookie_id = 'seller-1' AND item_id = 'item-1'
            """
        )
        cursor.execute(
            """
            INSERT INTO cards (name, type, data_content, enabled, user_id)
            VALUES ('batch', 'data', 'CODE-1\nCODE-2\nCODE-3\nCODE-4\nCODE-5', 1, 1)
            """
        )
        card_id = cursor.lastrowid
        self.manager.conn.commit()
        self.manager.save_item_delivery_config(
            user_id=1,
            cookie_id="seller-1",
            item_id="item-1",
            enabled=True,
            is_multi_spec=False,
            variants=[{"card_id": card_id, "delivery_count": 2}],
        )

        live = object.__new__(XianyuLive)
        live.cookie_id = "seller-1"
        live.save_item_info_to_db = AsyncMock()
        delivery_context = {}

        async def acquire_all():
            contents = [
                await live._auto_delivery(
                    "item-1",
                    "Subscription",
                    "order-1",
                    "buyer-1",
                    delivery_context=delivery_context,
                    requested_item_quantity=2,
                )
            ]
            for _ in range(3):
                contents.append(
                    await live._auto_delivery(
                        "item-1",
                        "Subscription",
                        "order-1",
                        "buyer-1",
                        delivery_context=delivery_context,
                    )
                )
            return contents

        with patch("app.db_manager.db_manager", self.manager):
            contents = asyncio.run(acquire_all())

        self.assertEqual(["CODE-1", "CODE-2", "CODE-3", "CODE-4"], contents)
        self.assertEqual(4, delivery_context["batch_data_required_count"])
        self.assertEqual([], delivery_context["batch_data_queue"])
        cursor.execute("SELECT data_content FROM cards WHERE id = ?", (card_id,))
        self.assertEqual("CODE-5", cursor.fetchone()[0])


if __name__ == "__main__":
    unittest.main()
