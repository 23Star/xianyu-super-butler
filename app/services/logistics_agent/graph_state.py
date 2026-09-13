"""物流报价 Agent 的 LangGraph 图状态。

图状态是运行期唯一会话真相源：messages 与业务状态（session）都由
checkpointer 按 thread_id 持久化。业务字段继续以 `SessionState` 为契约，
本模块只定义通道与合并语义，不新增第二套业务模型。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from app.services.logistics_agent.models import ExtractedQuote, SessionState

# 入口类型：正式消息链路与第五步测试会话共用同一个图。
ENTRY_PRODUCTION = "production"
ENTRY_TEST = "test"


def add_events(
    left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """审计事件通道：节点级事件只增不改。"""
    return (left or []) + (right or [])


def graph_event(
    node: str,
    *,
    message_id: str = "",
    state_version: int = 0,
    detail: str = "",
    error: str = "",
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    """构造一条节点级审计事件（不含模型凭据等敏感信息）。"""
    return {
        "node": node,
        "message_id": message_id,
        "state_version": state_version,
        "detail": detail,
        "error": error,
        "elapsed_ms": round(elapsed_ms),
    }


class LogisticsGraphState(TypedDict, total=False):
    """物流 Agent 图状态；节点只返回需要更新的通道。"""

    # LangChain 标准消息列表：买家消息与 Agent 回复（按消息 ID 幂等追加）。
    messages: Annotated[list[AnyMessage], add_messages]
    # 审计事件（节点级，只增）。
    events: Annotated[list[dict[str, Any]], add_events]

    # 业务隔离键与入口。
    thread_id: str
    cookie_id: str
    chat_id: str
    item_id: str
    mode: str
    message: str
    message_id: str
    had_session: bool

    # 业务状态与中间结果。
    session: SessionState
    extracted: ExtractedQuote | None
    missing_fields: list[str]
    follow_up: str
    routes: Any
    quotes: list[dict[str, Any]]
    package_plan: dict[str, Any]
    book_sha256: str

    # 最终输出。
    rendered_messages: list[str]
    action: str
    reason: str
