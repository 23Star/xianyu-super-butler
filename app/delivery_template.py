"""卡密发货文案：参数渲染、图片嵌入与分开发送。

与报价回复文案共用 ``{分隔符}`` 语义：渲染后按标记拆成多条消息依次发送，
不合并成一条。``{图片N}`` 标记配合卡密保存的图片映射，在发送时替换为真实
图片消息，卖家不需要在文案里维护图片 URL。

序列化格式沿用历史 ``__IMAGE_SEND__`` 协议，多段之间用 ``\\x1e`` 分隔，
这样发送侧既能识别纯文本、单张图片，也能识别新的多段内容。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Mapping, Optional

from loguru import logger

# 与前端 utils/messageTemplate.ts、报价文案保持同一分隔符语义。
SPLIT_TOKEN = "{分隔符}"
IMAGE_TOKEN_PREFIX = "图片"

SEGMENT_SEPARATOR = "\x1e"
IMAGE_MARKER_PREFIX = "__IMAGE_SEND__"

# 单段文本消息的最大字符数。闲鱼 IM 对长文本的容忍度有限，
# 超长内容一次性发送容易被截断或吞掉，500 字符是保守值。
MAX_SEGMENT_CHARS = 500

# 模板里能代表卡密内容本身的参数；渲染前用它判断文案是否漏插卡密。
CONTENT_TOKENS = ("发货内容", "DELIVERY_CONTENT")

_TOKEN_RE = re.compile(r"\{([^{}]+)\}")
_MARKER_RE = re.compile(r"\{图片(\d+)\}|\{分隔符\}")


def _card_value(rule: Mapping[str, Any], name: str) -> Any:
    """发货规则里的卡密字段统一带 card_ 前缀，这里兼容两种取法。"""
    if not rule:
        return None
    prefixed = f"card_{name}"
    if prefixed in rule:
        return rule.get(prefixed)
    return rule.get(name)


def is_template_enabled(rule: Mapping[str, Any]) -> bool:
    """卡密的发货文案开关是否生效（开关打开且文案非空）。"""
    if not rule:
        return False
    return bool(_card_value(rule, "delivery_template_enabled")) and bool(
        str(_card_value(rule, "delivery_template") or "").strip()
    )


def normalize_images(images: Any) -> Dict[str, str]:
    """把模板图片配置规范化为 ``{"1": "url"}``；键兼容 ``图片1`` 写法。"""
    if not images:
        return {}
    if isinstance(images, str):
        try:
            images = json.loads(images)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    if not isinstance(images, Mapping):
        return {}

    normalized: Dict[str, str] = {}
    for key, value in images.items():
        token = str(key or "").strip()
        url = str(value or "").strip()
        if not token or not url:
            continue
        if token.startswith(IMAGE_TOKEN_PREFIX):
            token = token[len(IMAGE_TOKEN_PREFIX):]
        if not token.isdigit():
            continue
        normalized[token] = url
    return normalized


def render_template(template: str, values: Mapping[str, str]) -> str:
    """渲染 ``{参数}``；未知名保持原样，与报价文案预览行为一致。"""
    return _TOKEN_RE.sub(
        lambda match: values.get(match.group(1).strip(), match.group(0)),
        template or "",
    )


def _flush_text(segments: List[Dict[str, Any]], buffer: List[str]) -> None:
    text = "".join(buffer).strip()
    buffer.clear()
    if text:
        segments.append({"type": "text", "content": text})


def build_segments(rendered: str, images: Any = None) -> List[Dict[str, Any]]:
    """把渲染后的文案拆成文本/图片/分条段落。"""
    image_map = normalize_images(images)
    segments: List[Dict[str, Any]] = []
    buffer: List[str] = []
    position = 0

    for match in _MARKER_RE.finditer(rendered or ""):
        buffer.append((rendered or "")[position:match.start()])
        position = match.end()

        if match.group(0) == SPLIT_TOKEN:
            _flush_text(segments, buffer)
            continue

        # 图片标记：映射缺失时保留原文，避免静默吞掉卖家写下的标记。
        key = match.group(1)
        url = image_map.get(key) or image_map.get(f"{IMAGE_TOKEN_PREFIX}{key}")
        if url:
            _flush_text(segments, buffer)
            segments.append({"type": "image", "url": url, "card_id": None})
        else:
            buffer.append(match.group(0))

    buffer.append((rendered or "")[position:])
    _flush_text(segments, buffer)
    return segments


def serialize_segments(segments: List[Dict[str, Any]]) -> str:
    """序列化为发送侧可解析的单字符串。"""
    parts: List[str] = []
    for segment in segments:
        if segment.get("type") == "image":
            parts.append(f"{IMAGE_MARKER_PREFIX}{segment.get('url') or ''}")
        else:
            text = str(segment.get("content") or "")
            if text:
                parts.append(text)
    return SEGMENT_SEPARATOR.join(parts)


def parse_segments(payload: str) -> List[Dict[str, Any]]:
    """解析发货内容，兼容历史单条文本与 ``__IMAGE_SEND__`` 图片标记。"""
    if not payload:
        return []

    raw_parts = (
        payload.split(SEGMENT_SEPARATOR)
        if SEGMENT_SEPARATOR in payload
        else [payload]
    )

    segments: List[Dict[str, Any]] = []
    for part in raw_parts:
        if part.startswith(IMAGE_MARKER_PREFIX):
            image_data = part[len(IMAGE_MARKER_PREFIX):]
            card_id: Optional[int] = None
            if "|" in image_data:
                card_id_text, image_url = image_data.split("|", 1)
                try:
                    card_id = int(card_id_text)
                except ValueError:
                    card_id = None
            else:
                image_url = image_data
            if image_url:
                segments.append({"type": "image", "url": image_url, "card_id": card_id})
            continue
        if part.strip():
            segments.append({"type": "text", "content": part})
    return segments


def split_delivery_content(content: str, max_chars: int = MAX_SEGMENT_CHARS) -> list[str]:
    """按最大长度切分文本，优先在换行处断开，避免把一行卡密从中间切断。"""
    text = (content or "").strip()
    if not text:
        return []

    segments: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        cut = remaining.rfind("\n", 0, max_chars)
        if cut <= 0:
            # 没有可用的换行边界（单行超长），退化为硬切
            cut = max_chars
        segments.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        segments.append(remaining)
    return segments


def build_card_delivery_payload(
    rule: Mapping[str, Any],
    delivery_content: str,
    *,
    order_id: str = None,
    item_id: str = None,
    buyer_id: str = None,
    item_title: str = None,
    spec_name: str = None,
    spec_value: str = None,
    quantity: int = None,
) -> str:
    """按卡密发货文案渲染最终发货内容。"""
    template = str(_card_value(rule, "delivery_template") or "").strip()
    values = {
        "发货内容": delivery_content or "",
        # 兼容旧备注里的英文变量写法。
        "DELIVERY_CONTENT": delivery_content or "",
        "订单号": order_id or "",
        "商品ID": item_id or "",
        "商品标题": item_title or "",
        "买家ID": buyer_id or "",
        "规格名称": spec_name or "",
        "规格值": spec_value or "",
        "发货数量": str(quantity) if quantity else "",
    }

    rendered = render_template(template, values)
    if not any(token in template for token in CONTENT_TOKENS):
        # 漏插卡密时补在末尾：发货文案写错不该让买家收不到卡密。
        logger.warning(
            f"发货文案未包含 {CONTENT_TOKENS[0]} 参数，已自动追加卡密内容: "
            f"卡密ID={rule.get('card_id')}"
        )
        rendered = f"{rendered}\n\n{delivery_content}" if rendered else (delivery_content or "")

    images = _card_value(rule, "delivery_template_images")
    return serialize_segments(build_segments(rendered, images))


async def send_payload(
    live: Any,
    websocket: Any,
    chat_id: Any,
    buyer_id: Any,
    payload: str,
    *,
    interval: float = 1.0,
) -> int:
    """把一段发货内容按段落依次发送，返回实际发送的消息条数。

    超长文本段在发送前按 IM 安全长度再细分，避免一次性发送被截断或吞掉。
    """
    segments = parse_segments(payload)
    if not segments:
        raise ValueError("发货文案为空，未生成可发送内容")

    # 先展开成实际发送序列：图片一段一条，文本段按安全长度细分。
    outgoing: List[Dict[str, Any]] = []
    for segment in segments:
        if segment.get("type") == "image":
            outgoing.append(segment)
        else:
            outgoing.extend(
                {"type": "text", "content": part}
                for part in split_delivery_content(segment["content"])
            )

    for index, message in enumerate(outgoing):
        if message.get("type") == "image":
            await live.send_image_msg(
                websocket,
                chat_id,
                buyer_id,
                message["url"],
                card_id=message.get("card_id"),
            )
        else:
            await live.send_msg(websocket, chat_id, buyer_id, message["content"])

        if interval and index < len(outgoing) - 1:
            await asyncio.sleep(interval)

    return len(outgoing)
