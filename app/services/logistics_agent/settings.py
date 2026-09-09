"""物流 Agent 第五步配置：读写与默认值。

配置按闲鱼账号（cookie_id）保存在服务端，是自动报价运行时的唯一配置来源；
浏览器 localStorage 里的报价设置不参与运行时决策。
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from loguru import logger

DEFAULT_MODEL = "deepseek-v4-flash"
MODEL_CHOICES = ("deepseek-v4-flash", "deepseek-v4-pro")
DEFAULT_QUOTE_LINE_TEMPLATE = "{渠道}：{运费}元（{计费规则}）"


class CarrierPricingConfig(BaseModel):
    """单个承运商的抛比与价格调整；未配置的项使用 Workflow 内置默认。"""

    volume_ratio: float | None = Field(default=None, gt=0)
    markup_cost: float = 0
    markup_manual: float = 0
    discount_rate: float = Field(default=0, ge=0, le=100)
    discount_amount: float = Field(default=0, ge=0)
    quote_line_template: str = Field(default=DEFAULT_QUOTE_LINE_TEMPLATE, max_length=2000)

    @field_validator("quote_line_template")
    @classmethod
    def validate_quote_line_template(cls, value: str) -> str:
        import re

        tokens = set(re.findall(r"\{([^{}]+)\}", value))
        allowed = {"渠道", "运费", "计费规则", "计费重量", "线路"}
        if tokens - allowed:
            raise ValueError(f"渠道报价格式包含未知参数：{'、'.join(sorted(tokens - allowed))}")
        if not {"渠道", "运费"}.issubset(tokens):
            raise ValueError("渠道报价格式必须包含 {渠道} 和 {运费}")
        return value.strip()


class PricingConfig(BaseModel):
    """报价金额构成：报价表券原价 + 自定义加价 - 优惠券抵扣。"""

    card_face_value: float = Field(default=0, ge=0, description="卡密面值，元")
    platform_face_value: float = Field(default=0, ge=0, description="兼容旧配置的优惠券抵扣，元")
    coupon_discount: float | None = Field(default=None, ge=0, description="优惠券抵扣，元")
    profit_markup: float = Field(default=0, ge=0, description="每单利润加价，元")
    continued_markup: float = Field(default=0, ge=0, description="每公斤续重加价，元")
    default_one_kg: bool = True

    @property
    def effective_coupon_discount(self) -> float:
        return self.platform_face_value if self.coupon_discount is None else self.coupon_discount


class ReplyTemplates(BaseModel):
    """回复文案模板，支持 {参数} 占位与 {分隔符} 拆分多条消息。"""

    quote_message: str = (
        "亲，您的运费报价算好啦：\n{渠道报价行}\n{体积重行}\n{渠道报价提示}\n"
        "推荐渠道：{最优渠道}\n包裹信息：{长宽高}，实重 {实重}，计费重 {计费重量}\n"
        "运费 {快递总价}，合计 {合计}，闲鱼已付 {闲鱼已付}，还需补差价 {补差价}哦～"
    )
    diff_positive: str = "拍下后请补差价 {补差价}，客服会发送补差链接，补齐后马上为您安排发货哦～"
    diff_zero: str = "亲，本单平台支付刚好够用，无需补差价，直接拍下就可以啦～"
    guide_order: str = "确认没问题的话，直接拍下并付款哦，客服会第一时间为您安排发货～"
    missing_params: str = "亲，为了给您准确报价，还需要{缺失字段}哦～"
    first_reply: str = (
        "亲，欢迎咨询！本店支持运费自动报价，告诉我发货地、收货地和包裹重量（或长宽高），马上为您算出运费哦～"
    )
    no_route: str = "亲，暂时没有查到 {发货省} 到 {收货省} 的报价线路，已为您转人工客服，请稍等哦～"
    failure: str = "亲，您的询价已收到，报价暂时算不出来，已通知人工客服为您处理，请稍等哦～"

    def to_mapping(self) -> dict[str, str]:
        return self.model_dump()


class AgentSettings(BaseModel):
    """物流 Agent 运行配置（第五步页面读写、服务端持久化）。"""

    enabled: bool = False
    model_name: str = DEFAULT_MODEL
    book_ids: list[int] = Field(default_factory=list, description="生效的线路导入批次；为空时使用全部")
    auto_send: bool = False
    recommend_mode: Literal["lowest", "all"] = "lowest"
    no_route_policy: Literal["manual", "silent"] = "manual"
    item_scope: Literal["all", "custom"] = "all"
    item_ids: list[str] = Field(default_factory=list)
    carrier_config: dict[str, CarrierPricingConfig] = Field(default_factory=dict)
    default_volume_ratios: dict[str, Any] = Field(default_factory=dict)
    pricing: PricingConfig = Field(default_factory=PricingConfig)
    templates: ReplyTemplates = Field(default_factory=ReplyTemplates)

    def covers_item(self, item_id: str) -> bool:
        if self.item_scope != "custom":
            return True
        return bool(item_id) and item_id in set(self.item_ids)

    def resolved_book_ids(self, available_ids: list[int]) -> list[int]:
        """生效批次：显式选择与可用项取交集；未选择时回退为全部可用批次。"""
        if self.book_ids:
            return [book_id for book_id in self.book_ids if book_id in set(available_ids)]
        return list(available_ids)


def normalize_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """前端提交的配置清洗：仅接受已知字段，模型名与策略值收敛到合法集合。"""
    allowed = set(AgentSettings.model_fields)
    cleaned = {key: value for key, value in (payload or {}).items() if key in allowed}
    model_name = cleaned.get("model_name")
    if model_name not in MODEL_CHOICES:
        cleaned["model_name"] = DEFAULT_MODEL
    for field, choices in (
        ("recommend_mode", ("lowest", "all")),
        ("no_route_policy", ("manual", "silent")),
        ("item_scope", ("all", "custom")),
    ):
        if cleaned.get(field) not in choices:
            cleaned[field] = AgentSettings.model_fields[field].default
    return cleaned


class AgentSettingsStore:
    """`logistics_agent_settings` 表读写；每行一个账号。"""

    JSON_FIELDS = ("book_ids", "item_ids", "carrier_config", "default_volume_ratios", "pricing", "templates")

    def __init__(self, db_manager: Any):
        self.db = db_manager

    def exists(self, cookie_id: str) -> bool:
        """该账号是否保存过配置；用于第五步首次进入时从第二/三步带入设置。"""
        with self.db.lock:
            cursor = self.db.conn.execute(
                "SELECT 1 FROM logistics_agent_settings WHERE cookie_id = ?",
                (cookie_id,),
            )
            return cursor.fetchone() is not None

    def load(self, cookie_id: str) -> AgentSettings:
        with self.db.lock:
            cursor = self.db.conn.execute(
                """
                SELECT enabled, model_name, book_ids, auto_send, recommend_mode, no_route_policy,
                       item_scope, item_ids, carrier_config, default_volume_ratios, pricing_config, templates
                FROM logistics_agent_settings WHERE cookie_id = ?
                """,
                (cookie_id,),
            )
            row = cursor.fetchone()
        if not row:
            return AgentSettings()
        try:
            carrier_config = {
                name: CarrierPricingConfig(**value)
                for name, value in _decode(row[8], {}).items()
                if isinstance(value, dict)
            }
            return AgentSettings(
                enabled=bool(row[0]),
                model_name=row[1] if row[1] in MODEL_CHOICES else DEFAULT_MODEL,
                book_ids=[int(value) for value in _decode(row[2], [])],
                auto_send=bool(row[3]),
                recommend_mode=row[4] if row[4] in ("lowest", "all") else "lowest",
                no_route_policy=row[5] if row[5] in ("manual", "silent") else "manual",
                item_scope=row[6] if row[6] in ("all", "custom") else "all",
                item_ids=[str(value) for value in _decode(row[7], [])],
                carrier_config=carrier_config,
                default_volume_ratios=_decode(row[9], {}),
                pricing=PricingConfig(**_decode(row[10], {})),
                templates=ReplyTemplates(**_decode(row[11], {})),
            )
        except Exception as exc:
            logger.warning(f"物流 Agent 设置解析失败，账号 {cookie_id} 使用默认配置：{exc}")
            return AgentSettings()

    def save(self, cookie_id: str, settings: AgentSettings) -> bool:
        try:
            with self.db.lock:
                self.db.conn.execute(
                    """
                    INSERT INTO logistics_agent_settings (
                        cookie_id, enabled, model_name, book_ids, auto_send, recommend_mode,
                        no_route_policy, item_scope, item_ids, carrier_config,
                        default_volume_ratios, pricing_config, templates, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(cookie_id) DO UPDATE SET
                        enabled = excluded.enabled,
                        model_name = excluded.model_name,
                        book_ids = excluded.book_ids,
                        auto_send = excluded.auto_send,
                        recommend_mode = excluded.recommend_mode,
                        no_route_policy = excluded.no_route_policy,
                        item_scope = excluded.item_scope,
                        item_ids = excluded.item_ids,
                        carrier_config = excluded.carrier_config,
                        default_volume_ratios = excluded.default_volume_ratios,
                        pricing_config = excluded.pricing_config,
                        templates = excluded.templates,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        cookie_id,
                        int(settings.enabled),
                        settings.model_name,
                        json.dumps(settings.book_ids),
                        int(settings.auto_send),
                        settings.recommend_mode,
                        settings.no_route_policy,
                        settings.item_scope,
                        json.dumps(settings.item_ids),
                        json.dumps(
                            {name: config.model_dump() for name, config in settings.carrier_config.items()},
                            ensure_ascii=False,
                        ),
                        json.dumps(settings.default_volume_ratios, ensure_ascii=False),
                        json.dumps(settings.pricing.model_dump(), ensure_ascii=False),
                        json.dumps(settings.templates.to_mapping(), ensure_ascii=False),
                    ),
                )
                self.db.conn.commit()
            return True
        except Exception as exc:
            logger.error(f"保存物流 Agent 设置失败 {cookie_id}: {exc}")
            return False


def _decode(value: Any, default: Any) -> Any:
    if isinstance(value, dict | list):
        return value
    if value in (None, ""):
        return default
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return default
    return decoded if isinstance(decoded, type(default)) else default
