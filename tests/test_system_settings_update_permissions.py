# -*- coding: utf-8 -*-
"""系统设置更新端点的写权限回归（issue #98）。

回归的是这个故障：买家互动页的模板与兜底间隔经 PUT /system-settings/{key}
保存，多用户权限体系上线后该端点被整体 require_admin，普通用户点
「保存设置」直接 403。而同页的 GET /system-settings 早已为普通用户放行了
业务白名单（买家互动模板等），读写不一致。

期望：普通用户可写白名单内的业务键，写系统级键仍被拒；管理员不受限。
"""

import unittest
from unittest import mock

from fastapi import HTTPException

from app.reply_server import (
    SystemSettingIn,
    USER_VISIBLE_SETTINGS_KEYS,
    update_system_setting,
)

ADMIN = {"user_id": 1, "username": "admin"}
USER = {"user_id": 2, "username": "buyer_a"}


class SystemSettingUpdatePermissionTests(unittest.TestCase):
    def setUp(self):
        self.db = mock.MagicMock()
        self.db.set_system_setting = mock.Mock(return_value=True)
        patcher = mock.patch("app.db_manager.db_manager", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _save(self, key, value, user):
        return update_system_setting(key, SystemSettingIn(value=value), user)

    def test_user_can_save_buyer_interaction_settings(self):
        """issue #98 场景：普通用户保存买家互动模板与兜底间隔，不应 403。"""
        for key in ('auto_rate_template', 'auto_thanks_template',
                    'buyer_interaction_interval'):
            resp = self._save(key, '7200', USER)
            self.assertEqual(resp['msg'], 'system setting updated')
        self.assertEqual(self.db.set_system_setting.call_count, 3)

    def test_user_rejected_on_system_level_keys(self):
        """SMTP、注册开关等系统级键普通用户仍不可写。"""
        with self.assertRaises(HTTPException) as ctx:
            self._save('smtp_server', 'smtp.qq.com', USER)
        self.assertEqual(ctx.exception.status_code, 403)
        self.db.set_system_setting.assert_not_called()

    def test_password_hash_rejected_for_everyone(self):
        """密码哈希对所有人禁改，普通用户也拿不到 403 之外的绕路口子。"""
        with self.assertRaises(HTTPException) as ctx:
            self._save('admin_password_hash', 'x', USER)
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx:
            self._save('admin_password_hash', 'x', ADMIN)
        self.assertEqual(ctx.exception.status_code, 400)
        self.db.set_system_setting.assert_not_called()

    def test_admin_can_save_any_key(self):
        resp = self._save('smtp_server', 'smtp.qq.com', ADMIN)
        self.assertEqual(resp['msg'], 'system setting updated')

    def test_whitelist_matches_buyer_interaction_page_keys(self):
        """买家互动页提交的三个键必须全部在白名单里，防止以后改漏。"""
        self.assertTrue({
            'auto_rate_template', 'auto_thanks_template',
            'buyer_interaction_interval',
        } <= USER_VISIBLE_SETTINGS_KEYS)


if __name__ == "__main__":
    unittest.main()
