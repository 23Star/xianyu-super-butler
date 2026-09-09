"""报价回复渲染：把 Workflow 结果套进店家模板。

金额只允许来自 Workflow 结果（total_price 等），缺参与失败使用预设文案；
{分隔符} 标记把模板拆成多条消息依次发送，与前端模板语义一致。
"""

from __future__ import annotations

import re
from typing import Any

from app.services.logistics_agent.models import SessionState
from app.services.logistics_agent.settings import CarrierPricingConfig, PricingConfig
from app.services.logistics_agent.pricing import calculate_customer_quote

SPLIT_TOKEN = "{分隔符}"

_TOKEN_RE = re.compile(r"\{([^{}]+)\}")

# 与前端 utils/quoteTemplate.ts 的占位提示保持一致的待输入文案
_MISSING = "待买家提供"
_PENDING_PRICE = "待核价"

# 失败模板自身含未解析占位符时的兜底文案（占位符闸门的最后防线）。
_FALLBACK_FAILURE_TEXT = "亲，您的询价已收到，报价暂时算不出来，已通知人工客服为您处理，请稍等哦～"


def format_money(value: float | None) -> str:
    if value is None:
        return _PENDING_PRICE
    return f"¥{value:.2f}"


def format_weight(value: float | None) -> str:
    if value is None:
        return _MISSING
    if float(value).is_integer():
        return f"{int(value)}kg"
    return f"{value:g}kg"


def split_messages(text: str) -> list[str]:
    """按 {分隔符} 拆分模板；空片段丢弃。"""
    parts = [part.strip() for part in (text or "").split(SPLIT_TOKEN)]
    return [part for part in parts if part]


def render_template(template: str, values: dict[str, str]) -> str:
    """渲染 {参数}；未知名保持原样（与前端预览行为一致）。"""
    return _TOKEN_RE.sub(lambda match: values.get(match.group(1).strip(), match.group(0)), template or "")


def build_quote_values(
    state: SessionState,
    quotes: list[dict[str, Any]],
    routes: dict[str, dict[str, Any]],
    pricing: PricingConfig,
    recommend_mode: str = "lowest",
    carrier_config: dict[str, CarrierPricingConfig] | None = None,
) -> dict[str, str]:
    """用真实 Workflow 结果构造模板参数值。"""
    if not quotes:
        return {}
    ordered = sorted(quotes, key=lambda quote: quote.get("total_price", 0))
    chosen = ordered[0]
    carrier = chosen.get("carrier", "")
    match = routes.get(carrier, {})
    origin = match.get("origin") or {}
    destination = match.get("destination") or {}

    dims = [state.length_cm, state.width_cm, state.height_cm]
    has_dims = all(value is not None and value > 0 for value in dims)
    dims_text = "×".join(format_weight(value).replace("kg", "") for value in dims) + "cm" if has_dims else _MISSING
    volume_ratio = chosen.get("volume_ratio")
    volume_weight = None
    volume_formula = None
    if has_dims and volume_ratio:
        volume_weight = dims[0] * dims[1] * dims[2] / volume_ratio
        volume_formula = f"{dims[0]:g}×{dims[1]:g}×{dims[2]:g}cm ÷ {volume_ratio:g} = {volume_weight:.1f}kg"

    lines: list[str] = []
    for quote in ordered:
        quote_match = routes.get(quote.get("carrier", ""), {})
        route_text = _route_text(quote_match, origin, destination)
        config = (carrier_config or {}).get(quote.get("carrier", "")) or CarrierPricingConfig()
        line = render_template(config.quote_line_template, {
            "渠道": quote.get("carrier", ""),
            "运费": f"{quote['total_price']:.2f}".rstrip("0").rstrip("."),
            "计费规则": price_rule_text(quote_match.get("price_model") or {}),
            "计费重量": format_weight(quote.get("chargeable_weight_kg")),
            "线路": route_text,
        })
        package_id = quote.get("package_id")
        lines.append(f"包裹{package_id}：{line}" if package_id else line)
    route_text = _route_text(match, origin, destination)

    freight = float(chosen.get("total_price") or 0)
    customer_quote = calculate_customer_quote(
        freight,
        profit_markup=pricing.profit_markup,
        continued_markup=pricing.continued_markup,
        chargeable_weight_kg=chosen.get("chargeable_weight_kg"),
        coupon_discount=pricing.effective_coupon_discount,
    )
    total = customer_quote.payable
    remaining = total

    return {
        "发货省": state.sender or _MISSING,
        "收货省": state.receiver or _MISSING,
        "重量": format_weight(state.weight_kg),
        "实重": format_weight(state.weight_kg),
        "计费重量": format_weight(chosen.get("chargeable_weight_kg")),
        "体积重": format_weight(volume_weight),
        "体积算式": volume_formula or _MISSING,
        "体积重行": f"体积重：{volume_formula}，取实重与体积重较大值计费" if volume_formula else _MISSING,
        "长宽高": dims_text,
        "渠道报价行": "\n".join(lines) if lines else _PENDING_PRICE,
        "渠道报价提示": "以上为当前报价表实际线路价格，计费重取实重与体积重较大值（按抛比折算）",
        "最优渠道": f"{ordered[0].get('carrier', '')} {format_money(ordered[0].get('total_price'))}",
        "快递总价": format_money(freight),
        "运费": format_money(freight),
        "卡密面值": format_money(customer_quote.coupon_original),
        "券原价": format_money(customer_quote.coupon_original),
        "平台支付面值": format_money(customer_quote.coupon_discount),
        "优惠券抵扣": format_money(customer_quote.coupon_discount),
        "闲鱼已付": format_money(customer_quote.coupon_discount),
        "利润加价": format_money(pricing.profit_markup or None),
        "续重加价": format_money(pricing.continued_markup or None),
        "续重": format_weight(chosen.get("chargeable_weight_kg")),
        "合计": format_money(total),
        "补差价": format_money(remaining),
        "余款": format_money(remaining),
        "默认重量": "1kg" if pricing.default_one_kg else _PENDING_PRICE,
        "线路": route_text,
    }


def price_rule_text(model: dict[str, Any]) -> str:
    """从核价使用的价格模型生成说明，门槛与续重基数保持一致。"""
    tiers = model.get("tiers") or {}
    threshold = max(map(float, tiers)) if tiers else None
    first = model.get("first_weight", 1)
    unit = model.get("continued_unit", 1)
    rate = model.get("continued_weight_price")
    rate_text = f"{rate:g}元/{'kg' if unit == 1 else f'{unit:g}kg'}" if rate is not None else ""
    if threshold is not None:
        prefix = f"{threshold:g}kg内按阶梯价"
        if rate is None:
            return prefix
        if first == threshold:
            return f"{prefix}；超过{threshold:g}kg后，仅超出部分按{rate_text}计费"
        return f"{prefix}；超过{threshold:g}kg后，首重{first:g}kg，续重按{rate_text}计费"
    if model.get("continued_tiers"):
        bands = []
        lower = 0.0
        for upper, price in sorted(model["continued_tiers"].items(), key=lambda item: float(item[0])):
            bands.append(f"{lower:g}至{float(upper):g}kg按{price:g}元/kg")
            lower = float(upper)
        bands.append(f"超过{lower:g}kg按{model['overflow_continued_price']:g}元/kg")
        return f"首重{first:g}kg，续重部分" + "、".join(bands)
    if rate is not None:
        return (f"首重{first:g}kg，" if first != 1 else "") + f"续重{rate_text}"
    if model.get("per_kg_price") is not None:
        return f"最低{model.get('minimum_price', 0):g}元，每公斤{model['per_kg_price']:g}元"
    return "按报价表计费"


def _route_text(match: dict[str, Any], origin: dict[str, str], destination: dict[str, str]) -> str:
    parts_origin = "".join(origin.get(part, "") or "" for part in ("province", "city")) or (
        "".join(match.get("origin", {}).get(part, "") or "" for part in ("province", "city"))
    )
    parts_dest = "".join(destination.get(part, "") or "" for part in ("province", "city")) or (
        "".join(match.get("destination", {}).get(part, "") or "" for part in ("province", "city"))
    )
    return f"{parts_origin}→{parts_dest}"


def render_follow_up(template: str, missing_field: str, pricing: PricingConfig | None = None) -> str:
    """渲染追问模板；追问参数包含 {缺失字段} 与 {默认重量}。

    业务规则固定：default_one_kg 开启时买家可见值为 1kg；关闭时显示待核价
    占位文案而不是把未定义的 {默认重量} 发给买家。
    """
    values = {"缺失字段": missing_field}
    if pricing is not None:
        values["默认重量"] = "1kg" if pricing.default_one_kg else _PENDING_PRICE
    return render_template(template, values)


def unresolved_tokens(text: str) -> list[str]:
    """最终待发送消息里仍未解析的 {参数} 名（{分隔符} 在拆分后不应存在）。"""
    tokens = {
        match.strip()
        for match in _TOKEN_RE.findall(text or "")
        if match.strip() and match.strip() != SPLIT_TOKEN.strip()
    }
    return sorted(tokens)


def render_no_route(template: str, sender: str | None, receiver: str | None) -> str:
    return render_template(template, {"发货省": sender or _MISSING, "收货省": receiver or _MISSING})


def render_failure_message(template: str) -> str:
    """渲染失败模板并执行占位符闸门（异常降级路径与正常路径同一口径）。

    模板里存在未解析 `{参数}` 时不允许进入发送文本，退回内置兜底文案。
    """
    text = render_template(template or "", {})
    if unresolved_tokens(text):
        return _FALLBACK_FAILURE_TEXT
    return text
