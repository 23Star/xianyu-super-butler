import base64
import json
from typing import Any, Dict, List, Optional, Tuple


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
    return {}


def _strip_domain(value: Any) -> str:
    return str(value or "").split("@", 1)[0]


# 闲鱼的会话接口不返回买家头像（avatar / avatarUrl / senderAvatar 都是空），
# 会话列表里就会是一片灰色占位。用 DiceBear 按用户 ID 生成确定性头像补上：
# 同一个买家每次都是同一张图，便于在列表里区分。
DICEBEAR_STYLE = "thumbs"
DICEBEAR_ENDPOINT = f"https://api.dicebear.com/9.x/{DICEBEAR_STYLE}/svg"


def make_avatar_url(seed: Any) -> str:
    """按 seed 生成确定性的占位头像地址，seed 为空时返回空串。

    走的是第三方服务，图片由浏览器直接请求；网络不通时前端会回落到首字母占位。
    """
    from urllib.parse import quote

    key = str(seed or "").strip()
    if not key:
        return ""
    return f"{DICEBEAR_ENDPOINT}?seed={quote(key, safe='')}"


def _load_content(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, json.JSONDecodeError):
        pass
    try:
        parsed = json.loads(base64.b64decode(raw).decode("utf-8"))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _interpret_content(decoded: Dict[str, Any]) -> Tuple[str, List[str], str]:
    content_type = decoded.get("contentType")
    text_value = decoded.get("text")
    if content_type == 1 or text_value is not None:
        if isinstance(text_value, dict):
            return str(text_value.get("text", "")), [], "text"
        return str(text_value or ""), [], "text"

    image = decoded.get("image")
    if content_type == 2 or isinstance(image, dict):
        pics = image.get("pics", []) if isinstance(image, dict) else []
        images = [
            str(pic.get("url"))
            for pic in pics
            if isinstance(pic, dict) and pic.get("url")
        ]
        legacy_url = decoded.get("picUrl")
        if legacy_url and not images:
            images.append(str(legacy_url))
        return "", images, "image"

    if content_type == 3 or decoded.get("audio"):
        return "[语音消息]", [], "system"

    if decoded.get("title") or decoded.get("template"):
        return str(decoded.get("title") or decoded.get("template")), [], "card"
    return "", [], ""


def extract_message_summary(message: Dict[str, Any]) -> str:
    content = _as_dict(message.get("content"))
    custom = _as_dict(content.get("custom"))
    summary = custom.get("summary") or custom.get("degrade")
    if summary:
        return str(summary)[:80]
    decoded = _load_content(custom.get("data"))
    if decoded:
        text, images, msg_type = _interpret_content(decoded)
        if text:
            return text[:80]
        if images or msg_type == "image":
            return "[图片]"
    return ""


def parse_conversation(raw: Dict[str, Any], my_id: str) -> Optional[Dict[str, Any]]:
    try:
        conversation = _as_dict(raw.get("singleChatConversation"))
        raw_cid = str(conversation.get("cid") or "")
        cid = _strip_domain(raw_cid)
        if not cid:
            return None

        first = _strip_domain(conversation.get("pairFirst"))
        second = _strip_domain(conversation.get("pairSecond"))
        other_id = second if first == str(my_id) else first
        if not other_id or other_id == "0":
            return None

        extension = _as_dict(conversation.get("extension"))
        last_message_wrapper = _as_dict(raw.get("lastMessage"))
        last_message = _as_dict(last_message_wrapper.get("message"))
        last_extension = _as_dict(last_message.get("extension"))
        sender_id = _strip_domain(last_extension.get("senderUserId"))
        sender_name = str(last_extension.get("reminderTitle") or "")
        if sender_id != other_id or sender_name.isdigit():
            sender_name = ""

        # reminderTitle 经常缺失或是纯数字，再从消息体里找一次昵称，
        # 否则会话列表只能显示「闲鱼用户 123456」。
        if not sender_name and sender_id == other_id:
            for candidate in (
                last_extension.get("senderNick"),
                last_extension.get("senderNickName"),
                last_message_wrapper.get("senderNick"),
            ):
                text = str(candidate or "").strip()
                if text and not text.isdigit():
                    sender_name = text
                    break

        return {
            "cid": cid,
            "rawCid": raw_cid,
            "otherUserId": other_id,
            "otherUserName": sender_name,
            "otherUserAvatar": str(
                extension.get("avatar")
                or extension.get("avatarUrl")
                or last_extension.get("senderAvatar")
                or make_avatar_url(other_id)
            ),
            "itemId": str(extension.get("itemId") or ""),
            "itemTitle": str(extension.get("itemTitle") or ""),
            "itemImage": str(
                extension.get("itemPic")
                or extension.get("itemImage")
                or extension.get("picUrl")
                or ""
            ),
            "lastMessageSummary": extract_message_summary(last_message),
            "lastMessageTime": int(raw.get("modifyTime") or 0),
            "unreadCount": int(raw.get("redPoint") or 0),
        }
    except (TypeError, ValueError):
        return None


def parse_message(model: Dict[str, Any], my_id: str) -> Optional[Dict[str, Any]]:
    try:
        message = _as_dict(model.get("message"))
        extension = _as_dict(message.get("extension"))
        sender_id = _strip_domain(extension.get("senderUserId"))
        content = _as_dict(message.get("content"))
        custom = _as_dict(content.get("custom"))
        decoded = _load_content(custom.get("data"))

        text = ""
        images: List[str] = []
        message_type = "system"
        if decoded:
            text, images, message_type = _interpret_content(decoded)
        if not text and not images:
            text = str(custom.get("summary") or custom.get("degrade") or "[系统消息]")
        if not message_type:
            message_type = "image" if images else "text"

        return {
            "messageId": str(message.get("messageId") or ""),
            "senderId": sender_id,
            "senderName": str(extension.get("reminderTitle") or ""),
            "isSelf": sender_id == str(my_id),
            "type": message_type,
            "text": text,
            "images": images,
            "time": int(message.get("createAt") or message.get("time") or 0),
        }
    except (TypeError, ValueError):
        return None
