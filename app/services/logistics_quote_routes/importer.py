"""报价文件 -> 线路明细导入。

复用报价表解析器的完整逐行模式，把解析行转换为规范化线路并写入
线路明细表；导入按 (用户, 文件哈希) 幂等，重复导入同一文件时整批替换。
"""

from __future__ import annotations

from typing import Any

from app.services import logistics_quote_parser
from app.services.logistics_quote_routes.model import build_price_model
from app.services.logistics_quote_routes.region import (
    is_known_province,
    normalize_region,
    split_region_text,
)

_BATCH_SIZE = 5_000


def _region_pair(province: Any, city: Any, fallback: Any) -> tuple[str, str]:
    """从解析行的省/市/整体字段得到（规范省, 规范市）。"""
    normalized_province = normalize_region(province)
    normalized_city = normalize_region(city)
    if not normalized_province and not normalized_city:
        # 只有整体地名时：像省名的按省处理，否则当作市留待线路库反查省份。
        fallback_text = normalize_region(fallback)
        if is_known_province(fallback_text):
            return fallback_text, ""
        return "", fallback_text
    if not normalized_province and normalized_city and not is_known_province(normalized_city):
        # 省列缺失但市列有值：市可能是省名（如顺心表把直辖市写在省列位置）。
        return "", normalized_city
    return normalized_province, normalized_city


def build_route_rows(parse_result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """把解析结果转换为线路行；返回 (线路行列表, 告警列表)。

    只有 review_state 为 valid 的行才进入线路明细：review/rejected 行存在
    语义或取值疑点时宁可不报价，避免错误价格直接生效。
    """
    warnings: list[str] = []
    skipped_review = 0
    skipped_unbuildable = 0
    skipped_routeless = 0
    routes: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

    for row in parse_result.get("rows", []):
        state = row.get("review_state")
        if state not in (None, "valid"):
            if state == "review":
                skipped_review += 1
            continue
        carrier = (row.get("carrier") or "").strip()
        if not carrier:
            continue
        origin_province, origin_city = _region_pair(
            row.get("origin_province"), row.get("origin_city"), row.get("origin")
        )
        dest_province, dest_city = _region_pair(
            row.get("destination_province"), row.get("destination_city"), row.get("destination")
        )
        if not origin_province and not origin_city and not dest_province and not dest_city:
            skipped_routeless += 1
            continue
        price_model = build_price_model(row)
        if price_model is None:
            skipped_unbuildable += 1
            continue
        key = (carrier, origin_province, origin_city, dest_province, dest_city)
        routes[key] = {
            "carrier": carrier,
            "book_kind": row.get("book_kind"),
            "origin_province": origin_province,
            "origin_city": origin_city,
            "dest_province": dest_province,
            "dest_city": dest_city,
            "price_model": price_model,
        }

    if skipped_review:
        warnings.append(f"{skipped_review} 行存在疑点需人工确认，未纳入线路明细")
    if skipped_unbuildable:
        warnings.append(f"{skipped_unbuildable} 行价格形态不完整，未纳入线路明细")
    if skipped_routeless:
        warnings.append(f"{skipped_routeless} 行缺少收发地，未纳入线路明细")
    return list(routes.values()), warnings


def parse_quote_file(data: bytes, filename: str, content_type: str = "") -> dict[str, Any]:
    """解析上传的报价文件（完整逐行模式）；解析失败抛 ValueError。"""
    return logistics_quote_parser.parse_quote_file(
        data,
        filename=filename,
        content_type=content_type,
        rate_book_summary=False,
    )
