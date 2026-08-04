"""
使用Playwright浏览器的订单状态查询模块
通过访问订单详情页面并拦截API来获取订单状态
"""
import asyncio
import json
from typing import Dict, Any
from playwright.async_api import async_playwright
from utils.order_status_rules import normalize_order_status
from utils.xianyu_utils import trans_cookies


class OrderStatusQueryPlaywright:
    """使用Playwright的订单状态查询类"""

    def __init__(self, cookies_str: str, cookie_id: str, headless: bool = True):
        """
        初始化订单查询器

        Args:
            cookies_str: Cookie字符串
            cookie_id: Cookie ID
            headless: 是否使用无头浏览器（默认True，不显示窗口）
        """
        self.cookies_str = cookies_str
        self.cookie_id = cookie_id
        self.headless = headless
        self.api_responses = []

    async def query_order_status(
        self,
        order_id: str,
        timeout: int = 30000
    ) -> Dict[str, Any]:
        """
        查询订单状态（使用Playwright）

        Args:
            order_id: 订单ID
            timeout: 超时时间（毫秒）

        Returns:
            包含订单信息的字典
        """
        # 解析Cookie
        cookies_dict = trans_cookies(self.cookies_str)

        # 转换为Playwright格式的Cookie列表
        playwright_cookies = []
        for name, value in cookies_dict.items():
            playwright_cookies.append({
                'name': name,
                'value': value,
                'domain': '.goofish.com',
                'path': '/'
            })

        async def handle_route(route, request):
            """拦截网络请求"""
            # 拦截订单详情API
            if 'mtop.idle.web.trade.order.detail' in request.url:
                print(f"\n[拦截] 发现订单详情API请求")

                # 继续请求并获取响应
                response = await route.fetch()
                body = await response.body()

                try:
                    result = json.loads(body)
                    self.api_responses.append(result)

                except Exception as e:
                    print(f"解析响应失败: {e}")

            # 继续所有请求
            await route.continue_()

        async with async_playwright() as p:
            browser = None
            try:
                print(f"\n启动浏览器...")
                browser = await p.chromium.launch(headless=self.headless)

                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
                )

                # 添加Cookie
                await context.add_cookies(playwright_cookies)
                print(f"已添加 {len(playwright_cookies)} 个Cookie")

                # 创建页面并设置路由拦截
                page = await context.new_page()
                await page.route('**/*', handle_route)

                # 访问订单详情页面
                page_url = f'https://www.goofish.com/order-detail?orderId={order_id}&role=seller'
                print(f"\n访问订单详情页面: {page_url}")

                response = await page.goto(page_url, wait_until='networkidle', timeout=timeout)
                print(f"页面响应状态码: {response.status}")

                # 等待API响应（减少等待时间）
                print("等待API响应...")
                await asyncio.sleep(2)  # 从5秒减少到2秒

                # 快速滚动，触发可能延迟加载的内容
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await asyncio.sleep(0.5)  # 从2秒减少到0.5秒
                await page.evaluate('window.scrollTo(0, 0)')
                await asyncio.sleep(0.5)  # 从3秒减少到0.5秒

                # 检查是否拦截到API响应
                if self.api_responses:
                    result = self.api_responses[0]

                    if result.get('ret') and result['ret'][0].startswith('SUCCESS'):
                        order_data = result.get('data', {})

                        # 提取商品信息
                        components = order_data.get('components', [])
                        item_title = 'N/A'
                        price = 'N/A'
                        receiver_address = None
                        receiver_city = None

                        for component in components:
                            if component.get('render') == 'orderInfoVO':
                                item_info = component.get('data', {}).get('itemInfo', {})
                                item_title = item_info.get('title', 'N/A')
                                price_info = component.get('data', {}).get('priceInfo', {})
                                amount = price_info.get('amount', {})
                                price = amount.get('value', 'N/A')

                                # 提取收货地址信息
                                address_info = component.get('data', {}).get('addressInfo', {})
                                print(f"[DEBUG] address_info: {address_info}")
                                receiver_name = None
                                receiver_phone = None
                                if address_info:
                                    # 构建完整地址
                                    receiver_name = address_info.get('receiverName', '')
                                    receiver_phone = address_info.get('receiverMobile', '')
                                    province = address_info.get('province', '')
                                    city = address_info.get('city', '')
                                    district = address_info.get('district', '')
                                    detail_address = address_info.get('detailAddress', '')
                                    full_address = address_info.get('fullAddress', '')

                                    # 设置城市（用于地区统计）
                                    if city:
                                        receiver_city = city

                                    # 构建完整地址字符串
                                    if full_address:
                                        receiver_address = full_address
                                    elif province or city or district or detail_address:
                                        address_parts = []
                                        if province:
                                            address_parts.append(province)
                                        if city:
                                            address_parts.append(city)
                                        if district:
                                            address_parts.append(district)
                                        if detail_address:
                                            address_parts.append(detail_address)
                                        if receiver_name:
                                            address_parts.insert(0, f"{receiver_name}")

                                        receiver_address = ' '.join(address_parts)

                        # 检查是否可评价
                        bottom_bar = order_data.get('bottomBarVO', {})
                        button_list = bottom_bar.get('buttonList', {})

                        can_rate = any(
                            btn.get('tradeAction') == 'RATE'
                            for btn in button_list
                        )

                        status_code = order_data.get('status')
                        status_text = order_data.get('utArgs', {}).get('orderStatusName', '')
                        return {
                            'success': True,
                            'order_id': order_id,
                            'order_status': normalize_order_status(status_code, status_text),
                            'raw_status_code': status_code,
                            'status_text': status_text,
                            'item_title': item_title,
                            'price': price,
                            'can_rate': can_rate,
                            'receiver_name': receiver_name,
                            'receiver_phone': receiver_phone,
                            'receiver_address': receiver_address,
                            'receiver_city': receiver_city,
                            'raw_data': order_data
                        }
                    else:
                        error_msg = result.get('ret', ['未知错误'])[0]
                        return {
                            'success': False,
                            'error': error_msg,
                            'order_id': order_id
                        }
                else:
                    return {
                        'success': False,
                        'error': '未拦截到API响应',
                        'order_id': order_id
                    }

            finally:
                if browser:
                    await browser.close()

    def format_order_info(self, result: Dict[str, Any]) -> str:
        """
        格式化订单信息用于显示

        Args:
            result: query_order_status返回的结果

        Returns:
            格式化的字符串
        """
        if not result.get('success'):
            return f"[X] 查询失败: {result.get('error')}"

        output = []
        output.append("=" * 50)
        output.append("订单信息")
        output.append("=" * 50)
        output.append(f"订单ID: {result.get('order_id')}")
        output.append(f"商品标题: {result.get('item_title', 'N/A')}")
        output.append(f"成交价: {result.get('price', 'N/A')}")
        output.append(f"订单状态: {result.get('status_text', 'N/A')}")
        output.append(f"状态码: {result.get('order_status', 'N/A')}")

        # 显示收货地址
        if result.get('receiver_address'):
            output.append(f"收货地址: {result.get('receiver_address')}")
        if result.get('receiver_city'):
            output.append("收货城市: {}".format(result.get('receiver_city')))

        if result.get('can_rate'):
            output.append("[OK] 该订单可以评价")
        else:
            output.append("[X] 该订单暂不可评价")

        output.append("=" * 50)

        return "\n".join(output)
