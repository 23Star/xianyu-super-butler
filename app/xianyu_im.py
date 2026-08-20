import base64
import json
from typing import Any, Dict, List, Optional

from utils.im_media import binary_data_url, resolve_media


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


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _audio_mime_type(file_type: Any) -> str:
    types = {0: "audio/opus", 1: "audio/ogg", 2: "audio/amr"}
    if isinstance(file_type, str):
        return f"audio/{file_type.lower()}"
    return types.get(file_type, "audio/ogg")


def _empty_content() -> Dict[str, Any]:
    return {"text": "", "images": [], "type": "", "audio": None, "video": None}


def _resolve_url(value: Any, media_host: Optional[str]) -> str:
    return str(resolve_media(value, media_host).get("url") or "")


def make_image_content(image_url: str, width: int = 800, height: int = 600) -> Dict[str, Any]:
    return {
        "contentType": 2,
        "image": {
            "pics": [
                {
                    "height": int(height),
                    "type": 0,
                    "url": image_url,
                    "width": int(width),
                }
            ]
        },
    }


def make_video_content(
    video_url: str,
    width: int = 0,
    height: int = 0,
    duration_ms: int = 0,
    poster: str = "",
) -> Dict[str, Any]:
    video = {
        "url": video_url,
        "width": int(width or 0),
        "height": int(height or 0),
        "duration": int(duration_ms or 0),
        "durationMs": int(duration_ms or 0),
    }
    if poster:
        video["poster"] = poster
        video["coverUrl"] = poster
    return {"contentType": 4, "video": video}


def _interpret_content(
    decoded: Dict[str, Any],
    media_host: Optional[str] = None,
) -> Dict[str, Any]:
    result = _empty_content()
    content_type = decoded.get("contentType")
    if isinstance(content_type, str) and content_type.isdigit():
        content_type = int(content_type)

    text_value = decoded.get("text")
    if content_type == 1 or (text_value is not None and content_type not in (2, 3, 4)):
        if isinstance(text_value, dict):
            result["text"] = str(text_value.get("text", ""))
        else:
            result["text"] = str(text_value or "")
        result["type"] = "text"
        return result

    image = decoded.get("image") or decoded.get("photo")
    if content_type == 2 or isinstance(image, dict):
        pics = image.get("pics", []) if isinstance(image, dict) else []
        images = []
        for pic in pics:
            raw_url = None
            if isinstance(pic, dict):
                raw_url = pic.get("url") or pic.get("mediaId")
            url = _resolve_url(raw_url, media_host)
            if url:
                images.append(url)
        if not images:
            url = _resolve_url(decoded.get("picUrl"), media_host)
            if url:
                images.append(url)
        result["images"] = images
        result["type"] = "image"
        return result

    audio_block = decoded.get("audio")
    if content_type == 3 or isinstance(audio_block, dict):
        if isinstance(audio_block, dict):
            media_value = (
                audio_block.get("url")
                or audio_block.get("audioUrl")
                or audio_block.get("mediaId")
            )
            resource = resolve_media(media_value, media_host)
            audio_url = resource.get("url") or binary_data_url(
                audio_block.get("audioBytes"),
                _audio_mime_type(audio_block.get("fileType") or resource.get("fileType")),
            )
            if audio_url:
                result["audio"] = {
                    "url": audio_url,
                    "durationMs": _optional_int(
                        audio_block.get("durationMs") or audio_block.get("duration")
                    ),
                }
        result["type"] = "audio"
        return result

    video_block = decoded.get("video")
    if content_type == 4 or isinstance(video_block, dict):
        if isinstance(video_block, dict):
            resource = resolve_media(
                video_block.get("url")
                or video_block.get("videoUrl")
                or video_block.get("videoMediaId"),
                media_host,
            )
            poster = resolve_media(
                video_block.get("poster")
                or video_block.get("coverUrl")
                or video_block.get("picMediaId"),
                media_host,
            )
            if resource.get("url"):
                result["video"] = {
                    "url": resource["url"],
                    "poster": poster.get("url") or "",
                    "width": _optional_int(
                        video_block.get("width") or resource.get("width")
                    ),
                    "height": _optional_int(
                        video_block.get("height") or resource.get("height")
                    ),
                    "durationMs": _optional_int(
                        video_block.get("durationMs") or video_block.get("duration")
                    ),
                }
        result["type"] = "video"
        return result

    if decoded.get("title") or decoded.get("template"):
        result["text"] = str(decoded.get("title") or decoded.get("template"))
        result["type"] = "card"
        return result
    return result


def extract_message_summary(
    message: Dict[str, Any],
    media_host: Optional[str] = None,
) -> str:
    content = _as_dict(message.get("content"))
    custom = _as_dict(content.get("custom"))
    summary = custom.get("summary") or custom.get("degrade")
    if summary:
        return str(summary)[:80]
    decoded = _load_content(custom.get("data"))
    if decoded:
        interpreted = _interpret_content(decoded, media_host)
        if interpreted["text"]:
            return interpreted["text"][:80]
        if interpreted["images"] or interpreted["type"] == "image":
            return "[图片]"
        if interpreted["audio"] or interpreted["type"] == "audio":
            return "[语音]"
        if interpreted["video"] or interpreted["type"] == "video":
            return "[视频]"
    return ""


def parse_conversation(
    raw: Dict[str, Any],
    my_id: str,
    media_host: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
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
            "itemImage": _resolve_url(
                extension.get("itemPic")
                or extension.get("itemImage")
                or extension.get("picUrl")
                or "",
                media_host,
            ),
            "lastMessageSummary": extract_message_summary(last_message, media_host),
            "lastMessageId": str(last_message.get("messageId") or ""),
            "lastMessageTime": int(raw.get("modifyTime") or 0),
            "unreadCount": int(raw.get("redPoint") or 0),
        }
    except (TypeError, ValueError):
        return None


def parse_message(
    model: Dict[str, Any],
    my_id: str,
    media_host: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    try:
        message = _as_dict(model.get("message"))
        extension = _as_dict(message.get("extension"))
        sender_id = _strip_domain(extension.get("senderUserId"))
        content = _as_dict(message.get("content"))
        custom = _as_dict(content.get("custom"))
        decoded = _load_content(custom.get("data"))

        text = ""
        images: List[str] = []
        audio = None
        video = None
        message_type = "system"
        if decoded:
            interpreted = _interpret_content(decoded, media_host)
            text = interpreted["text"]
            images = interpreted["images"]
            audio = interpreted["audio"]
            video = interpreted["video"]
            message_type = interpreted["type"] or "system"
        if not text and not images and not audio and not video:
            text = str(custom.get("summary") or custom.get("degrade") or "[系统消息]")
        if not message_type:
            if images:
                message_type = "image"
            elif audio:
                message_type = "audio"
            elif video:
                message_type = "video"
            else:
                message_type = "text"

        return {
            "messageId": str(message.get("messageId") or ""),
            "senderId": sender_id,
            "senderName": str(extension.get("reminderTitle") or ""),
            "isSelf": sender_id == str(my_id),
            "type": message_type,
            "text": text,
            "images": images,
            "audio": audio,
            "video": video,
            "time": int(message.get("createAt") or message.get("time") or 0),
        }
    except (TypeError, ValueError):
        return None
