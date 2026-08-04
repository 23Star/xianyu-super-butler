"""
订单状态处理器
专门处理订单状态更新逻辑，用于更新订单管理中的状态
"""

import re
import json
import time
import uuid
import threading
import asyncio
from loguru import logger
from typing import Optional, Dict, Any

# ==================== 订单状态处理器配置 ====================
# 订单状态处理器配置
ORDER_STATUS_HANDLER_CONFIG = {
    'use_pending_queue': True,                     # 是否使用待处理队列
    'strict_validation': True,                     # 是否启用严格的状态转换验证
    'log_level': 'info',                          # 日志级别 (debug/info/warning/error)
    'max_pending_age_hours': 24,                  # 待处理更新的最大保留时间（小时）
    'enable_status_logging': True,                # 是否启用详细的状态变更日志
}


class OrderStatusHandler:
    """订单状态处理器"""
    
    # 状态转换规则常量
    # 规则说明：
    # 1. 已付款的订单和已完成的订单不能回退到处理中
    # 2. 已付款的订单和已完成的订单可以设置为已关闭（因为会出现退款）
    # 3. 退款中的订单或者退货中的订单设置为退款中
    # 4. 退款中的订单可以设置为已完成（因为买家可能取消退款）
    # 5. 只有退款完成才设置为已关闭
    VALID_TRANSITIONS = {
        'processing': ['pending_ship', 'shipped', 'completed', 'cancelled'],
        'pending_ship': ['shipped', 'completed', 'cancelled', 'refunding'],  # 已付款，可以退款
        'shipped': ['completed', 'cancelled', 'refunding'],  # 已发货，可以退款
        'completed': ['cancelled', 'refunding'],  # 已完成，可以退款
        'refunding': ['completed', 'cancelled', 'refund_cancelled'],  # 退款中，可以完成（取消退款）、关闭（退款完成）或撤销
        'refund_cancelled': [],  # 退款撤销（临时状态，会立即回退到上一次状态）
        'cancelled': []  # 已关闭，不能转换到其他状态
    }
    
    def __init__(self):
        """初始化订单状态处理器"""
        # 加载配置
        self.config = ORDER_STATUS_HANDLER_CONFIG
        
        self.status_mapping = {
            'processing': '处理中',     # 初始状态/基本信息阶段
            'pending_ship': '待发货',   # 已付款，等待发货
            'shipped': '已发货',        # 发货确认后
            'completed': '已完成',      # 交易完成
            'refunding': '退款中',      # 退款中/退货中
            'refund_cancelled': '退款撤销',  # 退款撤销（临时状态，会回退）
            'cancelled': '已关闭',      # 交易关闭
        }
        
        # 待处理的订单状态更新队列 {order_id: [update_info, ...]}
        self.pending_updates = {}
        # 待处理的系统消息队列（用于延迟处理）{cookie_id: [message_info, ...]}
        self._pending_system_messages = {}
        # 待处理的红色提醒消息队列（用于延迟处理）{cookie_id: [message_info, ...]}
        self._pending_red_reminder_messages = {}
        
        # 订单状态历史记录 {order_id: [status_history, ...]}
        # 用于退款撤销时回退到上一次状态
        self._order_status_history = {}
        
        # 使用threading.RLock保护并发访问
        # 注意：虽然在async环境中asyncio.Lock更理想，但本类的所有方法都是同步的
        # 且被同步代码调用，因此保持使用threading.RLock是合适的
        self._lock = threading.RLock()
        
        # 设置日志级别
        log_level = self.config.get('log_level', 'info')
        logger.info(f"订单状态处理器初始化完成，配置: {self.config}")
    
    def extract_order_id(self, message: dict) -> Optional[str]:
        """从消息中提取订单ID"""
        try:
            order_id = None
            
            # 原始消息可能包含用户隐私或会话字段，只记录顶层结构。
            logger.debug(
                "订单消息结构: type={}, keys={}",
                type(message).__name__,
                list(message.keys()) if isinstance(message, dict) else []
            )
            
            # 检查message['1']的结构，处理可能是列表、字典或字符串的情况
            message_1 = message.get('1', {})
            content_json_str = ''
            
            if isinstance(message_1, dict):
                logger.info(f"🔍 message['1'] 是字典，keys: {list(message_1.keys())}")
                
                # 检查message['1']['6']的结构
                message_1_6 = message_1.get('6', {})
                if isinstance(message_1_6, dict):
                    logger.info(f"🔍 message['1']['6'] 是字典，keys: {list(message_1_6.keys())}")
                    # 方法1: 从button的targetUrl中提取orderId
                    content_json_str = message_1_6.get('3', {}).get('5', '') if isinstance(message_1_6.get('3', {}), dict) else ''
                else:
                    logger.info(f"🔍 message['1']['6'] 不是字典: {type(message_1_6)}")
            
            elif isinstance(message_1, list):
                logger.info(f"🔍 message['1'] 是列表，长度: {len(message_1)}")
                # 如果message['1']是列表，跳过这种提取方式
            
            elif isinstance(message_1, str):
                logger.info(f"🔍 message['1'] 是字符串，长度: {len(message_1)}")
                # 如果message['1']是字符串，跳过这种提取方式
            
            else:
                logger.info(f"🔍 message['1'] 未知类型: {type(message_1)}")
                # 其他类型，跳过这种提取方式
            
            if content_json_str:
                try:
                    content_data = json.loads(content_json_str)
                    
                    # 方法1a: 从button的targetUrl中提取orderId
                    target_url = content_data.get('dxCard', {}).get('item', {}).get('main', {}).get('exContent', {}).get('button', {}).get('targetUrl', '')
                    if target_url:
                        # 从URL中提取orderId参数
                        order_match = re.search(r'orderId=(\d+)', target_url)
                        if order_match:
                            order_id = order_match.group(1)
                            logger.info(f'✅ 从button提取到订单ID: {order_id}')
                    
                    # 方法1b: 从main的targetUrl中提取order_detail的id
                    if not order_id:
                        main_target_url = content_data.get('dxCard', {}).get('item', {}).get('main', {}).get('targetUrl', '')
                        if main_target_url:
                            order_match = re.search(r'order_detail\?id=(\d+)', main_target_url)
                            if order_match:
                                order_id = order_match.group(1)
                                logger.info(f'✅ 从main targetUrl提取到订单ID: {order_id}')
                
                except Exception as parse_e:
                    logger.error(f"解析内容JSON失败: {parse_e}")
            
            # 方法2: 从dynamicOperation中的order_detail URL提取orderId
            if not order_id and content_json_str:
                try:
                    content_data = json.loads(content_json_str)
                    dynamic_target_url = content_data.get('dynamicOperation', {}).get('changeContent', {}).get('dxCard', {}).get('item', {}).get('main', {}).get('exContent', {}).get('button', {}).get('targetUrl', '')
                    if dynamic_target_url:
                        # 从order_detail URL中提取id参数
                        order_match = re.search(r'order_detail\?id=(\d+)', dynamic_target_url)
                        if order_match:
                            order_id = order_match.group(1)
                            logger.info(f'✅ 从order_detail提取到订单ID: {order_id}')
                except Exception as parse_e:
                    logger.error(f"解析dynamicOperation JSON失败: {parse_e}")
            
            # 方法3: 从tip类型消息中提取订单ID（通过itemId和买家ID查询）
            if not order_id and isinstance(message_1, dict):
                try:
                    # 检查是否为tip类型消息（contentType=14）
                    message_1_10 = message_1.get('10', {})
                    if isinstance(message_1_10, dict):
                        reminder_url = message_1_10.get('reminderUrl', '')
                        if reminder_url:
                            # 从reminderUrl提取itemId和peerUserId
                            # 格式：fleamarket://message_chat?itemId=xxx&peerUserId=yyy&...
                            item_match = re.search(r'itemId=(\d+)', reminder_url)
                            peer_match = re.search(r'peerUserId=(\d+)', reminder_url)

                            if item_match and peer_match:
                                item_id = item_match.group(1)
                                buyer_id = peer_match.group(1)
                                logger.info(f'🔍 从tip消息提取到: itemId={item_id}, buyerId={buyer_id}')

                                # 通过itemId和买家ID查询最近的订单
                                try:
                                    from db_manager import db_manager
                                    # 查询该商品和买家的最近订单
                                    recent_order = db_manager.get_recent_order_by_item_and_buyer(item_id, buyer_id)
                                    if recent_order:
                                        order_id = recent_order.get('order_id')
                                        if order_id:
                                            logger.info(f'✅ 从数据库查询到关联订单ID: {order_id}')
                                except Exception as db_e:
                                    logger.warning(f'从数据库查询订单失败: {db_e}')
                except Exception as tip_e:
                    logger.warning(f'处理tip消息失败: {tip_e}')

            # 方法4: 如果前面的方法都失败，尝试在整个消息中搜索订单ID模式
            if not order_id:
                try:
                    # 将整个消息转换为字符串进行搜索
                    message_str = str(message)

                    # 搜索各种可能的订单ID模式
                    patterns = [
                        r'orderId[=:](\d{10,})',  # orderId=123456789 或 orderId:123456789
                        r'order_detail\?id=(\d{10,})',  # order_detail?id=123456789
                        r'"id"\s*:\s*"?(\d{10,})"?',  # "id":"123456789" 或 "id":123456789
                        r'bizOrderId[=:](\d{10,})',  # bizOrderId=123456789
                    ]

                    for pattern in patterns:
                        matches = re.findall(pattern, message_str)
                        if matches:
                            # 取第一个匹配的订单ID
                            order_id = matches[0]
                            logger.info(f'✅ 从消息字符串中提取到订单ID: {order_id} (模式: {pattern})')
                            break

                except Exception as search_e:
                    logger.error(f"在消息字符串中搜索订单ID失败: {search_e}")
            
            if order_id:
                logger.info(f'🎯 最终提取到订单ID: {order_id}')
            else:
                logger.error(f'❌ 未能从消息中提取到订单ID')
            
            return order_id
        
        except Exception as e:
            logger.error(f"提取订单ID失败: {str(e)}")
            return None
    
    def update_order_status(self, order_id: str, new_status: str, cookie_id: str, context: str = "") -> bool:
        """更新订单状态到数据库
        
        Args:
            order_id: 订单ID
            new_status: 新状态 (processing/pending_ship/shipped/completed/cancelled)
            cookie_id: Cookie ID
            context: 上下文信息，用于日志记录
            
        Returns:
            bool: 更新是否成功
        """
        logger.info(f"🔄 订单状态处理器.update_order_status开始: order_id={order_id}, new_status={new_status}, cookie_id={cookie_id}, context={context}")
        with self._lock:
            try:
                from db_manager import db_manager
                
                # 验证状态值是否有效
                if new_status not in self.status_mapping:
                    logger.error(f"❌ 无效的订单状态: {new_status}，有效状态: {list(self.status_mapping.keys())}")
                    return False
                
                logger.info(f"✅ 订单状态验证通过: {new_status}")
                
                # 检查订单是否存在于数据库中（带重试机制）
                current_order = None
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        logger.info(f"🔍 尝试获取订单信息 (尝试 {attempt + 1}/{max_retries}): {order_id}")
                        current_order = db_manager.get_order_by_id(order_id)
                        logger.info(f"✅ 订单信息获取成功: {order_id}")
                        break
                    except Exception as db_e:
                        if attempt == max_retries - 1:
                            logger.error(f"❌ 获取订单信息失败 (尝试 {attempt + 1}/{max_retries}): {str(db_e)}")
                            return False
                        else:
                            logger.error(f"⚠️ 获取订单信息失败，重试中 (尝试 {attempt + 1}/{max_retries}): {str(db_e)}")
                            time.sleep(0.1 * (attempt + 1))  # 递增延迟
                
                if not current_order:
                    # 订单不存在，根据配置决定是否添加到待处理队列
                    logger.info(f"⚠️ 订单 {order_id} 不存在于数据库中")
                    if self.config.get('use_pending_queue', True):
                        logger.info(f"📝 订单 {order_id} 不存在于数据库中，添加到待处理队列等待主程序拉取订单详情")
                        self._add_to_pending_updates(order_id, new_status, cookie_id, context)
                    else:
                        logger.error(f"❌ 订单 {order_id} 不存在于数据库中且未启用待处理队列，跳过状态更新")
                    return False
                
                current_status = current_order.get('order_status', 'processing')
                logger.info(f"📊 当前订单状态: {current_status}, 目标状态: {new_status}")
                
                # 检查是否是相同的状态更新（避免重复处理）
                if current_status == new_status:
                    status_text = self.status_mapping.get(new_status, new_status)
                    logger.info(f"⏭️ 订单 {order_id} 状态无变化，跳过重复更新: {status_text}")
                    return True  # 返回True表示"成功"，避免重复日志
                
                # 检查状态转换是否合理（根据配置决定是否启用严格验证）
                if self.config.get('strict_validation', True) and not self._is_valid_status_transition(current_status, new_status):
                    logger.error(f"❌ 订单 {order_id} 状态转换不合理: {current_status} -> {new_status} (严格验证已启用)")
                    logger.error(f"当前状态 '{current_status}' 允许转换到: {self._get_allowed_transitions(current_status)}")
                    return False
                
                logger.info(f"✅ 状态转换验证通过: {current_status} -> {new_status}")
                
                # 处理退款撤销的特殊逻辑
                if new_status == 'refund_cancelled':
                    # 从历史记录中获取上一次状态
                    previous_status = self._get_previous_status(order_id)
                    if previous_status:
                        logger.info(f"🔄 退款撤销，回退到上一次状态: {previous_status}")
                        new_status = previous_status
                    else:
                        logger.warning(f"⚠️ 退款撤销但无法获取上一次状态，保持当前状态: {current_status}")
                        new_status = current_status
                
                # 更新订单状态（带乐观锁和重试机制）
                success = False
                current_version = current_order.get('version', 1)
                for attempt in range(max_retries):
                    try:
                        logger.info(f"💾 尝试更新订单状态 (尝试 {attempt + 1}/{max_retries}): {order_id}, version={current_version}")
                        success = db_manager.insert_or_update_order(
                            order_id=order_id,
                            order_status=new_status,
                            cookie_id=cookie_id,
                            expected_version=current_version
                        )
                        if success:
                            logger.info(f"✅ 订单状态更新成功: {order_id}")
                            break
                        else:
                            # 乐观锁冲突，重新获取订单信息
                            logger.warning(f"⚠️ 订单状态更新失败（版本冲突），重新获取订单信息 (尝试 {attempt + 1}/{max_retries})")
                            time.sleep(0.1 * (attempt + 1))  # 递增延迟
                            current_order = db_manager.get_order_by_id(order_id)
                            if not current_order:
                                logger.error(f"❌ 重新获取订单信息失败: {order_id}")
                                return False
                            current_version = current_order.get('version', 1)
                            current_status = current_order.get('order_status', 'processing')
                            # 检查是否已经被更新为目标状态
                            if current_status == new_status:
                                logger.info(f"✅ 订单 {order_id} 已被其他线程更新为目标状态: {new_status}")
                                return True
                    except Exception as db_e:
                        if attempt == max_retries - 1:
                            logger.error(f"❌ 更新订单状态失败 (尝试 {attempt + 1}/{max_retries}): {str(db_e)}")
                            return False
                        else:
                            logger.error(f"⚠️ 更新订单状态失败，重试中 (尝试 {attempt + 1}/{max_retries}): {str(db_e)}")
                            time.sleep(0.1 * (attempt + 1))  # 递增延迟
                
                if success:
                    # 记录状态历史（用于退款撤销时回退）
                    self._record_status_history(order_id, current_status, new_status, context)
                    
                    status_text = self.status_mapping.get(new_status, new_status)
                    if self.config.get('enable_status_logging', True):
                        logger.info(f"✅ 订单状态更新成功: {order_id} -> {status_text} ({context})")
                else:
                    logger.error(f"❌ 订单状态更新失败: {order_id} -> {new_status} ({context})")
                
                return success
                
            except Exception as e:
                logger.error(f"更新订单状态时出错: {str(e)}")
                import traceback
                logger.error(f"详细错误信息: {traceback.format_exc()}")
                return False
    
    def _is_valid_status_transition(self, current_status: str, new_status: str) -> bool:
        """检查状态转换是否合理
        
        Args:
            current_status: 当前状态
            new_status: 新状态
            
        Returns:
            bool: 转换是否合理
        """
        # 如果当前状态不在规则中，允许转换（兼容性）
        if current_status not in self.VALID_TRANSITIONS:
            return True
        
        # 特殊规则：已付款的订单和已完成的订单不能回退到处理中
        if new_status == 'processing' and current_status in ['pending_ship', 'shipped', 'completed', 'refunding', 'refund_cancelled']:
            logger.warning(f"❌ 状态转换被拒绝：{current_status} -> {new_status} (已付款/已完成的订单不能回退到处理中)")
            return False
        
        # 检查新状态是否在允许的转换列表中
        allowed_statuses = self.VALID_TRANSITIONS.get(current_status, [])
        return new_status in allowed_statuses
    
    def _get_allowed_transitions(self, current_status: str) -> list:
        """获取当前状态允许转换到的状态列表
        
        Args:
            current_status: 当前状态
            
        Returns:
            list: 允许转换到的状态列表
        """
        if current_status not in self.VALID_TRANSITIONS:
            return ['所有状态']  # 兼容性
        
        return self.VALID_TRANSITIONS.get(current_status, [])
    
    def _check_refund_message(self, message: dict, send_message: str) -> Optional[str]:
        """检查退款申请消息，需要同时识别标题和按钮文本
        
        Args:
            message: 原始消息数据
            send_message: 消息内容
            
        Returns:
            str: 对应的状态，如果不是退款消息则返回None
        """
        try:
            # 检查消息结构，寻找退款相关的信息
            message_1 = message.get('1', {})
            if not isinstance(message_1, dict):
                return None
            
            # 检查消息卡片内容
            message_1_6 = message_1.get('6', {})
            if not isinstance(message_1_6, dict):
                return None
            
            # 解析JSON内容
            content_json_str = message_1_6.get('3', {}).get('5', '') if isinstance(message_1_6.get('3', {}), dict) else ''
            if not content_json_str:
                return None
            
            try:
                content_data = json.loads(content_json_str)
                
                # 检查dynamicOperation中的内容
                dynamic_content = content_data.get('dynamicOperation', {}).get('changeContent', {})
                if not dynamic_content:
                    return None
                
                dx_card = dynamic_content.get('dxCard', {}).get('item', {}).get('main', {})
                if not dx_card:
                    return None
                
                ex_content = dx_card.get('exContent', {})
                if not ex_content:
                    return None
                
                # 获取标题和按钮文本
                title = ex_content.get('title', '')
                button_text = ex_content.get('button', {}).get('text', '')
                
                logger.info(f"🔍 检查退款消息 - 标题: '{title}', 按钮: '{button_text}'")
                
                # 检查是否是退款申请且已同意
                if title == '我发起了退款申请' and button_text == '已同意':
                    logger.info(f"✅ 识别到退款申请已同意消息")
                    return 'refunding'
                
                # 检查是否是退款撤销（买家主动撤销）
                if title == '我发起了退款申请' and button_text == '已撤销':
                    logger.info(f"✅ 识别到退款撤销消息")
                    return 'refund_cancelled'
                
                # 退款申请被拒绝不需要改变状态，因为没同意
                # if title == '我发起了退款申请' and button_text == '已拒绝':
                #     logger.info(f"ℹ️ 识别到退款申请被拒绝消息，不改变订单状态")
                #     return None
                
            except Exception as parse_e:
                logger.debug(f"解析退款消息JSON失败: {parse_e}")
                return None
            
            return None
            
        except Exception as e:
            logger.debug(f"检查退款消息失败: {e}")
            return None
    
    def _record_status_history(self, order_id: str, from_status: str, to_status: str, context: str):
        """记录订单状态历史
        
        Args:
            order_id: 订单ID
            from_status: 原状态
            to_status: 新状态
            context: 上下文信息
        """
        with self._lock:
            if order_id not in self._order_status_history:
                self._order_status_history[order_id] = []
            
            # 只记录非临时状态的历史（排除 refund_cancelled）
            if to_status != 'refund_cancelled':
                history_entry = {
                    'from_status': from_status,
                    'to_status': to_status,
                    'context': context,
                    'timestamp': time.time()
                }
                self._order_status_history[order_id].append(history_entry)
                
                # 限制历史记录数量，只保留最近10条
                if len(self._order_status_history[order_id]) > 10:
                    self._order_status_history[order_id] = self._order_status_history[order_id][-10:]
                
                logger.debug(f"📝 记录订单状态历史: {order_id} {from_status} -> {to_status}")
    
    def _get_previous_status(self, order_id: str) -> Optional[str]:
        """获取订单的上一次状态（用于退款撤销时回退）
        
        Args:
            order_id: 订单ID
            
        Returns:
            str: 上一次状态，如果没有历史记录则返回None
        """
        with self._lock:
            if order_id not in self._order_status_history or not self._order_status_history[order_id]:
                return None
            
            # 退款撤销应恢复到进入退款状态之前的状态，而不是继续停留在退款中。
            for entry in reversed(self._order_status_history[order_id]):
                if entry.get('to_status') == 'refunding':
                    return entry.get('from_status')

            last_entry = self._order_status_history[order_id][-1]
            return last_entry.get('from_status')
    
    def _add_to_pending_updates(self, order_id: str, new_status: str, cookie_id: str, context: str):
        """添加到待处理更新队列
        
        Args:
            order_id: 订单ID
            new_status: 新状态
            cookie_id: Cookie ID
            context: 上下文信息
        """
        with self._lock:
            if order_id not in self.pending_updates:
                self.pending_updates[order_id] = []
            
            update_info = {
                'new_status': new_status,
                'cookie_id': cookie_id,
                'context': context,
                'timestamp': time.time()
            }
            
            self.pending_updates[order_id].append(update_info)
            logger.info(f"订单 {order_id} 状态更新已添加到待处理队列: {new_status} ({context})")
    
    def process_pending_updates(self, order_id: str) -> bool:
        """处理指定订单的待处理更新
        
        Args:
            order_id: 订单ID
            
        Returns:
            bool: 是否有更新被处理
        """
        with self._lock:
            if order_id not in self.pending_updates:
                return False
            
            updates = self.pending_updates.pop(order_id)
            processed_count = 0
        
        for update_info in updates:
            try:
                success = self.update_order_status(
                    order_id=order_id,
                    new_status=update_info['new_status'],
                    cookie_id=update_info['cookie_id'],
                    context=f"待处理队列: {update_info['context']}"
                )
                
                if success:
                    processed_count += 1
                    logger.info(f"处理待处理更新成功: 订单 {order_id} -> {update_info['new_status']}")
                else:
                    logger.error(f"处理待处理更新失败: 订单 {order_id} -> {update_info['new_status']}")
                    
            except Exception as e:
                logger.error(f"处理待处理更新时出错: {str(e)}")
        
        if processed_count > 0:
            logger.info(f"订单 {order_id} 共处理了 {processed_count} 个待处理状态更新")
        
        return processed_count > 0
    
    def process_all_pending_updates(self) -> int:
        """处理所有待处理的更新
        
        Returns:
            int: 处理的订单数量
        """
        with self._lock:
            if not self.pending_updates:
                return 0
            
            order_ids = list(self.pending_updates.keys())
            processed_orders = 0
        
        for order_id in order_ids:
            if self.process_pending_updates(order_id):
                processed_orders += 1
        
        return processed_orders
    
    def get_pending_updates_count(self) -> int:
        """获取待处理更新的数量
        
        Returns:
            int: 待处理更新的数量
        """
        with self._lock:
            return len(self.pending_updates)
    
    def clear_old_pending_updates(self, max_age_hours: int = None):
        """清理过期的待处理更新
        
        Args:
            max_age_hours: 最大保留时间（小时），如果为None则使用配置中的默认值
        """
        # 检查是否启用待处理队列
        if not self.config.get('use_pending_queue', True):
            logger.error("未启用待处理队列，跳过清理操作")
            return
        
        if max_age_hours is None:
            max_age_hours = self.config.get('max_pending_age_hours', 24)
        
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        with self._lock:
            # 清理 pending_updates
            expired_orders = []
            for order_id, updates in self.pending_updates.items():
                # 过滤掉过期的更新
                valid_updates = [
                    update for update in updates 
                    if current_time - update['timestamp'] < max_age_seconds
                ]
                
                if not valid_updates:
                    expired_orders.append(order_id)
                else:
                    self.pending_updates[order_id] = valid_updates
            
            # 移除完全过期的订单
            for order_id in expired_orders:
                del self.pending_updates[order_id]
                logger.info(f"清理过期的待处理更新: 订单 {order_id}")
            
            if expired_orders:
                logger.info(f"共清理了 {len(expired_orders)} 个过期的待处理订单更新")
            
            # 清理 _pending_system_messages
            expired_cookies_system = []
            for cookie_id, messages in self._pending_system_messages.items():
                valid_messages = [
                    msg for msg in messages 
                    if current_time - msg.get('timestamp', 0) < max_age_seconds
                ]
                
                if not valid_messages:
                    expired_cookies_system.append(cookie_id)
                else:
                    self._pending_system_messages[cookie_id] = valid_messages
            
            for cookie_id in expired_cookies_system:
                del self._pending_system_messages[cookie_id]
                logger.info(f"清理过期的待处理系统消息: 账号 {cookie_id}")
            
            # 清理 _pending_red_reminder_messages
            expired_cookies_red = []
            for cookie_id, messages in self._pending_red_reminder_messages.items():
                valid_messages = [
                    msg for msg in messages 
                    if current_time - msg.get('timestamp', 0) < max_age_seconds
                ]
                
                if not valid_messages:
                    expired_cookies_red.append(cookie_id)
                else:
                    self._pending_red_reminder_messages[cookie_id] = valid_messages
            
            for cookie_id in expired_cookies_red:
                del self._pending_red_reminder_messages[cookie_id]
                logger.info(f"清理过期的待处理红色提醒消息: 账号 {cookie_id}")
            
            total_cleared = len(expired_orders) + len(expired_cookies_system) + len(expired_cookies_red)
            if total_cleared > 0:
                logger.info(f"内存清理完成，共清理了 {total_cleared} 个过期项目")
    
    def handle_system_message(self, message: dict, send_message: str, cookie_id: str, msg_time: str) -> bool:
        """处理系统消息并更新订单状态
        
        Args:
            message: 原始消息数据
            send_message: 消息内容
            cookie_id: Cookie ID
            msg_time: 消息时间
            
        Returns:
            bool: 是否处理了订单状态更新
        """
        try:
            # 定义消息类型与状态的映射
            message_status_mapping = {
                '[买家确认收货，交易成功]': 'completed',
                '[你已确认收货，交易成功]': 'completed',  # 已完成
                '[你已发货]': 'shipped',  # 已发货
                '你已发货': 'shipped',  # 已发货（无方括号）
                '[你已发货，请等待买家确认收货]': 'shipped',  # 已发货（完整格式）
                '[我已付款，等待你发货]': 'pending_ship',  # 已付款，等待发货
                '[我已拍下，待付款]': 'processing',  # 已拍下，待付款
                '[买家已付款]': 'pending_ship',  # 买家已付款
                '[付款完成]': 'pending_ship',  # 付款完成
                '[已付款，待发货]': 'pending_ship',  # 已付款，待发货
                '[退款成功，钱款已原路退返]': 'cancelled',  # 退款成功，设置为已关闭
                '[你关闭了订单，钱款已原路退返]': 'cancelled',  # 卖家关闭订单，设置为已关闭
            }
            
            # 特殊处理：检查退款申请消息（需要同时识别标题和按钮文本）
            refund_status = self._check_refund_message(message, send_message)
            if refund_status:
                new_status = refund_status
            elif send_message in message_status_mapping:
                new_status = message_status_mapping[send_message]
            else:
                return False
            
            # 提取订单ID
            order_id = self.extract_order_id(message)
            if not order_id:
                # 如果无法提取订单ID，根据配置决定是否添加到待处理队列
                if not self.config.get('use_pending_queue', True):
                    logger.error(f'[{msg_time}] 【{cookie_id}】{send_message}，无法提取订单ID且未启用待处理队列，跳过处理')
                    return False
                
                # 创建一个临时的订单ID占位符，用于标识这个待处理的状态更新
                temp_order_id = f"temp_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

                # 添加到待处理队列，使用特殊标记
                self._add_to_pending_updates(
                    order_id=temp_order_id,
                    new_status=new_status,
                    cookie_id=cookie_id,
                    context=f"{send_message} - {msg_time} - 等待订单ID提取"
                )
                
                # 添加到待处理的系统消息队列
                if cookie_id not in self._pending_system_messages:
                    self._pending_system_messages[cookie_id] = []
                
                self._pending_system_messages[cookie_id].append({
                    'message': message,
                    'send_message': send_message,
                    'cookie_id': cookie_id,
                    'msg_time': msg_time,
                    'new_status': new_status,
                    'temp_order_id': temp_order_id,
                    'message_hash': hash(str(sorted(message.items()))) if isinstance(message, dict) else hash(str(message)),  # 添加消息哈希用于匹配
                    'timestamp': time.time()  # 添加时间戳用于清理
                })

                logger.info(f'[{msg_time}] 【{cookie_id}】{send_message}，暂时无法提取订单ID，已添加到待处理队列')
                return True
            
            # 获取对应的状态（new_status已经在上面通过_check_refund_message或message_status_mapping确定了）
            
            # 检查当前订单状态，避免不合理的状态回退
            from db_manager import db_manager
            current_order = db_manager.get_order_by_id(order_id)
            
            # 如果订单存在，检查是否需要忽略这次状态更新
            if current_order and current_order.get('order_status'):
                current_status = current_order.get('order_status')
                
                # 定义状态优先级（数字越大，状态越靠后）
                status_priority = {
                    'processing': 1,      # 处理中
                    'pending_ship': 2,    # 待发货
                    'shipped': 3,         # 已发货
                    'completed': 4,       # 已完成
                    'refunding': 2,       # 退款中（与待发货同级）
                    'cancelled': 5,       # 已取消（终态）
                }
                
                current_priority = status_priority.get(current_status, 0)
                new_priority = status_priority.get(new_status, 0)
                
                # 如果新状态的优先级低于当前状态，且不是特殊状态（退款、取消），则忽略
                if new_priority < current_priority and new_status not in ['refunding', 'cancelled']:
                    logger.warning(f'[{msg_time}] 【{cookie_id}】{send_message}，订单 {order_id} 当前状态为 {current_status}，忽略回退到 {new_status}')
                    return True  # 返回True表示已处理，但实际上是忽略
            
            # 更新订单状态
            success = self.update_order_status(
                order_id=order_id,
                new_status=new_status,
                cookie_id=cookie_id,
                context=f"{send_message} - {msg_time}"
            )
            
            if success:
                status_text = self.status_mapping.get(new_status, new_status)
                logger.info(f'[{msg_time}] 【{cookie_id}】{send_message}，订单 {order_id} 状态已更新为{status_text}')
            else:
                logger.error(f'[{msg_time}] 【{cookie_id}】{send_message}，但订单 {order_id} 状态更新失败')
            
            return True
            
        except Exception as e:
            logger.error(f'[{msg_time}] 【{cookie_id}】处理系统消息订单状态更新时出错: {str(e)}')
            return False
    
    def handle_red_reminder_message(self, message: dict, red_reminder: str, user_id: str, cookie_id: str, msg_time: str) -> bool:
        """处理红色提醒消息并更新订单状态
        
        Args:
            message: 原始消息数据
            red_reminder: 红色提醒内容
            user_id: 用户ID
            cookie_id: Cookie ID
            msg_time: 消息时间
            
        Returns:
            bool: 是否处理了订单状态更新
        """
        try:
            # 只处理交易关闭的情况
            if red_reminder != '交易关闭':
                return False
            
            # 提取订单ID
            order_id = self.extract_order_id(message)
            if not order_id:
                # 如果无法提取订单ID，根据配置决定是否添加到待处理队列
                if not self.config.get('use_pending_queue', True):
                    logger.error(f'[{msg_time}] 【{cookie_id}】交易关闭，无法提取订单ID且未启用待处理队列，跳过处理')
                    return False
                
                # 创建一个临时的订单ID占位符，用于标识这个待处理的状态更新
                temp_order_id = f"temp_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
                
                # 添加到待处理队列，使用特殊标记
                self._add_to_pending_updates(
                    order_id=temp_order_id,
                    new_status='cancelled',
                    cookie_id=cookie_id,
                    context=f"交易关闭 - 用户{user_id} - {msg_time} - 等待订单ID提取"
                )
                
                # 添加到待处理的红色提醒消息队列
                if cookie_id not in self._pending_red_reminder_messages:
                    self._pending_red_reminder_messages[cookie_id] = []
                
                self._pending_red_reminder_messages[cookie_id].append({
                    'message': message,
                    'red_reminder': red_reminder,
                    'user_id': user_id,
                    'cookie_id': cookie_id,
                    'msg_time': msg_time,
                    'new_status': 'cancelled',
                    'temp_order_id': temp_order_id,
                    'message_hash': hash(str(sorted(message.items()))) if isinstance(message, dict) else hash(str(message)),  # 添加消息哈希用于匹配
                    'timestamp': time.time()  # 添加时间戳用于清理
                })

                logger.info(f'[{msg_time}] 【{cookie_id}】交易关闭，暂时无法提取订单ID，已添加到待处理队列')
                return True
            
            # 更新订单状态为已关闭
            success = self.update_order_status(
                order_id=order_id,
                new_status='cancelled',
                cookie_id=cookie_id,
                context=f"交易关闭 - 用户{user_id} - {msg_time}"
            )
            
            if success:
                logger.info(f'[{msg_time}] 【{cookie_id}】交易关闭，订单 {order_id} 状态已更新为已关闭')
            else:
                logger.error(f'[{msg_time}] 【{cookie_id}】交易关闭，但订单 {order_id} 状态更新失败')
            
            return True
            
        except Exception as e:
            logger.error(f'[{msg_time}] 【{cookie_id}】处理交易关闭订单状态更新时出错: {str(e)}')
            return False
    
    def handle_auto_delivery_order_status(self, order_id: str, cookie_id: str, context: str = "自动发货") -> bool:
        """处理自动发货时的订单状态更新
        
        Args:
            order_id: 订单ID
            cookie_id: Cookie ID
            context: 上下文信息
            
        Returns:
            bool: 更新是否成功
        """
        return self.update_order_status(
            order_id=order_id,
            new_status='shipped',  # 已发货
            cookie_id=cookie_id,
            context=context
        )
    
    def handle_order_basic_info_status(self, order_id: str, cookie_id: str, context: str = "基本信息保存") -> bool:
        """处理订单基本信息保存时的状态设置
        
        Args:
            order_id: 订单ID
            cookie_id: Cookie ID
            context: 上下文信息
            
        Returns:
            bool: 更新是否成功
        """
        return self.update_order_status(
            order_id=order_id,
            new_status='processing',  # 处理中
            cookie_id=cookie_id,
            context=context
        )
    
    def handle_order_detail_fetched_status(self, order_id: str, cookie_id: str, context: str = "详情已获取") -> bool:
        """处理订单详情拉取后的状态设置
        
        Args:
            order_id: 订单ID
            cookie_id: Cookie ID
            context: 上下文信息
            
        Returns:
            bool: 更新是否成功
        """
        logger.info(f"🔄 订单状态处理器.handle_order_detail_fetched_status开始: order_id={order_id}, cookie_id={cookie_id}, context={context}")
        
        # 订单详情获取成功后，不需要改变状态，只是处理待处理队列
        logger.info(f"✅ 订单详情已获取，处理待处理队列: order_id={order_id}")
        return True
    
    def on_order_details_fetched(self, order_id: str):
        """当主程序拉取到订单详情后调用此方法处理待处理的更新
        
        Args:
            order_id: 订单ID
        """
        logger.info(f"🔄 订单状态处理器.on_order_details_fetched开始: order_id={order_id}")
        
        # 检查是否启用待处理队列
        if not self.config.get('use_pending_queue', True):
            logger.info(f"⏭️ 订单 {order_id} 详情已拉取，但未启用待处理队列，跳过处理")
            return
        
        logger.info(f"✅ 待处理队列已启用，检查订单 {order_id} 的待处理更新")
        
        with self._lock:
            if order_id in self.pending_updates:
                logger.info(f"📝 检测到订单 {order_id} 详情已拉取，开始处理待处理的状态更新")
                # 注意：process_pending_updates 内部也有锁，这里需要先释放锁避免死锁
                updates = self.pending_updates.pop(order_id)
                logger.info(f"📊 订单 {order_id} 有 {len(updates)} 个待处理更新")
            else:
                logger.info(f"ℹ️ 订单 {order_id} 没有待处理的更新")
                return
        
        # 在锁外处理更新，避免死锁
        if 'updates' in locals():
            logger.info(f"🔄 开始处理订单 {order_id} 的 {len(updates)} 个待处理更新")
            self._process_updates_outside_lock(order_id, updates)
            logger.info(f"✅ 订单 {order_id} 的待处理更新处理完成")
    
    def _process_updates_outside_lock(self, order_id: str, updates: list):
        """在锁外处理更新，避免死锁
        
        Args:
            order_id: 订单ID
            updates: 更新列表
        """
        processed_count = 0
        
        for update_info in updates:
            try:
                success = self.update_order_status(
                    order_id=order_id,
                    new_status=update_info['new_status'],
                    cookie_id=update_info['cookie_id'],
                    context=f"待处理队列: {update_info['context']}"
                )
                
                if success:
                    processed_count += 1
                    logger.info(f"处理待处理更新成功: 订单 {order_id} -> {update_info['new_status']}")
                else:
                    logger.error(f"处理待处理更新失败: 订单 {order_id} -> {update_info['new_status']}")
                    
            except Exception as e:
                logger.error(f"处理待处理更新时出错: {str(e)}")
        
        if processed_count > 0:
            logger.info(f"订单 {order_id} 共处理了 {processed_count} 个待处理状态更新")
    
    def on_order_id_extracted(self, order_id: str, cookie_id: str, message: dict = None):
        """当主程序成功提取到订单ID后调用此方法处理待处理的系统消息
        
        Args:
            order_id: 订单ID
            cookie_id: Cookie ID
            message: 原始消息（可选，用于匹配）
        """
        logger.info(f"🔄 订单状态处理器.on_order_id_extracted开始: order_id={order_id}, cookie_id={cookie_id}")
        
        with self._lock:
            # 检查是否启用待处理队列
            if not self.config.get('use_pending_queue', True):
                logger.info(f"⏭️ 订单 {order_id} ID已提取，但未启用待处理队列，跳过处理")
                return
            
            logger.info(f"✅ 待处理队列已启用，检查账号 {cookie_id} 的待处理系统消息")
            
            # 处理待处理的系统消息队列
            if cookie_id in self._pending_system_messages and self._pending_system_messages[cookie_id]:
                logger.info(f"📝 账号 {cookie_id} 有 {len(self._pending_system_messages[cookie_id])} 个待处理的系统消息")
                pending_msg = None
                
                # 如果提供了消息，尝试匹配
                if message:
                    logger.info(f"🔍 尝试通过消息哈希匹配待处理的系统消息")
                    message_hash = hash(str(sorted(message.items()))) if isinstance(message, dict) else hash(str(message))
                    # 从后往前遍历，避免pop时索引变化问题
                    for i in range(len(self._pending_system_messages[cookie_id]) - 1, -1, -1):
                        msg = self._pending_system_messages[cookie_id][i]
                        if msg.get('message_hash') == message_hash:
                            pending_msg = self._pending_system_messages[cookie_id].pop(i)
                            logger.info(f"✅ 通过消息哈希匹配到待处理的系统消息: {pending_msg['send_message']}")
                            break
                
                # 如果没有匹配到，使用FIFO原则
                if not pending_msg and self._pending_system_messages[cookie_id]:
                    pending_msg = self._pending_system_messages[cookie_id].pop(0)
                    logger.info(f"✅ 使用FIFO原则处理待处理的系统消息: {pending_msg['send_message']}")
                
                if pending_msg:
                    logger.info(f"🔄 开始处理待处理的系统消息: {pending_msg['send_message']}")
                    
                    # 更新订单状态
                    success = self.update_order_status(
                        order_id=order_id,
                        new_status=pending_msg['new_status'],
                        cookie_id=cookie_id,
                        context=f"{pending_msg['send_message']} - {pending_msg['msg_time']} - 延迟处理"
                    )
                    
                    if success:
                        status_text = self.status_mapping.get(pending_msg['new_status'], pending_msg['new_status'])
                        logger.info(f'✅ [{pending_msg["msg_time"]}] 【{cookie_id}】{pending_msg["send_message"]}，订单 {order_id} 状态已更新为{status_text} (延迟处理)')
                    else:
                        logger.error(f'❌ [{pending_msg["msg_time"]}] 【{cookie_id}】{pending_msg["send_message"]}，但订单 {order_id} 状态更新失败 (延迟处理)')
                    
                    # 清理临时订单ID的待处理更新
                    temp_order_id = pending_msg['temp_order_id']
                    if temp_order_id in self.pending_updates:
                        del self.pending_updates[temp_order_id]
                        logger.info(f"🗑️ 清理临时订单ID {temp_order_id} 的待处理更新")
                    
                    # 如果队列为空，删除该账号的队列
                    if not self._pending_system_messages[cookie_id]:
                        del self._pending_system_messages[cookie_id]
                        logger.info(f"🗑️ 账号 {cookie_id} 的待处理系统消息队列已清空")
                else:
                    logger.info(f"ℹ️ 订单 {order_id} ID已提取，但没有找到对应的待处理系统消息")
            else:
                logger.info(f"ℹ️ 账号 {cookie_id} 没有待处理的系统消息")
            
            # 处理待处理的红色提醒消息队列
            if cookie_id in self._pending_red_reminder_messages and self._pending_red_reminder_messages[cookie_id]:
                pending_msg = None
                
                # 如果提供了消息，尝试匹配
                if message:
                    message_hash = hash(str(sorted(message.items()))) if isinstance(message, dict) else hash(str(message))
                    # 从后往前遍历，避免pop时索引变化问题
                    for i in range(len(self._pending_red_reminder_messages[cookie_id]) - 1, -1, -1):
                        msg = self._pending_red_reminder_messages[cookie_id][i]
                        if msg.get('message_hash') == message_hash:
                            pending_msg = self._pending_red_reminder_messages[cookie_id].pop(i)
                            logger.info(f"通过消息哈希匹配到待处理的红色提醒消息: {pending_msg['red_reminder']}")
                            break
                
                # 如果没有匹配到，使用FIFO原则
                if not pending_msg and self._pending_red_reminder_messages[cookie_id]:
                    pending_msg = self._pending_red_reminder_messages[cookie_id].pop(0)
                    logger.info(f"使用FIFO原则处理待处理的红色提醒消息: {pending_msg['red_reminder']}")
                
                if pending_msg:
                    logger.info(f"检测到订单 {order_id} ID已提取，开始处理待处理的红色提醒消息: {pending_msg['red_reminder']}")
                    
                    # 更新订单状态
                    success = self.update_order_status(
                        order_id=order_id,
                        new_status=pending_msg['new_status'],
                        cookie_id=cookie_id,
                        context=f"{pending_msg['red_reminder']} - 用户{pending_msg['user_id']} - {pending_msg['msg_time']} - 延迟处理"
                    )
                    
                    if success:
                        status_text = self.status_mapping.get(pending_msg['new_status'], pending_msg['new_status'])
                        logger.info(f'[{pending_msg["msg_time"]}] 【{cookie_id}】{pending_msg["red_reminder"]}，订单 {order_id} 状态已更新为{status_text} (延迟处理)')
                    else:
                        logger.error(f'[{pending_msg["msg_time"]}] 【{cookie_id}】{pending_msg["red_reminder"]}，但订单 {order_id} 状态更新失败 (延迟处理)')
                    
                    # 清理临时订单ID的待处理更新
                    temp_order_id = pending_msg['temp_order_id']
                    if temp_order_id in self.pending_updates:
                        del self.pending_updates[temp_order_id]
                        logger.info(f"清理临时订单ID {temp_order_id} 的待处理更新")
                    
                    # 如果队列为空，删除该账号的队列
                    if not self._pending_red_reminder_messages[cookie_id]:
                        del self._pending_red_reminder_messages[cookie_id]
                else:
                    logger.error(f"订单 {order_id} ID已提取，但没有找到对应的待处理红色提醒消息")


# 创建全局实例
order_status_handler = OrderStatusHandler()
