"""自动发货“是否点闲鱼发货”的判定策略。

需求：买家付款后，系统只发送卡密、不自动在闲鱼点“发货”；
“发货”留给卖家后续在订单页手动操作。

因此新增全局开关 auto_confirm_ship_enabled（默认 false）：

- false：付款自动发货时只发卡密，不调用平台发货接口，订单保持 pending_ship；
- true ：恢复原有行为（仍受账号级 auto_confirm 开关与发货保护规则的 card_only 约束）。

最终判定：global_enabled AND account_enabled AND NOT card_only_delivery。
"""

from __future__ import annotations

# 系统设置表里的全局开关 key
AUTO_CONFIRM_SHIP_SETTING_KEY = "auto_confirm_ship_enabled"

# 开关值中视为“开启”的字符串
_TRUE_VALUES = {"1", "true", "yes", "on"}


def parse_setting_bool(value, default: bool = False) -> bool:
    """把 system_settings 里的字符串开关解析成布尔。

    兼容 'true'/'1'/'yes'/'on' 等写法；None 或空串回退到 default，
    其余非真值一律视为 False，避免把 'false' 当成真值。
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE_VALUES


def should_auto_confirm_platform(
    global_auto_ship_enabled,
    account_auto_confirm_enabled,
    card_only_delivery: bool = False,
) -> bool:
    """判断本次自动发货发送卡密后，是否继续在闲鱼平台点“发货”。

    三个条件同时满足才确认发货：
    1. 全局开关 auto_confirm_ship_enabled 开启；
    2. 账号级开关 auto_confirm 开启；
    3. 发货保护规则没有把本次降级为 card_only（只发卡不点发货）。
    """
    return (
        parse_setting_bool(global_auto_ship_enabled, default=False)
        and bool(account_auto_confirm_enabled)
        and not bool(card_only_delivery)
    )
