"""闲鱼卖家端（seller.goofish.com）MTOP 接口客户端。

与买家端（www.goofish.com）是两套独立的前端应用和 API 族：

- 买家端 ``mtop.idle.web.trade.bought.list`` 只能拿到买入订单，且视角硬编码，
  无法切换为卖家视角，PC 买家端不存在卖出订单列表接口。
- 卖家端 ``mtop.taobao.idle.trade.merchant.sold.get`` 一次调用即返回订单、
  买家收货信息和可执行动作，是卖出订单的唯一可靠来源。

签名沿用 H5 端的 MD5 方案（见 :func:`utils.xianyu_utils.generate_sign`），
``origin`` / ``referer`` 必须指向 seller.goofish.com，否则服务端会返回
``FAIL_SYS_SESSION_EXPIRED``（该错误码有误导性，实际原因是来源校验失败）。
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger

from utils import risk_control
from utils.xianyu_utils import generate_sign, trans_cookies


# 卖家端接口在部分字段上与买家端行为不同，调用方需注意：
# - 分页终止条件只能用 nextPage，totalCount 在越界页会变成 0
# - orderSearchParam 需要 JSON 字符串，refundSearchParam 需要嵌套对象
# - sold.get 的 orderId / itemId / buyerId 是整数，落库前必须转字符串
# - refundFee 在 sold.get 是元（"99.80"），在 pc.trade.full.info 是分（9980）


class SellerApiError(Exception):
    """卖家端接口返回业务失败。"""

    def __init__(self, api: str, ret: List[str]):
        self.api = api
        self.ret = ret
        super().__init__(f"{api} 调用失败: {'; '.join(ret) if ret else '未知错误'}")


class XianyuSellerAPI:
    """卖家端接口客户端。

    每个闲鱼账号一个实例，Cookie 由外部传入并可通过 :meth:`update_cookies` 刷新。
    """

    APP_KEY = "34839810"
    BASE_URL = "https://h5api.m.goofish.com/h5/{api}/{version}/"
    ORIGIN = "https://seller.goofish.com"
    SPM_CNT = "a21107h.42826273.0.0"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    )

    # sold.get 的订单状态筛选，值来自 merchant.order.count 的 countInfoList
    QUERY_CODES = (
        "ALL",
        "NOT_PAY",
        "NOT_SHIP",
        "SHIPPED",
        "TRADE_SUCCESS",
        "TRADE_CLOSED",
        "REFUND",
        "NOT_SHIP_ABOUT_TO_EXPIRE",
        "NOT_SHIP_EXPIRED",
    )

    def __init__(self, cookie_id: str, cookies_str: str, session: Optional[aiohttp.ClientSession] = None):
        self.cookie_id = cookie_id
        self.cookies_str = cookies_str or ""
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> "XianyuSellerAPI":
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """仅关闭自己创建的 session，外部传入的交由调用方管理。"""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    def update_cookies(self, cookies_str: str) -> None:
        self.cookies_str = cookies_str or ""

    # ------------------------------------------------------------------
    # 底层请求
    # ------------------------------------------------------------------

    def _token(self) -> str:
        """从 Cookie 取签名令牌，_m_h5_tk 的下划线前半段。"""
        if not self.cookies_str:
            return ""
        try:
            token_value = trans_cookies(self.cookies_str).get("_m_h5_tk", "")
        except ValueError:
            return ""
        return token_value.split("_")[0] if token_value else ""

    def _headers(self) -> Dict[str, str]:
        return {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            # 卖家端接口校验来源，指向 www.goofish.com 会被判定为会话过期
            "origin": self.ORIGIN,
            "referer": f"{self.ORIGIN}/",
            "user-agent": self.USER_AGENT,
            "cookie": self.cookies_str.replace("\n", "").replace("\r", ""),
        }

    async def _call(
        self,
        api: str,
        payload: Dict[str, Any],
        version: str = "1.0",
        value_type: Optional[str] = "string",
        timeout: int = 20,
    ) -> Dict[str, Any]:
        """调用卖家端接口并返回完整响应；业务失败抛 :class:`SellerApiError`。

        令牌过期时服务端会在响应里下发新的 ``_m_h5_tk``，此时用新令牌重签一次
        即可成功，因此对这类错误自动重试而不是直接失败。
        """
        if not self.cookies_str:
            raise SellerApiError(api, ["Cookie 为空，无法调用卖家端接口"])

        last_ret: List[str] = []
        # 熔断：账号处于风控冷却期时直接放弃，继续请求只会延长风控
        guard = risk_control.registry.get(self.cookie_id)
        if guard.is_blocked:
            raise risk_control.RiskControlBlocked(
                self.cookie_id, guard.remaining_seconds, guard.last_hit_reason
            )

        for attempt in range(2):
            data_val = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            # 毫秒时间戳：先乘再取整，避免丢失毫秒精度
            timestamp = str(int(time.time() * 1000))
            params = {
                "jsv": "2.7.2",
                "appKey": self.APP_KEY,
                "t": timestamp,
                "sign": generate_sign(timestamp, self._token(), data_val),
                "v": version,
                "type": "originaljson",
                "accountSite": "xianyu",
                "dataType": "json",
                "timeout": "20000",
                "api": api,
                "sessionOption": "AutoLoginOnly",
                "spm_cnt": self.SPM_CNT,
            }
            if value_type:
                params["valueType"] = value_type

            session = await self._ensure_session()
            url = self.BASE_URL.format(api=api, version=version)
            # 限流：控制每账号的请求速率，多账号并发时也不会突发
            await guard.acquire()
            async with session.post(
                url,
                params=params,
                data={"data": data_val},
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                result = await response.json(content_type=None)
                # 必须在判断结果前合并，令牌就在这次响应里
                self._merge_response_cookies(response)

            ret_list = [str(value) for value in (result.get("ret", []) if isinstance(result, dict) else [])]
            if any("SUCCESS" in value for value in ret_list):
                guard.reset()
                return result

            last_ret = ret_list

            # 平台风控：立刻熔断，不重试
            if risk_control.is_risk_control_error("; ".join(ret_list)):
                guard.trip("; ".join(ret_list))
                raise SellerApiError(api, ret_list)

            # 服务端对令牌过期有两种拼写，且历史版本存在拼写错误（EXOIRED）
            token_expired = any(
                "TOKEN_EXPIRED" in value
                or "TOKEN_EXOIRED" in value
                or "FAIL_SYS_TOKEN_EMPTY" in value
                for value in ret_list
            )
            if not token_expired or attempt == 1:
                break
            logger.debug(f"【{self.cookie_id}】{api} 令牌过期，使用新令牌重试")

        raise SellerApiError(api, last_ret)

    def _merge_response_cookies(self, response) -> None:
        """合并响应下发的新 Cookie，保持 _m_h5_tk 等令牌为最新值。"""
        if "set-cookie" not in response.headers:
            return

        updates: Dict[str, str] = {}
        for raw in response.headers.getall("set-cookie", []):
            pair = raw.split(";", 1)[0].strip()
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            if key in ("_m_h5_tk", "_m_h5_tk_enc", "cookie2", "sgcookie", "_tb_token_"):
                updates[key] = value

        if not updates:
            return

        try:
            current = trans_cookies(self.cookies_str) if self.cookies_str else {}
        except ValueError:
            current = {}
        current.update(updates)
        self.cookies_str = "; ".join(f"{k}={v}" for k, v in current.items())
        logger.debug(f"【{self.cookie_id}】卖家端 Cookie 已更新: {', '.join(updates)}")

    # ------------------------------------------------------------------
    # 订单
    # ------------------------------------------------------------------

    async def get_sold_orders(
        self,
        page_number: int = 1,
        rows_per_page: int = 20,
        query_code: str = "ALL",
        order_ids: str = "",
        search_param: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """查询卖出订单列表。

        Args:
            order_ids: 精确查询，多个订单号用逗号分隔（空格或数组会被服务端拒绝）。
            search_param: 见 :meth:`build_search_param`，会被序列化为 JSON 字符串。

        Returns:
            ``{"items": [...], "total_count": int, "next_page": bool}``。
            ``total_count`` 在越界页会返回 0，分页请以 ``next_page`` 为准。
        """
        payload = {
            "pageNumber": page_number,
            "rowsPerPage": rows_per_page,
            "orderIds": order_ids or "",
            "queryCode": query_code,
            # 该字段要求 JSON 字符串，不能直接传对象
            "orderSearchParam": json.dumps(
                search_param or {}, separators=(",", ":"), ensure_ascii=False
            ),
        }
        result = await self._call("mtop.taobao.idle.trade.merchant.sold.get", payload)
        module = (result.get("data") or {}).get("module") or {}
        return {
            "items": module.get("items") or [],
            "total_count": module.get("totalCount") or 0,
            "next_page": bool(module.get("nextPage")),
        }

    async def iter_sold_orders(
        self,
        query_code: str = "ALL",
        rows_per_page: int = 50,
        search_param: Optional[Dict[str, Any]] = None,
        max_pages: int = 100,
        page_interval: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """翻页拉取全部卖出订单。

        以 ``next_page`` 作为终止条件：``total_count`` 在超出总页数时会变成 0，
        用它计算循环边界会导致提前结束或死循环。

        服务端偶发 ``COMMON_SYSTEM_ERROR``，单页失败会重试若干次；重试仍失败时
        跳过该页继续后面的，避免一次抖动让整轮同步颗粒无收。
        """
        collected: List[Dict[str, Any]] = []
        seen_ids = set()
        failed_pages = []
        for page in range(1, max_pages + 1):
            batch = None
            for attempt in range(3):
                try:
                    batch = await self.get_sold_orders(
                        page_number=page,
                        rows_per_page=rows_per_page,
                        query_code=query_code,
                        search_param=search_param,
                    )
                    break
                except SellerApiError as exc:
                    if attempt == 2:
                        logger.warning(
                            f"【{self.cookie_id}】第 {page} 页拉取失败（已重试 3 次）: {exc}"
                        )
                        failed_pages.append(page)
                    else:
                        # 退避后重试，服务端限流时立刻重试通常还是失败
                        await asyncio.sleep(1.0 * (attempt + 1))

            if batch is None:
                # 该页确实拿不到，继续尝试后面的页而不是整体放弃
                if page_interval:
                    await asyncio.sleep(page_interval)
                continue

            for item in batch["items"]:
                order_id = str(((item.get("commonData") or {}).get("orderId") or ""))
                if order_id and order_id in seen_ids:
                    continue
                if order_id:
                    seen_ids.add(order_id)
                collected.append(item)

            if not batch["next_page"]:
                break
            if page_interval:
                await asyncio.sleep(page_interval)
        else:
            logger.warning(
                f"【{self.cookie_id}】卖出订单翻页达到上限 {max_pages} 页，可能未拉全"
            )

        if failed_pages:
            logger.warning(
                f"【{self.cookie_id}】以下页码最终未取到: {failed_pages}"
            )

        return collected

    @staticmethod
    def build_search_param(
        create_start: Optional[str] = None,
        create_end: Optional[str] = None,
        pay_start: Optional[str] = None,
        pay_end: Optional[str] = None,
        end_start: Optional[str] = None,
        end_end: Optional[str] = None,
        auction_title: Optional[str] = None,
        buyer_nick: Optional[str] = None,
        precise_query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """构造 orderSearchParam。

        时间字段格式为 ``YYYY-MM-DD``，只精确到天。``auction_title`` 是模糊匹配，
        ``buyer_nick`` 和 ``precise_query``（订单号）是精确匹配。
        """
        param: Dict[str, Any] = {}
        for key, value in (
            ("createStartTime", create_start),
            ("createEndTime", create_end),
            ("payStartTime", pay_start),
            ("payEndTime", pay_end),
            ("endStartTime", end_start),
            ("endEndTime", end_end),
            ("auctionTitle", auction_title),
            ("buyerNick", buyer_nick),
            ("preciseQuery", precise_query),
        ):
            if value:
                param[key] = value
        return param

    async def get_order_count(self, query_type: str = "ORDER") -> Dict[str, int]:
        """获取角标计数。query_type 取 ORDER / RATE / REFUND。

        ``ORDER.ALL`` 是服务端认定的订单总数，可用来校验列表是否拉全。
        注意 ``RATE`` 和 ``REFUND`` 维度的数字是历史累计值，远大于列表接口
        能返回的条数（已归档订单不在列表里）。
        """
        result = await self._call(
            "mtop.taobao.idle.merchant.order.count",
            {"queryType": query_type},
            value_type=None,
        )
        module = (result.get("data") or {}).get("module") or {}
        counts: Dict[str, int] = {}
        for entry in module.get("countInfoList") or []:
            code = entry.get("queryCode")
            if code:
                try:
                    counts[code] = int(entry.get("count") or 0)
                except (TypeError, ValueError):
                    counts[code] = 0
        return counts

    async def get_expected_order_total(self) -> Optional[int]:
        """读取服务端认定的订单总数，用于校验拉取完整性；失败返回 None。"""
        try:
            counts = await self.get_order_count("ORDER")
        except SellerApiError as exc:
            logger.debug(f"【{self.cookie_id}】读取订单角标失败: {exc}")
            return None
        return counts.get("ALL")

    async def get_close_reasons(self, order_id: str) -> List[Dict[str, Any]]:
        """获取卖家版关单理由。

        与买家版 ``mtop.taobao.idle.trade.order.close.reason.get`` 的取值完全不同，
        卖家版为：不想卖了 / 宝贝已出售 / 买家联系不上 / 与买家协商一致 / 其他原因。
        """
        result = await self._call(
            "mtop.taobao.idle.merchant.order.close.reason.get",
            {"tid": str(order_id), "bizOrderId": str(order_id)},
            value_type=None,
        )
        module = (result.get("data") or {}).get("module") or {}
        return module.get("closeReasons") or []

    async def get_privacy_address(
        self, order_id: str, page_source: str = "order_list"
    ) -> Dict[str, Any]:
        """获取收货地址。

        买家开启隐私号时 ``buyerInfoVO`` 可能是脱敏值，发实物前应补调一次；
        响应仅约 85 字节，成本可忽略。
        """
        result = await self._call(
            "mtop.idle.trade.order.detail.privacy.address",
            {"bizOrderId": str(order_id), "pageSource": page_source},
        )
        return (result.get("data") or {}) or {}

    async def get_consign_render(self, order_id: str) -> Dict[str, Any]:
        """获取发货页渲染信息。

        这是发货前信息最全的只读接口，一次返回规格、收货信息、件数、
        支持的发货方式（虚拟发货对应 ``DUMMY_CONSIGN``）以及是否必须填序列号。
        订单列表的 ``itemInfoLines`` 是空的，规格只能从这里拿。

        注意该接口的参数名是 tradeId，不是 orderId。
        """
        result = await self._call(
            "mtop.taobao.idle.logistics.merchant.consign.page.render",
            {"tradeId": str(order_id)},
            value_type=None,
        )
        return (result.get("data") or {}) or {}

    async def get_order_detail(self, order_id: str) -> Dict[str, Any]:
        """通过买家端订单详情接口获取订单信息（含 skuInfo 规格字段）。

        ``mtop.idle.web.trade.order.detail`` 返回的 ``skuInfo`` 字段格式固定为
        ``"规格名:规格值"``（如 ``"尺码:天卡"``），比 ``consign.page.render`` 的
        ``itemInfoLines`` 更可靠，不受字段排序影响。

        注意：这是买家端接口，origin 必须指向 www.goofish.com。
        """
        guard = risk_control.registry.get(self.cookie_id)
        if guard.is_blocked:
            raise risk_control.RiskControlBlocked(
                self.cookie_id, guard.remaining_seconds, guard.last_hit_reason
            )

        if not self.cookies_str:
            raise SellerApiError("mtop.idle.web.trade.order.detail", ["Cookie 为空"])

        last_ret: List[str] = []
        data_val = json.dumps({"tid": str(order_id)}, separators=(",", ":"))
        timestamp = str(int(time.time() * 1000))

        headers = {
            "accept": "application/json",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://www.goofish.com",
            "referer": "https://www.goofish.com/",
            "user-agent": self.USER_AGENT,
            "cookie": self.cookies_str.replace("\n", "").replace("\r", ""),
        }

        for attempt in range(2):
            params = {
                "jsv": "2.7.2",
                "appKey": self.APP_KEY,
                "t": timestamp,
                "sign": generate_sign(timestamp, self._token(), data_val),
                "v": "1.0",
                "type": "originaljson",
                "accountSite": "xianyu",
                "dataType": "json",
                "timeout": "20000",
                "api": "mtop.idle.web.trade.order.detail",
                "sessionOption": "AutoLoginOnly",
                "spm_cnt": "a21ybx.order-detail.0.0",
            }

            session = await self._ensure_session()
            url = self.BASE_URL.format(api="mtop.idle.web.trade.order.detail", version="1.0")
            await guard.acquire()
            async with session.post(
                url,
                params=params,
                data={"data": data_val},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                result = await response.json(content_type=None)
                self._merge_response_cookies(response)

            ret_list = [str(v) for v in (result.get("ret", []) if isinstance(result, dict) else [])]
            if any("SUCCESS" in v for v in ret_list):
                guard.reset()
                return (result.get("data") or {}) or {}

            last_ret = ret_list
            if risk_control.is_risk_control_error("; ".join(ret_list)):
                guard.trip("; ".join(ret_list))
                raise SellerApiError("mtop.idle.web.trade.order.detail", ret_list)

            token_expired = any(
                "TOKEN_EXPIRED" in v or "TOKEN_EXOIRED" in v or "FAIL_SYS_TOKEN_EMPTY" in v
                for v in ret_list
            )
            if not token_expired or attempt == 1:
                break
            logger.debug(f"【{self.cookie_id}】order.detail 令牌过期，使用新令牌重试")

        raise SellerApiError("mtop.idle.web.trade.order.detail", last_ret)

    # ------------------------------------------------------------------
    # 退款
    # ------------------------------------------------------------------

    async def get_user_profile(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """获取账号公开资料（昵称、头像、店铺等级、信用标签）。

        原先靠 Playwright 抓个人主页解析 HTML，浏览器版本不匹配时会整个失效；
        这个接口直接返回结构化数据，不需要浏览器。
        """
        result = await self._call(
            "mtop.idle.web.user.page.head",
            {"userId": str(user_id or self.cookie_id)},
        )
        return (result.get("data") or {}) or {}

    async def get_refund_list(
        self,
        page_number: int = 1,
        rows_per_page: int = 20,
        query_code: str = "ALL",
    ) -> Dict[str, Any]:
        """查询退款列表。

        该接口的响应比 sold.get 多一层（``data.data``），且 refundSearchParam
        要求嵌套对象而非 JSON 字符串。
        """
        payload = {
            "pageNumber": page_number,
            "rowsPerPage": rows_per_page,
            "queryType": "refund",
            "refundSearchParam": {"queryCode": query_code},
        }
        result = await self._call("mtop.taobao.idle.merchant.refund.list", payload)
        data = (result.get("data") or {}).get("data") or {}
        return {
            "items": data.get("items") or [],
            "total_refund_fee": ((data.get("ext") or {}).get("totalRefundFee")),
        }

    async def get_refund_record(self, order_id: str) -> Dict[str, Any]:
        """获取结构化退款记录，比 refund.detail 的 UI 组件更易解析。"""
        result = await self._call(
            "mtop.taobao.idle.merchant.refund.service.record",
            {"orderId": str(order_id)},
            value_type=None,
        )
        return (result.get("data") or {}) or {}

    async def get_logistics_trace(self, order_id: str) -> Dict[str, Any]:
        """获取物流轨迹。

        项目原先没有物流能力，实物订单的运单状态只能靠人工去闲鱼查看。
        参数名是 tradeId，也支持按 mailNo 查询。
        """
        result = await self._call(
            "mtop.cainiao.ld.detail.tradeid.ordercode.mailno.rescode.get.xy",
            {"tradeId": str(order_id)},
            value_type=None,
        )
        return (result.get("data") or {}) or {}

    async def iter_refund_orders(
        self,
        rows_per_page: int = 50,
        max_pages: int = 40,
        page_interval: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """翻页拉取全部退款单。

        退款列表能返回 sold.get 已经查不到的历史归档订单，是补全早期成交记录的
        唯一途径。它不返回收货信息，金额也只有单价和退款额。
        """
        collected: List[Dict[str, Any]] = []
        seen = set()
        for page in range(1, max_pages + 1):
            batch = await self.get_refund_list(
                page_number=page, rows_per_page=rows_per_page
            )
            items = batch.get("items") or []
            if not items:
                break

            for item in items:
                order_id = str(((item.get("commonData") or {}).get("orderId") or ""))
                if order_id and order_id in seen:
                    continue
                if order_id:
                    seen.add(order_id)
                collected.append(item)

            if len(items) < rows_per_page:
                break
            if page_interval:
                await asyncio.sleep(page_interval)

        return collected

    # ------------------------------------------------------------------
    # 写操作：默认关闭，由调用方按开关决定是否执行
    # ------------------------------------------------------------------

    async def create_rate(
        self,
        order_ids: List[str],
        feedback: str,
        rate: int = 1,
        image_urls: Optional[List[str]] = None,
        anonymous: bool = False,
    ) -> Dict[str, Any]:
        """提交买家评价，支持批量。

        评价提交后无法撤销，调用方必须先确认开关已开启。

        Args:
            rate: 1 好评 / 0 中评 / -1 差评。
        """
        if not order_ids:
            raise SellerApiError("mtop.taobao.idle.merchant.rate.create", ["订单列表为空"])
        if not (feedback or "").strip():
            raise SellerApiError("mtop.taobao.idle.merchant.rate.create", ["评价内容不能为空"])
        if rate not in (1, 0, -1):
            raise SellerApiError(
                "mtop.taobao.idle.merchant.rate.create", [f"评价等级非法: {rate}"]
            )

        payload = {
            "tradeIdList": [str(order_id) for order_id in order_ids],
            "rate": rate,
            "feedback": feedback,
            "imageUrls": image_urls or [],
            "anonymous": bool(anonymous),
        }
        result = await self._call("mtop.taobao.idle.merchant.rate.create", payload)
        module = (result.get("data") or {}).get("module") or {}
        return {
            "success": bool(module.get("success")),
            "success_order_ids": module.get("successOrderIds") or [],
            "fail_orders": module.get("failOrderInfos") or [],
        }

    async def require_flower(self, order_id: str) -> Dict[str, Any]:
        """向买家索要小红花（求花）。

        会给买家发送一条消息，交易完结后即可调用，与评价状态无关。
        """
        result = await self._call(
            "mtop.taobao.idlemessage.red.flower",
            {"orderId": str(order_id)},
            value_type=None,
        )
        return (result.get("data") or {}) or {}


def parse_sold_order(item: Dict[str, Any]) -> Dict[str, Any]:
    """把 sold.get 的单条订单展开成落库用的扁平字段。

    金额取 ``priceVO.totalPrice``（真实成交额）而非商品挂牌价，数量取
    ``priceVO.buyNum`` 而非固定 1，多件和议价订单才不会算错。
    """
    common = item.get("commonData") or {}
    buyer = item.get("buyerInfoVO") or {}
    price = item.get("priceVO") or {}
    item_vo = item.get("itemVO") or {}
    right = item.get("rightVO") or {}

    actions = [
        btn.get("tradeAction")
        for btn in (right.get("btnList") or [])
        if btn.get("tradeAction")
    ]

    def _text(value: Any) -> str:
        return "" if value is None else str(value)

    return {
        "order_id": _text(common.get("orderId")),
        "item_id": _text(common.get("itemId")),
        "item_title": _text(item_vo.get("title")),
        # orderStatus 是中文文案，交给 normalize_order_status 归一化
        "status_text": _text(common.get("orderStatus")),
        "created_at": _text(common.get("createTime")),
        "pay_time": _text(common.get("paySuccessTime")),
        "consign_time": _text(common.get("consignTime")),
        "finish_time": _text(common.get("finishTime")),
        "seller_rate_status": common.get("sellerRateStatus"),
        "in_refund": bool(common.get("inRefund")),
        "refund_status_desc": _text(common.get("refundStatusDesc")),
        "buyer_id": _text(buyer.get("buyerId")),
        "buyer_nick": _text(buyer.get("userNick")),
        "receiver_name": _text(buyer.get("name")),
        "receiver_phone": _text(buyer.get("phone")),
        "receiver_address": _text(buyer.get("address")),
        "is_privacy": bool(buyer.get("isPrivacy")),
        "amount": _text(price.get("totalPrice")),
        "auction_price": _text(price.get("auctionPrice")),
        "buy_num": price.get("buyNum") or 1,
        "post_fee": _text(price.get("postFee")),
        "discount_fee": _text(price.get("discountFee")),
        "confirm_fee": _text(price.get("confirmFee")),
        "refund_fee": _text(price.get("refundFee")),
        "trade_actions": actions,
    }


def parse_refund_order(item: Dict[str, Any]) -> Dict[str, Any]:
    """把 refund.list 的单条退款单展开成落库用的扁平字段。

    该接口用于补全 sold.get 已查不到的历史归档订单，字段比订单列表少：

    - 没有 ``totalPrice``，成交额只能按 ``auctionPrice × buyNum`` 估算，
      因此不含运费和优惠，与订单列表的真值可能有差异
    - 没有收货信息（``buyerInfoVO`` 只有 buyerId / userNick / userIcon）
    - 没有 ``confirmFee``，这些单均已退款，卖家实收记为 0
    """
    common = item.get("commonData") or {}
    buyer = item.get("buyerInfoVO") or {}
    price = item.get("priceVO") or {}
    item_vo = item.get("itemVO") or {}
    refund = item.get("refundInfoVO") or {}

    def _text(value: Any) -> str:
        return "" if value is None else str(value)

    buy_num = price.get("buyNum") or 1
    unit_price = _text(price.get("auctionPrice"))
    amount = ""
    try:
        if unit_price:
            # 缺少 totalPrice，只能用单价乘件数估算
            amount = f"{float(unit_price) * int(buy_num):.2f}"
    except (TypeError, ValueError):
        amount = unit_price

    return {
        "order_id": _text(common.get("orderId")),
        "item_id": _text(common.get("itemId")),
        "item_title": _text(item_vo.get("title")),
        "status_text": _text(common.get("orderStatus")),
        "created_at": _text(common.get("createTime")),
        "buyer_id": _text(buyer.get("buyerId")),
        "buyer_nick": _text(buyer.get("userNick")),
        "amount": amount,
        "auction_price": unit_price,
        "buy_num": buy_num,
        "refund_fee": _text(price.get("refundFee")),
        # 已退款订单卖家实收为 0，避免被计入营收
        "confirm_fee": "0.00",
        "post_fee": "",
        "refund_id": _text(refund.get("refundId")),
        "refund_reason": _text(refund.get("reason")),
        "refund_status_desc": _text(refund.get("refundStatus")),
        "in_refund": True,
        "from_refund_list": True,
    }


def parse_consign_render(data: Dict[str, Any]) -> Dict[str, Any]:
    """从 consign.page.render 的响应里取出发货所需信息。

    这是规格信息的唯一来源 —— 订单列表的 ``itemInfoLines`` 为空，
    只有发货页渲染接口会返回 ``[{"key": "规格", "value": "..."}]``。

    Returns:
        含 ``spec_name`` / ``spec_value`` / 收货信息 / ``support_consign_type``
        等字段；缺字段时返回空值而不抛异常。
    """
    orders = data.get("bizOrderInfoList") or []
    first = orders[0] if orders else {}
    common = first.get("commonData") or {}
    item_vo = first.get("itemVO") or {}
    price = first.get("priceVO") or {}
    # 顶层 buyerInfoVO 与订单级的内容一致，订单级缺失时回退到顶层
    buyer = first.get("buyerInfoVO") or data.get("buyerInfoVO") or {}

    def _text(value: Any) -> str:
        return "" if value is None else str(value)

    spec_name = ""
    spec_value = ""
    for line in item_vo.get("itemInfoLines") or []:
        key = _text(line.get("key"))
        if key and key != "商品ID":
            spec_name = key
            spec_value = _text(line.get("value"))
            break

    return {
        "order_id": _text(common.get("orderId")),
        "item_id": _text(common.get("itemId")),
        "item_title": _text(item_vo.get("title")),
        "spec_name": spec_name,
        "spec_value": spec_value,
        "buy_num": price.get("buyNum") or 1,
        "auction_price": _text(price.get("auctionPrice")),
        "receiver_name": _text(buyer.get("name")),
        "receiver_phone": _text(buyer.get("phone")),
        "receiver_address": _text(buyer.get("address")),
        "buyer_nick": _text(buyer.get("userNick")),
        "need_serial_number": bool(common.get("needSerialNumber")),
        "need_upload_report": bool(common.get("needUploadReport")),
        "support_consign_type": data.get("supportConsignType") or [],
    }


def parse_logistics_trace(data: Dict[str, Any]) -> Dict[str, Any]:
    """把物流轨迹响应整理成运单概要和节点列表。

    一个订单可能拆成多个包裹，这里只取第一个包裹；``nodes`` 按接口返回顺序，
    最新节点在前。
    """
    views = data.get("detailViewList") or []
    view = views[0] if views else {}

    nodes = []
    for node in view.get("detailList") or []:
        nodes.append({
            "time": node.get("time") or node.get("ocurrTimeStr") or "",
            "desc": node.get("desc") or node.get("standerdDesc") or "",
            "action": node.get("action") or "",
            "status_desc": node.get("statusDesc") or "",
        })

    return {
        "trade_id": str(view.get("tradeIdAsString") or view.get("tradeId") or ""),
        "mail_no": str(view.get("orderCode") or ""),
        # status 是 {statusCode, statusDesc, statusSeq} 结构，取可读文案
        "status": (
            view["status"].get("statusDesc") or view["status"].get("statusCode") or ""
            if isinstance(view.get("status"), dict)
            else str(view.get("status") or "")
        ),
        "package_count": len(views),
        "nodes": nodes,
        # 最新一条轨迹，用于列表页直接展示
        "latest": nodes[0] if nodes else None,
    }


def parse_user_profile(data: Dict[str, Any]) -> Dict[str, Any]:
    """从 user.page.head 响应里取出账号资料。

    昵称在 ``module.base.displayName``，头像在 ``module.base.avatar.avatar``；
    另外附带店铺等级和好评率，用于账号列表展示。
    """
    module = data.get("module") or {}
    base = module.get("base") or {}
    shop = module.get("shop") or {}
    # 粉丝/关注在 module.social 下，接口返回的是字符串
    social = module.get("social") or {}
    avatar = base.get("avatar") or {}

    def _text(value: Any) -> str:
        return "" if value is None else str(value)

    avatar_url = _text(avatar.get("avatar") if isinstance(avatar, dict) else avatar)
    # 接口返回的是 http，页面用 https 加载会被浏览器拦掉
    if avatar_url.startswith("http://"):
        avatar_url = "https://" + avatar_url[len("http://"):]

    # 信用标签里区分买家和卖家两个维度，只取卖家的
    seller_level = None
    for tag in base.get("ylzTags") or []:
        attrs = (tag or {}).get("attributes") or {}
        if attrs.get("role") == "seller":
            seller_level = tag.get("text") or ""
            break

    def _count(value):
        """接口把粉丝/关注返回成字符串，转成整数供前端展示。"""
        text = _text(value).replace(",", "").strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None

    return {
        "nickname": _text(base.get("displayName")),
        "avatar_url": avatar_url,
        "location": _text(base.get("ipLocation")),
        "seller_credit": _text(seller_level),
        "shop_level": _text(shop.get("level")),
        "praise_ratio": shop.get("praiseRatio"),
        "review_num": shop.get("reviewNum"),
        "followers": _count(social.get("followers")),
        "following": _count(social.get("following")),
    }
