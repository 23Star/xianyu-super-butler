"""风控状态的呈现是否反映"当前"而非"历史"。

回归的是这个故障：账号滑块过完、Token 已拿到、接口恢复 200，界面却仍挂着
「闲鱼要求完成人机验证，账号暂时拿不到令牌」。原因是判定只看风控日志——
那是历史记录，而且一条「滑块验证成功」的日志同样含"滑块"二字。
"""

import unittest

from app.reply_server import classify_verification_event


class ClassifyVerificationEventTests(unittest.TestCase):
    def test_pending_slider_is_reported(self):
        detail = 'slider_captcha 检测到需要滑块验证，触发场景: Token刷新, URL: https://x/punish?action=captcha'
        kind, message = classify_verification_event(detail)

        self.assertEqual(kind, 'slider')
        self.assertTrue(message)

    def test_succeeded_slider_is_not_reported(self):
        # 处理成功的日志也带"滑块"，只按关键词匹配会让恢复的账号一直显示需要验证
        detail = 'slider_captcha 检测到需要滑块验证 滑块验证成功（浏览器自动），耗时: 12.3秒'
        kind, message = classify_verification_event(detail)

        self.assertEqual(kind, 'none')
        self.assertEqual(message, '')

    def test_succeeded_but_still_blocked_reports_risk_control(self):
        # 验证成功但本地熔断还没到期，仍要如实告知处于冷却
        detail = '滑块验证成功'
        kind, message = classify_verification_event(detail, blocked=True, reason='命中限流')

        self.assertEqual(kind, 'risk_control')
        self.assertEqual(message, '命中限流')

    def test_face_verification_is_reported(self):
        kind, _ = classify_verification_event('iframeRedirect 需要人脸验证')
        self.assertEqual(kind, 'face')

    def test_empty_detail_is_none(self):
        self.assertEqual(classify_verification_event('')[0], 'none')

    def test_blocked_without_detail_is_risk_control(self):
        kind, message = classify_verification_event('', blocked=True, reason='被挤爆')
        self.assertEqual(kind, 'risk_control')
        self.assertEqual(message, '被挤爆')


if __name__ == '__main__':
    unittest.main()
