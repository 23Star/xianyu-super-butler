import os
import tempfile
import unittest

from app.db_manager import DBManager
from utils.xianyu_seller_api import (
    SellerApiError,
    XianyuSellerAPI,
    classify_sku_discovery_error,
    find_sku_rows,
    normalize_sku_rows,
)


class ClassifySkuDiscoveryErrorTests(unittest.TestCase):
    def test_unauthorized_is_classified(self):
        exc = SellerApiError("mtop.test", ["FAIL_BIZ_IDLE_USER_UNAUTHORIZED::无权限访问"])

        self.assertEqual(classify_sku_discovery_error(exc), "unauthorized")

    def test_risk_control_is_classified(self):
        exc = SellerApiError("mtop.test", ["FAIL_SYS_USER_VALIDATE::哎哟喂,被挤爆啦"])

        self.assertEqual(classify_sku_discovery_error(exc), "risk_control")

    def test_other_errors_are_generic(self):
        self.assertEqual(classify_sku_discovery_error(RuntimeError("boom")), "error")


class NormalizeSkuRowsTests(unittest.TestCase):
    def test_property_list_is_joined_and_numeric_ids_become_strings(self):
        rows = normalize_sku_rows([
            {
                "skuId": 6283316031481,
                "propertyList": [
                    {"propertyText": "颜色", "actualValueText": "蓝色"},
                    {"propertyText": "尺码", "valueText": "XL"},
                ],
            },
        ])

        self.assertEqual(
            rows,
            [{"platform_sku_id": "6283316031481", "name": "蓝色 / XL"}],
        )

    def test_rows_without_identity_are_filtered_and_duplicates_dropped(self):
        rows = normalize_sku_rows([
            {"skuId": "1", "propertyList": [{"actualValueText": "A"}]},
            {"skuId": 1, "propertyList": [{"actualValueText": "A"}]},
            {"inventoryId": "2", "name": "库存规格"},
            {"propertyList": [{"actualValueText": "无 ID"}]},
            {"skuId": "3"},
        ])

        self.assertEqual(
            rows,
            [
                {"platform_sku_id": "1", "name": "A"},
                {"platform_sku_id": "2", "name": "库存规格"},
            ],
        )

    def test_find_sku_rows_scans_nested_payload(self):
        payload = {
            "data": {
                "itemDO": {"unrelated": True},
                "deeper": {"skus": [
                    {"inventoryId": "9", "propertyList": [{"valueText": "默认"}]},
                ]},
            },
        }

        found = find_sku_rows(payload)

        self.assertEqual(found, [{"inventoryId": "9", "propertyList": [{"valueText": "默认"}]}])


class ItemSkuDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_seller_search_normalizes_sku_list(self):
        api = XianyuSellerAPI("account", "cookie")

        async def fake_call(api_name, payload, **kwargs):
            return {
                "ret": ["SUCCESS::调用成功"],
                "data": {"data": {"itemSearchResponseList": [{
                    "itemId": "1001",
                    "idleItemSkuList": [{
                        "skuId": 5208283398672,
                        "quantity": 994,
                        "propertyList": [{"actualValueText": "蓝色 / XL"}],
                    }],
                }]}},
            }

        api._call = fake_call
        rows = await api.search_item_skus("1001")

        self.assertEqual(rows, [{"platform_sku_id": "5208283398672", "name": "蓝色 / XL"}])

    async def test_buyer_detail_is_used_as_fallback(self):
        api = XianyuSellerAPI("account", "cookie")

        async def fake_call_buyer(api_name, payload, **kwargs):
            self.assertEqual(api_name, "mtop.taobao.idle.pc.detail")
            self.assertEqual(payload, {"itemId": "1001"})
            return {
                "ret": ["SUCCESS::调用成功"],
                "data": {"itemDO": {"skuList": [
                    {
                        "skuId": 6283316031481,
                        "quantity": 1000,
                        "priceInCent": 39,
                        "propertyList": [{"actualValueText": "首单特惠"}],
                    },
                    {
                        "skuId": 6283316031482,
                        "quantity": 1000,
                        "propertyList": [{"valueText": "补差价专用"}],
                    },
                ]}},
            }

        api._call_buyer = fake_call_buyer
        rows = await api.search_item_skus_buyer("1001")

        self.assertEqual(
            rows,
            [
                {"platform_sku_id": "6283316031481", "name": "首单特惠"},
                {"platform_sku_id": "6283316031482", "name": "补差价专用"},
            ],
        )


class RecordDeliverySkuOptionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = DBManager(os.path.join(self.temp_dir.name, "sku.db"))

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def test_explicit_sku_key_supports_single_option(self):
        self.manager.record_delivery_sku_option(
            "seller-1", "item-1", "默认规格", "", source="discovery", sku_key="single:item-1",
        )

        options = self.manager.list_delivery_sku_options("seller-1", "item-1")

        self.assertEqual(options[0]["key"], "single:item-1")
        self.assertEqual(options[0]["name"], "默认规格")

    def test_blank_platform_sku_id_falls_back_to_default_name(self):
        self.manager.record_delivery_sku_option("seller-1", "item-1", "", "")

        options = self.manager.list_delivery_sku_options("seller-1", "item-1")

        self.assertEqual(options[0]["key"], "single:item-1")
        self.assertEqual(options[0]["name"], "默认规格")


if __name__ == "__main__":
    unittest.main()
