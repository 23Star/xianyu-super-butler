"""物流报价 Agent 数据模型。

识别结果、会话状态与对外决策的 Pydantic 契约。模型输出必须经过这里的
校验才会进入业务流程；金额永远不出现在识别结果里，只来自 Workflow。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

INTENT_LOGISTICS = "logistics_quote"
INTENT_OTHER = "other"

# 会话状态机：收集参数 → 参数齐备 → 已报价 / 失败 / 转人工
SESSION_COLLECTING = "collecting"
SESSION_READY = "ready"
SESSION_QUOTED = "quoted"
SESSION_FAILED = "failed"
SESSION_MANUAL = "manual"


class ExtractedQuote(BaseModel):
    """模型对单条买家消息的结构化识别结果（计划 8.1 契约的扁平形态）。"""

    intent: Literal["logistics_quote", "other"] = INTENT_OTHER
    sender: str | None = Field(default=None, description="发货地原文，如：江西省赣州市")
    sender_confidence: float = Field(default=0.0, ge=0, le=1)
    receiver: str | None = Field(default=None, description="收货地原文，如：河北省")
    receiver_confidence: float = Field(default=0.0, ge=0, le=1)
    weight_kg: float | None = Field(default=None, gt=0, description="实重，统一公斤")
    weight_confidence: float = Field(default=0.0, ge=0, le=1)
    length_cm: float | None = Field(default=None, gt=0)
    width_cm: float | None = Field(default=None, gt=0)
    height_cm: float | None = Field(default=None, gt=0)
    quantity: int = Field(default=1, ge=1)
    carrier: str | None = Field(default=None, description="买家点名的承运商，可空")
    payment_mode: Literal["offline", "online"] | None = None
    is_new_shipment: bool = Field(default=False, description="买家开启了新的询价")
    update_targets: list[str] = Field(
        default_factory=list,
        description='本条消息明确修改的字段：sender/receiver/weight/dimensions',
    )
    notes: str | None = None
    packages: list["ExtractedPackage"] = Field(default_factory=list, description="同一消息中的多个包裹")
    address_candidates: list["AddressCandidate"] = Field(default_factory=list)
    unit_issues: list[str] = Field(default_factory=list)


class ExtractedPackage(BaseModel):
    """单个包裹的识别结果；缺失字段保持为空，禁止猜测。"""

    package_id: str = ""
    weight_kg: float | None = Field(default=None, gt=0)
    length_cm: float | None = Field(default=None, gt=0)
    width_cm: float | None = Field(default=None, gt=0)
    height_cm: float | None = Field(default=None, gt=0)
    quantity: int = Field(default=1, ge=1)
    unit_issues: list[str] = Field(default_factory=list)


class AddressCandidate(BaseModel):
    field: Literal["sender", "receiver"]
    raw: str
    normalized: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    needs_confirmation: bool = True


class SessionState(BaseModel):
    """按 cookie + 会话 + 商品隔离的多轮询价状态（计划 8.2 契约）。"""

    sender: str | None = None
    receiver: str | None = None
    weight_kg: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    quantity: int = 1
    carrier: str | None = None
    payment_mode: Literal["offline", "online"] | None = None
    last_message_id: str = ""
    # 会话级幂等记录：跨轮次保留，只保留最近 N 条（保留策略见 state._RECENT_MESSAGE_LIMIT）。
    recent_message_ids: list[str] = Field(default_factory=list)
    updated_at: str = ""
    state_version: int = 1
    round_id: int = 1
    status: str = SESSION_COLLECTING
    packages: list[ExtractedPackage] = Field(default_factory=list)
    address_candidates: list[AddressCandidate] = Field(default_factory=list)
    unit_issues: list[str] = Field(default_factory=list)

    def dimensions(self) -> list[float | None]:
        return [self.length_cm, self.width_cm, self.height_cm]

    def has_processed_message(self, message_id: str) -> bool:
        """同一条消息是否已由 Agent 处理过（幂等：不重复推进状态）。"""
        if not message_id:
            return False
        return message_id in set(self.recent_message_ids) or message_id == self.last_message_id

    def has_complete_dimensions(self) -> bool:
        return all(value is not None and value > 0 for value in self.dimensions())

    def has_weight(self) -> bool:
        return self.weight_kg is not None and self.weight_kg > 0

    def has_shipment_params(self) -> bool:
        """是否已经有任何包裹参数（用于判断会话是否有效延续）。"""
        return bool(self.sender or self.receiver or self.has_weight() or self.has_complete_dimensions())


class RouteMatchSummary(BaseModel):
    """一条命中线路的摘要（用于决策展示与审计）。"""

    carrier: str
    match_level: str
    match_level_label: str
    origin: dict[str, str] = Field(default_factory=dict)
    destination: dict[str, str] = Field(default_factory=dict)
    price_model: dict[str, Any] = Field(default_factory=dict)


class AgentDecision(BaseModel):
    """Agent 对外决策：回复消息、草稿、转人工或忽略。

    action 含义（所有买家可见消息的发送闸门由 AgentSettings.auto_send 统一决定）：
    - reply：产生了待发送文本，调用方发送前还需通过 claim_send 版本校验。
    - manual：失败提示/转人工文案，调用方按发送流程处理（同样受发送闸门约束）。
    - draft：自动发送关闭，只记录草稿，不发送、不回退到通用 AI。
    - ignore：非物流消息，调用方继续走原有回复链路。
    """

    action: Literal["reply", "draft", "manual", "ignore"] = "ignore"
    messages: list[str] = Field(default_factory=list)
    reason: str = ""
    intent: str = INTENT_OTHER
    fields: dict[str, Any] = Field(default_factory=dict)
    routes: list[RouteMatchSummary] = Field(default_factory=list)
    quotes: list[dict[str, Any]] = Field(default_factory=list)
    channel_results: list[dict[str, Any]] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    state_version: int = 0
    book_sha256: str = ""
    session_status: str = ""
