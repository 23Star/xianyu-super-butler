# -*- coding: utf-8 -*-
"""订单导出端点（GET /api/orders/export）的回归测试。

端点函数内是 `from app.db_manager import db_manager` 局部导入，
patch 模块属性即可生效。覆盖：
1. CSV 表头/列映射/UTF-8 BOM/Content-Disposition 文件名
2. status 筛选只保留匹配行（与列表接口同口径的规范化状态）
3. cookie_id 权限：不能导出他人账号订单（空结果仅表头）
4. CSV 注入防护（= + - @ 开头的值加单引号前缀）
5. 空数据返回仅表头的 CSV
6. db 层 get_orders_by_cookie 补充的导出字段（buy_num/post_fee/receiver_city）
"""

import csv
import io
import os
import tempfile
import unittest
from unittest import mock

from app.db_manager import DBManager
from app.reply_server import export_orders


USER = {"user_id": 1, "username": "seller_a"}

# 表头必须与前端导出需求的列顺序严格一致
EXPECTED_HEADERS = [
    '订单号', '商品ID', '商品标题', '买家ID', '规格', '数量', '单价', '运费',
    '订单状态', '收货人', '收货人电话', '收货地址', '城市', '是否议价', '下单时间', '更新时间'
]


def make_order(**overrides):
    """构造一条 get_orders_by_cookie 口径的订单数据。"""
    order = {
        'order_id': 'ORD-001',
        'item_id': 'ITEM-001',
        'buyer_id': 'buyer-001',
        'spec_name': '尺寸',
        'spec_value': 'XL',
        'quantity': '2',
        'amount': '99.00',
        'buy_num': 3,
        'post_fee': '5.00',
        'order_status': 'pending_ship',
        'is_bargain': True,
        'receiver_name': '张三',
        'receiver_phone': '13800138000',
        'receiver_address': '某省某市某区幸福街道1号',
        'receiver_city': '杭州',
        'created_at': '2026-01-01 10:00:00',
        'updated_at': '2026-01-02 10:00:00',
    }
    order.update(overrides)
    return order


def parse_csv(resp):
    """断言响应体以 UTF-8 BOM 开头，返回解析后的行列表。"""
    assert resp.body.startswith(b'\xef\xbb\xbf'), "导出内容必须以 UTF-8 BOM 开头"
    text = resp.body.decode('utf-8-sig')
    return list(csv.reader(io.StringIO(text)))


class ExportOrdersEndpointTests(unittest.TestCase):
    def setUp(self):
        self.db = mock.MagicMock()
        patcher = mock.patch("app.db_manager.db_manager", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        # item_info 商品标题映射默认为空
        self.db.conn.cursor.return_value.fetchall.return_value = []

    def setup_orders(self, orders_by_cookie, item_rows=None):
        """orders_by_cookie: {cookie_id: [order, ...]}；item_rows: [(item_id, item_title)]"""
        self.db.get_all_cookies.return_value = {
            cid: {"value": "cookie-" + cid} for cid in orders_by_cookie
        }
        self.db.get_orders_by_cookie.side_effect = (
            lambda cookie_id, limit=100: orders_by_cookie.get(cookie_id, [])
        )
        if item_rows is not None:
            self.db.conn.cursor.return_value.fetchall.return_value = item_rows

    def test_basic_export(self):
        """表头正确、数据行映射正确、BOM 开头、文件名符合 orders_时间戳.csv。"""
        self.setup_orders(
            {
                'acc-1': [make_order()],
                'acc-2': [make_order(
                    order_id='ORD-002', item_id='ITEM-002',
                    created_at='2026-01-03 10:00:00',
                )],
            },
            item_rows=[('ITEM-001', '测试商品A'), ('ITEM-002', '测试商品B')],
        )

        resp = export_orders(current_user=USER, cookie_id=None, status=None)

        self.assertEqual(resp.media_type, 'text/csv; charset=utf-8')
        self.assertRegex(
            resp.headers['content-disposition'],
            r'^attachment; filename="orders_\d{8}_\d{6}\.csv"$',
        )

        rows = parse_csv(resp)
        self.assertEqual(rows[0], EXPECTED_HEADERS)
        # 两个账号各一条订单
        self.assertEqual(len(rows), 3)
        # 按下单时间倒序，ORD-002（2026-01-03）在前
        self.assertEqual(rows[1][0], 'ORD-002')

        row = rows[2]
        self.assertEqual(row[0], 'ORD-001')          # 订单号
        self.assertEqual(row[1], 'ITEM-001')         # 商品ID
        self.assertEqual(row[2], '测试商品A')          # 商品标题（来自 item_info）
        self.assertEqual(row[3], 'buyer-001')        # 买家ID
        self.assertEqual(row[4], '尺寸=XL')           # 规格 = 名称:值 合并
        self.assertEqual(row[5], '3')                # 数量优先 buy_num
        self.assertEqual(row[6], '99.00')            # 单价
        self.assertEqual(row[7], '5.00')             # 运费
        self.assertEqual(row[8], 'pending_ship')     # 订单状态
        self.assertEqual(row[9], '张三')              # 收货人
        self.assertEqual(row[10], '13800138000')     # 收货人电话
        self.assertEqual(row[11], '某省某市某区幸福街道1号')  # 收货地址
        self.assertEqual(row[12], '杭州')             # 城市
        self.assertEqual(row[13], '是')              # 是否议价
        self.assertEqual(row[14], '2026-01-01 10:00:00')     # 下单时间
        self.assertEqual(row[15], '2026-01-02 10:00:00')     # 更新时间

    def test_quantity_falls_back_to_legacy_field(self):
        """旧数据没有 buy_num 时数量回退用 quantity；议价为否。"""
        self.setup_orders({
            'acc-1': [make_order(buy_num=None, quantity='7', is_bargain=False)],
        })

        rows = parse_csv(export_orders(current_user=USER, cookie_id=None, status=None))

        self.assertEqual(rows[1][5], '7')
        self.assertEqual(rows[1][13], '否')

    def test_status_filter_only_keeps_matching_rows(self):
        """status 筛选使用规范化状态值，只导出匹配行。"""
        self.setup_orders({
            'acc-1': [
                make_order(order_id='ORD-PAID', order_status='pending_ship'),
                make_order(order_id='ORD-DONE', order_status='completed'),
            ],
        })

        rows = parse_csv(export_orders(current_user=USER, cookie_id=None, status='pending_ship'))

        self.assertEqual(len(rows), 2)  # 表头 + 1 条匹配
        self.assertEqual(rows[1][0], 'ORD-PAID')

    def test_other_users_cookie_exports_nothing(self):
        """传入他人账号 cookie_id 时不得导出任何数据（仅表头）。"""
        self.setup_orders({'acc-own': [make_order()]})

        resp = export_orders(current_user=USER, cookie_id='acc-foreign', status=None)

        rows = parse_csv(resp)
        self.assertEqual(rows, [EXPECTED_HEADERS])
        self.db.get_orders_by_cookie.assert_not_called()

    def test_cookie_id_filter_restricts_to_that_account(self):
        """传入自己的 cookie_id 时只导出该账号的订单。"""
        self.setup_orders({
            'acc-1': [make_order(order_id='ORD-A')],
            'acc-2': [make_order(order_id='ORD-B')],
        })

        rows = parse_csv(export_orders(current_user=USER, cookie_id='acc-2', status=None))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], 'ORD-B')
        # 只查询了 acc-2 一个账号
        self.db.get_orders_by_cookie.assert_called_once()

    def test_csv_injection_cells_are_prefixed(self):
        """以 = + - @ 开头的单元格值前加单引号，防 Excel 公式注入。"""
        self.setup_orders({
            'acc-1': [make_order(
                receiver_name='=HYPERLINK("http://evil","点我")',
                receiver_address='+1700000000',
                receiver_phone='-12345678',
                receiver_city='@SUM(1+1)',
            )],
        })

        rows = parse_csv(export_orders(current_user=USER, cookie_id=None, status=None))

        row = rows[1]
        self.assertEqual(row[9], "'=HYPERLINK(\"http://evil\",\"点我\")")
        self.assertEqual(row[11], "'+1700000000")
        self.assertEqual(row[10], "'-12345678")
        self.assertEqual(row[12], "'@SUM(1+1)")

    def test_empty_data_returns_header_only(self):
        """没有订单时也返回仅表头的 CSV，而不是 404。"""
        self.setup_orders({'acc-1': []})

        resp = export_orders(current_user=USER, cookie_id=None, status=None)

        self.assertEqual(resp.status_code, 200)
        rows = parse_csv(resp)
        self.assertEqual(rows, [EXPECTED_HEADERS])


class GetOrdersByCookieExportFieldsTests(unittest.TestCase):
    """db 层 get_orders_by_cookie 必须带出导出需要的补充字段。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = DBManager(os.path.join(self.temp_dir.name, 'xianyu.db'))
        self.addCleanup(self.db.close)

    def test_includes_buy_num_post_fee_and_city(self):
        self.db.conn.execute(
            """
            INSERT INTO orders (
                order_id, cookie_id, item_id, buyer_id, spec_name, spec_value,
                quantity, amount, buy_num, post_fee, order_status, is_bargain,
                receiver_name, receiver_phone, receiver_address, receiver_city
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                'ORD-DB-1', 'acc-db', 'ITEM-9', 'buyer-9', '颜色', '白色',
                '1', '12.00', 2, '3.00', 'pending_ship', 1,
                '李四', '13900000000', '某街道2号', '上海',
            ),
        )
        self.db.conn.commit()

        orders = self.db.get_orders_by_cookie('acc-db', limit=10)

        self.assertEqual(len(orders), 1)
        order = orders[0]
        self.assertEqual(order['buy_num'], 2)
        self.assertEqual(order['post_fee'], '3.00')
        self.assertEqual(order['receiver_city'], '上海')
        self.assertEqual(order['receiver_address'], '某街道2号')


if __name__ == '__main__':
    unittest.main()
