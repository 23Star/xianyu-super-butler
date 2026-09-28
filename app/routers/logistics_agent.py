"""物流 Agent 路由。

按账号维度聚合订单的物流状态：单订单轨迹查询已有
``/api/orders/{order_id}/logistics``，这里补充"最近哪些单还在途/滞留"的批量视角。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query

from utils.xianyu_seller_api import SellerApiError, XianyuSellerAPI, parse_logistics_trace

# 每次聚合最多并发查询的物流轨迹数，避免瞬间打爆卖家端接口触发风控
_CONCURRENCY = 3


def create_logistics_agent_router(
    get_current_user: Callable[..., dict[str, Any]],
    db_manager: Any,
) -> APIRouter:
    router = APIRouter()

    def require_account(cookie_id: str, current_user: dict[str, Any]) -> str:
        """校验账号归属，返回可用的 cookies_str。"""
        details = db_manager.get_cookie_details(cookie_id)
        if not details or details.get("user_id") != current_user["user_id"]:
            raise HTTPException(status_code=404, detail="账号不存在或无权限")
        cookies_str = details.get("value") or ""
        if not cookies_str:
            raise HTTPException(status_code=400, detail=f"账号缺少 Cookie: {cookie_id}")
        return cookies_str

    @router.get("/logistics-agent/{cookie_id}/summary")
    async def get_logistics_summary(
        cookie_id: str,
        limit: int = Query(default=10, ge=1, le=50),
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """聚合该账号最近订单的物流轨迹状态。"""
        cookies_str = require_account(cookie_id, current_user)

        orders = db_manager.get_orders_by_cookie(cookie_id, limit=limit)
        if not orders:
            return {"success": True, "items": [], "message": "该账号暂无订单记录"}

        semaphore = asyncio.Semaphore(_CONCURRENCY)
        api = XianyuSellerAPI(cookie_id, cookies_str)
        items: list[dict[str, Any]] = []

        async def fetch_one(order: dict[str, Any]) -> None:
            order_id = str(order.get("order_id") or "")
            if not order_id:
                return
            entry: dict[str, Any] = {"order_id": order_id}
            items.append(entry)
            async with semaphore:
                try:
                    trace = parse_logistics_trace(await api.get_logistics_trace(order_id))
                    entry.update(trace)
                    entry["query_status"] = "ok"
                except SellerApiError as exc:
                    entry["query_status"] = "error"
                    entry["error"] = str(exc)

        try:
            await asyncio.gather(*(fetch_one(order) for order in orders))
        finally:
            await api.close()

        return {"success": True, "items": items}

    return router
