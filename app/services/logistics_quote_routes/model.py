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


def _tiers_map(fixed_tiers: list[dict[str, Any]] | None) -> tuple[dict[str, float] | None, bool]:
    """固定重量档 -> Workflow `tiers`（键为正整数公斤）与是否"以内"语义。

    只有整行档位都带"以内/以下"表头时才按不高于档位重量计价；混用精确
    档位时返回 up_to=False，由 Workflow 按精确命中处理。
    """
    if not fixed_tiers:
        return None, False
    tiers: dict[str, float] = {}
    up_to = True
    for tier in fixed_tiers:
        up_to_kg = _finite(tier.get("up_to_kg"))
        price = _finite(tier.get("price"))
        if up_to_kg is None or price is None or up_to_kg <= 0 or up_to_kg != int(up_to_kg):
            return None, False
        tiers[str(int(up_to_kg))] = price
        if not tier.get("up_to"):
            up_to = False
    return (tiers or None), (up_to and bool(tiers))


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
        tiers, up_to = _tiers_map(row.get("fixed_tiers"))
        if not tiers or continued_price is None:
            return None
        if first_price is None:
            # 没有显式首重列（如"1KG价格+3KG价格+续重(1KG)价格"）时，用最大
            # 固定档作为溢出段的首重与首重价：超过最大档的包裹从该档价起按
            # 续重单位累加，避免整行因缺首重价被丢弃。
            base_key = max(tiers, key=int)
            first_weight = float(base_key)
            first_price = tiers[base_key]
        else:
            first_weight = label_first or _finite(row.get("first_weight_kg")) or 1.0
        if first_weight <= 0:
            return None
        model = {
            "tiers": tiers,
            "first_weight": first_weight,
            "first_weight_price": first_price,
            "continued_unit": label_unit or _finite(row.get("continued_unit_kg")) or 1.0,
            "continued_weight_price": continued_price,
        }
        if up_to:
            model["tiers_up_to"] = True
        return model

    if rule_type == "fixed_tiers":
        tiers, up_to = _tiers_map(row.get("fixed_tiers"))
        if not tiers:
            return None
        model = {"tiers": tiers}
        if up_to:
            model["tiers_up_to"] = True
        return model

    if rule_type == "banded_additional":
        # 分段续重：计费重不高于首重只收首重价；续重部分按区间取单价。
        # 分档区间默认针对续重部分，表头写"计费重量/总重量"时针对计费总重。
        if first_price is None:
            return None
        first_weight = _finite(row.get("first_weight_kg")) or label_first
        if first_weight is None or first_weight <= 0:
            return None
        bases = {tier.get("basis") or "continued" for tier in row.get("continued_tiers") or []}
        if len(bases) > 1:
            return None
        basis = next(iter(bases), "continued")
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
        model = {
            "first_weight": first_weight,
            "first_weight_price": first_price,
            "continued_unit": 1.0,
            "continued_tiers": tiers,
            "overflow_continued_price": overflow,
        }
        if basis == "total":
            model["continued_tiers_basis"] = "total"
        return model

    return None
