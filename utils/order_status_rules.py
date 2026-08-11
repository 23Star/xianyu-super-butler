"""Shared order status normalization rules."""

from typing import Any


VALID_ORDER_STATUSES = {
    "processing",
    "pending_ship",
    "shipped",
    "completed",
    "refunding",
    "cancelled",
    "unknown",
}

STATUS_CODE_MAP = {
    "1": "processing",
    "2": "pending_ship",
    "3": "shipped",
    "4": "completed",
    "5": "refunding",
    "6": "cancelled",
    "7": "refunding",
    "8": "cancelled",
    "9": "refunding",
    "10": "cancelled",
    "11": "completed",
    "12": "cancelled",
}

STABLE_ORDER_STATUSES = frozenset({"shipped", "completed", "cancelled"})

STATUS_TEXT_RULES = (
    ("退款成功", "cancelled"),
    ("钱款已原路退返", "cancelled"),
    ("买家取消了订单", "cancelled"),
    ("卖家取消了订单", "cancelled"),
    ("订单已关闭", "cancelled"),
    ("交易关闭", "cancelled"),
    # 卖家端退款列表的状态文案。必须排在「已发货」之前，
    # 否则「已发货退款」会先命中 shipped 而被当成有效订单计入营收。
    ("未发货退款", "refunding"),
    ("已发货退款", "refunding"),
    ("退货退款", "refunding"),
    ("等待卖家处理退款", "refunding"),
    ("退款申请中", "refunding"),
    ("退货退款中", "refunding"),
    ("退款中", "refunding"),
    ("申请退款", "refunding"),
    ("卖家已发货，待买家确认收货", "shipped"),
    ("已发货，待买家确认收货", "shipped"),
    ("待买家确认收货", "shipped"),
    ("卖家已发货", "shipped"),
    ("已发货", "shipped"),
    ("买家已付款，请尽快发货", "pending_ship"),
    ("等待卖家发货", "pending_ship"),
    ("买家已付款", "pending_ship"),
    ("待发货", "pending_ship"),
    ("交易成功", "completed"),
    ("订单完成", "completed"),
    ("交易完成", "completed"),
    ("处理中", "processing"),
)


def detect_order_status_from_text(text: Any) -> str:
    normalized_text = str(text or "").strip()
    for keyword, status in STATUS_TEXT_RULES:
        if keyword in normalized_text:
            return status
    return "unknown"


def normalize_order_status(status_code: Any, status_text: Any = "") -> str:
    normalized_code = str(status_code or "").strip()
    if normalized_code in VALID_ORDER_STATUSES:
        return normalized_code
    if normalized_code in STATUS_CODE_MAP:
        return STATUS_CODE_MAP[normalized_code]
    return detect_order_status_from_text(status_text or normalized_code)


def get_order_status(order: Any) -> str:
    """Read the canonical status while retaining compatibility with old rows."""
    if not isinstance(order, dict):
        return "unknown"
    return normalize_order_status(
        order.get("order_status") or order.get("status") or "unknown"
    )


def is_stable_order_status(status: Any) -> bool:
    return normalize_order_status(status) in STABLE_ORDER_STATUSES
