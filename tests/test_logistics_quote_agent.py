"""物流报价 Agent 测试：预筛、状态合并、Workflow 调用、渲染、图编排与会话管理。"""

import os
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from app.services.logistics_agent import extractor
from app.services.logistics_agent.models import ExtractedQuote, SessionState
from app.services.logistics_agent.render import (
    build_quote_values,
    render_follow_up,
    render_no_route,
    render_template,
    split_messages,
    unresolved_tokens,
)
from app.services.logistics_agent.routes import category_for, route_weight_kg
from app.services.logistics_agent.service import LogisticsQuoteAgent
from app.services.logistics_agent.settings import (
    AgentSettings,
    AgentSettingsStore,
    CarrierPricingConfig,
    PricingConfig,
    ReplyTemplates,
)
from app.services.logistics_agent.state import merge_state, missing_fields
from app.services.logistics_agent.tools import build_quote_config, build_workflow_input, call_workflow
from app.services.logistics_agent.pricing import calculate_customer_quote
from app.services.logistics_quote_routes import LogisticsRouteService, build_route_rows, parse_quote_file

# service.py 持有识别管线的注入引用；测试在 service 模块层替换它。
_EXTRACT_TARGET = "app.services.logistics_agent.service.extract_from_model"


def close_cached_checkpointers() -> None:
    """关闭模块级 checkpointer 缓存里的 SQLite 连接并清空缓存。

    checkpointer 对每个临时数据库持有独立连接；测试结束不关闭会让
    Windows 的临时目录清理因文件占用而失败。
    """
    from app.services.logistics_agent import checkpointer as checkpointer_module

    with checkpointer_module._cache_lock:
        for saver in list(checkpointer_module._cache.values()):
            connection = getattr(saver, "conn", None)
            if connection is not None:
                try:
                    connection.close()
                except Exception:  # noqa: BLE001 - 清理失败不阻断测试收尾
                    pass
        checkpointer_module._cache.clear()

EXPRESS_CSV = (
    "承运商,发件省,收件省,首重(1KG)价格,续重(1KG)价格\n"
    "中通,江西省,河北省,5,2\n"
    "圆通,江西省,河北省,6,1.8\n"
).encode("utf-8-sig")

BANDED_CSV = (
    '承运商,发件省,发件市,收件省,收件市,首重(30KG)价格,"0<续重重量≤100kg\n续重价格\n（元/KG）",'
    '"100<续重重量≤500kg\n续重价格\n（元/KG）","续重重量>500kg\n续重价格\n（元/KG）"\n'
    "百世快运,江西省,赣州市,河北省,石家庄市,50,1.5,1.3,1.1\n"
    "百世快运,安徽省,合肥市,上海,上海,42,1.36,1.28,1.18\n"
).encode("utf-8-sig")


class PrefilterTests(unittest.TestCase):
    def test_logistics_keywords_hit(self):
        for text in ("江西寄河北多少钱", "运费怎么算", "发什么快递", "到付可以吗"):
            self.assertTrue(extractor.looks_like_logistics(text), text)

    def test_weight_and_dimension_forms_hit(self):
        self.assertTrue(extractor.looks_like_logistics("20*30*80"))
        self.assertTrue(extractor.looks_like_logistics("长20宽30高80"))
        self.assertTrue(extractor.looks_like_logistics("130kg"))
        self.assertTrue(extractor.looks_like_logistics("5公斤"))

    def test_province_names_hit(self):
        self.assertTrue(extractor.looks_like_logistics("河北有货吗"))
        self.assertFalse(extractor.looks_like_logistics("这个多少钱"))

    def test_non_logistics_misses(self):
        self.assertFalse(extractor.looks_like_logistics("可以便宜一点吗"))
        self.assertFalse(extractor.looks_like_logistics("还有货吗"))

    def test_weight_units(self):
        self.assertEqual(extractor.parse_weight_kg("130kg"), 130.0)
        self.assertEqual(extractor.parse_weight_kg("5公斤"), 5.0)
        self.assertEqual(extractor.parse_weight_kg("3斤"), 1.5)
        self.assertEqual(extractor.parse_weight_kg("500g"), 0.5)
        self.assertIsNone(extractor.parse_weight_kg("两件"))

    def test_dimension_forms(self):
        self.assertEqual(extractor.parse_dimensions("20*30*80"), (20.0, 30.0, 80.0))
        self.assertEqual(extractor.parse_dimensions("长20宽30高80"), (20.0, 30.0, 80.0))
        self.assertIsNone(extractor.parse_dimensions("20*30"))


class StateMergeTests(unittest.TestCase):
    def test_first_message_fills_fields(self):
        state = merge_state(None, ExtractedQuote(intent="logistics_quote", sender="江西省", receiver="河北省"), "m1")
        self.assertEqual(state.sender, "江西省")
        self.assertEqual(state.receiver, "河北省")
        self.assertEqual(state.state_version, 2)
        self.assertEqual(missing_fields(state), ["包裹重量或长宽高"])

    def test_multi_turn_merge_keeps_previous_fields(self):
        state = merge_state(None, ExtractedQuote(intent="logistics_quote", sender="江西省", receiver="河北省"), "m1")
        state = merge_state(state, ExtractedQuote(intent="logistics_quote", length_cm=20, width_cm=30, height_cm=80), "m2")
        self.assertEqual(state.sender, "江西省")
        self.assertEqual(state.length_cm, 20.0)
        self.assertEqual(missing_fields(state), [])

    def test_new_complete_route_starts_new_round(self):
        state = merge_state(None, ExtractedQuote(intent="logistics_quote", sender="江西省", receiver="河北省", weight_kg=2), "m1")
        state.status = "quoted"
        state = merge_state(state, ExtractedQuote(intent="logistics_quote", sender="赣州", receiver="广州", weight_kg=130), "m2")
        self.assertEqual(state.sender, "赣州")
        self.assertEqual(state.weight_kg, 130.0)
        self.assertEqual(state.round_id, 2)

    def test_modification_replaces_target_only(self):
        state = merge_state(None, ExtractedQuote(intent="logistics_quote", sender="江西省", receiver="河北省", weight_kg=2), "m1")
        state = merge_state(state, ExtractedQuote(intent="logistics_quote", receiver="杭州", update_targets=["receiver"]), "m2")
        self.assertEqual(state.sender, "江西省")
        self.assertEqual(state.receiver, "杭州")
        self.assertEqual(state.weight_kg, 2.0)

    def test_new_shipment_flag_resets_params(self):
        state = merge_state(None, ExtractedQuote(intent="logistics_quote", sender="山东省", receiver="江苏省", weight_kg=30), "m1")
        state = merge_state(state, ExtractedQuote(intent="logistics_quote", sender="山东", receiver="江苏", weight_kg=30, is_new_shipment=True), "m2")
        self.assertEqual(state.weight_kg, 30.0)
        self.assertEqual(state.sender, "山东")
        self.assertEqual(state.round_id, 2)

    def test_missing_fields_priority(self):
        empty = SessionState()
        self.assertEqual(missing_fields(empty), ["发货地", "收货地", "包裹重量或长宽高"])
        partial = SessionState(sender="江西")
        self.assertEqual(missing_fields(partial), ["收货地", "包裹重量或长宽高"])
        dims_partial = SessionState(sender="江西", receiver="河北", length_cm=20, width_cm=30)
        self.assertEqual(missing_fields(dims_partial), ["包裹重量或长宽高"])
        complete_dims = SessionState(sender="江西", receiver="河北", length_cm=20, width_cm=30, height_cm=80)
        self.assertEqual(missing_fields(complete_dims), [])


class RouteWeightTests(unittest.TestCase):
    def test_category_boundary_matches_workflow(self):
        self.assertEqual(category_for(29, [None, None, None]), "express")
        self.assertEqual(category_for(29.01, [None, None, None]), "freight")
        self.assertEqual(category_for(30, [None, None, None]), "freight")

    def test_volume_participates_in_route_weight(self):
        self.assertEqual(route_weight_kg(3, [50, 40, 30]), 8)
        self.assertEqual(route_weight_kg(None, [80, 60, 120]), 72)

    def test_python_category_agrees_with_node_workflow(self):
        """Python 分界与 Node Workflow 的 category 对同一批边界值一致。"""
        cases = [(29, "express"), (29.5, "freight"), (30, "freight"), (3, [50, 40, 30], "express")]
        for case in cases:
            weight, dims = (case[0], [None, None, None]) if len(case) == 2 else (case[0], case[1])
            expected = case[-1]
            payload = {
                "weight_kg": weight,
                **({"length_cm": dims[0], "width_cm": dims[1], "height_cm": dims[2]} if all(dims) else {}),
                "quote_config": {"carriers": {"测试": {"price_table": {"first_weight_price": 1, "continued_weight_price": 1}}}},
            }
            result = call_workflow(payload)
            self.assertEqual(result["category"], expected)
            self.assertEqual(category_for(weight, dims), expected)


class WorkflowToolTests(unittest.TestCase):
    def test_call_workflow_partial_failure_keeps_semantics(self):
        payload = {
            "weight_kg": 5,
            "quote_config": {
                "carriers": {
                    "好配置": {"price_table": {"first_weight_price": 12, "continued_weight_price": 4.8}},
                    "坏配置": {"price_table": {}},
                }
            },
        }
        result = call_workflow(payload)
        self.assertFalse(result["success"])
        self.assertTrue(result["partial"])
        self.assertEqual(len(result["quotes"]), 1)
        self.assertEqual(result["errors"][0]["carrier"], "坏配置")

    def test_call_workflow_banded_price_table(self):
        payload = {
            "weight_kg": 35,
            "quote_config": {
                "carriers": {
                    "百世快运": {
                        "price_table": {
                            "first_weight": 30, "first_weight_price": 42, "continued_unit": 1,
                            "continued_tiers": {"100": 1.36, "500": 1.28}, "overflow_continued_price": 1.18,
                        },
                        "payment_mode": "direct",
                    }
                }
            },
        }
        result = call_workflow(payload)
        self.assertTrue(result["success"])
        self.assertEqual(result["quotes"][0]["base_price"], 48.8)

    def test_build_quote_config_prefers_carrier_ratio(self):
        settings = AgentSettings(
            carrier_config={"百世快运": CarrierPricingConfig(volume_ratio=6000)},
            default_volume_ratios={"百世快运": 5000},
        )
        config = build_quote_config(settings, {"百世快运": {"price_model": {"first_weight_price": 5, "continued_weight_price": 1}}})
        self.assertEqual(config["carriers"]["百世快运"]["volume_ratio"], 6000)
        self.assertEqual(config["default_volume_ratios"]["百世快运"], 5000)

    def test_build_workflow_input_omits_empty_fields(self):
        state = SessionState(weight_kg=2, sender="江西", receiver="河北")
        payload = build_workflow_input(state, {"carriers": {}})
        self.assertEqual(payload["weight_kg"], 2)
        self.assertNotIn("length_cm", payload)
        self.assertEqual(payload["sender"], "江西")


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.state = SessionState(sender="江西省赣州市", receiver="河北省石家庄市", weight_kg=2, length_cm=20, width_cm=30, height_cm=80)
        self.quotes = [
            {
                "carrier": "中通", "volume_ratio": 8000, "chargeable_weight_kg": 6,
                "base_price": 36.0, "adjusted_price": 36.0, "total_price": 36.0,
                "platform_payment": 36.0, "remaining_payment": 0, "payment_mode": "direct",
            },
        ]
        self.routes = {
            "中通": {
                "carrier": "中通",
                "origin": {"province": "江西", "city": "赣州"},
                "destination": {"province": "河北", "city": "石家庄"},
                "price_model": {},
                "match_level": "city_city",
                "match_level_label": "市→市",
            },
        }
        self.pricing = PricingConfig(card_face_value=100, platform_face_value=2.49, profit_markup=0)

    def test_customer_quote_subtracts_coupon_discount(self):
        quote = calculate_customer_quote(50, coupon_discount=2.49)
        self.assertEqual(quote.payable, 47.51)
        marked = calculate_customer_quote(50, coupon_discount=2.49, profit_markup=5)
        self.assertEqual(marked.payable, 52.51)

    def test_quote_values_use_real_results(self):
        values = build_quote_values(self.state, self.quotes, self.routes, self.pricing)
        self.assertEqual(values["快递总价"], "¥36.00")
        self.assertEqual(values["合计"], "¥33.51")
        self.assertEqual(values["补差价"], "¥33.51")
        self.assertEqual(values["计费重量"], "6kg")
        self.assertIn("中通", values["渠道报价行"])
        self.assertEqual(values["体积重"], "6kg")
        self.assertEqual(values["体积算式"], "20×30×80cm ÷ 8000 = 6.0kg")

    def test_template_render_and_split(self):
        text = render_template("第一段{合计}{分隔符}第二段{未知参数}", {"合计": "¥118.00"})
        self.assertEqual(split_messages(text), ["第一段¥118.00", "第二段{未知参数}"])

    def test_follow_up_and_no_route(self):
        self.assertEqual(render_follow_up("还需要{缺失字段}哦～", "发货地"), "还需要发货地哦～")
        text = render_no_route("{发货省}到{收货省}无线路", "江西", "河北")
        self.assertEqual(text, "江西到河北无线路")


class AgentSettingsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = AgentTestDatabase(os.path.join(self.temp_dir.name, "agent.db"))
        self.store = AgentSettingsStore(self.manager)

    def tearDown(self):
        close_cached_checkpointers()
        self.manager.conn.close()
        self.temp_dir.cleanup()

    def test_defaults_when_missing(self):
        settings = self.store.load("acc1")
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.model_name, "deepseek-v4-flash")

    def test_save_load_roundtrip(self):
        settings = AgentSettings(
            enabled=True, model_name="deepseek-v4-pro", book_ids=[1, 2], auto_send=True,
            recommend_mode="all", item_scope="custom", item_ids=["item-1"],
            pricing=PricingConfig(card_face_value=100, platform_face_value=100, profit_markup=5),
            templates=ReplyTemplates(quote_message="自定义模板 {合计}"),
        )
        self.assertTrue(self.store.save("acc1", settings))
        loaded = self.store.load("acc1")
        self.assertEqual(loaded.model_name, "deepseek-v4-pro")
        self.assertEqual(loaded.book_ids, [1, 2])
        self.assertTrue(loaded.auto_send)
        self.assertEqual(loaded.pricing.card_face_value, 100)
        self.assertEqual(loaded.templates.quote_message, "自定义模板 {合计}")

    def test_unknown_model_falls_back(self):
        self.assertTrue(self.store.save("acc1", AgentSettings(enabled=True, model_name="gpt-9")))
        self.assertEqual(self.store.load("acc1").model_name, "deepseek-v4-flash")

    def test_book_scope_resolution(self):
        settings = AgentSettings(book_ids=[1, 3])
        self.assertEqual(settings.resolved_book_ids([1, 2, 3]), [1, 3])
        fallback = AgentSettings()
        self.assertEqual(fallback.resolved_book_ids([1, 2]), [1, 2])

    def test_exists_tracks_saved_state(self):
        self.assertFalse(self.store.exists("acc1"))
        self.store.save("acc1", AgentSettings())
        self.assertTrue(self.store.exists("acc1"))
        self.assertFalse(self.store.exists("acc2"))


class AgentTestDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
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
            CREATE TABLE logistics_quote_books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT DEFAULT '',
                size_bytes INTEGER DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                book_kind TEXT,
                service_count INTEGER DEFAULT 0,
                route_count INTEGER DEFAULT 0,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, sha256)
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
                UNIQUE(user_id, sha256)
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
                price_model TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE logistics_agent_settings (
                cookie_id TEXT PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                model_name TEXT DEFAULT 'deepseek-v4-flash',
                book_ids TEXT DEFAULT '[]',
                auto_send INTEGER DEFAULT 0,
                recommend_mode TEXT DEFAULT 'lowest',
                no_route_policy TEXT DEFAULT 'manual',
                item_scope TEXT DEFAULT 'all',
                item_ids TEXT DEFAULT '[]',
                carrier_config TEXT DEFAULT '{}',
                default_volume_ratios TEXT DEFAULT '{}',
                pricing_config TEXT DEFAULT '{}',
                templates TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE logistics_quote_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cookie_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                item_id TEXT DEFAULT '',
                state TEXT NOT NULL DEFAULT '{}',
                state_version INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active',
                last_message_id TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(cookie_id, chat_id, item_id)
            );
            CREATE TABLE logistics_quote_send_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cookie_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                item_id TEXT DEFAULT '',
                message_id TEXT DEFAULT '',
                state_version INTEGER DEFAULT 0,
                book_sha256 TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX idx_logistics_quote_send_logs_unique
            ON logistics_quote_send_logs(cookie_id, chat_id, item_id, message_id)
            WHERE message_id != '';
            """
        )

    def get_cookie_owner_user(self, cookie_id: str):
        cursor = self.conn.execute("SELECT user_id FROM cookies WHERE id = ?", (cookie_id,))
        row = cursor.fetchone()
        return int(row[0]) if row else None

    def get_all_cookies(self, user_id: int = None):
        cursor = self.conn.execute("SELECT id, value FROM cookies", ()) if user_id is None else self.conn.execute(
            "SELECT id, value FROM cookies WHERE user_id = ?", (user_id,)
        )
        return {row[0]: row[1] for row in cursor.fetchall()}


class AgentServiceTests(unittest.TestCase):
    """完整编排：识别结果 mock，线路真实匹配，Workflow 真实调用。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = AgentTestDatabase(os.path.join(self.temp_dir.name, "agent.db"))
        self.manager.conn.execute("INSERT INTO cookies (id, value, user_id) VALUES ('acc1', 'v', 1)")
        self.manager.conn.commit()
        self.agent = LogisticsQuoteAgent(self.manager)
        self.route_service = LogisticsRouteService(self.manager)
        express_parse = parse_quote_file(EXPRESS_CSV, filename="快递.csv")
        express_rows, _ = build_route_rows(express_parse)
        self.express_import = self.route_service.import_book(1, "快递.csv", express_parse, express_rows, [])
        banded_parse = parse_quote_file(BANDED_CSV, filename="物流.csv")
        banded_rows, _ = build_route_rows(banded_parse)
        self.banded_import = self.route_service.import_book(1, "物流.csv", banded_parse, banded_rows, [])

        settings = AgentSettings(enabled=True, book_ids=[self.express_import["id"], self.banded_import["id"]])
        self.store = AgentSettingsStore(self.manager)
        self.store.save("acc1", settings)

    def tearDown(self):
        close_cached_checkpointers()
        self.manager.conn.close()
        self.temp_dir.cleanup()

    def _extract(self, **overrides) -> ExtractedQuote:
        base = {
            "intent": "logistics_quote",
            "sender": "江西省赣州市",
            "receiver": "河北省石家庄市",
            "weight_kg": 2.0,
            "length_cm": 20.0,
            "width_cm": 30.0,
            "height_cm": 80.0,
            "sender_confidence": 0.9,
            "receiver_confidence": 0.9,
            "weight_confidence": 0.9,
        }
        base.update(overrides)
        return ExtractedQuote(**base)

    def _run(self, message: str, message_id: str = "m1", **extract_overrides):
        extracted = self._extract(**extract_overrides)

        def _fake_extract(cookie_id, settings, text, session):
            return extracted

        with mock.patch(_EXTRACT_TARGET, side_effect=_fake_extract):
            return self.agent.handle_message(
                message=message, chat_id="chat1", cookie_id="acc1", item_id="item1", message_id=message_id,
            )

    def test_disabled_agent_returns_none(self):
        decision = self._run("江西寄河北，2公斤，20*30*80")
        self.assertIsNotNone(decision)
        self.store.save("acc1", AgentSettings(enabled=False))
        decision = self._run("江西寄河北，2公斤，20*30*80")
        self.assertIsNone(decision)

    def test_item_scope_filters(self):
        self.store.save("acc1", AgentSettings(enabled=True, book_ids=[self.express_import["id"]], item_scope="custom", item_ids=["other-item"]))
        decision = self._run("江西寄河北，2公斤，20*30*80")
        self.assertIsNone(decision)

    def test_complete_message_quotes_and_stays_draft_without_auto_send(self):
        decision = self._run("江西寄河北，2公斤，20*30*80")
        self.assertEqual(decision.action, "draft")
        self.assertEqual(decision.reason, "quoted")
        self.assertTrue(decision.messages)
        self.assertTrue(any("¥" in message for message in decision.messages))
        self.assertEqual(decision.session_status, "quoted")

    def test_auto_send_enabled_marks_reply(self):
        self.store.save("acc1", AgentSettings(enabled=True, auto_send=True, book_ids=[self.express_import["id"], self.banded_import["id"]]))
        decision = self._run("江西寄河北，2公斤，20*30*80")
        self.assertEqual(decision.action, "reply")

    def test_duplicate_message_id_is_ignored(self):
        first = self._run("江西寄河北", message_id="m1")
        self.assertIsNotNone(first)
        again = self._run("江西寄河北", message_id="m1")
        self.assertEqual(again.action, "ignore")
        self.assertEqual(again.reason, "duplicate_message")

    def test_multi_turn_follow_up_then_quote(self):
        first = self._run("江西寄河北", message_id="m1", sender="江西省", receiver="河北省", weight_kg=None, length_cm=None, width_cm=None, height_cm=None)
        self.assertEqual(first.reason, "missing_params")
        second = self._run("20*30*80，2公斤", message_id="m2", sender="江西省赣州市", receiver="河北省石家庄市", weight_kg=2, length_cm=20, width_cm=30, height_cm=80)
        self.assertEqual(second.reason, "quoted")

    def test_province_only_message_asks_city_for_city_level_books(self):
        """省级地址 + 物流表只有市级线路：追问城市而不是转人工。"""
        decision = self._run("江西寄河北，130公斤", message_id="m1", sender="江西省", receiver="河北省", weight_kg=130)
        self.assertEqual(decision.reason, "missing_city")
        self.assertEqual(decision.missing_fields, ["收货城市"])

    def test_city_level_message_quotes_freight(self):
        decision = self._run("赣州寄石家庄，130公斤", message_id="m1", sender="江西省赣州市", receiver="河北省石家庄市", weight_kg=130)
        self.assertEqual(decision.reason, "quoted")
        self.assertEqual([route.carrier for route in decision.routes], ["百世快运"])
        quote = decision.quotes[0]
        self.assertEqual(quote["chargeable_weight_kg"], 130)
        # 首重30KG 50元 + 续重100kg × 1.5 = 200
        self.assertEqual(quote["total_price"], 200.0)

    def test_auto_send_off_keeps_follow_up_and_failure_as_draft(self):
        """统一发送闸门：自动发送关闭时，追问与失败提示都不进入发送分支。"""
        follow_up = self._run("江西寄河北", message_id="m1", sender="江西省", receiver="河北省", weight_kg=None, length_cm=None, width_cm=None, height_cm=None)
        self.assertEqual(follow_up.action, "draft")
        self.assertEqual(follow_up.reason, "missing_params")
        failure = self._run("青海寄河北，2公斤", message_id="m2", sender="青海省", receiver="河北省", weight_kg=2)
        self.assertEqual(failure.action, "draft")
        self.assertEqual(failure.reason, "route_not_found")

    def test_unknown_province_falls_to_manual(self):
        self.store.save("acc1", AgentSettings(enabled=True, auto_send=True, book_ids=[self.express_import["id"], self.banded_import["id"]]))
        decision = self._run("青海寄河北，2公斤", message_id="m1", sender="青海省", receiver="河北省", weight_kg=2)
        self.assertEqual(decision.reason, "route_not_found")
        self.assertEqual(decision.action, "manual")

    def test_no_route_silent_policy_drafts(self):
        self.store.save("acc1", AgentSettings(enabled=True, no_route_policy="silent", book_ids=[self.express_import["id"]]))
        decision = self._run("青海寄河北，2公斤", message_id="m1", sender="青海省", receiver="河北省", weight_kg=2)
        self.assertEqual(decision.action, "draft")
        self.assertEqual(decision.reason, "route_not_found")

    def test_carrier_filter_via_buyer_message(self):
        decision = self._run("江西寄河北，2公斤，走圆通", message_id="m1", sender="江西省", receiver="河北省", weight_kg=2, carrier="圆通")
        self.assertEqual(decision.reason, "quoted")
        self.assertEqual([route.carrier for route in decision.routes], ["圆通"])

    def test_non_logistics_intent_falls_back(self):
        with mock.patch(_EXTRACT_TARGET, return_value=ExtractedQuote(intent="other")):
            decision = self.agent.handle_message(
                message="可以便宜一点吗", chat_id="chat2", cookie_id="acc1", item_id="item1", message_id="m9",
            )
        self.assertIsNone(decision)


class AgentGraphSessionTests(unittest.TestCase):
    """LangGraph 会话：多轮上下文、隔离、幂等、恢复、模板参数与审计事件。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = AgentTestDatabase(os.path.join(self.temp_dir.name, "graph.db"))
        self.manager.conn.execute("INSERT INTO cookies (id, value, user_id) VALUES ('acc1', 'v', 1)")
        self.manager.conn.commit()
        self.route_service = LogisticsRouteService(self.manager)
        express_parse = parse_quote_file(EXPRESS_CSV, filename="快递.csv")
        express_rows, _ = build_route_rows(express_parse)
        self.express_import = self.route_service.import_book(1, "快递.csv", express_parse, express_rows, [])
        banded_parse = parse_quote_file(BANDED_CSV, filename="物流.csv")
        banded_rows, _ = build_route_rows(banded_parse)
        self.banded_import = self.route_service.import_book(1, "物流.csv", banded_parse, banded_rows, [])
        self.store = AgentSettingsStore(self.manager)
        self.store.save("acc1", AgentSettings(
            enabled=True, book_ids=[self.express_import["id"], self.banded_import["id"]],
        ))

    def tearDown(self):
        close_cached_checkpointers()
        self.manager.conn.close()
        self.temp_dir.cleanup()

    def _agent(self) -> LogisticsQuoteAgent:
        return LogisticsQuoteAgent(self.manager)

    def _preview(self, agent, thread_id, message, message_id, **extract_overrides):
        extracted = self._extract(**extract_overrides)

        def _fake_extract(cookie_id, settings, text, session):
            return extracted

        with mock.patch(_EXTRACT_TARGET, side_effect=_fake_extract):
            return agent.preview_message(
                message=message, chat_id="chat1", cookie_id="acc1", item_id="item1",
                message_id=message_id, thread_id=thread_id,
            )

    def _extract(self, **overrides) -> ExtractedQuote:
        base = {
            "intent": "logistics_quote",
            "sender": "江西省赣州市",
            "receiver": "河北省石家庄市",
            "weight_kg": 2.0,
            "length_cm": 20.0,
            "width_cm": 30.0,
            "height_cm": 80.0,
        }
        base.update(overrides)
        return ExtractedQuote(**base)

    def test_multi_turn_context_merges_previous_fields(self):
        """江西寄河北 -> 20*30*80：第二条继承地址并进入报价。"""
        agent = self._agent()
        thread_id = agent.new_thread_id()
        first = self._preview(
            agent, thread_id, "江西寄河北", "m1",
            sender="江西省", receiver="河北省", weight_kg=None, length_cm=None, width_cm=None, height_cm=None,
        )
        self.assertEqual(first.reason, "missing_params")
        second = self._preview(
            agent, thread_id, "20*30*80，2公斤", "m2",
            sender=None, receiver=None,
        )
        self.assertEqual(second.reason, "quoted")
        self.assertEqual(second.fields["sender"], "江西省")
        self.assertEqual(second.fields["receiver"], "河北省")

    def test_modification_updates_target_fields_only(self):
        """把收货地改成石家庄、2公斤改3公斤：只覆盖目标字段，不开新轮次。"""
        agent = self._agent()
        thread_id = agent.new_thread_id()
        self._preview(agent, thread_id, "江西寄河北，2公斤", "m1")
        second = self._preview(
            agent, thread_id, "把收货地改成河北省石家庄市，3公斤", "m2",
            sender=None, receiver="河北省石家庄市", weight_kg=3, update_targets=["receiver", "weight"],
        )
        self.assertEqual(second.reason, "quoted")
        self.assertEqual(second.fields["sender"], "江西省赣州市")
        self.assertEqual(second.fields["receiver"], "河北省石家庄市")
        self.assertEqual(second.fields["weight_kg"], 3.0)
        self.assertEqual(second.fields["round_id"], 1)
        self.assertEqual(second.state_version, 3)

    def test_new_complete_route_starts_new_round(self):
        """已报价后新的完整询价：开新轮次，不混用上一单尺寸。"""
        agent = self._agent()
        thread_id = agent.new_thread_id()
        self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")
        second = self._preview(
            agent, thread_id, "赣州寄石家庄130kg", "m2",
            sender="江西省赣州市", receiver="河北省石家庄市", weight_kg=130,
            length_cm=None, width_cm=None, height_cm=None,
        )
        self.assertEqual(second.reason, "quoted")
        self.assertEqual(second.fields["round_id"], 2)
        self.assertIsNone(second.fields["length_cm"])
        # 旧轮次消息仍可从会话记录追溯。
        snapshot = agent.thread_snapshot(thread_id)
        buyer_messages = [m for m in snapshot["messages"] if m["role"] == "buyer"]
        self.assertEqual(len(buyer_messages), 2)

    def test_threads_are_isolated_by_thread_id(self):
        """两个不同 thread 即使同账号同商品，状态也完全隔离。"""
        agent = self._agent()
        thread_a = agent.new_thread_id()
        thread_b = agent.new_thread_id()
        self._preview(agent, thread_a, "江西寄河北", "m1", sender="江西省", receiver="河北省",
                      weight_kg=None, length_cm=None, width_cm=None, height_cm=None)
        second = self._preview(agent, thread_b, "2公斤", "m2", sender=None, receiver=None,
                               weight_kg=2, length_cm=None, width_cm=None, height_cm=None)
        # thread_b 没有地址上下文：不应继承 thread_a 的地址。
        self.assertEqual(second.reason, "missing_params")

    def test_duplicate_message_id_is_ignored_but_new_id_processes(self):
        agent = self._agent()
        thread_id = agent.new_thread_id()
        first = self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")
        self.assertEqual(first.reason, "quoted")
        again = self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")
        self.assertEqual(again.action, "ignore")
        self.assertEqual(again.reason, "duplicate_message")
        same_text_new_id = self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m2")
        self.assertEqual(same_text_new_id.reason, "quoted")

    def test_retry_across_rounds_is_ignored_and_version_monotonic(self):
        """消息处理记录跨轮次保留：旧消息在开启新一轮后重发仍识别为重试。"""
        agent = self._agent()
        thread_id = agent.new_thread_id()
        first = self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")
        self.assertEqual(first.reason, "quoted")
        second = self._preview(
            agent, thread_id, "赣州寄石家庄130kg", "m2",
            sender="江西省赣州市", receiver="河北省石家庄市", weight_kg=130,
            length_cm=None, width_cm=None, height_cm=None,
        )
        self.assertEqual(second.reason, "quoted")
        self.assertEqual(second.fields["round_id"], 2)
        self.assertGreater(second.state_version, first.state_version)
        retry = self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")
        self.assertEqual(retry.action, "ignore")
        self.assertEqual(retry.reason, "duplicate_message")

    def test_new_round_with_missing_params_has_no_stale_quotes(self):
        """新询价缺参：上一轮报价、线路与报价表哈希不再混入当前决策。"""
        agent = self._agent()
        thread_id = agent.new_thread_id()
        first = self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")
        self.assertEqual(first.reason, "quoted")
        self.assertTrue(first.quotes)
        second = self._preview(
            agent, thread_id, "江西寄上海多少钱", "m2",
            sender="江西省", receiver="上海", weight_kg=None,
            length_cm=None, width_cm=None, height_cm=None,
        )
        self.assertEqual(second.reason, "missing_params")
        self.assertEqual(second.quotes, [])
        self.assertEqual(second.routes, [])
        self.assertEqual(second.book_sha256, "")

    def test_concurrent_same_thread_no_lost_update(self):
        """同一会话完整处理周期串行：并发提交的两个参数都不丢，版本单调。"""
        agent = self._agent()
        thread_id = agent.new_thread_id()
        extract_started = threading.Event()
        release_extract = threading.Event()

        def _dispatch_extract(cookie_id, settings, text, session):
            if text == "发货地江西":
                extract_started.set()
                release_extract.wait(5)
                return self._extract(sender="江西省", receiver=None, weight_kg=None,
                                     length_cm=None, width_cm=None, height_cm=None)
            return self._extract(sender=None, receiver="河北省", weight_kg=None,
                                 length_cm=None, width_cm=None, height_cm=None)

        results: dict[str, Any] = {}

        def _run_first():
            results["first"] = agent.preview_message(
                message="发货地江西", chat_id="chat1", cookie_id="acc1", item_id="item1",
                message_id="m1", thread_id=thread_id,
            )

        # 单一 patch 覆盖两次调用：识别函数按消息内容分流，避免两个
        # patch 上下文跨线程互相覆盖目标属性。
        with mock.patch(_EXTRACT_TARGET, side_effect=_dispatch_extract):
            first_thread = threading.Thread(target=_run_first)
            first_thread.start()
            self.assertTrue(extract_started.wait(5), "识别节点未开始")
            # 第一条消息还在识别中时提交第二条：第二个处理周期必须等第一个完成。
            release_extract.set()
            results["second"] = agent.preview_message(
                message="收货地河北", chat_id="chat1", cookie_id="acc1", item_id="item1",
                message_id="m2", thread_id=thread_id,
            )
            first_thread.join(10)

        self.assertEqual(results["first"].reason, "missing_params")
        self.assertEqual(results["second"].reason, "missing_params")
        self.assertEqual(results["second"].state_version, results["first"].state_version + 1)
        snapshot = agent.thread_snapshot(thread_id)
        session = snapshot["session"]
        self.assertEqual(session["sender"], "江西省")
        self.assertEqual(session["receiver"], "河北省")

    def test_mid_flow_failure_allows_same_message_retry(self):
        """合并之后中途失败：消息不占用幂等凭据，同 ID 重试可以完整跑完。"""
        agent = self._agent()
        thread_id = agent.new_thread_id()
        with mock.patch(_EXTRACT_TARGET, return_value=self._extract()):
            with mock.patch.object(
                agent.route_service, "list_imports", side_effect=RuntimeError("线路服务闪断"),
            ):
                with self.assertRaises(RuntimeError):
                    agent.preview_message(
                        message="江西寄河北，2公斤，20*30*80", chat_id="chat1", cookie_id="acc1",
                        item_id="item1", message_id="m1", thread_id=thread_id,
                    )
        retried = self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")
        self.assertEqual(retried.reason, "quoted")

    def test_model_failure_persisted_with_template_gate(self):
        """模型超时：决策、快照与审计一致；失败模板占位符不进入发送文本。"""
        self.store.save("acc1", AgentSettings(
            enabled=True,
            book_ids=[self.express_import["id"], self.banded_import["id"]],
            templates=ReplyTemplates(failure="请联系客服，错误{未知参数}"),
        ))
        agent = self._agent()
        thread_id = agent.new_thread_id()

        from app.services.logistics_agent.model import ModelCallError

        with mock.patch(_EXTRACT_TARGET, side_effect=ModelCallError("识别超时")):
            decision = agent.preview_message(
                message="江西寄河北，2公斤", chat_id="chat1", cookie_id="acc1",
                item_id="item1", message_id="m1", thread_id=thread_id,
            )
        self.assertEqual(decision.reason, "model_failed")
        for text in decision.messages:
            self.assertEqual(unresolved_tokens(text), [])

        snapshot = agent.thread_snapshot(thread_id)
        self.assertEqual(snapshot["session"]["status"], "failed")
        self.assertEqual(snapshot["last_action"], decision.action)
        self.assertEqual(snapshot["last_reason"], "model_failed")
        agent_texts = [m["content"] for m in snapshot["messages"] if m["role"] == "agent"]
        self.assertTrue(agent_texts)
        self.assertEqual(unresolved_tokens(agent_texts[-1]), [])

        # 故障不占用幂等凭据：同一条消息可以立即重试并完整跑完。
        retried = self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")
        self.assertEqual(retried.reason, "quoted")

    def test_session_survives_agent_recreation(self):
        """进程重启（重建 Agent 与 checkpointer 连接）后按 thread 恢复状态与消息。"""
        agent = self._agent()
        thread_id = agent.new_thread_id()
        self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")

        close_cached_checkpointers()
        revived = self._agent()
        snapshot = revived.thread_snapshot(thread_id)
        self.assertTrue(snapshot["exists"])
        self.assertEqual(snapshot["session"]["receiver"], "河北省石家庄市")
        self.assertEqual(snapshot["session"]["status"], "quoted")
        roles = [message["role"] for message in snapshot["messages"]]
        self.assertIn("buyer", roles)
        self.assertIn("agent", roles)

    def test_reset_thread_clears_session(self):
        agent = self._agent()
        thread_id = agent.new_thread_id()
        self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")
        self.assertTrue(agent.thread_snapshot(thread_id)["exists"])
        self.assertTrue(agent.reset_thread(thread_id))
        self.assertFalse(agent.thread_snapshot(thread_id)["exists"])

    def test_follow_up_template_renders_default_weight(self):
        """{默认重量}：开关开启渲染 1kg，关闭显示待核价，不出现占位符。"""
        self.store.save("acc1", AgentSettings(
            enabled=True,
            book_ids=[self.express_import["id"], self.banded_import["id"]],
            pricing=PricingConfig(default_one_kg=True),
            templates=ReplyTemplates(missing_params="还差{缺失字段}哦，将按{默认重量}计费"),
        ))
        agent = self._agent()
        thread_id = agent.new_thread_id()
        # 第一条只给重量（走 first_reply 模板），第二条补发货地后仍缺收货地。
        self._preview(agent, thread_id, "2公斤", "m1", sender=None, receiver=None,
                      length_cm=None, width_cm=None, height_cm=None)
        decision = self._preview(agent, thread_id, "发货地江西", "m2", sender="江西省", receiver=None,
                                 length_cm=None, width_cm=None, height_cm=None)
        self.assertEqual(decision.reason, "missing_params")
        self.assertIn("收货地", decision.messages[0])
        self.assertIn("1kg", decision.messages[0])
        self.assertNotIn("{默认重量}", decision.messages[0])
        self.assertEqual(unresolved_tokens(decision.messages[0]), [])

        self.store.save("acc1", AgentSettings(
            enabled=True,
            book_ids=[self.express_import["id"], self.banded_import["id"]],
            pricing=PricingConfig(default_one_kg=False),
            templates=ReplyTemplates(missing_params="还差{缺失字段}哦，将按{默认重量}计费"),
        ))
        agent = self._agent()
        thread_id = agent.new_thread_id()
        self._preview(agent, thread_id, "2公斤", "m1", sender=None, receiver=None,
                      length_cm=None, width_cm=None, height_cm=None)
        decision = self._preview(agent, thread_id, "发货地江西", "m2", sender="江西省", receiver=None,
                                 length_cm=None, width_cm=None, height_cm=None)
        self.assertNotIn("{默认重量}", decision.messages[0])
        self.assertIn("待核价", decision.messages[0])

    def test_unresolved_template_param_blocks_send(self):
        """模板中的未知参数不允许进入发送文本，自动发送关闭时只留草稿。"""
        agent = self._agent()
        self.store.save("acc1", AgentSettings(
            enabled=True,
            book_ids=[self.express_import["id"]],
            templates=ReplyTemplates(quote_message="运费{快递总价}，备注{不存在的参数}"),
        ))
        decision = self._preview(agent, agent.new_thread_id(), "江西寄河北，2公斤，20*30*80", "m1")
        self.assertEqual(decision.reason, "template_unresolved")
        self.assertEqual(decision.action, "draft")
        for message in decision.messages:
            self.assertEqual(unresolved_tokens(message), [])

    def test_unresolved_template_param_marks_manual_when_auto_send_on(self):
        """自动发送开启时，未解析占位符转人工且不把占位符发给买家。"""
        agent = self._agent()
        self.store.save("acc1", AgentSettings(
            enabled=True,
            auto_send=True,
            book_ids=[self.express_import["id"]],
            templates=ReplyTemplates(quote_message="运费{快递总价}，备注{不存在的参数}"),
        ))
        decision = self._preview(agent, agent.new_thread_id(), "江西寄河北，2公斤，20*30*80", "m1")
        self.assertEqual(decision.reason, "template_unresolved")
        self.assertEqual(decision.action, "manual")
        for message in decision.messages:
            self.assertEqual(unresolved_tokens(message), [])

    def test_node_audit_events_recorded(self):
        agent = self._agent()
        thread_id = agent.new_thread_id()
        self._preview(agent, thread_id, "江西寄河北，2公斤，20*30*80", "m1")
        nodes = [event["node"] for event in agent.thread_snapshot(thread_id)["events"]]
        for node in ("extract", "merge_state", "check_missing", "resolve_routes", "call_workflow", "render_reply", "finalize"):
            self.assertIn(node, nodes)


class SendGateTests(unittest.TestCase):
    """发送闸门：状态/报价表版本校验与待发送记录唯一登记。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = AgentTestDatabase(os.path.join(self.temp_dir.name, "send-gate.db"))
        self.manager.conn.execute("INSERT INTO cookies (id, value, user_id) VALUES ('acc1', 'v', 1)")
        self.manager.conn.commit()
        self.agent = LogisticsQuoteAgent(self.manager)
        self.route_service = LogisticsRouteService(self.manager)
        express_parse = parse_quote_file(EXPRESS_CSV, filename="快递.csv")
        express_rows, _ = build_route_rows(express_parse)
        self.express_import = self.route_service.import_book(1, "快递.csv", express_parse, express_rows, [])
        AgentSettingsStore(self.manager).save(
            "acc1", AgentSettings(enabled=True, auto_send=True, book_ids=[self.express_import["id"]]),
        )

    def tearDown(self):
        close_cached_checkpointers()
        self.manager.conn.close()
        self.temp_dir.cleanup()

    def _quoted_decision(self):
        extracted = ExtractedQuote(
            intent="logistics_quote", sender="江西省", receiver="河北省", weight_kg=2.0,
            length_cm=20.0, width_cm=30.0, height_cm=80.0,
        )
        with mock.patch(_EXTRACT_TARGET, return_value=extracted):
            decision = self.agent.handle_message(
                message="江西寄河北，2公斤，20*30*80", chat_id="chat1", cookie_id="acc1",
                item_id="item1", message_id="m1",
            )
        self.assertEqual(decision.action, "reply")
        return decision

    def _claim(self, decision, **overrides):
        payload = {
            "cookie_id": "acc1", "chat_id": "chat1", "item_id": "item1", "message_id": "m1",
            "state_version": decision.state_version, "book_sha256": decision.book_sha256,
        }
        payload.update(overrides)
        return self.agent.claim_send(**payload)

    def _send_rows(self):
        cursor = self.manager.conn.execute(
            "SELECT message_id, status FROM logistics_quote_send_logs ORDER BY id"
        )
        return [{"message_id": row[0], "status": row[1]} for row in cursor.fetchall()]

    def test_claim_send_records_pending_and_blocks_duplicate(self):
        decision = self._quoted_decision()
        self.assertTrue(self._claim(decision))
        rows = self._send_rows()
        self.assertEqual(rows, [{"message_id": "m1", "status": "pending"}])
        # 同一消息已有待发送/已发送记录：不允许重复登记（防重发）。
        self.assertFalse(self._claim(decision))
        self.agent.mark_send_result(
            cookie_id="acc1", chat_id="chat1", item_id="item1", message_id="m1", success=True,
        )
        self.assertEqual(self._send_rows()[0]["status"], "sent")
        self.assertFalse(self._claim(decision))

    def test_mark_send_result_records_failure(self):
        decision = self._quoted_decision()
        self.assertTrue(self._claim(decision))
        self.agent.mark_send_result(
            cookie_id="acc1", chat_id="chat1", item_id="item1", message_id="m1", success=False,
        )
        self.assertEqual(self._send_rows()[0]["status"], "failed")

    def test_claim_send_rejects_stale_state_version(self):
        decision = self._quoted_decision()
        self.assertFalse(self._claim(decision, state_version=decision.state_version + 5))
        self.assertEqual(self._send_rows(), [])

    def test_claim_send_rejects_replaced_rate_book(self):
        decision = self._quoted_decision()
        # 报价表在决策后被替换（哈希不一致）：拒绝发送。
        self.assertFalse(self._claim(decision, book_sha256="deadbeef"))
        self.assertEqual(self._send_rows(), [])


class AgentRouterTests(unittest.TestCase):
    """FastAPI 接口：线路导入、配置读写、状态检测与试算。"""

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers.logistics_agent import create_logistics_agent_router

        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = AgentTestDatabase(os.path.join(self.temp_dir.name, "router.db"))
        self.manager.conn.execute("INSERT INTO cookies (id, value, user_id) VALUES ('acc1', 'v', 1)")
        self.manager.conn.commit()

        app = FastAPI()

        def get_current_user():
            return {"user_id": 1, "username": "admin"}

        app.include_router(create_logistics_agent_router(get_current_user, self.manager))
        self.client = TestClient(app)

    def tearDown(self):
        close_cached_checkpointers()
        self.manager.conn.close()
        self.temp_dir.cleanup()

    def test_route_import_and_listing(self):
        listed = self.client.get("/api/logistics/routes/imports")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["imports"], [])

        imported = self.client.post(
            "/api/logistics/routes/import",
            files={"file": ("快递.csv", EXPRESS_CSV, "text/csv")},
        )
        self.assertEqual(imported.status_code, 200)
        payload = imported.json()["import"]
        self.assertEqual(payload["route_count"], 2)
        self.assertEqual(payload["book_kind"], "express")

        reimported = self.client.post(
            "/api/logistics/routes/import",
            files={"file": ("快递-更新.csv", EXPRESS_CSV, "text/csv")},
        )
        self.assertEqual(reimported.json()["import"]["id"], payload["id"])
        self.assertEqual(len(self.client.get("/api/logistics/routes/imports").json()["imports"]), 1)

        deleted = self.client.delete(f"/api/logistics/routes/imports/{payload['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/logistics/routes/imports").json()["imports"], [])

    def test_invalid_import_returns_400(self):
        failed = self.client.post(
            "/api/logistics/routes/import",
            files={"file": ("无关.csv", b"a,b,c\n1,2,3\n", "text/csv")},
        )
        self.assertEqual(failed.status_code, 400)

    def test_settings_roundtrip(self):
        settings = self.client.get("/api/logistics/agent/settings/acc1")
        self.assertEqual(settings.status_code, 200)
        self.assertFalse(settings.json()["settings"]["enabled"])

        saved = self.client.put(
            "/api/logistics/agent/settings/acc1",
            json={
                "enabled": True, "model_name": "deepseek-v4-pro", "auto_send": True,
                "pricing": {"card_face_value": 100, "platform_face_value": 100, "profit_markup": 5},
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()["settings"]["enabled"])

        forbidden = self.client.put(
            "/api/logistics/agent/settings/unknown-cookie", json={"enabled": True},
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_status_checks_without_books(self):
        status = self.client.get("/api/logistics/agent/status/acc1")
        self.assertEqual(status.status_code, 200)
        body = status.json()
        self.assertFalse(body["ready"])
        keys = {check["key"]: check for check in body["checks"]}
        self.assertFalse(keys["rate_book"]["passed"])
        self.assertTrue(keys["weight_rule"]["passed"])

    def test_status_ready_after_import_and_settings(self):
        self.client.post("/api/logistics/routes/import", files={"file": ("快递.csv", EXPRESS_CSV, "text/csv")})
        self.client.put(
            "/api/logistics/agent/settings/acc1",
            json={"enabled": True, "pricing": {"card_face_value": 0, "platform_face_value": 0}},
        )
        status = self.client.get("/api/logistics/agent/status/acc1")
        body = status.json()
        self.assertTrue(body["ready"], body)
        keys = {check["key"]: check for check in body["checks"]}
        self.assertTrue(keys["test_calculation"]["passed"], keys["test_calculation"])

    def test_agent_test_without_credentials_reports_readable_decision(self):
        """缺模型凭据时试算返回明确决策，而不是静默丢失或抛 500。"""
        self.client.post("/api/logistics/routes/import", files={"file": ("快递.csv", EXPRESS_CSV, "text/csv")})
        response = self.client.post(
            "/api/logistics/agent/test",
            json={"cookie_id": "acc1", "message": "江西寄河北，2公斤"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["handled"])
        self.assertTrue(body["thread_id"])
        # 自动发送未开启：故障提示也只生成草稿（统一发送闸门）。
        self.assertEqual(body["decision"]["action"], "draft")
        self.assertEqual(body["decision"]["reason"], "model_not_configured")
        # 故障决策与快照一致：状态与审计事件里都能看到这次失败。
        self.assertEqual(body["state"]["status"], "failed")
        self.assertTrue(any(event["node"] == "service" for event in body["events"]))


class AgentThreadApiTests(unittest.TestCase):
    """测试会话 API：新建、快照恢复、清空与越权防护。"""

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers.logistics_agent import create_logistics_agent_router

        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = AgentTestDatabase(os.path.join(self.temp_dir.name, "threads.db"))
        self.manager.conn.execute("INSERT INTO cookies (id, value, user_id) VALUES ('acc1', 'v', 1)")
        self.manager.conn.execute("INSERT INTO cookies (id, value, user_id) VALUES ('acc2', 'v', 2)")
        self.manager.conn.commit()

        app = FastAPI()

        self.current_user = {"user_id": 1, "username": "admin"}

        def get_current_user():
            return self.current_user

        app.include_router(create_logistics_agent_router(get_current_user, self.manager))
        self.client = TestClient(app)

    def tearDown(self):
        close_cached_checkpointers()
        self.manager.conn.close()
        self.temp_dir.cleanup()

    def _extract_patch(self, **overrides):
        extracted = ExtractedQuote(
            intent="logistics_quote", sender="江西省赣州市", receiver="河北省石家庄市", weight_kg=2.0,
            length_cm=20.0, width_cm=30.0, height_cm=80.0, **overrides,
        )
        return mock.patch(_EXTRACT_TARGET, return_value=extracted)

    def _create_thread(self, cookie_id: str) -> str:
        created = self.client.post("/api/logistics/agent/threads", json={"cookie_id": cookie_id})
        self.assertEqual(created.status_code, 200, created.text)
        return created.json()["thread_id"]

    def test_thread_lifecycle(self):
        """新建 -> 试算 -> 快照恢复 -> 清空。"""
        imported = self.client.post(
            "/api/logistics/routes/import", files={"file": ("快递.csv", EXPRESS_CSV, "text/csv")},
        )
        self.assertEqual(imported.status_code, 200)
        created = self.client.post("/api/logistics/agent/threads", json={"cookie_id": "acc1"})
        self.assertEqual(created.status_code, 200)
        thread_id = created.json()["thread_id"]
        self.assertTrue(thread_id)

        with self._extract_patch():
            tested = self.client.post("/api/logistics/agent/test", json={
                "cookie_id": "acc1", "message": "江西寄河北，2公斤，20*30*80",
                "thread_id": thread_id, "message_id": "msg-1",
            })
        self.assertEqual(tested.status_code, 200)
        body = tested.json()
        self.assertEqual(body["thread_id"], thread_id)
        self.assertTrue(body["handled"])
        self.assertEqual(body["decision"]["reason"], "quoted")
        self.assertTrue(body["state"])
        self.assertTrue(any(event["node"] == "finalize" for event in body["events"]))
        self.assertEqual(body["decision"]["state_version"], 2)

        snapshot = self.client.get(
            f"/api/logistics/agent/threads/{thread_id}", params={"cookie_id": "acc1"},
        )
        self.assertEqual(snapshot.status_code, 200)
        restored = snapshot.json()
        self.assertTrue(restored["exists"])
        self.assertEqual(restored["status"], "quoted")
        roles = [message["role"] for message in restored["messages"]]
        self.assertEqual(roles.count("buyer"), 1)
        self.assertGreaterEqual(roles.count("agent"), 1)

        cleared = self.client.delete(
            f"/api/logistics/agent/threads/{thread_id}", params={"cookie_id": "acc1"},
        )
        self.assertEqual(cleared.status_code, 200)
        gone = self.client.get(
            f"/api/logistics/agent/threads/{thread_id}", params={"cookie_id": "acc1"},
        )
        self.assertEqual(gone.status_code, 404)

    def test_reserved_thread_prefix_rejected(self):
        """测试入口禁止使用正式消息链路的 thread 命名空间。"""
        response = self.client.post("/api/logistics/agent/test", json={
            "cookie_id": "acc1", "message": "江西寄河北", "thread_id": "prod:acc1:chat1:item1",
        })
        self.assertEqual(response.status_code, 400)
        # 正式命名空间同样不允许通过快照读取/删除接口触碰。
        snapshot = self.client.get(
            "/api/logistics/agent/threads/prod:acc1:chat1:item1", params={"cookie_id": "acc1"},
        )
        self.assertEqual(snapshot.status_code, 400)
        deleted = self.client.delete(
            "/api/logistics/agent/threads/prod:acc1:chat1:item1", params={"cookie_id": "acc1"},
        )
        self.assertEqual(deleted.status_code, 400)

    def test_thread_access_control(self):
        """其他账号名下的会话不可读写。"""
        imported = self.client.post(
            "/api/logistics/routes/import", files={"file": ("快递.csv", EXPRESS_CSV, "text/csv")},
        )
        self.assertEqual(imported.status_code, 200)
        created = self.client.post("/api/logistics/agent/threads", json={"cookie_id": "acc1"})
        thread_id = created.json()["thread_id"]
        with self._extract_patch():
            self.client.post("/api/logistics/agent/test", json={
                "cookie_id": "acc1", "message": "江西寄河北，2公斤，20*30*80", "thread_id": thread_id,
            })
        forbidden = self.client.get(
            f"/api/logistics/agent/threads/{thread_id}", params={"cookie_id": "acc2"},
        )
        self.assertEqual(forbidden.status_code, 403)
        delete_forbidden = self.client.delete(
            f"/api/logistics/agent/threads/{thread_id}", params={"cookie_id": "acc2"},
        )
        self.assertEqual(delete_forbidden.status_code, 403)

    def test_test_api_rejects_foreign_thread_for_post_and_reset(self):
        """自有 cookie 提交他人已有 thread_id：试算与 reset 都拒绝，原状态不被覆盖。"""
        self.current_user = {"user_id": 2, "username": "seller2"}
        foreign_thread = self._create_thread("acc2")
        with self._extract_patch():
            created = self.client.post("/api/logistics/agent/test", json={
                "cookie_id": "acc2", "message": "owner-private-message", "thread_id": foreign_thread,
            })
        self.assertEqual(created.status_code, 200)

        self.current_user = {"user_id": 1, "username": "admin"}
        with self._extract_patch():
            hijacked = self.client.post("/api/logistics/agent/test", json={
                "cookie_id": "acc1", "message": "江西寄河北，2公斤，20*30*80", "thread_id": foreign_thread,
            })
        self.assertEqual(hijacked.status_code, 403)
        hijacked_reset = self.client.post("/api/logistics/agent/test", json={
            "cookie_id": "acc1", "message": "江西寄河北", "thread_id": foreign_thread, "reset": True,
        })
        self.assertEqual(hijacked_reset.status_code, 403)

        # 原会话保持原样：历史消息与归属都没有被试算请求改写。
        self.current_user = {"user_id": 2, "username": "seller2"}
        snapshot = self.client.get(
            f"/api/logistics/agent/threads/{foreign_thread}", params={"cookie_id": "acc2"},
        )
        self.assertEqual(snapshot.status_code, 200)
        contents = [message["content"] for message in snapshot.json()["messages"]]
        self.assertIn("owner-private-message", contents)
        self.assertNotIn("江西寄河北，2公斤，20*30*80", contents)

    def test_test_api_rejects_thread_bound_to_other_chat(self):
        """同一账号下，会话与其他聊天绑定时不允许换聊天串读状态。"""
        thread_id = self._create_thread("acc1")
        with self._extract_patch():
            self.client.post("/api/logistics/agent/test", json={
                "cookie_id": "acc1", "message": "江西寄河北，2公斤，20*30*80", "thread_id": thread_id,
            })
        with self._extract_patch():
            rebound = self.client.post("/api/logistics/agent/test", json={
                "cookie_id": "acc1", "message": "2公斤", "thread_id": thread_id, "chat_id": "chat-other",
            })
        self.assertEqual(rebound.status_code, 403)


class QuoteBookRouteSyncTests(unittest.TestCase):
    """第一步识别报价表与第五步线路库的衔接：上传即同步、删除即清理。"""

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers.logistics_agent import create_logistics_agent_router
        from app.routers.logistics_quote import create_logistics_quote_router

        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = AgentTestDatabase(os.path.join(self.temp_dir.name, "sync.db"))
        self.manager.conn.execute("INSERT INTO cookies (id, value, user_id) VALUES ('acc1', 'v', 1)")
        self.manager.conn.commit()

        app = FastAPI()

        def get_current_user():
            return {"user_id": 1, "username": "admin"}

        app.include_router(create_logistics_quote_router(get_current_user, self.manager))
        app.include_router(create_logistics_agent_router(get_current_user, self.manager))
        self.client = TestClient(app)

    def tearDown(self):
        close_cached_checkpointers()
        self.manager.conn.close()
        self.temp_dir.cleanup()

    def test_create_quote_book_syncs_routes_to_agent(self):
        created = self.client.post(
            "/api/logistics/quote-books",
            files={"file": ("快递.csv", EXPRESS_CSV, "text/csv")},
        )
        self.assertEqual(created.status_code, 200)
        body = created.json()
        self.assertIsNotNone(body["route_import"])
        self.assertEqual(body["route_import"]["route_count"], 2)
        self.assertEqual(body["route_warning"], "")

        imports = self.client.get("/api/logistics/routes/imports").json()["imports"]
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]["sha256"], body["book"]["sha256"])

    def test_reupload_same_file_keeps_single_batch(self):
        for _ in range(2):
            response = self.client.post(
                "/api/logistics/quote-books",
                files={"file": ("快递.csv", EXPRESS_CSV, "text/csv")},
            )
            self.assertEqual(response.status_code, 200)
        imports = self.client.get("/api/logistics/routes/imports").json()["imports"]
        self.assertEqual(len(imports), 1)

    def test_delete_quote_book_cleans_route_import(self):
        created = self.client.post(
            "/api/logistics/quote-books",
            files={"file": ("快递.csv", EXPRESS_CSV, "text/csv")},
        )
        book_id = created.json()["book"]["id"]
        deleted = self.client.delete(f"/api/logistics/quote-books/{book_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/logistics/routes/imports").json()["imports"], [])

    def test_settings_report_has_saved_flag(self):
        fresh = self.client.get("/api/logistics/agent/settings/acc1")
        self.assertFalse(fresh.json()["has_saved_settings"])
        self.client.put("/api/logistics/agent/settings/acc1", json={"enabled": True})
        saved = self.client.get("/api/logistics/agent/settings/acc1")
        self.assertTrue(saved.json()["has_saved_settings"])


if __name__ == "__main__":
    unittest.main()
