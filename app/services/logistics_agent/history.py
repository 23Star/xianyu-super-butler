"""测试会话与 thread 管理：快照读取、消息转换、会话重置。

thread_id 约定：
- 正式消息链路使用 `prod:` 前缀的确定性 ID（账号 + 聊天 + 商品隔离）；
- 第五步测试会话使用客户端/服务端生成的 `test-` 随机 ID。
测试入口禁止使用 `prod:` 前缀，避免与正式会话相互覆盖。
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from app.services.logistics_agent.models import (
    INTENT_LOGISTICS,
    AgentDecision,
    SessionState,
)
from app.services.logistics_agent.state import missing_fields

PRODUCTION_THREAD_PREFIX = "prod:"
TEST_THREAD_PREFIX = "test-"


def production_thread_id(cookie_id: str, chat_id: str, item_id: str) -> str:
    """正式消息链路的确定性 thread：账号 + 聊天 + 商品隔离。"""
    return f"{PRODUCTION_THREAD_PREFIX}{cookie_id}:{chat_id}:{item_id}"


def new_test_thread_id() -> str:
    """新建第五步测试会话 ID。"""
    return f"{TEST_THREAD_PREFIX}{uuid.uuid4().hex}"


def is_reserved_thread_id(thread_id: str) -> bool:
    """测试入口不允许使用的 thread ID（正式会话命名空间）。"""
    return (thread_id or "").startswith(PRODUCTION_THREAD_PREFIX)


def load_state(graph: Any, thread_id: str) -> dict[str, Any]:
    """读取 thread 的图状态值；会话不存在时返回空字典。"""
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    return dict(snapshot.values or {})


def reset_thread(checkpointer: Any, thread_id: str) -> bool:
    """删除指定 thread 的会话与消息记录（测试会话重置）。"""
    try:
        checkpointer.delete_thread(thread_id)
        return True
    except Exception as exc:  # noqa: BLE001 - 删除失败要给调用方可读反馈
        logger.warning(f"物流会话 {thread_id} 重置失败：{type(exc).__name__}: {exc}")
        return False


def messages_to_payload(values: dict[str, Any]) -> list[dict[str, Any]]:
    """把图状态里的 LangChain 消息转换成前端气泡数据。"""
    payload: list[dict[str, Any]] = []
    for message in values.get("messages", []):
        content = message.content if isinstance(message.content, str) else str(message.content)
        payload.append({
            "role": "buyer" if message.type == "human" else "agent",
            "content": content,
            "id": message.id or "",
        })
    return payload


def decision_from_state(values: dict[str, Any]) -> AgentDecision:
    """把图最终状态转换为对外决策契约（AgentDecision）。"""
    session: SessionState = values.get("session") or SessionState()
    extracted = values.get("extracted")
    return AgentDecision(
        action=values.get("action", "ignore"),
        messages=values.get("rendered_messages", []),
        reason=values.get("reason", ""),
        intent=extracted.intent if extracted is not None else INTENT_LOGISTICS,
        fields=session.model_dump(),
        routes=_route_summaries(values.get("routes")),
        quotes=values.get("quotes", []),
        channel_results=_channel_results(values),
        missing_fields=values.get("missing_fields", []),
        state_version=session.state_version,
        book_sha256=values.get("book_sha256", ""),
        session_status=session.status,
    )


def _channel_results(values: dict[str, Any]) -> list[dict[str, Any]]:
    from app.services.logistics_agent.render import price_rule_text

    resolution = values.get("routes")
    if resolution is None or not hasattr(resolution, "matched"):
        return []
    quotes = {quote["carrier"]: quote for quote in values.get("quotes", [])}
    results = []
    for carrier, match in resolution.matched.items():
        quote = quotes.get(carrier)
        results.append({
            "carrier": carrier,
            "status": "quoted" if quote else "pricing_failed",
            "rule": price_rule_text(match.get("price_model") or {}),
            "total_price": quote.get("total_price") if quote else None,
            "chargeable_weight_kg": quote.get("chargeable_weight_kg") if quote else None,
        })
    for carrier in resolution.unmatched_carriers:
        results.append({
            "carrier": carrier,
            "status": "missing_city" if carrier in resolution.needs_city_carriers else "no_route",
            "rule": "", "total_price": None, "chargeable_weight_kg": None,
        })
    return sorted(results, key=lambda result: (
        result["total_price"] is None,
        result["total_price"] if result["total_price"] is not None else float("inf"),
        result["carrier"],
    ))


def _route_summaries(routes: Any) -> list[dict[str, Any]]:
    if routes is None:
        return []
    source = routes.matched if hasattr(routes, "matched") else (routes or {})
    return [
        {
            "carrier": match["carrier"],
            "match_level": match["match_level"],
            "match_level_label": match["match_level_label"],
            "origin": match["origin"],
            "destination": match["destination"],
            "price_model": match["price_model"],
        }
        for match in source.values()
    ]


def snapshot_payload(graph: Any, thread_id: str) -> dict[str, Any]:
    """会话快照：结构化状态 + 可回放消息 + 最近决策 + 审计事件。"""
    values = load_state(graph, thread_id)
    if not values:
        return {
            "thread_id": thread_id,
            "exists": False,
            "session": None,
            "messages": [],
            "events": [],
        }
    session: SessionState = values.get("session") or SessionState()
    return {
        "thread_id": thread_id,
        "exists": True,
        "cookie_id": values.get("cookie_id", ""),
        "chat_id": values.get("chat_id", ""),
        "item_id": values.get("item_id", ""),
        "round_id": session.round_id,
        "state_version": session.state_version,
        "status": session.status,
        "missing_fields": missing_fields(session),
        "last_action": values.get("action", ""),
        "last_reason": values.get("reason", ""),
        "session": session.model_dump(),
        "decision": decision_from_state(values).model_dump(),
        "messages": messages_to_payload(values),
        "events": values.get("events", []),
    }
