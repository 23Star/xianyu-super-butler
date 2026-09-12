import json
import re
import time
from typing import Dict, Any, Optional

RECEIVED_FLOWER_MARKERS = ("收到小红花", "received_red_flower")

# 官方卡片/提示的稳定特征：extJson 的 msgArg1 以及消息体的 contentType。
# 14 是 MsgTips（交易提示），25/26/28 是交易、评价、小红花等卡片。
OFFICIAL_CARD_MSG_ARGS = frozenset({"MsgCard", "MsgTips"})
OFFICIAL_CARD_CONTENT_TYPES = frozenset({14, 25, 26, 28})


def _load_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def is_official_card_message(message: Dict[str, Any]) -> bool:
    """判断消息是否为闲鱼官方卡片/提示。

    官方卡片的 senderUserId 是买家（或平台账号）、reminderContent 是卡片标题，
    单看聊天字段和普通买家消息没有区别；稳定的区别在 message['1']['10'] 的
    extJson（msgArg1 为 MsgCard/MsgTips）以及 message['1']['6']['3']['4'] 的
    contentType。这类消息只承载平台状态，不能进入任何回复链路。
    """
    if not isinstance(message, dict):
        return False
    message_1 = message.get("1")
    if not isinstance(message_1, dict):
        return False

    message_10 = message_1.get("10")
    if isinstance(message_10, dict):
        ext_json = _load_json_dict(message_10.get("extJson"))
        if str(ext_json.get("msgArg1") or "") in OFFICIAL_CARD_MSG_ARGS:
            return True

    message_6 = message_1.get("6")
    if isinstance(message_6, dict):
        content = message_6.get("3")
        if isinstance(content, dict):
            try:
                if int(content.get("4")) in OFFICIAL_CARD_CONTENT_TYPES:
                    return True
            except (TypeError, ValueError):
                pass
    return False


def extract_received_flower_order(message: Dict[str, Any]) -> Optional[str]:
    """从「买家赠送小红花」卡片消息里解析订单号。

    闲鱼这张卡片的标题是「你人真不错，送你闲鱼小红花」：既不含「收到小红花」，
    也不带订单号；真正的标识和订单号分别在 message['1']['10'] 的
    bizTag/extJson（taskName 收到小红花-卖家、updateKey ...:received_red_flower）
    以及卡片 targetUrl 的 orderId 参数里。解析不出来时返回 None。
    """
    if not isinstance(message, dict):
        return None
    message_1 = message.get("1")
    if not isinstance(message_1, dict):
        return None

    blob_parts = []
    message_10 = message_1.get("10")
    if isinstance(message_10, dict):
        for key in ("bizTag", "extJson", "reminderContent", "reminderTitle"):
            value = message_10.get(key)
            if value:
                blob_parts.append(str(value))
    message_6 = message_1.get("6")
    if isinstance(message_6, dict) and isinstance(message_6.get("3"), dict):
        for key in ("2", "5"):
            value = message_6["3"].get(key)
            if value:
                blob_parts.append(str(value))
    blob = " ".join(blob_parts)

    looks_received = any(marker in blob for marker in RECEIVED_FLOWER_MARKERS) or (
        "red-flower-play" in blob and "role=seller" in blob
    )
    if not looks_received:
        return None

    for pattern in (r"orderId=(\d{6,24})", r"(\d{6,24}):received_red_flower"):
        match = re.search(pattern, blob)
        if match:
            return match.group(1)

    # 兼容旧版把订单号直接放在提醒文案里的情况
    reminder = str((message_10 or {}).get("reminderContent") or "")
    match = re.search(r"\d{6,24}", reminder)
    return match.group(0) if match else None

def format_message(message_data: Dict[str, Any], is_outgoing: bool = False, is_manual: bool = False) -> str:
    """格式化消息输出"""
    try:
        # 获取消息内容
        content = message_data.get('content', '')
        if not content:
            return ''
            
        # 获取发送时间
        timestamp = message_data.get('time', time.time() * 1000)
        time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp / 1000))
        
        # 确定消息方向
        direction = '【发出】' if is_outgoing else '【收到】'
        if is_manual:
            direction = '【手动发出】'
            
        # 格式化输出
        return f"{time_str} {direction} {content}"
    except Exception as e:
        return f"消息格式化错误: {str(e)}"

def format_system_message(message: str) -> str:
    """格式化系统消息输出"""
    time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    return f"{time_str} 【系统】 {message}" 