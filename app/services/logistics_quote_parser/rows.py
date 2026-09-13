"""单行报价数据构建：把一行单元格映射为结构化报价结果。"""

from __future__ import annotations

from typing import Any

from .headers import _CORE_FIELDS, FIELD_ALIASES
from .rules import _infer_book_kind, _infer_rule_type, _missing_price_fields
from .values import (
    _cell_text,
    _label,
    _parse_amount,
    _parse_eta,
    _parse_weight,
    _region_text,
)


def _build_row_result(
    row_id: str,
    sheet: str,
    source_row: int,
    headers: dict[int, str],
    mapping: dict[int, str],
    row: list[Any],
    column_specs: dict[int, dict[str, Any]] | None = None,
    sheet_carrier: str | None = None,
) -> dict[str, Any]:
    specs = column_specs or {}
    values: dict[str, Any] = {field: None for field in FIELD_ALIASES}
    values["continued_tiers"] = None
    values["fixed_tiers"] = None
    carrier_source: str | None = None
    issues: list[str] = []

    for column, field in mapping.items():
        spec = specs.get(column, {})
        cell = row[column] if column < len(row) else None
        text = _cell_text(cell)
        if field == "continued_tier":
            if not text:
                continue
            number, error = _parse_amount(cell)
            if error:
                issues.append(f"阶梯续重价：{error}（原文：{text}）")
                continue
            lower, upper = spec["tier"]
            tier: dict[str, Any] = {"price_per_kg": number}
            if lower is not None:
                tier["min_exclusive_kg"] = lower
            if upper is not None:
                tier["max_inclusive_kg"] = upper
            tiers = list(values["continued_tiers"] or [])
            tiers.append(tier)
            values["continued_tiers"] = tiers
            continue
        if field == "fixed_tier":
            if not text:
                continue
            number, error = _parse_amount(cell)
            if error:
                issues.append(f"固定重量档价格：{error}（原文：{text}）")
                continue
            tiers = list(values["fixed_tiers"] or [])
            tiers.append({"up_to_kg": spec["up_to_kg"], "price": number})
            values["fixed_tiers"] = tiers
            continue
        if not text:
            continue
        if field in ("first_price", "continued_price"):
            number, error = _parse_amount(cell)
            if error:
                issues.append(f"{_label(field)}：{error}（原文：{text}）")
            else:
                values[field] = number
        elif field in ("first_weight_kg", "continued_unit_kg"):
            number, error = _parse_weight(cell)
            if error:
                issues.append(f"{_label(field)}：{error}（原文：{text}）")
            else:
                values[field] = number
        elif field == "eta":
            values[field] = _parse_eta(text)
        else:
            values[field] = text
        if field == "carrier" and values["carrier"] is not None:
            carrier_source = headers.get(column)
        if field == "origin_province" and spec.get("candidate"):
            issues.append("「发件省」来自异常表头的候选映射，需人工确认")
        if field == "first_price" and spec.get("semantics") == "最低价":
            issues.append(f"「{spec.get('header') or text}」为最低价语义，适用规则需确认")

    for column, spec in specs.items():
        implied = spec.get("implied_weight")
        if implied is None:
            continue
        field = spec.get("field") or mapping.get(column)
        if field == "first_price" and values["first_weight_kg"] is None:
            values["first_weight_kg"] = implied
            issues.append(f"「{_label('first_weight_kg')}」由表头推导（{implied:g}KG），语义需确认")
        elif field == "continued_price" and values["continued_unit_kg"] is None:
            values["continued_unit_kg"] = implied

    if values["carrier"] is None and sheet_carrier:
        values["carrier"] = sheet_carrier
        carrier_source = sheet

    if values["continued_tiers"]:
        values["continued_tiers"].sort(key=lambda item: item.get("min_exclusive_kg", 0))
        issues.append(f"续重为阶梯计价（{len(values['continued_tiers'])} 档），计费规则需确认")

    if values["fixed_tiers"]:
        values["fixed_tiers"].sort(key=lambda item: item["up_to_kg"])
        fixed_weights = [tier["up_to_kg"] for tier in values["fixed_tiers"]]
        if len(fixed_weights) != len(set(fixed_weights)):
            issues.append("固定重量档存在重复上限，需人工确认")

    if values["route"] is None:
        origin = _region_text(values["origin_province"], values["origin_city"], values["origin"])
        destination = _region_text(
            values["destination_province"], values["destination_city"], values["destination"]
        )
        if origin and destination:
            values["route"] = f"{origin}→{destination}"

    raw = {headers[column]: _cell_text(row[column] if column < len(row) else None) for column in sorted(mapping)}

    rule_type = _infer_rule_type(values, specs, mapping)
    if rule_type is None:
        issues.append("未能识别计价规则，需人工确认")
    missing_required = [field for field in ("carrier",) + tuple(_missing_price_fields(values, rule_type)) if values.get(field) is None or (field.endswith("tiers") and not values.get(field))]
    if missing_required:
        issues.extend(f"缺少{_label(field)}" for field in missing_required)

    extracted = sum(1 for field in _CORE_FIELDS if values[field] is not None)
    confidence = round(extracted * 100 / len(_CORE_FIELDS))
    book_kind = _infer_book_kind(values)

    state = "rejected" if any("无法解析" in issue for issue in issues) else ("review" if issues else "valid")
    return {
        "id": row_id,
        "sheet": sheet,
        "source_row": source_row,
        **values,
        "carrier_source": carrier_source,
        "rule_type": rule_type,
        "book_kind": book_kind,
        "quote": None,
        "confidence": confidence,
        "review_state": state,
        "issues": issues,
        "raw": raw,
    }
