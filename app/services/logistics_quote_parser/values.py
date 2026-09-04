"""单元格文本与数值解析：金额、重量、时效、区域与字段文案。"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .constants import MAX_CELL_TEXT

_TEXT_CLEAN_RE = re.compile(r"\s+")
_MONEY_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_RANGE_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?\s*[-~至到]\s*[+-]?\d+(?:\.\d+)?$")


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return _TEXT_CLEAN_RE.sub("", text)


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > MAX_CELL_TEXT:
        text = text[: MAX_CELL_TEXT - 1] + "…"
    return text


def _parse_amount(value: Any) -> tuple[float | None, str | None]:
    """解析金额；返回 (数值, 失败原因)。范围值与含糊文本不强行归类。"""
    text = _normalize_text(value)
    if not text:
        return None, None
    if any(keyword in text for keyword in ("票", "件", "单")):
        return None, "按票/件计价的费用与按kg单价含义不同"
    text = text.upper().replace("￥", "").replace("¥", "").replace("RMB", "")
    if text.endswith("/KG"):
        text = text[:-3]
    if text.endswith("元"):
        text = text[:-1]
    if _MONEY_RE.match(text):
        number = float(text)
        if number < 0:
            return None, "金额为负数"
        return number, None
    if _RANGE_RE.match(text):
        return None, "金额为区间值"
    return None, "金额无法解析"


def _parse_weight(value: Any) -> tuple[float | None, str | None]:
    """解析重量（kg）；支持 1kg / 0.5千克 / 500g / 首重1kg 等写法。"""
    text = _normalize_text(value)
    if not text:
        return None, None
    if _RANGE_RE.match(text):
        return None, "重量为区间值"
    match = re.search(r"([+-]?\d+(?:\.\d+)?)(千克|公斤|KG|Kg|kg|G|g)?$", text.upper())
    if not match:
        return None, "重量无法解析"
    number = float(match.group(1))
    unit = (match.group(2) or "KG").upper()
    if unit == "G":
        number = number / 1000
    if number < 0:
        return None, "重量为负数"
    return number, None


def _parse_eta(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _region_text(province: str | None, city: str | None, fallback: str | None = None) -> str | None:
    if province and city:
        return city if province in city else f"{province}{city}"
    return province or city or fallback or None


def _label(field: str) -> str:
    labels = {
        "seller": "店家",
        "channel": "渠道",
        "carrier": "承运商",
        "route": "路线/区域",
        "eta": "时效",
        "origin_province": "发件省",
        "origin_city": "发件市",
        "origin": "发件地",
        "destination_province": "收件省",
        "destination_city": "收件市",
        "destination": "收件地",
        "first_weight_kg": "首重重量",
        "first_price": "首重价格",
        "continued_unit_kg": "续重单位",
        "continued_price": "续重价格",
        "fixed_tiers": "固定重量档价格",
        "note": "备注",
    }
    return labels.get(field, field)
