"""多轮询价状态合并规则（LangGraph merge_state 节点复用的纯函数）。

状态按 thread 隔离、由 LangGraph checkpointer 持久化；本模块只负责语义：
同一轮询价内的新消息累计合并，明确出现"改成/换成"等修改语义时替换指定
字段，出现新的完整路线时开启新询价轮次。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.logistics_agent.models import (
    SESSION_COLLECTING,
    SESSION_MANUAL,
    SESSION_QUOTED,
    ExtractedQuote,
    SessionState,
)

# 会话过期时间（小时）：超时后的下一条消息视为新询价。
SESSION_TTL_HOURS = 24

# 已完结的状态：再来一条完整询价时开启新一轮而不是继续改旧单。
_FINISHED_STATUSES = {SESSION_QUOTED, SESSION_MANUAL}

# 幂等窗口：保留最近 N 条消息 ID 用于重复判定（同一会话全周期有效，
# 轮次切换不清空）。超出窗口的极旧消息依赖发送记录唯一键兜底，
# 窗口大小即会话内消息处理记录的保留策略。
_RECENT_MESSAGE_LIMIT = 200

_DIMENSION_TARGETS = {"dimensions": ("length_cm", "width_cm", "height_cm")}
_FIELD_TARGETS = {
    "sender": "sender",
    "receiver": "receiver",
    "weight": "weight_kg",
    "dimensions": "dimensions",
}


def merge_state(current: SessionState | None, extracted: ExtractedQuote, message_id: str) -> SessionState:
    """把识别结果合并进会话状态，返回新状态（不修改入参）。

    轮次切换只清空单轮包裹字段；`state_version` 与已处理消息记录
    （`recent_message_ids`/`last_message_id`）是会话级数据，跨轮次单调保留，
    因此同一条消息 ID 在整个会话生命周期内只会被处理一次。消息处理记录
    由 finalize 节点在完整跑完后写入，中途失败的执行不占用幂等凭据。
    """
    state = current.model_copy(deep=True) if current else SessionState()
    if extracted.packages:
        state.packages = extracted.packages
    if extracted.address_candidates:
        state.address_candidates = extracted.address_candidates
    if extracted.unit_issues:
        state.unit_issues = list(dict.fromkeys([*state.unit_issues, *extracted.unit_issues]))
    if state.status in _FINISHED_STATUSES:
        # 上一轮已完结：除非明确修改旧单，否则一律开新一轮。
        if not _is_modification(extracted):
            state = _new_round(state, bump_round=True)

    starts_complete_round = (
        extracted.sender and extracted.receiver and (extracted.weight_kg or _has_dimensions(extracted))
    )
    if extracted.is_new_shipment or (starts_complete_round and state.has_shipment_params()):
        # 新的完整询价：重置包裹参数，避免新旧包裹混算。
        state = _new_round(state, bump_round=state.has_shipment_params())

    targets = {_FIELD_TARGETS.get(target, target) for target in extracted.update_targets}

    if extracted.sender is not None or "sender" in targets:
        state.sender = extracted.sender
    if extracted.receiver is not None or "receiver" in targets:
        state.receiver = extracted.receiver
    if extracted.weight_kg is not None or "weight_kg" in targets:
        state.weight_kg = extracted.weight_kg
    if _has_dimensions(extracted) or "dimensions" in targets:
        for field in _DIMENSION_TARGETS["dimensions"]:
            value = getattr(extracted, field)
            if value is not None or "dimensions" in targets:
                setattr(state, field, value)
    if extracted.quantity and extracted.quantity != 1:
        state.quantity = extracted.quantity
    if extracted.carrier:
        state.carrier = extracted.carrier
    if extracted.payment_mode:
        state.payment_mode = extracted.payment_mode

    state.updated_at = _now_iso()
    state.state_version += 1
    state.status = SESSION_COLLECTING
    return state


def register_processed_message(state: SessionState, message_id: str) -> SessionState:
    """把一条完整处理过的消息登记进幂等记录（finalize 节点专用）。

    处理记录是会话级数据：只在消息完整跑完图后写入，中途失败的执行
    不占用幂等凭据，同一条消息可以安全重试。
    """
    marked = state.model_copy(deep=True)
    if message_id:
        marked.last_message_id = message_id
        marked.recent_message_ids = [
            *marked.recent_message_ids[-(_RECENT_MESSAGE_LIMIT - 1):], message_id,
        ]
    return marked


def _new_round(prev: SessionState, *, bump_round: bool) -> SessionState:
    """开启新一轮询价：只清空单轮包裹字段。

    `state_version`、`round_id` 计数与已处理消息记录跨轮次保留，
    保证版本单调与同一会话内消息 ID 幂等。
    """
    nxt = prev.model_copy(deep=True)
    if bump_round and prev.has_shipment_params():
        nxt.round_id = prev.round_id + 1
    nxt.sender = None
    nxt.receiver = None
    nxt.weight_kg = None
    nxt.length_cm = None
    nxt.width_cm = None
    nxt.height_cm = None
    nxt.quantity = 1
    nxt.carrier = None
    nxt.payment_mode = None
    nxt.packages = []
    nxt.address_candidates = []
    nxt.unit_issues = []
    nxt.status = SESSION_COLLECTING
    return nxt


def missing_fields(state: SessionState) -> list[str]:
    """当前最小缺口，按追问优先级排序（发货地 → 收货地 → 实重/尺寸）。"""
    gaps: list[str] = []
    if any(candidate.needs_confirmation for candidate in state.address_candidates):
        gaps.append("地址确认")
    if not state.sender:
        gaps.append("发货地")
    if not state.receiver:
        gaps.append("收货地")
    if not state.has_weight() and not state.has_complete_dimensions():
        gaps.append("包裹重量或长宽高")
    elif state.has_weight() and _has_partial_dimensions(state):
        # 重量与部分尺寸并存：以实重为准，不再追问缺的尺寸。
        pass
    return gaps


def follow_up_field(gaps: list[str]) -> str:
    """追问文案用的缺口描述（一次只问当前最小缺口）。"""
    return gaps[0] if gaps else "包裹信息"


def is_session_expired(state: SessionState | None) -> bool:
    """正式会话 TTL：过期后的下一条消息按新询价处理（状态归零）。"""
    if state is None:
        return True
    return _is_expired(state.updated_at)


def _is_modification(extracted: ExtractedQuote) -> bool:
    return bool(extracted.update_targets)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_dimensions(extracted: ExtractedQuote) -> bool:
    return all(
        value is not None and value > 0
        for value in (extracted.length_cm, extracted.width_cm, extracted.height_cm)
    )


def _has_partial_dimensions(state: SessionState) -> bool:
    values = [state.length_cm, state.width_cm, state.height_cm]
    return any(value is not None for value in values) and not all(
        value is not None for value in values
    )


def _is_expired(updated_at: str) -> bool:
    if not updated_at:
        return True
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
    return hours > SESSION_TTL_HOURS
