"""卖出订单同步：把卖家端接口的数据落到 orders 表。

数据来源有两个，互为补充：

- ``merchant.sold.get``：订单列表，字段最全（含成交额和收货信息），但服务端
  只保留近期订单。实测账号在订单管理页也只显示这批，与接口返回一致。
- ``merchant.refund.list``：退款列表，能返回订单列表已经查不到的历史归档单，
  但没有收货信息，成交额只能按单价乘件数估算。

订单列表的数据优先，退款列表只用来补全订单列表缺失的单。
"""

from typing import Any, Dict, Optional

from loguru import logger

from utils.order_status_rules import normalize_order_status
from utils.xianyu_seller_api import (
    SellerApiError,
    XianyuSellerAPI,
    parse_consign_render,
    parse_refund_order,
    parse_sold_order,
)


def _save_order(db_manager, cookie_id: str, parsed: Dict[str, Any]) -> bool:
    """把解析后的订单写入数据库。"""
    order_id = parsed.get("order_id")
    if not order_id:
        return False

    return db_manager.insert_or_update_order(
        order_id=order_id,
        item_id=parsed.get("item_id") or None,
        buyer_id=parsed.get("buyer_id") or None,
        quantity=str(parsed.get("buy_num") or 1),
        amount=parsed.get("amount") or None,
        order_status=normalize_order_status("", parsed.get("status_text")),
        cookie_id=cookie_id,
        created_at=parsed.get("created_at") or None,
        receiver_name=parsed.get("receiver_name") or None,
        receiver_phone=parsed.get("receiver_phone") or None,
        receiver_address=parsed.get("receiver_address") or None,
        buy_num=parsed.get("buy_num"),
        auction_price=parsed.get("auction_price") or None,
        confirm_fee=parsed.get("confirm_fee") or None,
        refund_fee=parsed.get("refund_fee") or None,
        post_fee=parsed.get("post_fee") or None,
    )


async def fetch_order_detail_direct(
    cookie_id: str,
    cookies_str: str,
    order_id: str,
) -> Optional[Dict[str, Any]]:
    """直连获取单个订单的完整详情，返回结构兼容浏览器抓取的结果。

    组合两个接口：``sold.get`` 给出成交额和状态，``consign.page.render``
    给出规格 —— 后者是规格的唯一来源，订单列表的 itemInfoLines 是空的。

    自动发货依赖规格来决定发哪个卡密，因此两个接口都要调；任一失败时返回
    已获取的部分，由调用方决定是否回退到浏览器抓取。

    Returns:
        字段与 ``utils.order_detail_fetcher.fetch_order_detail_simple`` 对齐；
        完全拿不到数据时返回 None。
    """
    if not order_id or not cookies_str:
        return None

    api = XianyuSellerAPI(cookie_id, cookies_str)
    result: Dict[str, Any] = {}
    try:
        # 成交额、状态、买家和收货信息
        try:
            batch = await api.get_sold_orders(order_ids=str(order_id), rows_per_page=10)
            for item in batch.get("items") or []:
                parsed = parse_sold_order(item)
                if parsed.get("order_id") == str(order_id):
                    result.update(parsed)
                    break
        except SellerApiError as exc:
            logger.debug(f"【{cookie_id}】订单 {order_id} 列表查询失败: {exc}")

        # 规格信息只能从发货页渲染接口拿
        try:
            render = parse_consign_render(await api.get_consign_render(order_id))
            for key in (
                "spec_name",
                "spec_value",
                "need_serial_number",
                "need_upload_report",
                "support_consign_type",
            ):
                if render.get(key) not in (None, "", []):
                    result[key] = render[key]
            # 列表接口缺字段时用渲染接口补齐
            for key in (
                "item_id",
                "item_title",
                "receiver_name",
                "receiver_phone",
                "receiver_address",
                "auction_price",
            ):
                if not result.get(key) and render.get(key):
                    result[key] = render[key]
            if not result.get("buy_num"):
                result["buy_num"] = render.get("buy_num") or 1
        except SellerApiError as exc:
            logger.debug(f"【{cookie_id}】订单 {order_id} 发货页渲染失败: {exc}")
    except Exception as e:
        logger.warning(f"【{cookie_id}】订单 {order_id} 直连获取异常: {e}")
    finally:
        await api.close()

    if not result:
        return None

    result.setdefault("order_id", str(order_id))
    result["url"] = (
        f"https://www.goofish.com/order-detail?orderId={order_id}&role=seller"
    )
    result["title"] = f"订单详情 - {order_id}"
    result["quantity"] = str(result.get("buy_num") or 1)
    result["order_time"] = result.get("created_at") or ""
    result["order_status"] = normalize_order_status("", result.get("status_text"))
    result["from_seller_api"] = True
    return result


async def sync_account_orders(
    cookie_id: str,
    cookies_str: str,
    include_refund_history: bool = True,
) -> Dict[str, Any]:
    """同步单个账号的全部卖出订单。

    不按时间范围筛选 —— 服务端本身只保留近期订单，加时间条件反而会把边界上的
    订单切掉（例如账号最早一单正好落在 30 天前后）。

    Args:
        include_refund_history: 是否用退款列表补全历史归档订单。

    Returns:
        ``{"total", "saved", "failed", "from_refund", "expected", "complete", "cookies_str"}``。
        ``complete`` 为 False 表示拉取数量少于服务端角标，调用方应关注。
    """
    result: Dict[str, Any] = {
        "total": 0,
        "saved": 0,
        "failed": 0,
        "from_refund": 0,
        "expected": None,
        "complete": True,
        "cookies_str": cookies_str,
    }
    if not cookies_str:
        return result

    from app.db_manager import db_manager

    api = XianyuSellerAPI(cookie_id, cookies_str)
    try:
        # 服务端角标是订单总数的权威值，用来判断是否拉全
        expected = await api.get_expected_order_total()
        result["expected"] = expected

        try:
            items = await api.iter_sold_orders(rows_per_page=50)
        except SellerApiError as exc:
            logger.warning(f"【{cookie_id}】卖出订单拉取失败: {exc}")
            items = []

        seen = set()
        for item in items:
            parsed = parse_sold_order(item)
            order_id = parsed.get("order_id")
            if not order_id:
                continue
            seen.add(order_id)
            try:
                ok = _save_order(db_manager, cookie_id, parsed)
                result["saved"] += 1 if ok else 0
                result["failed"] += 0 if ok else 1
            except Exception as e:
                result["failed"] += 1
                logger.error(f"【{cookie_id}】保存卖出订单失败 {order_id}: {e}")

        result["total"] = len(seen)

        if expected is not None and len(seen) < expected:
            result["complete"] = False
            logger.warning(
                f"【{cookie_id}】卖出订单可能未拉全: 已获取 {len(seen)} 单，"
                f"服务端角标为 {expected} 单"
            )

        # 补全订单列表已查不到的历史归档单
        if include_refund_history:
            try:
                refunds = await api.iter_refund_orders(rows_per_page=50)
            except SellerApiError as exc:
                logger.warning(f"【{cookie_id}】退款单拉取失败: {exc}")
                refunds = []

            for item in refunds:
                parsed = parse_refund_order(item)
                order_id = parsed.get("order_id")
                if not order_id or order_id in seen:
                    continue
                seen.add(order_id)
                try:
                    ok = _save_order(db_manager, cookie_id, parsed)
                    if ok:
                        result["saved"] += 1
                        result["from_refund"] += 1
                    else:
                        result["failed"] += 1
                except Exception as e:
                    result["failed"] += 1
                    logger.error(f"【{cookie_id}】保存历史退款单失败 {order_id}: {e}")

            result["total"] = len(seen)

        # 接口会下发新的签名令牌，回传给调用方以便同步到账号会话
        result["cookies_str"] = api.cookies_str
    except Exception as e:
        logger.error(f"【{cookie_id}】卖出订单同步异常: {e}")
    finally:
        await api.close()

    logger.info(
        f"【{cookie_id}】卖出订单同步完成: 共 {result['total']} 单"
        f"（其中退款历史补全 {result['from_refund']} 单），"
        f"成功 {result['saved']}，失败 {result['failed']}"
        + ("" if result["complete"] else f"，⚠️ 少于服务端角标 {result['expected']}")
    )
    return result
