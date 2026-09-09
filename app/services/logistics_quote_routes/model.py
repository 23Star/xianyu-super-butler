"""报价行 -> Workflow 价格模型转换。

解析器输出的每一行报价必须转换成 `workflows/logistics-quote.mjs` 认识的
`price_table` 结构；转换过程只做形态映射，不做任何金额推导，费率数值
全部来自解析结果本身。
"""

from __future__ import annotations

import math
import re
from typing import Any

# 表头标签里的显式公斤数：如"首重(1KG)价格"、"续重(5KG)价格"。
_FIRST_WEIGHT_LABEL_RE = re.compile(r"首重[(（](\d+(?:\.\d+)?)\s*KG", re.IGNORECASE)
_CONTINUED_UNIT_LABEL_RE = re.compile(r"续重[(（](\d+(?:\.\d+)?)\s*KG", re.IGNORECASE)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _labelled_weights(row: dict[str, Any]) -> tuple[float | None, float | None]:
    """从原始表头键里取"首重(NKG)"/"续重(NKG)"的显式公斤数。"""
    first_weight = continued_unit = None
    for header in row.get("raw", {}):
        text = str(header or "")
        if first_weight is None:
            match = _FIRST_WEIGHT_LABEL_RE.search(text)
            if match:
                first_weight = float(match.group(1))
        if continued_unit is None:
            match = _CONTINUED_UNIT_LABEL_RE.search(text)
            if match:
                continued_unit = float(match.group(1))
    return first_weight, continued_unit


def _tiers_map(fixed_tiers: list[dict[str, Any]] | None) -> dict[str, float] | None:
    """固定重量档 -> Workflow `tiers`（键为正整数公斤）。"""
    if not fixed_tiers:
        return None
    tiers: dict[str, float] = {}
    for tier in fixed_tiers:
        up_to = _finite(tier.get("up_to_kg"))
        price = _finite(tier.get("price"))
        if up_to is None or price is None or up_to <= 0 or up_to != int(up_to):
            return None
        tiers[str(int(up_to))] = price
    return tiers or None


def build_price_model(row: dict[str, Any]) -> dict[str, Any] | None:
    """把单个解析行转成 Workflow `price_table`；形态不完整时返回 None。

    溢出段（固定重量档之外的 >3KG / >5KG 区间）采用表头标签口径：
    "首重(NKG)价格"覆盖包裹前 N 公斤，续重价按每公斤向上取整追加，
    精确命中固定档时优先用档位价。
    """
    rule_type = row.get("rule_type")
    first_price = _finite(row.get("first_price"))
    continued_price = _finite(row.get("continued_price"))
    label_first, label_unit = _labelled_weights(row)

    if rule_type in ("first_additional", "minimum_then_per_kg"):
        if first_price is None or continued_price is None:
            return None
        first_weight = _finite(row.get("first_weight_kg")) or label_first or 1.0
        continued_unit = label_unit or _finite(row.get("continued_unit_kg")) or 1.0
        if first_weight <= 0 or continued_unit <= 0:
            return None
        return {
            "first_weight": first_weight,
            "first_weight_price": first_price,
            "continued_unit": continued_unit,
            "continued_weight_price": continued_price,
        }

    if rule_type == "fixed_tiers_overflow":
        tiers = _tiers_map(row.get("fixed_tiers"))
        if not tiers or first_price is None or continued_price is None:
            return None
        return {
            "tiers": tiers,
            "first_weight": label_first or _finite(row.get("first_weight_kg")) or 1.0,
            "first_weight_price": first_price,
            "continued_unit": label_unit or 1.0,
            "continued_weight_price": continued_price,
        }

    if rule_type == "fixed_tiers":
        tiers = _tiers_map(row.get("fixed_tiers"))
        return {"tiers": tiers} if tiers else None

    if rule_type == "banded_additional":
        # 分段续重：计费重不高于首重只收首重价；续重部分按区间取单价。
        if first_price is None:
            return None
        first_weight = _finite(row.get("first_weight_kg")) or label_first
        if first_weight is None or first_weight <= 0:
            return None
        tiers: dict[str, float] = {}
        overflow: float | None = None
        for tier in row.get("continued_tiers") or []:
            price = _finite(tier.get("price_per_kg"))
            if price is None:
                return None
            max_inclusive = tier.get("max_inclusive_kg")
            if max_inclusive is None:
                overflow = price
            else:
                bounded = _finite(max_inclusive)
                if bounded is None or bounded <= 0 or bounded != int(bounded):
                    return None
                tiers[str(int(bounded))] = price
        if not tiers or overflow is None:
            return None
        return {
            "first_weight": first_weight,
            "first_weight_price": first_price,
            "continued_unit": 1.0,
            "continued_tiers": tiers,
            "overflow_continued_price": overflow,
        }

    return None
