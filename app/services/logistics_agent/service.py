"""物流报价 Agent 对外入口（LangGraph 图编排）。

`handle_message`（正式消息）与 `preview_message`（第五步测试会话）共用
同一个编译后的图实例：识别、状态合并、缺参检查、线路匹配、Workflow 计费
与模板渲染全部由图节点完成，两者只在鉴权、发送权限与测试标记上有差异。
自动发送由调用方（消息链路）在所有校验通过后执行，本模块不直接发送任何
闲鱼消息；会话与消息由 checkpointer 按 thread_id 持久化。

并发控制：同一 thread 的完整处理周期（读状态 → 识别 → 合并 → 持久化）
由进程内 per-thread 锁串行化；发送前还要重新校验状态版本与报价表版本
（`claim_send`），避免发送期间会话已被更新。多进程部署需要额外的跨进程
锁（如数据库行锁或分布式锁），本模块只覆盖单进程语义。
"""

from __future__ import annotations

import threading
from typing import Any

from langchain_core.messages import HumanMessage
from loguru import logger

from app.services.logistics_agent import history
from app.services.logistics_agent.checkpointer import get_checkpointer
from app.services.logistics_agent.extractor import extract_from_model
from app.services.logistics_agent.graph import build_logistics_graph
from app.services.logistics_agent.graph_state import (
    ENTRY_PRODUCTION,
    ENTRY_TEST,
    graph_event,
)
from app.services.logistics_agent.model import ModelCallError, ModelNotConfigured
from app.services.logistics_agent.models import (
    INTENT_LOGISTICS,
    SESSION_FAILED,
    AgentDecision,
    SessionState,
)
from app.services.logistics_agent.nodes import GraphDeps
from app.services.logistics_agent.render import render_failure_message
from app.services.logistics_agent.settings import AgentSettingsStore
from app.services.logistics_agent.state import is_session_expired
from app.services.logistics_agent.tools import selected_book_sha
from app.services.logistics_quote_routes.service import LogisticsRouteService

# 进程内 per-thread 锁注册表：同一会话的完整处理周期串行化。
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(thread_id: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(thread_id)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[thread_id] = lock
        return lock


class LogisticsQuoteAgent:
    """面向店家的物流报价 Agent。"""

    def __init__(
        self,
        db_manager: Any,
        checkpointer: Any = None,
        notification_publisher: Any = None,
    ):
        self.db = db_manager
        self.route_service = LogisticsRouteService(db_manager)
        self.settings_store = AgentSettingsStore(db_manager)
        self.checkpointer = checkpointer or get_checkpointer(db_manager)
        from app.services.logistics_agent.notifications import publish_logistics_quote_event

        self.notification_publisher = notification_publisher or (
            lambda event: publish_logistics_quote_event(event, db=self.db)
        )
        self.graph = build_logistics_graph(
            GraphDeps(
                db=db_manager,
                settings_store=self.settings_store,
                route_service=self.route_service,
                notification_publisher=self.notification_publisher,
                # 通过模块属性在调用时解析，便于测试替换识别管线。
                extract_fn=lambda cookie_id, settings, message, session: extract_from_model(
                    cookie_id, settings, message, session,
                ),
            ),
            checkpointer=self.checkpointer,
        )

    # ---------- 正式消息入口 ----------

    def handle_message(
        self,
        *,
        message: str,
        chat_id: str,
        cookie_id: str,
        item_id: str = "",
        message_id: str = "",
    ) -> AgentDecision | None:
        """处理一条买家消息；返回 None 表示与物流无关，走原有回复链路。"""
        settings = self.settings_store.load(cookie_id)
        if not settings.enabled:
            return None
        if not settings.covers_item(item_id):
            return None

        thread_id = history.production_thread_id(cookie_id, chat_id, item_id)
        with _thread_lock(thread_id):
            session = self._load_session(thread_id, enforce_ttl=True)
            if session and session.has_processed_message(message_id):
                # 同一条消息已由 Agent 处理过：不重复报价，也不回退到通用 AI。
                return AgentDecision(action="ignore", reason="duplicate_message", intent=INTENT_LOGISTICS)

            values = self._invoke(
                thread_id, mode=ENTRY_PRODUCTION, cookie_id=cookie_id, chat_id=chat_id,
                item_id=item_id, message=message, message_id=message_id,
                session=session, had_session=bool(session),
            )
        decision = _decision_from(values)
        if decision.action == "ignore" and decision.reason == "not_logistics":
            return None
        return decision

    # ---------- 试算（第五步测试会话） ----------

    def preview_message(
        self,
        *,
        message: str,
        chat_id: str,
        cookie_id: str,
        item_id: str = "",
        message_id: str = "",
        thread_id: str = "",
    ) -> AgentDecision | None:
        """试算入口：与正式链路共用同一个图。

        区别：不检查 Agent 开关与商品范围（便于配置过程中测试）；意图不明
        时也给出识别结果，便于店家观察识别效果。
        """
        with _thread_lock(thread_id):
            session = self._load_session(thread_id, enforce_ttl=False)
            if session and session.has_processed_message(message_id):
                return AgentDecision(action="ignore", reason="duplicate_message", intent=INTENT_LOGISTICS)
            values = self._invoke(
                thread_id, mode=ENTRY_TEST, cookie_id=cookie_id, chat_id=chat_id,
                item_id=item_id, message=message, message_id=message_id,
                session=session, had_session=bool(session),
            )
        return _decision_from(values)

    # ---------- 会话快照与管理 ----------

    def thread_snapshot(self, thread_id: str) -> dict[str, Any]:
        """读取会话快照与可回放消息（测试窗口恢复用）。"""
        return history.snapshot_payload(self.graph, thread_id)

    def reset_thread(self, thread_id: str) -> bool:
        """删除指定会话的状态与消息记录。"""
        return history.reset_thread(self.checkpointer, thread_id)

    @staticmethod
    def new_thread_id() -> str:
        """生成新的测试会话 ID。"""
        return history.new_test_thread_id()

    # ---------- 发送闸门与审计 ----------

    def claim_send(
        self,
        *,
        cookie_id: str,
        chat_id: str,
        item_id: str,
        message_id: str,
        state_version: int,
        book_sha256: str,
    ) -> bool:
        """发送闸门：登记一条待发送记录，全部校验通过才允许发送。

        - 重读 thread 最新状态：决策生成后会话又被更新（版本不一致）时拒绝发送；
        - 重读报价表版本：决策生成后报价表已重新导入（哈希不一致）时拒绝发送；
        - 同一消息只允许一条待发送/已发送记录（唯一键），重复触发直接拒绝。
        """
        thread_id = history.production_thread_id(cookie_id, chat_id, item_id)
        with _thread_lock(thread_id):
            values = history.load_state(self.graph, thread_id)
            session: SessionState | None = values.get("session")
            if session is None or session.state_version != state_version:
                return False
            if book_sha256:
                latest_sha = self._current_book_sha(cookie_id)
                if latest_sha != book_sha256:
                    return False
            with self.db.lock:
                if message_id:
                    cursor = self.db.conn.execute(
                        """
                        SELECT 1 FROM logistics_quote_send_logs
                        WHERE cookie_id = ? AND chat_id = ? AND item_id = ?
                          AND message_id = ? AND status IN ('pending', 'sent')
                        """,
                        (cookie_id, chat_id, item_id, message_id),
                    )
                    if cursor.fetchone() is not None:
                        return False
                self.db.conn.execute(
                    """
                    INSERT INTO logistics_quote_send_logs (
                        cookie_id, chat_id, item_id, message_id, state_version,
                        book_sha256, summary, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (cookie_id, chat_id, item_id, message_id, state_version, book_sha256, ""),
                )
                self.db.conn.commit()
        return True

    def mark_send_result(
        self,
        *,
        cookie_id: str,
        chat_id: str,
        item_id: str,
        message_id: str,
        success: bool,
    ) -> None:
        """把最近一条待发送记录标记为已发送或发送失败。"""
        with self.db.lock:
            self.db.conn.execute(
                """
                UPDATE logistics_quote_send_logs SET status = ?
                WHERE id = (
                    SELECT id FROM logistics_quote_send_logs
                    WHERE cookie_id = ? AND chat_id = ? AND item_id = ? AND message_id = ?
                      AND status = 'pending'
                    ORDER BY id DESC LIMIT 1
                )
                """,
                ("sent" if success else "failed", cookie_id, chat_id, item_id, message_id),
            )
            self.db.conn.commit()

    # ---------- 内部 ----------

    def _current_book_sha(self, cookie_id: str) -> str:
        """当前生效报价表批次的第一条哈希（与 resolve_routes 选取口径一致）。"""
        settings = self.settings_store.load(cookie_id)
        user_id = self.db.get_cookie_owner_user(cookie_id)
        if user_id is None:
            return ""
        imports = self.route_service.list_imports(user_id)
        available_ids = [item["id"] for item in imports if item.get("status") == "completed"]
        return selected_book_sha(imports, settings.resolved_book_ids(available_ids))

    def _load_session(self, thread_id: str, *, enforce_ttl: bool) -> SessionState | None:
        """从 checkpointer 读取业务状态；正式会话过期后按新询价处理。"""
        values = history.load_state(self.graph, thread_id)
        session: SessionState | None = values.get("session")
        if session is None:
            return None
        if enforce_ttl and is_session_expired(session):
            return None
        return session

    def _invoke(
        self,
        thread_id: str,
        *,
        mode: str,
        cookie_id: str,
        chat_id: str,
        item_id: str,
        message: str,
        message_id: str,
        session: SessionState | None,
        had_session: bool,
    ) -> dict[str, Any]:
        input_state: dict[str, Any] = {
            "thread_id": thread_id,
            "cookie_id": cookie_id,
            "chat_id": chat_id,
            "item_id": item_id,
            "mode": mode,
            "message": message,
            "message_id": message_id,
            "session": session or SessionState(),
            "had_session": had_session,
            "messages": [
                HumanMessage(content=message, id=f"buyer-{message_id}" if message_id else None),
            ],
        }
        try:
            return self.graph.invoke(input_state, config={"configurable": {"thread_id": thread_id}})
        except (ModelNotConfigured, ModelCallError) as exc:
            # 模型故障两个入口同口径降级：给出明确动作与原因，回退通用 AI
            # 会让通用模型自行猜测运费；故障不标记消息已处理，可安全重试。
            logger.warning(f"物流 Agent 模型调用失败：{type(exc).__name__}: {exc}")
            failure = _model_failure_state(session, exc, self.settings_store.load(cookie_id), message_id)
            failure.update({
                "cookie_id": cookie_id,
                "chat_id": chat_id,
                "item_id": item_id,
                "mode": mode,
                "thread_id": thread_id,
            })
            self._persist_failure(thread_id, failure)
            return failure

    def _persist_failure(self, thread_id: str, failure: dict[str, Any]) -> None:
        """把故障降级结果写回 checkpoint：快照、决策与审计保持一致。"""
        from app.services.logistics_agent.notifications import build_logistics_quote_event

        event = build_logistics_quote_event(
            account_id=failure.get("cookie_id", ""),
            message_id=failure.get("message_id", ""),
            chat_id=failure.get("chat_id", ""),
            item_id=failure.get("item_id", ""),
            thread_id=thread_id,
            decision_action=failure.get("action", ""),
            reason=failure.get("reason", ""),
            mode=failure.get("mode", ""),
        )
        if event:
            try:
                failure["notification_result"] = self.notification_publisher(event)
            except Exception as exc:  # noqa: BLE001 - 通知故障不得阻断降级
                logger.error(f"物流报价事件发布失败：{type(exc).__name__}: {exc}")
        try:
            self.graph.update_state(
                {"configurable": {"thread_id": thread_id}}, failure, as_node="finalize",
            )
        except Exception as exc:  # noqa: BLE001 - 故障降级本身不允许拖垮调用方
            logger.warning(f"物流 Agent 故障状态写回失败：{type(exc).__name__}: {exc}")


def _model_failure_state(
    session: SessionState | None, exc: Exception, settings: Any, message_id: str = ""
) -> dict[str, Any]:
    """模型故障降级：返回可读决策，不静默丢失上下文，也不发送占位符。"""
    from app.services.logistics_agent.nodes import _agent_message

    state = (session or SessionState()).model_copy(deep=True)
    state.status = SESSION_FAILED
    reason = "model_not_configured" if isinstance(exc, ModelNotConfigured) else "model_failed"
    failure_text = render_failure_message(settings.templates.failure)
    action = "manual"
    # 与渲染节点同一发送闸门：自动发送关闭时故障提示也只生成草稿。
    if not getattr(settings, "auto_send", False):
        action = "draft"
    return {
        "message_id": message_id,
        "session": state,
        "rendered_messages": [failure_text],
        "messages": [_agent_message(message_id, 0, failure_text)],
        "action": action,
        "reason": reason,
        "quotes": [],
        "routes": None,
        "book_sha256": "",
        "missing_fields": [],
        "events": [graph_event("service", message_id=message_id, detail=f"model error: {type(exc).__name__}")],
    }


def _decision_from(values: dict[str, Any]) -> AgentDecision:
    """图状态 → 决策（实现复用 history.decision_from_state，快照恢复同源）。"""
    return history.decision_from_state(values)
