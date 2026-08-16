"""AI 回复的两道安全网：思维链不得外发、纯数字还价要计入议价轮数。

回归两个故障，都是买家侧可见的：

1. 思维链泄露。_extract_openai_content 里曾有一句「content 为空就取
   reasoning_content 兜底」。但 reasoning_content 装的是思维链而非答案，
   推理模型（deepseek-r1、qwq 等）把 token 预算花在思考上时 content 就是空的，
   于是原始推理被当成回复发给了买家：

       「我们需要理解这个对话场景。用户是卖家，我们是客服助手……
         最大优惠百分比10%是19.6元，所以最低不能低于176.4元」

   这同时暴露了「对面是机器人」和议价底价。

2. 纯数字还价没被识别成议价意图。detect_intent 只匹配关键词，买家直接回
   「167」「166」会落到 default，get_bargain_count 数不到，max_bargain_rounds
   上限永远不成立 —— 实测 AI 从 196 一路让到 168，议价十几轮而计数只有 3。
"""

import unittest
from unittest.mock import patch

from app.ai_reply_engine import AIReplyEngine, ReasoningBudgetExhausted


class _FakeMessage:
    def __init__(self, content=None, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content


class _FakeChoice:
    def __init__(self, message, finish_reason='stop'):
        self.message = message
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, choice):
        self.choices = [choice]


LEAKED = (
    '我们需要理解这个对话场景。用户是卖家，我们是客服助手，要模拟卖家回复买家。'
    '议价设置：当前议价次数3，最大议价轮数3，最大优惠百分比10%。'
)


class ExtractContentTests(unittest.TestCase):
    def test_reasoning_content_is_never_used_as_reply(self):
        """content 为空时不得拿思维链兜底，应当报错让上层回落。"""
        response = _FakeResponse(_FakeChoice(
            _FakeMessage(content=None, reasoning_content=LEAKED),
            finish_reason='length',
        ))

        with self.assertRaises(RuntimeError) as ctx:
            AIReplyEngine._extract_openai_content(response)

        self.assertNotIn('我们需要理解', str(ctx.exception))

    def test_normal_content_is_returned(self):
        response = _FakeResponse(_FakeChoice(_FakeMessage(content='  170包邮成交～  ')))
        self.assertEqual(AIReplyEngine._extract_openai_content(response), '170包邮成交～')

    def test_content_wins_over_reasoning(self):
        response = _FakeResponse(_FakeChoice(
            _FakeMessage(content='196元包邮', reasoning_content=LEAKED)
        ))
        self.assertEqual(AIReplyEngine._extract_openai_content(response), '196元包邮')

    def test_content_filter_is_reported(self):
        response = _FakeResponse(_FakeChoice(_FakeMessage(), finish_reason='content_filter'))
        with self.assertRaises(RuntimeError) as ctx:
            AIReplyEngine._extract_openai_content(response)
        self.assertIn('内容过滤', str(ctx.exception))


class NormalizeReplyTests(unittest.TestCase):
    def setUp(self):
        self.engine = AIReplyEngine.__new__(AIReplyEngine)

    def test_think_block_is_stripped(self):
        reply = '<think>先算一下底价是176.4</think>170包邮成交～'
        self.assertEqual(self.engine._normalize_reply(reply), '170包邮成交～')

    def test_unclosed_think_block_is_stripped(self):
        """被截断时可能只有开标签，同样不能外发。"""
        reply = '好的亲～<think>他出167，低于底价176.4，我应该'
        self.assertEqual(self.engine._normalize_reply(reply), '好的亲～')

    def test_leaked_reasoning_is_rejected(self):
        self.assertIsNone(self.engine._normalize_reply(LEAKED))

    def test_leaked_reasoning_without_tags_is_rejected(self):
        reply = '我们需要根据对话历史来回复。让我们梳理一下历史：'
        self.assertIsNone(self.engine._normalize_reply(reply))

    def test_normal_reply_survives(self):
        for reply in ('170包邮成交～拍下改价😊',
                      '2XL，适合120-150斤。建议看尺码表哦～',
                      '正品官方买哒，质量放心'):
            self.assertEqual(self.engine._normalize_reply(reply), reply)

    def test_length_is_capped(self):
        self.assertEqual(len(self.engine._normalize_reply('好' * 500)), 300)


class PriceOfferDetectionTests(unittest.TestCase):
    def test_bare_numbers_are_offers(self):
        for text in ('167', '166', ' 165 ', '178吧', '170，', '¥180', '196.5', '1'):
            self.assertTrue(AIReplyEngine._looks_like_price_offer(text), text)

    def test_number_with_currency_unit_is_offer(self):
        for text in ('1块钱', '给你170块', '180元包邮', '最多160元'):
            self.assertTrue(AIReplyEngine._looks_like_price_offer(text), text)

    def test_non_price_numbers_are_not_offers(self):
        """尺码、体重、算式里的数字不能算报价。"""
        for text in ('2xl', '120-150斤', '1+1=？', '穿多大码', '发2件', '43码'):
            self.assertFalse(AIReplyEngine._looks_like_price_offer(text), text)

    def test_empty_is_not_offer(self):
        for text in ('', '   ', None):
            self.assertFalse(AIReplyEngine._looks_like_price_offer(text))


class IntentDetectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = AIReplyEngine.__new__(AIReplyEngine)
        self._patcher = patch(
            'app.ai_reply_engine.db_manager.get_ai_reply_settings',
            return_value={'ai_enabled': 1},
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_bare_counteroffer_counts_as_price(self):
        """这是让议价轮数失效的那条路径。"""
        self.assertEqual(self.engine.detect_intent('167', 'acc'), 'price')

    def test_keyword_still_works(self):
        self.assertEqual(self.engine.detect_intent('最低多少钱可以拿', 'acc'), 'price')

    def test_size_question_is_not_price(self):
        self.assertEqual(self.engine.detect_intent('穿多大码', 'acc'), 'default')

    def test_tech_question(self):
        self.assertEqual(self.engine.detect_intent('怎么用啊', 'acc'), 'tech')


class TokenBudgetTests(unittest.TestCase):
    """默认预算太小时推理模型只会思考、不出正文，表现为「AI 配好了却不回」。"""

    def setUp(self):
        self.engine = AIReplyEngine.__new__(AIReplyEngine)

    def test_default_budget_leaves_room_for_reasoning(self):
        self.assertGreaterEqual(self.engine._resolve_max_tokens({}), 2000)

    def test_invalid_value_falls_back(self):
        self.assertGreaterEqual(self.engine._resolve_max_tokens({'max_tokens': 'abc'}), 2000)

    def test_value_is_clamped(self):
        self.assertEqual(self.engine._resolve_max_tokens({'max_tokens': 1}),
                         AIReplyEngine.MAX_TOKENS_FLOOR)
        self.assertEqual(self.engine._resolve_max_tokens({'max_tokens': 999999}),
                         AIReplyEngine.MAX_TOKENS_CEILING)


class BudgetEscalationTests(unittest.TestCase):
    """思维链吃光预算时，换时间重试没用，必须加大额度再试。"""

    def setUp(self):
        self.engine = AIReplyEngine.__new__(AIReplyEngine)

    def test_budget_is_escalated_until_content_appears(self):
        seen = []

        def fake_call(_self, settings, messages, cookie_id, max_tokens):
            seen.append(max_tokens)
            if max_tokens < 6000:
                raise ReasoningBudgetExhausted('思维链吃光了预算')
            return '170包邮成交～'

        with patch.object(AIReplyEngine, '_dispatch_api_call', fake_call):
            reply = self.engine._generate_with_retry({}, [], 'acc')

        self.assertEqual(reply, '170包邮成交～')
        self.assertEqual(seen, [2000, 6000], f"预算未按预期升级: {seen}")

    def test_gives_up_at_ceiling_instead_of_looping(self):
        def always_exhausted(_self, settings, messages, cookie_id, max_tokens):
            raise ReasoningBudgetExhausted('思维链吃光了预算')

        with patch.object(AIReplyEngine, '_dispatch_api_call', always_exhausted):
            with self.assertRaises(ReasoningBudgetExhausted):
                self.engine._generate_with_retry({'max_tokens': 8000}, [], 'acc')

    def test_escalation_does_not_sleep(self):
        """这不是限流，不该退避 —— 退避只会让买家多等。"""
        def fake_call(_self, settings, messages, cookie_id, max_tokens):
            if max_tokens < 6000:
                raise ReasoningBudgetExhausted('x')
            return 'ok'

        with patch.object(AIReplyEngine, '_dispatch_api_call', fake_call), \
             patch('app.ai_reply_engine.time.sleep') as slept:
            self.engine._generate_with_retry({}, [], 'acc')

        slept.assert_not_called()


if __name__ == '__main__':
    unittest.main()


class PriceFloorTests(unittest.TestCase):
    """底价原先只写在提示词里，模型不照做就没人管 —— 实测 196 元被让到 168，
    而 max_discount_percent=10 算出的底价是 176.4。钱的事不能只靠模型自觉。"""

    ITEM = {'title': '塑形裤', 'price': '196', 'desc': ''}
    SETTINGS = {'max_discount_percent': 10, 'max_discount_amount': 100}

    def test_floor_takes_the_stricter_of_two_limits(self):
        """百分比 10% 只让 19.6 元，固定额度 100 元会让到 96 元，应取更严的。"""
        floor = AIReplyEngine._resolve_price_floor(self.ITEM, self.SETTINGS)
        self.assertAlmostEqual(floor, 176.4, places=2)

    def test_percent_only(self):
        floor = AIReplyEngine._resolve_price_floor(self.ITEM, {'max_discount_percent': 50})
        self.assertAlmostEqual(floor, 98.0, places=2)

    def test_amount_only(self):
        floor = AIReplyEngine._resolve_price_floor(self.ITEM, {'max_discount_amount': 20})
        self.assertAlmostEqual(floor, 176.0, places=2)

    def test_unparsable_price_disables_check(self):
        """商品价格读不出来时不做校验 —— 宁可不管，也不能误拦正常回复。"""
        self.assertIsNone(
            AIReplyEngine._resolve_price_floor({'price': '面议'}, self.SETTINGS))
        self.assertIsNone(
            AIReplyEngine._resolve_price_floor({'price': '¥0'}, self.SETTINGS))

    def test_no_limits_disables_check(self):
        self.assertIsNone(AIReplyEngine._resolve_price_floor(self.ITEM, {}))

    def test_price_with_currency_prefix_is_parsed(self):
        floor = AIReplyEngine._resolve_price_floor({'price': '¥196.00'}, self.SETTINGS)
        self.assertAlmostEqual(floor, 176.4, places=2)

    def test_lowest_price_in_reply(self):
        self.assertEqual(AIReplyEngine._lowest_price_in('好的亲，168包邮成交～'), 168.0)
        self.assertEqual(
            AIReplyEngine._lowest_price_in('原价196，现在给你170'), 170.0)

    def test_single_digits_are_not_prices(self):
        """「1元不行哦」里的 1 是举例，不能当成报价。"""
        self.assertIsNone(AIReplyEngine._lowest_price_in('亲，1元不行哦～'))

    def test_reply_without_number_is_ignored(self):
        self.assertIsNone(AIReplyEngine._lowest_price_in('正品包邮，质量放心～'))

    def test_below_floor_is_detected(self):
        floor = AIReplyEngine._resolve_price_floor(self.ITEM, self.SETTINGS)
        offered = AIReplyEngine._lowest_price_in('好的亲，168包邮成交～拍下改价😊')
        self.assertLess(offered, floor)

    def test_at_or_above_floor_passes(self):
        floor = AIReplyEngine._resolve_price_floor(self.ITEM, self.SETTINGS)
        for reply in ('178包邮成交～', '180元包邮，最低啦', '196元包邮～'):
            self.assertGreaterEqual(AIReplyEngine._lowest_price_in(reply), floor, reply)
