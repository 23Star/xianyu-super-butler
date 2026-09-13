"""计价规则与表类型推断、必填字段校验。"""

from __future__ import annotations

from typing import Any

from .headers import REQUIRED_PRICE_FIELDS


def _infer_rule_type(
    values: dict[str, Any],
    specs: dict[int, dict[str, Any]],
    mapping: dict[int, str],
) -> str | None:
    """按报价表结构推断计价规则，不从单元格金额猜测业务语义。"""
    fixed_tiers = values.get("fixed_tiers") or []
    continued_tiers = values.get("continued_tiers") or []
    has_first_price = values.get("first_price") is not None
    has_continued_price = values.get("continued_price") is not None

    if fixed_tiers:
        return "fixed_tiers_overflow" if has_continued_price else "fixed_tiers"
    if continued_tiers:
        return "banded_additional"
    if has_first_price and has_continued_price:
        has_minimum_price = any(
            spec.get("semantics") == "最低价"
            and (spec.get("field") or mapping.get(column)) == "first_price"
            for column, spec in specs.items()
        )
        return "minimum_then_per_kg" if has_minimum_price else "first_additional"
    return None


def _infer_book_kind(values: dict[str, Any]) -> str | None:
    """沿用报价表识别约定：首档重量至少 30KG 时归为大件物流。"""
    first_weight = values.get("first_weight_kg")
    if first_weight is None:
        fixed_tiers = values.get("fixed_tiers") or []
        first_weight = min((tier["up_to_kg"] for tier in fixed_tiers), default=None)
    if first_weight is None:
        return None
    return "logistics" if first_weight >= 30 else "express"


def _missing_price_fields(values: dict[str, Any], rule_type: str | None) -> list[str]:
    required_by_rule = {
        "first_additional": ("first_price", "continued_price"),
        "minimum_then_per_kg": ("first_price", "continued_price"),
        "banded_additional": ("first_price", "continued_tiers"),
        "fixed_tiers": ("fixed_tiers",),
        "fixed_tiers_overflow": ("fixed_tiers", "continued_price"),
    }
    required = required_by_rule.get(rule_type, REQUIRED_PRICE_FIELDS)
    missing: list[str] = []
    for field in required:
        value = values.get(field)
        if value is None or (field.endswith("tiers") and not value):
            missing.append(field)
    return missing
