"""测试“付款后只发卡密、不点发货”的全局开关策略。"""
import unittest

from app.services.delivery_ship_policy import (
    AUTO_CONFIRM_SHIP_SETTING_KEY,
    parse_setting_bool,
    should_auto_confirm_platform,
)


class ParseSettingBoolTests(unittest.TestCase):
    def test_none_uses_default(self):
        self.assertFalse(parse_setting_bool(None, default=False))
        self.assertTrue(parse_setting_bool(None, default=True))

    def test_false_strings_are_false(self):
        for raw in ("false", "False", "0", "no", "OFF", "  "):
            self.assertFalse(parse_setting_bool(raw, default=True), raw)

    def test_true_strings_are_true(self):
        for raw in ("true", "True", "1", "yes", "on"):
            self.assertTrue(parse_setting_bool(raw, default=False), raw)

    def test_boolean_passthrough(self):
        self.assertTrue(parse_setting_bool(True, default=False))
        self.assertFalse(parse_setting_bool(False, default=True))


class ShouldAutoConfirmPlatformTests(unittest.TestCase):
    def test_global_off_means_card_only_even_if_account_on(self):
        self.assertFalse(
            should_auto_confirm_platform(
                global_auto_ship_enabled=False,
                account_auto_confirm_enabled=True,
            )
        )

    def test_global_on_and_account_on_confirm(self):
        self.assertTrue(
            should_auto_confirm_platform(
                global_auto_ship_enabled=True,
                account_auto_confirm_enabled=True,
            )
        )

    def test_account_off_blocks_global_on(self):
        self.assertFalse(
            should_auto_confirm_platform(
                global_auto_ship_enabled=True,
                account_auto_confirm_enabled=False,
            )
        )

    def test_card_only_blocks_even_when_both_on(self):
        self.assertFalse(
            should_auto_confirm_platform(
                global_auto_ship_enabled=True,
                account_auto_confirm_enabled=True,
                card_only_delivery=True,
            )
        )

    def test_missing_global_defaults_to_off(self):
        self.assertFalse(
            should_auto_confirm_platform(
                global_auto_ship_enabled=None,
                account_auto_confirm_enabled=True,
            )
        )

    def test_setting_key_is_stable(self):
        self.assertEqual(AUTO_CONFIRM_SHIP_SETTING_KEY, "auto_confirm_ship_enabled")


if __name__ == "__main__":
    unittest.main()
