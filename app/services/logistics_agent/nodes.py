"""LangGraph 节点实现：识别 → 合并 → 缺参检查 → 线路 → Workflow → 渲染。

节点保持短小、可重试、可测试：识别节点只做结构化抽取，合并节点只做状态
语义，线路与计费节点使用确定性逻辑（RouteResolver + Node Workflow），金额
永远只来自 Workflow 结果。渲染节点负责模板渲染与未解析占位符闸门。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
import re

from loguru import logger

from app.services.logistics_agent.graph_state import (
    ENTRY_TEST,
    LogisticsGraphState,
    graph_event,
)
from app.services.logistics_agent.model import ModelCallError, ModelNotConfigured
from app.services.logistics_agent.models import (
    INTENT_LOGISTICS,
    SESSION_COLLECTING,
    SESSION_FAILED,
    SESSION_MANUAL,
    SESSION_QUOTED,
    ExtractedQuote,
    SessionState,
)
from app.services.logistics_agent.render import (
    build_quote_values,
    render_failure_message,
    render_follow_up,
    render_no_route,
    render_provisional_notice,
    render_template,
    split_messages,
    unresolved_tokens,
)
from app.services.logistics_agent.routes import RouteResolver, book_kind_for
from app.services.logistics_agent.settings import AgentSettings, AgentSettingsStore
from app.services.logistics_agent.state import (
    follow_up_field,
    merge_state,
    missing_fields,
    register_processed_message,
)
from app.services.logistics_agent.tools import (
    WorkflowError,
    WorkflowUnavailable,
    build_quote_config,
    build_workflow_input,
    call_workflow,
    selected_book_sha,
)
from app.services.logistics_agent.extractor import parse_package_weights
from app.services.logistics_agent.models import ExtractedPackage

# 渲染为追问的失败原因（其余 reason 走失败模板）。
_FOLLOW_UP_REASONS = ("missing_params", "ambiguous_city", "missing_city")
# 转人工的失败原因（其余 reason 标记为 failed）。
_MANUAL_REASONS = ("account_not_found", "no_rate_book")


@dataclass
class GraphDeps:
    """图节点的依赖注入容器（数据库与识别管线都可替换，便于测试）。"""

    db: Any
    settings_store: AgentSettingsStore
    route_service: Any
    extract_fn: Callable[[str, AgentSettings, str, SessionState], ExtractedQuote]
    notification_publisher: Callable[[dict[str, Any]], Any] | None = None


def extract_node(deps: GraphDeps, state: LogisticsGraphState) -> dict[str, Any]:
    """识别节点：模型结构化抽取；模型故障向上抛出，由入口按模式转换。"""
    started = time.perf_counter()
    session: SessionState = state.get("session") or SessionState()
    settings = deps.settings_store.load(state["cookie_id"])
    extracted = deps.extract_fn(state["cookie_id"], settings, state["message"], session)
    # Models occasionally collapse “第一个23kg第二个130kg” into one weight.
    # A deterministic pass preserves every explicit package boundary.
    explicit_weights = parse_package_weights(state["message"])
    if len(explicit_weights) > 1:
        extracted.packages = [
            ExtractedPackage(package_id=str(index), weight_kg=weight)
            for index, weight in enumerate(explicit_weights, 1)
        ]
        extracted.weight_kg = sum(explicit_weights)
    # 买家常用“我不知道/不清楚重量”等自然语言回答上一轮追问。
    # 这不是缺少意图，而是接受按默认 1kg 计费的明确语义；补入结构化
    # 字段后才能继续线路与 Workflow，而不会重复发送同一条追问。
    if (
        (extracted.intent == "logistics_quote" or session.has_shipment_params())
        and extracted.weight_kg is None
        and settings.pricing.default_one_kg
        and re.search(r"(?:不知道|不清楚|不确定|无法确认|没称过|没有称|不晓得).{0,8}(?:重|重量|多重|几重|公斤|kg)", state["message"], re.I)
    ):
        extracted.weight_kg = 1.0
        extracted.weight_confidence = max(extracted.weight_confidence, 0.9)
        extracted.notes = "买家无法确认重量，按配置默认 1kg 计费"
    return {
        "extracted": extracted,
        "events": [graph_event(
            "extract",
            message_id=state.get("message_id", ""),
            state_version=session.state_version,
            detail=f"intent={extracted.intent}",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )],
    }


def merge_state_node(deps: GraphDeps, state: LogisticsGraphState) -> dict[str, Any]:
    """合并节点：补充参数、明确修改与新询价轮次（正式入口含意图闸门）。

    每条新消息运行开始时显式清空瞬时结果通道（quotes/routes/book_sha256
    等）：LangGraph 会保留未覆盖的旧值，不清空会让上一轮报价混进本轮
    缺参或失败决策。
    """
    started = time.perf_counter()
    extracted: ExtractedQuote = state["extracted"]
    session: SessionState = state.get("session") or SessionState()
    message_id = state.get("message_id", "")

    # 本轮瞬时结果：新消息一律从空开始，旧轮次报价只存在于历史事件里。
    ephemeral_reset: dict[str, Any] = {
        "quotes": [],
        "package_plan": {},
        "routes": None,
        "book_sha256": "",
        "rendered_messages": [],
        "missing_fields": [],
        "follow_up": "",
    }

    if (
        state.get("mode") != ENTRY_TEST
        and extracted.intent != INTENT_LOGISTICS
        and not session.has_shipment_params()
    ):
        # 模型确认不是物流询价，且会话里没有任何包裹参数：交回通用 AI。
        return {
            "action": "ignore",
            "reason": "not_logistics",
            **ephemeral_reset,
            "events": [graph_event(
                "merge_state", message_id=message_id, state_version=session.state_version,
                detail="not_logistics", elapsed_ms=(time.perf_counter() - started) * 1000,
            )],
        }

    merged = merge_state(session, extracted, message_id)
    return {
        "session": merged,
        **ephemeral_reset,
        # 无条件覆写：避免上一轮 checkpoint 里遗留的 action/reason 影响路由。
        "action": "",
        "reason": "",
        "events": [graph_event(
            "merge_state",
            message_id=message_id,
            state_version=merged.state_version,
            detail=f"round={merged.round_id} status={merged.status}",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )],
    }


def check_missing_node(deps: GraphDeps, state: LogisticsGraphState) -> dict[str, Any]:
    """参数检查节点：算出最小缺口；缺参走追问渲染，齐备走线路匹配。"""
    started = time.perf_counter()
    session: SessionState = state["session"]
    gaps = missing_fields(session)
    message_id = state.get("message_id", "")
    event = graph_event(
        "check_missing",
        message_id=message_id,
        state_version=session.state_version,
        detail=",".join(gaps) if gaps else "complete",
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )
    if not gaps:
        return {
            "missing_fields": [],
            "follow_up": "",
            "action": "",
            "reason": "",
            "events": [event],
        }
    follow_up = follow_up_field(gaps)
    if "地址确认" in gaps and session.address_candidates:
        candidate = next((item for item in session.address_candidates if item.needs_confirmation), None)
        if candidate:
            options = candidate.normalized or "、".join([candidate.raw])
            follow_up = f"您说的是“{options}”吗？请确认地址"
    return {
        "missing_fields": gaps,
        "follow_up": follow_up,
        "action": "reply",
        "reason": "missing_params",
        "events": [event],
    }


def resolve_routes_node(deps: GraphDeps, state: LogisticsGraphState) -> dict[str, Any]:
    """线路查询节点：确定性匹配报价表线路；失败原因进入渲染节点。"""
    started = time.perf_counter()
    settings = deps.settings_store.load(state["cookie_id"])
    session: SessionState = state["session"]
    message_id = state.get("message_id", "")

    def _finish(reason: str, **extra: Any) -> dict[str, Any]:
        updates: dict[str, Any] = {
            "routes": None,
            "book_sha256": "",
            "action": "reply" if reason in _FOLLOW_UP_REASONS else "manual",
            "reason": reason,
            "events": [graph_event(
                "resolve_routes", message_id=message_id, state_version=session.state_version,
                detail=reason, elapsed_ms=(time.perf_counter() - started) * 1000,
            )],
        }
        updates.update(extra)
        return updates

    user_id = deps.db.get_cookie_owner_user(state["cookie_id"])
    if user_id is None:
        return _finish("account_not_found")

    imports = deps.route_service.list_imports(user_id)
    available_ids = [item["id"] for item in imports if item.get("status") == "completed"]
    book_ids = settings.resolved_book_ids(available_ids)
    if not book_ids:
        return _finish("no_rate_book")

    book_sha256 = selected_book_sha(imports, book_ids)
    resolution = RouteResolver(deps.route_service, user_id).resolve(
        session.sender or "", session.receiver or "",
        book_kind_for(session.weight_kg, session.dimensions()), book_ids,
        carrier_filter=session.carrier or None,
    )

    if resolution.ambiguous_city:
        return _finish(
            "ambiguous_city",
            follow_up=f"具体的{resolution.ambiguous_city}所在省份",
            missing_fields=[resolution.ambiguous_city],
        )
    if resolution.route_not_found:
        return _finish("route_not_found")
    if not resolution.matched and resolution.needs_city_carriers:
        return _finish("missing_city", follow_up="收货城市（精确到市）", missing_fields=["收货城市"])

    return {
        "routes": resolution,
        "book_sha256": book_sha256,
        "action": "",
        "reason": "",
        "events": [graph_event(
            "resolve_routes",
            message_id=message_id,
            state_version=session.state_version,
            detail=f"matched={len(resolution.matched)} level={resolution.match_level}",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )],
    }


def call_workflow_node(deps: GraphDeps, state: LogisticsGraphState) -> dict[str, Any]:
    """计费节点：金额只能来自 Workflow；失败不渲染报价。"""
    started = time.perf_counter()
    settings = deps.settings_store.load(state["cookie_id"])
    session: SessionState = state["session"]
    resolution = state["routes"]
    message_id = state.get("message_id", "")

    def _finish(reason: str, error: str = "") -> dict[str, Any]:
        return {
            "quotes": [],
            "action": "manual",
            "reason": reason,
            "events": [graph_event(
                "call_workflow", message_id=message_id, state_version=session.state_version,
                detail=reason, error=error, elapsed_ms=(time.perf_counter() - started) * 1000,
            )],
        }

    try:
        quote_config = build_quote_config(settings, resolution.matched)
        if len(session.packages) > 1:
            # 多包裹统一合并按总重报价：包裹只用于识别与报价前提醒。
            from app.services.logistics_agent.tools import plan_package_quote_mode
            plan = plan_package_quote_mode([package.weight_kg for package in session.packages])
            merged = session.model_copy(deep=True)
            merged.packages = []
            merged.weight_kg = plan["weight_kg"]
            result = call_workflow(build_workflow_input(merged, quote_config))
            result["package_plan"] = plan
        else:
            result = call_workflow(build_workflow_input(session, quote_config))
    except (WorkflowError, WorkflowUnavailable) as exc:
        logger.warning(f"物流 Workflow 调用失败：{exc}")
        return _finish("workflow_failed", error=str(exc))

    if not result.get("success") and not result.get("partial"):
        return _finish(result.get("reason") or "workflow_failed")

    quotes: list[dict[str, Any]] = result.get("quotes", [])
    if not quotes:
        return _finish("route_not_found")

    carriers = ",".join(quote.get("carrier", "") for quote in quotes)
    return {
        "quotes": quotes,
        "package_plan": result.get("package_plan", {}),
        "action": "reply",
        "reason": "quoted",
        "events": [graph_event(
            "call_workflow",
            message_id=message_id,
            state_version=session.state_version,
            detail=f"quotes={len(quotes)} packages={len(session.packages) or 1} carriers={carriers}",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )],
    }


def render_reply_node(deps: GraphDeps, state: LogisticsGraphState) -> dict[str, Any]:
    """回复渲染节点：按 reason 渲染模板，并拦截未解析占位符进入发送文本。"""
    started = time.perf_counter()
    settings = deps.settings_store.load(state["cookie_id"])
    session: SessionState = state["session"].model_copy(deep=True)
    reason = state.get("reason", "")
    messages: list[str]

    if reason in _FOLLOW_UP_REASONS:
        if reason == "missing_params" and not state.get("had_session"):
            template = settings.templates.first_reply
        else:
            template = settings.templates.missing_params
        messages = [render_follow_up(template, state.get("follow_up", "包裹信息"), settings.pricing)]
        action = "reply"
        session.status = SESSION_COLLECTING
    elif reason == "route_not_found":
        if settings.no_route_policy == "silent":
            messages, action = [], "draft"
            session.status = SESSION_FAILED
        else:
            messages = [render_no_route(settings.templates.no_route, session.sender, session.receiver)]
            action = "manual"
            session.status = SESSION_MANUAL
    elif reason == "quoted":
        try:
            messages = _render_quote(settings, state, session)
            notices: list[str] = []
            notice = (state.get("package_plan") or {}).get("notice")
            if notice:
                notices.append(notice)
            provisional = _provisional_matches(state.get("routes"))
            if provisional:
                notices.append(render_provisional_notice(provisional))
            messages = [*notices, *messages]
        except RenderError:
            messages = [render_failure_message(settings.templates.failure)]
            action = "manual"
            reason = "render_failed"
            session.status = SESSION_FAILED
        else:
            action = "reply"
            session.status = SESSION_QUOTED
    else:
        messages = [render_failure_message(settings.templates.failure)]
        action = "manual"
        session.status = SESSION_MANUAL if reason in _MANUAL_REASONS else SESSION_FAILED

    leaked = sorted({token for text in messages for token in unresolved_tokens(text)})
    if leaked:
        # 未解析占位符不允许发送给买家：进入人工处理并记录模板字段名。
        logger.error(f"物流回复模板存在未解析参数 {leaked}，已转人工处理")
        messages = [render_template(settings.templates.failure, {})]
        if unresolved_tokens(messages[0]):
            messages = []
        action = "manual"
        reason = "template_unresolved"
        session.status = SESSION_MANUAL

    # 统一发送闸门（放在占位符闸门之后兜底）：自动发送关闭时，所有消息
    # 类型（报价、追问、失败提示）都只生成草稿，不进入真实发送分支。
    if not settings.auto_send and action in ("reply", "manual"):
        action = "draft"

    return {
        "session": session,
        "rendered_messages": messages,
        "action": action,
        "reason": reason,
        "events": [graph_event(
            "render_reply",
            message_id=state.get("message_id", ""),
            state_version=session.state_version,
            detail=f"action={action} messages={len(messages)}",
            error=reason if reason == "template_unresolved" else "",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )],
    }


def finalize_node(deps: GraphDeps, state: LogisticsGraphState) -> dict[str, Any]:
    """收尾节点：登记消息处理凭据、把 Agent 回复写入消息通道并落审计事件。

    消息处理凭据在这里（图完整跑完）才写入会话状态：中途失败的执行不
    标记消息已处理，同一条消息可以安全重试。
    """
    message_id = state.get("message_id", "")
    rendered = state.get("rendered_messages", [])
    session: SessionState = state.get("session") or SessionState()
    marked = register_processed_message(session, message_id)
    updates: dict[str, Any] = {
        "session": marked,
        "events": [graph_event(
            "finalize",
            message_id=message_id,
            state_version=marked.state_version,
            detail=(
                f"action={state.get('action', '')} reason={state.get('reason', '')} "
                f"book_sha256={state.get('book_sha256', '')[:12]}"
            ),
        )],
    }
    # 所有可行动的失败/人工结果从同一出口发布，避免遗漏分支或重复通知。
    from app.services.logistics_agent.notifications import build_logistics_quote_event

    event = build_logistics_quote_event(
        account_id=state.get("cookie_id", ""),
        message_id=message_id,
        chat_id=state.get("chat_id", ""),
        item_id=state.get("item_id", ""),
        thread_id=state.get("thread_id", ""),
        decision_action=state.get("action", ""),
        reason=state.get("reason", ""),
        mode=state.get("mode", ""),
    )
    if event:
        publisher = deps.notification_publisher
        if publisher is None:
            from app.services.logistics_agent.notifications import publish_logistics_quote_event

            publisher = lambda payload: publish_logistics_quote_event(payload, db=deps.db)
        try:
            updates["notification_result"] = publisher(event)
        except Exception as exc:  # noqa: BLE001 - 通知故障不得阻断报价
            logger.error(f"物流报价事件发布失败：{type(exc).__name__}: {exc}")
    if rendered:
        updates["messages"] = [
            _agent_message(message_id, index, text) for index, text in enumerate(rendered)
        ]
    return updates


def _render_quote(
    settings: AgentSettings,
    state: LogisticsGraphState,
    session: SessionState,
) -> list[str]:
    """用 Workflow 结果构造模板参数并拆分消息（与前端模板语义一致）。"""
    quotes = state.get("quotes", [])
    resolution = state["routes"]
    values = build_quote_values(
        session, quotes, resolution.matched, settings.pricing, settings.recommend_mode,
        settings.carrier_config,
    )
    if not values:
        raise RenderError("报价结果无法构造模板参数")
    remaining = _parse_amount(values.get("补差价", ""))
    parts: list[str] = []
    for template in (
        settings.templates.quote_message,
        settings.templates.diff_positive if remaining > 0 else settings.templates.diff_zero,
        settings.templates.guide_order,
    ):
        parts.extend(split_messages(render_template(template, values)))
    return parts


def _provisional_matches(resolution: Any) -> dict[str, dict[str, Any]]:
    """省级询价里按示例城市预估的匹配渠道（需要向买家注明预估口径）。"""
    matched = getattr(resolution, "matched", None) or {}
    return {carrier: match for carrier, match in matched.items() if match.get("provisional")}


class RenderError(RuntimeError):
    """模板参数构造失败（Workflow 结果不完整等）。"""


def _agent_message(message_id: str, index: int, text: str):
    from langchain_core.messages import AIMessage

    return AIMessage(content=text, id=f"agent-{message_id}-{index}" if message_id else None)


def _parse_amount(text: str) -> float:
    """从渲染后的金额文本解析数字（如 "¥12.30" -> 12.30）。"""
    digits = "".join(character for character in text if character.isdigit() or character == ".")
    try:
        return float(digits) if digits else 0.0
    except ValueError:
        return 0.0
