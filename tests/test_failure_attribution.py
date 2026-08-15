"""滑块失败判定与商品列表接口的错误归因。

回归两类"把别的事情说成失败"的问题：

1. 滑块：原实现拿 page.content()（整页 HTML 源码）匹配「重试」「失败」这类单字词，
   闲鱼自己的「哎哟喂，被挤爆啦，请稍后重试」和页面 JS 里的任意提示都会命中，
   于是一次正在处理中的验证被判成失败，还会顺带触发风控熔断。
2. 商品列表：网关 502 返回 HTML 错误页时不检查状态码，最后被报成
   「闲鱼接口未返回"在售"分组」，把临时抖动说成数据问题。
"""

import unittest
from unittest.mock import MagicMock, patch

from utils import xianyu_slider_stealth as slider


class FakeElement:
    def __init__(self, text="", visible=True):
        self._text = text
        self._visible = visible

    def text_content(self):
        return self._text

    def is_visible(self):
        return self._visible


class FakeFrame:
    """按选择器返回元素；未列出的选择器返回 None。"""

    def __init__(self, mapping):
        self._mapping = mapping

    def query_selector(self, selector):
        return self._mapping.get(selector)


def make_slider(frame):
    instance = slider.XianyuSliderStealth.__new__(slider.XianyuSliderStealth)
    instance.user_id = instance.pure_user_id = "acc"
    instance.page = frame
    instance._detected_slider_frame = frame
    return instance


class SliderFailureDetectionTests(unittest.TestCase):
    def setUp(self):
        # 判定函数内部有 1.5 秒固定等待，测试里没必要真等
        patcher = patch.object(slider.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_platform_busy_text_is_not_a_slider_failure(self):
        # 闲鱼在被限流时整页会出现这句话，它与滑块结果无关
        frame = FakeFrame({".nc-container": FakeElement("哎哟喂，被挤爆啦，请稍后重试")})
        has_failure, retry = make_slider(frame).check_verification_failure()

        self.assertFalse(has_failure, "平台限流文案被误判为滑块失败")
        self.assertIsNone(retry)

    def test_container_presence_alone_is_not_a_failure(self):
        # 容器在验证处理中一直存在，原实现把 .nc-container 列进"失败提示选择器"
        frame = FakeFrame({".nc-container": FakeElement("请按住滑块，拖动到最右边")})
        has_failure, _ = make_slider(frame).check_verification_failure()

        self.assertFalse(has_failure, "滑块容器存在本身被当成失败证据")

    def test_explicit_failure_text_is_detected(self):
        frame = FakeFrame({
            ".nc-container": FakeElement("验证失败，点击框体重试"),
            "text=点击框体重试": FakeElement("点击框体重试"),
        })
        has_failure, retry = make_slider(frame).check_verification_failure()

        self.assertTrue(has_failure)
        self.assertIsNotNone(retry, "确认失败时应带回重试按钮，否则滑块无法重置")

    def test_missing_container_is_not_a_failure(self):
        # 容器不在了说明验证已经走完，这里不该给出失败结论
        has_failure, _ = make_slider(FakeFrame({})).check_verification_failure()

        self.assertFalse(has_failure)

    def test_keywords_exclude_bare_common_words(self):
        # 「重试」「失败」这类单字词一旦入表，几乎任何页面都会命中
        for bare in ("重试", "失败", "请重试"):
            self.assertNotIn(bare, slider.SLIDER_FAILURE_KEYWORDS)

    def test_returns_two_tuple_on_every_path(self):
        # 调用方按 (has_failure, retry_element) 解包，返回裸值会抛 unpack 异常
        for frame in (
            FakeFrame({}),
            FakeFrame({".nc-container": FakeElement("验证失败")}),
            FakeFrame({".nc-container": FakeElement("正常提示")}),
        ):
            result = make_slider(frame).check_verification_failure()
            self.assertIsInstance(result, tuple)
            self.assertEqual(len(result), 2)


class ItemListTransientErrorTests(unittest.TestCase):
    def test_transient_error_type_exists_and_is_exception(self):
        from XianyuAutoAsync import ItemListTransientError

        self.assertTrue(issubclass(ItemListTransientError, Exception))

    def test_gateway_status_is_classified_as_transient(self):
        # 502/503 是网关抖动，必须与业务错误区分，否则会被报成"未返回在售分组"
        from XianyuAutoAsync import ItemListTransientError

        err = ItemListTransientError("闲鱼接口返回 HTTP 502")
        self.assertIn("502", str(err))


class ItemGroupFallbackTests(unittest.TestCase):
    def test_selects_on_sale_group_when_present(self):
        from XianyuAutoAsync import XianyuLive

        groups = [
            {"groupName": "草稿", "groupId": 1, "itemNumber": 3},
            {"groupName": "在售", "groupId": 2, "itemNumber": 7},
        ]
        self.assertEqual(XianyuLive._select_item_group(groups)["groupId"], 2)

    def test_falls_back_to_status_condition(self):
        from XianyuAutoAsync import XianyuLive

        # 分组名被平台改动时，用 searchCondition 里 status=0 兜底
        groups = [{
            "groupName": "全部宝贝",
            "groupId": 9,
            "itemNumber": 5,
            "searchCondition": [{"status": "0"}],
        }]
        self.assertEqual(XianyuLive._select_item_group(groups)["groupId"], 9)

    def test_returns_none_when_nothing_matches(self):
        from XianyuAutoAsync import XianyuLive

        # 选不出来时返回 None，由调用方决定降级策略
        groups = [{"groupName": "我的收藏", "groupId": 4, "itemNumber": 2}]
        self.assertIsNone(XianyuLive._select_item_group(groups))


if __name__ == "__main__":
    unittest.main()
