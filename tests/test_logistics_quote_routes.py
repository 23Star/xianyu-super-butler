"""物流报价线路明细层测试：归一化、价格模型转换、导入与线路匹配。"""

import os
import sqlite3
import tempfile
import threading
import unittest

from app.services.logistics_quote_routes import (
    LogisticsRouteService,
    build_price_model,
    build_route_rows,
    parse_quote_file,
)
from app.services.logistics_quote_routes.region import (
    is_known_province,
    normalize_region,
    split_region_text,
)

# 省级粒度快递报价表（承运商列 + 省→省 + 首续重）
EXPRESS_CSV = (
    "承运商,发件省,收件省,首重(1KG)价格,续重(1KG)价格\n"
    "中通,江西省,河北省,5,2\n"
    "中通,浙江省,广东省,5.5,2.2\n"
    "圆通,江西省,河北省,6,1.8\n"
    "圆通,湖北省,河北省,7,1.9\n"
).encode("utf-8-sig")

# 市级粒度物流报价表（分段续重表头内含换行，模拟真实百世式表头）
BANDED_CSV = (
    '承运商,发件省,发件市,收件省,收件市,首重(30KG)价格,"0<续重重量≤100kg\n续重价格\n（元/KG）",'
    '"100<续重重量≤500kg\n续重价格\n（元/KG）","续重重量>500kg\n续重价格\n（元/KG）"\n'
    "百世快运,江西省,赣州市,河北省,石家庄市,50,1.5,1.3,1.1\n"
    "百世快运,安徽省,合肥市,上海,上海,42,1.36,1.28,1.18\n"
).encode("utf-8-sig")


def parse_csv(data: bytes) -> dict:
    return parse_quote_file(data, filename="报价.csv")


class RegionTests(unittest.TestCase):
    def test_province_and_city_suffixes_are_stripped(self):
        self.assertEqual(normalize_region("江西省"), "江西")
        self.assertEqual(normalize_region("杭州市"), "杭州")
        self.assertEqual(normalize_region("石家庄市"), "石家庄")

    def test_municipalities_normalize_to_core_names(self):
        self.assertEqual(normalize_region("北京市"), "北京")
        self.assertEqual(normalize_region("上海"), "上海")
        self.assertEqual(normalize_region("天津市"), "天津")

    def test_autonomous_regions_strip_full_suffix(self):
        self.assertEqual(normalize_region("新疆维吾尔自治区"), "新疆")
        self.assertEqual(normalize_region("广西壮族自治区"), "广西")
        self.assertEqual(normalize_region("内蒙古自治区"), "内蒙古")

    def test_unknown_text_survives(self):
        self.assertEqual(normalize_region("赣州市"), "赣州")
        self.assertEqual(normalize_region(""), "")
        self.assertEqual(normalize_region(None), "")

    def test_split_region_text(self):
        self.assertEqual(split_region_text("江西省赣州市"), ("江西", "赣州"))
        self.assertEqual(split_region_text("河北"), ("河北", ""))
        self.assertEqual(split_region_text("广州"), ("", "广州"))

    def test_known_province(self):
        self.assertTrue(is_known_province("湖北省"))
        self.assertFalse(is_known_province("赣州市"))


class PriceModelTests(unittest.TestCase):
    def test_first_additional_row(self):
        model = build_price_model({
            "rule_type": "first_additional",
            "first_weight_kg": 30.0,
            "first_price": 50.14,
            "continued_unit_kg": 1.0,
            "continued_price": 1.49,
            "raw": {"首重(30KG)价格": "50.14", "续重(1KG)价格": "1.49"},
        })
        self.assertEqual(model, {
            "first_weight": 30.0,
            "first_weight_price": 50.14,
            "continued_unit": 1.0,
            "continued_weight_price": 1.49,
        })

    def test_overflow_uses_labelled_first_weight(self):
        """>3KG 溢出段按表头标签口径：首重(1KG)覆盖包裹前 1 公斤。"""
        model = build_price_model({
            "rule_type": "fixed_tiers_overflow",
            "fixed_tiers": [
                {"up_to_kg": 1.0, "price": 5.18},
                {"up_to_kg": 3.0, "price": 7.3},
            ],
            "first_weight_kg": 3.0,
            "first_price": 6.8,
            "continued_unit_kg": 3.0,
            "continued_price": 1.5,
            "raw": {
                "重量>3KG 首重(1KG)价格": "6.8",
                "重量>3KG 续重(1KG)价格": "1.5",
            },
        })
        self.assertEqual(model, {
            "tiers": {"1": 5.18, "3": 7.3},
            "first_weight": 1.0,
            "first_weight_price": 6.8,
            "continued_unit": 1.0,
            "continued_weight_price": 1.5,
        })

    def test_banded_row_maps_tiers_and_overflow(self):
        model = build_price_model({
            "rule_type": "banded_additional",
            "first_weight_kg": 30.0,
            "first_price": 42.0,
            "continued_tiers": [
                {"min_exclusive_kg": 0.0, "max_inclusive_kg": 100.0, "price_per_kg": 1.36},
                {"min_exclusive_kg": 100.0, "max_inclusive_kg": 500.0, "price_per_kg": 1.28},
                {"min_exclusive_kg": 500.0, "price_per_kg": 1.18},
            ],
            "raw": {},
        })
        self.assertEqual(model, {
            "first_weight": 30.0,
            "first_weight_price": 42.0,
            "continued_unit": 1.0,
            "continued_tiers": {"100": 1.36, "500": 1.28},
            "overflow_continued_price": 1.18,
        })

    def test_incomplete_rows_are_rejected(self):
        self.assertIsNone(build_price_model({"rule_type": "first_additional", "first_price": 5.0}))
        self.assertIsNone(build_price_model({"rule_type": "banded_additional", "first_price": 42.0}))
        self.assertIsNone(build_price_model({"rule_type": "unknown_rule"}))


class RouteImportTests(unittest.TestCase):
    def test_build_route_rows_from_express_csv(self):
        result = parse_csv(EXPRESS_CSV)
        rows, warnings = build_route_rows(result)
        self.assertEqual(len(rows), 4)
        self.assertEqual(warnings, [])
        zhongtong = next(row for row in rows if row["carrier"] == "中通" and row["dest_province"] == "河北")
        self.assertEqual(zhongtong["book_kind"], "express")
        self.assertEqual(zhongtong["origin_province"], "江西")
        self.assertEqual(zhongtong["dest_city"], "")
        self.assertEqual(zhongtong["price_model"]["first_weight_price"], 5.0)

    def test_build_route_rows_from_banded_csv(self):
        result = parse_csv(BANDED_CSV)
        rows, _ = build_route_rows(result)
        self.assertEqual(len(rows), 2)
        best = next(row for row in rows if row["dest_city"] == "石家庄")
        self.assertEqual(best["origin_city"], "赣州")
        self.assertEqual(best["book_kind"], "logistics")
        self.assertEqual(best["price_model"]["continued_tiers"], {"100": 1.5, "500": 1.3})
        self.assertEqual(best["price_model"]["overflow_continued_price"], 1.1)

    def test_same_route_deduplicated_per_carrier(self):
        duplicated = EXPRESS_CSV.decode("utf-8-sig") + "中通,江西省,河北省,5,2\n"
        rows, _ = build_route_rows(parse_csv(duplicated.encode("utf-8-sig")))
        self.assertEqual(len(rows), 4)


class RouteServiceTestDatabase:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = threading.RLock()
        self.conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL
            );
            CREATE TABLE logistics_quote_route_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT DEFAULT '',
                size_bytes INTEGER DEFAULT 0,
                sha256 TEXT NOT NULL,
                book_kind TEXT,
                service_count INTEGER DEFAULT 0,
                route_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'completed',
                warnings TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, sha256),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE logistics_quote_routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                import_id INTEGER NOT NULL,
                carrier TEXT NOT NULL,
                book_kind TEXT,
                origin_province TEXT DEFAULT '',
                origin_city TEXT DEFAULT '',
                dest_province TEXT DEFAULT '',
                dest_city TEXT DEFAULT '',
                price_model TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (import_id) REFERENCES logistics_quote_route_imports(id) ON DELETE CASCADE
            );
            """
        )


class RouteServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = RouteServiceTestDatabase(os.path.join(self.temp_dir.name, "routes.db"))
        self.service = LogisticsRouteService(self.manager)
        self.express_import = self.service.import_book(1, "快递.csv", parse_csv(EXPRESS_CSV), *build_route_rows(parse_csv(EXPRESS_CSV)))
        self.banded_import = self.service.import_book(1, "物流.csv", parse_csv(BANDED_CSV), *build_route_rows(parse_csv(BANDED_CSV)))

    def tearDown(self):
        self.manager.conn.close()
        self.temp_dir.cleanup()

    def test_import_is_idempotent_per_file_hash(self):
        refreshed = self.service.import_book(1, "快递-更新.csv", parse_csv(EXPRESS_CSV), *build_route_rows(parse_csv(EXPRESS_CSV)))
        self.assertEqual(refreshed["id"], self.express_import["id"])
        self.assertEqual(refreshed["route_count"], 4)
        self.assertEqual(len(self.service.list_imports(1)), 2)

    def test_imports_are_isolated_per_user(self):
        self.assertEqual(self.service.list_imports(2), [])
        self.assertEqual(self.service.carriers_for_books(2, [self.express_import["id"]], "express"), [])

    def test_delete_import_removes_routes(self):
        self.assertTrue(self.service.delete_import(1, self.banded_import["id"]))
        self.assertIsNone(self.service.get_import(1, self.banded_import["id"]))
        self.assertEqual(self.service.carriers_for_books(1, [self.banded_import["id"]], "logistics"), [])

    def test_resolve_province_by_city(self):
        resolved = self.service.resolve_province_by_city(1, "赣州")
        self.assertEqual(resolved, {"province": "江西", "ambiguous": False})
        resolved_destination = self.service.resolve_province_by_city(1, "石家庄", side="destination")
        self.assertEqual(resolved_destination, {"province": "河北", "ambiguous": False})
        missing = self.service.resolve_province_by_city(1, "不存在市")
        self.assertEqual(missing, {"province": "", "ambiguous": False})

    def test_match_province_level_express(self):
        result = self.service.match_routes(
            1, {"province": "江西", "city": ""}, {"province": "河北", "city": ""}, "express",
            import_ids=[self.express_import["id"]],
        )
        self.assertEqual(set(result["matched"]), {"中通", "圆通"})
        self.assertEqual(result["matched"]["中通"]["match_level"], "province_province")
        self.assertFalse(result["route_not_found"])
        self.assertEqual(result["needs_city_carriers"], [])

    def test_match_city_level_logistics(self):
        result = self.service.match_routes(
            1, {"province": "江西", "city": "赣州"}, {"province": "河北", "city": "石家庄"}, "logistics",
            import_ids=[self.banded_import["id"]],
        )
        self.assertEqual(set(result["matched"]), {"百世快运"})
        self.assertEqual(result["matched"]["百世快运"]["match_level"], "city_city")

    def test_match_mixed_granularity_keeps_each_carrier_best_level(self):
        """快递省级线路与物流市级线路同时命中，各自取最精确级别。"""
        both = self.express_import["id"]
        result = self.service.match_routes(
            1, {"province": "江西", "city": "赣州"}, {"province": "河北", "city": "石家庄"}, "express",
            import_ids=[both],
        )
        self.assertEqual(set(result["matched"]), {"中通", "圆通"})
        self.assertEqual(result["matched"]["中通"]["match_level"], "province_province")

    def test_match_carrier_filter(self):
        result = self.service.match_routes(
            1, {"province": "江西", "city": ""}, {"province": "河北", "city": ""}, "express",
            import_ids=[self.express_import["id"]], carriers=["圆通"],
        )
        self.assertEqual(set(result["matched"]), {"圆通"})

    def test_province_only_falls_back_to_sample_city_for_city_level_carriers(self):
        """买家只给省级地址时，市级粒度承运商按示例城市预报价（标 provisional）。"""
        result = self.service.match_routes(
            1, {"province": "江西", "city": ""}, {"province": "河北", "city": ""}, "logistics",
            import_ids=[self.banded_import["id"]],
        )
        self.assertEqual(set(result["matched"]), {"百世快运"})
        match = result["matched"]["百世快运"]
        self.assertTrue(match["provisional"])
        self.assertEqual(match["origin"], {"province": "江西", "city": "赣州"})
        self.assertEqual(result["match_level"], "province_province")
        self.assertEqual(result["needs_city_carriers"], [])
        self.assertFalse(result["route_not_found"])

    def test_municipality_destination_still_uses_province_fallback(self):
        """收货地是直辖市（上海/上海）时，等同于省级询价，不能挡住备用匹配。"""
        result = self.service.match_routes(
            1, {"province": "安徽", "city": ""}, {"province": "上海", "city": "上海"}, "logistics",
            import_ids=[self.banded_import["id"]],
        )
        self.assertEqual(set(result["matched"]), {"百世快运"})
        match = result["matched"]["百世快运"]
        self.assertTrue(match["provisional"])
        self.assertEqual(match["origin"], {"province": "安徽", "city": "合肥"})
        self.assertEqual(match["destination"], {"province": "上海", "city": "上海"})

    def test_province_exact_rows_are_not_provisional(self):
        """有省级线路的承运商走精确匹配，不标 provisional。"""
        result = self.service.match_routes(
            1, {"province": "江西", "city": ""}, {"province": "河北", "city": ""}, "express",
            import_ids=[self.express_import["id"]],
        )
        self.assertEqual(set(result["matched"]), {"中通", "圆通"})
        for match in result["matched"].values():
            self.assertNotIn("provisional", match)

    def test_route_not_found_when_province_pair_missing(self):
        result = self.service.match_routes(
            1, {"province": "青海", "city": ""}, {"province": "河北", "city": ""}, "express",
            import_ids=[self.express_import["id"]],
        )
        self.assertTrue(result["route_not_found"])
        self.assertEqual(result["needs_city_carriers"], [])


if __name__ == "__main__":
    unittest.main()
