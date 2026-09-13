"""收发地 -> 线路匹配（Agent 侧封装）。

负责地址文本拆分、省市反查、按计费重选择快递/物流报价表，以及把匹配
结果整理成 Workflow 可用的 quote_config 线路部分。所有费率都来自线路
明细表，缺线路时返回结构化原因，绝不生成价格。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.services.logistics_quote_routes.region import split_region_text
from app.services.logistics_quote_routes.service import LogisticsRouteService

# 路由分界：计费重 < 30kg 走快递报价表，>= 30kg 走物流报价表。
# 口径与 workflows/logistics-quote.mjs 的 route_weight_kg/category 保持一致，
# 由测试用 Node CLI 做交叉回归（见 tests/test_logistics_quote_agent.py）。
ROUTE_WEIGHT_RATIO = 8000
FREIGHT_MIN_WEIGHT_KG = 30


@dataclass
class RegionParts:
    text: str = ""
    province: str = ""
    city: str = ""

    def to_query(self) -> dict[str, str]:
        return {"province": self.province, "city": self.city}


@dataclass
class RouteResolution:
    matched: dict[str, dict[str, Any]] = field(default_factory=dict)
    match_level: str | None = None
    match_level_label: str = ""
    needs_city_carriers: list[str] = field(default_factory=list)
    unmatched_carriers: list[str] = field(default_factory=list)
    route_not_found: bool = False
    ambiguous_city: str = ""
    missing_city_carriers: list[str] = field(default_factory=list)


def route_weight_kg(weight: float | None, dims: list[float | None]) -> float:
    """路由计费重：ceil(max(实重, 体积/8000))；与 Workflow 同口径。"""
    actual = weight or 0.0
    volume = 0.0
    if all(value is not None and value > 0 for value in dims):
        volume = dims[0] * dims[1] * dims[2]
    return math.ceil(max(actual, volume / ROUTE_WEIGHT_RATIO))


def category_for(weight: float | None, dims: list[float | None]) -> str:
    """Workflow 口径的分类：express / freight。"""
    return "express" if route_weight_kg(weight, dims) < FREIGHT_MIN_WEIGHT_KG else "freight"


def book_kind_for(weight: float | None, dims: list[float | None]) -> str:
    """线路表书种：计费重 < 30kg 用快递表，否则用物流表（解析器约定）。"""
    return "logistics" if category_for(weight, dims) == "freight" else "express"


class RouteResolver:
    """线路匹配入口：组合线路服务与地址解析。"""

    def __init__(self, route_service: LogisticsRouteService, user_id: int):
        self.routes = route_service
        self.user_id = user_id

    def resolve(
        self,
        sender_text: str,
        receiver_text: str,
        book_kind: str,
        import_ids: list[int],
        carrier_filter: str | None = None,
    ) -> RouteResolution:
        resolution = RouteResolution()
        origin = self._split(sender_text)
        destination = self._split(receiver_text)

        # 城市缺少省份时按线路库反查；同名市跨省或反查不到时需要买家补充省份。
        for parts, side in ((origin, "origin"), (destination, "destination")):
            if parts.city and not parts.province:
                resolved = self.routes.resolve_province_by_city(self.user_id, parts.city, side=side)
                if resolved["ambiguous"] or not resolved["province"]:
                    resolution.ambiguous_city = parts.city
                    return resolution
                parts.province = resolved["province"]

        result = self.routes.match_routes(
            self.user_id, origin.to_query(), destination.to_query(), book_kind,
            import_ids=import_ids or None,
            carriers=[carrier_filter] if carrier_filter else None,
        )
        resolution.matched = result["matched"]
        resolution.match_level = result.get("match_level")
        resolution.match_level_label = result.get("match_level_label", "")
        resolution.needs_city_carriers = result.get("needs_city_carriers", [])
        resolution.unmatched_carriers = result.get("unmatched_carriers", [])
        resolution.route_not_found = result.get("route_not_found", False)
        return resolution

    def _split(self, text: str | None) -> RegionParts:
        if not text:
            return RegionParts()
        province, city = split_region_text(text)
        return RegionParts(text=text, province=province, city=city)
