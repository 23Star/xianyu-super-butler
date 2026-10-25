# -*- coding: utf-8 -*-
"""订单备注后端（PUT /api/orders/{order_id}/note + seller_note 列）的回归测试。

端点函数内是 `from app.db_manager import db_manager` 局部导入，
patch 模块属性即可生效。覆盖：
1. 正常添加备注 / 空串清空备注
2. 超 500 字返回 400；非字符串（含缺失）返回 400
3. 他人账号订单返回 404；订单不存在返回 404；写失败返回 500
4. 旧库迁移：orders 表补 seller_note 列，重复初始化幂等且数据不丢
5. 列表（get_orders_by_cookie）与单订单（get_order_by_id）带出 seller_note
"""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from fastapi import HTTPException

from app.db_manager import DBManager
from app.reply_server import update_order_note


USER = {"user_id": 1, "username": "seller_a"}

# 与线上订单数据同口径的最小订单结构
ORDER = {
    "order_id": "ORD-001",
    "item_id": "ITEM-001",
    "buyer_id": "buyer-001",
    "order_status": "pending_ship",
    "cookie_id": "acc-1",
    "receiver_name": "张三",
    "receiver_phone": "13800138000",
    "receiver_address": "某省某市某区幸福街道1号",
    "seller_note": "",
}


class UpdateOrderNoteEndpointTests(unittest.TestCase):
    """PUT /api/orders/{order_id}/note 端点行为。"""

    def setUp(self):
        self.db = mock.MagicMock()
        patcher = mock.patch("app.db_manager.db_manager", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

        # 默认场景：用户名下有 acc-1 账号，订单 ORD-001 属于该账号
        self.db.get_all_cookies.return_value = {"acc-1": "cookie-acc-1"}
        self.db.get_order_by_id.return_value = dict(ORDER)
        self.db.update_order_note.return_value = True

    def call(self, order_id="ORD-001", payload=None, user=None):
        return update_order_note(
            order_id=order_id,
            payload=payload if payload is not None else {"note": "测试备注"},
            current_user=user or USER,
        )

    def test_add_note_success(self):
        """正常添加备注：返回新值，且以 (order_id, note) 调用 db 层方法。"""
        result = self.call(payload={"note": "买家要求发顺丰"})

        self.assertEqual(result, {"success": True, "seller_note": "买家要求发顺丰"})
        self.db.update_order_note.assert_called_once_with("ORD-001", "买家要求发顺丰")

    def test_clear_note_with_empty_string(self):
        """空串表示清空备注，允许通过并原样返回空串。"""
        result = self.call(payload={"note": ""})

        self.assertEqual(result, {"success": True, "seller_note": ""})
        self.db.update_order_note.assert_called_once_with("ORD-001", "")

    def test_note_at_500_char_limit_is_allowed(self):
        """恰好 500 字在上限内，不拒绝。"""
        note = "备" * 500
        result = self.call(payload={"note": note})

        self.assertEqual(result, {"success": True, "seller_note": note})

    def test_note_over_500_chars_rejected(self):
        """超过 500 字返回 400，且不触碰写库。"""
        with self.assertRaises(HTTPException) as ctx:
            self.call(payload={"note": "备" * 501})

        self.assertEqual(ctx.exception.status_code, 400)
        self.db.update_order_note.assert_not_called()

    def test_non_string_note_rejected(self):
        """非字符串备注（数字 / 缺失键）返回 400。"""
        for payload in ({"note": 123}, {"note": None}, {}, {"note": ["a"]}):
            with self.assertRaises(HTTPException) as ctx:
                self.call(payload=payload)
            self.assertEqual(ctx.exception.status_code, 400)

        self.db.update_order_note.assert_not_called()

    def test_other_users_order_returns_404(self):
        """订单存在但属于他人账号（cookie_id 不在当前用户名下）返回 404。"""
        self.db.get_all_cookies.return_value = {"acc-other": "cookie-other"}

        with self.assertRaises(HTTPException) as ctx:
            self.call()

        self.assertEqual(ctx.exception.status_code, 404)
        self.db.update_order_note.assert_not_called()

    def test_order_not_found_returns_404(self):
        """订单不存在返回 404。"""
        self.db.get_order_by_id.return_value = None

        with self.assertRaises(HTTPException) as ctx:
            self.call(order_id="ORD-404")

        self.assertEqual(ctx.exception.status_code, 404)

    def test_db_write_failure_returns_500(self):
        """db 层写失败返回 500。"""
        self.db.update_order_note.return_value = False

        with self.assertRaises(HTTPException) as ctx:
            self.call()

        self.assertEqual(ctx.exception.status_code, 500)


LEGACY_ORDERS_SCHEMA = """
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    item_id TEXT,
    buyer_id TEXT,
    spec_name TEXT,
    spec_value TEXT,
    quantity TEXT,
    amount TEXT,
    order_status TEXT DEFAULT 'unknown',
    cookie_id TEXT,
    is_bargain INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


class SellerNoteMigrationAndQueryTests(unittest.TestCase):
    """seller_note 列迁移与查询带出（临时库，不 mock）。"""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.db_path = os.path.join(self._temp_dir.name, "orders_note.db")

    def build_legacy_db(self):
        """构造缺少 seller_note 列的旧库。"""
        connection = sqlite3.connect(self.db_path)
        cursor = connection.cursor()
        cursor.execute(LEGACY_ORDERS_SCHEMA)
        cursor.execute(
            "INSERT INTO orders (order_id, item_id, cookie_id, order_status) "
            "VALUES ('ORD-LEGACY', 'ITEM-1', 'acc-1', 'pending_ship')"
        )
        connection.commit()
        connection.close()

    def seed_user_order(self, manager, order_id="ORD-1", cookie_id="acc-1"):
        """准备账号与一条订单，返回 order_id。"""
        manager.save_cookie(cookie_id, "cookie-" + cookie_id, USER["user_id"])
        manager.insert_or_update_order(
            order_id=order_id,
            item_id="ITEM-1",
            buyer_id="buyer-1",
            order_status="pending_ship",
            cookie_id=cookie_id,
        )
        return order_id

    def test_migration_adds_seller_note_to_legacy_orders(self):
        """旧库初始化后 orders 表补上 seller_note 列，且默认空串。"""
        self.build_legacy_db()

        manager = DBManager(self.db_path)
        try:
            columns = {
                row[1]
                for row in manager.conn.execute("PRAGMA table_info(orders)")
            }
            self.assertIn("seller_note", columns)
            # 旧数据不丢，新列默认空串
            order = manager.get_order_by_id("ORD-LEGACY")
            self.assertEqual(order["seller_note"], "")
        finally:
            manager.close()

    def test_migration_is_idempotent_and_keeps_data(self):
        """重复初始化不报错（幂等），已写入的备注保持不变。"""
        self.build_legacy_db()

        manager = DBManager(self.db_path)
        try:
            self.assertTrue(manager.update_order_note("ORD-LEGACY", "第二次启动前的备注"))
        finally:
            manager.close()

        # 再次初始化：列已存在，跳过 ALTER，不抛异常
        manager = DBManager(self.db_path)
        try:
            columns = [
                row[1]
                for row in manager.conn.execute("PRAGMA table_info(orders)")
            ]
            self.assertEqual(columns.count("seller_note"), 1)
            self.assertEqual(
                manager.get_order_by_id("ORD-LEGACY")["seller_note"],
                "第二次启动前的备注",
            )
        finally:
            manager.close()

    def test_update_note_and_queries_carry_seller_note(self):
        """新库：写备注后，单订单与订单列表查询都带出 seller_note。"""
        manager = DBManager(self.db_path)
        try:
            order_id = self.seed_user_order(manager)

            # 新订单默认空串
            self.assertEqual(manager.get_order_by_id(order_id)["seller_note"], "")

            # 写备注
            self.assertTrue(manager.update_order_note(order_id, "买家要求尽快发货"))

            self.assertEqual(
                manager.get_order_by_id(order_id)["seller_note"],
                "买家要求尽快发货",
            )
            orders = manager.get_orders_by_cookie("acc-1")
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0]["seller_note"], "买家要求尽快发货")

            # 清空备注
            self.assertTrue(manager.update_order_note(order_id, ""))
            self.assertEqual(manager.get_order_by_id(order_id)["seller_note"], "")
            self.assertEqual(manager.get_orders_by_cookie("acc-1")[0]["seller_note"], "")
        finally:
            manager.close()

    def test_update_note_on_missing_order_returns_false(self):
        """订单不存在时 db 层返回 False（端点据此返回 500/404）。"""
        manager = DBManager(self.db_path)
        try:
            self.assertFalse(manager.update_order_note("ORD-404", "备注"))
        finally:
            manager.close()


if __name__ == "__main__":
    unittest.main()
