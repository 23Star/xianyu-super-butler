"""统一计算物流券原价、店家加价和优惠券抵扣。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CustomerQuote:
    coupon_original: float
    markup: float
    coupon_discount: float
    payable: float


def calculate_customer_quote(
    coupon_original: float,
    *,
    profit_markup: float = 0,
    continued_markup: float = 0,
    chargeable_weight_kg: float | None = None,
    continued_base_weight_kg: float = 1,
    coupon_discount: float = 0,
) -> CustomerQuote:
    """券原价 + 自定义加价 - 优惠券抵扣，结果不低于零。"""
    original = max(0.0, float(coupon_original or 0))
    excess = max(0.0, float(chargeable_weight_kg or 0) - continued_base_weight_kg)
    markup = max(0.0, float(profit_markup or 0)) + max(0.0, float(continued_markup or 0)) * excess
    discount = max(0.0, float(coupon_discount or 0))
    return CustomerQuote(original, markup, discount, max(0.0, original + markup - discount))
