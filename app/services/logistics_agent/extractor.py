"""物流询价识别：本地预筛 + 模型结构化抽取。

预筛用本地规则判断是否值得调用模型（成本考虑，沿用现有 AI 回复引擎的
本地关键词思路）；命中后才发起结构化抽取，由模型确认意图并解析参数。
"""

from __future__ import annotations

import re

from app.services.logistics_agent.model import (
    ModelCallError,
    ModelNotConfigured,
    build_chat_model,
    extract_structured,
    resolve_model_credentials,
)
from app.services.logistics_agent.models import ExtractedQuote
from app.services.logistics_agent.prompts import (
    EXTRACT_SYSTEM_PROMPT,
    build_extraction_user_prompt,
    summarize_state_for_prompt,
)
from app.services.logistics_agent.settings import AgentSettings
from app.services.logistics_quote_routes.region import PROVINCE_NAMES

# 物流相关关键词：预筛命中才调用模型。
_LOGISTICS_KEYWORDS = (
    "运费", "快递", "物流", "邮费", "寄", "发货", "发货地", "收货", "体积", "重量",
    "公斤", "千克", "到付", "线下", "线上", "计费", "抛比", "首重", "续重",
    "立方", "承运商", "运单", "包裹", "大件",
)

# 数字尺寸：20*30*80 / 20×30×80 / 长20宽30高80（命名形态分隔符可省略）
_DIMS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x×*＊]\s*(\d+(?:\.\d+)?)\s*[x×*＊]\s*(\d+(?:\.\d+)?)"
    r"|长\s*(\d+(?:\.\d+)?)[，,、x×*＊\s]*宽\s*(\d+(?:\.\d+)?)[，,、x×*＊\s]*高\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# 重量：2公斤 / 130kg / 3斤 / 500g / 1.5吨
_WEIGHT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(公斤|千克|kg|KG|Kg|斤|克|g|G|吨)(?![a-zA-Z])"
)

_UNIT_TO_KG = {
    "公斤": 1.0, "千克": 1.0, "kg": 1.0, "斤": 0.5, "克": 0.001, "g": 0.001, "吨": 1000.0,
}


def looks_like_logistics(message: str) -> bool:
    """本地预筛：关键词、尺寸或重量形态、省名命中之一即视为疑似物流询价。"""
    text = (message or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if any(keyword in lowered for keyword in _LOGISTICS_KEYWORDS):
        return True
    if _DIMS_RE.search(text):
        return True
    if _WEIGHT_RE.search(text):
        return True
    for province in PROVINCE_NAMES:
        if province in text or f"{province}省" in text or f"{province}市" in text:
            return True
    return False


def parse_weight_kg(text: str) -> float | None:
    """本地重量解析（kg）；与模型识别互相独立，用于预筛与兜底。"""
    match = _WEIGHT_RE.search(text or "")
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    factor = _UNIT_TO_KG.get(unit, 1.0)
    result = value * factor
    return result if result > 0 else None


def parse_package_weights(text: str) -> list[float]:
    """Parse every explicit weight, preserving message order."""
    weights = []
    for match in _WEIGHT_RE.finditer(text or ""):
        value = float(match.group(1)) * _UNIT_TO_KG.get(match.group(2).lower(), 1.0)
        if value > 0:
            weights.append(value)
    return weights


def extract_fields(model: Any, message: str, state: Any) -> ExtractedQuote:
    """调用模型完成结构化识别；失败抛 ModelCallError / ModelNotConfigured。"""
    user_prompt = build_extraction_user_prompt(message, summarize_state_for_prompt(state))
    return extract_structured(model, EXTRACT_SYSTEM_PROMPT, user_prompt, ExtractedQuote)


def extract_from_model(
    cookie_id: str, settings: AgentSettings, message: str, state: Any
) -> ExtractedQuote:
    """默认识别管线（LangGraph extract 节点的缺省实现）：凭据 → ChatModel → 结构化抽取。"""
    credentials = resolve_model_credentials(cookie_id)
    model = build_chat_model(settings, credentials)
    return extract_fields(model, message, state)


def extract_with_fallback(model: Any, message: str, state: Any) -> ExtractedQuote:
    """模型识别失败时退回本地解析，保证多轮会话不因单次模型故障中断。

    本地兜底只填保守字段（重量/尺寸）；地址文本复杂，交由调用方按缺参追问。
    """
    try:
        return extract_fields(model, message, state)
    except (ModelCallError, ModelNotConfigured):
        dims = parse_dimensions(message)
        weights = parse_package_weights(message)
        from app.services.logistics_agent.models import ExtractedPackage
        return ExtractedQuote(
            intent="logistics_quote",
            weight_kg=weights[0] if len(weights) == 1 else None,
            packages=[ExtractedPackage(package_id=str(index), weight_kg=weight)
                      for index, weight in enumerate(weights, 1)],
            length_cm=dims[0] if dims else None,
            width_cm=dims[1] if dims else None,
            height_cm=dims[2] if dims else None,
            weight_confidence=0.5,
        )


def parse_dimensions(text: str) -> tuple[float, float, float] | None:
    """本地尺寸解析；不完整或非正数时返回 None。"""
    match = _DIMS_RE.search(text or "")
    if not match:
        return None
    numbers = [value for value in match.groups() if value is not None]
    if len(numbers) != 3:
        return None
    values = [float(value) for value in numbers]
    if any(value <= 0 for value in values):
        return None
    return values[0], values[1], values[2]
