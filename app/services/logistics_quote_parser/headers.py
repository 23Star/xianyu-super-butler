"""表头识别：字段别名词典、复合表头模式与表头行检测。"""

from __future__ import annotations

import re
from typing import Any

from .constants import HEADER_SCAN_ROWS
from .values import _cell_text, _normalize_text

# 字段 -> 别名列表；匹配时"最长别名优先"，多个字段等长命中视为歧义，不强行归类。
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "seller": ("店家名称", "店铺名称", "卖家名称", "店家", "店铺", "卖家"),
    "channel": ("渠道名称", "店铺类型", "渠道", "平台"),
    "carrier": ("承运商名称", "承运公司", "快递公司", "物流公司", "服务商", "承运商", "快递", "物流"),
    "route": ("线路/区域", "发货地-目的地", "运输线路", "目的区域", "区域", "航线", "线路", "路线"),
    "eta": ("预计时效", "运输时效", "到达时效", "时效"),
    "origin_province": ("发件省", "发货省", "始发省", "出发省"),
    "origin_city": ("发件市", "发货市", "始发市", "出发市"),
    "origin": (
        "起始地",
        "起运地",
        "始发地",
        "发件地",
        "发货地",
        "寄件地",
        "出发地",
        "起点",
        "发件",
        "始发",
        "寄件",
        "出发",
        "发货",
        "起运",
    ),
    "destination_province": ("收件省", "到达省", "目的省"),
    "destination_city": ("收件市", "到达市", "目的市"),
    "destination": (
        "目的地",
        "收件地",
        "收货地",
        "到货地",
        "送达地",
        "到达地",
        "终点",
        "收件",
        "目的",
        "到达",
        "收货",
        "到货",
        "送达",
    ),
    "first_weight_kg": ("首重重量", "首重kg", "首重"),
    "first_price": ("首重价格", "首重费用", "首重价", "首重费"),
    "continued_unit_kg": ("续重单位", "续重重量", "续重kg", "续重"),
    "continued_price": ("续重价格", "续重费用", "续重价", "续重费"),
    "note": ("备注说明", "备注", "说明"),
}

# 表头模式规则：优先于别名词典，区分"首重(30KG)价格"这类复合表头中的价格列与重量列。
_HEADER_FIELD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"首重[^。]*?(价格|费用|价|费)", re.IGNORECASE), "first_price"),
    (re.compile(r"续重[^。]*?(价格|费用|价|费)", re.IGNORECASE), "continued_price"),
    (re.compile(r"最低价格|最低价"), "first_price"),
    (re.compile(r"首重.*(重量|kg|公斤)", re.IGNORECASE), "first_weight_kg"),
    (re.compile(r"续重.*(重量|kg|公斤)", re.IGNORECASE), "continued_unit_kg"),
)

# 阶梯续重表头（如"0<续重重量≤100kg / 续重价格"），返回 (下界, 上界)；开放档上界为 None。
_TIER_HEADER_RE = re.compile(
    r"^(?:(\d+(?:\.\d+)?)\s*<\s*)?续重(?:重量)?\s*(?:≤|<=)\s*(\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)\s*/",
    re.IGNORECASE,
)
_TIER_OPEN_HEADER_RE = re.compile(
    r"^续重(?:重量)?\s*>\s*(\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)\s*/",
    re.IGNORECASE,
)
_FIXED_TIER_HEADER_RE = re.compile(
    r"(?P<weight>\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)(?:以内|以下|及以下|含)?(?:重量)?(?:价格|费用|价|费)",
    re.IGNORECASE,
)
_IMPLIED_WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)[kK][gG]")
_NUMERIC_HEADER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

REQUIRED_PRICE_FIELDS = ("first_price", "continued_price")
_CORE_FIELDS = tuple(field for field in FIELD_ALIASES if field != "note")


def _match_header_field(header: str) -> tuple[str | None, str | None]:
    """返回 (字段名, 冲突说明)。表头模式规则优先，其次最长别名；等长命中视为歧义。"""
    for pattern, field in _HEADER_FIELD_PATTERNS:
        if pattern.search(header):
            return field, None
    best_field: str | None = None
    best_length = 0
    conflict = False
    for field, aliases in FIELD_ALIASES.items():
        matched = max((len(alias) for alias in aliases if header == alias or alias in header), default=0)
        if not matched:
            continue
        if matched > best_length:
            best_field = field
            best_length = matched
            conflict = False
        elif matched == best_length and field != best_field:
            conflict = True
    if conflict:
        return None, "表头同时包含多个字段含义"
    return best_field, None


def _match_tier_header(header: str) -> tuple[float | None, float | None] | None:
    match = _TIER_HEADER_RE.match(header)
    if match:
        lower = float(match.group(1)) if match.group(1) else 0.0
        return lower, float(match.group(2))
    match = _TIER_OPEN_HEADER_RE.match(header)
    if match:
        return float(match.group(1)), None
    return None


def _match_fixed_tier_header(header: str) -> float | None:
    """识别"1KG价格"这类固定重量档，避免和首重/续重列混淆。"""
    if any(marker in header for marker in ("首重", "续重", "最低")):
        return None
    match = _FIXED_TIER_HEADER_RE.search(header)
    return float(match.group("weight")) if match else None


def _header_implied_weight(header: str) -> float | None:
    match = _IMPLIED_WEIGHT_RE.search(header)
    return float(match.group(1)) if match else None


def _detect_header(
    rows: list[list[Any]],
) -> tuple[int | None, dict[int, str], dict[int, dict[str, Any]], list[str]]:
    """在前若干行中找表头行；返回 (行号, 列->字段映射, 列补充规格, 警告)。"""
    best_index: int | None = None
    best_mapping: dict[int, str] = {}
    best_specs: dict[int, dict[str, Any]] = {}
    best_score = 0
    best_warnings: list[str] = []

    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        mapping: dict[int, str] = {}
        specs: dict[int, dict[str, Any]] = {}
        ambiguous: list[str] = []
        row_warnings: list[str] = []
        for column, cell in enumerate(row):
            header = _normalize_text(cell)
            if not header:
                continue
            tier = _match_tier_header(header)
            if tier:
                if column not in mapping:
                    mapping[column] = "continued_tier"
                    specs[column] = {"tier": tier}
                continue
            fixed_tier = _match_fixed_tier_header(header)
            if fixed_tier is not None:
                if column not in mapping:
                    mapping[column] = "fixed_tier"
                    specs[column] = {"up_to_kg": fixed_tier}
                continue
            field, conflict = _match_header_field(header)
            if conflict:
                ambiguous.append(_cell_text(cell))
            elif field and field not in mapping:
                mapping[column] = field
        if (
            "origin_city" in mapping.values()
            and "origin_province" not in mapping.values()
            and "origin" not in mapping.values()
        ):
            numeric_columns = [
                column
                for column, cell in enumerate(row)
                if column not in mapping and _NUMERIC_HEADER_RE.match(_normalize_text(cell))
            ]
            if len(numeric_columns) == 1:
                column = numeric_columns[0]
                mapping[column] = "origin_province"
                specs[column] = {"candidate": True}
                row_warnings.append(
                    f"表头「{_cell_text(row[column])}」异常，已按候选「发件省」处理，需人工确认"
                )
        score = len(mapping)
        if score > best_score:
            best_score = score
            best_index = index
            best_mapping = mapping
            best_specs = specs
            best_warnings = row_warnings + [f"表头「{text}」含义不明确，已忽略该列" for text in ambiguous]

    warnings: list[str] = []
    if best_score < 2:
        return None, {}, {}, ["未能在前几行识别出报价表头"]
    return best_index, best_mapping, best_specs, best_warnings
