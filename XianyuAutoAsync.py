import asyncio
import json
import re
import time
import base64
import os
import random
from enum import Enum
from loguru import logger
from utils import browser_limit
import websockets
from utils.xianyu_utils import (
    decrypt, generate_mid, generate_uuid, trans_cookies,
    generate_device_id, generate_sign, CAPTCHA_CHALLENGE_COOKIES
)
from app.config import (
    WEBSOCKET_URL, HEARTBEAT_INTERVAL, HEARTBEAT_TIMEOUT,
    TOKEN_REFRESH_INTERVAL, TOKEN_RETRY_INTERVAL, COOKIES_STR,
    LOG_CONFIG, AUTO_REPLY, DEFAULT_HEADERS, WEBSOCKET_HEADERS,
    APP_CONFIG, API_ENDPOINTS
)
from app.config import config as cfg  # 导入config实例（不是模块），使用别名避免冲突
import sys
import aiohttp
from collections import defaultdict
from app.db_manager import db_manager
from app.specification import combine_legacy_specification
from utils.log_sanitizer import redact_log_record, redact_sensitive_text

# 滑块验证补丁已废弃，使用集成的 Playwright 登录方法
# 不再需要猴子补丁，所有功能已集成到 XianyuSliderStealth 类中

class ConnectionState(Enum):
    """WebSocket连接状态枚举"""
    DISCONNECTED = "disconnected"  # 未连接
    CONNECTING = "connecting"  # 连接中
    CONNECTED = "connected"  # 已连接
    RECONNECTING = "reconnecting"  # 重连中
    FAILED = "failed"  # 连接失败
    CLOSED = "closed"  # 已关闭


class ItemListTransientError(Exception):
    """商品列表接口的临时故障（网关 5xx、响应不是 JSON 等）。

    与业务错误区分开：这类故障重试就可能好，不该被写成“未返回在售分组”
    之类的数据结论，否则用户会以为是账号或商品的问题。
    """


class AutoReplyPauseManager:
    """自动回复暂停管理器（人工接入后暂停该会话的自动回复）。

    键必须是 (cookie_id, chat_id) 而不是单独的 chat_id。这是个全局单例，
    所有账号共用；chat_id 标识的是一个会话，当用户自己的两个账号正好是同一个
    会话的两端时（测试自动回复时最常见的做法），两边拿到的是同一个 chat_id。
    于是 A 账号手动发一条消息，就会把 B 账号对这个会话的自动回复一起停掉，
    表现为「关键词明明配好了却不回」，而唯一线索只有一行 info 日志。
    """
    def __init__(self):
        # {(cookie_id, chat_id): pause_until_timestamp}
        self.paused_chats = {}

    @staticmethod
    def _key(cookie_id: str, chat_id: str):
        return (str(cookie_id), str(chat_id))

    def pause_chat(self, chat_id: str, cookie_id: str):
        """暂停指定账号下该 chat_id 的自动回复，使用账号特定的暂停时间"""
        # 获取账号特定的暂停时间
        try:
            from app.db_manager import db_manager
            pause_minutes = db_manager.get_cookie_pause_duration(cookie_id)
        except Exception as e:
            logger.error(f"获取账号 {cookie_id} 暂停时间失败: {e}，使用默认10分钟")
            pause_minutes = 10

        # 如果暂停时间为0，表示不暂停
        if pause_minutes == 0:
            logger.info(f"【{cookie_id}】检测到手动发出消息，但暂停时间设置为0，不暂停自动回复")
            return

        pause_duration_seconds = pause_minutes * 60
        pause_until = time.time() + pause_duration_seconds
        self.paused_chats[self._key(cookie_id, chat_id)] = pause_until

        # 计算暂停结束时间
        end_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(pause_until))
        logger.info(f"【{cookie_id}】检测到手动发出消息，chat_id {chat_id} 自动回复暂停{pause_minutes}分钟，恢复时间: {end_time}")

    def is_chat_paused(self, chat_id: str, cookie_id: str) -> bool:
        """检查指定账号下该 chat_id 是否处于暂停状态"""
        key = self._key(cookie_id, chat_id)
        pause_until = self.paused_chats.get(key)
        if pause_until is None:
            return False

        if time.time() >= pause_until:
            # 暂停时间已过，移除记录
            del self.paused_chats[key]
            return False

        return True

    def get_remaining_pause_time(self, chat_id: str, cookie_id: str) -> int:
        """获取指定账号下该 chat_id 的剩余暂停时间（秒）"""
        pause_until = self.paused_chats.get(self._key(cookie_id, chat_id))
        if pause_until is None:
            return 0

        return max(0, int(pause_until - time.time()))

    def cleanup_expired_pauses(self):
        """清理已过期的暂停记录"""
        current_time = time.time()
        expired = [key for key, pause_until in self.paused_chats.items()
                   if current_time >= pause_until]

        for key in expired:
            del self.paused_chats[key]


# 全局暂停管理器实例
pause_manager = AutoReplyPauseManager()

def log_captcha_event(cookie_id: str, event_type: str, success: bool = None, details: str = ""):
    """
    简单记录滑块验证事件到txt文件

    Args:
        cookie_id: 账号ID
        event_type: 事件类型 (检测到/开始处理/成功/失败)
        success: 是否成功 (None表示进行中)
        details: 详细信息
    """
    try:
        log_dir = 'logs'
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'captcha_verification.txt')

        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        status = "成功" if success is True else "失败" if success is False else "进行中"

        log_entry = f"[{timestamp}] 【{cookie_id}】{event_type} - {status}"
        if details:
            log_entry += f" - {redact_sensitive_text(details)}"
        log_entry += "\n"

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)

    except Exception as e:
        logger.error(f"记录滑块验证日志失败: {e}")

# 日志配置
log_dir = 'logs'
os.makedirs(log_dir, exist_ok=True)
log_path = os.path.join(log_dir, f"xianyu_{time.strftime('%Y-%m-%d')}.log")
logger.remove()
logger.configure(patcher=redact_log_record)
logger.add(
    log_path,
    rotation=LOG_CONFIG.get('rotation', '1 day'),
    retention=LOG_CONFIG.get('retention', '7 days'),
    compression=LOG_CONFIG.get('compression', 'zip'),
    level=LOG_CONFIG.get('level', 'DEBUG'),
    format=LOG_CONFIG.get('format', '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>'),
    encoding='utf-8',
    enqueue=True
)
logger.add(
    sys.stdout,
    level=LOG_CONFIG.get('level', 'DEBUG'),
    format=LOG_CONFIG.get('format', '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>'),
    enqueue=True
)

class XianyuLive:
    # 类级别的锁字典，为每个order_id维护一个锁（用于自动发货）
    _order_locks = defaultdict(lambda: asyncio.Lock())
    # 记录锁的最后使用时间，用于清理
    _lock_usage_times = {}
    # 记录锁的持有状态和释放时间 {lock_key: {'locked': bool, 'release_time': float, 'task': asyncio.Task}}
    _lock_hold_info = {}

    # 独立的锁字典，用于订单详情获取（不使用延迟锁机制）
    _order_detail_locks = defaultdict(lambda: asyncio.Lock())
    # 记录订单详情锁的使用时间
    _order_detail_lock_times = {}

    # 商品详情缓存（24小时有效）
    _item_detail_cache = {}  # {item_id: {'detail': str, 'timestamp': float, 'access_time': float}}
    _item_detail_cache_lock = asyncio.Lock()
    _item_detail_cache_max_size = 1000  # 最大缓存1000个商品
    _item_detail_cache_ttl = 24 * 60 * 60  # 24小时TTL

    # 类级别的实例管理字典，用于API调用
    _instances = {}  # {cookie_id: XianyuLive实例}
    _instances_lock = asyncio.Lock()
    
    # 类级别的密码登录时间记录，用于防止重复登录
    _last_password_login_time = {}  # {cookie_id: timestamp}
    _password_login_cooldown = 60  # 密码登录冷却时间：60秒
    
    def _safe_str(self, e):
        """安全地将异常转换为字符串"""
        try:
            return str(e)
        except:
            try:
                return repr(e)
            except:
                return "未知错误"

    def _set_connection_state(self, new_state: ConnectionState, reason: str = ""):
        """设置连接状态并记录日志"""
        if self.connection_state != new_state:
            old_state = self.connection_state
            self.connection_state = new_state
            self.last_state_change_time = time.time()
            
            # 记录状态转换
            state_msg = f"【{self.cookie_id}】连接状态: {old_state.value} → {new_state.value}"
            if reason:
                state_msg += f" ({reason})"
            
            # 根据状态严重程度选择日志级别
            if new_state == ConnectionState.FAILED:
                logger.error(state_msg)
            elif new_state == ConnectionState.RECONNECTING:
                logger.warning(state_msg)
            elif new_state == ConnectionState.CONNECTED:
                logger.success(state_msg)
            else:
                logger.info(state_msg)

    async def _interruptible_sleep(self, duration: float):
        """可中断的sleep，将长时间sleep拆分成多个短时间sleep，以便及时响应取消信号
        
        Args:
            duration: 总睡眠时间（秒）
        """
        # 将长时间sleep拆分成多个1秒的短sleep，这样可以及时响应取消信号
        chunk_size = 1.0  # 每次sleep 1秒
        remaining = duration
        
        while remaining > 0:
            sleep_time = min(chunk_size, remaining)
            try:
                await asyncio.sleep(sleep_time)
                remaining -= sleep_time
            except asyncio.CancelledError:
                # 如果收到取消信号，立即抛出
                raise

    def _reset_background_tasks(self):
        """直接重置后台任务引用，不等待取消（用于快速重连）
        
        注意：只重置心跳任务，因为只有心跳任务依赖WebSocket连接。
        其他任务（Token刷新、清理、Cookie刷新）不依赖WebSocket，可以继续运行。
        """
        logger.info(f"【{self.cookie_id}】准备重置后台任务引用（仅重置依赖WebSocket的任务）...")
        
        # 只处理心跳任务（依赖WebSocket，需要重启）
        if self.heartbeat_task:
            status = "已完成" if self.heartbeat_task.done() else "运行中"
            logger.info(f"【{self.cookie_id}】发现心跳任务（状态: {status}），需要重置（因为依赖WebSocket连接）")
            # 尝试取消心跳任务（但不等待）
            if not self.heartbeat_task.done():
                try:
                    self.heartbeat_task.cancel()
                    logger.debug(f"【{self.cookie_id}】已发送取消信号给心跳任务（不等待响应）")
                except Exception as e:
                    logger.warning(f"【{self.cookie_id}】取消心跳任务失败: {e}")
            # 重置心跳任务引用
            self.heartbeat_task = None
            logger.info(f"【{self.cookie_id}】心跳任务引用已重置")
        else:
            logger.info(f"【{self.cookie_id}】没有心跳任务需要重置")
        
        # 检查其他任务的状态（这些任务不依赖WebSocket，不需要重启）
        other_tasks_status = []
        if self.token_refresh_task:
            status = "已完成" if self.token_refresh_task.done() else "运行中"
            other_tasks_status.append(f"Token刷新任务({status})")
        if self.cleanup_task:
            status = "已完成" if self.cleanup_task.done() else "运行中"
            other_tasks_status.append(f"清理任务({status})")
        if self.cookie_refresh_task:
            status = "已完成" if self.cookie_refresh_task.done() else "运行中"
            other_tasks_status.append(f"Cookie刷新任务({status})")
        if self.item_sync_task:
            status = "已完成" if self.item_sync_task.done() else "运行中"
            other_tasks_status.append(f"商品同步任务({status})")
        if self.order_sync_task:
            status = "已完成" if self.order_sync_task.done() else "运行中"
            other_tasks_status.append(f"订单同步任务({status})")
        if self.item_polish_task:
            status = "已完成" if self.item_polish_task.done() else "运行中"
            other_tasks_status.append(f"商品擦亮任务({status})")
        if self.delivery_timeout_task:
            status = "已完成" if self.delivery_timeout_task.done() else "运行中"
            other_tasks_status.append(f"发货超时检查({status})")
        if self.buyer_interaction_task:
            status = "已完成" if self.buyer_interaction_task.done() else "运行中"
            other_tasks_status.append(f"买家互动任务({status})")

        if other_tasks_status:
            logger.info(f"【{self.cookie_id}】其他任务继续运行（不依赖WebSocket）: {', '.join(other_tasks_status)}")
        else:
            logger.info(f"【{self.cookie_id}】没有其他任务在运行")
        
        logger.info(f"【{self.cookie_id}】任务重置完成，可以立即创建新的心跳任务")

    async def _cancel_background_tasks(self):
        """取消并清理所有后台任务（保留此方法用于程序退出时的完整清理）"""
        try:
            tasks_to_cancel = []
            
            # 收集所有需要取消的任务（只收集未完成的任务）
            if self.heartbeat_task:
                if not self.heartbeat_task.done():
                    tasks_to_cancel.append(("心跳任务", self.heartbeat_task))
                else:
                    logger.debug(f"【{self.cookie_id}】心跳任务已完成，跳过")
                    
            if self.token_refresh_task:
                if not self.token_refresh_task.done():
                    tasks_to_cancel.append(("Token刷新任务", self.token_refresh_task))
                else:
                    logger.debug(f"【{self.cookie_id}】Token刷新任务已完成，跳过")
                    
            if self.cleanup_task:
                if not self.cleanup_task.done():
                    tasks_to_cancel.append(("清理任务", self.cleanup_task))
                else:
                    logger.debug(f"【{self.cookie_id}】清理任务已完成，跳过")
                    
            if self.cookie_refresh_task:
                if not self.cookie_refresh_task.done():
                    tasks_to_cancel.append(("Cookie刷新任务", self.cookie_refresh_task))
                else:
                    logger.debug(f"【{self.cookie_id}】Cookie刷新任务已完成，跳过")

            if self.item_sync_task:
                if not self.item_sync_task.done():
                    tasks_to_cancel.append(("商品同步任务", self.item_sync_task))
                else:
                    logger.debug(f"【{self.cookie_id}】商品同步任务已完成，跳过")

            if self.order_sync_task:
                if not self.order_sync_task.done():
                    tasks_to_cancel.append(("订单同步任务", self.order_sync_task))
                else:
                    logger.debug(f"【{self.cookie_id}】订单同步任务已完成，跳过")

            if self.item_polish_task:
                if not self.item_polish_task.done():
                    tasks_to_cancel.append(("商品擦亮任务", self.item_polish_task))
                else:
                    logger.debug(f"【{self.cookie_id}】商品擦亮任务已完成，跳过")

            if self.delivery_timeout_task:
                if not self.delivery_timeout_task.done():
                    tasks_to_cancel.append(("发货超时检查", self.delivery_timeout_task))
                else:
                    logger.debug(f"【{self.cookie_id}】发货超时检查已完成，跳过")

            if self.buyer_interaction_task:
                if not self.buyer_interaction_task.done():
                    tasks_to_cancel.append(("买家互动任务", self.buyer_interaction_task))
                else:
                    logger.debug(f"【{self.cookie_id}】买家互动任务已完成，跳过")

            if not tasks_to_cancel:
                logger.info(f"【{self.cookie_id}】没有后台任务需要取消（所有任务已完成或不存在）")
                # 立即重置任务引用
                self.heartbeat_task = None
                self.token_refresh_task = None
                self.cleanup_task = None
                self.cookie_refresh_task = None
                self.item_sync_task = None
                self.order_sync_task = None
                self.item_polish_task = None
                self.delivery_timeout_task = None
                self.buyer_interaction_task = None
                return
            
            logger.info(f"【{self.cookie_id}】开始取消 {len(tasks_to_cancel)} 个未完成的后台任务...")
            
            # 取消所有任务
            for task_name, task in tasks_to_cancel:
                try:
                    if task.done():
                        logger.info(f"【{self.cookie_id}】任务已完成，跳过取消: {task_name}")
                    else:
                        task.cancel()
                        logger.info(f"【{self.cookie_id}】已发送取消信号: {task_name}")
                except Exception as e:
                    logger.warning(f"【{self.cookie_id}】取消任务失败 {task_name}: {e}")
            
            # 等待所有任务完成取消，使用合理的超时时间
            # 现在任务中已经添加了 await asyncio.sleep(0) 来让出控制权，应该能够响应取消信号
            tasks = [task for _, task in tasks_to_cancel]
            logger.info(f"【{self.cookie_id}】等待 {len(tasks)} 个任务响应取消信号...")
            
            wait_timeout = 5.0  # 增加超时时间到5秒，给任务更多时间响应取消信号
            
            start_time = time.time()
            try:
                # 只等待未完成的任务
                pending_tasks_list = [task for task in tasks if not task.done()]
                
                # 记录每个任务的状态
                for task_name, task in tasks_to_cancel:
                    status = "已完成" if task.done() else "运行中"
                    logger.info(f"【{self.cookie_id}】任务状态: {task_name} - {status}")
                
                if not pending_tasks_list:
                    logger.info(f"【{self.cookie_id}】所有任务已完成，无需等待")
                else:
                    logger.info(f"【{self.cookie_id}】等待 {len(pending_tasks_list)} 个未完成任务响应（超时时间: {wait_timeout}秒）...")
                    try:
                        # 使用 wait 等待任务完成，设置超时
                        logger.debug(f"【{self.cookie_id}】开始调用 asyncio.wait()...")
                        done, pending = await asyncio.wait(
                            pending_tasks_list,
                            timeout=wait_timeout,
                            return_when=asyncio.ALL_COMPLETED
                        )
                        elapsed = time.time() - start_time
                        logger.info(f"【{self.cookie_id}】asyncio.wait() 返回，耗时 {elapsed:.3f}秒，已完成: {len(done)}，未完成: {len(pending)}")
                        
                        # 检查已完成的任务，并记录详细信息
                        for task_name, task in tasks_to_cancel:
                            if task in done:
                                try:
                                    task.result()
                                    logger.warning(f"【{self.cookie_id}】⚠️ 任务正常完成（非取消）: {task_name}")
                                except asyncio.CancelledError:
                                    logger.info(f"【{self.cookie_id}】✅ 任务已成功取消: {task_name}")
                                except Exception as e:
                                    logger.warning(f"【{self.cookie_id}】⚠️ 任务取消时出现异常 {task_name}: {e}")
                        
                        if pending:
                            # 找出未完成的任务名称和详细信息
                            pending_names = []
                            for task_name, task in tasks_to_cancel:
                                if task in pending:
                                    pending_names.append(task_name)
                                    # 记录未完成任务的状态
                                    if task.done():
                                        try:
                                            task.result()
                                            logger.warning(f"【{self.cookie_id}】任务在等待期间完成: {task_name}")
                                        except asyncio.CancelledError:
                                            logger.info(f"【{self.cookie_id}】任务在等待期间被取消: {task_name}")
                                        except Exception as e:
                                            logger.warning(f"【{self.cookie_id}】任务在等待期间异常 {task_name}: {e}")
                                    else:
                                        logger.warning(f"【{self.cookie_id}】任务仍未完成: {task_name} (done={task.done()})")
                            
                            logger.warning(f"【{self.cookie_id}】等待超时 ({elapsed:.3f}秒)，以下任务可能仍在运行: {', '.join(pending_names)}")
                            
                            # 强制取消所有未完成的任务（再次尝试）
                            for task_name, task in tasks_to_cancel:
                                if task in pending and not task.done():
                                    try:
                                        task.cancel()
                                        logger.warning(f"【{self.cookie_id}】强制取消任务: {task_name}")
                                    except Exception as e:
                                        logger.warning(f"【{self.cookie_id}】强制取消任务失败 {task_name}: {e}")
                            
                            # 再等待一小段时间，看是否有任务响应
                            if pending:
                                try:
                                    done2, pending2 = await asyncio.wait(pending, timeout=1.0, return_when=asyncio.ALL_COMPLETED)
                                    for task_name, task in tasks_to_cancel:
                                        if task in done2:
                                            try:
                                                task.result()
                                            except asyncio.CancelledError:
                                                logger.info(f"【{self.cookie_id}】任务在二次等待期间被取消: {task_name}")
                                            except Exception as e:
                                                logger.warning(f"【{self.cookie_id}】任务在二次等待期间异常 {task_name}: {e}")
                                except Exception as e:
                                    logger.warning(f"【{self.cookie_id}】二次等待任务时出错: {e}")
                            
                            logger.warning(f"【{self.cookie_id}】强制继续重连流程，未完成的任务将在后台继续运行（但已标记为取消）")
                        else:
                            logger.info(f"【{self.cookie_id}】所有后台任务已取消 (耗时 {elapsed:.3f}秒)")
                            
                    except Exception as e:
                        elapsed = time.time() - start_time
                        logger.warning(f"【{self.cookie_id}】等待任务时出错 (耗时 {elapsed:.3f}秒): {e}")
                        import traceback
                        logger.warning(f"【{self.cookie_id}】等待任务异常堆栈:\n{traceback.format_exc()}")
                        
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"【{self.cookie_id}】等待任务取消时出错 (耗时 {elapsed:.3f}秒): {e}")
                import traceback
                logger.error(f"【{self.cookie_id}】等待任务取消异常堆栈:\n{traceback.format_exc()}")
            
            logger.info(f"【{self.cookie_id}】任务取消流程完成，继续重连流程")
            
            # 最后检查一次所有任务的状态
            for task_name, task in tasks_to_cancel:
                if task and not task.done():
                    logger.warning(f"【{self.cookie_id}】⚠️ 任务取消流程完成后，任务仍未完成: {task_name} (done={task.done()})")
                elif task and task.done():
                    logger.debug(f"【{self.cookie_id}】✅ 任务已完成: {task_name}")
        
        finally:
            # 使用 finally 确保无论发生什么情况都会重置任务引用
            # 这样可以保证下次重连时所有任务都会被重新创建
            self.heartbeat_task = None
            self.token_refresh_task = None
            self.cleanup_task = None
            self.cookie_refresh_task = None
            self.item_sync_task = None
            self.order_sync_task = None
            self.item_polish_task = None
            self.delivery_timeout_task = None
            self.buyer_interaction_task = None
            logger.info(f"【{self.cookie_id}】后台任务引用已全部重置")

    # 平台风控/人机验证的特征串。命中后必须大幅退避 —— 继续高频重试只会
    # 让风控持续时间更长，实测无退避时会形成每分钟数百次请求的重试风暴。
    RISK_CONTROL_MARKERS = (
        'RGV587_ERROR',
        'FAIL_SYS_USER_VALIDATE',
        '哎哟喂',
        '被挤爆',
        'FAIL_SYS_FLOW_LIMIT',
        '请稍后重试',
    )

    @classmethod
    def is_risk_control_error(cls, message) -> bool:
        """判断错误是否来自平台风控或限流。"""
        text = str(message or '')
        return any(marker in text for marker in cls.RISK_CONTROL_MARKERS)

    def _calculate_retry_delay(self, error_msg: str) -> int:
        """根据错误类型和失败次数计算重试延迟"""
        # 平台风控 - 指数退避，最长 30 分钟
        if self.is_risk_control_error(error_msg):
            delay = min(60 * (2 ** max(0, self.connection_failures - 1)), 1800)
            logger.warning(
                f"【{self.cookie_id}】检测到平台风控，退避 {delay} 秒后重试"
                f"（第 {self.connection_failures} 次）"
            )
            return delay

        # WebSocket意外断开 - 短延迟
        if "no close frame received or sent" in error_msg:
            return min(3 * self.connection_failures, 15)

        # 网络连接问题 - 长延迟
        elif "Connection refused" in error_msg or "timeout" in error_msg.lower():
            return min(10 * self.connection_failures, 60)

        # 其他未知错误 - 中等延迟
        else:
            return min(5 * self.connection_failures, 30)

    def _cleanup_instance_caches(self):
        """清理实例级别的缓存，防止内存泄漏"""
        try:
            current_time = time.time()
            cleaned_total = 0
            
            # 清理过期的通知记录（保留30分钟内的，从1小时优化）
            max_notification_age = 1800  # 30分钟（从3600优化）
            expired_notifications = [
                key for key, last_time in self.last_notification_time.items()
                if current_time - last_time > max_notification_age
            ]
            for key in expired_notifications:
                del self.last_notification_time[key]
            if expired_notifications:
                cleaned_total += len(expired_notifications)
                logger.warning(f"【{self.cookie_id}】清理了 {len(expired_notifications)} 个过期通知记录")
            
            # 清理过期的发货记录（保留30分钟内的）
            max_delivery_age = 1800  # 30分钟
            expired_deliveries = [
                order_id for order_id, last_time in self.last_delivery_time.items()
                if current_time - last_time > max_delivery_age
            ]
            for order_id in expired_deliveries:
                del self.last_delivery_time[order_id]
            if expired_deliveries:
                cleaned_total += len(expired_deliveries)
                logger.warning(f"【{self.cookie_id}】清理了 {len(expired_deliveries)} 个过期发货记录")
            
            # 清理过期的订单确认记录（保留30分钟内的）
            max_confirm_age = 1800  # 30分钟
            expired_confirms = [
                order_id for order_id, last_time in self.confirmed_orders.items()
                if current_time - last_time > max_confirm_age
            ]
            for order_id in expired_confirms:
                del self.confirmed_orders[order_id]
            if expired_confirms:
                cleaned_total += len(expired_confirms)
                logger.warning(f"【{self.cookie_id}】清理了 {len(expired_confirms)} 个过期订单确认记录")
            
            # 只有实际清理了内容才记录总数日志
            if cleaned_total > 0:
                logger.info(f"【{self.cookie_id}】实例缓存清理完成，共清理 {cleaned_total} 条记录")
                logger.warning(f"【{self.cookie_id}】当前缓存数量 - 通知: {len(self.last_notification_time)}, 发货: {len(self.last_delivery_time)}, 确认: {len(self.confirmed_orders)}")
        
        except Exception as e:
            logger.error(f"【{self.cookie_id}】清理实例缓存时出错: {self._safe_str(e)}")
    
    async def _cleanup_playwright_cache(self):
        """清理Playwright浏览器临时文件和缓存（Docker环境专用）"""
        try:
            import shutil
            import glob
            
            # 定义需要清理的临时目录路径
            temp_paths = [
                '/tmp/playwright-*',  # Playwright临时会话
                '/tmp/chromium-*',    # Chromium临时文件
                '/ms-playwright/chromium-*/Default/Cache',  # 浏览器缓存
                '/ms-playwright/chromium-*/Default/Code Cache',  # 代码缓存
                '/ms-playwright/chromium-*/Default/GPUCache',  # GPU缓存
            ]
            
            total_cleaned = 0
            total_size_mb = 0
            
            for pattern in temp_paths:
                try:
                    matching_paths = glob.glob(pattern)
                    for path in matching_paths:
                        try:
                            if os.path.exists(path):
                                # 计算大小
                                if os.path.isdir(path):
                                    size = sum(
                                        os.path.getsize(os.path.join(dirpath, filename))
                                        for dirpath, _, filenames in os.walk(path)
                                        for filename in filenames
                                    )
                                    shutil.rmtree(path, ignore_errors=True)
                                else:
                                    size = os.path.getsize(path)
                                    os.remove(path)
                                
                                total_size_mb += size / (1024 * 1024)
                                total_cleaned += 1
                        except Exception as e:
                            logger.warning(f"清理路径 {path} 时出错: {e}")
                except Exception as e:
                    logger.warning(f"匹配路径 {pattern} 时出错: {e}")
            
            if total_cleaned > 0:
                logger.info(f"【{self.cookie_id}】Playwright缓存清理完成: 删除了 {total_cleaned} 个文件/目录，释放 {total_size_mb:.2f} MB")
            else:
                logger.warning(f"【{self.cookie_id}】Playwright缓存清理: 没有需要清理的临时文件")
                
        except Exception as e:
            logger.warning(f"【{self.cookie_id}】清理Playwright缓存时出错: {self._safe_str(e)}")

    async def _cleanup_old_logs(self, retention_days: int = 7):
        """清理过期的日志文件
        
        Args:
            retention_days: 保留的天数，默认7天
            
        Returns:
            清理的文件数量
        """
        try:
            import glob
            from datetime import datetime, timedelta
            
            logs_dir = "logs"
            if not os.path.exists(logs_dir):
                logger.warning(f"【{self.cookie_id}】日志目录不存在: {logs_dir}")
                return 0
            
            # 计算过期时间点
            cutoff_time = datetime.now() - timedelta(days=retention_days)
            
            # 查找所有日志文件（包括.log和.log.zip）
            log_patterns = [
                os.path.join(logs_dir, "xianyu_*.log"),
                os.path.join(logs_dir, "xianyu_*.log.zip"),
                os.path.join(logs_dir, "app_*.log"),
                os.path.join(logs_dir, "app_*.log.zip"),
            ]
            
            total_cleaned = 0
            total_size_mb = 0
            
            for pattern in log_patterns:
                log_files = glob.glob(pattern)
                for log_file in log_files:
                    try:
                        # 获取文件修改时间
                        file_mtime = datetime.fromtimestamp(os.path.getmtime(log_file))
                        
                        # 如果文件早于保留期限，则删除
                        if file_mtime < cutoff_time:
                            file_size = os.path.getsize(log_file)
                            os.remove(log_file)
                            total_size_mb += file_size / (1024 * 1024)
                            total_cleaned += 1
                            logger.debug(f"【{self.cookie_id}】删除过期日志文件: {log_file} (修改时间: {file_mtime})")
                    except Exception as e:
                        logger.warning(f"【{self.cookie_id}】删除日志文件失败 {log_file}: {self._safe_str(e)}")
            
            if total_cleaned > 0:
                logger.info(f"【{self.cookie_id}】日志清理完成: 删除了 {total_cleaned} 个日志文件，释放 {total_size_mb:.2f} MB (保留 {retention_days} 天内的日志)")
            else:
                logger.debug(f"【{self.cookie_id}】日志清理: 没有需要清理的过期日志文件 (保留 {retention_days} 天)")
            
            return total_cleaned
            
        except Exception as e:
            logger.error(f"【{self.cookie_id}】清理日志文件时出错: {self._safe_str(e)}")
            return 0

    def __init__(self, cookies_str=None, cookie_id: str = "default", user_id: int = None):
        """初始化闲鱼直播类"""
        logger.info(f"【{cookie_id}】开始初始化XianyuLive...")

        if not cookies_str:
            cookies_str = COOKIES_STR
        if not cookies_str:
            raise ValueError("未提供cookies，请在global_config.yml中配置COOKIES_STR或通过参数传入")

        logger.info(f"【{cookie_id}】解析cookies...")
        self.cookies = trans_cookies(cookies_str)
        logger.info(f"【{cookie_id}】cookies解析完成，包含字段: {list(self.cookies.keys())}")

        self.cookie_id = cookie_id  # 唯一账号标识
        self.cookies_str = cookies_str  # 保存原始cookie字符串
        self.user_id = user_id  # 保存用户ID，用于token刷新时保持正确的所有者关系
        self.base_url = WEBSOCKET_URL

        if 'unb' not in self.cookies:
            raise ValueError(f"【{cookie_id}】Cookie中缺少必需的'unb'字段，当前字段: {list(self.cookies.keys())}")

        self.myid = self.cookies['unb']
        logger.info(f"【{cookie_id}】用户ID: {self.myid}")
        self.device_id = generate_device_id(self.myid)

        # 心跳相关配置
        self.heartbeat_interval = HEARTBEAT_INTERVAL
        self.heartbeat_timeout = HEARTBEAT_TIMEOUT
        self.last_heartbeat_time = 0
        self.last_heartbeat_response = 0
        self.heartbeat_task = None
        self.ws = None
        self._im_pending = {}
        self._im_request_lock = asyncio.Lock()

        # Token刷新相关配置
        self.token_refresh_interval = TOKEN_REFRESH_INTERVAL
        self.token_retry_interval = TOKEN_RETRY_INTERVAL
        self.last_token_refresh_time = 0
        self.current_token = None
        self.media_host = "down.im.dingtalk.cn"
        self.token_refresh_task = None
        self.connection_restart_flag = False  # 连接重启标志

        # 通知防重复机制
        self.last_notification_time = {}  # 记录每种通知类型的最后发送时间
        self.notification_cooldown = 300  # 5分钟内不重复发送相同类型的通知
        self.token_refresh_notification_cooldown = 18000  # Token刷新异常通知冷却时间：3小时
        self.notification_lock = asyncio.Lock()  # 通知防重复机制的异步锁

        # 自动发货防重复机制
        self.last_delivery_time = {}  # 记录每个商品的最后发货时间
        self.delivery_cooldown = 600  # 10分钟内不重复发货

        # 自动确认发货防重复机制
        self.confirmed_orders = {}  # 记录已确认发货的订单，防止重复确认
        self.order_confirm_cooldown = 600  # 10分钟内不重复确认同一订单

        # 自动发货已发送订单记录
        self.delivery_sent_orders = set()  # 记录已发货的订单ID，防止重复发货
        self.delivery_blocked_orders = set()  # 部分发货或内容已消耗的订单，阻止自动重试造成重复发送

        # 交易卡片落库前暂存卖家端接口返回的真实成交数据（金额、数量、收货信息）
        self._pending_order_real_values = {}

        self.session = None  # 用于API调用的aiohttp session

        # 启动定期清理过期暂停记录的任务
        self.cleanup_task = None

        # Cookie刷新定时任务
        self.cookie_refresh_task = None
        self.cookie_refresh_interval = 1200  # 1小时 = 3600秒
        self.last_cookie_refresh_time = 0
        self.cookie_refresh_lock = asyncio.Lock()  # 使用Lock防止重复执行Cookie刷新
        self.cookie_refresh_enabled = True  # 是否启用Cookie刷新功能

        # 商品同步定时任务
        self.item_sync_task = None
        self.item_sync_enabled = cfg.get('ITEM_SYNC', {}).get('enabled', True)
        self.item_sync_interval = cfg.get('ITEM_SYNC', {}).get('interval', 3600)  # 默认1小时
        self.item_sync_max_pages = cfg.get('ITEM_SYNC', {}).get('max_pages', 5)
        self.last_item_sync_time = 0
        self.item_sync_lock = asyncio.Lock()  # 使用Lock防止重复执行商品同步

        # 订单同步定时任务：从卖家端接口拉全量，补齐监听离线期间的订单
        self.order_sync_task = None
        self.last_order_sync_time = 0

        # 商品擦亮定时任务：重新获取搜索曝光，默认关闭
        self.item_polish_task = None
        self.last_polish_time = 0

        # 发货超时告警：记录已提醒过的订单，避免重复推送
        self.delivery_timeout_task = None
        self._delivery_timeout_alerted = set()

        # 账号资料只在连接成功后同步一次，避免重连时反复请求
        self._profile_synced = False

        # 买家互动（评价/求花）：记录已处理订单，两者都默认关闭
        self.buyer_interaction_task = None
        self._auto_rated_orders = set()
        self._auto_flowered_orders = set()
        # 已发过确认收货致谢的会话/订单，避免同一笔交易的多条系统消息各发一次
        self._thanked_receipts = set()
        # 买家互动即时触发的去重标记
        self._buyer_interaction_triggering = False

        # 扫码登录Cookie刷新标志
        self.last_qr_cookie_refresh_time = 0  # 记录上次扫码登录Cookie刷新时间
        self.qr_cookie_refresh_cooldown = 600  # 扫码登录Cookie刷新后的冷却时间：10分钟

        # 消息接收标识 - 用于控制Cookie刷新
        self.last_message_received_time = 0  # 记录上次收到消息的时间
        self.message_cookie_refresh_cooldown = 300  # 收到消息后5分钟内不执行Cookie刷新

        # 浏览器Cookie刷新成功标志
        self.browser_cookie_refreshed = False  # 标记_refresh_cookies_via_browser是否成功更新过数据库
        self.restarted_in_browser_refresh = False  # 刷新流程内部是否已触发重启（用于去重）


        # 滑块验证相关
        self.captcha_verification_count = 0  # 滑块验证次数计数器
        self.max_captcha_verification_count = 3  # 最大滑块验证次数，防止无限递归

        # WebSocket连接监控
        self.connection_state = ConnectionState.DISCONNECTED  # 连接状态
        self.connection_failures = 0  # 连续连接失败次数
        self.max_connection_failures = 5  # 最大连续失败次数
        self.last_successful_connection = 0  # 上次成功连接时间
        self.last_state_change_time = time.time()  # 上次状态变化时间
        # 登录态已过期且无法自动续期时置位。与"风控中"要分开：风控能等能过验证，
        # 会话过期只能重新扫码，界面必须给出不同的指引。
        self.needs_relogin = False
        self.relogin_reason = ''

        # 后台任务追踪（用于清理未等待的任务）
        self.background_tasks = set()  # 追踪所有后台任务
        
        # 消息处理并发控制（防止内存泄漏）
        self.message_semaphore = asyncio.Semaphore(100)  # 最多100个并发消息处理任务
        self.active_message_tasks = 0  # 当前活跃的消息处理任务数

        # 消息防抖管理器：用于处理用户连续发送消息的情况
        # {chat_id: {'task': asyncio.Task, 'last_message': dict, 'timer': float}}
        self.message_debounce_tasks = {}  # 存储每个chat_id的防抖任务
        self.message_debounce_delay = 1  # 防抖延迟时间（秒）：用户停止发送消息1秒后才回复
        self.message_debounce_lock = asyncio.Lock()  # 防抖任务管理的锁
        
        # 消息去重机制：防止同一条消息被处理多次
        self.processed_message_ids = {}  # 存储已处理的消息ID和时间戳 {message_id: timestamp}
        self.processed_message_ids_lock = asyncio.Lock()  # 消息ID去重的锁
        self.processed_message_ids_max_size = 10000  # 最大保存10000个消息ID，防止内存泄漏
        self.message_expire_time = 3600  # 消息过期时间（秒），默认1小时后可以重复回复

        # 初始化订单状态处理器
        self._init_order_status_handler()

        # 注册实例到类级别字典（用于API调用）
        self._register_instance()

    def _init_order_status_handler(self):
        """初始化订单状态处理器"""
        try:
            # 直接导入订单状态处理器
            from app.order_status_handler import order_status_handler
            self.order_status_handler = order_status_handler
            logger.info(f"【{self.cookie_id}】订单状态处理器已启用")
        except Exception as e:
            logger.error(f"【{self.cookie_id}】初始化订单状态处理器失败: {self._safe_str(e)}")
            self.order_status_handler = None

    def _register_instance(self):
        """注册当前实例到类级别字典"""
        try:
            # 使用同步方式注册，避免在__init__中使用async
            XianyuLive._instances[self.cookie_id] = self
            logger.warning(f"【{self.cookie_id}】实例已注册到全局字典")
        except Exception as e:
            logger.error(f"【{self.cookie_id}】注册实例失败: {self._safe_str(e)}")

    def _unregister_instance(self):
        """从类级别字典中注销当前实例"""
        try:
            # 重连时同一账号会先建新实例再回收旧实例，若无条件删除，
            # 旧实例的清理会把仍在运行的新实例一并抹掉 —— 表现为账号心跳正常、
            # 界面显示「监听中」，完整发货却报「该账号未在线运行」。
            # 因此只在注册表里存的确实是自己时才删除。
            if XianyuLive._instances.get(self.cookie_id) is self:
                del XianyuLive._instances[self.cookie_id]
                logger.warning(f"【{self.cookie_id}】实例已从全局字典中注销")
            elif self.cookie_id in XianyuLive._instances:
                logger.warning(
                    f"【{self.cookie_id}】注册表中已是更新的实例，跳过注销避免误删"
                )
        except Exception as e:
            logger.error(f"【{self.cookie_id}】注销实例失败: {self._safe_str(e)}")

    @classmethod
    def get_instance(cls, cookie_id: str):
        """获取指定cookie_id的XianyuLive实例"""
        return cls._instances.get(cookie_id)

    @classmethod
    def get_all_instances(cls):
        """获取所有活跃的XianyuLive实例"""
        return dict(cls._instances)

    @classmethod
    def get_instance_count(cls):
        """获取当前活跃实例数量"""
        return len(cls._instances)
    
    def _create_tracked_task(self, coro):
        """创建并追踪后台任务，确保异常不会被静默忽略"""
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        return task

    def is_auto_confirm_enabled(self) -> bool:
        """检查当前账号是否启用自动确认发货"""
        try:
            from app.db_manager import db_manager
            return db_manager.get_auto_confirm(self.cookie_id)
        except Exception as e:
            logger.error(f"【{self.cookie_id}】获取自动确认发货设置失败: {self._safe_str(e)}")
            return True  # 出错时默认启用

    async def _merge_mtop_response_cookies(self, response, source: str) -> None:
        """合并 mtop 响应中的 Cookie，并同步到当前会话和数据库。"""
        if 'set-cookie' not in response.headers:
            return

        new_cookies = {}
        for cookie in response.headers.getall('set-cookie', []):
            if '=' not in cookie:
                continue
            name, value = cookie.split(';', 1)[0].split('=', 1)
            new_cookies[name.strip()] = value.strip()

        if not new_cookies:
            return

        self.cookies.update(new_cookies)
        self.cookies_str = '; '.join(f"{key}={value}" for key, value in self.cookies.items())
        if self.session and not self.session.closed:
            self.session.headers['cookie'] = self.cookies_str
        await self.update_config_cookies()
        logger.info(f"【{self.cookie_id}】{source}响应更新了 {len(new_cookies)} 个 Cookie 字段")

    async def fetch_buyer_rating_count(self, buyer_id: str, retry_count: int = 0) -> int:
        """获取买家被评价总数；失败返回 -1，由规则引擎按放行处理。"""
        max_retry = 3
        if not buyer_id or not self.cookies_str:
            logger.warning(f"【{self.cookie_id}】买家信用查询缺少 buyer_id 或 Cookie，跳过")
            return -1

        data_payload = {
            "rateType": 0,
            "ratedUid": str(buyer_id),
            "raterType": 0,
            "rowsPerPage": 20,
            "pageNumber": 1,
            "foldFlag": 0,
            "fishAdCode": "330110",
            "extraTag": "",
        }
        data_val = json.dumps(data_payload, separators=(',', ':'), ensure_ascii=False)
        timestamp = str(int(time.time() * 1000))
        cookies = trans_cookies(self.cookies_str)
        token_value = cookies.get('_m_h5_tk', '')
        token = token_value.split('_')[0] if token_value else ''
        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': timestamp,
            'sign': generate_sign(timestamp, token, data_val),
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.idle.web.trade.rate.list',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.personal.0.0',
        }
        headers = {
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://www.goofish.com',
            'referer': 'https://www.goofish.com/',
            'user-agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36'
            ),
            'cookie': self.cookies_str.replace('\n', '').replace('\r', ''),
        }

        try:
            async with self.session.post(
                'https://h5api.m.goofish.com/h5/mtop.idle.web.trade.rate.list/1.0/',
                params=params,
                data={'data': data_val},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                result = await response.json()
                await self._merge_mtop_response_cookies(response, "买家信用查询")

            ret_list = result.get('ret', []) if isinstance(result, dict) else []
            if any('SUCCESS' in value for value in ret_list):
                total_count = (result.get('data') or {}).get('totalCount')
                try:
                    count = int(total_count)
                    logger.info(
                        f"【{self.cookie_id}】买家信用查询成功: buyer_id={buyer_id}, total_count={count}"
                    )
                    return count
                except (TypeError, ValueError):
                    logger.warning(
                        f"【{self.cookie_id}】买家信用查询缺少有效 totalCount: buyer_id={buyer_id}"
                    )
            else:
                logger.warning(
                    f"【{self.cookie_id}】买家信用查询失败: buyer_id={buyer_id}, ret={ret_list}"
                )
        except Exception as exc:
            logger.warning(
                f"【{self.cookie_id}】买家信用查询异常（第 {retry_count + 1} 次）: "
                f"{self._safe_str(exc)}"
            )

        if retry_count < max_retry - 1:
            await asyncio.sleep(0.5)
            return await self.fetch_buyer_rating_count(buyer_id, retry_count + 1)
        return -1

    async def close_order_by_seller(self, order_id: str, retry_count: int = 0) -> bool:
        """命中发货保护后，由卖家主动关闭闲鱼订单。"""
        max_retry = 3
        if not order_id or not self.cookies_str:
            logger.warning(f"【{self.cookie_id}】关闭订单缺少 order_id 或 Cookie，跳过")
            return False

        data_payload = {
            "tid": str(order_id),
            "bizOrderId": str(order_id),
            # 卖家版关单理由与买家版取值完全不同，可选值为：
            # 不想卖了 / 宝贝已出售 / 买家联系不上 / 与买家协商一致 / 其他原因
            "closeReason": "宝贝已出售",
        }
        data_val = json.dumps(data_payload, separators=(',', ':'), ensure_ascii=False)
        timestamp = str(int(time.time() * 1000))
        cookies = trans_cookies(self.cookies_str)
        token_value = cookies.get('_m_h5_tk', '')
        token = token_value.split('_')[0] if token_value else ''
        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': timestamp,
            'sign': generate_sign(timestamp, token, data_val),
            'v': '2.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idle.trade.merchant.close.by.seller',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21107h.44911108.0.0',
        }
        headers = {
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://seller.goofish.com',
            'referer': 'https://seller.goofish.com/',
            'user-agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36'
            ),
            'cookie': self.cookies_str.replace('\n', '').replace('\r', ''),
        }

        try:
            async with self.session.post(
                'https://h5api.m.goofish.com/h5/mtop.taobao.idle.trade.merchant.close.by.seller/2.0/',
                params=params,
                data={'data': data_val},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                result = await response.json()
                await self._merge_mtop_response_cookies(response, "关闭订单")

            ret_list = result.get('ret', []) if isinstance(result, dict) else []
            if any('SUCCESS' in value for value in ret_list):
                logger.warning(f"【{self.cookie_id}】订单 {order_id} 已由卖家主动关闭")
                return True
            logger.warning(
                f"【{self.cookie_id}】关闭订单失败（第 {retry_count + 1} 次）: "
                f"order_id={order_id}, ret={ret_list}"
            )
        except Exception as exc:
            logger.warning(
                f"【{self.cookie_id}】关闭订单异常（第 {retry_count + 1} 次）: "
                f"order_id={order_id}, error={self._safe_str(exc)}"
            )

        if retry_count < max_retry - 1:
            await asyncio.sleep(0.5)
            return await self.close_order_by_seller(order_id, retry_count + 1)
        return False

    async def apply_delivery_block_rules(
        self,
        order_id: str,
        buyer_id: str,
        item_id: str = None,
        chat_id: str = '',
        websocket=None,
        owner_id: int = None,
        service=None,
    ) -> dict:
        """执行全部发货保护，并返回 allow、block 或 card_only。"""
        from app.services.delivery_block_rules import (
            DeliveryBlockRuleService,
            resolve_delivery_action,
        )

        rule_service = service or DeliveryBlockRuleService(db_manager)
        buyer_rating_count = None
        try:
            credit_rule = next(
                (
                    rule for rule in rule_service.list_rules(self.cookie_id)
                    if rule['rule_code'] == 'buyer_credit_zero'
                ),
                None,
            )
            if (
                credit_rule
                and credit_rule['enabled']
                and (not item_id or str(item_id) not in set(credit_rule['excluded_item_ids']))
            ):
                buyer_rating_count = await self.fetch_buyer_rating_count(buyer_id)
        except Exception as exc:
            logger.warning(
                f"【{self.cookie_id}】准备买家信用规则失败，按接口异常放行该规则: "
                f"{self._safe_str(exc)}"
            )

        result = rule_service.evaluate(
            account_id=self.cookie_id,
            order_id=order_id,
            buyer_id=buyer_id,
            item_id=item_id,
            owner_id=owner_id,
            buyer_rating_count=buyer_rating_count,
        )
        if not result['hit']:
            return {**result, 'action': 'allow', 'order_closed': False}

        block_message = result.get('block_reason') or ''
        active_websocket = websocket or self.ws
        if block_message and chat_id and active_websocket:
            try:
                await self.send_msg(active_websocket, chat_id, buyer_id, block_message)
            except Exception as exc:
                logger.error(
                    f"【{self.cookie_id}】订单 {order_id} 已拦截，但发送买家提示失败: "
                    f"{self._safe_str(exc)}"
                )

        order_closed = False
        if result.get('auto_close_order'):
            order_closed = await self.close_order_by_seller(order_id)

        action = resolve_delivery_action(result, order_closed)
        if action == 'block':
            self.delivery_blocked_orders.add(order_id)
            self.last_delivery_time[order_id] = time.time()

        logger.warning(
            f"【{self.cookie_id}】订单 {order_id} 命中发货保护: "
            f"rule={result.get('rule_code')}, action={action}, "
            f"order_closed={order_closed}, reason={result.get('reason')}"
        )
        return {**result, 'action': action, 'order_closed': order_closed}



    def can_auto_delivery(self, order_id: str) -> bool:
        """检查是否可以进行自动发货（防重复发货）- 基于订单ID"""
        if not order_id:
            # 如果没有订单ID，则不进行冷却检查，允许发货
            return True

        if order_id in self.delivery_sent_orders:
            logger.info(f"【{self.cookie_id}】订单 {order_id} 已完成自动发货，跳过重复发货")
            return False

        if order_id in self.delivery_blocked_orders:
            logger.warning(f"【{self.cookie_id}】订单 {order_id} 存在部分发货或内容消耗异常，需要人工处理，跳过自动重试")
            return False

        current_time = time.time()
        last_delivery = self.last_delivery_time.get(order_id, 0)

        if current_time - last_delivery < self.delivery_cooldown:
            logger.info(f"【{self.cookie_id}】订单 {order_id} 在冷却期内，跳过自动发货")
            return False

        return True

    def mark_delivery_sent(self, order_id: str, update_order_status: bool = True):
        """标记订单已发货"""
        self.delivery_sent_orders.add(order_id)
        self.last_delivery_time[order_id] = time.time()
        logger.info(f"【{self.cookie_id}】订单 {order_id} 已标记为发货")

        if not update_order_status:
            logger.warning(f"【{self.cookie_id}】订单 {order_id} 的卡券已发送，但闲鱼发货状态未确认")
            return

        # 更新订单状态为已发货
        logger.info(f"【{self.cookie_id}】检查自动发货订单状态处理器: handler_exists={self.order_status_handler is not None}")
        if self.order_status_handler:
            logger.info(f"【{self.cookie_id}】准备调用订单状态处理器.handle_auto_delivery_order_status: {order_id}")
            try:
                success = self.order_status_handler.handle_auto_delivery_order_status(
                    order_id=order_id,
                    cookie_id=self.cookie_id,
                    context="自动发货完成"
                )
                logger.info(f"【{self.cookie_id}】订单状态处理器.handle_auto_delivery_order_status返回结果: {success}")
                if success:
                    logger.info(f"【{self.cookie_id}】订单 {order_id} 状态已更新为已发货")
                else:
                    logger.warning(f"【{self.cookie_id}】订单 {order_id} 状态更新为已发货失败")
            except Exception as e:
                logger.error(f"【{self.cookie_id}】订单状态更新失败: {self._safe_str(e)}")
                import traceback
                logger.error(f"【{self.cookie_id}】详细错误信息: {traceback.format_exc()}")
        else:
            logger.warning(f"【{self.cookie_id}】订单状态处理器为None，跳过自动发货状态更新: {order_id}")

    async def _delayed_lock_release(self, lock_key: str, delay_minutes: int = 10):
        """
        延迟释放锁的异步任务

        Args:
            lock_key: 锁的键
            delay_minutes: 延迟时间（分钟），默认10分钟
        """
        try:
            delay_seconds = delay_minutes * 60
            logger.info(f"【{self.cookie_id}】订单锁 {lock_key} 将在 {delay_minutes} 分钟后释放")

            # 等待指定时间
            await asyncio.sleep(delay_seconds)

            # 检查锁是否仍然存在且需要释放
            if lock_key in self._lock_hold_info:
                lock_info = self._lock_hold_info[lock_key]
                if lock_info.get('locked', False):
                    # 释放锁
                    lock_info['locked'] = False
                    lock_info['release_time'] = time.time()
                    logger.info(f"【{self.cookie_id}】订单锁 {lock_key} 延迟释放完成")

                    # 清理锁信息（可选，也可以保留用于统计）
                    # del self._lock_hold_info[lock_key]

        except asyncio.CancelledError:
            logger.info(f"【{self.cookie_id}】订单锁 {lock_key} 延迟释放任务被取消")
            raise
        except Exception as e:
            logger.error(f"【{self.cookie_id}】订单锁 {lock_key} 延迟释放失败: {self._safe_str(e)}")

    def is_lock_held(self, lock_key: str) -> bool:
        """
        检查指定的锁是否仍在持有状态

        Args:
            lock_key: 锁的键

        Returns:
            bool: True表示锁仍在持有，False表示锁已释放或不存在
        """
        if lock_key not in self._lock_hold_info:
            return False

        lock_info = self._lock_hold_info[lock_key]
        return lock_info.get('locked', False)

    def cleanup_expired_locks(self, max_age_hours: int = 24):
        """
        清理过期的锁（包括自动发货锁和订单详情锁）

        Args:
            max_age_hours: 锁的最大保留时间（小时），默认24小时
        """
        try:
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600

            # 清理自动发货锁
            expired_delivery_locks = []
            for order_id, last_used in self._lock_usage_times.items():
                if current_time - last_used > max_age_seconds:
                    expired_delivery_locks.append(order_id)

            # 清理过期的自动发货锁
            for order_id in expired_delivery_locks:
                if order_id in self._order_locks:
                    del self._order_locks[order_id]
                if order_id in self._lock_usage_times:
                    del self._lock_usage_times[order_id]
                # 清理锁持有信息
                if order_id in self._lock_hold_info:
                    lock_info = self._lock_hold_info[order_id]
                    # 取消延迟释放任务
                    if 'task' in lock_info and lock_info['task']:
                        lock_info['task'].cancel()
                    del self._lock_hold_info[order_id]

            # 清理订单详情锁
            expired_detail_locks = []
            for order_id, last_used in self._order_detail_lock_times.items():
                if current_time - last_used > max_age_seconds:
                    expired_detail_locks.append(order_id)

            # 清理过期的订单详情锁
            for order_id in expired_detail_locks:
                if order_id in self._order_detail_locks:
                    del self._order_detail_locks[order_id]
                if order_id in self._order_detail_lock_times:
                    del self._order_detail_lock_times[order_id]

            total_expired = len(expired_delivery_locks) + len(expired_detail_locks)
            if total_expired > 0:
                logger.info(f"【{self.cookie_id}】清理了 {total_expired} 个过期锁 (发货锁: {len(expired_delivery_locks)}, 详情锁: {len(expired_detail_locks)})")
                logger.warning(f"【{self.cookie_id}】当前锁数量 - 发货锁: {len(self._order_locks)}, 详情锁: {len(self._order_detail_locks)}")

        except Exception as e:
            logger.error(f"【{self.cookie_id}】清理过期锁时发生错误: {self._safe_str(e)}")

    

    def _is_auto_delivery_trigger(self, message: str) -> bool:
        """检查消息是否为自动发货触发关键字"""
        auto_delivery_messages = {
            '[我已付款，等待你发货]',
            '[已付款，待发货]',
            '[记得及时发货]',
        }
        return isinstance(message, str) and message.strip() in auto_delivery_messages

    def _is_system_or_order_event(self, message: str) -> bool:
        """统一识别需要绕过普通自动回复链路的系统和订单事件。"""
        try:
            from app.ai_reply_engine import AIReplyEngine
            return AIReplyEngine.is_system_or_order_event(message)
        except Exception as e:
            logger.warning(f"【{self.cookie_id}】系统事件识别失败: {self._safe_str(e)}")
            return False

    def _extract_order_id(self, message: dict) -> str:
        """从消息中提取订单ID"""
        try:
            order_id = None

            logger.debug(
                f"【{self.cookie_id}】消息结构: type={type(message).__name__}, "
                f"keys={list(message.keys()) if isinstance(message, dict) else []}"
            )

            # 检查message['1']的结构，处理可能是列表、字典或字符串的情况
            message_1 = message.get('1', {})
            content_json_str = ''

            if isinstance(message_1, dict):
                logger.warning(f"【{self.cookie_id}】🔍 message['1'] 是字典，keys: {list(message_1.keys())}")

                # 检查message['1']['6']的结构
                message_1_6 = message_1.get('6', {})
                if isinstance(message_1_6, dict):
                    logger.warning(f"【{self.cookie_id}】🔍 message['1']['6'] 是字典，keys: {list(message_1_6.keys())}")
                    # 方法1: 从button的targetUrl中提取orderId
                    content_json_str = message_1_6.get('3', {}).get('5', '') if isinstance(message_1_6.get('3', {}), dict) else ''
                else:
                    logger.warning(f"【{self.cookie_id}】🔍 message['1']['6'] 不是字典: {type(message_1_6)}")

            elif isinstance(message_1, list):
                logger.warning(f"【{self.cookie_id}】🔍 message['1'] 是列表，长度: {len(message_1)}")
                # 如果message['1']是列表，跳过这种提取方式

            elif isinstance(message_1, str):
                logger.warning(f"【{self.cookie_id}】🔍 message['1'] 是字符串，长度: {len(message_1)}")
                # 如果message['1']是字符串，跳过这种提取方式

            else:
                logger.warning(f"【{self.cookie_id}】🔍 message['1'] 未知类型: {type(message_1)}")
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
                            logger.info(f'【{self.cookie_id}】✅ 从button提取到订单ID: {order_id}')

                    # 方法1b: 从main的targetUrl中提取order_detail的id
                    if not order_id:
                        main_target_url = content_data.get('dxCard', {}).get('item', {}).get('main', {}).get('targetUrl', '')
                        if main_target_url:
                            order_match = re.search(r'order_detail\?id=(\d+)', main_target_url)
                            if order_match:
                                order_id = order_match.group(1)
                                logger.info(f'【{self.cookie_id}】✅ 从main targetUrl提取到订单ID: {order_id}')

                except Exception as parse_e:
                    logger.warning(f"解析内容JSON失败: {parse_e}")

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
                            logger.info(f'【{self.cookie_id}】✅ 从order_detail提取到订单ID: {order_id}')
                except Exception as parse_e:
                    logger.warning(f"解析dynamicOperation JSON失败: {parse_e}")

            # 方法2.5: 从 message['3'] 中直接提取 orderId
            if not order_id:
                message_3 = message.get('3')
                if isinstance(message_3, dict):
                    direct_order_id = message_3.get('orderId')
                    if direct_order_id and str(direct_order_id).isdigit():
                        order_id = str(direct_order_id)
                        logger.info(f'【{self.cookie_id}】✅ 从message[3].orderId提取到订单ID: {order_id}')

            # 方法3: 如果前面的方法都失败，尝试在整个消息中搜索订单ID模式
            if not order_id:
                try:
                    # 将整个消息转换为字符串进行搜索
                    message_str = str(message)

                    # 搜索各种可能的订单ID模式
                    patterns = [
                        r'orderId["\']?\s*[:=]\s*["\']?(\d{10,})',  # orderId: '123' 或 orderId=123
                        r'order_detail\?id=(\d{10,})',  # order_detail?id=123456789
                        r'"id"\s*:\s*"?(\d{10,})"?',  # "id":"123456789" 或 "id":123456789
                        r'bizOrderId["\']?\s*[:=]\s*["\']?(\d{10,})',  # bizOrderId=123456789
                    ]

                    for pattern in patterns:
                        matches = re.findall(pattern, message_str)
                        if matches:
                            # 取第一个匹配的订单ID
                            order_id = matches[0]
                            logger.info(f'【{self.cookie_id}】✅ 从消息字符串中提取到订单ID: {order_id} (模式: {pattern})')
                            break

                except Exception as search_e:
                    logger.warning(f"在消息字符串中搜索订单ID失败: {search_e}")

            if order_id:
                logger.info(f'【{self.cookie_id}】🎯 最终提取到订单ID: {order_id}')
            else:
                logger.warning(f'【{self.cookie_id}】❌ 未能从消息中提取到订单ID')

            return order_id

        except Exception as e:
            logger.error(f"【{self.cookie_id}】提取订单ID失败: {self._safe_str(e)}")
            return None

    @staticmethod
    def _extract_order_event_status(message: dict) -> str:
        """从交易卡片中识别可安全落库的订单状态。"""
        if not isinstance(message, dict):
            return None

        message_1 = message.get("1")
        if not isinstance(message_1, dict):
            return None

        message_detail = message_1.get("10")
        event_text = message_detail.get("reminderContent", "") if isinstance(message_detail, dict) else ""
        if not event_text:
            content = message_1.get("6")
            content_detail = content.get("3") if isinstance(content, dict) else None
            event_text = content_detail.get("2", "") if isinstance(content_detail, dict) else ""

        return {
            "[我已拍下，待付款]": "processing",
            "[我已付款，等待你发货]": "pending_ship",
            "[买家已付款]": "pending_ship",
            "[付款完成]": "pending_ship",
            "[已付款，待发货]": "pending_ship",
            "[你已发货]": "shipped",
            "[你已发货，请等待买家确认收货]": "shipped",
            "[买家确认收货，交易成功]": "completed",
            "[你已确认收货，交易成功]": "completed",
            "[退款成功，钱款已原路退返]": "cancelled",
            "[你关闭了订单，钱款已原路退返]": "cancelled",
        }.get(str(event_text).strip())

    def _save_order_event_snapshot(
        self,
        order_id: str,
        message: dict,
        item_id: str = None,
        buyer_id: str = None,
    ) -> bool:
        """订单详情暂不可用时，先保存交易卡片中可信的基础信息。"""
        order_status = self._extract_order_event_status(message)
        if not order_id or not order_status:
            return False

        try:
            from app.db_manager import db_manager

            message_1 = message.get("1") if isinstance(message, dict) else None
            message_1 = message_1 if isinstance(message_1, dict) else {}
            chat_id_raw = message_1.get("2", "")
            chat_id = str(chat_id_raw).split("@")[0] if chat_id_raw else ""

            created_at = None
            create_time = message_1.get("5")
            if create_time:
                try:
                    created_at = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(int(create_time) / 1000),
                    )
                except (TypeError, ValueError, OSError):
                    created_at = None

            # 金额和数量必须来自卖家端接口的真实成交数据。
            # 旧实现取商品挂牌价并把数量固定为 1，多件和议价订单会算错，
            # 这里只在接口不可用时保留状态，不再伪造金额。
            amount = None
            buy_num = None
            auction_price = None
            confirm_fee = None
            refund_fee = None
            post_fee = None
            receiver_name = None
            receiver_phone = None
            receiver_address = None
            real_values = self._pending_order_real_values.pop(order_id, None)
            if real_values:
                amount = real_values.get("amount") or None
                buy_num = real_values.get("buy_num")
                auction_price = real_values.get("auction_price") or None
                confirm_fee = real_values.get("confirm_fee") or None
                refund_fee = real_values.get("refund_fee") or None
                post_fee = real_values.get("post_fee") or None
                receiver_name = real_values.get("receiver_name") or None
                receiver_phone = real_values.get("receiver_phone") or None
                receiver_address = real_values.get("receiver_address") or None

            existing_order = db_manager.get_order_by_id(order_id)
            snapshot_item_id = item_id
            snapshot_buyer_id = buyer_id
            snapshot_quantity = str(buy_num) if buy_num else None
            snapshot_created_at = created_at
            if existing_order:
                snapshot_item_id = item_id if not existing_order.get("item_id") else None
                snapshot_buyer_id = buyer_id if not existing_order.get("buyer_id") else None
                snapshot_created_at = created_at if not existing_order.get("created_at") else None

            saved = db_manager.insert_or_update_order(
                order_id=order_id,
                item_id=snapshot_item_id,
                buyer_id=snapshot_buyer_id,
                quantity=snapshot_quantity,
                amount=amount,
                order_status=order_status,
                cookie_id=self.cookie_id,
                created_at=snapshot_created_at,
                chat_id=chat_id,
                buy_num=buy_num,
                auction_price=auction_price,
                confirm_fee=confirm_fee,
                refund_fee=refund_fee,
                post_fee=post_fee,
                receiver_name=receiver_name,
                receiver_phone=receiver_phone,
                receiver_address=receiver_address,
            )
            if saved:
                source = "卖家端接口" if real_values else "交易卡片"
                logger.info(
                    f"【{self.cookie_id}】已保存订单快照（金额来源: {source}）: "
                    f"order_id={order_id}, item_id={item_id}, buyer_id={buyer_id}, status={order_status}"
                )
            return saved
        except Exception as e:
            logger.error(f"【{self.cookie_id}】保存订单事件快照失败 {order_id}: {self._safe_str(e)}")
            return False

    async def fetch_order_real_values(self, order_id: str) -> dict:
        """通过卖家端 sold.get 获取订单的真实成交数据。

        取代按商品挂牌价推算金额的做法；失败时返回空字典，由调用方决定降级策略。
        """
        if not order_id or not self.cookies_str:
            return {}

        try:
            from utils.xianyu_seller_api import (
                XianyuSellerAPI,
                SellerApiError,
                parse_sold_order,
            )

            api = XianyuSellerAPI(self.cookie_id, self.cookies_str)
            try:
                batch = await api.get_sold_orders(order_ids=str(order_id), rows_per_page=10)
                # 卖家端会下发新的签名令牌，同步回本实例避免后续请求失效
                if api.cookies_str and api.cookies_str != self.cookies_str:
                    self.cookies_str = api.cookies_str
            finally:
                await api.close()

            for item in batch.get("items") or []:
                parsed = parse_sold_order(item)
                if parsed.get("order_id") == str(order_id):
                    return parsed

            logger.warning(f"【{self.cookie_id}】卖家端未返回订单 {order_id} 的成交数据")
            return {}
        except SellerApiError as exc:
            logger.warning(f"【{self.cookie_id}】获取订单真实成交数据失败 {order_id}: {exc}")
            return {}
        except Exception as e:
            logger.error(
                f"【{self.cookie_id}】获取订单真实成交数据异常 {order_id}: {self._safe_str(e)}"
            )
            return {}

    async def sync_sold_orders(self, days: int = 7, query_code: str = "ALL") -> dict:
        """全量同步卖出订单，作为消息驱动的兜底对账。

        不按时间筛选 —— 卖家端接口本身只保留近期订单，加时间条件会把边界订单切掉。
        ``days`` 和 ``query_code`` 仅为兼容旧调用保留，实际不再使用。

        Returns:
            ``{"total": int, "saved": int, "failed": int, ...}``
        """
        if not self.cookies_str:
            return {"total": 0, "saved": 0, "failed": 0}

        from utils.seller_order_sync import sync_account_orders

        result = await sync_account_orders(self.cookie_id, self.cookies_str)

        # 同步接口下发的新令牌，避免后续请求签名失效
        new_cookies = result.get("cookies_str")
        if new_cookies and new_cookies != self.cookies_str:
            self.cookies_str = new_cookies

        return result

    async def _handle_auto_delivery(self, websocket, message: dict, send_user_name: str, send_user_id: str,
                                   item_id: str, chat_id: str, msg_time: str):
        """统一处理自动发货逻辑"""
        try:
            # 检查商品是否属于当前cookies
            if item_id and item_id != "未知商品":
                try:
                    from app.db_manager import db_manager
                    item_info = db_manager.get_item_info(self.cookie_id, item_id)
                    if not item_info:
                        logger.warning(f'[{msg_time}] 【{self.cookie_id}】❌ 商品 {item_id} 不属于当前账号，跳过自动发货')
                        return
                    logger.warning(f'[{msg_time}] 【{self.cookie_id}】✅ 商品 {item_id} 归属验证通过')
                except Exception as e:
                    logger.error(f'[{msg_time}] 【{self.cookie_id}】检查商品归属失败: {self._safe_str(e)}，跳过自动发货')
                    return

            # 提取订单ID
            order_id = self._extract_order_id(message)

            # 如果order_id不存在，直接返回
            if not order_id:
                logger.warning(f'[{msg_time}] 【{self.cookie_id}】❌ 未能提取到订单ID，跳过自动发货')
                return

            # 发货前必须确认订单归属和已付款状态，避免伪造文本或旧消息误触发。
            from app.db_manager import db_manager
            current_order = db_manager.get_order_by_id(order_id)
            if current_order:
                if str(current_order.get('cookie_id') or '') != str(self.cookie_id):
                    logger.error(f'[{msg_time}] 【{self.cookie_id}】订单 {order_id} 不属于当前账号，拒绝自动发货')
                    return
                if current_order.get('item_id') and str(current_order.get('item_id')) != str(item_id):
                    logger.error(f'[{msg_time}] 【{self.cookie_id}】订单 {order_id} 商品归属不一致，拒绝自动发货')
                    return
                if current_order.get('buyer_id') and str(current_order.get('buyer_id')) != str(send_user_id):
                    logger.error(f'[{msg_time}] 【{self.cookie_id}】订单 {order_id} 买家归属不一致，拒绝自动发货')
                    return

            order_status = (current_order or {}).get('order_status')
            order_detail = None
            if order_status != 'pending_ship':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】订单 {order_id} 本地状态为 {order_status or "未记录"}，拉取详情确认付款状态')
                order_detail = await self.fetch_order_detail_info(order_id, item_id, send_user_id)
                if order_detail:
                    order_status = order_detail.get('order_status')
                if not order_status or order_status == 'unknown':
                    refreshed_order = db_manager.get_order_by_id(order_id)
                    order_status = (refreshed_order or {}).get('order_status')

            if order_status != 'pending_ship':
                logger.warning(
                    f'[{msg_time}] 【{self.cookie_id}】订单 {order_id} 未确认处于待发货状态'
                    f'（当前: {order_status or "unknown"}），跳过自动发货'
                )
                return

            logger.info(f'[{msg_time}] 【{self.cookie_id}】订单 {order_id} 已确认付款并等待发货')

            # 使用订单ID作为锁的键
            lock_key = order_id

            # 第一重检查：延迟锁状态（在获取锁之前检查，避免不必要的等待）
            if self.is_lock_held(lock_key):
                logger.info(f'[{msg_time}] 【{self.cookie_id}】🔒【提前检查】订单 {lock_key} 延迟锁仍在持有状态，跳过发货')
                return

            # 第二重检查：基于时间的冷却机制
            if not self.can_auto_delivery(order_id):
                logger.info(f'[{msg_time}] 【{self.cookie_id}】订单 {order_id} 在冷却期内，跳过发货')
                return

            # 获取或创建该订单的锁
            order_lock = self._order_locks[lock_key]

            # 更新锁的使用时间
            self._lock_usage_times[lock_key] = time.time()

            # 使用异步锁防止同一订单的并发处理
            async with order_lock:
                logger.info(f'[{msg_time}] 【{self.cookie_id}】获取订单锁成功: {lock_key}，开始处理自动发货')

                # 第三重检查：获取锁后再次检查延迟锁状态（双重检查，防止在等待锁期间状态发生变化）
                if self.is_lock_held(lock_key):
                    logger.info(f'[{msg_time}] 【{self.cookie_id}】订单 {lock_key} 在获取锁后检查发现延迟锁仍持有，跳过发货')
                    return

                # 第四重检查：获取锁后再次检查冷却状态
                if not self.can_auto_delivery(order_id):
                    logger.info(f'[{msg_time}] 【{self.cookie_id}】订单 {order_id} 在获取锁后检查发现仍在冷却期，跳过发货')
                    return

                protection_result = await self.apply_delivery_block_rules(
                    order_id=order_id,
                    buyer_id=send_user_id,
                    item_id=item_id,
                    chat_id=chat_id,
                    websocket=websocket,
                )
                if protection_result["action"] == "block":
                    logger.warning(
                        f'[{msg_time}] 【{self.cookie_id}】订单 {order_id} 已停止自动发货: '
                        f'{protection_result["reason"]}'
                    )
                    return
                card_only_delivery = protection_result["action"] == "card_only"

                # 构造用户URL
                user_url = f'https://www.goofish.com/personal?userId={send_user_id}'

                # 自动发货逻辑
                try:
                    # 设置默认标题（将通过API获取真实商品信息）
                    item_title = "待获取商品信息"

                    logger.info(f"【{self.cookie_id}】准备自动发货: item_id={item_id}, item_title={item_title}")

                    # 检查是否需要多数量发货
                    quantity_to_send = 1  # 默认发送1个

                    # 检查商品是否开启了多数量发货
                    multi_quantity_delivery = db_manager.get_item_multi_quantity_delivery_status(self.cookie_id, item_id)

                    if multi_quantity_delivery and order_id:
                        logger.info(f"商品 {item_id} 开启了多数量发货，获取订单详情...")
                        try:
                            # 付款校验阶段可能已经拉取过详情，优先复用。
                            if order_detail is None:
                                order_detail = await self.fetch_order_detail_info(order_id, item_id, send_user_id)
                            if order_detail and order_detail.get('quantity'):
                                try:
                                    order_quantity = int(order_detail['quantity'])
                                    if order_quantity > 1:
                                        quantity_to_send = order_quantity
                                        logger.info(f"从订单详情获取数量: {order_quantity}，将发送 {quantity_to_send} 个卡券")
                                    else:
                                        logger.info(f"订单数量为 {order_quantity}，发送单个卡券")
                                except (ValueError, TypeError):
                                    logger.warning(f"订单数量格式无效: {order_detail.get('quantity')}，发送单个卡券")
                            else:
                                logger.info(f"未获取到订单数量信息，发送单个卡券")
                        except Exception as e:
                            logger.error(f"获取订单详情失败: {self._safe_str(e)}，发送单个卡券")
                    elif not multi_quantity_delivery:
                        logger.info(f"商品 {item_id} 未开启多数量发货，发送单个卡券")
                    else:
                        logger.info(f"无订单ID，发送单个卡券")

                    # 先解析一次商品规格与库存绑定，再按订单数量和每件发货份数取内容。
                    delivery_contents = []
                    delivery_context = {}

                    try:
                        first_content = await self._auto_delivery(
                            item_id,
                            item_title,
                            order_id,
                            send_user_id,
                            order_detail=order_detail,
                            delivery_context=delivery_context,
                            requested_item_quantity=quantity_to_send,
                        )
                    except Exception as e:
                        logger.error(f"第 1 个卡券获取异常: {self._safe_str(e)}")
                        first_content = None

                    if first_content:
                        per_item_delivery_count = max(
                            1,
                            int(delivery_context.get("delivery_count") or 1),
                        )
                        quantity_to_send *= per_item_delivery_count
                        delivery_contents.append(first_content)
                        logger.info(
                            f"自动发货数量已确定: 订单商品数量系数="
                            f"{max(1, quantity_to_send // per_item_delivery_count)}, "
                            f"每件发货={per_item_delivery_count}，合计={quantity_to_send}"
                        )
                    else:
                        logger.warning("第 1 个卡券内容获取失败，停止本次自动发货")

                    for i in range(1, quantity_to_send):
                        if not delivery_contents:
                            break
                        try:
                            # 每次调用都可能获取不同的内容（API卡券、批量数据等）
                            delivery_content = await self._auto_delivery(
                                item_id,
                                item_title,
                                order_id,
                                send_user_id,
                                order_detail=order_detail,
                                delivery_context=delivery_context,
                            )
                            if delivery_content:
                                delivery_contents.append(delivery_content)
                                if quantity_to_send > 1:
                                    logger.info(f"第 {i+1}/{quantity_to_send} 个卡券内容获取成功")
                            else:
                                logger.warning(f"第 {i+1}/{quantity_to_send} 个卡券内容获取失败")
                        except Exception as e:
                            logger.error(f"第 {i+1}/{quantity_to_send} 个卡券获取异常: {self._safe_str(e)}")

                    if delivery_contents:
                        # 标记锁为持有状态，并启动延迟释放任务
                        self._lock_hold_info[lock_key] = {
                            'locked': True,
                            'lock_time': time.time(),
                            'release_time': None,
                            'task': None
                        }

                        # 启动延迟释放锁的异步任务（10分钟后释放）
                        delay_task = asyncio.create_task(self._delayed_lock_release(lock_key, delay_minutes=10))
                        self._lock_hold_info[lock_key]['task'] = delay_task

                        # 发送所有获取到的发货内容
                        sent_count = 0
                        send_errors = []
                        for i, delivery_content in enumerate(delivery_contents):
                            try:
                                # 检查是否是图片发送标记
                                if delivery_content.startswith("__IMAGE_SEND__"):
                                    # 提取卡券ID和图片URL
                                    image_data = delivery_content.replace("__IMAGE_SEND__", "")
                                    if "|" in image_data:
                                        card_id_str, image_url = image_data.split("|", 1)
                                        try:
                                            card_id = int(card_id_str)
                                        except ValueError:
                                            logger.error(f"无效的卡券ID: {card_id_str}")
                                            card_id = None
                                    else:
                                        # 兼容旧格式（没有卡券ID）
                                        card_id = None
                                        image_url = image_data

                                    # 发送图片消息
                                    await self.send_image_msg(websocket, chat_id, send_user_id, image_url, card_id=card_id)
                                    if len(delivery_contents) > 1:
                                        logger.info(f'[{msg_time}] 【多数量自动发货图片】第 {i+1}/{len(delivery_contents)} 张已向 {user_url} 发送图片: {image_url}')
                                    else:
                                        logger.info(f'[{msg_time}] 【自动发货图片】已向 {user_url} 发送图片: {image_url}')

                                    # 多数量发货时，消息间隔1秒
                                    if len(delivery_contents) > 1 and i < len(delivery_contents) - 1:
                                        await asyncio.sleep(1)

                                else:
                                    # 普通文本发货内容
                                    await self.send_msg(websocket, chat_id, send_user_id, delivery_content)
                                    if len(delivery_contents) > 1:
                                        logger.info(f'[{msg_time}] 【多数量自动发货】第 {i+1}/{len(delivery_contents)} 条已向 {user_url} 发送发货内容')
                                    else:
                                        logger.info(f'[{msg_time}] 【自动发货】已向 {user_url} 发送发货内容')

                                    # 多数量发货时，消息间隔1秒
                                    if len(delivery_contents) > 1 and i < len(delivery_contents) - 1:
                                        await asyncio.sleep(1)

                                sent_count += 1
                            except Exception as e:
                                error_message = self._safe_str(e)
                                send_errors.append(f"第{i + 1}条: {error_message}")
                                logger.error(f"发送第 {i+1} 条消息失败: {error_message}")

                        acquired_all = len(delivery_contents) == quantity_to_send
                        sent_all = sent_count == len(delivery_contents)

                        if acquired_all and sent_all:
                            confirm_required = self.is_auto_confirm_enabled() and not card_only_delivery
                            platform_confirmed = False
                            confirm_error = None

                            if confirm_required:
                                try:
                                    confirm_result = await self.auto_confirm(order_id, item_id)
                                    platform_confirmed = bool(confirm_result and confirm_result.get('success'))
                                    if platform_confirmed:
                                        self.confirmed_orders[order_id] = time.time()
                                    else:
                                        confirm_error = (confirm_result or {}).get('error', '未知错误')
                                except Exception as confirm_exception:
                                    confirm_error = self._safe_str(confirm_exception)

                            # 卡券全部发送后才记录系统已发货；订单状态只在闲鱼确认成功后推进。
                            self.mark_delivery_sent(order_id, update_order_status=platform_confirmed)
                            try:
                                db_manager.insert_or_update_order(
                                    order_id=order_id,
                                    system_shipped=True,
                                    chat_id=chat_id
                                )
                                logger.info(f'【{self.cookie_id}】订单 {order_id} 已标记为系统已发货 (system_shipped=1)')
                            except Exception as db_e:
                                logger.error(f'【{self.cookie_id}】更新订单system_shipped状态失败: {self._safe_str(db_e)}')

                            if card_only_delivery:
                                await self.send_delivery_failure_notification(
                                    send_user_name,
                                    send_user_id,
                                    item_id,
                                    f"订单命中“{protection_result['rule_name']}”并已关闭，仅发送卡券成功",
                                    chat_id
                                )
                            elif confirm_required and not platform_confirmed:
                                await self.send_delivery_failure_notification(
                                    send_user_name,
                                    send_user_id,
                                    item_id,
                                    f"卡券已全部发送，但闲鱼确认发货失败，请手动确认：{confirm_error}",
                                    chat_id
                                )
                            elif len(delivery_contents) > 1:
                                await self.send_delivery_failure_notification(send_user_name, send_user_id, item_id, f"多数量发货成功，共发送 {sent_count} 个卡券", chat_id)
                            else:
                                await self.send_delivery_failure_notification(send_user_name, send_user_id, item_id, "发货成功", chat_id)
                        else:
                            # 内容可能已从批量卡池取出，自动重试可能重复消耗或重复发送，转人工处理。
                            self.delivery_blocked_orders.add(order_id)
                            self.last_delivery_time[order_id] = time.time()
                            failure_detail = (
                                f"应发 {quantity_to_send} 个，获取 {len(delivery_contents)} 个，"
                                f"成功发送 {sent_count} 个"
                            )
                            if send_errors:
                                failure_detail += f"；发送错误：{'；'.join(send_errors)}"
                            logger.error(f"【{self.cookie_id}】订单 {order_id} 自动发货未完整完成：{failure_detail}")
                            await self.send_delivery_failure_notification(
                                send_user_name,
                                send_user_id,
                                item_id,
                                f"自动发货未完整完成（{failure_detail}），已停止自动重试，请人工核对",
                                chat_id
                            )
                    else:
                        logger.warning(f'[{msg_time}] 【自动发货】未找到匹配的发货规则或获取发货内容失败')
                        # 发送自动发货失败通知
                        await self.send_delivery_failure_notification(send_user_name, send_user_id, item_id, "未找到匹配的发货规则或获取发货内容失败", chat_id)

                except Exception as e:
                    logger.error(f"自动发货处理异常: {self._safe_str(e)}")
                    # 发送自动发货异常通知
                    await self.send_delivery_failure_notification(send_user_name, send_user_id, item_id, f"自动发货处理异常: {str(e)}", chat_id)

                logger.info(f'[{msg_time}] 【{self.cookie_id}】订单锁释放: {lock_key}，自动发货处理完成')

        except Exception as e:
            logger.error(f"统一自动发货处理异常: {self._safe_str(e)}")



    async def refresh_token(self, captcha_retry_count: int = 0):
        """刷新token

        Args:
            captcha_retry_count: 滑块验证重试次数，用于防止无限递归
        """
        # 初始化通知发送标志，避免重复发送通知
        notification_sent = False
        # 本轮是否已经记过一次风控熔断。滑块失败分支和后面基于 ret 的通用分支
        # 都会 trip()，同一次失败记两次会让冷却阶梯跳级、账号被多锁一倍时间。
        already_tripped = False
        
        try:
            logger.info(f"【{self.cookie_id}】开始刷新token... (滑块验证重试次数: {captcha_retry_count})")
            # 标记本次刷新状态
            self.last_token_refresh_status = "started"
            # 重置“刷新流程内已重启”标记，避免多次重启
            self.restarted_in_browser_refresh = False

            # 风控冷却期内不再尝试刷新 —— 持续请求会让风控一直不解除
            from utils import risk_control
            guard = risk_control.registry.get(self.cookie_id)
            if guard.is_blocked:
                logger.warning(
                    f"【{self.cookie_id}】处于风控冷却期（剩余 {guard.remaining_seconds} 秒），"
                    f"跳过本次 Token 刷新"
                )
                self.last_token_refresh_status = "risk_control_blocked"
                return None

            # 检查滑块验证重试次数，防止无限递归
            if captcha_retry_count >= self.max_captcha_verification_count:
                logger.error(f"【{self.cookie_id}】滑块验证重试次数已达上限 ({self.max_captcha_verification_count})，停止重试")
                await self.send_token_refresh_notification(
                    f"滑块验证重试次数已达上限，请手动处理",
                    "captcha_max_retries_exceeded"
                )
                notification_sent = True
                return None

            # 【消息接收检查】检查是否在消息接收后的冷却时间内，与 cookie_refresh_loop 保持一致
            current_time = time.time()
            time_since_last_message = current_time - self.last_message_received_time
            if self.last_message_received_time > 0 and time_since_last_message < self.message_cookie_refresh_cooldown:
                remaining_time = self.message_cookie_refresh_cooldown - time_since_last_message
                remaining_minutes = int(remaining_time // 60)
                remaining_seconds = int(remaining_time % 60)
                logger.info(f"【{self.cookie_id}】收到消息后冷却中，放弃本次token刷新，还需等待 {remaining_minutes}分{remaining_seconds}秒")
                # 标记为因冷却而跳过（正常情况）
                self.last_token_refresh_status = "skipped_cooldown"
                return None

            # 【重要】在刷新token前，先从数据库重新加载最新的cookie
            # 这样即使用户已经手动更新了cookie，代码也会使用最新的cookie
            logger.info(f"【{self.cookie_id}】开始执行Cookie刷新任务...")
            # await self._execute_cookie_refresh(time.time())
            try:
                from app.db_manager import db_manager
                # 必须走线程池。db_manager 是同步 SQLite 且带全局锁，直接在事件
                # 循环里调用会把整个循环卡住 —— 此时 HTTP 线程通过
                # run_coroutine_threadsafe 提交的删除、更新等操作永远得不到调度，
                # 表现为「点删除账号没反应，最后报超时」。
                account_info = await asyncio.to_thread(
                    db_manager.get_cookie_details, self.cookie_id
                )
                if account_info and account_info.get('cookie_value'):
                    new_cookies_str = account_info.get('cookie_value')
                    if new_cookies_str != self.cookies_str:
                        logger.info(f"【{self.cookie_id}】检测到数据库中的cookie已更新，重新加载cookie")
                        self.cookies_str = new_cookies_str
                        # 更新cookies字典
                        self.cookies = trans_cookies(self.cookies_str)
                        logger.warning(f"【{self.cookie_id}】Cookie已从数据库重新加载")
            except Exception as reload_e:
                logger.warning(f"【{self.cookie_id}】从数据库重新加载cookie失败，继续使用当前cookie: {self._safe_str(reload_e)}")

            # 生成更精确的时间戳
            timestamp = str(int(time.time() * 1000))

            params = {
                'jsv': '2.7.2',
                'appKey': '34839810',
                't': timestamp,
                'sign': '',
                'v': '1.0',
                'type': 'originaljson',
                'accountSite': 'xianyu',
                'dataType': 'json',
                'timeout': '20000',
                'api': 'mtop.taobao.idlemessage.pc.login.token',
                'sessionOption': 'AutoLoginOnly',
                'dangerouslySetWindvaneParams': '%5Bobject%20Object%5D',
                'smToken': 'token',
                'queryToken': 'sm',
                'sm': 'sm',
                'spm_cnt': 'a21ybx.im.0.0',
                'spm_pre': 'a21ybx.home.sidebar.1.4c053da6vYwnmf',
                'log_id': '4c053da6vYwnmf'
            }
            data_val = '{"appKey":"444e9908a51d1cb236a27862abc769c9","deviceId":"' + self.device_id + '"}'
            data = {
                'data': data_val,
            }

            # 获取token
            token = None
            token = trans_cookies(self.cookies_str).get('_m_h5_tk', '').split('_')[0] if trans_cookies(self.cookies_str).get('_m_h5_tk') else ''

            sign = generate_sign(params['t'], token, data_val)
            params['sign'] = sign

            # 发送请求 - 使用与浏览器完全一致的请求头
            headers = {
                'accept': 'application/json',
                'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'cache-control': 'no-cache',
                'content-type': 'application/x-www-form-urlencoded',
                'pragma': 'no-cache',
                'priority': 'u=1, i',
                'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
                'referer': 'https://www.goofish.com/',
                'origin': 'https://www.goofish.com',
                'cookie': self.cookies_str
            }

            api_url = API_ENDPOINTS.get('token')
            cookie_dict = trans_cookies(self.cookies_str)
            logger.info(
                f"【{self.cookie_id}】Token刷新请求: endpoint={api_url}, method=POST, "
                f"cookie_fields={len(cookie_dict)}, cookie_length={len(self.cookies_str)}, "
                f"token_present={bool(token)}, token_length={len(token)}, "
                f"payload_length={len(data_val)}"
            )

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    params=params,
                    data=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    logger.info(
                        f"【{self.cookie_id}】Token刷新响应: status={response.status}, "
                        f"content_type={response.headers.get('content-type', 'unknown')}"
                    )
                    
                    res_json = await response.json()
                    response_keys = sorted(res_json.keys()) if isinstance(res_json, dict) else []
                    response_data = res_json.get("data") if isinstance(res_json, dict) else None
                    data_keys = sorted(response_data.keys()) if isinstance(response_data, dict) else []
                    # ret 是闲鱼说明失败原因的唯一字段（TOKEN 过期、未登录、风控拦截
                    # 各有不同取值）。原先只记结构不记 ret，日志里只能看到
                    # 「data_keys=[] / Token获取失败」，等于把唯一的线索丢了。
                    response_ret = res_json.get("ret") if isinstance(res_json, dict) else None
                    logger.info(
                        f"【{self.cookie_id}】Token刷新响应结构: "
                        f"type={type(res_json).__name__}, keys={response_keys}, "
                        f"data_keys={data_keys}, ret={response_ret}, "
                        f"has_access_token={isinstance(response_data, dict) and bool(response_data.get('accessToken'))}"
                    )
                    logger.info(f"【{self.cookie_id}】================================")

                    # 检查并更新Cookie
                    if 'set-cookie' in response.headers:
                        new_cookies = {}
                        for cookie in response.headers.getall('set-cookie', []):
                            if '=' in cookie:
                                name, value = cookie.split(';')[0].split('=', 1)
                                new_cookies[name.strip()] = value.strip()

                        # 更新cookies
                        if new_cookies:
                            self.cookies.update(new_cookies)
                            # 生成新的cookie字符串
                            self.cookies_str = '; '.join([f"{k}={v}" for k, v in self.cookies.items()])
                            # 更新数据库中的Cookie
                            await self.update_config_cookies()
                            logger.warning("已更新Cookie到数据库")

                    if isinstance(res_json, dict):
                        ret_value = res_json.get('ret', [])
                        # 检查ret是否包含成功信息
                        if any('SUCCESS::调用成功' in ret for ret in ret_value):
                            if 'data' in res_json and 'accessToken' in res_json['data']:
                                new_token = res_json['data']['accessToken']
                                self.current_token = new_token
                                self.media_host = (
                                    res_json['data'].get('mediaHost')
                                    or "down.im.dingtalk.cn"
                                )
                                self.last_token_refresh_time = time.time()

                                # 【消息接收时间重置】Token刷新成功后重置消息接收标志，与 cookie_refresh_loop 保持一致
                                self.last_message_received_time = 0
                                logger.warning(f"【{self.cookie_id}】Token刷新成功，已重置消息接收时间标识")

                                logger.info(f"【{self.cookie_id}】Token刷新成功")
                                # 标记为成功
                                self.last_token_refresh_status = "success"
                                # 拿到有效 token 就说明登录态是活的，必须清掉
                                # 「需重新扫码」终态标记。它曾经只置不清，于是账号
                                # 明明已经连上、订单和消息都在同步，界面还一直挂着
                                # 「需重新扫码」，把用户引去做一次没必要的扫码。
                                if self.needs_relogin:
                                    logger.info(
                                        f"【{self.cookie_id}】登录态已恢复，"
                                        f"清除「需重新扫码」标记"
                                    )
                                self.needs_relogin = False
                                self.relogin_reason = ''
                                risk_control.registry.get(self.cookie_id).reset()
                                return new_token

                    # 检查是否需要滑块验证
                    if self._need_captcha_verification(res_json):
                        logger.warning(f"【{self.cookie_id}】检测到需要滑块验证，开始处理...")

                        # 记录滑块验证检测到日志文件
                        verification_url = res_json.get('data', {}).get('url', 'Token刷新时检测')
                        log_captcha_event(self.cookie_id, "检测到滑块验证", None, f"触发场景: Token刷新, URL: {verification_url}")

                        # 添加风控日志记录
                        log_id = None
                        try:
                            from app.db_manager import db_manager
                            success = db_manager.add_risk_control_log(
                                cookie_id=self.cookie_id,
                                event_type='slider_captcha',
                                event_description=f"检测到需要滑块验证，触发场景: Token刷新, URL: {verification_url}",
                                processing_status='processing'
                            )
                            if success:
                                # 获取刚插入的记录ID（简单方式，实际应该返回ID）
                                logs = db_manager.get_risk_control_logs(cookie_id=self.cookie_id, limit=1)
                                if logs:
                                    log_id = logs[0].get('id')
                                logger.info(f"【{self.cookie_id}】风控日志记录成功，ID: {log_id}")
                        except Exception as log_e:
                            logger.error(f"【{self.cookie_id}】记录风控日志失败: {log_e}")

                        try:
                            # 尝试通过滑块验证获取新的cookies
                            captcha_start_time = time.time()
                            new_cookies_str = await self._handle_captcha_verification(res_json)
                            captcha_duration = time.time() - captcha_start_time

                            if new_cookies_str:
                                logger.info(f"【{self.cookie_id}】滑块验证成功，准备重启实例...")

                                # 更新风控日志为成功状态
                                if 'log_id' in locals() and log_id:
                                    try:
                                        from app.db_manager import db_manager
                                        db_manager.update_risk_control_log(
                                            log_id=log_id,
                                            processing_result=f"滑块验证成功，耗时: {captcha_duration:.2f}秒, cookies长度: {len(new_cookies_str)}",
                                            processing_status='success'
                                        )
                                    except Exception as update_e:
                                        logger.error(f"【{self.cookie_id}】更新风控日志失败: {update_e}")

                                # 重启实例（cookies已在_handle_captcha_verification中更新到数据库）
                                # await self._restart_instance()
                                
                                # 重新尝试刷新token（递归调用，但有深度限制）
                                return await self.refresh_token(captcha_retry_count + 1)
                            else:
                                logger.error(f"【{self.cookie_id}】滑块验证失败")

                                # 自动验证失败后立即熔断。实测滑块虽被拖到目标位置，
                                # 服务端仍判定失败（行为特征识别），继续自动重试不会成功，
                                # 只会让风控持续更久 —— 此时应转人工处理。
                                risk_control.registry.get(self.cookie_id).trip(
                                    "滑块自动验证失败，需人工处理"
                                )
                                # 本轮已经熔断过，后面基于 ret 的通用风控分支不要再记一次：
                                # 同一次失败连续 trip 两次会让冷却阶梯跳级
                                # （300 秒直接跳到 600 秒），账号被多锁一倍时间。
                                already_tripped = True

                                # 更新风控日志为失败状态
                                if 'log_id' in locals() and log_id:
                                    try:
                                        from app.db_manager import db_manager
                                        db_manager.update_risk_control_log(
                                            log_id=log_id,
                                            processing_result=f"滑块验证失败，耗时: {captcha_duration:.2f}秒, 原因: 未获取到新cookies",
                                            processing_status='failed'
                                        )
                                    except Exception as update_e:
                                        logger.error(f"【{self.cookie_id}】更新风控日志失败: {update_e}")
                                
                                # 标记已发送通知（通知已在_handle_captcha_verification中发送）
                                notification_sent = True

                                # 自动验证已无望，给出可操作的人工处理指引。
                                # 滑块被拖到目标位置仍被判失败时，重试再多次也不会通过。
                                try:
                                    await self.send_token_refresh_notification(
                                        "滑块自动验证失败，需要人工处理\n\n"
                                        "处理方式（任选其一）：\n"
                                        "1. 在账号管理页重新扫码登录（最直接）\n"
                                        "2. 用浏览器登录 www.goofish.com 手动完成验证后更新 Cookie\n\n"
                                        "系统已暂停该账号的自动请求，避免风控加重。",
                                        "captcha_manual_required",
                                    )
                                except Exception as notify_error:
                                    logger.warning(
                                        f"【{self.cookie_id}】发送人工处理通知失败: "
                                        f"{self._safe_str(notify_error)}"
                                    )
                        except Exception as captcha_e:
                            logger.error(f"【{self.cookie_id}】滑块验证处理异常: {self._safe_str(captcha_e)}")

                            # 更新风控日志为异常状态
                            captcha_duration = time.time() - captcha_start_time if 'captcha_start_time' in locals() else 0
                            if 'log_id' in locals() and log_id:
                                try:
                                    from app.db_manager import db_manager
                                    db_manager.update_risk_control_log(
                                        log_id=log_id,
                                        processing_result=f"滑块验证处理异常，耗时: {captcha_duration:.2f}秒",
                                        processing_status='failed',
                                        error_message=str(captcha_e)
                                    )
                                except Exception as update_e:
                                    logger.error(f"【{self.cookie_id}】更新风控日志失败: {update_e}")
                            
                            # 标记已发送通知（通知已在_handle_captcha_verification中发送）
                            notification_sent = True

                    # 「令牌过期」和「Session过期」必须分开处理 —— 它们不是一回事：
                    #
                    #   FAIL_SYS_TOKEN_EXOIRED::令牌过期
                    #       mtop 的签名令牌 _m_h5_tk 过时了。失败响应本身就会
                    #       set-cookie 下发新令牌，重签一次即可，属可恢复。
                    #   FAIL_SYS_SESSION_EXPIRED::Session过期
                    #       登录会话（cookie2 / unb）真的死了，滑块和等待都救不回来，
                    #       只能重新扫码。
                    #
                    # 原来一个 if 把两者一起打上「需重新扫码」终态，于是仅仅令牌
                    # 过期也会让界面提示重扫；而实测紧接着的下一次刷新就返回
                    # SUCCESS，账号完全正常。
                    if isinstance(res_json, dict):
                        res_json_str = json.dumps(res_json, ensure_ascii=False, separators=(',', ':'))
                        session_expired = 'Session过期' in res_json_str
                        token_expired = '令牌过期' in res_json_str

                        if token_expired and not session_expired:
                            # 令牌已随本次响应更新，直接带新令牌重试。必须递增计数：
                            # 递归上限由 refresh_token 开头的
                            # max_captcha_verification_count 统一把关。
                            logger.warning(
                                f"【{self.cookie_id}】签名令牌过期（可恢复），"
                                f"带新令牌重试第 {captcha_retry_count + 1} 次"
                            )
                            return await self.refresh_token(captcha_retry_count + 1)

                        if session_expired:
                            # 调用统一的密码登录刷新方法
                            refresh_success = await self._try_password_login_refresh("Session过期")

                            if not refresh_success:
                                # 会话过期和风控是两回事：滑块过了也救不回来，只能重新登录。
                                # 打上终态标记，让界面能明确提示"请重新扫码"，
                                # 否则用户只看到「连接中/重连」，会一直等一个不会好的状态。
                                self.needs_relogin = True
                                self.relogin_reason = '闲鱼登录态已过期，请重新扫码登录'
                                logger.error(
                                    f"【{self.cookie_id}】登录态已过期且无法自动续期"
                                    f"（未配置账号密码或密码登录失败），需要重新扫码登录"
                                )
                                # 标记已发送通知，避免重复通知
                                notification_sent = True
                                # 返回None，让调用者知道刷新失败
                                return None
                            else:
                                self.needs_relogin = False
                                self.relogin_reason = ''
                                # 刷新成功后重新获取 token。必须递增计数，否则上限判断
                                # 永远不成立，会形成无限递归重试并持续加剧平台风控。
                                return await self.refresh_token(captcha_retry_count + 1)

                    ret_value = res_json.get('ret', []) if isinstance(res_json, dict) else []
                    logger.error(
                        f"【{self.cookie_id}】Token刷新失败: status={response.status}, "
                        f"ret={ret_value[:3]}, response_type={type(res_json).__name__}"
                    )

                    # 平台风控：立刻熔断，避免重试风暴反复触发验证
                    if risk_control.is_risk_control_error(json.dumps(ret_value, ensure_ascii=False)):
                        if not already_tripped:
                            guard.trip(str(ret_value[:2]))
                        self.last_token_refresh_status = "risk_control"
                        return None

                    # 清空当前token，确保下次重试时重新获取
                    self.current_token = None

                    # 只有在没有发送过通知的情况下才发送Token刷新失败通知
                    # 并且WebSocket未连接时才发送（已连接说明只是暂时失败）
                    if not notification_sent:
                        # 检查WebSocket连接状态
                        is_ws_connected = (
                            self.connection_state == ConnectionState.CONNECTED and 
                            self.ws and 
                            not self.ws.closed
                        )
                        
                        if is_ws_connected:
                            logger.info(f"【{self.cookie_id}】WebSocket连接正常，Token刷新失败可能是暂时的，跳过失败通知")
                        else:
                            logger.warning(f"【{self.cookie_id}】WebSocket未连接，发送Token刷新失败通知")
                            await self.send_token_refresh_notification(
                                f"Token刷新失败: {ret_value[:3]}",
                                "token_refresh_failed",
                            )
                    else:
                        logger.info(f"【{self.cookie_id}】已发送滑块验证相关通知，跳过Token刷新失败通知")
                    return None

        except Exception as e:
            logger.error(f"Token刷新异常: {self._safe_str(e)}")

            # 清空当前token，确保下次重试时重新获取
            self.current_token = None

            # 只有在没有发送过通知的情况下才发送Token刷新异常通知
            # 并且WebSocket未连接时才发送（已连接说明只是暂时失败）
            if not notification_sent:
                # 检查WebSocket连接状态
                is_ws_connected = (
                    self.connection_state == ConnectionState.CONNECTED and 
                    self.ws and 
                    not self.ws.closed
                )
                
                if is_ws_connected:
                    logger.info(f"【{self.cookie_id}】WebSocket连接正常，Token刷新异常可能是暂时的，跳过失败通知")
                else:
                    logger.warning(f"【{self.cookie_id}】WebSocket未连接，发送Token刷新异常通知")
                    await self.send_token_refresh_notification(f"Token刷新异常: {str(e)}", "token_refresh_exception")
            else:
                logger.info(f"【{self.cookie_id}】已发送滑块验证相关通知，跳过Token刷新异常通知")
            return None

    def _need_captcha_verification(self, res_json: dict) -> bool:
        """检查响应是否需要滑块验证"""
        try:
            if not isinstance(res_json, dict):
                return False

            log_captcha_event(
                self.cookie_id,
                "检查滑块验证响应",
                None,
                f"响应字段: {sorted(res_json.keys())}",
            )

            # 检查返回的错误信息
            ret_value = res_json.get('ret', [])
            if not ret_value:
                return False

            # 检查是否包含需要验证的关键词
            captcha_keywords = [
                'FAIL_SYS_USER_VALIDATE',  # 用户验证失败
                'RGV587_ERROR',            # 风控错误
                '哎哟喂,被挤爆啦',          # 被挤爆了
                '哎哟喂，被挤爆啦',         # 被挤爆了（中文逗号）
                '挤爆了',                  # 挤爆了
                '请稍后重试',              # 请稍后重试
                'punish?x5secdata',        # 惩罚页面
                'captcha',                 # 验证码
            ]

            error_msg = str(ret_value[0]) if ret_value else ''

            # 检查错误信息是否包含需要验证的关键词
            for keyword in captcha_keywords:
                if keyword in error_msg:
                    logger.info(f"【{self.cookie_id}】检测到需要滑块验证的关键词: {keyword}")
                    return True

            # 检查data字段中是否包含验证URL
            data = res_json.get('data', {})
            if isinstance(data, dict) and 'url' in data:
                url = data.get('url', '')
                if 'punish' in url or 'captcha' in url or 'validate' in url:
                    logger.info(f"【{self.cookie_id}】检测到验证URL: {url}")
                    return True

            return False

        except Exception as e:
            logger.error(f"【{self.cookie_id}】检查是否需要滑块验证时出错: {self._safe_str(e)}")
            return False

    async def _handle_captcha_verification(self, res_json: dict) -> str:
        """处理滑块验证，返回新的cookies字符串"""
        try:
            logger.info(f"【{self.cookie_id}】开始处理滑块验证...")

            # 获取验证URL
            verification_url = None

            # 从data字段获取URL
            data = res_json.get('data', {})
            if isinstance(data, dict) and 'url' in data:
                verification_url = data.get('url')

            # 如果没有找到URL，使用默认的验证页面
            if not verification_url:
                logger.info(f"【{self.cookie_id}】未找到验证URL，认为不需要滑块验证，返回正常")
                return None

            logger.info(f"【{self.cookie_id}】验证URL: {verification_url}")

            # 使用滑块验证器（独立实例，解决并发冲突）
            try:
                # 使用集成的滑块验证方法（无需猴子补丁）
                from utils.xianyu_slider_stealth import XianyuSliderStealth
                logger.info(f"【{self.cookie_id}】XianyuSliderStealth导入成功，使用滑块验证")

                # 创建独立的滑块验证实例（每个用户独立实例，避免并发冲突）
                # headless 必须为 False：实测同一账号、同一轨迹下，
                # 无头 0/2 通过，有头 1/3 通过且平台确认解除风控。
                # Chrome 无头的 WebGL 渲染器、字体列表、navigator.plugins、
                # 屏幕参数与有头差异巨大，会被阿里 nc 直接识破。
                # 服务器无显示器时用 Xvfb 提供虚拟显示：
                #   xvfb-run -a --server-args="-screen 0 1920x1080x24" python Start.py
                slider_headless = os.getenv('SLIDER_HEADLESS', 'false').lower() == 'true'
                slider_stealth = XianyuSliderStealth(
                    user_id=f"{self.cookie_id}",
                    enable_learning=True,  # 启用学习功能
                    headless=slider_headless
                )

                # 在线程池中执行滑块验证
                import asyncio
                import concurrent.futures

                loop = asyncio.get_event_loop()
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    # 执行滑块验证。必须把账号 Cookie 一并传入 ——
                    # 惩罚页的 x5secdata 绑定账号会话，不带 Cookie 时即使滑块拖过，
                    # 回收到的也只是空浏览器凭证，风控不会解除。
                    success, cookies = await loop.run_in_executor(
                        executor,
                        slider_stealth.run,
                        verification_url,
                        self.cookies_str
                    )

                if success and cookies:
                    # 边界防御：只有 x5sec 才是通行凭证。x5secdata / x5sectag 是挑战
                    # 标记，必然存在，不能拿它们当验证通过的证据 —— 否则会把一堆
                    # 挑战 cookie 写回账号，token 刷新永远 FAIL_SYS_USER_VALIDATE。
                    if 'x5sec' not in {k.lower() for k in cookies}:
                        logger.error(
                            f"【{self.cookie_id}】滑块返回的 cookie 中没有 x5sec，"
                            f"视觉通过但服务端未放行，按失败处理。"
                            f"已有key: {list(cookies.keys())}"
                        )
                        success = False
                        cookies = None

                if success and cookies:
                    logger.info(f"【{self.cookie_id}】滑块验证成功，获取到新的cookies")

                    # 只提取x5sec相关的cookie值进行更新
                    updated_cookies = self.cookies.copy()  # 复制现有cookies
                    new_cookie_count = 0
                    updated_cookie_count = 0
                    x5sec_cookies = {}

                    # 筛选出x5相关的cookies（包括x5sec, x5step等）
                    for cookie_name, cookie_value in cookies.items():
                        cookie_name_lower = cookie_name.lower()
                        if cookie_name_lower.startswith('x5') or 'x5sec' in cookie_name_lower:
                            x5sec_cookies[cookie_name] = cookie_value

                    logger.info(f"【{self.cookie_id}】找到{len(x5sec_cookies)}个x5相关cookies: {list(x5sec_cookies.keys())}")

                    # 只更新x5相关的cookies
                    for cookie_name, cookie_value in x5sec_cookies.items():
                        if cookie_name in updated_cookies:
                            if updated_cookies[cookie_name] != cookie_value:
                                logger.warning(f"【{self.cookie_id}】更新x5 cookie: {cookie_name}")
                                updated_cookies[cookie_name] = cookie_value
                                updated_cookie_count += 1
                            else:
                                logger.warning(f"【{self.cookie_id}】x5 cookie值未变: {cookie_name}")
                        else:
                            logger.warning(f"【{self.cookie_id}】新增x5 cookie: {cookie_name}")
                            updated_cookies[cookie_name] = cookie_value
                            new_cookie_count += 1

                    # 拿到 x5sec 就必须清掉挑战标记。x5secdata / x5sectag 表示"这个请求
                    # 还有一道未完成的人机验证"，而 x5sec 才是通过凭证。
                    # 原来只做新增和覆盖、从不删除，于是滑块过了以后 Cookie 里
                    # x5sec 和旧的 x5secdata 同时存在 —— 闲鱼据此认为挑战仍未完成，
                    # 继续返回 FAIL_SYS_USER_VALIDATE，表现为"滑块过了却一直用不了"。
                    if 'x5sec' in {k.lower() for k in x5sec_cookies}:
                        for stale in CAPTCHA_CHALLENGE_COOKIES:
                            for name in [k for k in updated_cookies if k.lower() == stale]:
                                # 本次滑块响应又下发了同名值时以新值为准，不要删
                                if name not in x5sec_cookies:
                                    updated_cookies.pop(name, None)
                                    logger.warning(
                                        f"【{self.cookie_id}】已清除过期的验证挑战标记: {name}"
                                    )

                    # 将合并后的cookies字典转换为字符串格式
                    cookies_str = "; ".join([f"{k}={v}" for k, v in updated_cookies.items()])

                    logger.info(f"【{self.cookie_id}】x5 Cookie更新完成: 新增{new_cookie_count}个, 更新{updated_cookie_count}个, 总计{len(updated_cookies)}个")

                    # 自动更新数据库中的cookie
                    try:
                        # 备份原有cookies
                        old_cookies_str = self.cookies_str
                        old_cookies_dict = self.cookies.copy()

                        # 更新当前实例的cookies（使用合并后的cookies）
                        self.cookies_str = cookies_str
                        self.cookies = updated_cookies

                        # 更新数据库中的cookies
                        await self.update_config_cookies()
                        logger.info(f"【{self.cookie_id}】滑块验证成功后，数据库cookies已自动更新")

                            
                        log_captcha_event(self.cookie_id, "滑块验证成功并自动更新数据库", True,
                            f"cookies长度: {len(cookies_str)}, 新增{new_cookie_count}个x5, 更新{updated_cookie_count}个x5, 总计{len(updated_cookies)}个cookie项, x5字段: {sorted(x5sec_cookies.keys())}")

                        # 发送成功通知
                        await self.send_token_refresh_notification(
                            f"滑块验证成功，cookies已自动更新到数据库",
                            "captcha_success_auto_update"
                        )

                    except Exception as update_e:
                        logger.error(f"【{self.cookie_id}】自动更新数据库cookies失败: {self._safe_str(update_e)}")

                        # 回滚cookies
                        self.cookies_str = old_cookies_str
                        self.cookies = old_cookies_dict

                        log_captcha_event(self.cookie_id, "滑块验证成功但数据库更新失败", False,
                            f"更新异常: {self._safe_str(update_e)[:100]}, x5字段: {sorted(x5sec_cookies.keys())}")

                        # 发送更新失败通知
                        await self.send_token_refresh_notification(
                            f"滑块验证成功但数据库更新失败: {self._safe_str(update_e)}",
                            "captcha_success_db_update_failed"
                        )

                    return cookies_str
                else:
                    logger.error(f"【{self.cookie_id}】滑块验证失败")

                    # 记录滑块验证失败到日志文件
                    log_captcha_event(self.cookie_id, "滑块验证失败", False,
                        f"XianyuSliderStealth执行失败, 环境: {'Docker' if os.getenv('DOCKER_ENV') else '本地'}")

                    # 发送通知（检查WebSocket连接状态）
                    # 只有在WebSocket未连接时才发送通知，已连接说明可能是暂时性问题
                    is_ws_connected = (
                        self.connection_state == ConnectionState.CONNECTED and 
                        self.ws and 
                        not self.ws.closed
                    )
                    
                    if is_ws_connected:
                        logger.info(f"【{self.cookie_id}】WebSocket连接正常，滑块验证失败可能是暂时的，跳过通知")
                    else:
                        logger.warning(f"【{self.cookie_id}】WebSocket未连接，发送滑块验证失败通知")
                        await self.send_token_refresh_notification(
                            f"滑块验证失败，需要手动处理。验证URL: {verification_url}",
                            "captcha_verification_failed"
                        )
                    return None

            except ImportError as import_e:
                logger.error(f"【{self.cookie_id}】XianyuSliderStealth导入失败: {import_e}")
                logger.error(f"【{self.cookie_id}】请安装Playwright库: pip install playwright")

                # 记录导入失败到日志文件
                log_captcha_event(self.cookie_id, "XianyuSliderStealth导入失败", False,
                    f"Playwright未安装, 错误: {import_e}")

                # 发送通知
                await self.send_token_refresh_notification(
                    f"滑块验证功能不可用，请安装Playwright。验证URL: {verification_url}",
                    "captcha_dependency_missing"
                )
                return None

            except Exception as stealth_e:
                logger.error(f"【{self.cookie_id}】滑块验证异常: {self._safe_str(stealth_e)}")

                # 记录异常到日志文件
                log_captcha_event(self.cookie_id, "滑块验证异常", False,
                    f"执行异常, 错误: {self._safe_str(stealth_e)[:100]}")

                # 发送通知（检查WebSocket连接状态）
                # 只有在WebSocket未连接时才发送通知，已连接说明可能是暂时性问题
                is_ws_connected = (
                    self.connection_state == ConnectionState.CONNECTED and 
                    self.ws and 
                    not self.ws.closed
                )
                
                if is_ws_connected:
                    logger.info(f"【{self.cookie_id}】WebSocket连接正常，滑块验证执行异常可能是暂时的，跳过通知")
                else:
                    logger.warning(f"【{self.cookie_id}】WebSocket未连接，发送滑块验证执行异常通知")
                    await self.send_token_refresh_notification(
                        f"滑块验证执行异常，需要手动处理。验证URL: {verification_url}",
                        "captcha_execution_error"
                    )
                return None



        except Exception as e:
            logger.error(f"【{self.cookie_id}】处理滑块验证时出错: {self._safe_str(e)}")
            return None

    async def _update_cookies_and_restart(self, new_cookies_str: str):
        """更新cookies并重启任务"""
        try:
            logger.info(f"【{self.cookie_id}】开始更新cookies并重启任务...")

            # 验证新cookies的有效性
            if not new_cookies_str or not new_cookies_str.strip():
                logger.error(f"【{self.cookie_id}】新cookies为空，无法更新")
                return False

            # 解析新cookies，确保格式正确
            try:
                new_cookies_dict = trans_cookies(new_cookies_str)
                if not new_cookies_dict:
                    logger.error(f"【{self.cookie_id}】新cookies解析失败，无法更新")
                    return False
                logger.info(f"【{self.cookie_id}】新cookies解析成功，包含 {len(new_cookies_dict)} 个字段")
            except Exception as parse_e:
                logger.error(f"【{self.cookie_id}】新cookies解析异常: {self._safe_str(parse_e)}")
                return False

            # 合并cookies：保留原有cookies，只更新新获取到的字段
            try:
                # 获取当前的cookies字典
                current_cookies_dict = trans_cookies(self.cookies_str)
                logger.info(f"【{self.cookie_id}】当前cookies包含 {len(current_cookies_dict)} 个字段")

                # 合并cookies：新cookies覆盖旧cookies中的相同字段
                merged_cookies_dict = current_cookies_dict.copy()
                updated_fields = []

                for key, value in new_cookies_dict.items():
                    if key in merged_cookies_dict:
                        if merged_cookies_dict[key] != value:
                            merged_cookies_dict[key] = value
                            updated_fields.append(key)
                    else:
                        merged_cookies_dict[key] = value
                        updated_fields.append(f"{key}(新增)")

                if updated_fields:
                    logger.info(f"【{self.cookie_id}】更新的cookie字段: {', '.join(updated_fields)}")
                else:
                    logger.info(f"【{self.cookie_id}】没有cookie字段需要更新")

                # 重新组装cookies字符串
                merged_cookies_str = '; '.join([f"{k}={v}" for k, v in merged_cookies_dict.items()])
                logger.info(f"【{self.cookie_id}】合并后cookies包含 {len(merged_cookies_dict)} 个字段")
                
                # 打印合并后的Cookie字段详情
                logger.info(f"【{self.cookie_id}】========== 合并后Cookie字段详情 ==========")
                logger.info(f"【{self.cookie_id}】Cookie字段数: {len(merged_cookies_dict)}")
                logger.info(f"【{self.cookie_id}】Cookie字段列表:")
                for i, (key, value) in enumerate(merged_cookies_dict.items(), 1):
                    if len(str(value)) > 50:
                        logger.info(f"【{self.cookie_id}】  {i:2d}. {key}: {str(value)[:30]}...{str(value)[-20:]} (长度: {len(str(value))})")
                    else:
                        logger.info(f"【{self.cookie_id}】  {i:2d}. {key}: {value}")
                
                # 检查关键字段
                important_keys = ['unb', '_m_h5_tk', '_m_h5_tk_enc', 'cookie2', 't', 'sgcookie', 'cna']
                logger.info(f"【{self.cookie_id}】关键字段检查:")
                for key in important_keys:
                    if key in merged_cookies_dict:
                        val = merged_cookies_dict[key]
                        logger.info(f"【{self.cookie_id}】  ✅ {key}: {'存在' if val else '为空'} (长度: {len(str(val)) if val else 0})")
                    else:
                        logger.info(f"【{self.cookie_id}】  ❌ {key}: 缺失")
                logger.info(f"【{self.cookie_id}】==========================================")

                # 使用合并后的cookies字符串
                new_cookies_str = merged_cookies_str
                new_cookies_dict = merged_cookies_dict

            except Exception as merge_e:
                logger.error(f"【{self.cookie_id}】cookies合并异常: {self._safe_str(merge_e)}")
                logger.warning(f"【{self.cookie_id}】将使用原始新cookies（不合并）")
                # 如果合并失败，继续使用原始的new_cookies_str

            # 备份原有cookies，以防更新失败需要回滚
            old_cookies_str = self.cookies_str
            old_cookies_dict = self.cookies.copy()

            try:
                # 更新当前实例的cookies
                self.cookies_str = new_cookies_str
                self.cookies = new_cookies_dict

                # 更新数据库中的cookies
                await self.update_config_cookies()
                logger.info(f"【{self.cookie_id}】数据库cookies更新成功")

                # 通过CookieManager重启任务
                logger.info(f"【{self.cookie_id}】通过CookieManager重启任务...")
                await self._restart_instance()
                
                # ⚠️ _restart_instance() 已触发重启，当前任务即将被取消
                # 立即返回，不执行后续代码
                logger.info(f"【{self.cookie_id}】cookies更新成功，重启请求已触发")
                return True

            except Exception as update_e:
                logger.error(f"【{self.cookie_id}】更新cookies过程中出错，尝试回滚: {self._safe_str(update_e)}")

                # 回滚cookies
                try:
                    self.cookies_str = old_cookies_str
                    self.cookies = old_cookies_dict
                    await self.update_config_cookies()
                    logger.info(f"【{self.cookie_id}】cookies已回滚到原始状态")
                except Exception as rollback_e:
                    logger.error(f"【{self.cookie_id}】cookies回滚失败: {self._safe_str(rollback_e)}")

                return False

        except Exception as e:
            logger.error(f"【{self.cookie_id}】更新cookies并重启任务时出错: {self._safe_str(e)}")
            return False

    async def update_config_cookies(self):
        """更新数据库中的cookies（不会覆盖账号密码等其他字段）"""
        try:
            from app.db_manager import db_manager

            # 更新数据库中的Cookie
            if hasattr(self, 'cookie_id') and self.cookie_id:
                try:
                    # 获取当前Cookie的用户ID，避免在刷新时改变所有者
                    current_user_id = None
                    if hasattr(self, 'user_id') and self.user_id:
                        current_user_id = self.user_id

                    # 使用 update_cookie_account_info 避免覆盖其他字段（如 username, password, pause_duration, remark 等）
                    # 这个方法会自动处理新账号和现有账号的情况，不会覆盖账号密码
                    success = db_manager.update_cookie_account_info(
                        self.cookie_id, 
                        cookie_value=self.cookies_str,
                        user_id=current_user_id  # 如果是新账号，需要提供user_id
                    )
                    if not success:
                        # 如果更新失败，记录错误但不使用 save_cookie（避免覆盖账号密码）
                        logger.warning(f"更新Cookie到数据库失败: {self.cookie_id}，但不使用save_cookie避免覆盖账号密码")
                    else:
                        logger.warning(f"已更新Cookie到数据库: {self.cookie_id}")
                except Exception as e:
                    logger.error(f"更新数据库Cookie失败: {self._safe_str(e)}")
                    # 发送数据库更新失败通知
                    await self.send_token_refresh_notification(f"数据库Cookie更新失败: {str(e)}", "db_update_failed")
            else:
                logger.warning("Cookie ID不存在，无法更新数据库")
                # 发送Cookie ID缺失通知
                await self.send_token_refresh_notification("Cookie ID不存在，无法更新数据库", "cookie_id_missing")

        except Exception as e:
            logger.error(f"更新Cookie失败: {self._safe_str(e)}")
            # 发送Cookie更新失败通知
            await self.send_token_refresh_notification(f"Cookie更新失败: {str(e)}", "cookie_update_failed")

    async def _try_password_login_refresh(self, trigger_reason: str = "令牌/Session过期"):
        """尝试通过密码登录刷新Cookie并重启实例
        
        Args:
            trigger_reason: 触发原因，用于日志记录
            
        Returns:
            bool: 是否成功刷新Cookie
        """
        logger.warning(f"【{self.cookie_id}】检测到{trigger_reason}，准备刷新Cookie并重启实例...")

        # 检查是否在密码登录冷却期内，避免重复登录
        current_time = time.time()
        last_password_login = XianyuLive._last_password_login_time.get(self.cookie_id, 0)
        time_since_last_login = current_time - last_password_login
        
        if last_password_login > 0 and time_since_last_login < XianyuLive._password_login_cooldown:
            remaining_time = XianyuLive._password_login_cooldown - time_since_last_login
            logger.warning(f"【{self.cookie_id}】距离上次密码登录仅 {time_since_last_login:.1f} 秒，仍在冷却期内（还需等待 {remaining_time:.1f} 秒），跳过密码登录")
            logger.warning(f"【{self.cookie_id}】提示：如果新Cookie仍然无效，请检查账号状态或手动更新Cookie")
            return False

        # 记录到日志文件
        log_captcha_event(self.cookie_id, f"{trigger_reason}触发Cookie刷新和实例重启", None,
            f"检测到{trigger_reason}，准备刷新Cookie并重启实例")

        try:
            # 从数据库获取账号登录信息
            from app.db_manager import db_manager
            account_info = db_manager.get_cookie_details(self.cookie_id)
            
            if not account_info:
                logger.error(f"【{self.cookie_id}】无法获取账号信息")
                return False
            
            # 【重要】先检查数据库中的cookie是否已经更新
            # 如果用户已经手动更新了cookie，就不需要触发密码登录刷新
            db_cookie_value = account_info.get('cookie_value', '')
            if db_cookie_value and db_cookie_value != self.cookies_str:
                logger.info(f"【{self.cookie_id}】检测到数据库中的cookie已更新，重新加载cookie")
                self.cookies_str = db_cookie_value
                self.cookies = trans_cookies(self.cookies_str)
                logger.info(f"【{self.cookie_id}】Cookie已从数据库重新加载，跳过密码登录刷新")
                return True
            
            username = account_info.get('username', '')
            password = account_info.get('password', '')
            show_browser = account_info.get('show_browser', False)
            
            # 检查是否配置了用户名和密码
            if not username or not password:
                logger.warning(f"【{self.cookie_id}】未配置用户名或密码，跳过密码登录刷新")
                await self.send_token_refresh_notification(
                    f"检测到{trigger_reason}，但未配置用户名或密码，无法自动刷新Cookie",
                    "no_credentials"
                )
                return False
            
            # 使用集成的 Playwright 登录方法（无需猴子补丁）
            from utils.xianyu_slider_stealth import XianyuSliderStealth
            browser_mode = "有头" if show_browser else "无头"
            logger.info(f"【{self.cookie_id}】开始使用{browser_mode}浏览器进行密码登录刷新Cookie...")
            logger.info(f"【{self.cookie_id}】使用账号: {username}")
            
            # 创建一个通知回调包装函数，支持接收截图路径和验证链接
            async def notification_callback_wrapper(message: str, screenshot_path: str = None, verification_url: str = None):
                """通知回调包装函数，支持接收截图路径和验证链接"""
                await self.send_token_refresh_notification(
                    error_message=message,
                    notification_type="token_refresh",
                    chat_id=None,
                    attachment_path=screenshot_path,
                    verification_url=verification_url
                )
            
            # 在单独的线程中运行同步的登录方法
            import asyncio
            slider = XianyuSliderStealth(user_id=self.cookie_id, enable_learning=False, headless=not show_browser)
            result = await asyncio.to_thread(
                slider.login_with_password_playwright,
                account=username,
                password=password,
                show_browser=show_browser,
                notification_callback=notification_callback_wrapper
            )
            
            if result:
                logger.info(f"【{self.cookie_id}】密码登录成功，获取到Cookie")
                logger.info(
                    f"【{self.cookie_id}】Cookie读取完成: "
                    f"fields={len(result)}, names={sorted(result.keys())}"
                )
                
                # 打印密码登录获取的Cookie字段详情
                logger.info(f"【{self.cookie_id}】========== 密码登录Cookie字段详情 ==========")
                logger.info(f"【{self.cookie_id}】Cookie字段数: {len(result)}")
                logger.info(f"【{self.cookie_id}】Cookie字段列表:")
                for i, (key, value) in enumerate(result.items(), 1):
                    if len(str(value)) > 50:
                        logger.info(f"【{self.cookie_id}】  {i:2d}. {key}: {str(value)[:30]}...{str(value)[-20:]} (长度: {len(str(value))})")
                    else:
                        logger.info(f"【{self.cookie_id}】  {i:2d}. {key}: {value}")
                
                # 检查关键字段
                important_keys = ['unb', '_m_h5_tk', '_m_h5_tk_enc', 'cookie2', 't', 'sgcookie', 'cna']
                logger.info(f"【{self.cookie_id}】关键字段检查:")
                for key in important_keys:
                    if key in result:
                        val = result[key]
                        logger.info(f"【{self.cookie_id}】  ✅ {key}: {'存在' if val else '为空'} (长度: {len(str(val)) if val else 0})")
                    else:
                        logger.info(f"【{self.cookie_id}】  ❌ {key}: 缺失")
                logger.info(f"【{self.cookie_id}】==========================================")
                
                # 将cookie字典转换为字符串格式
                new_cookies_str = '; '.join([f"{k}={v}" for k, v in result.items()])
                logger.info(
                    f"【{self.cookie_id}】密码登录Cookie已获取: "
                    f"字段数={len(result)}, 字符串长度={len(new_cookies_str)}"
                )
                
                # 记录密码登录时间，防止重复登录
                XianyuLive._last_password_login_time[self.cookie_id] = time.time()
                logger.warning(f"【{self.cookie_id}】已记录密码登录时间，冷却期 {XianyuLive._password_login_cooldown} 秒")
                
                # 更新cookies并重启任务
                update_success = await self._update_cookies_and_restart(new_cookies_str)
                
                if update_success:
                    logger.info(f"【{self.cookie_id}】Cookie更新并重启任务成功")
                    # 发送账号密码登录成功通知
                    await self.send_token_refresh_notification(
                        f"账号密码登录成功，Cookie已更新，任务已重启",
                        "password_login_success"
                    )
                    return True
                else:
                    logger.error(f"【{self.cookie_id}】Cookie更新失败")
                    return False
                    
            else:
                logger.warning(f"【{self.cookie_id}】密码登录失败，未获取到Cookie")
                return False

        except Exception as refresh_e:
            logger.error(f"【{self.cookie_id}】Cookie刷新或实例重启失败: {self._safe_str(refresh_e)}")
            import traceback
            logger.error(f"【{self.cookie_id}】详细堆栈:\n{traceback.format_exc()}")
            return False

    async def _verify_cookie_validity(self) -> dict:
        """验证Cookie的有效性，通过实际调用API测试
        
        Returns:
            dict: {
                'valid': bool,  # 总体是否有效
                'confirm_api': bool,  # 确认发货API是否有效
                'image_api': bool,  # 图片上传API是否有效
                'details': str  # 详细信息
            }
        """
        logger.info(f"【{self.cookie_id}】开始验证Cookie有效性（使用真实API调用）...")
        
        result = {
            'valid': True,
            'confirm_api': None,
            'image_api': None,
            'details': []
        }
        
        # 1. 测试确认发货API - 使用测试订单ID实际调用
        # try:
        #     logger.info(f"【{self.cookie_id}】测试确认发货API（使用测试数据实际调用）...")
            
        #     # 确保session存在
        #     if not self.session:
        #         import aiohttp
        #         connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
        #         timeout = aiohttp.ClientTimeout(total=30)
        #         self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            
        #     # 创建临时的确认发货实例
        #     from app.secure_confirm import SecureConfirm
        #     confirm_tester = SecureConfirm(
        #         session=self.session,
        #         cookies_str=self.cookies_str,
        #         cookie_id=self.cookie_id,
        #         main_instance=self
        #     )
            
        #     # 使用一个测试订单ID（不存在的订单ID）
        #     # 如果Cookie有效，应该返回"订单不存在"类的错误
        #     # 如果Cookie无效，会返回"Session过期"错误
        #     test_order_id = "999999999999999999"  # 不存在的测试订单ID
            
        #     # 实际调用API (retry_count=3阻止重试，快速失败)
        #     response = await confirm_tester.auto_confirm(test_order_id, retry_count=3)
            
        #     # 分析响应
        #     if response and isinstance(response, dict):
        #         error_msg = str(response.get('error', ''))
        #         success = response.get('success', False)
                
        #         # 检查是否是Session过期错误
        #         if 'Session过期' in error_msg or 'SESSION_EXPIRED' in error_msg:
        #             logger.warning(f"【{self.cookie_id}】❌ 确认发货API验证失败: Session过期")
        #             result['confirm_api'] = False
        #             result['valid'] = False
        #             result['details'].append("确认发货API: Session过期")
        #         elif '令牌过期' in error_msg:
        #             logger.warning(f"【{self.cookie_id}】❌ 确认发货API验证失败: 令牌过期")
        #             result['confirm_api'] = False
        #             result['valid'] = False
        #             result['details'].append("确认发货API: 令牌过期")
        #         elif success:
        #             # 竟然成功了（不太可能，因为是测试订单ID）
        #             logger.info(f"【{self.cookie_id}】✅ 确认发货API验证通过: API调用成功")
        #             result['confirm_api'] = True
        #             result['details'].append("确认发货API: 通过验证")
        #         elif error_msg and len(error_msg) > 0:
        #             # 有其他错误信息（如订单不存在、重试次数过多等），说明Cookie是有效的
        #             logger.info(f"【{self.cookie_id}】✅ 确认发货API验证通过: Cookie有效（返回业务错误: {error_msg[:50]}）")
        #             result['confirm_api'] = True
        #             result['details'].append(f"确认发货API: 通过验证")
        #         else:
        #             # 没有明确信息，保守认为可能有问题
        #             logger.warning(f"【{self.cookie_id}】⚠️ 确认发货API验证警告: 响应不明确")
        #             result['confirm_api'] = False
        #             result['valid'] = False
        #             result['details'].append("确认发货API: 响应不明确")
        #     else:
        #         # 没有响应，可能有问题
        #         logger.warning(f"【{self.cookie_id}】⚠️ 确认发货API验证警告: 无响应")
        #         result['confirm_api'] = False
        #         result['valid'] = False
        #         result['details'].append("确认发货API: 无响应")
                    
        # except Exception as e:
        #     error_str = self._safe_str(e)
        #     # 检查异常信息中是否包含Session过期
        #     if 'Session过期' in error_str or 'SESSION_EXPIRED' in error_str:
        #         logger.warning(f"【{self.cookie_id}】❌ 确认发货API验证失败: Session过期")
        #         result['confirm_api'] = False
        #         result['valid'] = False
        #         result['details'].append("确认发货API: Session过期")
        #     else:
        #         logger.error(f"【{self.cookie_id}】确认发货API验证异常: {error_str}")
        #         # 网络异常等问题，不一定是Cookie问题，暂时标记为通过
        #         result['confirm_api'] = True
        #         result['details'].append(f"确认发货API: 调用异常(可能非Cookie问题)")
        
        # 2. 测试图片上传API - 创建测试图片并实际上传
        try:
            logger.info(f"【{self.cookie_id}】测试图片上传API（使用测试图片实际上传）...")
            
            # 创建一个最小的测试图片（1x1像素的PNG）
            import tempfile
            import os
            from PIL import Image
            
            # 创建临时目录
            temp_dir = tempfile.gettempdir()
            test_image_path = os.path.join(temp_dir, f'cookie_test_{self.cookie_id}.png')
            
            try:
                # 创建1x1像素的白色图片
                img = Image.new('RGB', (1, 1), color='white')
                img.save(test_image_path, 'PNG')
                logger.info(f"【{self.cookie_id}】已创建测试图片: {test_image_path}")
                
                # 创建图片上传实例
                from utils.image_uploader import ImageUploader
                uploader = ImageUploader(cookies_str=self.cookies_str)
                
                # 创建session
                await uploader.create_session()
                
                try:
                    # 实际上传测试图片
                    upload_result = await uploader.upload_image(test_image_path)
                finally:
                    # 确保关闭session
                    await uploader.close_session()
                
                # 分析上传结果
                if upload_result:
                    # 上传成功，Cookie有效
                    logger.info(f"【{self.cookie_id}】✅ 图片上传API验证通过: 上传成功 ({upload_result[:50]}...)")
                    result['image_api'] = True
                    result['details'].append("图片上传API: 通过验证")
                else:
                    # 上传失败，需要进一步判断原因
                    # 如果是Cookie失效，通常会返回HTML登录页面
                    logger.warning(f"【{self.cookie_id}】❌ 图片上传API验证失败: 上传失败（可能是Cookie失效）")
                    result['image_api'] = False
                    result['valid'] = False
                    result['details'].append("图片上传API: 上传失败，可能Cookie已失效")
                
            finally:
                # 清理测试图片
                if os.path.exists(test_image_path):
                    try:
                        os.remove(test_image_path)
                        logger.debug(f"【{self.cookie_id}】已删除测试图片")
                    except:
                        pass
                        
        except Exception as e:
            error_str = self._safe_str(e)
            logger.error(f"【{self.cookie_id}】图片上传API验证异常: {error_str}")
            # 图片上传异常，标记为失败
            result['image_api'] = False
            result['valid'] = False
            result['details'].append(f"图片上传API: 验证异常 - {error_str[:50]}")
        
        # 汇总结果
        if result['valid']:
            logger.info(f"【{self.cookie_id}】✅ Cookie验证通过: 所有关键API均可用")
        else:
            logger.warning(f"【{self.cookie_id}】❌ Cookie验证失败:")
            for detail in result['details']:
                logger.warning(f"【{self.cookie_id}】  - {detail}")
        
        result['details'] = '; '.join(result['details'])
        return result

    async def _restart_instance(self):
        """重启XianyuLive实例
        
        ⚠️ 注意：此方法会触发当前任务被取消！
        调用此方法后，当前任务会立即被 CookieManager 取消，
        因此不要在此方法后执行任何重要操作。
        """
        try:
            logger.info(f"【{self.cookie_id}】准备重启实例...")

            # 导入CookieManager
            from app.cookie_manager import manager as cookie_manager

            if cookie_manager:
                # 通过CookieManager重启实例
                logger.info(f"【{self.cookie_id}】通过CookieManager重启实例...")
                
                # ⚠️ 重要：不要等待重启完成！
                # cookie_manager.update_cookie() 会立即取消当前任务
                # 如果我们等待它完成，会导致 CancelledError 中断等待
                # 正确的做法是：触发重启后立即返回，让任务自然退出
                
                import threading
                
                def trigger_restart():
                    """在后台线程中触发重启，不阻塞当前任务"""
                    try:
                        # 给当前任务一点时间完成清理（避免竞态条件）
                        import time
                        time.sleep(0.5)
                        
                        # save_to_db=False 因为 update_config_cookies 已经保存过了
                        cookie_manager.update_cookie(self.cookie_id, self.cookies_str, save_to_db=False)
                        logger.info(f"【{self.cookie_id}】实例重启请求已触发")
                    except Exception as e:
                        logger.error(f"【{self.cookie_id}】触发实例重启失败: {e}")
                        import traceback
                        logger.error(f"【{self.cookie_id}】重启失败详情:\n{traceback.format_exc()}")

                # 在后台线程中触发重启
                restart_thread = threading.Thread(target=trigger_restart, daemon=True)
                restart_thread.start()
                
                logger.info(f"【{self.cookie_id}】实例重启已触发，当前任务即将退出...")
                logger.warning(f"【{self.cookie_id}】注意：重启请求已发送，CookieManager将在0.5秒后取消当前任务并启动新实例")
                    
            else:
                logger.warning(f"【{self.cookie_id}】CookieManager不可用，无法重启实例")

        except Exception as e:
            logger.error(f"【{self.cookie_id}】重启实例失败: {self._safe_str(e)}")
            import traceback
            logger.error(f"【{self.cookie_id}】重启失败堆栈:\n{traceback.format_exc()}")
            # 发送重启失败通知
            try:
                await self.send_token_refresh_notification(f"实例重启失败: {str(e)}", "instance_restart_failed")
            except Exception as notify_e:
                logger.error(f"【{self.cookie_id}】发送重启失败通知时出错: {self._safe_str(notify_e)}")

    async def save_item_info_to_db(self, item_id: str, item_detail: str = None, item_title: str = None):
        """保存商品信息到数据库

        Args:
            item_id: 商品ID
            item_detail: 商品详情内容（可以是任意格式的文本）
            item_title: 商品标题
        """
        try:
            # 跳过以 auto_ 开头的商品ID
            if item_id and item_id.startswith('auto_'):
                logger.warning(f"跳过保存自动生成的商品ID: {item_id}")
                return

            # 验证：如果只有商品ID，没有商品标题和商品详情，则不插入数据库
            if not item_title and not item_detail:
                logger.warning(f"跳过保存商品信息：缺少商品标题和详情 - {item_id}")
                return

            # 如果有商品标题但没有详情，也跳过（根据需求，需要同时有标题和详情）
            if not item_title or not item_detail:
                logger.warning(f"跳过保存商品信息：商品标题或详情不完整 - {item_id}")
                return

            from app.db_manager import db_manager

            # 直接使用传入的详情内容
            item_data = item_detail

            # 保存到数据库
            success = db_manager.save_item_info(self.cookie_id, item_id, item_data)
            if success:
                logger.info(f"商品信息已保存到数据库: {item_id}")
            else:
                logger.warning(f"保存商品信息到数据库失败: {item_id}")

        except Exception as e:
            logger.error(f"保存商品信息到数据库异常: {self._safe_str(e)}")

    async def save_item_detail_only(self, item_id, item_detail):
        """仅保存商品详情（不影响标题等基本信息）"""
        try:
            from app.db_manager import db_manager

            # 使用专门的详情更新方法
            success = db_manager.update_item_detail(self.cookie_id, item_id, item_detail)

            if success:
                logger.info(f"商品详情已更新: {item_id}")
            else:
                logger.warning(f"更新商品详情失败: {item_id}")

            return success

        except Exception as e:
            logger.error(f"更新商品详情异常: {self._safe_str(e)}")
            return False

    async def fetch_item_detail_from_api(self, item_id: str) -> str:
        """获取商品详情（使用浏览器获取，支持24小时缓存）

        Args:
            item_id: 商品ID

        Returns:
            str: 商品详情文本，获取失败返回空字符串
        """
        try:
            # 检查是否启用自动获取功能
            from app.config import config
            auto_fetch_config = config.get('ITEM_DETAIL', {}).get('auto_fetch', {})

            if not auto_fetch_config.get('enabled', True):
                logger.warning(f"自动获取商品详情功能已禁用: {item_id}")
                return ""

            # 1. 首先检查缓存（24小时有效）
            async with self._item_detail_cache_lock:
                if item_id in self._item_detail_cache:
                    cache_data = self._item_detail_cache[item_id]
                    cache_time = cache_data['timestamp']
                    current_time = time.time()

                    # 检查缓存是否在24小时内
                    if current_time - cache_time < self._item_detail_cache_ttl:
                        # 更新访问时间（用于LRU）
                        cache_data['access_time'] = current_time
                        logger.info(f"从缓存获取商品详情: {item_id}")
                        return cache_data['detail']
                    else:
                        # 缓存过期，删除
                        del self._item_detail_cache[item_id]
                        logger.warning(f"缓存已过期，删除: {item_id}")

            # 2. 尝试使用浏览器获取商品详情
            detail_from_browser = await self._fetch_item_detail_from_browser(item_id)
            if detail_from_browser:
                # 保存到缓存（带大小限制）
                await self._add_to_item_cache(item_id, detail_from_browser)
                logger.info(f"成功通过浏览器获取商品详情: {item_id}, 长度: {len(detail_from_browser)}")
                return detail_from_browser

            # 浏览器获取失败
            logger.warning(f"浏览器获取商品详情失败: {item_id}")
            return ""

        except Exception as e:
            logger.error(f"获取商品详情异常: {item_id}, 错误: {self._safe_str(e)}")
            return ""

    async def _add_to_item_cache(self, item_id: str, detail: str):
        """添加商品详情到缓存，实现LRU策略和大小限制
        
        Args:
            item_id: 商品ID
            detail: 商品详情
        """
        async with self._item_detail_cache_lock:
            current_time = time.time()
            
            # 检查缓存大小，如果超过限制则清理
            if len(self._item_detail_cache) >= self._item_detail_cache_max_size:
                # 使用LRU策略删除最久未访问的项
                if self._item_detail_cache:
                    # 找到最久未访问的项
                    oldest_item = min(
                        self._item_detail_cache.items(),
                        key=lambda x: x[1].get('access_time', x[1]['timestamp'])
                    )
                    oldest_item_id = oldest_item[0]
                    del self._item_detail_cache[oldest_item_id]
                    logger.warning(f"缓存已满，删除最旧项: {oldest_item_id}")
            
            # 添加新项到缓存
            self._item_detail_cache[item_id] = {
                'detail': detail,
                'timestamp': current_time,
                'access_time': current_time
            }
            logger.warning(f"添加商品详情到缓存: {item_id}, 当前缓存大小: {len(self._item_detail_cache)}")

    @classmethod
    async def _cleanup_item_cache(cls):
        """清理过期的商品详情缓存"""
        try:
            async with cls._item_detail_cache_lock:
                # 在持有锁时也要能响应取消信号
                await asyncio.sleep(0)
                
                current_time = time.time()
                expired_items = []
                
                # 找出所有过期的项
                for item_id, cache_data in cls._item_detail_cache.items():
                    # 在循环中也要能响应取消信号
                    await asyncio.sleep(0)
                    if current_time - cache_data['timestamp'] >= cls._item_detail_cache_ttl:
                        expired_items.append(item_id)
                
                # 删除过期项
                for item_id in expired_items:
                    await asyncio.sleep(0)  # 让出控制权
                    del cls._item_detail_cache[item_id]
                
                if expired_items:
                    logger.info(f"清理了 {len(expired_items)} 个过期的商品详情缓存")
                
                return len(expired_items)
        except asyncio.CancelledError:
            # 如果被取消，确保锁能正确释放
            raise

    def _get_playwright_launch_options(self, playwright, browser_args, purpose: str) -> dict:
        """构造浏览器启动参数，Playwright浏览器缺失时回退到系统Chrome/Edge。"""
        launch_options = {
            'headless': True,
            'args': browser_args,
            # 显式指定完整版 Chromium。headless=True 时 Playwright 会优先找
            # chromium_headless_shell-*，那是与 chromium-* 分开下载的另一份文件；
            # 下载中断时常常只装上其中一个，于是出现「自检说浏览器已安装、
            # 真正启动却报 Executable doesn't exist」。指定 channel 后只依赖
            # 完整版，与下方 executable_path 的检查也就对得上了。
            'channel': 'chromium',
        }
        bundled_executable = playwright.chromium.executable_path
        if os.path.exists(bundled_executable):
            logger.info(f"【{self.cookie_id}】{purpose}使用Playwright Chromium")
            return launch_options

        system_browser_candidates = [
            ("Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            ("Chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            ("Edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            ("Edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ]
        system_browser = next(
            (
                (name, path)
                for name, path in system_browser_candidates
                if os.path.exists(path)
            ),
            None
        )
        if not system_browser:
            raise RuntimeError(
                f"{purpose}未找到可用浏览器；Playwright预期路径不存在，"
                "系统Chrome/Edge也未找到"
            )

        browser_name, browser_path = system_browser
        launch_options['executable_path'] = browser_path
        # 指定了自定义可执行文件就不能再带 channel，两者互斥
        launch_options.pop('channel', None)
        logger.warning(
            f"【{self.cookie_id}】{purpose}的Playwright Chromium未安装，"
            f"回退使用系统{browser_name}: {browser_path}"
        )
        return launch_options

    @staticmethod
    def _parse_profile_count(value):
        """将“116”或“1.2万”转换为整数。"""
        text = str(value or '').strip().replace(',', '')
        if not text:
            return None
        multiplier = 10000 if text.endswith('万') else 1
        if multiplier > 1:
            text = text[:-1]
        try:
            return int(float(text) * multiplier)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _parse_account_profile_snapshot(cls, snapshot, account_id=''):
        """从个人页的语义文本和图片元数据中提取公开账号资料。"""
        if not isinstance(snapshot, dict):
            return {}

        lines = [
            re.sub(r'\s+', ' ', str(line or '')).strip()
            for line in snapshot.get('body_lines', [])
        ]
        lines = [line for line in lines if line]
        title = re.sub(r'\s+', ' ', str(snapshot.get('title') or '')).strip()
        nickname = re.sub(r'[_\-\s]*闲鱼\s*$', '', title).strip()
        if not nickname or nickname in ('闲鱼', 'Goofish'):
            nickname = next(
                (
                    line for line in lines
                    if line not in ('订单', '我的闲鱼') and len(line) <= 40
                ),
                '',
            )

        followers = None
        following = None
        follower_index = None
        following_index = None
        # 闲鱼个人页的粉丝/关注在不同版本里排布不一：
        #   「123 粉丝」/「粉丝 123」/「粉丝」与「123」分处相邻两行。
        # 原来只用 fullmatch(r'([\d,.]+万?)\s*粉丝') 要求整行严格等于「123 粉丝」，
        # 其余排布一律匹配不到，导致 followers 永远是 None。
        count_pattern = r'[\d,.]+(?:\.\d+)?万?'
        for index, line in enumerate(lines):
            for label, is_follower in (('粉丝', True), ('关注', False)):
                if label not in line:
                    continue
                target = followers if is_follower else following
                if target is not None:
                    continue

                # 同一行内取数字，兼容「123 粉丝」和「粉丝 123」
                m = re.search(rf'({count_pattern})\s*{label}', line) \
                    or re.search(rf'{label}\s*({count_pattern})', line)
                value = cls._parse_profile_count(m.group(1)) if m else None

                # 标签独占一行时，数字通常在相邻行
                if value is None and line.strip() == label:
                    for neighbor in (index + 1, index - 1):
                        if 0 <= neighbor < len(lines):
                            nm = re.fullmatch(count_pattern, lines[neighbor].strip())
                            if nm:
                                value = cls._parse_profile_count(nm.group(0))
                                break

                if value is not None:
                    if is_follower:
                        followers, follower_index = value, index
                    else:
                        following, following_index = value, index

        location = ''
        if follower_index is not None and follower_index > 0:
            candidate = lines[follower_index - 1]
            if candidate != nickname and len(candidate) <= 40:
                location = candidate

        bio = ''
        if following_index is not None:
            stop_texts = {'编辑资料', '宝贝', '信用及评价', '综合', '在售', '已售出'}
            for candidate in lines[following_index + 1:following_index + 5]:
                if candidate in stop_texts:
                    break
                if candidate != nickname and len(candidate) <= 160:
                    bio = candidate
                    break

        avatar_url = ''
        avatar_candidates = []
        for image in snapshot.get('images', []):
            if not isinstance(image, dict):
                continue
            src = str(image.get('src') or '').strip()
            if src.startswith('//'):
                src = f'https:{src}'
            if not src.startswith(('http://', 'https://')):
                continue
            lower_src = src.lower()
            if 'mtopupload' not in lower_src and 'avatar' not in str(
                image.get('class_name') or ''
            ).lower():
                continue
            width = int(image.get('natural_width') or 0)
            height = int(image.get('natural_height') or 0)
            score = width * height
            if account_id and account_id in src:
                score += 100000
            if 'mtopupload' in lower_src:
                score += 50000
            avatar_candidates.append((score, src))
        if avatar_candidates:
            avatar_url = max(avatar_candidates, key=lambda item: item[0])[1]

        profile = {
            'nickname': nickname,
            'avatar_url': avatar_url,
            'location': location,
            'bio': bio,
            'followers': followers,
            'following': following,
        }
        return {
            key: value
            for key, value in profile.items()
            if value not in (None, '')
        }

    async def _sync_account_profile(self):
        """连接成功后把账号昵称和头像同步到数据库。

        资料走接口直连，不受风控熔断影响时才执行；失败不影响主流程，
        下次重连会再试。
        """
        try:
            from utils import risk_control

            if risk_control.registry.get(self.cookie_id).is_blocked:
                logger.debug(f"【{self.cookie_id}】风控冷却中，跳过账号资料同步")
                self._profile_synced = False
                return

            result = await self.fetch_account_profile()
            if not result.get('success'):
                self._profile_synced = False
                return

            profile = result.get('profile') or {}
            if not profile.get('nickname') and not profile.get('avatar_url'):
                self._profile_synced = False
                return

            from app.db_manager import db_manager

            db_manager.update_cookie_profile(self.cookie_id, profile)
            logger.info(
                f"【{self.cookie_id}】账号资料已自动同步: {profile.get('nickname')}"
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._profile_synced = False
            logger.warning(
                f"【{self.cookie_id}】账号资料自动同步失败: {self._safe_str(exc)}"
            )

    async def fetch_account_profile(self):
        """获取账号公开资料。

        优先走接口直连：``mtop.idle.web.user.page.head`` 直接返回结构化的昵称和
        头像，不依赖浏览器。Playwright 抓页面留作兜底 —— 浏览器版本不匹配或未安装
        时那条路会整个失效，而资料为空会让账号列表看起来像没登录成功。
        """
        try:
            from utils.xianyu_seller_api import (
                XianyuSellerAPI,
                SellerApiError,
                parse_user_profile,
            )

            api = XianyuSellerAPI(self.cookie_id, self.cookies_str)
            try:
                profile = parse_user_profile(await api.get_user_profile())
                if api.cookies_str and api.cookies_str != self.cookies_str:
                    self.cookies_str = api.cookies_str
            finally:
                await api.close()

            if profile.get('nickname') or profile.get('avatar_url'):
                logger.info(
                    f"【{self.cookie_id}】账号资料获取成功（接口直连）: "
                    f"{profile.get('nickname')}"
                )
                return {'success': True, 'profile': profile}
            logger.info(f"【{self.cookie_id}】接口未返回资料，回退浏览器抓取")
        except SellerApiError as exc:
            logger.info(f"【{self.cookie_id}】资料接口调用失败，回退浏览器抓取: {exc}")
        except Exception as exc:
            logger.warning(
                f"【{self.cookie_id}】资料接口异常，回退浏览器抓取: {self._safe_str(exc)}"
            )

        return await self._fetch_account_profile_by_browser()

    async def _fetch_account_profile_by_browser(self):
        """使用当前账号Cookie只读抓取闲鱼个人页公开资料。"""
        playwright = None
        browser = None
        context = None
        started_at = time.perf_counter()
        try:
            from playwright.async_api import async_playwright

            playwright = await asyncio.wait_for(async_playwright().start(), timeout=30)
            browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-extensions',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--hide-scrollbars',
                '--mute-audio',
                '--no-default-browser-check',
                '--no-pings',
            ]
            launch_options = self._get_playwright_launch_options(
                playwright,
                browser_args,
                "账号资料抓取",
            )
            browser = await browser_limit.launch_browser(playwright, launch_options, "账号资料抓取")
            context = await browser.new_context(
                viewport={'width': 1440, 'height': 900},
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/138.0.0.0 Safari/537.36'
                ),
            )

            browser_cookies = []
            for cookie_pair in self.cookies_str.split(';'):
                cookie_pair = cookie_pair.strip()
                if '=' not in cookie_pair:
                    continue
                name, value = cookie_pair.split('=', 1)
                browser_cookies.append({
                    'name': name.strip(),
                    'value': value.strip(),
                    'domain': '.goofish.com',
                    'path': '/',
                })
            await context.add_cookies(browser_cookies)

            page = await context.new_page()
            await page.goto(
                f'https://www.goofish.com/personal?userId={self.myid}',
                wait_until='domcontentloaded',
                timeout=30000,
            )
            try:
                await page.wait_for_function(
                    "() => document.body && document.body.innerText.includes('粉丝')",
                    timeout=10000,
                )
            except Exception:
                logger.warning(
                    f"【{self.cookie_id}】账号资料页未在等待时间内出现粉丝信息，继续解析已加载内容"
                )

            snapshot = await page.evaluate(
                """() => ({
                    title: document.title || '',
                    body_lines: (document.body?.innerText || '')
                        .split(/\\r?\\n/)
                        .map(line => line.trim())
                        .filter(Boolean),
                    images: Array.from(document.images).map(image => ({
                        src: image.currentSrc || image.src || '',
                        class_name: String(image.className || ''),
                        natural_width: image.naturalWidth || 0,
                        natural_height: image.naturalHeight || 0
                    }))
                })"""
            )
            profile = self._parse_account_profile_snapshot(snapshot, self.myid)
            if not profile.get('nickname') and not profile.get('avatar_url'):
                raise RuntimeError("个人页未返回可识别的账号资料")

            logger.info(
                f"【{self.cookie_id}】账号资料抓取完成，"
                f"字段={sorted(profile.keys())}，"
                f"耗时={time.perf_counter() - started_at:.2f}s"
            )
            return {'success': True, 'profile': profile}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                f"【{self.cookie_id}】账号资料抓取失败，"
                f"异常类型={type(exc).__name__}，"
                f"耗时={time.perf_counter() - started_at:.2f}s"
            )
            return {
                'success': False,
                'error': '未能从闲鱼个人页获取账号资料',
                'error_type': type(exc).__name__,
            }
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass

    async def _fetch_item_detail_from_browser(self, item_id: str) -> str:
        """使用浏览器获取商品详情"""
        playwright = None
        browser = None
        try:
            from playwright.async_api import async_playwright

            logger.info(f"开始使用浏览器获取商品详情: {item_id}")

            playwright = await async_playwright().start()

            # 启动浏览器（参照order_detail_fetcher的配置）
            browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-features=TranslateUI',
                '--disable-ipc-flooding-protection',
                '--disable-extensions',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--hide-scrollbars',
                '--mute-audio',
                '--no-default-browser-check',
                '--no-pings'
            ]

            # 在Docker环境中添加额外参数
            if os.getenv('DOCKER_ENV'):
                browser_args.extend([
                    # '--single-process',  # 注释掉，避免多用户并发时的进程冲突和资源泄漏
                    '--disable-background-networking',
                    '--disable-client-side-phishing-detection',
                    '--disable-hang-monitor',
                    '--disable-popup-blocking',
                    '--disable-prompt-on-repost',
                    '--disable-web-resources',
                    '--metrics-recording-only',
                    '--safebrowsing-disable-auto-update',
                    '--enable-automation',
                    '--password-store=basic',
                    '--use-mock-keychain'
                ])

            launch_options = self._get_playwright_launch_options(
                playwright,
                browser_args,
                "商品详情获取"
            )
            browser = await browser_limit.launch_browser(playwright, launch_options, "商品详情获取")

            # 创建浏览器上下文
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
            )

            # 设置Cookie
            cookies = []
            for cookie_pair in self.cookies_str.split('; '):
                if '=' in cookie_pair:
                    name, value = cookie_pair.split('=', 1)
                    cookies.append({
                        'name': name.strip(),
                        'value': value.strip(),
                        'domain': '.goofish.com',
                        'path': '/'
                    })

            await context.add_cookies(cookies)
            logger.warning(f"已设置 {len(cookies)} 个Cookie")

            # 创建页面
            page = await context.new_page()

            # 构造商品详情页面URL
            item_url = f"https://www.goofish.com/item?id={item_id}"
            logger.info(f"访问商品页面: {item_url}")

            # 访问页面
            await page.goto(item_url, wait_until='networkidle', timeout=30000)

            # 等待页面完全加载
            await asyncio.sleep(3)

            # 获取商品详情内容
            detail_text = ""
            try:
                # 等待目标元素出现
                await page.wait_for_selector('.desc--GaIUKUQY', timeout=10000)

                # 获取商品详情文本
                detail_element = await page.query_selector('.desc--GaIUKUQY')
                if detail_element:
                    detail_text = await detail_element.inner_text()
                    logger.info(f"成功获取商品详情: {item_id}, 长度: {len(detail_text)}")
                    return detail_text.strip()
                else:
                    logger.warning(f"未找到商品详情元素: {item_id}")

            except Exception as e:
                logger.warning(f"获取商品详情元素失败: {item_id}, 错误: {self._safe_str(e)}")

            return ""

        except Exception as e:
            logger.error(f"浏览器获取商品详情异常: {item_id}, 错误: {self._safe_str(e)}")
            return ""
        finally:
            # 确保资源被正确清理
            try:
                if browser:
                    await browser.close()
                    logger.warning(f"Browser已关闭: {item_id}")
            except Exception as e:
                logger.warning(f"关闭browser时出错: {self._safe_str(e)}")
            
            try:
                if playwright:
                    await playwright.stop()
                    logger.warning(f"Playwright已停止: {item_id}")
            except Exception as e:
                logger.warning(f"停止playwright时出错: {self._safe_str(e)}")


    async def save_items_list_to_db(self, items_list):
        """批量保存商品列表信息到数据库（并发安全）

        Args:
            items_list: 从get_item_list_info获取的商品列表
        """
        try:
            from app.db_manager import db_manager

            # 准备批量数据
            batch_data = []
            items_need_detail = []  # 需要获取详情的商品列表

            for item in items_list:
                item_id = item.get('id')
                if not item_id or item_id.startswith('auto_'):
                    continue

                # 构造商品详情数据
                item_detail = {
                    'title': item.get('title', ''),
                    'price': item.get('price', ''),
                    'price_text': item.get('price_text', ''),
                    'category_id': item.get('category_id', ''),
                    'auction_type': item.get('auction_type', ''),
                    'item_status': item.get('item_status', 0),
                    'detail_url': item.get('detail_url', ''),
                    'web_url': item.get('web_url', ''),  # Web可访问URL
                    'pic_info': item.get('pic_info', {}),
                    'detail_params': item.get('detail_params', {}),
                    'track_params': item.get('track_params', {}),
                    'item_label_data': item.get('item_label_data', {}),
                    'card_type': item.get('card_type', 0)
                }

                # 检查数据库中是否已有详情
                existing_item = db_manager.get_item_info(self.cookie_id, item_id)
                has_detail = existing_item and existing_item.get('item_detail') and existing_item['item_detail'].strip()

                batch_data.append({
                    'cookie_id': self.cookie_id,
                    'item_id': item_id,
                    'item_title': item.get('title', ''),
                    'item_description': '',  # 暂时为空
                    'item_category': str(item.get('category_id', '')),
                    'item_price': item.get('price_text', ''),
                    'item_image': item.get('item_image', ''),
                    'item_detail': json.dumps(item_detail, ensure_ascii=False)
                })

                # 如果没有详情，添加到需要获取详情的列表
                if not has_detail:
                    items_need_detail.append({
                        'item_id': item_id,
                        'item_title': item.get('title', '')
                    })

            if not batch_data:
                logger.info("没有有效的商品数据需要保存")
                return 0

            # 使用批量保存方法（并发安全）
            saved_count = db_manager.batch_save_item_basic_info(batch_data)
            logger.info(f"批量保存商品信息完成: {saved_count}/{len(batch_data)} 个商品")

            # 异步获取缺失的商品详情
            if items_need_detail:
                from app.config import config
                auto_fetch_config = config.get('ITEM_DETAIL', {}).get('auto_fetch', {})

                if auto_fetch_config.get('enabled', True):
                    logger.info(f"发现 {len(items_need_detail)} 个商品缺少详情，开始获取...")
                    detail_success_count = await self._fetch_missing_item_details(items_need_detail)
                    logger.info(f"成功获取 {detail_success_count}/{len(items_need_detail)} 个商品的详情")
                else:
                    logger.info(f"发现 {len(items_need_detail)} 个商品缺少详情，但自动获取功能已禁用")

            return saved_count

        except Exception as e:
            logger.error(f"批量保存商品信息异常: {self._safe_str(e)}")
            return 0

    async def _fetch_missing_item_details(self, items_need_detail):
        """批量获取缺失的商品详情

        Args:
            items_need_detail: 需要获取详情的商品列表

        Returns:
            int: 成功获取详情的商品数量
        """
        success_count = 0

        try:
            from app.config import config

            # 从配置获取并发数量和延迟时间
            auto_fetch_config = config.get('ITEM_DETAIL', {}).get('auto_fetch', {})
            max_concurrent = auto_fetch_config.get('max_concurrent', 3)
            retry_delay = auto_fetch_config.get('retry_delay', 0.5)

            # 限制并发数量，避免对API服务器造成压力
            semaphore = asyncio.Semaphore(max_concurrent)

            async def fetch_single_item_detail(item_info):
                async with semaphore:
                    try:
                        item_id = item_info['item_id']
                        item_title = item_info['item_title']

                        # 获取商品详情
                        item_detail_text = await self.fetch_item_detail_from_api(item_id)

                        if item_detail_text:
                            # 保存详情到数据库
                            success = await self.save_item_detail_only(item_id, item_detail_text)
                            if success:
                                logger.info(f"✅ 成功获取并保存商品详情: {item_id} - {item_title}")
                                return 1
                            else:
                                logger.warning(f"❌ 获取详情成功但保存失败: {item_id}")
                        else:
                            logger.warning(f"❌ 未能获取商品详情: {item_id} - {item_title}")

                        # 添加延迟，避免请求过于频繁
                        await asyncio.sleep(retry_delay)
                        return 0

                    except Exception as e:
                        logger.error(f"获取单个商品详情异常: {item_info.get('item_id', 'unknown')}, 错误: {self._safe_str(e)}")
                        return 0

            # 并发获取所有商品详情
            tasks = [fetch_single_item_detail(item_info) for item_info in items_need_detail]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 统计成功数量
            for result in results:
                if isinstance(result, int):
                    success_count += result
                elif isinstance(result, Exception):
                    logger.error(f"获取商品详情任务异常: {result}")

            return success_count

        except Exception as e:
            logger.error(f"批量获取商品详情异常: {self._safe_str(e)}")
            return success_count

    async def get_item_info(self, item_id, retry_count=0):
        """获取商品信息，自动处理token失效的情况"""
        if retry_count >= 4:  # 最多重试3次
            logger.error("获取商品信息失败，重试次数过多")
            return {"error": "获取商品信息失败，重试次数过多"}

        # 确保session已创建
        if not self.session:
            await self.create_session()

        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': str(int(time.time() * 1000)),
            'sign': '',
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idle.pc.detail',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.im.0.0',
        }

        data_val = '{"itemId":"' + item_id + '"}'
        data = {
            'data': data_val,
        }

        # 始终从最新的cookies中获取_m_h5_tk token（刷新后cookies会被更新）
        token = trans_cookies(self.cookies_str).get('_m_h5_tk', '').split('_')[0] if trans_cookies(self.cookies_str).get('_m_h5_tk') else ''

        if token:
            logger.info("获取商品详情，_m_h5_tk字段存在")
        else:
            logger.warning("cookies中没有找到_m_h5_tk token")

        from utils.xianyu_utils import generate_sign
        sign = generate_sign(params['t'], token, data_val)
        params['sign'] = sign

        try:
            async with self.session.post(
                'https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/',
                params=params,
                data=data
            ) as response:
                res_json = await response.json()

                # 检查并更新Cookie
                if 'set-cookie' in response.headers:
                    new_cookies = {}
                    for cookie in response.headers.getall('set-cookie', []):
                        if '=' in cookie:
                            name, value = cookie.split(';')[0].split('=', 1)
                            new_cookies[name.strip()] = value.strip()

                    # 更新cookies
                    if new_cookies:
                        self.cookies.update(new_cookies)
                        # 生成新的cookie字符串
                        self.cookies_str = '; '.join([f"{k}={v}" for k, v in self.cookies.items()])
                        # 更新数据库中的Cookie
                        await self.update_config_cookies()
                        logger.warning("已更新Cookie到数据库")

                logger.warning(f"商品信息获取成功: {res_json}")
                # 检查返回状态
                if isinstance(res_json, dict):
                    ret_value = res_json.get('ret', [])
                    # 检查ret是否包含成功信息
                    if not any('SUCCESS::调用成功' in ret for ret in ret_value):
                        logger.warning(f"商品信息API调用失败，错误信息: {ret_value}")

                        await asyncio.sleep(0.5)
                        return await self.get_item_info(item_id, retry_count + 1)
                    else:
                        logger.warning(f"商品信息获取成功: {item_id}")
                        return res_json
                else:
                    logger.error(f"商品信息API返回格式异常: {res_json}")
                    return await self.get_item_info(item_id, retry_count + 1)

        except Exception as e:
            logger.error(f"商品信息API请求异常: {self._safe_str(e)}")
            await asyncio.sleep(0.5)
            return await self.get_item_info(item_id, retry_count + 1)

    def extract_item_id_from_message(self, message):
        """从消息中提取商品ID的辅助方法"""
        try:
            # 方法1: 从message["1"]中提取（如果是字符串格式）
            message_1 = message.get('1')
            if isinstance(message_1, str):
                # 尝试从字符串中提取数字ID
                id_match = re.search(r'(\d{10,})', message_1)
                if id_match:
                    logger.info(f"从message[1]字符串中提取商品ID: {id_match.group(1)}")
                    return id_match.group(1)

            # 方法2: 从message["3"]中提取
            message_3 = message.get('3', {})
            if isinstance(message_3, dict):

                # 从extension中提取
                if 'extension' in message_3:
                    extension = message_3['extension']
                    if isinstance(extension, dict):
                        item_id = extension.get('itemId') or extension.get('item_id')
                        if item_id:
                            logger.info(f"从extension中提取商品ID: {item_id}")
                            return item_id

                # 从bizData中提取
                if 'bizData' in message_3:
                    biz_data = message_3['bizData']
                    if isinstance(biz_data, dict):
                        item_id = biz_data.get('itemId') or biz_data.get('item_id')
                        if item_id:
                            logger.info(f"从bizData中提取商品ID: {item_id}")
                            return item_id

                # 从其他可能的字段中提取
                for key, value in message_3.items():
                    if isinstance(value, dict):
                        item_id = value.get('itemId') or value.get('item_id')
                        if item_id:
                            logger.info(f"从{key}字段中提取商品ID: {item_id}")
                            return item_id

                # 从消息内容中提取数字ID
                content = message_3.get('content', '')
                if isinstance(content, str) and content:
                    id_match = re.search(r'(\d{10,})', content)
                    if id_match:
                        logger.info(f"【{self.cookie_id}】从消息内容中提取商品ID: {id_match.group(1)}")
                        return id_match.group(1)

            # 方法3: 遍历整个消息结构查找可能的商品ID
            def find_item_id_recursive(obj, path=""):
                if isinstance(obj, dict):
                    # 直接查找itemId字段
                    for key in ['itemId', 'item_id', 'id']:
                        if key in obj and isinstance(obj[key], (str, int)):
                            value = str(obj[key])
                            if len(value) >= 10 and value.isdigit():
                                logger.info(f"从{path}.{key}中提取商品ID: {value}")
                                return value

                    # 递归查找
                    for key, value in obj.items():
                        result = find_item_id_recursive(value, f"{path}.{key}" if path else key)
                        if result:
                            return result

                elif isinstance(obj, str):
                    # 从字符串中提取可能的商品ID
                    id_match = re.search(r'(\d{10,})', obj)
                    if id_match:
                        logger.info(f"从{path}字符串中提取商品ID: {id_match.group(1)}")
                        return id_match.group(1)

                return None

            result = find_item_id_recursive(message)
            if result:
                return result

            logger.warning("所有方法都未能提取到商品ID")
            return None

        except Exception as e:
            logger.error(f"提取商品ID失败: {self._safe_str(e)}")
            return None

    def debug_message_structure(self, message, context=""):
        """调试消息结构的辅助方法"""
        try:
            logger.warning(f"[{context}] 消息结构调试:")
            logger.warning(f"  消息类型: {type(message)}")

            if isinstance(message, dict):
                for key, value in message.items():
                    logger.warning(f"  键 '{key}': {type(value)} - {str(value)[:100]}...")

                    # 特别关注可能包含商品ID的字段
                    if key in ["1", "3"] and isinstance(value, dict):
                        logger.warning(f"    详细结构 '{key}':")
                        for sub_key, sub_value in value.items():
                            logger.warning(f"      '{sub_key}': {type(sub_value)} - {str(sub_value)[:50]}...")
            else:
                logger.warning(f"  消息内容: {str(message)[:200]}...")

        except Exception as e:
            logger.error(f"调试消息结构时发生错误: {self._safe_str(e)}")

    async def get_default_reply(self, send_user_name: str, send_user_id: str, send_message: str, chat_id: str, item_id: str = None) -> dict:
        """获取默认回复内容，支持指定商品回复、变量替换、只回复一次功能和图片发送
        
        Returns:
            dict: 包含 'text' (文字回复) 和 'image_url' (图片URL，可选) 的字典
                  或 None (无回复)
                  或 "EMPTY_REPLY" (空回复标记)
        """
        try:
            from app.db_manager import db_manager

            # 1. 优先检查指定商品回复
            if item_id:
                item_reply = db_manager.get_item_reply(self.cookie_id, item_id)
                if item_reply and item_reply.get('reply_content'):
                    reply_content = item_reply['reply_content']
                    logger.info(f"【{self.cookie_id}】使用指定商品回复: 商品ID={item_id}")

                    # 进行变量替换
                    try:
                        formatted_reply = reply_content.format(
                            send_user_name=send_user_name,
                            send_user_id=send_user_id,
                            send_message=send_message,
                            item_id=item_id
                        )
                        logger.info(f"【{self.cookie_id}】指定商品回复内容: {formatted_reply}")
                        return {'text': formatted_reply, 'image_url': None}
                    except Exception as format_error:
                        logger.error(f"指定商品回复变量替换失败: {self._safe_str(format_error)}")
                        # 如果变量替换失败，返回原始内容
                        return {'text': reply_content, 'image_url': None}
                else:
                    logger.warning(f"【{self.cookie_id}】商品ID {item_id} 没有配置指定回复，使用默认回复")

            # 2. 获取当前账号的默认回复设置
            default_reply_settings = db_manager.get_default_reply(self.cookie_id)

            if not default_reply_settings or not default_reply_settings.get('enabled', False):
                logger.warning(f"账号 {self.cookie_id} 未启用默认回复")
                return None

            # 检查"只回复一次"功能
            if default_reply_settings.get('reply_once', False) and chat_id:
                # 检查是否已经回复过这个chat_id
                if db_manager.has_default_reply_record(self.cookie_id, chat_id):
                    logger.info(f"【{self.cookie_id}】chat_id {chat_id} 已使用过默认回复，跳过（只回复一次）")
                    return None

            reply_content = default_reply_settings.get('reply_content', '')
            reply_image_url = default_reply_settings.get('reply_image_url', '')
            
            # 如果文字和图片都为空，返回空回复标记
            if (not reply_content or reply_content.strip() == '') and (not reply_image_url or reply_image_url.strip() == ''):
                logger.info(f"账号 {self.cookie_id} 默认回复内容和图片都为空，不进行回复")
                return "EMPTY_REPLY"  # 返回特殊标记表示不回复

            # 进行变量替换
            try:
                # 获取当前商品是否有设置自动回复
                item_replay = db_manager.get_item_replay(item_id)

                formatted_reply = reply_content.format(
                    send_user_name=send_user_name,
                    send_user_id=send_user_id,
                    send_message=send_message
                ) if reply_content else ''

                if item_replay:
                    formatted_reply = item_replay.get('reply_content', '')

                # 如果开启了"只回复一次"功能，记录这次回复
                if default_reply_settings.get('reply_once', False) and chat_id:
                    db_manager.add_default_reply_record(self.cookie_id, chat_id)
                    logger.info(f"【{self.cookie_id}】记录默认回复: chat_id={chat_id}")

                logger.info(f"【{self.cookie_id}】使用默认回复: 文字={formatted_reply}, 图片={reply_image_url}")
                return {'text': formatted_reply, 'image_url': reply_image_url if reply_image_url and reply_image_url.strip() else None}
            except Exception as format_error:
                logger.error(f"默认回复变量替换失败: {self._safe_str(format_error)}")
                # 如果变量替换失败，返回原始内容
                return {'text': reply_content, 'image_url': reply_image_url if reply_image_url and reply_image_url.strip() else None}

        except Exception as e:
            logger.error(f"获取默认回复失败: {self._safe_str(e)}")
            return None

    async def get_keyword_reply(self, send_user_name: str, send_user_id: str, send_message: str, item_id: str = None) -> str:
        """获取关键词匹配回复（支持商品ID优先匹配和图片类型）"""
        try:
            from app.db_manager import db_manager

            # 获取当前账号的关键词列表（包含类型信息）
            keywords = db_manager.get_keywords_with_type(self.cookie_id)

            if not keywords:
                logger.warning(f"账号 {self.cookie_id} 没有配置关键词")
                return None

            # 1. 如果有商品ID，优先匹配该商品ID对应的关键词
            if item_id:
                for keyword_data in keywords:
                    keyword = keyword_data['keyword']
                    reply = keyword_data['reply']
                    keyword_item_id = keyword_data['item_id']
                    keyword_type = keyword_data.get('type', 'text')
                    image_url = keyword_data.get('image_url')

                    if keyword_item_id == item_id and keyword.lower() in send_message.lower():
                        logger.info(f"商品ID关键词匹配成功: 商品{item_id} '{keyword}' (类型: {keyword_type})")

                        # 根据关键词类型处理
                        if keyword_type == 'image' and image_url:
                            # 图片类型关键词，发送图片
                            return await self._handle_image_keyword(keyword, image_url, send_user_name, send_user_id, send_message)
                        else:
                            # 文本类型关键词，检查回复内容是否为空
                            if not reply or (reply and reply.strip() == ''):
                                logger.info(f"商品ID关键词 '{keyword}' 回复内容为空，不进行回复")
                                return "EMPTY_REPLY"  # 返回特殊标记表示匹配到但不回复

                            # 进行变量替换
                            try:
                                formatted_reply = reply.format(
                                    send_user_name=send_user_name,
                                    send_user_id=send_user_id,
                                    send_message=send_message
                                )
                                logger.info(f"商品ID文本关键词回复: {formatted_reply}")
                                return formatted_reply
                            except Exception as format_error:
                                logger.error(f"关键词回复变量替换失败: {self._safe_str(format_error)}")
                                # 如果变量替换失败，返回原始内容
                                return reply

            # 2. 如果商品ID匹配失败或没有商品ID，匹配没有商品ID的通用关键词
            for keyword_data in keywords:
                keyword = keyword_data['keyword']
                reply = keyword_data['reply']
                keyword_item_id = keyword_data['item_id']
                keyword_type = keyword_data.get('type', 'text')
                image_url = keyword_data.get('image_url')

                if not keyword_item_id and keyword.lower() in send_message.lower():
                    logger.info(f"通用关键词匹配成功: '{keyword}' (类型: {keyword_type})")

                    # 根据关键词类型处理
                    if keyword_type == 'image' and image_url:
                        # 图片类型关键词，发送图片
                        return await self._handle_image_keyword(keyword, image_url, send_user_name, send_user_id, send_message)
                    else:
                        # 文本类型关键词，检查回复内容是否为空
                        if not reply or (reply and reply.strip() == ''):
                            logger.info(f"通用关键词 '{keyword}' 回复内容为空，不进行回复")
                            return "EMPTY_REPLY"  # 返回特殊标记表示匹配到但不回复

                        # 进行变量替换
                        try:
                            formatted_reply = reply.format(
                                send_user_name=send_user_name,
                                send_user_id=send_user_id,
                                send_message=send_message
                            )
                            logger.info(f"通用文本关键词回复: {formatted_reply}")
                            return formatted_reply
                        except Exception as format_error:
                            logger.error(f"关键词回复变量替换失败: {self._safe_str(format_error)}")
                            # 如果变量替换失败，返回原始内容
                            return reply

            logger.warning(f"未找到匹配的关键词: {send_message}")
            return None

        except Exception as e:
            logger.error(f"获取关键词回复失败: {self._safe_str(e)}")
            return None

    async def _handle_image_keyword(self, keyword: str, image_url: str, send_user_name: str, send_user_id: str, send_message: str) -> str:
        """处理图片类型关键词"""
        try:
            # 检查图片URL类型
            if self._is_cdn_url(image_url):
                # 已经是CDN链接，直接使用
                logger.info(f"使用已有的CDN图片链接: {image_url}")
                return f"__IMAGE_SEND__{image_url}"

            elif image_url.startswith('/static/uploads/') or image_url.startswith('static/uploads/'):
                # 本地图片，需要上传到闲鱼CDN
                local_image_path = image_url.replace('/static/uploads/', 'static/uploads/')
                if os.path.exists(local_image_path):
                    logger.info(f"准备上传本地图片到闲鱼CDN: {local_image_path}")

                    # 使用图片上传器上传到闲鱼CDN
                    from utils.image_uploader import ImageUploader
                    uploader = ImageUploader(self.cookies_str)

                    async with uploader:
                        cdn_url = await uploader.upload_image(local_image_path)
                        if cdn_url:
                            logger.info(f"图片上传成功，CDN URL: {cdn_url}")
                            # 更新数据库中的图片URL为CDN URL
                            await self._update_keyword_image_url(keyword, cdn_url)
                            image_url = cdn_url
                        else:
                            logger.error(f"图片上传失败: {local_image_path}")
                            logger.error(f"❌ Cookie可能已失效！请检查配置并更新Cookie")
                            return f"抱歉，图片发送失败（Cookie可能已失效，请检查日志）"
                else:
                    logger.error(f"本地图片文件不存在: {local_image_path}")
                    return f"抱歉，图片文件不存在。"

            else:
                # 其他类型的URL（可能是外部链接），直接使用
                logger.info(f"使用外部图片链接: {image_url}")

            # 发送图片（这里返回特殊标记，在调用处处理实际发送）
            return f"__IMAGE_SEND__{image_url}"

        except Exception as e:
            logger.error(f"处理图片关键词失败: {e}")
            return f"抱歉，图片发送失败: {str(e)}"

    def _is_cdn_url(self, url: str) -> bool:
        """检查URL是否是闲鱼CDN链接"""
        if not url:
            return False

        # 闲鱼CDN域名列表
        cdn_domains = [
            'gw.alicdn.com',
            'img.alicdn.com',
            'cloud.goofish.com',
            'goofish.com',
            'taobaocdn.com',
            'tbcdn.cn',
            'aliimg.com'
        ]

        # 检查是否包含CDN域名
        url_lower = url.lower()
        for domain in cdn_domains:
            if domain in url_lower:
                return True

        # 检查是否是HTTPS链接且包含图片特征
        if url_lower.startswith('https://') and any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            return True

        return False

    async def _get_image_size_from_url(self, image_url: str) -> tuple:
        """从URL获取图片尺寸
        
        Args:
            image_url: 图片URL
            
        Returns:
            (width, height) 元组，失败返回 (None, None)
        """
        import aiohttp
        from io import BytesIO
        
        try:
            logger.info(f"【{self.cookie_id}】开始从URL获取图片尺寸: {image_url[:80]}...")
            
            # 不接受AVIF格式（PIL默认不支持），让CDN返回WEBP/JPEG等格式
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/jpeg,image/png,image/gif,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': 'https://www.goofish.com/',
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        from PIL import Image
                        with Image.open(BytesIO(image_data)) as img:
                            width, height = img.size
                            logger.info(f"【{self.cookie_id}】解析图片尺寸成功: {width}x{height}")
                            return (width, height)
                    else:
                        logger.warning(f"【{self.cookie_id}】下载图片失败，HTTP状态码: {response.status}")
        except Exception as e:
            logger.warning(f"【{self.cookie_id}】从URL获取图片尺寸失败: {e}")
        
        return (None, None)

    async def _update_keyword_image_url(self, keyword: str, new_image_url: str):
        """更新关键词的图片URL"""
        try:
            from app.db_manager import db_manager
            success = db_manager.update_keyword_image_url(self.cookie_id, keyword, new_image_url)
            if success:
                logger.info(f"图片URL已更新: {keyword} -> {new_image_url}")
            else:
                logger.warning(f"图片URL更新失败: {keyword}")
        except Exception as e:
            logger.error(f"更新关键词图片URL失败: {e}")

    async def _update_card_image_url(self, card_id: int, new_image_url: str):
        """更新卡券的图片URL"""
        try:
            from app.db_manager import db_manager
            success = db_manager.update_card_image_url(card_id, new_image_url)
            if success:
                logger.info(f"卡券图片URL已更新: 卡券ID={card_id} -> {new_image_url}")
            else:
                logger.warning(f"卡券图片URL更新失败: 卡券ID={card_id}")
        except Exception as e:
            logger.error(f"更新卡券图片URL失败: {e}")

    async def _update_default_reply_image_url(self, new_image_url: str):
        """更新默认回复的图片URL为CDN URL"""
        try:
            from app.db_manager import db_manager
            success = db_manager.update_default_reply_image_url(self.cookie_id, new_image_url)
            if success:
                logger.info(f"【{self.cookie_id}】默认回复图片URL已更新: {new_image_url}")
            else:
                logger.warning(f"【{self.cookie_id}】默认回复图片URL更新失败")
        except Exception as e:
            logger.error(f"【{self.cookie_id}】更新默认回复图片URL失败: {e}")

    async def get_ai_reply(self, send_user_name: str, send_user_id: str, send_message: str, item_id: str, chat_id: str):
        """获取AI回复"""
        try:
            from app.ai_reply_engine import ai_reply_engine

            # 检查是否启用AI回复
            if not ai_reply_engine.is_ai_enabled(self.cookie_id):
                logger.warning(f"账号 {self.cookie_id} 未启用AI回复")
                return None

            # 从数据库获取商品信息
            from app.db_manager import db_manager
            item_info_raw = db_manager.get_item_info(self.cookie_id, item_id)

            if not item_info_raw:
                logger.warning(f"数据库中无商品信息: {item_id}")
                # 使用默认商品信息
                item_info = {
                    'title': '商品信息获取失败',
                    'price': 0,
                    'desc': '暂无商品描述'
                }
            else:
                # 解析数据库中的商品信息
                item_info = {
                    'title': item_info_raw.get('item_title', '未知商品'),
                    'price': self._parse_price(item_info_raw.get('item_price', '0')),
                    'desc': item_info_raw.get('item_detail', '暂无商品描述')
                }

            # 生成AI回复
            # 由于外部已实现防抖机制，跳过内部等待（skip_wait=True）
            reply = await ai_reply_engine.generate_reply_async(
                message=send_message,
                item_info=item_info,
                chat_id=chat_id,
                cookie_id=self.cookie_id,
                user_id=send_user_id,
                item_id=item_id,
                skip_wait=True  # 跳过内部等待，因为外部已实现防抖
            )

            if reply:
                logger.info(f"【{self.cookie_id}】AI回复生成成功，字符数={len(reply)}")
                return reply
            else:
                logger.warning(f"【{self.cookie_id}】AI回复未生成，将继续尝试默认回复")
                return None

        except Exception as e:
            logger.error(f"获取AI回复失败: {self._safe_str(e)}")
            return None

    def _parse_price(self, price_str: str) -> float:
        """解析价格字符串为数字"""
        try:
            if not price_str:
                return 0.0
            # 移除非数字字符，保留小数点
            price_clean = re.sub(r'[^\d.]', '', str(price_str))
            return float(price_clean) if price_clean else 0.0
        except:
            return 0.0

    async def send_system_notification(self, message: str) -> int:
        """把系统级消息推送到该账号绑定的全部通知渠道。

        与 :meth:`send_notification` 的区别是不依赖买家消息上下文，
        供发货超时告警这类主动通知使用。

        Returns:
            成功发送的渠道数。
        """
        if not message:
            return 0

        try:
            from app.db_manager import db_manager

            notifications = db_manager.get_account_notifications(self.cookie_id) or []
        except Exception as e:
            logger.error(f"📱 读取通知渠道失败: {self._safe_str(e)}")
            return 0

        sent = 0
        for notification in notifications:
            if not notification.get('enabled', True):
                continue

            channel_type = notification.get('channel_type')
            try:
                config_data = self._parse_notification_config(
                    notification.get('channel_config')
                )
                match channel_type:
                    case 'ding_talk' | 'dingtalk':
                        await self._send_dingtalk_notification(config_data, message)
                    case 'feishu' | 'lark':
                        await self._send_feishu_notification(config_data, message)
                    case 'bark':
                        await self._send_bark_notification(config_data, message)
                    case 'email':
                        await self._send_email_notification(config_data, message)
                    case 'webhook':
                        await self._send_webhook_notification(config_data, message)
                    case 'wechat':
                        await self._send_wechat_notification(config_data, message)
                    case 'telegram':
                        await self._send_telegram_notification(config_data, message)
                    case _:
                        logger.warning(f"📱 不支持的通知渠道类型: {channel_type}")
                        continue
                sent += 1
            except Exception as notify_error:
                logger.error(
                    f"📱 发送系统通知失败 ({notification.get('channel_name', 'Unknown')}): "
                    f"{self._safe_str(notify_error)}"
                )

        return sent

    async def send_notification(self, send_user_name: str, send_user_id: str, send_message: str, item_id: str = None, chat_id: str = None):
        """发送消息通知"""
        try:
            from app.db_manager import db_manager
            import hashlib

            # 过滤系统默认消息，不发送通知
            system_messages = [
                '发来一条消息',
                '发来一条新消息'
            ]

            if send_message in system_messages:
                logger.warning(f"📱 系统消息不发送通知: {send_message}")
                return

            # 生成通知的唯一标识（基于消息内容、chat_id、send_user_id）
            # 用于防重复发送
            notification_key = f"{chat_id or 'unknown'}_{send_user_id}_{send_message}"
            notification_hash = hashlib.md5(notification_key.encode('utf-8')).hexdigest()
            
            # 使用异步锁保护防重复检查，确保并发安全
            async with self.notification_lock:
                # 检查是否在冷却时间内已发送过相同的通知
                current_time = time.time()
                if notification_hash in self.last_notification_time:
                    time_since_last = current_time - self.last_notification_time[notification_hash]
                    if time_since_last < self.notification_cooldown:
                        remaining_seconds = int(self.notification_cooldown - time_since_last)
                        logger.warning(f"📱 通知在冷却期内（剩余 {remaining_seconds} 秒），跳过重复发送 - 账号: {self.cookie_id}, 买家: {send_user_name}, 消息: {send_message[:30]}...")
                        return
                
                # 更新通知发送时间
                self.last_notification_time[notification_hash] = current_time
                
                # 清理过期的通知记录（超过1小时的记录）
                expired_keys = [
                    key for key, timestamp in self.last_notification_time.items()
                    if current_time - timestamp > 3600  # 1小时
                ]
                for key in expired_keys:
                    del self.last_notification_time[key]

            logger.info(f"📱 开始发送消息通知 - 账号: {self.cookie_id}, 买家: {send_user_name}")

            # 获取当前账号的通知配置
            notifications = db_manager.get_account_notifications(self.cookie_id)

            if not notifications:
                logger.warning(f"📱 账号 {self.cookie_id} 未配置消息通知，跳过通知发送")
                return

            logger.info(f"📱 找到 {len(notifications)} 个通知渠道配置")

            # 构建通知消息
            notification_msg = f"🚨 接收消息通知\n\n" \
                             f"账号: {self.cookie_id}\n" \
                             f"买家: {send_user_name} (ID: {send_user_id})\n" \
                             f"商品ID: {item_id or '未知'}\n" \
                             f"聊天ID: {chat_id or '未知'}\n" \
                             f"消息内容: {send_message}\n" \
                             f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

            # 发送通知到各个渠道
            for i, notification in enumerate(notifications, 1):
                logger.info(f"📱 处理第 {i} 个通知渠道: {notification.get('channel_name', 'Unknown')}")

                if not notification.get('enabled', True):
                    logger.warning(f"📱 通知渠道 {notification.get('channel_name')} 已禁用，跳过")
                    continue

                channel_type = notification.get('channel_type')
                channel_config = notification.get('channel_config')

                logger.info(f"📱 渠道类型: {channel_type}")

                try:
                    # 解析配置数据
                    config_data = self._parse_notification_config(channel_config)
                    match channel_type:
                        case 'ding_talk' | 'dingtalk':
                            logger.info(f"📱 开始发送钉钉通知...")
                            await self._send_dingtalk_notification(config_data, notification_msg)
                        case 'feishu' | 'lark':
                            logger.info(f"📱 开始发送飞书通知...")
                            await self._send_feishu_notification(config_data, notification_msg)
                        case 'bark':
                            logger.info(f"📱 开始发送Bark通知...")
                            await self._send_bark_notification(config_data, notification_msg)
                        case 'email':
                            logger.info(f"📱 开始发送邮件通知...")
                            await self._send_email_notification(config_data, notification_msg)
                        case 'webhook':
                            logger.info(f"📱 开始发送Webhook通知...")
                            await self._send_webhook_notification(config_data, notification_msg)
                        case 'wechat':
                            logger.info(f"📱 开始发送微信通知...")
                            await self._send_wechat_notification(config_data, notification_msg)
                        case 'telegram':
                            logger.info(f"📱 开始发送Telegram通知...")
                            await self._send_telegram_notification(config_data, notification_msg)
                        case _:
                            logger.warning(f"📱 不支持的通知渠道类型: {channel_type}")

                except Exception as notify_error:
                    logger.error(f"📱 发送通知失败 ({notification.get('channel_name', 'Unknown')}): {self._safe_str(notify_error)}")
                    import traceback
                    logger.error(f"📱 详细错误信息: {traceback.format_exc()}")

        except Exception as e:
            logger.error(f"📱 处理消息通知失败: {self._safe_str(e)}")
            import traceback
            logger.error(f"📱 详细错误信息: {traceback.format_exc()}")

    def _parse_notification_config(self, config: str) -> dict:
        """解析通知配置数据"""
        try:
            import json
            # 尝试解析JSON格式的配置
            return json.loads(config)
        except (json.JSONDecodeError, TypeError):
            # 兼容旧格式（直接字符串）
            return {"config": config}

    async def _send_dingtalk_notification(self, config_data: dict, message: str):
        """发送钉钉通知"""
        try:
            import aiohttp
            import hmac
            import hashlib
            import base64
            import time

            # 解析配置
            webhook_url = config_data.get('webhook_url') or config_data.get('config', '')
            secret = config_data.get('secret', '')

            webhook_url = webhook_url.strip() if webhook_url else ''
            if not webhook_url:
                logger.warning("钉钉通知配置为空")
                return

            # 如果有加签密钥，生成签名
            if secret:
                timestamp = str(round(time.time() * 1000))
                secret_enc = secret.encode('utf-8')
                string_to_sign = f'{timestamp}\n{secret}'
                string_to_sign_enc = string_to_sign.encode('utf-8')
                hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
                sign = base64.b64encode(hmac_code).decode('utf-8')
                webhook_url += f'&timestamp={timestamp}&sign={sign}'

            data = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "闲鱼自动回复通知",
                    "text": message
                }
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=data, timeout=10) as response:
                    if response.status == 200:
                        logger.info(f"钉钉通知发送成功")
                    else:
                        logger.warning(f"钉钉通知发送失败: {response.status}")

        except Exception as e:
            logger.error(f"发送钉钉通知异常: {self._safe_str(e)}")

    async def _send_feishu_notification(self, config_data: dict, message: str):
        """发送飞书通知"""
        try:
            import aiohttp
            import json
            import hmac
            import hashlib
            import base64

            logger.info("📱 飞书通知 - 开始处理")

            # 解析配置
            webhook_url = config_data.get('webhook_url', '')
            secret = config_data.get('secret', '')

            logger.info(f"📱 飞书通知 - Webhook URL: {webhook_url[:50]}...")
            logger.info(f"📱 飞书通知 - 是否有签名密钥: {'是' if secret else '否'}")

            if not webhook_url:
                logger.warning("📱 飞书通知 - Webhook URL配置为空，无法发送通知")
                return

            # 如果有加签密钥，生成签名
            timestamp = str(int(time.time()))
            sign = ""

            if secret:
                string_to_sign = f'{timestamp}\n{secret}'
                hmac_code = hmac.new(
                    string_to_sign.encode('utf-8'),
                    ''.encode('utf-8'),
                    digestmod=hashlib.sha256
                ).digest()
                sign = base64.b64encode(hmac_code).decode('utf-8')
                logger.info(f"📱 飞书通知 - 已生成签名")

            # 构建请求数据
            data = {
                "msg_type": "text",
                "content": {
                    "text": message
                },
                "timestamp": timestamp
            }

            # 如果有签名，添加到请求数据中
            if sign:
                data["sign"] = sign

            logger.info(f"📱 飞书通知 - 请求数据构建完成")

            # 发送POST请求
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=data, timeout=10) as response:
                    response_text = await response.text()
                    logger.info(f"📱 飞书通知 - 响应状态: {response.status}")
                    logger.info(f"📱 飞书通知 - 响应内容: {response_text}")

                    if response.status == 200:
                        try:
                            response_json = json.loads(response_text)
                            if response_json.get('code') == 0:
                                logger.info(f"📱 飞书通知发送成功")
                            else:
                                logger.warning(f"📱 飞书通知发送失败: {response_json.get('msg', '未知错误')}")
                        except json.JSONDecodeError:
                            logger.info(f"📱 飞书通知发送成功（响应格式异常）")
                    else:
                        logger.warning(f"📱 飞书通知发送失败: HTTP {response.status}, 响应: {response_text}")

        except Exception as e:
            logger.error(f"📱 发送飞书通知异常: {self._safe_str(e)}")
            import traceback
            logger.error(f"📱 飞书通知异常详情: {traceback.format_exc()}")

    async def _send_bark_notification(self, config_data: dict, message: str):
        """发送Bark通知"""
        try:
            import aiohttp
            import json

            logger.info("📱 Bark通知 - 开始处理")

            # 解析配置
            server_url = config_data.get('server_url', 'https://api.day.app').rstrip('/')
            device_key = config_data.get('device_key', '')
            title = config_data.get('title', '闲鱼自动回复通知')
            sound = config_data.get('sound', 'default')
            icon = config_data.get('icon', '')
            group = config_data.get('group', 'xianyu')
            url = config_data.get('url', '')

            logger.info(f"📱 Bark通知 - 服务器: {server_url}")
            logger.info(f"📱 Bark通知 - 设备密钥: {'已配置' if device_key else '未设置'}")
            logger.info(f"📱 Bark通知 - 标题: {title}")

            if not device_key:
                logger.warning("📱 Bark通知 - 设备密钥配置为空，无法发送通知")
                return

            # 构建请求URL和数据
            # Bark支持两种方式：URL路径方式和POST JSON方式
            # 这里使用POST JSON方式，更灵活且支持更多参数

            api_url = f"{server_url}/push"

            # 构建请求数据
            data = {
                "device_key": device_key,
                "title": title,
                "body": message,
                "sound": sound,
                "group": group
            }

            # 可选参数
            if icon:
                data["icon"] = icon
            if url:
                data["url"] = url

            logger.info(f"📱 Bark通知 - API地址: {api_url}")
            logger.info(f"📱 Bark通知 - 请求数据构建完成")

            # 发送POST请求
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=data, timeout=10) as response:
                    response_text = await response.text()
                    logger.info(f"📱 Bark通知 - 响应状态: {response.status}")
                    logger.info(f"📱 Bark通知 - 响应内容: {response_text}")

                    if response.status == 200:
                        try:
                            response_json = json.loads(response_text)
                            if response_json.get('code') == 200:
                                logger.info(f"📱 Bark通知发送成功")
                            else:
                                logger.warning(f"📱 Bark通知发送失败: {response_json.get('message', '未知错误')}")
                        except json.JSONDecodeError:
                            # 某些Bark服务器可能返回纯文本
                            if 'success' in response_text.lower() or 'ok' in response_text.lower():
                                logger.info(f"📱 Bark通知发送成功")
                            else:
                                logger.warning(f"📱 Bark通知响应格式异常: {response_text}")
                    else:
                        logger.warning(f"📱 Bark通知发送失败: HTTP {response.status}, 响应: {response_text}")

        except Exception as e:
            logger.error(f"📱 发送Bark通知异常: {self._safe_str(e)}")
            import traceback
            logger.error(f"📱 Bark通知异常详情: {traceback.format_exc()}")

    async def _send_email_notification(self, config_data: dict, message: str, attachment_path: str = None):
        """发送邮件通知（支持附件）
        
        Args:
            config_data: 邮件配置
            message: 邮件正文
            attachment_path: 附件文件路径（可选）
        """
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            from email.mime.image import MIMEImage
            import os

            # 解析配置
            smtp_server = config_data.get('smtp_server', '')
            smtp_port = int(config_data.get('smtp_port', 587))
            email_user = config_data.get('email_user', '')
            email_password = config_data.get('email_password', '')
            recipient_email = config_data.get('recipient_email', '')
            smtp_use_tls = config_data.get('smtp_use_tls', smtp_port == 587)  # 修复：添加变量定义

            if not all([smtp_server, email_user, email_password, recipient_email]):
                logger.warning("邮件通知配置不完整")
                return

            # 创建邮件
            msg = MIMEMultipart()
            msg['From'] = email_user
            msg['To'] = recipient_email
            msg['Subject'] = "闲鱼自动回复通知"

            # 添加邮件正文
            msg.attach(MIMEText(message, 'plain', 'utf-8'))

            # 添加附件（如果有）
            if attachment_path and os.path.exists(attachment_path):
                try:
                    with open(attachment_path, 'rb') as f:
                        img_data = f.read()
                    
                    # 根据文件扩展名判断MIME类型
                    filename = os.path.basename(attachment_path)
                    if attachment_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                        img = MIMEImage(img_data)
                        img.add_header('Content-Disposition', 'attachment', filename=filename)
                        msg.attach(img)
                        logger.info(f"已添加图片附件: {filename}")
                    else:
                        from email.mime.application import MIMEApplication
                        attach = MIMEApplication(img_data)
                        attach.add_header('Content-Disposition', 'attachment', filename=filename)
                        msg.attach(attach)
                        logger.info(f"已添加附件: {filename}")
                except Exception as attach_error:
                    logger.error(f"添加邮件附件失败: {self._safe_str(attach_error)}")

            # 发送邮件
            server = None
            try:
                if smtp_port == 465:
                    # 使用SSL连接（端口465）
                    server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
                else:
                    # 使用普通连接，然后升级到TLS（端口587）
                    server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
                    if smtp_use_tls:
                        server.starttls()
                
                # 尝试登录
                try:
                    server.login(email_user, email_password)
                except smtplib.SMTPAuthenticationError as auth_error:
                    error_code = auth_error.smtp_code if hasattr(auth_error, 'smtp_code') else None
                    error_msg = str(auth_error)
                    
                    # 提供详细的错误提示
                    logger.error(f"邮件SMTP认证失败 (错误码: {error_code})")
                    logger.error(f"邮箱地址: {email_user}")
                    logger.error(f"SMTP服务器: {smtp_server}:{smtp_port}")
                    logger.error(f"错误详情: {error_msg}")
                    
                    # 根据常见错误提供解决建议
                    suggestions = []
                    if 'qq.com' in email_user.lower() or 'qq' in smtp_server.lower():
                        suggestions.append("QQ邮箱需要使用授权码而不是登录密码")
                        suggestions.append("请到QQ邮箱设置 -> 账户 -> 开启SMTP服务 -> 生成授权码")
                    elif 'gmail.com' in email_user.lower() or 'gmail' in smtp_server.lower():
                        suggestions.append("Gmail需要使用应用专用密码")
                        suggestions.append("请到Google账户 -> 安全性 -> 两步验证 -> 应用专用密码")
                        suggestions.append("或启用'允许不够安全的应用访问'（不推荐）")
                    elif '163.com' in email_user.lower() or '126.com' in email_user.lower() or 'yeah.net' in email_user.lower():
                        suggestions.append("网易邮箱需要使用授权码")
                        suggestions.append("请到邮箱设置 -> POP3/SMTP/IMAP -> 开启SMTP服务 -> 生成授权码")
                    else:
                        suggestions.append("请检查邮箱密码/授权码是否正确")
                        suggestions.append("某些邮箱服务商需要使用授权码而不是登录密码")
                        suggestions.append("请查看邮箱服务商的SMTP设置说明")
                    
                    if suggestions:
                        logger.error("解决建议:")
                        for i, suggestion in enumerate(suggestions, 1):
                            logger.error(f"  {i}. {suggestion}")
                    
                    raise  # 重新抛出异常
                
                server.send_message(msg)
                logger.info(f"邮件通知发送成功: {recipient_email}")

            finally:
                # 确保关闭连接
                if server:
                    try:
                        server.quit()
                    except:
                        try:
                            server.close()
                        except:
                            pass

        except smtplib.SMTPAuthenticationError:
            # 认证错误已在上面处理，这里不再重复记录
            pass
        except smtplib.SMTPException as smtp_error:
            logger.error(f"SMTP协议错误: {self._safe_str(smtp_error)}")
            logger.error(f"SMTP服务器: {smtp_server}:{smtp_port}")
            logger.error(f"请检查SMTP服务器地址和端口配置是否正确")
        except Exception as e:
            logger.error(f"发送邮件通知异常: {self._safe_str(e)}")
            import traceback
            logger.error(f"邮件发送详细错误: {traceback.format_exc()}")

    async def _send_webhook_notification(self, config_data: dict, message: str):
        """发送Webhook通知"""
        try:
            import aiohttp
            import json

            # 解析配置
            webhook_url = config_data.get('webhook_url', '')
            http_method = config_data.get('http_method', 'POST').upper()
            headers_str = config_data.get('headers', '{}')

            if not webhook_url:
                logger.warning("Webhook通知配置为空")
                return

            # 解析自定义请求头
            try:
                custom_headers = json.loads(headers_str) if headers_str else {}
            except json.JSONDecodeError:
                custom_headers = {}

            # 设置默认请求头
            headers = {'Content-Type': 'application/json'}
            headers.update(custom_headers)

            # 构建请求数据
            data = {
                'message': message,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'source': 'xianyu-auto-reply'
            }

            async with aiohttp.ClientSession() as session:
                if http_method == 'POST':
                    async with session.post(webhook_url, json=data, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            logger.info(f"Webhook通知发送成功")
                        else:
                            logger.warning(f"Webhook通知发送失败: {response.status}")
                elif http_method == 'PUT':
                    async with session.put(webhook_url, json=data, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            logger.info(f"Webhook通知发送成功")
                        else:
                            logger.warning(f"Webhook通知发送失败: {response.status}")
                else:
                    logger.warning(f"不支持的HTTP方法: {http_method}")

        except Exception as e:
            logger.error(f"发送Webhook通知异常: {self._safe_str(e)}")

    async def _send_wechat_notification(self, config_data: dict, message: str):
        """发送微信通知"""
        try:
            import aiohttp

            # 解析配置
            webhook_url = config_data.get('webhook_url', '')

            if not webhook_url:
                logger.warning("微信通知配置为空")
                return

            data = {
                "msgtype": "text",
                "text": {
                    "content": message
                }
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=data, timeout=10) as response:
                    if response.status == 200:
                        logger.info(f"微信通知发送成功")
                    else:
                        logger.warning(f"微信通知发送失败: {response.status}")

        except Exception as e:
            logger.error(f"发送微信通知异常: {self._safe_str(e)}")

    async def _send_telegram_notification(self, config_data: dict, message: str):
        """发送Telegram通知"""
        try:
            import aiohttp

            # 解析配置
            bot_token = config_data.get('bot_token', '')
            chat_id = config_data.get('chat_id', '')

            if not all([bot_token, chat_id]):
                logger.warning("Telegram通知配置不完整")
                return

            # 构建API URL
            api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

            data = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=data, timeout=10) as response:
                    if response.status == 200:
                        logger.info(f"Telegram通知发送成功")
                    else:
                        logger.warning(f"Telegram通知发送失败: {response.status}")

        except Exception as e:
            logger.error(f"发送Telegram通知异常: {self._safe_str(e)}")

    async def send_token_refresh_notification(self, error_message: str, notification_type: str = "token_refresh", chat_id: str = None, attachment_path: str = None, verification_url: str = None):
        """发送Token刷新异常通知（带防重复机制，支持附件）
        
        Args:
            error_message: 错误消息
            notification_type: 通知类型
            chat_id: 聊天ID（可选）
            attachment_path: 附件路径（可选，用于发送截图）
        """
        try:
            # 检查是否是正常的令牌过期，这种情况不需要发送通知
            if self._is_normal_token_expiry(error_message):
                logger.warning(f"检测到正常的令牌过期，跳过通知: {error_message}")
                return

            # 检查是否在冷却期内
            current_time = time.time()
            last_time = self.last_notification_time.get(notification_type, 0)

            # 为Token刷新异常通知使用特殊的3小时冷却时间
            # 基于错误消息内容判断是否为Token相关异常
            if self._is_token_related_error(error_message):
                cooldown_time = self.token_refresh_notification_cooldown
                cooldown_desc = "3小时"
            else:
                cooldown_time = self.notification_cooldown
                cooldown_desc = f"{self.notification_cooldown // 60}分钟"

            if current_time - last_time < cooldown_time:
                remaining_time = cooldown_time - (current_time - last_time)
                remaining_hours = int(remaining_time // 3600)
                remaining_minutes = int((remaining_time % 3600) // 60)
                remaining_seconds = int(remaining_time % 60)

                if remaining_hours > 0:
                    time_desc = f"{remaining_hours}小时{remaining_minutes}分钟"
                elif remaining_minutes > 0:
                    time_desc = f"{remaining_minutes}分钟{remaining_seconds}秒"
                else:
                    time_desc = f"{remaining_seconds}秒"

                logger.warning(f"Token刷新通知在冷却期内，跳过发送: {notification_type} (还需等待 {time_desc})")
                return

            from app.db_manager import db_manager

            # 获取当前账号的通知配置
            notifications = db_manager.get_account_notifications(self.cookie_id)

            if not notifications:
                logger.warning("未配置消息通知，跳过Token刷新通知")
                return

            # 构造通知消息
            # 判断异常信息中是否包含"滑块验证成功"
            if "滑块验证成功" in error_message:
                notification_msg = f"{error_message}\n\n" \
                                  f"账号: {self.cookie_id}\n" \
                                  f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            elif verification_url:
                # 如果有验证链接，添加到消息中
                notification_msg = f"{error_message}\n\n" \
                                  f"账号: {self.cookie_id}\n" \
                                  f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n" \
                                  f"验证链接: {verification_url}\n"
            else:
                notification_msg = f"Token刷新异常\n\n" \
                                  f"账号ID: {self.cookie_id}\n" \
                                  f"异常时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}\n" \
                                  f"异常信息: {error_message}\n\n" \
                                  f"请检查账号Cookie是否过期，如有需要请及时更新Cookie配置。\n"

            logger.info(f"准备发送Token刷新异常通知: {self.cookie_id}")

            # 发送通知到各个渠道
            notification_sent = False
            for notification in notifications:
                if not notification.get('enabled', True):
                    continue

                channel_type = notification.get('channel_type')
                channel_config = notification.get('channel_config')

                try:
                    # 解析配置数据
                    config_data = self._parse_notification_config(channel_config)

                    match channel_type:
                        case 'ding_talk' | 'dingtalk':
                            await self._send_dingtalk_notification(config_data, notification_msg)
                            notification_sent = True
                        case 'feishu' | 'lark':
                            await self._send_feishu_notification(config_data, notification_msg)
                            notification_sent = True
                        case 'bark':
                            await self._send_bark_notification(config_data, notification_msg)
                            notification_sent = True
                        case 'email':
                            # 邮件支持附件
                            await self._send_email_notification(config_data, notification_msg, attachment_path)
                            notification_sent = True
                        case 'webhook':
                            await self._send_webhook_notification(config_data, notification_msg)
                            notification_sent = True
                        case 'wechat':
                            await self._send_wechat_notification(config_data, notification_msg)
                            notification_sent = True
                        case 'telegram':
                            await self._send_telegram_notification(config_data, notification_msg)
                            notification_sent = True
                        case _:
                            logger.warning(f"不支持的通知渠道类型: {channel_type}")

                except Exception as notify_error:
                    logger.error(f"发送Token刷新通知失败 ({notification.get('channel_name', 'Unknown')}): {self._safe_str(notify_error)}")

            # 如果成功发送了通知，更新最后发送时间
            if notification_sent:
                self.last_notification_time[notification_type] = current_time

                # 根据错误消息内容使用不同的冷却时间
                if self._is_token_related_error(error_message):
                    next_send_time = current_time + self.token_refresh_notification_cooldown
                    cooldown_desc = "3小时"
                else:
                    next_send_time = current_time + self.notification_cooldown
                    cooldown_desc = f"{self.notification_cooldown // 60}分钟"

                next_send_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(next_send_time))
                logger.info(f"Token刷新通知已发送，下次可发送时间: {next_send_time_str} (冷却时间: {cooldown_desc})")

        except Exception as e:
            logger.error(f"处理Token刷新通知失败: {self._safe_str(e)}")

    def _is_normal_token_expiry(self, error_message: str) -> bool:
        """检查是否是正常的令牌过期或其他不需要通知的情况"""
        # 不需要发送通知的关键词
        no_notification_keywords = [
            # 正常的令牌过期
            'FAIL_SYS_TOKEN_EXOIRED::令牌过期',
            'FAIL_SYS_TOKEN_EXPIRED::令牌过期',
            'FAIL_SYS_TOKEN_EXOIRED',
            'FAIL_SYS_TOKEN_EXPIRED',
            '令牌过期',
            # Session过期（正常情况）
            'FAIL_SYS_SESSION_EXPIRED::Session过期',
            'FAIL_SYS_SESSION_EXPIRED',
            'Session过期',
            # Token定时刷新失败（会自动重试）
            'Token定时刷新失败，将自动重试',
            'Token定时刷新失败'
        ]

        # 检查错误消息是否包含不需要通知的关键词
        for keyword in no_notification_keywords:
            if keyword in error_message:
                return True

        return False

    def _is_token_related_error(self, error_message: str) -> bool:
        """检查是否是Token相关的错误，需要使用3小时冷却时间"""
        # Token相关错误的关键词
        token_error_keywords = [
            # Token刷新失败相关
            'Token刷新失败',
            'Token刷新异常',
            'token刷新失败',
            'token刷新异常',
            'TOKEN刷新失败',
            'TOKEN刷新异常',
            # 具体的Token错误信息
            'FAIL_SYS_USER_VALIDATE',
            'RGV587_ERROR',
            '哎哟喂,被挤爆啦',
            '请稍后重试',
            'punish?x5secdata',
            'captcha',
            # Token获取失败
            '无法获取有效token',
            '无法获取有效Token',
            'Token获取失败',
            'token获取失败',
            'TOKEN获取失败',
            # Token定时刷新失败
            'Token定时刷新失败',
            'token定时刷新失败',
            'TOKEN定时刷新失败',
            # 初始化Token失败
            '初始化时无法获取有效Token',
            '初始化时无法获取有效token',
            # 其他Token相关错误
            'accessToken',
            'access_token',
            '_m_h5_tk',
            'mtop.taobao.idlemessage.pc.login.token'
        ]

        # 检查错误消息是否包含Token相关的关键词
        error_message_lower = error_message.lower()
        for keyword in token_error_keywords:
            if keyword.lower() in error_message_lower:
                return True

        return False

    async def send_delivery_failure_notification(self, send_user_name: str, send_user_id: str, item_id: str, error_message: str, chat_id: str = None):
        """发送自动发货失败通知"""
        try:
            from app.db_manager import db_manager

            # 获取当前账号的通知配置
            notifications = db_manager.get_account_notifications(self.cookie_id)

            if not notifications:
                logger.warning("未配置消息通知，跳过自动发货通知")
                return

            # 构造通知消息
            notification_message = f"🚨 自动发货通知\n\n" \
                                 f"账号: {self.cookie_id}\n" \
                                 f"买家: {send_user_name} (ID: {send_user_id})\n" \
                                 f"商品ID: {item_id}\n" \
                                 f"聊天ID: {chat_id or '未知'}\n" \
                                 f"结果: {error_message}\n" \
                                 f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n" \
                                 f"请及时处理！"

            # 发送通知到所有已启用的通知渠道
            for notification in notifications:
                if notification.get('enabled', False):
                    channel_type = notification.get('channel_type', 'qq')
                    channel_config = notification.get('channel_config', '')

                    try:
                        # 解析配置数据
                        config_data = self._parse_notification_config(channel_config)

                        match channel_type:
                            case 'ding_talk' | 'dingtalk':
                                await self._send_dingtalk_notification(config_data, notification_message)
                                logger.info(f"已发送自动发货通知到钉钉")
                            case 'email':
                                await self._send_email_notification(config_data, notification_message)
                                logger.info(f"已发送自动发货通知到邮箱")
                            case 'webhook':
                                await self._send_webhook_notification(config_data, notification_message)
                                logger.info(f"已发送自动发货通知到Webhook")
                            case 'wechat':
                                await self._send_wechat_notification(config_data, notification_message)
                                logger.info(f"已发送自动发货通知到微信")
                            case 'telegram':
                                await self._send_telegram_notification(config_data, notification_message)
                                logger.info(f"已发送自动发货通知到Telegram")
                            case 'bark':
                                await self._send_bark_notification(config_data, notification_message)
                                logger.info(f"已发送自动发货通知到Bark")
                            case 'feishu' | 'lark':
                                await self._send_feishu_notification(config_data, notification_message)
                                logger.info(f"已发送自动发货通知到飞书")
                            case _:
                                logger.warning(f"不支持的通知渠道类型: {channel_type}")

                    except Exception as notify_error:
                        logger.error(f"发送自动发货通知失败: {self._safe_str(notify_error)}")

        except Exception as e:
            logger.error(f"发送自动发货通知异常: {self._safe_str(e)}")

    async def auto_confirm(self, order_id, item_id=None, retry_count=0):
        """自动确认发货 - 使用加密模块，不包含延时处理（延时已在_auto_delivery中处理）"""
        temp_session = None
        try:
            logger.warning(f"【{self.cookie_id}】开始确认发货，订单ID: {order_id}")

            # 导入解密后的确认发货模块
            from app.secure_confirm import SecureConfirm

            # self.session 是账号监听循环里创建的，绑定着那个事件循环。
            # 后台「完整发货」由 FastAPI 的循环发起，跨循环复用会抛
            # "Timeout context manager should be used inside a task"，
            # 表现为卡券已发出但闲鱼订单状态没变。
            # 因此这里检测循环归属，不一致时用当前循环临时建一个 session。
            session = self.session
            running_loop = asyncio.get_running_loop()
            session_loop = getattr(self.session, '_loop', None) if self.session else None
            if self.session is None or (session_loop is not None and session_loop is not running_loop):
                headers = DEFAULT_HEADERS.copy()
                headers['cookie'] = self.cookies_str
                temp_session = aiohttp.ClientSession(
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                )
                session = temp_session
                logger.warning(
                    f"【{self.cookie_id}】确认发货跨事件循环，已改用临时 session"
                )

            # 创建确认实例，传入主界面类实例
            secure_confirm = SecureConfirm(session, self.cookies_str, self.cookie_id, self)

            # 传递必要的属性
            secure_confirm.current_token = self.current_token
            secure_confirm.last_token_refresh_time = self.last_token_refresh_time
            secure_confirm.token_refresh_interval = self.token_refresh_interval

            # 调用确认方法，传入item_id用于token刷新
            result = await secure_confirm.auto_confirm(order_id, item_id, retry_count)

            # 同步更新后的cookies和token
            if secure_confirm.cookies_str != self.cookies_str:
                self.cookies_str = secure_confirm.cookies_str
                self.cookies = secure_confirm.cookies
                logger.warning(f"【{self.cookie_id}】已同步确认发货模块更新的cookies")

            if secure_confirm.current_token != self.current_token:
                self.current_token = secure_confirm.current_token
                self.last_token_refresh_time = secure_confirm.last_token_refresh_time
                logger.warning(f"【{self.cookie_id}】已同步确认发货模块更新的token")

            return result

        except Exception as e:
            logger.error(f"【{self.cookie_id}】加密确认模块调用失败: {self._safe_str(e)}")
            return {"error": f"加密确认模块调用失败: {self._safe_str(e)}", "order_id": order_id}
        finally:
            if temp_session is not None:
                try:
                    await temp_session.close()
                except Exception:
                    pass

    async def auto_freeshipping(self, order_id, item_id, buyer_id, retry_count=0):
        """自动免拼发货 - 使用解密模块"""
        try:
            logger.warning(f"【{self.cookie_id}】开始免拼发货，订单ID: {order_id}")

            # 导入解密后的免拼发货模块
            from app.secure_freeshipping import SecureFreeshipping

            # 创建免拼发货实例
            secure_freeshipping = SecureFreeshipping(self.session, self.cookies_str, self.cookie_id)

            # 传递必要的属性
            secure_freeshipping.current_token = self.current_token
            secure_freeshipping.last_token_refresh_time = self.last_token_refresh_time
            secure_freeshipping.token_refresh_interval = self.token_refresh_interval

            # 调用免拼发货方法
            return await secure_freeshipping.auto_freeshipping(order_id, item_id, buyer_id, retry_count)

        except Exception as e:
            logger.error(f"【{self.cookie_id}】免拼发货模块调用失败: {self._safe_str(e)}")
            return {"error": f"免拼发货模块调用失败: {self._safe_str(e)}", "order_id": order_id}

    async def fetch_order_detail_info(self, order_id: str, item_id: str = None, buyer_id: str = None, debug_headless: bool = None):
        """获取订单详情信息（使用独立的锁机制，不受延迟锁影响）"""
        # 使用独立的订单详情锁，不与自动发货锁冲突
        order_detail_lock = self._order_detail_locks[order_id]

        # 记录订单详情锁的使用时间
        self._order_detail_lock_times[order_id] = time.time()

        async with order_detail_lock:
            logger.info(f"🔍 【{self.cookie_id}】获取订单详情锁 {order_id}，开始处理...")
            
            try:
                logger.info(f"【{self.cookie_id}】开始获取订单详情: {order_id}")

                # 导入订单详情获取器
                from utils.order_detail_fetcher import fetch_order_detail_simple
                from app.db_manager import db_manager

                # 获取当前账号的cookie字符串
                cookie_string = self.cookies_str
                logger.warning(f"【{self.cookie_id}】使用Cookie长度: {len(cookie_string) if cookie_string else 0}")

                # 优先走卖家端接口直连：一次两个 HTTP 请求即可拿到成交额、规格和
                # 收货信息，无需启动浏览器。缺规格时说明接口没覆盖，再回退抓页面。
                result = None
                try:
                    from utils.seller_order_sync import fetch_order_detail_direct

                    direct = await fetch_order_detail_direct(
                        self.cookie_id, cookie_string, order_id
                    )
                    if direct and direct.get('spec_value'):
                        result = direct
                        logger.info(f"【{self.cookie_id}】订单详情已通过卖家端接口获取: {order_id}")
                    elif direct:
                        logger.info(
                            f"【{self.cookie_id}】卖家端接口未返回规格，回退浏览器抓取: {order_id}"
                        )
                except Exception as exc:
                    logger.warning(
                        f"【{self.cookie_id}】卖家端接口获取订单详情失败，回退浏览器: "
                        f"{self._safe_str(exc)}"
                    )

                if not result:
                    # 确定是否使用有头模式（调试用）
                    headless_mode = True if debug_headless is None else debug_headless
                    if not headless_mode:
                        logger.info(f"【{self.cookie_id}】🖥️ 启用有头模式进行调试")

                    # 异步获取订单详情（使用当前账号的cookie）
                    result = await fetch_order_detail_simple(order_id, cookie_string, headless=headless_mode)

                if result:
                    logger.info(f"【{self.cookie_id}】订单详情获取成功: {order_id}")
                    logger.info(f"【{self.cookie_id}】页面标题: {result.get('title', '未知')}")

                    # 获取解析后的规格信息
                    spec_name = result.get('spec_name', '')
                    spec_value = result.get('spec_value', '')
                    quantity = result.get('quantity', '')
                    amount = result.get('amount', '')

                    # 获取订单时间和收货人信息
                    order_time = result.get('order_time', None)
                    receiver_name = result.get('receiver_name', None)
                    receiver_phone = result.get('receiver_phone', None)
                    receiver_address = result.get('receiver_address', None)

                    if spec_name and spec_value:
                        logger.info(f"【{self.cookie_id}】📋 规格名称: {spec_name}")
                        logger.info(f"【{self.cookie_id}】📝 规格值: {spec_value}")
                        print(f"🛍️ 【{self.cookie_id}】订单 {order_id} 规格信息: {spec_name} -> {spec_value}")
                    else:
                        logger.warning(f"【{self.cookie_id}】未获取到有效的规格信息")
                        print(f"⚠️ 【{self.cookie_id}】订单 {order_id} 规格信息获取失败")

                    # 记录订单时间和收货人信息
                    if order_time:
                        logger.info(f"【{self.cookie_id}】⏰ 订单时间: {order_time}")
                    if receiver_name:
                        logger.info(f"【{self.cookie_id}】👤 收货人: {receiver_name}")
                    if receiver_phone:
                        logger.info(f"【{self.cookie_id}】📱 手机号: {receiver_phone}")
                    if receiver_address:
                        logger.info(f"【{self.cookie_id}】📍 收货地址: {receiver_address}")

                    # 插入或更新订单信息到数据库
                    try:
                        # 检查cookie_id是否在cookies表中存在
                        cookie_info = db_manager.get_cookie_by_id(self.cookie_id)
                        if not cookie_info:
                            logger.warning(f"Cookie ID {self.cookie_id} 不存在于cookies表中，丢弃订单 {order_id}")
                        else:
                            # 先保存订单基本信息（包含时间和收货人信息）
                            success = db_manager.insert_or_update_order(
                                order_id=order_id,
                                item_id=item_id,
                                buyer_id=buyer_id,
                                spec_name=spec_name,
                                spec_value=spec_value,
                                quantity=quantity,
                                amount=amount,
                                order_status=result.get('order_status'),  # 添加订单状态
                                cookie_id=self.cookie_id,
                                created_at=order_time,
                                receiver_name=receiver_name,
                                receiver_phone=receiver_phone,
                                receiver_address=receiver_address,
                                # 卖家端接口返回的成交明细，浏览器抓取时这些字段为空
                                buy_num=result.get('buy_num'),
                                auction_price=result.get('auction_price') or None,
                                confirm_fee=result.get('confirm_fee') or None,
                                refund_fee=result.get('refund_fee') or None,
                                post_fee=result.get('post_fee') or None
                            )
                            
                            # 使用订单状态处理器设置状态
                            logger.info(f"【{self.cookie_id}】检查订单状态处理器调用条件: success={success}, handler_exists={self.order_status_handler is not None}")
                            if success and self.order_status_handler:
                                logger.info(f"【{self.cookie_id}】准备调用订单状态处理器.handle_order_detail_fetched_status: {order_id}")
                                try:
                                    handler_result = self.order_status_handler.handle_order_detail_fetched_status(
                                        order_id=order_id,
                                        cookie_id=self.cookie_id,
                                        context="订单详情已拉取"
                                    )
                                    logger.info(f"【{self.cookie_id}】订单状态处理器.handle_order_detail_fetched_status返回结果: {handler_result}")
                                    
                                    # 处理待处理队列
                                    logger.info(f"【{self.cookie_id}】准备调用订单状态处理器.on_order_details_fetched: {order_id}")
                                    self.order_status_handler.on_order_details_fetched(order_id)
                                    logger.info(f"【{self.cookie_id}】订单状态处理器.on_order_details_fetched调用成功: {order_id}")
                                except Exception as e:
                                    logger.error(f"【{self.cookie_id}】订单状态处理器调用失败: {self._safe_str(e)}")
                                    import traceback
                                    logger.error(f"【{self.cookie_id}】详细错误信息: {traceback.format_exc()}")
                            else:
                                logger.warning(f"【{self.cookie_id}】订单状态处理器调用条件不满足: success={success}, handler_exists={self.order_status_handler is not None}")

                            if success:
                                logger.info(f"【{self.cookie_id}】订单信息已保存到数据库: {order_id}")
                                print(f"💾 【{self.cookie_id}】订单 {order_id} 信息已保存到数据库")
                            else:
                                logger.warning(f"【{self.cookie_id}】订单信息保存失败: {order_id}")

                    except Exception as db_e:
                        logger.error(f"【{self.cookie_id}】保存订单信息到数据库失败: {self._safe_str(db_e)}")

                    return result
                else:
                    logger.warning(f"【{self.cookie_id}】订单详情获取失败: {order_id}")
                    return None

            except Exception as e:
                logger.error(f"【{self.cookie_id}】获取订单详情异常: {self._safe_str(e)}")
                return None

    async def _auto_delivery(
        self,
        item_id: str,
        item_title: str = None,
        order_id: str = None,
        send_user_id: str = None,
        *,
        order_detail: dict = None,
        delivery_context: dict = None,
        requested_item_quantity: int = 1,
    ):
        """匹配并取得发货内容；批量库存会在首次调用时按整单需求原子扣减。"""
        try:
            from app.db_manager import db_manager

            logger.info(f"开始自动发货检查: 商品ID={item_id}")

            # 获取商品详细信息
            item_info = None
            search_text = item_title  # 默认使用传入的标题

            if item_id and item_id != "未知商品":
                # 直接从数据库获取商品信息（发货时不再调用API）
                try:
                    logger.info(f"从数据库获取商品信息: {item_id}")
                    db_item_info = db_manager.get_item_info(self.cookie_id, item_id)
                    if db_item_info:
                        # 拼接商品标题和详情作为搜索文本
                        item_title_db = db_item_info.get('item_title', '') or ''
                        item_detail_db = db_item_info.get('item_detail', '') or ''

                        # 如果数据库中没有详情，尝试自动获取
                        if not item_detail_db.strip():
                            from app.config import config
                            auto_fetch_config = config.get('ITEM_DETAIL', {}).get('auto_fetch', {})

                            if auto_fetch_config.get('enabled', True):
                                logger.info(f"数据库中商品详情为空，尝试自动获取: {item_id}")
                                try:
                                    fetched_detail = await self.fetch_item_detail_from_api(item_id)
                                    if fetched_detail:
                                        # 保存获取到的详情
                                        await self.save_item_detail_only(item_id, fetched_detail)
                                        item_detail_db = fetched_detail
                                        logger.info(f"成功获取并保存商品详情: {item_id}")
                                    else:
                                        logger.warning(f"未能获取到商品详情: {item_id}")
                                except Exception as api_e:
                                    logger.warning(f"获取商品详情失败: {item_id}, 错误: {self._safe_str(api_e)}")
                            else:
                                logger.warning(f"自动获取商品详情功能已禁用，跳过: {item_id}")

                        # 组合搜索文本：商品标题 + 商品详情
                        search_parts = []
                        if item_title_db.strip():
                            search_parts.append(item_title_db.strip())
                        if item_detail_db.strip():
                            search_parts.append(item_detail_db.strip())
                        if item_id and item_id != "未知商品":
                            search_parts.append(str(item_id).strip())

                        if search_parts:
                            search_text = ' '.join(search_parts)
                            logger.info(f"使用数据库商品标题+详情+商品ID作为搜索文本: 标题='{item_title_db}', 详情长度={len(item_detail_db)}")
                            logger.warning(f"完整搜索文本: {search_text[:200]}...")
                        else:
                            logger.warning(f"数据库中商品标题和详情都为空: {item_id}")
                            search_text = item_title or item_id
                    else:
                        logger.warning(f"数据库中未找到商品信息: {item_id}")
                        search_text = item_title or item_id

                except Exception as db_e:
                    logger.warning(f"从数据库获取商品信息失败: {self._safe_str(db_e)}")
                    search_text = item_title or item_id

            if not search_text:
                search_text = item_id or "未知商品"

            logger.info(f"使用搜索文本匹配发货规则: {search_text[:100]}...")

            spec_name = None
            spec_value = None
            spec_text = ""
            spec_payload = {}
            platform_sku_id = ""
            rule = delivery_context.get("resolved_rule") if delivery_context else None

            if rule:
                spec_name = delivery_context.get("spec_name")
                spec_value = delivery_context.get("spec_value")
                spec_text = delivery_context.get("spec_text") or ""
                spec_payload = delivery_context.get("spec_payload") or {}
                platform_sku_id = delivery_context.get("platform_sku_id") or ""
            else:
                delivery_config = db_manager.get_item_delivery_config(
                    self.cookie_id,
                    item_id,
                )
                if delivery_config:
                    if delivery_config.get("is_multi_spec"):
                        logger.info(f"检测到新版多规格商品配置，解析订单规格: {order_id}")
                        try:
                            if order_detail is None and order_id:
                                order_detail = await self.fetch_order_detail_info(
                                    order_id,
                                    item_id,
                                    send_user_id,
                                )
                        except Exception as e:
                            logger.error(
                                f"获取订单规格信息失败: {self._safe_str(e)}，"
                                "为避免错发已停止自动发货"
                            )
                            return None

                        if isinstance(order_detail, dict):
                            sku_info = order_detail.get("sku_info") or {}
                            spec_payload = (
                                order_detail.get("spec_payload")
                                or sku_info.get("spec_payload")
                                or {}
                            )
                            spec_text = (
                                order_detail.get("spec_text")
                                or sku_info.get("spec_text")
                                or combine_legacy_specification(
                                    order_detail.get("spec_name"),
                                    order_detail.get("spec_value"),
                                )
                            )
                            platform_sku_id = str(
                                order_detail.get("platform_sku_id")
                                or sku_info.get("platform_sku_id")
                                or ""
                            ).strip()
                            spec_name = order_detail.get("spec_name") or sku_info.get("spec_name")
                            spec_value = order_detail.get("spec_value") or sku_info.get("spec_value")

                    rule = db_manager.resolve_item_delivery_binding(
                        self.cookie_id,
                        item_id,
                        spec_text=spec_text,
                        spec_payload=spec_payload,
                        platform_sku_id=platform_sku_id,
                    )
                    if not rule.get("matched"):
                        reason_messages = {
                            "config_disabled": "商品自动发货已暂停",
                            "missing_specification": "订单未获取到规格",
                            "unknown_specification": "订单规格未绑定库存",
                            "conflicting_specification": "规格配置冲突",
                            "variant_disabled": "对应商品规格已停用",
                            "binding_disabled": "对应规格的发货绑定已停用",
                            "card_disabled": "对应规格绑定的卡密已停用",
                        }
                        reason = rule.get("reason") or "unknown"
                        logger.warning(
                            f"❌ 新版商品发货配置未通过: 商品={item_id}, "
                            f"原因={reason_messages.get(reason, reason)}, "
                            f"规格={spec_text or spec_payload or '空'}。"
                            "不会回退到普通卡密。"
                        )
                        return None
                    logger.info(
                        f"✅ 精确匹配商品规格库存: "
                        f"{rule.get('variant_name')} -> {rule.get('card_name')}"
                    )
                else:
                    # 仅未迁移的商品兼容旧发货规则；存在新版配置时禁止回退。
                    is_multi_spec = db_manager.get_item_multi_spec_status(
                        self.cookie_id,
                        item_id,
                    )
                    if is_multi_spec and order_id:
                        logger.info(f"检测到旧版多规格商品，获取订单规格信息: {order_id}")
                        try:
                            if order_detail is None:
                                order_detail = await self.fetch_order_detail_info(
                                    order_id,
                                    item_id,
                                    send_user_id,
                                )
                            if order_detail and isinstance(order_detail, dict):
                                spec_name = order_detail.get("spec_name", "")
                                spec_value = order_detail.get("spec_value", "")
                            else:
                                logger.warning("旧版多规格订单详情获取失败，停止自动发货")
                                return None
                        except Exception as e:
                            logger.error(
                                f"获取旧版订单规格失败: {self._safe_str(e)}，停止自动发货"
                            )
                            return None

                    if is_multi_spec and not (spec_name and spec_value):
                        # 区分两种失败：页面没渲染出来（技术故障，可重试）
                        # 与订单确实没有规格（配置问题）。原来一律静默跳过，
                        # 加上通知没配置，卖家对发货失败完全无感知。
                        page_empty = bool(
                            isinstance(order_detail, dict) and order_detail.get('page_empty')
                        )
                        if page_empty:
                            reason = (
                                f"订单详情页未渲染（DOM 节点 "
                                f"{order_detail.get('dom_node_count')} 个），未能读取规格"
                            )
                        else:
                            reason = "订单详情中没有规格信息"
                        logger.error(f"❌ 旧版多规格商品无法发货：{reason}，订单 {order_id}")
                        try:
                            await self.send_delivery_failure_notification(
                                send_user_name=str(send_user_id or '买家'),
                                send_user_id=str(send_user_id or ''),
                                item_id=str(item_id or ''),
                                error_message=f"订单 {order_id}：{reason}",
                            )
                        except Exception as notify_err:
                            logger.debug(f"发送发货失败通知出错: {self._safe_str(notify_err)}")
                        return None

                    delivery_rules = db_manager.get_delivery_rules_for_item(
                        search_text,
                        self.cookie_id,
                        item_id,
                        spec_name=spec_name if is_multi_spec else None,
                        spec_value=spec_value if is_multi_spec else None,
                    )
                    if not delivery_rules:
                        logger.warning(f"❌ 商品未找到匹配的发货规则，跳过自动发货: {item_id}")
                        return None
                    if len(delivery_rules) > 1:
                        rule_names = [
                            (
                                f"{candidate['card_name']}"
                                f"({candidate.get('spec_name', '')}:"
                                f"{candidate.get('spec_value', '')})"
                            )
                            if candidate.get("is_multi_spec")
                            else candidate["card_name"]
                            for candidate in delivery_rules
                        ]
                        logger.warning(
                            f"❌ 匹配到多个旧版发货规则({len(delivery_rules)}个)，"
                            f"无法确定使用哪个: {', '.join(rule_names)}"
                        )
                        return None
                    rule = delivery_rules[0]
                    logger.info(
                        f"✅ 唯一匹配旧版发货规则: "
                        f"{rule['keyword']} -> {rule['card_name']} ({rule['card_type']})"
                    )

                if delivery_context is not None:
                    delivery_context.update({
                        "resolved_rule": rule,
                        "delivery_count": max(1, int(rule.get("delivery_count") or 1)),
                        "spec_name": spec_name,
                        "spec_value": spec_value,
                        "spec_text": spec_text,
                        "spec_payload": spec_payload,
                        "platform_sku_id": platform_sku_id,
                    })

            # 保存商品信息到数据库（需要有商品标题才保存）
            # 尝试获取商品标题
            item_title_for_save = None
            try:
                from app.db_manager import db_manager
                db_item_info = db_manager.get_item_info(self.cookie_id, item_id)
                if db_item_info:
                    item_title_for_save = db_item_info.get('item_title', '').strip()
            except:
                pass

            # 如果有商品标题，则保存商品信息
            if item_title_for_save:
                await self.save_item_info_to_db(item_id, search_text, item_title_for_save)
            else:
                logger.warning(f"跳过保存商品信息：缺少商品标题 - {item_id}")

            # 详细的匹配结果日志
            if rule.get('is_multi_spec'):
                if spec_name and spec_value:
                    logger.info(f"🎯 精确匹配多规格发货规则: {rule['keyword']} -> {rule['card_name']} [{rule['spec_name']}:{rule['spec_value']}]")
                    logger.info(f"📋 订单规格: {spec_name}:{spec_value} ✅ 匹配卡券规格: {rule['spec_name']}:{rule['spec_value']}")
                else:
                    logger.info(f"⚠️ 使用多规格发货规则但无订单规格信息: {rule['keyword']} -> {rule['card_name']} [{rule['spec_name']}:{rule['spec_value']}]")
            else:
                if spec_name and spec_value:
                    logger.info(f"🔄 兜底匹配普通发货规则: {rule['keyword']} -> {rule['card_name']} ({rule['card_type']})")
                    logger.info(f"📋 订单规格: {spec_name}:{spec_value} ➡️ 使用普通卡券兜底")
                else:
                    logger.info(f"✅ 匹配普通发货规则: {rule['keyword']} -> {rule['card_name']} ({rule['card_type']})")

            # 获取延时设置
            delay_seconds = rule.get('card_delay_seconds', 0)

            # 执行延时（不管是否确认发货，只要有延时设置就执行）
            if delay_seconds and delay_seconds > 0:
                logger.info(f"检测到发货延时设置: {delay_seconds}秒，开始延时...")
                await asyncio.sleep(delay_seconds)
                logger.info(f"延时完成")

            # 检查是否存在订单ID，只有存在订单ID才处理发货内容
            if order_id:
                # 保存订单基本信息到数据库（如果还没有详细信息）
                try:
                    from app.db_manager import db_manager

                    # 检查cookie_id是否在cookies表中存在
                    cookie_info = db_manager.get_cookie_by_id(self.cookie_id)
                    if not cookie_info:
                        logger.warning(f"Cookie ID {self.cookie_id} 不存在于cookies表中，丢弃订单 {order_id}")
                    else:
                        existing_order = db_manager.get_order_by_id(order_id)
                        if not existing_order:
                            # 插入基本订单信息
                            success = db_manager.insert_or_update_order(
                                order_id=order_id,
                                item_id=item_id,
                                buyer_id=send_user_id,
                                cookie_id=self.cookie_id
                            )
                            
                            # 使用订单状态处理器设置状态
                            if success and self.order_status_handler:
                                try:
                                    self.order_status_handler.handle_order_basic_info_status(
                                        order_id=order_id,
                                        cookie_id=self.cookie_id,
                                        context="自动发货-基本信息"
                                    )
                                except Exception as e:
                                    logger.error(f"【{self.cookie_id}】订单状态处理器调用失败: {self._safe_str(e)}")
                            
                            if success:
                                logger.info(f"保存基本订单信息到数据库: {order_id}")
                except Exception as db_e:
                    logger.error(f"保存基本订单信息失败: {self._safe_str(db_e)}")

                # 开始处理发货内容
                logger.info(f"开始处理发货内容，规则: {rule['keyword']} -> {rule['card_name']} ({rule['card_type']})")

                delivery_content = None

                # 根据卡券类型处理发货内容
                if rule['card_type'] == 'api':
                    # API类型：调用API获取内容，传入订单和商品信息用于动态参数替换
                    delivery_content = await self._get_api_card_content(rule, order_id, item_id, send_user_id, spec_name, spec_value)

                elif rule['card_type'] == 'text':
                    # 固定文字类型：直接使用文字内容
                    delivery_content = rule['text_content']

                elif rule['card_type'] == 'data':
                    # 首次调用按“订单数量 * 每件发货数”一次性扣减，后续只读取内存队列。
                    if delivery_context is not None:
                        batch_queue = delivery_context.get("batch_data_queue")
                        if batch_queue is None:
                            try:
                                item_quantity = max(1, int(requested_item_quantity or 1))
                            except (TypeError, ValueError):
                                item_quantity = 1
                            delivery_count = max(
                                1,
                                int(delivery_context.get("delivery_count") or 1),
                            )
                            required_count = item_quantity * delivery_count
                            batch_queue = db_manager.consume_batch_data_batch(
                                rule['card_id'],
                                required_count,
                            )
                            if not batch_queue:
                                logger.warning(
                                    f"批量库存不足，整单未扣减: 卡券ID={rule['card_id']}, "
                                    f"需要={required_count}条"
                                )
                                return None
                            delivery_context["batch_data_queue"] = batch_queue
                            delivery_context["batch_data_required_count"] = required_count

                        if not batch_queue:
                            logger.error(
                                f"批量库存内存队列已耗尽: 卡券ID={rule['card_id']}"
                            )
                            return None
                        delivery_content = batch_queue.pop(0)
                    else:
                        delivery_content = db_manager.consume_batch_data(rule['card_id'])

                elif rule['card_type'] == 'image':
                    # 图片类型：返回图片发送标记，包含卡券ID
                    image_url = rule.get('image_url')
                    if image_url:
                        delivery_content = f"__IMAGE_SEND__{rule['card_id']}|{image_url}"
                        logger.info(f"准备发送图片: {image_url} (卡券ID: {rule['card_id']})")
                    else:
                        logger.error(f"图片卡券缺少图片URL: 卡券ID={rule['card_id']}")
                        delivery_content = None

                if delivery_content:
                    # 处理备注信息和变量替换
                    final_content = self._process_delivery_content_with_description(delivery_content, rule.get('card_description', ''))

                    # 增加对应规则或商品规格绑定的发货次数统计。
                    if rule.get("rule_kind") == "variant_binding":
                        db_manager.increment_variant_binding_delivery_times(
                            rule["variant_binding_id"]
                        )
                    else:
                        db_manager.increment_delivery_times(rule['id'])
                    logger.info(f"自动发货成功: 规则ID={rule['id']}, 内容长度={len(final_content)}")
                    return final_content
                else:
                    logger.warning(f"获取发货内容失败: 规则ID={rule['id']}")
                    return None
            else:
                # 没有订单ID，记录日志但不处理发货内容
                logger.info(f"⚠️ 未检测到订单ID，跳过发货内容处理。规则: {rule['keyword']} -> {rule['card_name']} ({rule['card_type']})")
                return None

        except Exception as e:
            logger.error(f"自动发货失败: {self._safe_str(e)}")
            return None



    def _process_delivery_content_with_description(self, delivery_content: str, card_description: str) -> str:
        """处理发货内容和备注信息，实现变量替换"""
        try:
            # 如果是图片发送标记，不进行备注处理，直接返回
            if delivery_content.startswith("__IMAGE_SEND__"):
                return delivery_content
            
            # 如果没有备注信息，直接返回发货内容
            if not card_description or not card_description.strip():
                return delivery_content

            # 替换备注中的变量
            processed_description = card_description.replace('{DELIVERY_CONTENT}', delivery_content)

            # 如果备注中包含变量替换，返回处理后的备注
            if '{DELIVERY_CONTENT}' in card_description:
                return processed_description
            else:
                # 如果备注中没有变量，将备注和发货内容组合
                return f"{processed_description}\n\n{delivery_content}"

        except Exception as e:
            logger.error(f"处理备注信息失败: {e}")
            # 出错时返回原始发货内容
            return delivery_content

    async def _get_api_card_content(self, rule, order_id=None, item_id=None, buyer_id=None, spec_name=None, spec_value=None, retry_count=0):
        """调用API获取卡券内容，支持动态参数替换和重试机制"""
        max_retries = 4

        if retry_count >= max_retries:
            logger.error(f"API调用失败，已达到最大重试次数({max_retries})")
            return None

        try:
            import aiohttp
            import json

            api_config = rule.get('api_config')
            if not api_config:
                logger.error(f"API配置为空，规则ID: {rule.get('id')}, 卡券名称: {rule.get('card_name')}")
                logger.warning(f"规则详情: {rule}")
                return None

            # 解析API配置
            if isinstance(api_config, str):
                api_config = json.loads(api_config)

            url = api_config.get('url')
            method = api_config.get('method', 'GET').upper()
            timeout = api_config.get('timeout', 10)
            headers = api_config.get('headers', '{}')
            params = api_config.get('params', '{}')

            # 解析headers和params
            if isinstance(headers, str):
                headers = json.loads(headers)
            if isinstance(params, str):
                params = json.loads(params)

            # 如果是POST请求且有动态参数，进行参数替换
            if method == 'POST' and params:
                params = await self._replace_api_dynamic_params(params, order_id, item_id, buyer_id, spec_name, spec_value)

            retry_info = f" (重试 {retry_count + 1}/{max_retries})" if retry_count > 0 else ""
            logger.info(f"调用API获取卡券: {method} {url}{retry_info}")
            if method == 'POST' and params:
                logger.warning(f"POST请求参数: {json.dumps(params, ensure_ascii=False)}")

            # 确保session存在
            if not self.session:
                await self.create_session()

            # 发起HTTP请求
            timeout_obj = aiohttp.ClientTimeout(total=timeout)

            if method == 'GET':
                async with self.session.get(url, headers=headers, params=params, timeout=timeout_obj) as response:
                    status_code = response.status
                    response_text = await response.text()
            elif method == 'POST':
                async with self.session.post(url, headers=headers, json=params, timeout=timeout_obj) as response:
                    status_code = response.status
                    response_text = await response.text()
            else:
                logger.error(f"不支持的HTTP方法: {method}")
                return None

            if status_code == 200:
                # 尝试解析JSON响应，如果失败则使用原始文本
                try:
                    result = json.loads(response_text)
                    # 如果返回的是对象，尝试提取常见的内容字段
                    if isinstance(result, dict):
                        content = result.get('data') or result.get('content') or result.get('card') or str(result)
                    else:
                        content = str(result)
                except:
                    content = response_text

                logger.info(f"API调用成功，返回内容长度: {len(content)}")
                return content
            else:
                logger.warning(f"API调用失败: {status_code} - {response_text[:200]}...")

                # 如果是服务器错误(5xx)或请求超时，进行重试
                if status_code >= 500 or status_code == 408:
                    if retry_count < max_retries - 1:
                        wait_time = (retry_count + 1) * 2  # 递增等待时间: 2s, 4s, 6s
                        logger.info(f"等待 {wait_time} 秒后重试...")
                        await asyncio.sleep(wait_time)
                        return await self._get_api_card_content(rule, order_id, item_id, buyer_id, spec_name, spec_value, retry_count + 1)

                return None

        except (aiohttp.ClientTimeout, aiohttp.ClientError) as e:
            logger.warning(f"API调用网络异常: {self._safe_str(e)}")

            # 网络异常也进行重试
            if retry_count < max_retries - 1:
                wait_time = (retry_count + 1) * 2  # 递增等待时间
                logger.info(f"等待 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)
                return await self._get_api_card_content(rule, order_id, item_id, buyer_id, spec_name, spec_value, retry_count + 1)
            else:
                logger.error(f"API调用网络异常，已达到最大重试次数: {self._safe_str(e)}")
                return None

        except Exception as e:
            logger.error(f"API调用异常: {self._safe_str(e)}")
            return None

    async def _replace_api_dynamic_params(self, params, order_id=None, item_id=None, buyer_id=None, spec_name=None, spec_value=None):
        """替换API请求参数中的动态参数"""
        try:
            if not params or not isinstance(params, dict):
                return params

            # 获取订单和商品信息
            order_info = None
            item_info = None

            # 如果有订单ID，获取订单信息
            if order_id:
                try:
                    from app.db_manager import db_manager
                    # 尝试从数据库获取订单信息
                    order_info = db_manager.get_order_by_id(order_id)
                    if not order_info:
                        # 如果数据库中没有，尝试通过API获取
                        order_detail = await self.fetch_order_detail_info(order_id, item_id, buyer_id)
                        if order_detail:
                            order_info = order_detail
                            logger.warning(f"通过API获取到订单信息: {order_id}")
                        else:
                            logger.warning(f"无法获取订单信息: {order_id}")
                    else:
                        logger.warning(f"从数据库获取到订单信息: {order_id}")
                except Exception as e:
                    logger.warning(f"获取订单信息失败: {self._safe_str(e)}")

            # 如果有商品ID，获取商品信息
            if item_id:
                try:
                    from app.db_manager import db_manager
                    item_info = db_manager.get_item_info(self.cookie_id, item_id)
                    if item_info:
                        logger.warning(f"从数据库获取到商品信息: {item_id}")
                    else:
                        logger.warning(f"无法获取商品信息: {item_id}")
                except Exception as e:
                    logger.warning(f"获取商品信息失败: {self._safe_str(e)}")

            # 构建参数映射
            param_mapping = {
                'order_id': order_id or '',
                'item_id': item_id or '',
                'buyer_id': buyer_id or '',
                'cookie_id': self.cookie_id or '',
                'spec_name': spec_name or '',
                'spec_value': spec_value or '',
            }

            # 从订单信息中提取参数
            if order_info:
                param_mapping.update({
                    'order_amount': str(order_info.get('amount', '')),
                    'order_quantity': str(order_info.get('quantity', '')),
                })

            # 从商品信息中提取参数
            if item_info:
                # 处理商品详情，如果是JSON字符串则提取detail字段
                item_detail = item_info.get('item_detail', '')
                if item_detail:
                    try:
                        # 尝试解析JSON
                        import json
                        detail_data = json.loads(item_detail)
                        if isinstance(detail_data, dict) and 'detail' in detail_data:
                            item_detail = detail_data['detail']
                    except (json.JSONDecodeError, TypeError):
                        # 如果不是JSON或解析失败，使用原始字符串
                        pass

                param_mapping.update({
                    'item_detail': item_detail,
                })

            # 递归替换参数
            replaced_params = self._recursive_replace_params(params, param_mapping)

            # 记录替换的参数
            replaced_keys = []
            for key, value in replaced_params.items():
                if isinstance(value, str) and '{' in str(params.get(key, '')):
                    replaced_keys.append(key)

            if replaced_keys:
                logger.info(f"API动态参数替换完成，替换的参数: {replaced_keys}")
                logger.warning(f"参数映射: {param_mapping}")

            return replaced_params

        except Exception as e:
            logger.error(f"替换API动态参数失败: {self._safe_str(e)}")
            return params

    def _recursive_replace_params(self, obj, param_mapping):
        """递归替换参数中的占位符"""
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                result[key] = self._recursive_replace_params(value, param_mapping)
            return result
        elif isinstance(obj, list):
            return [self._recursive_replace_params(item, param_mapping) for item in obj]
        elif isinstance(obj, str):
            # 替换字符串中的占位符
            result = obj
            for param_key, param_value in param_mapping.items():
                placeholder = f"{{{param_key}}}"
                if placeholder in result:
                    result = result.replace(placeholder, str(param_value))
            return result
        else:
            return obj

    async def token_refresh_loop(self):
        """Token刷新循环"""
        try:
            while True:
                try:
                    # 检查账号是否启用
                    from app.cookie_manager import manager as cookie_manager
                    if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                        logger.info(f"【{self.cookie_id}】账号已禁用，停止Token刷新循环")
                        break

                    current_time = time.time()
                    if current_time - self.last_token_refresh_time >= self.token_refresh_interval:
                        logger.info("Token即将过期，准备刷新...")
                        new_token = await self.refresh_token()
                        if new_token:
                            logger.info(f"【{self.cookie_id}】Token刷新成功，将关闭WebSocket以使用新Token重连")
                            
                            # Token刷新成功后，需要关闭WebSocket连接，让它用新Token重新连接
                            # 原因：WebSocket连接建立时使用的是旧Token，新Token需要重新建立连接才能生效
                            # 注意：只关闭WebSocket，不重启整个实例（后台任务继续运行）
                            
                            # 关闭当前WebSocket连接
                            if self.ws and not self.ws.closed:
                                try:
                                    logger.info(f"【{self.cookie_id}】关闭当前WebSocket连接以使用新Token重连...")
                                    await self.ws.close()
                                    logger.info(f"【{self.cookie_id}】WebSocket连接已关闭，将自动重连")
                                except Exception as close_e:
                                    logger.warning(f"【{self.cookie_id}】关闭WebSocket时出错: {self._safe_str(close_e)}")
                            
                            # 退出Token刷新循环，让main循环重新建立连接
                            # 后台任务（心跳、清理等）继续运行
                            logger.info(f"【{self.cookie_id}】Token刷新完成，WebSocket将使用新Token重新连接")
                            break
                        else:
                            # 根据上一次刷新状态决定日志级别（冷却/已重启为正常情况）
                            if getattr(self, 'last_token_refresh_status', None) in ("skipped_cooldown", "restarted_after_cookie_refresh"):
                                logger.info(f"【{self.cookie_id}】Token刷新未执行或已重启（正常），将在{self.token_retry_interval // 60}分钟后重试")
                            else:
                                logger.error(f"【{self.cookie_id}】Token刷新失败，将在{self.token_retry_interval // 60}分钟后重试")

                            # 清空当前token，确保下次重试时重新获取
                            self.current_token = None

                            # 发送Token刷新失败通知
                            await self.send_token_refresh_notification("Token定时刷新失败，将自动重试", "token_scheduled_refresh_failed")
                            await self._interruptible_sleep(self.token_retry_interval)
                            continue
                    await self._interruptible_sleep(60)
                except asyncio.CancelledError:
                    # 收到取消信号，立即退出循环
                    logger.info(f"【{self.cookie_id}】Token刷新循环收到取消信号，准备退出")
                    raise
                except Exception as e:
                    logger.error(f"Token刷新循环出错: {self._safe_str(e)}")
                    # 出错后也等待1分钟再重试，使用可中断的sleep
                    try:
                        await self._interruptible_sleep(60)
                    except asyncio.CancelledError:
                        logger.info(f"【{self.cookie_id}】Token刷新循环在重试等待时收到取消信号，准备退出")
                        raise
        except asyncio.CancelledError:
            # 确保CancelledError被正确传播
            logger.info(f"【{self.cookie_id}】Token刷新循环已取消，正在退出...")
            raise
        finally:
            # 确保任务能正常结束
            logger.info(f"【{self.cookie_id}】Token刷新循环已退出")

    async def create_chat(self, ws, toid, item_id='891198795482'):
        msg = {
            "lwp": "/r/SingleChatConversation/create",
            "headers": {
                "mid": generate_mid()
            },
            "body": [
                {
                    "pairFirst": f"{toid}@goofish",
                    "pairSecond": f"{self.myid}@goofish",
                    "bizType": "1",
                    "extension": {
                        "itemId": item_id
                    },
                    "ctx": {
                        "appVersion": "1.0",
                        "platform": "web"
                    }
                }
            ]
        }
        await ws.send(json.dumps(msg))

    async def send_msg(self, ws, cid, toid, text):
        text = {
            "contentType": 1,
            "text": {
                "text": text
            }
        }
        text_base64 = str(base64.b64encode(json.dumps(text).encode('utf-8')), 'utf-8')
        msg = {
            "lwp": "/r/MessageSend/sendByReceiverScope",
            "headers": {
                "mid": generate_mid()
            },
            "body": [
                {
                    "uuid": generate_uuid(),
                    "cid": f"{cid}@goofish",
                    "conversationType": 1,
                    "content": {
                        "contentType": 101,
                        "custom": {
                            "type": 1,
                            "data": text_base64
                        }
                    },
                    "redPointPolicy": 0,
                    "extension": {
                        "extJson": "{}"
                    },
                    "ctx": {
                        "appVersion": "1.0",
                        "platform": "web"
                    },
                    "mtags": {},
                    "msgReadStatusSetting": 1
                },
                {
                    "actualReceivers": [
                        f"{toid}@goofish",
                        f"{self.myid}@goofish"
                    ]
                }
            ]
        }
        await ws.send(json.dumps(msg))

    def _resolve_im_response(self, message_data):
        """Resolve a pending IM request when the server echoes its mid."""
        if not isinstance(message_data, dict):
            return False
        headers = message_data.get("headers")
        if not isinstance(headers, dict):
            return False
        mid = str(headers.get("mid") or "")
        if not mid:
            return False
        future = self._im_pending.pop(mid, None)
        if future is None or future.done():
            return False
        future.set_result(message_data)
        return True

    def _fail_pending_im_requests(self, reason):
        pending = list(self._im_pending.values())
        self._im_pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(ConnectionError(reason))

    async def _send_im_request(self, lwp, body, timeout=15):
        websocket = self.ws
        if websocket is None:
            # 风控冷却期内连接建不起来，给出可操作的提示而不是笼统的"未连接"
            from utils import risk_control

            guard = risk_control.registry.get(self.cookie_id)
            if guard.is_blocked:
                minutes = max(1, guard.remaining_seconds // 60)
                raise ConnectionError(
                    f"闲鱼要求人机验证，账号暂停请求中（约 {minutes} 分钟后自动重试）"
                )
            raise ConnectionError("账号尚未连接闲鱼消息服务")

        closed = getattr(websocket, "closed", False)
        if closed:
            raise ConnectionError("账号闲鱼消息连接已断开")

        mid = generate_mid()
        future = asyncio.get_running_loop().create_future()
        async with self._im_request_lock:
            self._im_pending[mid] = future
            try:
                await websocket.send(json.dumps({
                    "lwp": lwp,
                    "headers": {"mid": mid},
                    "body": body,
                }))
            except Exception:
                self._im_pending.pop(mid, None)
                raise

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._im_pending.pop(mid, None)
            raise TimeoutError(f"闲鱼消息服务响应超时: {lwp}") from exc
        finally:
            self._im_pending.pop(mid, None)

    async def get_im_conversations(self, start_timestamp=None, limit=20):
        if start_timestamp is None:
            start_timestamp = 9007199254740991
        response = await self._send_im_request(
            "/r/Conversation/listNewestPagination",
            [int(start_timestamp), max(1, min(int(limit), 100))],
        )
        return response.get("body", {}) if isinstance(response, dict) else {}

    async def get_im_messages(self, cid, start_timestamp=None, limit=20):
        if start_timestamp is None:
            start_timestamp = 9007199254740991
        full_cid = cid if "@goofish" in cid else f"{cid}@goofish"
        response = await self._send_im_request(
            "/r/MessageManager/listUserMessages",
            [full_cid, False, int(start_timestamp), max(1, min(int(limit), 100)), False],
        )
        return response.get("body", {}) if isinstance(response, dict) else {}

    async def mark_im_conversation_read(self, cid, message_id):
        target = str(message_id or "").strip()
        if not target:
            raise ValueError("缺少要标记已读的消息")
        full_cid = cid if "@goofish" in cid else f"{cid}@goofish"
        response = await self._send_im_request(
            "/r/Conversation/clearRedPoint",
            [[{"cid": full_cid, "messageId": target}]],
        )
        body = response.get("body", {}) if isinstance(response, dict) else {}
        if isinstance(body, dict) and (body.get("reason") or body.get("code")):
            reason = body.get("developerMessage") or body.get("reason") or body.get("code")
            raise RuntimeError(str(reason))
        return response

    async def send_im_text(self, cid, toid, text):
        text = str(text or "").strip()
        if not text:
            raise ValueError("消息内容不能为空")
        if len(text) > 2000:
            raise ValueError("消息内容不能超过 2000 个字符")

        full_cid = cid if "@goofish" in cid else f"{cid}@goofish"
        full_toid = toid if "@goofish" in toid else f"{toid}@goofish"
        payload = {
            "contentType": 1,
            "text": {"text": text},
        }
        text_base64 = base64.b64encode(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")
        response = await self._send_im_request(
            "/r/MessageSend/sendByReceiverScope",
            [
                {
                    "uuid": generate_uuid(),
                    "cid": full_cid,
                    "conversationType": 1,
                    "content": {
                        "contentType": 101,
                        "custom": {"type": 1, "data": text_base64},
                    },
                    "redPointPolicy": 0,
                    "extension": {"extJson": "{}"},
                    "ctx": {"appVersion": "1.0", "platform": "web"},
                    "mtags": {},
                    "msgReadStatusSetting": 1,
                },
                {
                    "actualReceivers": [
                        full_toid,
                        f"{self.myid}@goofish",
                    ],
                },
            ],
        )
        body = response.get("body", {}) if isinstance(response, dict) else {}
        if isinstance(body, dict) and (body.get("reason") or body.get("code")):
            reason = body.get("developerMessage") or body.get("reason") or body.get("code")
            raise RuntimeError(str(reason))
        return response

    async def _send_im_custom(self, cid, toid, payload):
        full_cid = cid if "@goofish" in cid else f"{cid}@goofish"
        full_toid = toid if "@goofish" in toid else f"{toid}@goofish"
        encoded = base64.b64encode(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")
        response = await self._send_im_request(
            "/r/MessageSend/sendByReceiverScope",
            [
                {
                    "uuid": generate_uuid(),
                    "cid": full_cid,
                    "conversationType": 1,
                    "content": {
                        "contentType": 101,
                        "custom": {"type": 1, "data": encoded},
                    },
                    "redPointPolicy": 0,
                    "extension": {"extJson": "{}"},
                    "ctx": {"appVersion": "1.0", "platform": "web"},
                    "mtags": {},
                    "msgReadStatusSetting": 1,
                },
                {
                    "actualReceivers": [
                        full_toid,
                        f"{self.myid}@goofish",
                    ],
                },
            ],
        )
        body = response.get("body", {}) if isinstance(response, dict) else {}
        if isinstance(body, dict) and (body.get("reason") or body.get("code")):
            reason = body.get("developerMessage") or body.get("reason") or body.get("code")
            raise RuntimeError(str(reason))
        return response

    async def send_im_image(self, cid, toid, image_path, width=None, height=None):
        from PIL import Image

        from app.xianyu_im import make_image_content
        from utils.image_uploader import ImageUploader

        if not image_path or not os.path.exists(image_path):
            raise ValueError("图片文件不存在")

        async with ImageUploader(self.cookies_str) as uploader:
            image_url = await uploader.upload_image(image_path)
        if not image_url:
            raise RuntimeError("图片上传失败，登录态可能已失效")

        if not width or not height:
            try:
                with Image.open(image_path) as img:
                    width, height = img.size
            except Exception:
                width, height = 800, 600
        width = int(width or 800)
        height = int(height or 600)
        response = await self._send_im_custom(
            cid, toid, make_image_content(image_url, width, height)
        )
        return {
            "response": response,
            "imageUrl": image_url,
            "width": width,
            "height": height,
        }

    async def send_im_video(self, cid, toid, video_path, content_type="video/mp4"):
        from app.xianyu_im import make_video_content
        from utils.im_media import probe_media
        from utils.image_uploader import ImageUploader

        if not video_path or not os.path.exists(video_path):
            raise ValueError("视频文件不存在")

        async with ImageUploader(self.cookies_str) as uploader:
            video_url = await uploader.upload_file(video_path, content_type, timeout=180)
        if not video_url:
            raise RuntimeError("视频上传失败，登录态可能已失效")

        info = await probe_media(video_path)
        response = await self._send_im_custom(
            cid,
            toid,
            make_video_content(
                video_url,
                info.get("width") or 0,
                info.get("height") or 0,
                info.get("durationMs") or 0,
            ),
        )
        return {
            "response": response,
            "videoUrl": video_url,
            "width": info.get("width") or 0,
            "height": info.get("height") or 0,
            "durationMs": info.get("durationMs") or 0,
        }

    async def init(self, ws):
        # 如果没有token或者token过期，获取新token
        token_refresh_attempted = False
        if not self.current_token or (time.time() - self.last_token_refresh_time) >= self.token_refresh_interval:
            logger.info(f"【{self.cookie_id}】获取初始token...")
            token_refresh_attempted = True

            await self.refresh_token()

        if not self.current_token:
            logger.error("无法获取有效token，初始化失败")
            # 只有在没有尝试刷新token的情况下才发送通知，避免与refresh_token中的通知重复
            if not token_refresh_attempted:
                await self.send_token_refresh_notification("初始化时无法获取有效Token", "token_init_failed")
            else:
                logger.info("由于刚刚尝试过token刷新，跳过重复的初始化失败通知")
            raise Exception("Token获取失败")

        msg = {
            "lwp": "/reg",
            "headers": {
                "cache-header": "app-key token ua wv",
                "app-key": APP_CONFIG.get('app_key'),
                "token": self.current_token,
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) DingWeb/2.1.5 IMPaaS DingWeb/2.1.5",
                "dt": "j",
                "wv": "im:3,au:3,sy:6",
                "sync": "0,0;0;0;",
                "did": self.device_id,
                "mid": generate_mid()
            }
        }
        await ws.send(json.dumps(msg))
        await asyncio.sleep(1)
        current_time = int(time.time() * 1000)
        msg = {
            "lwp": "/r/SyncStatus/ackDiff",
            "headers": {"mid": generate_mid()},
            "body": [
                {
                    "pipeline": "sync",
                    "tooLong2Tag": "PNM,1",
                    "channel": "sync",
                    "topic": "sync",
                    "highPts": 0,
                    "pts": current_time * 1000,
                    "seq": 0,
                    "timestamp": current_time
                }
            ]
        }
        await ws.send(json.dumps(msg))
        logger.info(f'【{self.cookie_id}】连接注册完成')

    async def send_heartbeat(self, ws):
        """发送心跳包"""
        # 检查WebSocket连接状态，如果已关闭则不发送
        if ws.closed:
            raise ConnectionError("WebSocket连接已关闭，无法发送心跳")
        
        msg = {
            "lwp": "/!",
            "headers": {
                "mid": generate_mid()
            }
        }
        # 添加超时保护，避免在WebSocket关闭时阻塞
        try:
            await asyncio.wait_for(ws.send(json.dumps(msg)), timeout=2.0)
            self.last_heartbeat_time = time.time()
            logger.warning(f"【{self.cookie_id}】心跳包已发送")
        except asyncio.TimeoutError:
            raise ConnectionError("心跳发送超时，WebSocket可能已断开")
        except asyncio.CancelledError:
            # 如果被取消，立即重新抛出，不执行后续操作
            raise

    async def heartbeat_loop(self, ws):
        """心跳循环"""
        consecutive_failures = 0
        max_failures = 3  # 连续失败3次后停止心跳

        try:
            while True:
                try:
                    # 检查账号是否启用
                    from app.cookie_manager import manager as cookie_manager
                    if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                        logger.info(f"【{self.cookie_id}】账号已禁用，停止心跳循环")
                        break

                    # 检查WebSocket连接状态
                    if ws.closed:
                        logger.warning(f"【{self.cookie_id}】WebSocket连接已关闭，停止心跳循环")
                        break

                    await self.send_heartbeat(ws)
                    consecutive_failures = 0  # 重置失败计数

                    await self._interruptible_sleep(self.heartbeat_interval)

                except asyncio.CancelledError:
                    # 收到取消信号，立即退出循环
                    logger.info(f"【{self.cookie_id}】心跳循环收到取消信号，准备退出")
                    raise  # 重新抛出，让任务正常结束
                except Exception as e:
                    consecutive_failures += 1
                    logger.error(f"心跳发送失败 ({consecutive_failures}/{max_failures}): {self._safe_str(e)}")

                    if consecutive_failures >= max_failures:
                        logger.error(f"【{self.cookie_id}】心跳连续失败{max_failures}次，停止心跳循环")
                        break

                    # 失败后短暂等待再重试，使用可中断的sleep
                    try:
                        await self._interruptible_sleep(5)
                    except asyncio.CancelledError:
                        # 在等待重试时收到取消信号，立即退出
                        logger.info(f"【{self.cookie_id}】心跳循环在重试等待时收到取消信号，准备退出")
                        raise
        except asyncio.CancelledError:
            # 确保CancelledError被正确传播
            logger.info(f"【{self.cookie_id}】心跳循环已取消，正在退出...")
            raise
        finally:
            # 确保任务能正常结束
            logger.info(f"【{self.cookie_id}】心跳循环已退出")

    async def handle_heartbeat_response(self, message_data):
        """处理心跳响应"""
        try:
            if message_data.get("code") == 200:
                self.last_heartbeat_response = time.time()
                logger.warning("心跳响应正常")
                return True
        except Exception as e:
            logger.error(f"处理心跳响应出错: {self._safe_str(e)}")
        return False

    async def pause_cleanup_loop(self):
        """定期清理过期的暂停记录、锁和缓存"""
        try:
            while True:
                try:
                    # 检查账号是否启用
                    from app.cookie_manager import manager as cookie_manager
                    if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                        logger.info(f"【{self.cookie_id}】账号已禁用，停止清理循环")
                        break

                    # 清理过期的暂停记录
                    pause_manager.cleanup_expired_pauses()
                    await asyncio.sleep(0)  # 让出控制权，允许检查取消信号

                    # 清理过期的锁（每5分钟清理一次，保留24小时内的锁）
                    self.cleanup_expired_locks(max_age_hours=24)
                    await asyncio.sleep(0)  # 让出控制权，允许检查取消信号

                    # 清理过期的商品详情缓存
                    try:
                        cleaned_count = await self._cleanup_item_cache()
                        if cleaned_count > 0:
                            logger.info(f"【{self.cookie_id}】清理了 {cleaned_count} 个过期的商品详情缓存")
                    except asyncio.CancelledError:
                        raise
                    except Exception as cache_clean_e:
                        logger.warning(f"【{self.cookie_id}】清理商品详情缓存时出错: {cache_clean_e}")

                    # 清理过期的通知、发货和订单确认记录（防止内存泄漏）
                    self._cleanup_instance_caches()
                    await asyncio.sleep(0)  # 让出控制权，允许检查取消信号

                    # 清理QR登录过期会话（每5分钟检查一次）
                    try:
                        from utils.qr_login import qr_login_manager
                        qr_login_manager.cleanup_expired_sessions()
                        await asyncio.sleep(0)  # 让出控制权，允许检查取消信号
                    except asyncio.CancelledError:
                        raise
                    except Exception as qr_clean_e:
                        logger.warning(f"【{self.cookie_id}】清理QR登录会话时出错: {qr_clean_e}")
                    
                    # 清理Playwright浏览器临时文件和缓存（每5分钟检查一次）
                    try:
                        await self._cleanup_playwright_cache()
                    except asyncio.CancelledError:
                        raise
                    except Exception as pw_clean_e:
                        logger.warning(f"【{self.cookie_id}】清理Playwright缓存时出错: {pw_clean_e}")
                    
                    # 清理过期的日志文件（每5分钟检查一次，保留7天）
                    try:
                        cleaned_logs = await self._cleanup_old_logs(retention_days=7)
                        await asyncio.sleep(0)  # 让出控制权，允许检查取消信号
                    except asyncio.CancelledError:
                        raise
                    except Exception as log_clean_e:
                        logger.warning(f"【{self.cookie_id}】清理日志文件时出错: {log_clean_e}")
                    
                    # 清理数据库历史数据（每天一次，保留90天数据）
                    # 为避免所有实例同时执行，只让第一个实例执行
                    try:
                        if hasattr(self.__class__, '_last_db_cleanup_time'):
                            last_cleanup = self.__class__._last_db_cleanup_time
                        else:
                            self.__class__._last_db_cleanup_time = 0
                            last_cleanup = 0
                        
                        current_time = time.time()
                        # 每24小时清理一次
                        if current_time - last_cleanup > 86400:
                            logger.info(f"【{self.cookie_id}】开始执行数据库历史数据清理...")
                            # 数据库清理可能很耗时，使用线程池执行，避免阻塞事件循环
                            # 这样即使清理操作很慢，也能响应取消信号
                            try:
                                stats = await asyncio.to_thread(db_manager.cleanup_old_data, days=90)
                                if 'error' not in stats:
                                    logger.info(f"【{self.cookie_id}】数据库清理完成: {stats}")
                                    self.__class__._last_db_cleanup_time = current_time
                                else:
                                    logger.error(f"【{self.cookie_id}】数据库清理失败: {stats['error']}")
                            except asyncio.CancelledError:
                                logger.warning(f"【{self.cookie_id}】数据库清理被取消")
                                raise
                    except asyncio.CancelledError:
                        raise  # 重新抛出取消信号
                    except Exception as db_clean_e:
                        logger.error(f"【{self.cookie_id}】清理数据库历史数据时出错: {db_clean_e}")

                    # 每5分钟清理一次
                    await self._interruptible_sleep(300)
                except asyncio.CancelledError:
                    # 收到取消信号，立即退出循环
                    logger.info(f"【{self.cookie_id}】清理循环收到取消信号，准备退出")
                    raise
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】清理任务失败: {self._safe_str(e)}")
                    # 出错后也等待5分钟再重试，使用可中断的sleep
                    try:
                        await self._interruptible_sleep(300)
                    except asyncio.CancelledError:
                        logger.info(f"【{self.cookie_id}】清理循环在重试等待时收到取消信号，准备退出")
                        raise
        except asyncio.CancelledError:
            # 确保CancelledError被正确传播
            logger.info(f"【{self.cookie_id}】清理循环已取消，正在退出...")
            raise
        finally:
            # 确保任务能正常结束
            logger.info(f"【{self.cookie_id}】清理循环已退出")


    async def item_sync_loop(self):
        """商品同步定时任务 - 按配置间隔定时同步商品信息

        支持动态配置更新：每次循环时从数据库读取最新配置
        """
        try:
            while True:
                try:
                    # 检查账号是否启用
                    from app.cookie_manager import manager as cookie_manager
                    if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                        logger.info(f"【{self.cookie_id}】账号已禁用，停止商品同步循环")
                        break

                    # 从数据库读取最新配置（支持动态更新）
                    from app.db_manager import db_manager
                    item_sync_enabled_str = db_manager.get_system_setting('item_sync_enabled')
                    item_sync_interval_str = db_manager.get_system_setting('item_sync_interval')
                    item_sync_max_pages_str = db_manager.get_system_setting('item_sync_max_pages')

                    # 使用数据库配置，如果不存在则使用实例变量（从global_config.yml读取的默认值）
                    item_sync_enabled = item_sync_enabled_str == 'true' if item_sync_enabled_str is not None else self.item_sync_enabled
                    item_sync_interval = int(item_sync_interval_str) if item_sync_interval_str is not None else self.item_sync_interval
                    item_sync_max_pages = int(item_sync_max_pages_str) if item_sync_max_pages_str is not None else self.item_sync_max_pages

                    # 检查是否启用了商品同步功能
                    if not item_sync_enabled:
                        await self._interruptible_sleep(60)  # 未启用时每分钟检查一次
                        continue

                    # 检查距离上次同步的时间
                    current_time = time.time()
                    if current_time - self.last_item_sync_time < item_sync_interval:
                        # 未到达同步时间，等待
                        wait_time = min(60, item_sync_interval - (current_time - self.last_item_sync_time))
                        await self._interruptible_sleep(wait_time)
                        continue

                    # 使用Lock防止重复执行
                    if self.item_sync_lock.locked():
                        logger.info(f"【{self.cookie_id}】商品同步任务正在进行中，跳过本次执行")
                        await self._interruptible_sleep(60)
                        continue

                    # 执行商品同步
                    async with self.item_sync_lock:
                        try:
                            logger.info(f"【{self.cookie_id}】🔄 开始定时同步商品信息...")
                            result = await self.get_all_items(page_size=20, max_pages=item_sync_max_pages)

                            if result.get('success'):
                                total_count = result.get('total_count', 0)
                                saved_count = result.get('total_saved', 0)
                                self.last_item_sync_time = current_time
                                if result.get('confirmed_empty'):
                                    account_id = result.get('account_id') or self.myid
                                    group_name = result.get('group_name', '在售')
                                    logger.info(
                                        f"【{self.cookie_id}】商品同步完成: 闲鱼接口确认账号 "
                                        f"{account_id} 的“{group_name}”分组当前为 0 件"
                                    )
                                else:
                                    logger.info(
                                        f"【{self.cookie_id}】✅ 商品同步完成: 共 {total_count} 件商品，"
                                        f"保存/更新 {saved_count} 件"
                                    )
                            else:
                                error_msg = result.get('error', '未知错误')
                                logger.warning(f"【{self.cookie_id}】❌ 商品同步失败: {error_msg}")

                        except asyncio.CancelledError:
                            logger.info(f"【{self.cookie_id}】商品同步被取消")
                            raise
                        except Exception as sync_error:
                            logger.error(f"【{self.cookie_id}】商品同步异常: {self._safe_str(sync_error)}")

                    # 等待下次同步时间
                    await self._interruptible_sleep(item_sync_interval)

                except asyncio.CancelledError:
                    # 收到取消信号，立即退出循环
                    logger.info(f"【{self.cookie_id}】商品同步循环收到取消信号，准备退出")
                    raise
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】商品同步任务失败: {self._safe_str(e)}")
                    # 出错后等待1分钟再重试
                    try:
                        await self._interruptible_sleep(60)
                    except asyncio.CancelledError:
                        logger.info(f"【{self.cookie_id}】商品同步循环在重试等待时收到取消信号，准备退出")
                        raise
        except asyncio.CancelledError:
            # 确保CancelledError被正确传播
            logger.info(f"【{self.cookie_id}】商品同步循环已取消，正在退出...")
            raise
        finally:
            # 确保任务能正常结束
            logger.info(f"【{self.cookie_id}】商品同步循环已退出")


    async def order_sync_loop(self):
        """订单同步定时任务。

        消息驱动只能捕获监听在线期间的订单事件，离线时段产生的订单会完全丢失，
        这里定期从卖家端接口拉全量做对账。间隔可在系统设置里调整。
        """
        # 启动错峰：多账号多任务同时发请求容易触发平台风控
        await self._interruptible_sleep(random.uniform(0, 120))
        try:
            while True:
                try:
                    from app.cookie_manager import manager as cookie_manager
                    if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                        logger.info(f"【{self.cookie_id}】账号已禁用，停止订单同步循环")
                        break

                    from app.db_manager import db_manager
                    enabled_str = db_manager.get_system_setting('order_sync_enabled')
                    interval_str = db_manager.get_system_setting('order_sync_interval')

                    # 默认开启，间隔 30 分钟
                    enabled = enabled_str != 'false'
                    try:
                        interval = int(interval_str) if interval_str else 7200
                    except (TypeError, ValueError):
                        interval = 7200
                    # 订单同步会翻多页，是请求量最大的任务，最短 30 分钟
                    interval = max(1800, interval)

                    if not enabled:
                        await self._interruptible_sleep(60)
                        continue

                    current_time = time.time()
                    if current_time - self.last_order_sync_time < interval:
                        wait_time = min(60, interval - (current_time - self.last_order_sync_time))
                        await self._interruptible_sleep(wait_time)
                        continue

                    if not self.cookies_str:
                        await self._interruptible_sleep(60)
                        continue

                    # 风控冷却期内不发任何主动请求
                    from utils import risk_control
                    guard = risk_control.registry.get(self.cookie_id)
                    if guard.is_blocked:
                        wait = min(guard.remaining_seconds + 5, 300)
                        logger.debug(
                            f"【{self.cookie_id}】风控冷却中，{wait} 秒后再检查"
                        )
                        await self._interruptible_sleep(wait)
                        continue

                    try:
                        from utils.seller_order_sync import sync_account_orders

                        result = await sync_account_orders(self.cookie_id, self.cookies_str)
                        self.last_order_sync_time = current_time

                        new_cookies = result.get('cookies_str')
                        if new_cookies and new_cookies != self.cookies_str:
                            self.cookies_str = new_cookies

                        logger.info(
                            f"【{self.cookie_id}】定时订单同步完成: 共 {result['total']} 单，"
                            f"成功 {result['saved']}，失败 {result['failed']}"
                        )
                    except asyncio.CancelledError:
                        logger.info(f"【{self.cookie_id}】订单同步被取消")
                        raise
                    except Exception as sync_error:
                        logger.error(
                            f"【{self.cookie_id}】订单同步异常: {self._safe_str(sync_error)}"
                        )

                    await self._interruptible_sleep(interval)

                except asyncio.CancelledError:
                    logger.info(f"【{self.cookie_id}】订单同步循环收到取消信号，准备退出")
                    raise
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】订单同步任务失败: {self._safe_str(e)}")
                    try:
                        await self._interruptible_sleep(60)
                    except asyncio.CancelledError:
                        raise
        except asyncio.CancelledError:
            logger.info(f"【{self.cookie_id}】订单同步循环已取消，正在退出...")
            raise
        finally:
            logger.info(f"【{self.cookie_id}】订单同步循环已退出")


    async def item_polish_loop(self):
        """商品擦亮定时任务。

        擦亮会把商品重新推到搜索和推荐前列，是平台提供的免费曝光手段。
        平台对每个商品每天的擦亮次数有限制，超出会返回业务错误但不影响流程。
        默认关闭，需要在设置里开启。
        """
        # 启动错峰：多账号多任务同时发请求容易触发平台风控
        await self._interruptible_sleep(random.uniform(0, 180))
        try:
            while True:
                try:
                    from app.cookie_manager import manager as cookie_manager
                    if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                        logger.info(f"【{self.cookie_id}】账号已禁用，停止商品擦亮循环")
                        break

                    from app.db_manager import db_manager
                    enabled_str = db_manager.get_system_setting('auto_polish_enabled')
                    interval_str = db_manager.get_system_setting('auto_polish_interval')

                    # 默认关闭：擦亮是对外动作，由用户显式开启
                    enabled = str(enabled_str or '').strip().lower() in ('1', 'true', 'yes')
                    try:
                        interval = int(interval_str) if interval_str else 21600
                    except (TypeError, ValueError):
                        interval = 21600
                    # 擦亮太频繁没有意义，最短 1 小时
                    interval = max(3600, interval)

                    if not enabled:
                        await self._interruptible_sleep(120)
                        continue

                    current_time = time.time()
                    if current_time - self.last_polish_time < interval:
                        wait_time = min(120, interval - (current_time - self.last_polish_time))
                        await self._interruptible_sleep(wait_time)
                        continue

                    if not self.cookies_str:
                        await self._interruptible_sleep(120)
                        continue

                    # 风控冷却期内不发任何主动请求
                    from utils import risk_control
                    guard = risk_control.registry.get(self.cookie_id)
                    if guard.is_blocked:
                        wait = min(guard.remaining_seconds + 5, 300)
                        logger.debug(
                            f"【{self.cookie_id}】风控冷却中，{wait} 秒后再检查"
                        )
                        await self._interruptible_sleep(wait)
                        continue

                    try:
                        from utils.item_polish import polish_account_items

                        result = await polish_account_items(self.cookie_id, self.cookies_str)
                        self.last_polish_time = current_time

                        new_cookies = result.get('cookies_str')
                        if new_cookies and new_cookies != self.cookies_str:
                            self.cookies_str = new_cookies

                        if result['total']:
                            logger.info(
                                f"【{self.cookie_id}】定时擦亮完成: 共 {result['total']} 个商品，"
                                f"成功 {result['success']}，失败 {result['failed']}"
                            )
                    except asyncio.CancelledError:
                        logger.info(f"【{self.cookie_id}】商品擦亮被取消")
                        raise
                    except Exception as polish_error:
                        logger.error(
                            f"【{self.cookie_id}】商品擦亮异常: {self._safe_str(polish_error)}"
                        )

                    await self._interruptible_sleep(interval)

                except asyncio.CancelledError:
                    logger.info(f"【{self.cookie_id}】商品擦亮循环收到取消信号，准备退出")
                    raise
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】商品擦亮任务失败: {self._safe_str(e)}")
                    try:
                        await self._interruptible_sleep(120)
                    except asyncio.CancelledError:
                        raise
        except asyncio.CancelledError:
            logger.info(f"【{self.cookie_id}】商品擦亮循环已取消，正在退出...")
            raise
        finally:
            logger.info(f"【{self.cookie_id}】商品擦亮循环已退出")


    async def delivery_timeout_loop(self):
        """发货超时告警。

        闲鱼对超时未发货有处罚。卖家端订单接口提供了两个预警状态：
        ``NOT_SHIP_ABOUT_TO_EXPIRE``（即将超时）和 ``NOT_SHIP_EXPIRED``（已超时），
        这里定期检查并推送到通知渠道。同一订单同一状态只提醒一次。
        """
        # 启动错峰：多账号多任务同时发请求容易触发平台风控
        await self._interruptible_sleep(random.uniform(0, 90))
        try:
            while True:
                try:
                    from app.cookie_manager import manager as cookie_manager
                    if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                        logger.info(f"【{self.cookie_id}】账号已禁用，停止发货超时检查")
                        break

                    from app.db_manager import db_manager
                    enabled_str = db_manager.get_system_setting('delivery_timeout_alert_enabled')
                    interval_str = db_manager.get_system_setting('delivery_timeout_interval')

                    # 默认开启：超时会被平台处罚，属于必要提醒
                    enabled = str(enabled_str or '').strip().lower() != 'false'
                    try:
                        interval = int(interval_str) if interval_str else 3600
                    except (TypeError, ValueError):
                        interval = 3600
                    interval = max(900, interval)

                    if not enabled or not self.cookies_str:
                        await self._interruptible_sleep(120)
                        continue

                    # 风控冷却期内不发任何主动请求
                    from utils import risk_control
                    guard = risk_control.registry.get(self.cookie_id)
                    if guard.is_blocked:
                        wait = min(guard.remaining_seconds + 5, 300)
                        logger.debug(
                            f"【{self.cookie_id}】风控冷却中，{wait} 秒后再检查"
                        )
                        await self._interruptible_sleep(wait)
                        continue

                    try:
                        await self._check_delivery_timeout()
                    except asyncio.CancelledError:
                        raise
                    except Exception as check_error:
                        logger.error(
                            f"【{self.cookie_id}】发货超时检查异常: {self._safe_str(check_error)}"
                        )

                    await self._interruptible_sleep(interval)

                except asyncio.CancelledError:
                    logger.info(f"【{self.cookie_id}】发货超时检查收到取消信号，准备退出")
                    raise
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】发货超时检查失败: {self._safe_str(e)}")
                    try:
                        await self._interruptible_sleep(120)
                    except asyncio.CancelledError:
                        raise
        except asyncio.CancelledError:
            logger.info(f"【{self.cookie_id}】发货超时检查已取消，正在退出...")
            raise
        finally:
            logger.info(f"【{self.cookie_id}】发货超时检查已退出")

    async def _check_delivery_timeout(self) -> int:
        """查询即将超时和已超时的待发货订单并推送告警。

        Returns:
            本次新提醒的订单数。
        """
        from utils.xianyu_seller_api import (
            XianyuSellerAPI,
            SellerApiError,
            parse_sold_order,
        )

        alerts = []
        api = XianyuSellerAPI(self.cookie_id, self.cookies_str)
        try:
            for query_code, label in (
                ("NOT_SHIP_ABOUT_TO_EXPIRE", "即将超时"),
                ("NOT_SHIP_EXPIRED", "已超时"),
            ):
                try:
                    batch = await api.get_sold_orders(
                        query_code=query_code, rows_per_page=50
                    )
                except SellerApiError as exc:
                    logger.debug(f"【{self.cookie_id}】查询 {query_code} 失败: {exc}")
                    continue

                for item in batch.get("items") or []:
                    parsed = parse_sold_order(item)
                    order_id = parsed.get("order_id")
                    if not order_id:
                        continue
                    # 同一订单的同一告警级别只提醒一次，避免重复轰炸
                    alert_key = f"{order_id}:{query_code}"
                    if alert_key in self._delivery_timeout_alerted:
                        continue
                    self._delivery_timeout_alerted.add(alert_key)
                    alerts.append((label, parsed))

            if self.cookies_str != api.cookies_str and api.cookies_str:
                self.cookies_str = api.cookies_str
        finally:
            await api.close()

        if not alerts:
            return 0

        lines = [f"⚠️ 发货超时提醒（账号 {self.cookie_id}）", ""]
        for label, parsed in alerts:
            lines.append(
                f"[{label}] 订单 {parsed['order_id']}\n"
                f"  商品: {parsed.get('item_title') or '未知'}\n"
                f"  金额: {parsed.get('amount') or '未知'}\n"
                f"  下单: {parsed.get('created_at') or '未知'}"
            )
        lines.append("")
        lines.append("请尽快处理，超时未发货会被平台处罚。")

        message = "\n".join(lines)
        sent = await self.send_system_notification(message)
        logger.warning(
            f"【{self.cookie_id}】发货超时告警: {len(alerts)} 个订单，已推送 {sent} 个渠道"
        )
        return len(alerts)


    async def buyer_interaction_loop(self):
        """自动评价与求小红花。

        两者都会对买家产生实际动作（评价不可撤销、求花会发消息），因此默认关闭，
        需要在设置里显式开启。同一订单只处理一次。
        """
        # 启动错峰：多账号多任务同时发请求容易触发平台风控
        await self._interruptible_sleep(random.uniform(0, 240))
        try:
            while True:
                try:
                    from app.cookie_manager import manager as cookie_manager
                    if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                        logger.info(f"【{self.cookie_id}】账号已禁用，停止买家互动任务")
                        break

                    from app.db_manager import db_manager
                    # 开关按账号存：不同账号经营策略不同，全局开关意味着一开就是
                    # 所有账号一起开，用户没法只对部分账号启用。
                    interaction = db_manager.get_buyer_interaction_settings(self.cookie_id)
                    rate_on = interaction['auto_rate_enabled']
                    flower_on = interaction['auto_flower_enabled']
                    interval_str = db_manager.get_system_setting('buyer_interaction_interval')
                    try:
                        interval = int(interval_str) if interval_str else 7200
                    except (TypeError, ValueError):
                        interval = 7200
                    # 下限从 30 分钟放宽到 5 分钟：确认收货现在由消息事件即时触发，
                    # 轮询退化成兜底（漏收消息、服务重启期间完成的订单）。但仍要有
                    # 下限 —— 这条循环每轮都拉一次卖出订单列表，太频繁会招来风控。
                    interval = min(max(300, interval), 86400)

                    if (not rate_on and not flower_on) or not self.cookies_str:
                        await self._interruptible_sleep(180)
                        continue

                    # 风控冷却期内不发任何主动请求
                    from utils import risk_control
                    guard = risk_control.registry.get(self.cookie_id)
                    if guard.is_blocked:
                        wait = min(guard.remaining_seconds + 5, 300)
                        logger.debug(
                            f"【{self.cookie_id}】风控冷却中，{wait} 秒后再检查"
                        )
                        await self._interruptible_sleep(wait)
                        continue

                    try:
                        await self._run_buyer_interactions(rate_on, flower_on)
                    except asyncio.CancelledError:
                        raise
                    except Exception as run_error:
                        logger.error(
                            f"【{self.cookie_id}】买家互动执行异常: {self._safe_str(run_error)}"
                        )

                    await self._interruptible_sleep(interval)

                except asyncio.CancelledError:
                    logger.info(f"【{self.cookie_id}】买家互动任务收到取消信号，准备退出")
                    raise
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】买家互动任务失败: {self._safe_str(e)}")
                    try:
                        await self._interruptible_sleep(180)
                    except asyncio.CancelledError:
                        raise
        except asyncio.CancelledError:
            logger.info(f"【{self.cookie_id}】买家互动任务已取消，正在退出...")
            raise
        finally:
            logger.info(f"【{self.cookie_id}】买家互动任务已退出")

    # 确认收货致谢的默认文案。留空则不发。
    DEFAULT_THANKS_TEMPLATE = '亲，感谢支持！有任何问题随时找我~'

    async def send_post_receipt_thanks(self, websocket, chat_id, to_user_id, order_id=None):
        """确认收货后给买家发一条致谢文本。

        和评价/求花不同，这条只是发消息，不依赖卖出订单接口的状态流转，所以直接
        在收到「交易成功」消息时就地发出 —— 此时 chat_id 和买家 ID 都在手上，
        不必再查订单。

        同一个会话只发一次：确认收货往往伴随多条系统消息（交易成功、评价提醒、
        小红花提醒），逐条发会连着骚扰买家。
        """
        from app.db_manager import db_manager

        if not db_manager.get_buyer_interaction_settings(
            self.cookie_id
        )['auto_thanks_enabled']:
            return False

        key = str(order_id or chat_id)
        if key in self._thanked_receipts:
            logger.debug(f"【{self.cookie_id}】{key} 已发过确认收货致谢，跳过")
            return False

        template = (
            db_manager.get_system_setting('auto_thanks_template')
            or self.DEFAULT_THANKS_TEMPLATE
        ).strip()
        if not template:
            return False

        # 先登记再发送：发送失败也不重试，避免异常时反复打扰买家
        self._thanked_receipts.add(key)
        try:
            await self.send_msg(websocket, chat_id, to_user_id, template)
            logger.info(f"【{self.cookie_id}】确认收货致谢已发送: chat_id={chat_id}")
            return True
        except Exception as exc:
            logger.warning(
                f"【{self.cookie_id}】确认收货致谢发送失败: {self._safe_str(exc)}"
            )
            return False

    # 交易成功后触发前的等待秒数。闲鱼推送「交易成功」消息时，卖出订单接口未必
    # 已经把该单切到 TRADE_SUCCESS，立刻去查会查不到；等一小会儿再查。
    BUYER_INTERACTION_TRIGGER_DELAY = float(
        os.getenv('BUYER_INTERACTION_TRIGGER_DELAY', '20')
    )

    async def trigger_buyer_interactions_now(self, reason: str = '交易成功'):
        """收到交易成功消息后立即执行一次买家互动，不必等下一轮轮询。

        轮询间隔最短也有几十分钟，买家确认收货后要等很久才评价/求花，时机上
        已经偏晚。这里由消息事件驱动，做成「尽快执行一次」。

        同一时刻只允许一个触发在跑：确认收货往往伴随多条系统消息（交易成功、
        评价提醒、小红花提醒），每条都触发一次会连着打同一个接口。
        """
        if getattr(self, '_buyer_interaction_triggering', False):
            logger.debug(f"【{self.cookie_id}】买家互动已在触发中，忽略重复的「{reason}」")
            return

        from app.db_manager import db_manager
        interaction = db_manager.get_buyer_interaction_settings(self.cookie_id)
        if not interaction['auto_rate_enabled'] and not interaction['auto_flower_enabled']:
            return
        if not self.cookies_str:
            return

        self._buyer_interaction_triggering = True

        async def run():
            try:
                await asyncio.sleep(self.BUYER_INTERACTION_TRIGGER_DELAY)

                from utils import risk_control
                guard = risk_control.registry.get(self.cookie_id)
                if guard.is_blocked:
                    logger.info(
                        f"【{self.cookie_id}】{reason}触发买家互动，但正处风控冷却，"
                        f"交由定时轮询稍后处理"
                    )
                    return

                logger.info(f"【{self.cookie_id}】{reason}，立即执行买家互动")
                result = await self._run_buyer_interactions(
                    interaction['auto_rate_enabled'], interaction['auto_flower_enabled']
                )
                if not result.get('rated') and not result.get('flowered'):
                    logger.info(
                        f"【{self.cookie_id}】{reason}触发未产生动作"
                        f"（可能该单已评价过，或接口尚未返回可求花状态）"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    f"【{self.cookie_id}】{reason}触发买家互动失败: {self._safe_str(exc)}"
                )
            finally:
                self._buyer_interaction_triggering = False

        asyncio.create_task(run())

    async def _run_buyer_interactions(self, rate_on: bool, flower_on: bool) -> dict:
        """对已完结订单执行评价和求花。

        判定依据来自订单接口：``sellerRateStatus`` 为 4 表示卖家已评价，
        ``REQUIRE_FLOWER`` 出现在可执行动作里才说明该单能求花。
        """
        from app.db_manager import db_manager
        from utils.xianyu_seller_api import (
            XianyuSellerAPI,
            SellerApiError,
            parse_sold_order,
        )

        rate_content = db_manager.get_system_setting('auto_rate_content') or '感谢惠顾，欢迎下次光临！'
        rated = 0
        flowered = 0

        api = XianyuSellerAPI(self.cookie_id, self.cookies_str)
        try:
            try:
                batch = await api.get_sold_orders(
                    query_code='TRADE_SUCCESS', rows_per_page=50
                )
            except SellerApiError as exc:
                logger.debug(f"【{self.cookie_id}】查询已完结订单失败: {exc}")
                return {'rated': 0, 'flowered': 0}

            for item in batch.get('items') or []:
                parsed = parse_sold_order(item)
                order_id = parsed.get('order_id')
                if not order_id:
                    continue
                actions = parsed.get('trade_actions') or []

                if rate_on and order_id not in self._auto_rated_orders:
                    # sellerRateStatus 为 4 表示已评价过
                    if parsed.get('seller_rate_status') != 4:
                        try:
                            result = await api.create_rate([order_id], feedback=rate_content, rate=1)
                            if result.get('success'):
                                rated += 1
                                logger.info(f"【{self.cookie_id}】订单 {order_id} 已自动评价")
                        except SellerApiError as exc:
                            logger.warning(f"【{self.cookie_id}】订单 {order_id} 评价失败: {exc}")
                    self._auto_rated_orders.add(order_id)

                if flower_on and order_id not in self._auto_flowered_orders:
                    if 'REQUIRE_FLOWER' in actions:
                        try:
                            await api.require_flower(order_id)
                            flowered += 1
                            logger.info(f"【{self.cookie_id}】订单 {order_id} 已发送求花")
                        except SellerApiError as exc:
                            logger.warning(f"【{self.cookie_id}】订单 {order_id} 求花失败: {exc}")
                    self._auto_flowered_orders.add(order_id)

            if api.cookies_str and api.cookies_str != self.cookies_str:
                self.cookies_str = api.cookies_str
        finally:
            await api.close()

        if rated or flowered:
            logger.info(
                f"【{self.cookie_id}】买家互动完成: 评价 {rated} 单，求花 {flowered} 单"
            )
        return {'rated': rated, 'flowered': flowered}


    async def cookie_refresh_loop(self):
        """Cookie刷新定时任务 - 每小时执行一次"""
        try:
            while True:
                try:
                    # 检查账号是否启用
                    from app.cookie_manager import manager as cookie_manager
                    if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                        logger.info(f"【{self.cookie_id}】账号已禁用，停止Cookie刷新循环")
                        break

                    # 检查Cookie刷新功能是否启用
                    if not self.cookie_refresh_enabled:
                        logger.warning(f"【{self.cookie_id}】Cookie刷新功能已禁用，跳过执行")
                        await self._interruptible_sleep(300)  # 5分钟后再检查
                        continue

                    current_time = time.time()
                    if current_time - self.last_cookie_refresh_time >= self.cookie_refresh_interval:
                        # 检查是否在消息接收后的冷却时间内
                        time_since_last_message = current_time - self.last_message_received_time
                        if time_since_last_message < self.message_cookie_refresh_cooldown:
                            remaining_time = self.message_cookie_refresh_cooldown - time_since_last_message
                            remaining_minutes = int(remaining_time // 60)
                            remaining_seconds = int(remaining_time % 60)
                            logger.warning(f"【{self.cookie_id}】收到消息后冷却中，还需等待 {remaining_minutes}分{remaining_seconds}秒 才能执行Cookie刷新")
                        # 检查是否已有Cookie刷新任务在执行
                        elif self.cookie_refresh_lock.locked():
                            logger.warning(f"【{self.cookie_id}】Cookie刷新任务已在执行中，跳过本次触发")
                        else:
                            logger.info(f"【{self.cookie_id}】开始执行Cookie刷新任务...")
                            # 在独立的任务中执行Cookie刷新，避免阻塞主循环
                            asyncio.create_task(self._execute_cookie_refresh(current_time))

                    # 每分钟检查一次是否需要执行
                    await self._interruptible_sleep(60)
                except asyncio.CancelledError:
                    # 收到取消信号，立即退出循环
                    logger.info(f"【{self.cookie_id}】Cookie刷新循环收到取消信号，准备退出")
                    raise
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】Cookie刷新循环失败: {self._safe_str(e)}")
                    # 出错后也等待1分钟再重试，使用可中断的sleep
                    try:
                        await self._interruptible_sleep(60)
                    except asyncio.CancelledError:
                        logger.info(f"【{self.cookie_id}】Cookie刷新循环在重试等待时收到取消信号，准备退出")
                        raise
        except asyncio.CancelledError:
            # 确保CancelledError被正确传播
            logger.info(f"【{self.cookie_id}】Cookie刷新循环已取消，正在退出...")
            raise
        finally:
            # 确保任务能正常结束
            logger.info(f"【{self.cookie_id}】Cookie刷新循环已退出")

    async def _execute_cookie_refresh(self, current_time):
        """独立执行Cookie刷新任务，避免阻塞主循环"""

        # 使用Lock确保原子性，防止重复执行
        async with self.cookie_refresh_lock:
            try:
                logger.info(f"【{self.cookie_id}】开始Cookie刷新任务，暂时暂停心跳以避免连接冲突...")

                # 暂时暂停心跳任务，避免与浏览器操作冲突
                heartbeat_was_running = False
                if self.heartbeat_task and not self.heartbeat_task.done():
                    heartbeat_was_running = True
                    self.heartbeat_task.cancel()
                    logger.warning(f"【{self.cookie_id}】已暂停心跳任务")

                # 为整个Cookie刷新任务添加超时保护（3分钟，缩短时间减少影响）
                success = await asyncio.wait_for(
                    self._refresh_cookies_via_browser(),
                    timeout=180.0  # 3分钟超时，减少对WebSocket的影响
                )

                # 重新启动心跳任务
                if heartbeat_was_running and self.ws and not self.ws.closed:
                    logger.warning(f"【{self.cookie_id}】重新启动心跳任务")
                    self.heartbeat_task = asyncio.create_task(self.heartbeat_loop(self.ws))

                if success:
                    self.last_cookie_refresh_time = current_time
                    logger.info(f"【{self.cookie_id}】Cookie刷新任务完成，心跳已恢复")
                    
                    # 刷新成功后，验证Cookie有效性
                    logger.info(f"【{self.cookie_id}】开始验证刷新后的Cookie有效性...")
                    try:
                        validation_result = await self._verify_cookie_validity()
                        
                        if not validation_result['valid']:
                            logger.warning(f"【{self.cookie_id}】❌ Cookie验证失败: {validation_result['details']}")
                            logger.warning(f"【{self.cookie_id}】检测到Cookie可能无法用于关键API，尝试通过密码登录重新获取...")
                            
                            # 触发密码登录刷新
                            password_refresh_success = await self._try_password_login_refresh("Cookie验证失败(关键API不可用)")
                            
                            if password_refresh_success:
                                logger.info(f"【{self.cookie_id}】✅ 密码登录刷新成功，Cookie已更新")
                            else:
                                logger.warning(f"【{self.cookie_id}】⚠️ 密码登录刷新失败，Cookie可能仍然无效")
                                # 发送通知
                                await self.send_token_refresh_notification(
                                    f"Cookie验证失败且密码登录刷新也失败\n验证详情: {validation_result['details']}",
                                    "cookie_validation_failed"
                                )
                        else:
                            logger.info(f"【{self.cookie_id}】✅ Cookie验证通过: {validation_result['details']}")
                            
                    except Exception as verify_e:
                        logger.error(f"【{self.cookie_id}】Cookie验证过程异常: {self._safe_str(verify_e)}")
                        import traceback
                        logger.error(f"【{self.cookie_id}】详细堆栈:\n{traceback.format_exc()}")
                else:
                    logger.warning(f"【{self.cookie_id}】Cookie刷新任务失败")
                    # 即使失败也要更新时间，避免频繁重试
                    self.last_cookie_refresh_time = current_time

            except asyncio.TimeoutError:
                # 超时也要更新时间，避免频繁重试
                self.last_cookie_refresh_time = current_time
            except Exception as e:
                logger.error(f"【{self.cookie_id}】执行Cookie刷新任务异常: {self._safe_str(e)}")
                # 异常也要更新时间，避免频繁重试
                self.last_cookie_refresh_time = current_time
            finally:
                # 确保心跳任务恢复（如果WebSocket仍然连接）
                if (self.ws and not self.ws.closed and
                    (not self.heartbeat_task or self.heartbeat_task.done())):
                    logger.info(f"【{self.cookie_id}】Cookie刷新完成，心跳任务正常运行")
                    self.heartbeat_task = asyncio.create_task(self.heartbeat_loop(self.ws))

                # 清空消息接收标志，允许下次正常执行Cookie刷新
                self.last_message_received_time = 0
                logger.warning(f"【{self.cookie_id}】Cookie刷新完成，已清空消息接收标志")



    def enable_cookie_refresh(self, enabled: bool = True):
        """启用或禁用Cookie刷新功能"""
        self.cookie_refresh_enabled = enabled
        status = "启用" if enabled else "禁用"
        logger.info(f"【{self.cookie_id}】Cookie刷新功能已{status}")


    async def refresh_cookies_from_qr_login(self, qr_cookies_str: str, cookie_id: str = None, user_id: int = None):
        """使用扫码登录获取的cookie访问指定界面获取真实cookie并存入数据库

        Args:
            qr_cookies_str: 扫码登录获取的cookie字符串
            cookie_id: 可选的cookie ID，如果不提供则使用当前实例的cookie_id
            user_id: 可选的用户ID，如果不提供则使用当前实例的user_id

        Returns:
            bool: 成功返回True，失败返回False
        """
        playwright = None
        browser = None
        target_cookie_id = cookie_id or self.cookie_id
        target_user_id = user_id or self.user_id

        try:
            import asyncio
            from playwright.async_api import async_playwright
            from utils.xianyu_utils import trans_cookies

            logger.info(f"【{target_cookie_id}】开始使用扫码登录cookie获取真实cookie...")
            logger.info(f"【{target_cookie_id}】扫码cookie长度: {len(qr_cookies_str)}")

            # 解析扫码登录的cookie
            qr_cookies_dict = trans_cookies(qr_cookies_str)
            logger.info(
                f"【{target_cookie_id}】扫码cookie字段数: {len(qr_cookies_dict)}, "
                f"字段: {sorted(qr_cookies_dict.keys())}"
            )

            # Docker环境下修复asyncio子进程问题
            is_docker = os.getenv('DOCKER_ENV') or os.path.exists('/.dockerenv')

            if is_docker:
                logger.warning(f"【{target_cookie_id}】检测到Docker环境，应用asyncio修复")

                # 创建一个完整的虚拟子进程监视器
                class DummyChildWatcher:
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        pass
                    def is_active(self):
                        return True
                    def add_child_handler(self, *args, **kwargs):
                        pass
                    def remove_child_handler(self, *args, **kwargs):
                        pass
                    def attach_loop(self, *args, **kwargs):
                        pass
                    def close(self):
                        pass
                    def __del__(self):
                        pass

                # 创建自定义事件循环策略
                class DockerEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
                    def get_child_watcher(self):
                        return DummyChildWatcher()

                # 临时设置策略
                old_policy = asyncio.get_event_loop_policy()
                asyncio.set_event_loop_policy(DockerEventLoopPolicy())

                try:
                    # 添加超时机制，避免无限等待
                    playwright = await asyncio.wait_for(
                        async_playwright().start(),
                        timeout=30.0  # 30秒超时
                    )
                    logger.warning(f"【{target_cookie_id}】Docker环境下Playwright启动成功")
                except asyncio.TimeoutError:
                    logger.error(f"【{target_cookie_id}】Docker环境下Playwright启动超时")
                    return False
                finally:
                    # 恢复原策略
                    asyncio.set_event_loop_policy(old_policy)
            else:
                # 非Docker环境，正常启动（也添加超时保护）
                try:
                    playwright = await asyncio.wait_for(
                        async_playwright().start(),
                        timeout=30.0  # 30秒超时
                    )
                except asyncio.TimeoutError:
                    logger.error(f"【{target_cookie_id}】Playwright启动超时")
                    return False

            # 启动浏览器（参照商品搜索的配置）
            browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-features=TranslateUI',
                '--disable-ipc-flooding-protection',
                '--disable-extensions',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--hide-scrollbars',
                '--mute-audio',
                '--no-default-browser-check',
                '--no-pings'
            ]

            # 在Docker环境中添加额外参数
            if os.getenv('DOCKER_ENV'):
                browser_args.extend([
                    # '--single-process',  # 注释掉，避免多用户并发时的进程冲突和资源泄漏
                    '--disable-background-networking',
                    '--disable-client-side-phishing-detection',
                    '--disable-hang-monitor',
                    '--disable-popup-blocking',
                    '--disable-prompt-on-repost',
                    '--disable-web-resources',
                    '--metrics-recording-only',
                    '--safebrowsing-disable-auto-update',
                    '--enable-automation',
                    '--password-store=basic',
                    '--use-mock-keychain'
                ])

            # 优先使用Playwright自带Chromium；未安装时回退到系统Chrome/Edge。
            bundled_executable = playwright.chromium.executable_path
            system_browser_candidates = [
                ("Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                ("Chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
                ("Edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
                ("Edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            ]
            launch_options = {
                'headless': True,
                'args': browser_args,
            }

            if os.path.exists(bundled_executable):
                logger.info(
                    f"【{target_cookie_id}】使用Playwright Chromium: {bundled_executable}"
                )
            else:
                system_browser = next(
                    (
                        (name, path)
                        for name, path in system_browser_candidates
                        if os.path.exists(path)
                    ),
                    None
                )
                if not system_browser:
                    logger.error(
                        f"【{target_cookie_id}】未找到可用浏览器。"
                        f"Playwright预期路径不存在: {bundled_executable}；"
                        "系统Chrome/Edge也未找到。请执行: python -m playwright install chromium"
                    )
                    return False

                browser_name, browser_path = system_browser
                launch_options['executable_path'] = browser_path
                logger.warning(
                    f"【{target_cookie_id}】Playwright Chromium未安装，"
                    f"回退使用系统{browser_name}: {browser_path}"
                )

            logger.info(f"【{target_cookie_id}】正在启动无头浏览器")
            browser = await browser_limit.launch_browser(playwright, launch_options, "扫码登录")
            logger.info(f"【{target_cookie_id}】无头浏览器启动成功")

            # 创建浏览器上下文
            context_options = {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
            }

            # 使用标准窗口大小
            context_options['viewport'] = {'width': 1920, 'height': 1080}

            context = await browser.new_context(**context_options)

            # 设置扫码登录获取的Cookie
            cookies = []
            for cookie_pair in qr_cookies_str.split('; '):
                if '=' in cookie_pair:
                    name, value = cookie_pair.split('=', 1)
                    cookies.append({
                        'name': name.strip(),
                        'value': value.strip(),
                        'domain': '.goofish.com',
                        'path': '/'
                    })

            await context.add_cookies(cookies)
            logger.info(
                f"【{target_cookie_id}】已设置 {len(cookies)} 个扫码Cookie到浏览器，"
                f"字段: {sorted(cookie['name'] for cookie in cookies)}"
            )

            # 创建页面
            page = await context.new_page()

            # 等待页面准备
            await asyncio.sleep(0.1)

            # 访问指定页面获取真实cookie
            target_url = "https://www.goofish.com/im"
            logger.info(f"【{target_cookie_id}】访问页面获取真实cookie: {target_url}")

            # 使用更灵活的页面访问策略
            try:
                # 首先尝试较短超时
                await page.goto(target_url, wait_until='domcontentloaded', timeout=15000)
                logger.info(f"【{target_cookie_id}】页面访问成功")
            except Exception as e:
                if 'timeout' in str(e).lower():
                    logger.warning(f"【{target_cookie_id}】页面访问超时，尝试降级策略...")
                    try:
                        # 降级策略：只等待基本加载
                        await page.goto(target_url, wait_until='load', timeout=20000)
                        logger.info(f"【{target_cookie_id}】页面访问成功（降级策略）")
                    except Exception as e2:
                        logger.warning(f"【{target_cookie_id}】降级策略也失败，尝试最基本访问...")
                        # 最后尝试：不等待任何加载完成
                        await page.goto(target_url, timeout=25000)
                        logger.info(f"【{target_cookie_id}】页面访问成功（最基本策略）")
                else:
                    raise e

            # 等待页面完全加载并获取真实cookie
            logger.info(f"【{target_cookie_id}】页面加载完成，等待获取真实cookie...")
            await asyncio.sleep(2)

            # 执行一次刷新以确保获取最新的cookie
            logger.info(f"【{target_cookie_id}】执行页面刷新获取最新cookie...")
            try:
                await page.reload(wait_until='domcontentloaded', timeout=12000)
                logger.info(f"【{target_cookie_id}】页面刷新成功")
            except Exception as e:
                if 'timeout' in str(e).lower():
                    logger.warning(f"【{target_cookie_id}】页面刷新超时，使用降级策略...")
                    await page.reload(wait_until='load', timeout=15000)
                    logger.info(f"【{target_cookie_id}】页面刷新成功（降级策略）")
                else:
                    raise e
            await asyncio.sleep(1)

            # 获取更新后的真实Cookie
            logger.info(f"【{target_cookie_id}】获取真实Cookie...")
            updated_cookies = await context.cookies()

            # 构造新的Cookie字典
            real_cookies_dict = {}
            for cookie in updated_cookies:
                real_cookies_dict[cookie['name']] = cookie['value']

            # 生成真实cookie字符串
            real_cookies_str = '; '.join([f"{k}={v}" for k, v in real_cookies_dict.items()])

            logger.info(f"【{target_cookie_id}】真实Cookie已获取，包含 {len(real_cookies_dict)} 个字段")

            # 检查关键字段
            important_keys = ['unb', '_m_h5_tk', '_m_h5_tk_enc', 'cookie2', 't', 'sgcookie', 'cna']
            key_status = []
            for key in important_keys:
                if key in real_cookies_dict:
                    val = real_cookies_dict[key]
                    key_status.append(f"{key}=存在({len(str(val)) if val else 0})")
                else:
                    key_status.append(f"{key}=缺失")
            logger.info(
                f"【{target_cookie_id}】真实Cookie摘要: 长度={len(real_cookies_str)}, "
                f"字段={sorted(real_cookies_dict.keys())}, 关键字段=[{', '.join(key_status)}]"
            )

            # 打印原始扫码Cookie对比
            logger.info(f"【{target_cookie_id}】=== 扫码Cookie对比 ===")
            logger.info(f"【{target_cookie_id}】扫码Cookie长度: {len(qr_cookies_str)}")
            logger.info(f"【{target_cookie_id}】扫码Cookie字段数: {len(qr_cookies_dict)}")
            logger.info(f"【{target_cookie_id}】真实Cookie长度: {len(real_cookies_str)}")
            logger.info(f"【{target_cookie_id}】真实Cookie字段数: {len(real_cookies_dict)}")
            logger.info(f"【{target_cookie_id}】长度增加: {len(real_cookies_str) - len(qr_cookies_str)} 字符")
            logger.info(f"【{target_cookie_id}】字段增加: {len(real_cookies_dict) - len(qr_cookies_dict)} 个")

            # 检查Cookie变化
            changed_cookies = []
            new_cookies = []
            for name, new_value in real_cookies_dict.items():
                old_value = qr_cookies_dict.get(name)
                if old_value is None:
                    new_cookies.append(name)
                elif old_value != new_value:
                    changed_cookies.append(name)

            # 显示Cookie变化统计
            if changed_cookies:
                logger.info(f"【{target_cookie_id}】发生变化的Cookie字段 ({len(changed_cookies)}个): {', '.join(changed_cookies)}")
            if new_cookies:
                logger.info(f"【{target_cookie_id}】新增的Cookie字段 ({len(new_cookies)}个): {', '.join(new_cookies)}")
            if not changed_cookies and not new_cookies:
                logger.info(f"【{target_cookie_id}】Cookie无变化")

            # 保存真实Cookie到数据库
            from app.db_manager import db_manager
            
            # 检查是否为新账号
            existing_cookie = db_manager.get_cookie_details(target_cookie_id)
            if existing_cookie:
                # 现有账号，使用 update_cookie_account_info 避免覆盖其他字段（如 pause_duration, remark 等）
                success = db_manager.update_cookie_account_info(target_cookie_id, cookie_value=real_cookies_str)
            else:
                # 新账号，使用 save_cookie
                success = db_manager.save_cookie(target_cookie_id, real_cookies_str, target_user_id)

            if success:
                logger.info(f"【{target_cookie_id}】真实Cookie已成功保存到数据库")

                # 如果当前实例的cookie_id匹配，更新实例的cookie信息
                if target_cookie_id == self.cookie_id:
                    self.cookies = real_cookies_dict
                    self.cookies_str = real_cookies_str
                    logger.info(f"【{target_cookie_id}】已更新当前实例的Cookie信息")

                # 更新扫码登录Cookie刷新时间标志
                self.last_qr_cookie_refresh_time = time.time()
                logger.info(f"【{target_cookie_id}】已更新扫码登录Cookie刷新时间标志，_refresh_cookies_via_browser将等待{self.qr_cookie_refresh_cooldown//60}分钟后执行")

                return True
            else:
                logger.error(f"【{target_cookie_id}】保存真实Cookie到数据库失败")
                return False

        except Exception as e:
            logger.error(f"【{target_cookie_id}】使用扫码cookie获取真实cookie失败: {self._safe_str(e)}")
            return False
        finally:
            # 确保资源清理
            try:
                # 先关闭浏览器，再关闭Playwright（顺序很重要）
                if browser:
                    try:
                        await asyncio.wait_for(browser.close(), timeout=5.0)
                        logger.warning(f"【{target_cookie_id}】浏览器关闭完成")
                    except asyncio.TimeoutError:
                        logger.warning(f"【{target_cookie_id}】浏览器关闭超时（5秒），资源可能未完全释放")
                        # 尝试取消浏览器相关的任务
                        try:
                            if hasattr(browser, '_connection'):
                                browser._connection = None
                        except:
                            pass
                    except Exception as e:
                        logger.warning(f"【{target_cookie_id}】关闭浏览器时出错: {self._safe_str(e)}")
                
                # Playwright关闭：使用更短的超时，超时后立即放弃
                if playwright:
                    try:
                        logger.warning(f"【{target_cookie_id}】正在关闭Playwright...")
                        await asyncio.wait_for(playwright.stop(), timeout=2.0)
                        logger.warning(f"【{target_cookie_id}】Playwright关闭完成")
                    except asyncio.TimeoutError:
                        logger.warning(f"【{target_cookie_id}】Playwright关闭超时（2秒），进程可能仍在运行")
                        logger.warning(f"【{target_cookie_id}】提示：如果后续Playwright启动失败，可能需要手动清理残留进程")
                        # 尝试清理Playwright的内部状态
                        try:
                            # 取消可能正在运行的Playwright任务
                            if hasattr(playwright, '_transport'):
                                playwright._transport = None
                        except:
                            pass
                    except Exception as e:
                        logger.warning(f"【{target_cookie_id}】关闭Playwright时出错: {self._safe_str(e)}")
            except Exception as cleanup_e:
                logger.warning(f"【{target_cookie_id}】清理浏览器资源时出错: {self._safe_str(cleanup_e)}")

    async def _refresh_cookies_via_browser_page(self, current_cookies_str: str):
        """使用当前cookie访问指定页面获取真实cookie并更新
        
        这是令牌过期时的备用刷新方案，类似于refresh_cookies_from_qr_login，
        但使用当前的cookie而不是扫码登录的cookie。

        Args:
            current_cookies_str: 当前的cookie字符串

        Returns:
            bool: 成功返回True，失败返回False
        """
        playwright = None
        browser = None

        try:
            import asyncio
            from playwright.async_api import async_playwright
            from utils.xianyu_utils import trans_cookies

            logger.info(f"【{self.cookie_id}】开始使用当前cookie访问指定页面获取真实cookie...")
            logger.info(f"【{self.cookie_id}】当前cookie长度: {len(current_cookies_str)}")

            # 解析当前的cookie
            current_cookies_dict = trans_cookies(current_cookies_str)
            logger.info(f"【{self.cookie_id}】当前cookie字段数: {len(current_cookies_dict)}")

            # Docker环境下修复asyncio子进程问题
            is_docker = os.getenv('DOCKER_ENV') or os.path.exists('/.dockerenv')

            if is_docker:
                logger.warning(f"【{self.cookie_id}】检测到Docker环境，应用asyncio修复")

                # 创建一个完整的虚拟子进程监视器
                class DummyChildWatcher:
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        pass
                    def is_active(self):
                        return True
                    def add_child_handler(self, *args, **kwargs):
                        pass
                    def remove_child_handler(self, *args, **kwargs):
                        pass
                    def attach_loop(self, *args, **kwargs):
                        pass
                    def close(self):
                        pass
                    def __del__(self):
                        pass

                # 创建自定义事件循环策略
                class DockerEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
                    def get_child_watcher(self):
                        return DummyChildWatcher()

                # 临时设置策略
                old_policy = asyncio.get_event_loop_policy()
                asyncio.set_event_loop_policy(DockerEventLoopPolicy())

                try:
                    # 添加超时机制，避免无限等待
                    playwright = await asyncio.wait_for(
                        async_playwright().start(),
                        timeout=30.0  # 30秒超时
                    )
                    logger.warning(f"【{self.cookie_id}】Docker环境下Playwright启动成功")
                except asyncio.TimeoutError:
                    logger.error(f"【{self.cookie_id}】Docker环境下Playwright启动超时")
                    return False
                finally:
                    # 恢复原策略
                    asyncio.set_event_loop_policy(old_policy)
            else:
                # 非Docker环境，正常启动（也添加超时保护）
                try:
                    playwright = await asyncio.wait_for(
                        async_playwright().start(),
                        timeout=30.0  # 30秒超时
                    )
                except asyncio.TimeoutError:
                    logger.error(f"【{self.cookie_id}】Playwright启动超时")
                    return False

            # 启动浏览器（参照商品搜索的配置）
            browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-features=TranslateUI',
                '--disable-ipc-flooding-protection',
                '--disable-extensions',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--hide-scrollbars',
                '--mute-audio',
                '--no-default-browser-check',
                '--no-pings'
            ]

            # 在Docker环境中添加额外参数
            if os.getenv('DOCKER_ENV'):
                browser_args.extend([
                    '--disable-background-networking',
                    '--disable-client-side-phishing-detection',
                    '--disable-hang-monitor',
                    '--disable-popup-blocking',
                    '--disable-prompt-on-repost',
                    '--disable-web-resources',
                    '--metrics-recording-only',
                    '--safebrowsing-disable-auto-update',
                    '--enable-automation',
                    '--password-store=basic',
                    '--use-mock-keychain'
                ])

            launch_options = self._get_playwright_launch_options(
                playwright,
                browser_args,
                "浏览器页面刷新"
            )
            browser = await browser_limit.launch_browser(playwright, launch_options, "浏览器页面刷新")

            # 创建浏览器上下文
            context_options = {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
            }

            # 使用标准窗口大小
            context_options['viewport'] = {'width': 1920, 'height': 1080}

            context = await browser.new_context(**context_options)

            # 设置当前的Cookie
            cookies = []
            for cookie_pair in current_cookies_str.split('; '):
                if '=' in cookie_pair:
                    name, value = cookie_pair.split('=', 1)
                    cookies.append({
                        'name': name.strip(),
                        'value': value.strip(),
                        'domain': '.goofish.com',
                        'path': '/'
                    })

            await context.add_cookies(cookies)
            logger.info(f"【{self.cookie_id}】已设置 {len(cookies)} 个当前Cookie到浏览器")

            # 创建页面
            page = await context.new_page()

            # 等待页面准备
            await asyncio.sleep(0.1)

            # 访问指定页面获取真实cookie
            target_url = "https://www.goofish.com/im"
            logger.info(f"【{self.cookie_id}】访问页面获取真实cookie: {target_url}")

            # 使用更灵活的页面访问策略
            try:
                # 首先尝试较短超时
                await page.goto(target_url, wait_until='domcontentloaded', timeout=15000)
                logger.info(f"【{self.cookie_id}】页面访问成功")
            except Exception as e:
                if 'timeout' in str(e).lower():
                    logger.warning(f"【{self.cookie_id}】页面访问超时，尝试降级策略...")
                    try:
                        # 降级策略：只等待基本加载
                        await page.goto(target_url, wait_until='load', timeout=20000)
                        logger.info(f"【{self.cookie_id}】页面访问成功（降级策略）")
                    except Exception as e2:
                        logger.warning(f"【{self.cookie_id}】降级策略也失败，尝试最基本访问...")
                        # 最后尝试：不等待任何加载完成
                        await page.goto(target_url, timeout=25000)
                        logger.info(f"【{self.cookie_id}】页面访问成功（最基本策略）")
                else:
                    raise e

            # 等待页面完全加载并获取真实cookie
            logger.info(f"【{self.cookie_id}】页面加载完成，等待获取真实cookie...")
            await asyncio.sleep(2)

            # 执行一次刷新以确保获取最新的cookie
            logger.info(f"【{self.cookie_id}】执行页面刷新获取最新cookie...")
            try:
                await page.reload(wait_until='domcontentloaded', timeout=12000)
                logger.info(f"【{self.cookie_id}】页面刷新成功")
            except Exception as e:
                if 'timeout' in str(e).lower():
                    logger.warning(f"【{self.cookie_id}】页面刷新超时，使用降级策略...")
                    await page.reload(wait_until='load', timeout=15000)
                    logger.info(f"【{self.cookie_id}】页面刷新成功（降级策略）")
                else:
                    raise e
            await asyncio.sleep(1)

            # 获取更新后的真实Cookie
            logger.info(f"【{self.cookie_id}】获取真实Cookie...")
            updated_cookies = await context.cookies()

            # 构造新的Cookie字典
            real_cookies_dict = {}
            for cookie in updated_cookies:
                real_cookies_dict[cookie['name']] = cookie['value']

            # 生成真实cookie字符串
            real_cookies_str = '; '.join([f"{k}={v}" for k, v in real_cookies_dict.items()])

            logger.info(f"【{self.cookie_id}】真实Cookie已获取，包含 {len(real_cookies_dict)} 个字段")
            logger.info(
                f"【{self.cookie_id}】真实Cookie采集完成: "
                f"fields={len(real_cookies_dict)}, length={len(real_cookies_str)}"
            )
            # 检查关键字段
            important_keys = ['unb', '_m_h5_tk', '_m_h5_tk_enc', 'cookie2', 't', 'sgcookie', 'cna']
            logger.info(f"【{self.cookie_id}】关键字段检查:")
            for key in important_keys:
                if key in real_cookies_dict:
                    val = real_cookies_dict[key]
                    logger.info(f"【{self.cookie_id}】  ✅ {key}: {'存在' if val else '为空'} (长度: {len(str(val)) if val else 0})")
                else:
                    logger.info(f"【{self.cookie_id}】  ❌ {key}: 缺失")

            # 检查Cookie是否有有效更新
            changed_cookies = []
            new_cookies = []
            for name, new_value in real_cookies_dict.items():
                old_value = current_cookies_dict.get(name)
                if old_value is None:
                    new_cookies.append(name)
                elif old_value != new_value:
                    changed_cookies.append(name)

            if not changed_cookies and not new_cookies:
                logger.warning(f"【{self.cookie_id}】Cookie无变化，可能当前cookie已失效")
                return False

            logger.info(f"【{self.cookie_id}】发生变化的Cookie字段 ({len(changed_cookies)}个): {', '.join(changed_cookies[:10])}")
            if new_cookies:
                logger.info(f"【{self.cookie_id}】新增的Cookie字段 ({len(new_cookies)}个): {', '.join(new_cookies[:10])}")

            # 更新Cookie并重启任务
            logger.info(f"【{self.cookie_id}】开始更新Cookie并重启任务...")
            update_success = await self._update_cookies_and_restart(real_cookies_str)

            if update_success:
                logger.info(f"【{self.cookie_id}】通过访问指定页面成功更新Cookie并重启任务")
                return True
            else:
                logger.error(f"【{self.cookie_id}】更新Cookie或重启任务失败")
                return False

        except Exception as e:
            logger.error(f"【{self.cookie_id}】使用当前cookie访问指定页面获取真实cookie失败: {self._safe_str(e)}")
            return False
        finally:
            # 确保资源清理
            try:
                # 先关闭浏览器，再关闭Playwright（顺序很重要）
                if browser:
                    try:
                        await asyncio.wait_for(browser.close(), timeout=5.0)
                        logger.warning(f"【{self.cookie_id}】浏览器关闭完成")
                    except asyncio.TimeoutError:
                        logger.warning(f"【{self.cookie_id}】浏览器关闭超时（5秒），资源可能未完全释放")
                    except Exception as e:
                        logger.warning(f"【{self.cookie_id}】关闭浏览器时出错: {self._safe_str(e)}")
                
                # Playwright关闭：使用更短的超时，超时后立即放弃
                if playwright:
                    try:
                        logger.warning(f"【{self.cookie_id}】正在关闭Playwright...")
                        await asyncio.wait_for(playwright.stop(), timeout=2.0)
                        logger.warning(f"【{self.cookie_id}】Playwright关闭完成")
                    except asyncio.TimeoutError:
                        logger.warning(f"【{self.cookie_id}】Playwright关闭超时（2秒），进程可能仍在运行")
                    except Exception as e:
                        logger.warning(f"【{self.cookie_id}】关闭Playwright时出错: {self._safe_str(e)}")
            except Exception as cleanup_e:
                logger.warning(f"【{self.cookie_id}】清理浏览器资源时出错: {self._safe_str(cleanup_e)}")

    def reset_qr_cookie_refresh_flag(self):
        """重置扫码登录Cookie刷新标志，允许立即执行_refresh_cookies_via_browser"""
        self.last_qr_cookie_refresh_time = 0
        logger.info(f"【{self.cookie_id}】已重置扫码登录Cookie刷新标志")

    def get_qr_cookie_refresh_remaining_time(self) -> int:
        """获取扫码登录Cookie刷新剩余冷却时间（秒）"""
        current_time = time.time()
        time_since_qr_refresh = current_time - self.last_qr_cookie_refresh_time
        remaining_time = max(0, self.qr_cookie_refresh_cooldown - time_since_qr_refresh)
        return int(remaining_time)

    async def _refresh_cookies_via_browser(self, triggered_by_refresh_token: bool = False):
        """通过浏览器访问指定页面刷新Cookie

        Args:
            triggered_by_refresh_token: 是否由refresh_token方法触发，如果是True则设置browser_cookie_refreshed标志
        """


        playwright = None
        browser = None
        try:
            import asyncio
            from playwright.async_api import async_playwright

            # 检查是否需要等待扫码登录Cookie刷新的冷却时间
            current_time = time.time()
            time_since_qr_refresh = current_time - self.last_qr_cookie_refresh_time

            if time_since_qr_refresh < self.qr_cookie_refresh_cooldown:
                remaining_time = self.qr_cookie_refresh_cooldown - time_since_qr_refresh
                remaining_minutes = int(remaining_time // 60)
                remaining_seconds = int(remaining_time % 60)

                logger.info(f"【{self.cookie_id}】扫码登录Cookie刷新冷却中，还需等待 {remaining_minutes}分{remaining_seconds}秒")
                logger.info(f"【{self.cookie_id}】跳过本次浏览器Cookie刷新")
                return False

            logger.info(f"【{self.cookie_id}】开始通过浏览器刷新Cookie...")
            logger.info(f"【{self.cookie_id}】刷新前Cookie长度: {len(self.cookies_str)}")
            logger.info(f"【{self.cookie_id}】刷新前Cookie字段数: {len(self.cookies)}")

            # Docker环境下修复asyncio子进程问题
            is_docker = os.getenv('DOCKER_ENV') or os.path.exists('/.dockerenv')

            if is_docker:
                logger.warning(f"【{self.cookie_id}】检测到Docker环境，应用asyncio修复")

                # 创建一个完整的虚拟子进程监视器
                class DummyChildWatcher:
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        pass
                    def is_active(self):
                        return True
                    def add_child_handler(self, *args, **kwargs):
                        pass
                    def remove_child_handler(self, *args, **kwargs):
                        pass
                    def attach_loop(self, *args, **kwargs):
                        pass
                    def close(self):
                        pass
                    def __del__(self):
                        pass

                # 创建自定义事件循环策略
                class DockerEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
                    def get_child_watcher(self):
                        return DummyChildWatcher()

                # 临时设置策略
                old_policy = asyncio.get_event_loop_policy()
                asyncio.set_event_loop_policy(DockerEventLoopPolicy())

                try:
                    # 添加超时机制，避免无限等待
                    playwright = await asyncio.wait_for(
                        async_playwright().start(),
                        timeout=30.0  # 30秒超时
                    )
                    logger.warning(f"【{self.cookie_id}】Docker环境下Playwright启动成功")
                except asyncio.TimeoutError:
                    logger.error(f"【{self.cookie_id}】Docker环境下Playwright启动超时")
                    return False
                finally:
                    # 恢复原策略
                    asyncio.set_event_loop_policy(old_policy)
            else:
                # 非Docker环境，正常启动（也添加超时保护）
                try:
                    playwright = await asyncio.wait_for(
                        async_playwright().start(),
                        timeout=30.0  # 30秒超时
                    )
                except asyncio.TimeoutError:
                    logger.error(f"【{self.cookie_id}】Playwright启动超时")
                    return False

            # 启动浏览器（参照商品搜索的配置）
            browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-features=TranslateUI',
                '--disable-ipc-flooding-protection',
                '--disable-extensions',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--hide-scrollbars',
                '--mute-audio',
                '--no-default-browser-check',
                '--no-pings'
            ]

            # 在Docker环境中添加额外参数
            if os.getenv('DOCKER_ENV'):
                browser_args.extend([
                    # '--single-process',  # 注释掉，避免多用户并发时的进程冲突和资源泄漏
                    '--disable-background-networking',
                    '--disable-client-side-phishing-detection',
                    '--disable-hang-monitor',
                    '--disable-popup-blocking',
                    '--disable-prompt-on-repost',
                    '--disable-web-resources',
                    '--metrics-recording-only',
                    '--safebrowsing-disable-auto-update',
                    '--enable-automation',
                    '--password-store=basic',
                    '--use-mock-keychain'
                ])

            launch_options = self._get_playwright_launch_options(
                playwright,
                browser_args,
                "定时Cookie刷新"
            )
            browser = await browser_limit.launch_browser(playwright, launch_options, "定时Cookie刷新")

            # 创建浏览器上下文
            context_options = {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
            }

            # 使用标准窗口大小
            context_options['viewport'] = {'width': 1920, 'height': 1080}

            context = await browser.new_context(**context_options)

            # 设置当前Cookie
            cookies = []
            for cookie_pair in self.cookies_str.split('; '):
                if '=' in cookie_pair:
                    name, value = cookie_pair.split('=', 1)
                    cookies.append({
                        'name': name.strip(),
                        'value': value.strip(),
                        'domain': '.goofish.com',
                        'path': '/'
                    })

            await context.add_cookies(cookies)
            logger.info(f"【{self.cookie_id}】已设置 {len(cookies)} 个Cookie到浏览器")

            # 创建页面
            page = await context.new_page()

            # 等待页面准备
            await asyncio.sleep(0.1)

            # 访问指定页面
            target_url = "https://www.goofish.com/im"
            logger.info(f"【{self.cookie_id}】访问页面: {target_url}")

            # 使用更灵活的页面访问策略
            try:
                # 首先尝试较短超时
                await page.goto(target_url, wait_until='domcontentloaded', timeout=15000)
                logger.info(f"【{self.cookie_id}】页面访问成功")
            except Exception as e:
                if 'timeout' in str(e).lower():
                    logger.warning(f"【{self.cookie_id}】页面访问超时，尝试降级策略...")
                    try:
                        # 降级策略：只等待基本加载
                        await page.goto(target_url, wait_until='load', timeout=20000)
                        logger.info(f"【{self.cookie_id}】页面访问成功（降级策略）")
                    except Exception as e2:
                        logger.warning(f"【{self.cookie_id}】降级策略也失败，尝试最基本访问...")
                        # 最后尝试：不等待任何加载完成
                        await page.goto(target_url, timeout=25000)
                        logger.info(f"【{self.cookie_id}】页面访问成功（最基本策略）")
                else:
                    raise e

            # Cookie刷新模式：执行两次刷新
            logger.info(f"【{self.cookie_id}】页面加载完成，开始刷新...")
            await asyncio.sleep(1)

            # 第一次刷新 - 带重试机制
            logger.info(f"【{self.cookie_id}】执行第一次刷新...")
            try:
                await page.reload(wait_until='domcontentloaded', timeout=12000)
                logger.info(f"【{self.cookie_id}】第一次刷新成功")
            except Exception as e:
                if 'timeout' in str(e).lower():
                    logger.warning(f"【{self.cookie_id}】第一次刷新超时，使用降级策略...")
                    await page.reload(wait_until='load', timeout=15000)
                    logger.info(f"【{self.cookie_id}】第一次刷新成功（降级策略）")
                else:
                    raise e
            await asyncio.sleep(1)

            # 第二次刷新 - 带重试机制
            logger.info(f"【{self.cookie_id}】执行第二次刷新...")
            try:
                await page.reload(wait_until='domcontentloaded', timeout=12000)
                logger.info(f"【{self.cookie_id}】第二次刷新成功")
            except Exception as e:
                if 'timeout' in str(e).lower():
                    logger.warning(f"【{self.cookie_id}】第二次刷新超时，使用降级策略...")
                    await page.reload(wait_until='load', timeout=15000)
                    logger.info(f"【{self.cookie_id}】第二次刷新成功（降级策略）")
                else:
                    raise e
            await asyncio.sleep(1)

            # Cookie刷新模式：正常更新Cookie
            logger.info(f"【{self.cookie_id}】获取更新后的Cookie...")
            updated_cookies = await context.cookies()
            
            # 获取并打印当前页面标题
            page_title = await page.title()
            logger.info(f"【{self.cookie_id}】当前页面标题: {page_title}")

            # 构造新的Cookie字典
            new_cookies_dict = {}
            for cookie in updated_cookies:
                new_cookies_dict[cookie['name']] = cookie['value']

            # 检查Cookie变化
            changed_cookies = []
            new_cookies = []
            for name, new_value in new_cookies_dict.items():
                old_value = self.cookies.get(name)
                if old_value is None:
                    new_cookies.append(name)
                elif old_value != new_value:
                    changed_cookies.append(name)

            # 更新self.cookies和cookies_str
            self.cookies.update(new_cookies_dict)
            self.cookies_str = '; '.join([f"{k}={v}" for k, v in self.cookies.items()])

            logger.info(f"【{self.cookie_id}】Cookie已更新，包含 {len(new_cookies_dict)} 个字段")

            # 显示Cookie变化统计
            if changed_cookies:
                logger.info(f"【{self.cookie_id}】发生变化的Cookie字段 ({len(changed_cookies)}个): {', '.join(changed_cookies)}")
            if new_cookies:
                logger.info(f"【{self.cookie_id}】新增的Cookie字段 ({len(new_cookies)}个): {', '.join(new_cookies)}")
            if not changed_cookies and not new_cookies:
                logger.info(f"【{self.cookie_id}】Cookie无变化")

            logger.info(
                f"【{self.cookie_id}】更新后Cookie字段名: "
                f"{', '.join(sorted(new_cookies_dict.keys()))}"
            )

            # 只记录关键字段是否存在，不记录任何Cookie值或片段。
            important_cookies = ['_m_h5_tk', '_m_h5_tk_enc', 'cookie2', 't', 'sgcookie', 'unb', 'uc1', 'uc3', 'uc4']
            present_important_cookies = [
                cookie_name
                for cookie_name in important_cookies
                if cookie_name in new_cookies_dict
            ]
            logger.info(
                f"【{self.cookie_id}】关键Cookie字段检查: "
                f"{', '.join(present_important_cookies) or '无'}"
            )

            # 更新数据库中的Cookie
            await self.update_config_cookies()

            # 只有当由refresh_token触发时才设置浏览器Cookie刷新成功标志
            if triggered_by_refresh_token:
                self.browser_cookie_refreshed = True
                logger.info(f"【{self.cookie_id}】由refresh_token触发，浏览器Cookie刷新成功标志已设置为True")

                # 兜底：直接在此处触发实例重启，避免外层协程在返回后被取消导致未重启
                try:
                    # 标记"刷新流程内已触发重启"，供外层去重
                    self.restarted_in_browser_refresh = True

                    logger.info(f"【{self.cookie_id}】Cookie刷新成功，准备重启实例...(via _refresh_cookies_via_browser)")
                    await self._restart_instance()
                    
                    # ⚠️ _restart_instance() 已触发重启，当前任务即将被取消
                    # 不要等待或执行耗时操作
                    logger.info(f"【{self.cookie_id}】重启请求已触发(via _refresh_cookies_via_browser)")
                    
                    # 标记重启标志（无需主动关闭WS，重启由管理器处理）
                    self.connection_restart_flag = True
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】兜底重启失败: {self._safe_str(e)}")
            else:
                logger.info(f"【{self.cookie_id}】由定时任务触发，不设置浏览器Cookie刷新成功标志")

            logger.info(f"【{self.cookie_id}】Cookie刷新完成")
            return True

        except Exception as e:
            logger.error(f"【{self.cookie_id}】通过浏览器刷新Cookie失败: {self._safe_str(e)}")
            return False
        finally:
            # 异步关闭浏览器：创建清理任务并等待完成，确保资源正确释放
            close_task = None
            try:
                if browser or playwright:
                    # 创建关闭任务
                    close_task = asyncio.create_task(
                        self._async_close_browser(browser, playwright)
                    )
                    logger.info(f"【{self.cookie_id}】浏览器异步关闭任务已启动")
                    
                    # 等待关闭任务完成，但设置超时避免阻塞太久
                    try:
                        await asyncio.wait_for(close_task, timeout=15.0)
                        logger.info(f"【{self.cookie_id}】浏览器关闭任务已完成")
                    except asyncio.TimeoutError:
                        logger.warning(f"【{self.cookie_id}】浏览器关闭任务超时（15秒），强制继续")
                        # 取消任务，避免资源泄漏
                        if not close_task.done():
                            close_task.cancel()
                            try:
                                await close_task
                            except (asyncio.CancelledError, Exception):
                                pass
                    except Exception as wait_e:
                        logger.warning(f"【{self.cookie_id}】等待浏览器关闭任务时出错: {self._safe_str(wait_e)}")
                        # 确保任务被取消
                        if close_task and not close_task.done():
                            close_task.cancel()
                            try:
                                await close_task
                            except (asyncio.CancelledError, Exception):
                                pass
            except Exception as cleanup_e:
                logger.warning(f"【{self.cookie_id}】创建浏览器关闭任务时出错: {self._safe_str(cleanup_e)}")
                # 如果创建任务失败，尝试直接关闭
                if browser or playwright:
                    try:
                        await self._force_close_resources(browser, playwright)
                    except Exception:
                        pass

    async def _async_close_browser(self, browser, playwright):
        """异步关闭：正常关闭，超时后强制关闭"""
        try:
            logger.info(f"【{self.cookie_id}】开始异步关闭浏览器...")  # 改为info级别
            
            # 正常关闭，设置超时
            await asyncio.wait_for(
                self._normal_close_resources(browser, playwright),
                timeout=10.0
            )
            logger.info(f"【{self.cookie_id}】浏览器正常关闭完成")  # 改为info级别
            
        except asyncio.TimeoutError:
            logger.warning(f"【{self.cookie_id}】正常关闭超时，开始强制关闭...")
            await self._force_close_resources(browser, playwright)
            
        except Exception as e:
            logger.warning(f"【{self.cookie_id}】异步关闭时出错，强制关闭: {self._safe_str(e)}")
            await self._force_close_resources(browser, playwright)

    async def _normal_close_resources(self, browser, playwright):
        """正常关闭资源：浏览器+Playwright短超时关闭"""
        try:
            # 先关闭浏览器，再关闭Playwright
            if browser:
                try:
                    # 关闭浏览器，设置超时
                    await asyncio.wait_for(browser.close(), timeout=5.0)
                    logger.info(f"【{self.cookie_id}】浏览器关闭完成")
                except asyncio.TimeoutError:
                    logger.warning(f"【{self.cookie_id}】浏览器关闭超时，尝试强制关闭")
                    try:
                        # 尝试强制关闭
                        if hasattr(browser, '_connection'):
                            browser._connection.dispose()
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(f"【{self.cookie_id}】关闭浏览器时出错: {e}")
            
            # 关闭Playwright：使用短超时，如果超时就放弃
            if playwright:
                try:
                    logger.info(f"【{self.cookie_id}】正在关闭Playwright...")
                    # 增加超时时间，确保Playwright有足够时间清理资源
                    await asyncio.wait_for(playwright.stop(), timeout=5.0)
                    logger.info(f"【{self.cookie_id}】Playwright关闭完成")
                except asyncio.TimeoutError:
                    logger.warning(f"【{self.cookie_id}】Playwright关闭超时，将自动清理")
                    # 尝试强制清理Playwright的内部连接
                    try:
                        if hasattr(playwright, '_connection'):
                            playwright._connection.dispose()
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(f"【{self.cookie_id}】关闭Playwright时出错: {e}")
                
        except Exception as e:
            logger.error(f"【{self.cookie_id}】正常关闭时出现异常: {e}")
            raise

    
    async def _force_close_resources(self, browser, playwright):
        """强制关闭资源：强制关闭浏览器+Playwright超时等待"""
        try:
            logger.warning(f"【{self.cookie_id}】开始强制关闭资源...")
            
            # 强制关闭浏览器+Playwright，设置短超时
            force_tasks = []
            if browser:
                force_tasks.append(asyncio.wait_for(browser.close(), timeout=3.0))
            if playwright:
                force_tasks.append(asyncio.wait_for(playwright.stop(), timeout=3.0))
            
            if force_tasks:
                # 使用gather执行，所有失败都会被忽略
                results = await asyncio.gather(*force_tasks, return_exceptions=True)
                
                # 检查是否有超时或异常，尝试强制清理
                for i, result in enumerate(results):
                    if isinstance(result, (asyncio.TimeoutError, Exception)):
                        resource_name = "浏览器" if i == 0 and browser else "Playwright"
                        logger.warning(f"【{self.cookie_id}】{resource_name}强制关闭失败，尝试直接清理连接")
                        try:
                            if i == 0 and browser and hasattr(browser, '_connection'):
                                browser._connection.dispose()
                            elif playwright and hasattr(playwright, '_connection'):
                                playwright._connection.dispose()
                        except Exception:
                            pass
                
                logger.info(f"【{self.cookie_id}】强制关闭完成")
            else:
                logger.info(f"【{self.cookie_id}】没有需要强制关闭的资源")
            
        except Exception as e:
            logger.warning(f"【{self.cookie_id}】强制关闭时出现异常（已忽略）: {e}")

    async def send_msg_once(self, toid, item_id, text):
        headers = {
            "Cookie": self.cookies_str,
            "Host": "wss-goofish.dingtalk.com",
            "Connection": "Upgrade",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Origin": "https://www.goofish.com",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        # 兼容不同版本的websockets库
        try:
            async with websockets.connect(
                self.base_url,
                extra_headers=headers
            ) as websocket:
                await self._handle_websocket_connection(websocket, toid, item_id, text)
        except TypeError as e:
            # 安全地检查异常信息
            error_msg = self._safe_str(e)

            if "extra_headers" in error_msg:
                logger.warning("websockets库不支持extra_headers参数，使用兼容模式")
                # 使用兼容模式，通过subprotocols传递部分头信息
                async with websockets.connect(
                    self.base_url,
                    additional_headers=headers
                ) as websocket:
                    await self._handle_websocket_connection(websocket, toid, item_id, text)
            else:
                raise

    async def _create_websocket_connection(self, headers):
        """创建WebSocket连接，兼容不同版本的websockets库"""
        import websockets

        # 获取websockets版本用于调试
        websockets_version = getattr(websockets, '__version__', '未知')
        logger.warning(f"websockets库版本: {websockets_version}")

        try:
            # 尝试使用extra_headers参数
            return websockets.connect(
                self.base_url,
                extra_headers=headers
            )
        except Exception as e:
            # 捕获所有异常类型，不仅仅是TypeError
            error_msg = self._safe_str(e)
            logger.warning(f"extra_headers参数失败: {error_msg}")

            if "extra_headers" in error_msg or "unexpected keyword argument" in error_msg:
                logger.warning("websockets库不支持extra_headers参数，尝试additional_headers")
                # 使用additional_headers参数（较新版本）
                try:
                    return websockets.connect(
                        self.base_url,
                        additional_headers=headers
                    )
                except Exception as e2:
                    error_msg2 = self._safe_str(e2)
                    logger.warning(f"additional_headers参数失败: {error_msg2}")

                    if "additional_headers" in error_msg2 or "unexpected keyword argument" in error_msg2:
                        # 如果都不支持，则不传递headers
                        logger.warning("websockets库不支持headers参数，使用基础连接模式")
                        return websockets.connect(self.base_url)
                    else:
                        raise e2
            else:
                raise e

    async def _handle_websocket_connection(self, websocket, toid, item_id, text):
        """处理WebSocket连接的具体逻辑"""
        await self.init(websocket)
        await self.create_chat(websocket, toid, item_id)
        async for message in websocket:
            try:
                logger.info(f"【{self.cookie_id}】message: {message}")
                message = json.loads(message)
                cid = message["body"]["singleChatConversation"]["cid"]
                cid = cid.split('@')[0]
                await self.send_msg(websocket, cid, toid, text)
                logger.info(f'【{self.cookie_id}】send message')
                return
            except Exception as e:
                pass

    def is_chat_message(self, message):
        """判断是否为用户聊天消息"""
        try:
            return (
                isinstance(message, dict)
                and "1" in message
                and isinstance(message["1"], dict)
                and "10" in message["1"]
                and isinstance(message["1"]["10"], dict)
                and "reminderContent" in message["1"]["10"]
            )
        except Exception:
            return False

    def is_sync_package(self, message_data):
        """判断是否为同步包消息"""
        try:
            return (
                isinstance(message_data, dict)
                and "body" in message_data
                and "syncPushPackage" in message_data["body"]
                and "data" in message_data["body"]["syncPushPackage"]
                and len(message_data["body"]["syncPushPackage"]["data"]) > 0
            )
        except Exception:
            return False

    async def create_session(self):
        """创建aiohttp session"""
        if not self.session:
            # 创建带有cookies和headers的session
            headers = DEFAULT_HEADERS.copy()
            headers['cookie'] = self.cookies_str

            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            )

    async def close_session(self):
        """关闭aiohttp session"""
        if self.session:
            await self.session.close()
            self.session = None

    async def get_api_reply(self, msg_time, user_url, send_user_id, send_user_name, item_id, send_message, chat_id):
        """调用API获取回复消息"""
        try:
            if not self.session:
                await self.create_session()

            api_config = AUTO_REPLY.get('api', {})
            timeout = aiohttp.ClientTimeout(total=api_config.get('timeout', 10))

            payload = {
                "cookie_id": self.cookie_id,
                "msg_time": msg_time,
                "user_url": user_url,
                "send_user_id": send_user_id,
                "send_user_name": send_user_name,
                "item_id": item_id,
                "send_message": send_message,
                "chat_id": chat_id
            }

            async with self.session.post(
                api_config.get('url', 'http://localhost:8080/xianyu/reply'),
                json=payload,
                timeout=timeout
            ) as response:
                result = await response.json()

                # 将code转换为字符串进行比较，或者直接用数字比较
                if str(result.get('code')) == '200' or result.get('code') == 200:
                    send_msg = result.get('data', {}).get('send_msg')
                    if send_msg:
                        # 格式化消息中的占位符
                        return send_msg.format(
                            send_user_id=payload['send_user_id'],
                            send_user_name=payload['send_user_name'],
                            send_message=payload['send_message']
                        )
                    else:
                        logger.warning("API返回成功但无回复消息")
                        return None
                else:
                    logger.warning(f"API返回错误: {result.get('msg', '未知错误')}")
                    return None

        except asyncio.TimeoutError:
            logger.error("API调用超时")
            return None
        except Exception as e:
            logger.error(f"调用API出错: {self._safe_str(e)}")
            return None

    async def _handle_message_with_semaphore(self, message_data, websocket):
        """带信号量的消息处理包装器，防止并发任务过多"""
        async with self.message_semaphore:
            self.active_message_tasks += 1
            try:
                await self.handle_message(message_data, websocket)
            finally:
                self.active_message_tasks -= 1
                # 定期记录活跃任务数（每100个任务记录一次）
                if self.active_message_tasks % 100 == 0 and self.active_message_tasks > 0:
                    logger.info(f"【{self.cookie_id}】当前活跃消息处理任务数: {self.active_message_tasks}")

    def _extract_message_id(self, message_data: dict) -> str:
        """
        从消息数据中提取消息ID，用于去重
        
        Args:
            message_data: 原始消息数据
            
        Returns:
            消息ID字符串，如果无法提取则返回None
        """
        try:
            # 尝试从 message['1']['10']['bizTag'] 中提取 messageId
            if isinstance(message_data, dict) and "1" in message_data:
                message_1 = message_data.get("1")
                if isinstance(message_1, dict) and "10" in message_1:
                    message_10 = message_1.get("10")
                    if isinstance(message_10, dict) and "bizTag" in message_10:
                        biz_tag = message_10.get("bizTag", "")
                        if isinstance(biz_tag, str):
                            # bizTag 是 JSON 字符串，格式如: '{"sourceId":"S:1","messageId":"984f323c719d4cd0a7b993a0769a33b6"}'
                            try:
                                import json
                                biz_tag_dict = json.loads(biz_tag)
                                if isinstance(biz_tag_dict, dict) and "messageId" in biz_tag_dict:
                                    return biz_tag_dict.get("messageId")
                            except (json.JSONDecodeError, TypeError):
                                pass
                        
                        # 如果 bizTag 解析失败，尝试从 extJson 中提取
                        if "extJson" in message_10:
                            ext_json = message_10.get("extJson", "")
                            if isinstance(ext_json, str):
                                try:
                                    import json
                                    ext_json_dict = json.loads(ext_json)
                                    if isinstance(ext_json_dict, dict) and "messageId" in ext_json_dict:
                                        return ext_json_dict.get("messageId")
                                except (json.JSONDecodeError, TypeError):
                                    pass
        except Exception as e:
            logger.debug(f"【{self.cookie_id}】提取消息ID失败: {self._safe_str(e)}")
        
        return None

    def _add_reply_decision_log(self, message_data: dict, **fields):
        try:
            from app.db_manager import db_manager
            return db_manager.add_auto_reply_log(
                cookie_id=self.cookie_id,
                source_message_id=self._extract_message_id(message_data),
                **fields,
            )
        except Exception as error:
            logger.error(f"【{self.cookie_id}】记录自动回复决策失败: {self._safe_str(error)}")
            return None

    def _update_reply_decision_log(self, log_id, **fields):
        if not log_id:
            return
        try:
            from app.db_manager import db_manager
            db_manager.update_auto_reply_log(log_id, **fields)
        except Exception as error:
            logger.error(f"【{self.cookie_id}】更新自动回复决策失败: {self._safe_str(error)}")

    def _find_reply_keyword(self, message: str, item_id: str = None):
        try:
            from app.db_manager import db_manager
            keywords = db_manager.get_keywords_with_type(self.cookie_id) or []
            normalized_message = (message or "").casefold()
            for item_only in (True, False):
                for keyword_data in keywords:
                    keyword_item_id = keyword_data.get("item_id")
                    if item_only and keyword_item_id != item_id:
                        continue
                    if not item_only and keyword_item_id:
                        continue
                    keyword = (keyword_data.get("keyword") or "").strip()
                    if keyword and keyword.casefold() in normalized_message:
                        return keyword
        except Exception as error:
            logger.debug(f"【{self.cookie_id}】读取命中关键词失败: {self._safe_str(error)}")
        return None

    async def _schedule_debounced_reply(self, chat_id: str, message_data: dict, websocket, 
                                       send_user_name: str, send_user_id: str, send_message: str,
                                       item_id: str, msg_time: str):
        """
        调度防抖回复：如果用户连续发送消息，等待用户停止发送后再回复最后一条消息
        
        Args:
            chat_id: 聊天ID
            message_data: 原始消息数据
            websocket: WebSocket连接
            send_user_name: 发送者用户名
            send_user_id: 发送者用户ID
            send_message: 消息内容
            item_id: 商品ID
            msg_time: 消息时间
        """
        # 提取消息ID并检查是否已处理
        message_id = self._extract_message_id(message_data)
        # 如果没有 messageId，使用备用标识（chat_id + send_message + 时间戳）
        if not message_id:
            try:
                # 尝试从消息数据中提取时间戳
                create_time = 0
                if isinstance(message_data, dict) and "1" in message_data:
                    message_1 = message_data.get("1")
                    if isinstance(message_1, dict):
                        create_time = message_1.get("5", 0)
                # 使用组合键作为备用标识
                message_id = f"{chat_id}_{send_message}_{create_time}"
            except Exception:
                # 如果提取失败，使用当前时间戳
                message_id = f"{chat_id}_{send_message}_{int(time.time() * 1000)}"
        
        async with self.processed_message_ids_lock:
            current_time = time.time()
            
            # 检查消息是否已处理且未过期
            if message_id in self.processed_message_ids:
                last_process_time = self.processed_message_ids[message_id]
                time_elapsed = current_time - last_process_time
                
                # 如果消息处理时间未超过1小时，跳过
                if time_elapsed < self.message_expire_time:
                    remaining_time = int(self.message_expire_time - time_elapsed)
                    logger.warning(f"【{self.cookie_id}】消息ID {message_id[:50]}... 已处理过，距离可重复回复还需 {remaining_time} 秒")
                    return
                else:
                    # 超过1小时，可以重新处理
                    logger.info(f"【{self.cookie_id}】消息ID {message_id[:50]}... 已超过 {int(time_elapsed/60)} 分钟，允许重新回复")
            
            # 标记消息ID为已处理（更新或添加时间戳）
            self.processed_message_ids[message_id] = current_time
            
            # 定期清理过期的消息ID
            if len(self.processed_message_ids) > self.processed_message_ids_max_size:
                # 清理超过1小时的旧记录
                expired_ids = [
                    msg_id for msg_id, timestamp in self.processed_message_ids.items()
                    if current_time - timestamp > self.message_expire_time
                ]
                
                for msg_id in expired_ids:
                    del self.processed_message_ids[msg_id]
                
                logger.info(f"【{self.cookie_id}】已清理 {len(expired_ids)} 个过期消息ID")
                
                # 如果清理后仍然过大，删除最旧的一半
                if len(self.processed_message_ids) > self.processed_message_ids_max_size:
                    sorted_ids = sorted(self.processed_message_ids.items(), key=lambda x: x[1])
                    remove_count = len(sorted_ids) // 2
                    for msg_id, _ in sorted_ids[:remove_count]:
                        del self.processed_message_ids[msg_id]
                    logger.info(f"【{self.cookie_id}】消息ID去重字典过大，已清理 {remove_count} 个最旧记录")
        
        async with self.message_debounce_lock:
            # 如果该chat_id已有防抖任务，取消它
            if chat_id in self.message_debounce_tasks:
                old_task = self.message_debounce_tasks[chat_id].get('task')
                if old_task and not old_task.done():
                    old_task.cancel()
                    logger.warning(f"【{self.cookie_id}】取消chat_id {chat_id} 的旧防抖任务")
            
            # 更新最后一条消息信息
            current_timer = time.time()
            self.message_debounce_tasks[chat_id] = {
                'last_message': {
                    'message_data': message_data,
                    'websocket': websocket,
                    'send_user_name': send_user_name,
                    'send_user_id': send_user_id,
                    'send_message': send_message,
                    'item_id': item_id,
                    'msg_time': msg_time
                },
                'timer': current_timer
            }
            
            # 创建新的防抖任务
            async def debounce_task():
                saved_timer = current_timer  # 保存创建任务时的时间戳
                try:
                    # 等待防抖延迟时间
                    await asyncio.sleep(self.message_debounce_delay)
                    
                    # 检查是否仍然是最新的消息（防止在等待期间有新消息）
                    async with self.message_debounce_lock:
                        if chat_id not in self.message_debounce_tasks:
                            return
                        
                        debounce_info = self.message_debounce_tasks[chat_id]
                        # 检查时间戳是否匹配（确保这是最新的消息）
                        if saved_timer != debounce_info['timer']:
                            logger.warning(f"【{self.cookie_id}】chat_id {chat_id} 在防抖期间有新消息，跳过旧消息处理")
                            return
                        
                        # 获取最后一条消息
                        last_msg = debounce_info['last_message']
                        
                        # 从防抖任务中移除
                        del self.message_debounce_tasks[chat_id]
                    
                    # 处理最后一条消息
                    logger.info(f"【{self.cookie_id}】防抖延迟结束，开始处理chat_id {chat_id} 的最后一条消息: {last_msg['send_message'][:30]}...")
                    await self._process_chat_message_reply(
                        last_msg['message_data'],
                        last_msg['websocket'],
                        last_msg['send_user_name'],
                        last_msg['send_user_id'],
                        last_msg['send_message'],
                        last_msg['item_id'],
                        chat_id,
                        last_msg['msg_time']
                    )
                    
                except asyncio.CancelledError:
                    logger.warning(f"【{self.cookie_id}】chat_id {chat_id} 的防抖任务被取消")
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】处理防抖回复时发生错误: {self._safe_str(e)}")
                    # 确保从防抖任务中移除
                    async with self.message_debounce_lock:
                        if chat_id in self.message_debounce_tasks:
                            del self.message_debounce_tasks[chat_id]
            
            task = self._create_tracked_task(debounce_task())
            self.message_debounce_tasks[chat_id]['task'] = task
            logger.warning(f"【{self.cookie_id}】为chat_id {chat_id} 创建防抖任务，延迟 {self.message_debounce_delay} 秒")

    async def _process_chat_message_reply(self, message_data: dict, websocket, send_user_name: str,
                                         send_user_id: str, send_message: str, item_id: str,
                                         chat_id: str, msg_time: str):
        """
        处理聊天消息的回复逻辑（从handle_message中提取出来的核心回复逻辑）
        
        Args:
            message_data: 原始消息数据
            websocket: WebSocket连接
            send_user_name: 发送者用户名
            send_user_id: 发送者用户ID
            send_message: 消息内容
            item_id: 商品ID
            chat_id: 聊天ID
            msg_time: 消息时间
        """
        log_id = None
        reply_send_failed = False
        log_context = {
            "chat_id": chat_id,
            "item_id": item_id,
            "sender_user_id": send_user_id,
            "sender_user_name": send_user_name,
            "source_message": send_message,
        }
        try:

            from app.db_manager import db_manager
            matched_filter = db_manager.matches_message_filter(
                self.cookie_id, send_message, "skip_reply"
            )
            if matched_filter:
                self._add_reply_decision_log(
                    message_data,
                    **log_context,
                    process_status="skipped",
                    decision_reason="skip_reply_filter",
                    reply_strategy="none",
                    matched_keyword=matched_filter,
                    send_status="unknown",
                )
                logger.info(
                    f"[{msg_time}] 【{self.cookie_id}】消息命中过滤规则“{matched_filter}”，跳过自动回复"
                )
                return

            # 自动回复消息
            if not AUTO_REPLY.get('enabled', True):
                self._add_reply_decision_log(
                    message_data,
                    **log_context,
                    process_status="skipped",
                    decision_reason="auto_reply_disabled",
                    reply_strategy="none",
                    send_status="unknown",
                )
                logger.info(f"[{msg_time}] 【{self.cookie_id}】【系统】自动回复已禁用")
                return

            # 检查该chat_id是否处于暂停状态
            if pause_manager.is_chat_paused(chat_id, self.cookie_id):
                remaining_time = pause_manager.get_remaining_pause_time(chat_id, self.cookie_id)
                remaining_minutes = remaining_time // 60
                remaining_seconds = remaining_time % 60
                self._add_reply_decision_log(
                    message_data,
                    **log_context,
                    process_status="skipped",
                    decision_reason="chat_paused",
                    reply_strategy="none",
                    send_status="unknown",
                )
                logger.info(f"[{msg_time}] 【{self.cookie_id}】【系统】chat_id {chat_id} 自动回复已暂停，剩余时间: {remaining_minutes}分{remaining_seconds}秒")
                return

            # 构造用户URL
            user_url = f'https://www.goofish.com/personal?userId={send_user_id}'

            reply = None
            reply_strategy = "none"
            matched_keyword = None
            # 判断是否启用API回复
            if AUTO_REPLY.get('api', {}).get('enabled', False):
                reply = await self.get_api_reply(
                    msg_time, user_url, send_user_id, send_user_name,
                    item_id, send_message, chat_id
                )
                if reply:
                    reply_strategy = "api"
                if not reply:
                    logger.error(f"[{msg_time}] 【API调用失败】用户: {send_user_name} (ID: {send_user_id}), 商品({item_id}): {send_message}")

            # 记录回复来源
            reply_source = 'API'  # 默认假设是API回复

            # 如果API回复失败或未启用API，按新的优先级顺序处理
            if not reply:
                # 1. 首先尝试关键词匹配（传入商品ID）
                reply = await self.get_keyword_reply(send_user_name, send_user_id, send_message, item_id)
                if reply == "EMPTY_REPLY":
                    # 匹配到关键词但回复内容为空，不进行任何回复
                    matched_keyword = self._find_reply_keyword(send_message, item_id)
                    self._add_reply_decision_log(
                        message_data,
                        **log_context,
                        process_status="skipped",
                        decision_reason="empty_reply",
                        reply_strategy="keyword",
                        matched_keyword=matched_keyword,
                        send_status="unknown",
                    )
                    logger.info(f"[{msg_time}] 【{self.cookie_id}】匹配到空回复关键词，跳过自动回复")
                    return
                elif reply:
                    reply_source = '关键词'  # 标记为关键词回复
                    reply_strategy = "keyword"
                    matched_keyword = self._find_reply_keyword(send_message, item_id)
                else:
                    # 2. 关键词匹配失败，如果AI开关打开，尝试AI回复
                    reply = await self.get_ai_reply(send_user_name, send_user_id, send_message, item_id, chat_id)
                    if reply:
                        reply_source = 'AI'  # 标记为AI回复
                        reply_strategy = "ai"
                    else:
                        # 3. 最后使用默认回复
                        default_reply_result = await self.get_default_reply(send_user_name, send_user_id, send_message, chat_id, item_id)
                        if default_reply_result == "EMPTY_REPLY":
                            # 默认回复内容为空，不进行任何回复
                            self._add_reply_decision_log(
                                message_data,
                                **log_context,
                                process_status="skipped",
                                decision_reason="empty_reply",
                                reply_strategy="default",
                                send_status="unknown",
                            )
                            logger.info(f"[{msg_time}] 【{self.cookie_id}】默认回复内容为空，跳过自动回复")
                            return
                        
                        # 处理默认回复（可能包含图片和文字）
                        if default_reply_result and isinstance(default_reply_result, dict):
                            reply_source = '默认'  # 标记为默认回复
                            reply_strategy = "default"
                            default_image_url = default_reply_result.get('image_url')
                            default_text = default_reply_result.get('text')
                            
                            # 如果存在图片，先发送图片
                            if default_image_url:
                                try:
                                    # 处理图片URL（上传到CDN如果需要）
                                    final_image_url = default_image_url
                                    image_width, image_height = 800, 600  # 默认尺寸
                                    
                                    if self._is_cdn_url(default_image_url):
                                        # 已经是CDN链接，获取真实尺寸
                                        logger.info(f"【{self.cookie_id}】默认回复使用CDN图片: {default_image_url}")
                                        width, height = await self._get_image_size_from_url(default_image_url)
                                        if width and height:
                                            image_width, image_height = width, height
                                    elif default_image_url.startswith('/static/uploads/') or default_image_url.startswith('static/uploads/'):
                                        # 本地图片，需要上传到闲鱼CDN
                                        local_image_path = default_image_url.replace('/static/uploads/', 'static/uploads/')
                                        if os.path.exists(local_image_path):
                                            logger.info(f"【{self.cookie_id}】准备上传默认回复本地图片到闲鱼CDN: {local_image_path}")
                                            
                                            from utils.image_uploader import ImageUploader
                                            uploader = ImageUploader(self.cookies_str)
                                            
                                            async with uploader:
                                                cdn_url = await uploader.upload_image(local_image_path)
                                                if cdn_url:
                                                    logger.info(f"【{self.cookie_id}】默认回复图片上传成功，CDN URL: {cdn_url}")
                                                    final_image_url = cdn_url
                                                    
                                                    # 更新数据库中的图片URL为CDN URL
                                                    await self._update_default_reply_image_url(cdn_url)
                                                    
                                                    # 获取实际图片尺寸
                                                    from utils.image_utils import image_manager
                                                    try:
                                                        actual_width, actual_height = image_manager.get_image_size(local_image_path)
                                                        if actual_width and actual_height:
                                                            image_width, image_height = actual_width, actual_height
                                                    except Exception as e:
                                                        logger.warning(f"【{self.cookie_id}】获取图片尺寸失败，使用默认尺寸: {e}")
                                                else:
                                                    logger.error(f"【{self.cookie_id}】默认回复图片上传失败: {local_image_path}")
                                                    final_image_url = None
                                        else:
                                            logger.error(f"【{self.cookie_id}】默认回复本地图片文件不存在: {local_image_path}")
                                            final_image_url = None
                                    else:
                                        # 其他类型的URL，获取真实尺寸
                                        width, height = await self._get_image_size_from_url(default_image_url)
                                        if width and height:
                                            image_width, image_height = width, height
                                    
                                    # 发送图片
                                    if final_image_url:
                                        log_id = self._add_reply_decision_log(
                                            message_data,
                                            **log_context,
                                            process_status="success",
                                            decision_reason="reply_selected",
                                            reply_strategy=reply_strategy,
                                            reply_text=default_text or final_image_url,
                                            send_status="unknown",
                                        )
                                        await self.send_image_msg(websocket, chat_id, send_user_id, final_image_url, image_width, image_height)
                                        self._update_reply_decision_log(
                                            log_id,
                                            decision_reason="reply_sent",
                                            send_status="success",
                                        )
                                        msg_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                                        logger.info(f"[{msg_time}] 【{reply_source}图片发出】用户: {send_user_name} (ID: {send_user_id}), 商品({item_id}): 图片 {final_image_url}")
                                    else:
                                        reply_send_failed = True
                                        log_id = self._add_reply_decision_log(
                                            message_data,
                                            **log_context,
                                            process_status="failed",
                                            decision_reason="send_failed",
                                            reply_strategy=reply_strategy,
                                            reply_text=default_text or default_image_url,
                                            error_message="默认回复图片不可用或上传失败",
                                            send_status="failed",
                                        )
                                except Exception as e:
                                    reply_send_failed = True
                                    self._update_reply_decision_log(
                                        log_id,
                                        process_status="failed",
                                        decision_reason="send_failed",
                                        error_message=self._safe_str(e),
                                        send_status="failed",
                                    )
                                    logger.error(f"【{self.cookie_id}】默认回复图片发送失败: {self._safe_str(e)}")
                            
                            # 然后发送文字（如果有）
                            if default_text and default_text.strip():
                                reply = default_text
                            else:
                                # 只有图片没有文字，已经发送完毕
                                if default_image_url:
                                    return
                                reply = None
                        else:
                            reply = None

            # 注意：这里只有商品ID，没有标题和详情，根据新的规则不保存到数据库
            # 商品信息会在其他有完整信息的地方保存（如发货规则匹配时）
            # 消息通知已在收到消息时立即发送，此处不再重复发送

            # 如果有回复内容，发送消息
            if reply:
                if not log_id:
                    log_id = self._add_reply_decision_log(
                        message_data,
                        **log_context,
                        process_status="success",
                        decision_reason="reply_selected",
                        reply_strategy=reply_strategy,
                        matched_keyword=matched_keyword,
                        reply_text=reply,
                        send_status="unknown",
                    )
                # 检查是否是图片发送标记
                if reply.startswith("__IMAGE_SEND__"):
                    # 提取图片URL（关键词回复不包含卡券ID）
                    image_url = reply.replace("__IMAGE_SEND__", "")
                    # 发送图片消息
                    try:
                        await self.send_image_msg(websocket, chat_id, send_user_id, image_url)
                        self._update_reply_decision_log(
                            log_id,
                            decision_reason="reply_sent",
                            send_status="success",
                        )
                        # 记录发出的图片消息
                        msg_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                        logger.info(f"[{msg_time}] 【{reply_source}图片发出】用户: {send_user_name} (ID: {send_user_id}), 商品({item_id}): 图片 {image_url}")
                    except Exception as e:
                        # 图片发送失败，发送错误提示
                        self._update_reply_decision_log(
                            log_id,
                            process_status="failed",
                            decision_reason="send_failed",
                            error_message=self._safe_str(e),
                            send_status="failed",
                        )
                        logger.error(f"图片发送失败: {self._safe_str(e)}")
                        await self.send_msg(websocket, chat_id, send_user_id, "抱歉，图片发送失败，请稍后重试。")
                        msg_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                        logger.error(f"[{msg_time}] 【{reply_source}图片发送失败】用户: {send_user_name} (ID: {send_user_id}), 商品({item_id})")
                else:
                    # 普通文本消息
                    await self.send_msg(websocket, chat_id, send_user_id, reply)
                    if not reply_send_failed:
                        self._update_reply_decision_log(
                            log_id,
                            decision_reason="reply_sent",
                            send_status="success",
                        )
                    # 记录发出的消息
                    msg_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    logger.info(f"[{msg_time}] 【{reply_source}发出】用户: {send_user_name} (ID: {send_user_id}), 商品({item_id}): {reply}")
            else:
                self._add_reply_decision_log(
                    message_data,
                    **log_context,
                    process_status="skipped",
                    decision_reason="no_rule_matched",
                    reply_strategy="none",
                    send_status="unknown",
                )
                msg_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                logger.info(f"[{msg_time}] 【{self.cookie_id}】【系统】未找到匹配的回复规则，不回复")
        except Exception as e:
            error_message = self._safe_str(e)
            if log_id:
                self._update_reply_decision_log(
                    log_id,
                    process_status="failed",
                    decision_reason="failed",
                    error_message=error_message,
                    send_status="failed",
                )
            else:
                self._add_reply_decision_log(
                    message_data,
                    **log_context,
                    process_status="failed",
                    decision_reason="failed",
                    reply_strategy="none",
                    error_message=error_message,
                    send_status="failed",
                )
            logger.error(f"处理聊天消息回复时发生错误: {self._safe_str(e)}")

    async def handle_message(self, message_data, websocket):
        """处理所有类型的消息"""
        try:
            # 检查账号是否启用
            from app.cookie_manager import manager as cookie_manager
            if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                logger.warning(f"【{self.cookie_id}】账号已禁用，跳过消息处理")
                return

            # 发送确认消息
            try:
                message = message_data
                ack = {
                    "code": 200,
                    "headers": {
                        "mid": message["headers"]["mid"] if "mid" in message["headers"] else generate_mid(),
                        "sid": message["headers"]["sid"] if "sid" in message["headers"] else '',
                    }
                }
                if 'app-key' in message["headers"]:
                    ack["headers"]["app-key"] = message["headers"]["app-key"]
                if 'ua' in message["headers"]:
                    ack["headers"]["ua"] = message["headers"]["ua"]
                if 'dt' in message["headers"]:
                    ack["headers"]["dt"] = message["headers"]["dt"]
                await websocket.send(json.dumps(ack))
            except Exception as e:
                pass

            # 如果不是同步包消息，直接返回
            if not self.is_sync_package(message_data):
                # 添加调试日志，记录非同步包消息
                logger.debug(f"【{self.cookie_id}】非同步包消息，跳过处理")
                return

            # 获取并解密数据
            sync_data = message_data["body"]["syncPushPackage"]["data"][0]

            # 检查是否有必要的字段
            if "data" not in sync_data:
                logger.warning("同步包中无data字段")
                return

            # 解密数据
            message = None
            try:
                data = sync_data["data"]
                try:
                    data = base64.b64decode(data).decode("utf-8")
                    parsed_data = json.loads(data)
                    # 处理未加密的消息（如系统提示等）
                    msg_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    if isinstance(parsed_data, dict) and 'chatType' in parsed_data:
                        if 'operation' in parsed_data and 'content' in parsed_data['operation']:
                            content = parsed_data['operation']['content']
                            if 'sessionArouse' in content:
                                # 处理系统引导消息
                                logger.info(f"[{msg_time}] 【{self.cookie_id}】【系统】小闲鱼智能提示:")
                                if 'arouseChatScriptInfo' in content['sessionArouse']:
                                    for qa in content['sessionArouse']['arouseChatScriptInfo']:
                                        logger.info(f"  - {qa['chatScrip']}")
                            elif 'contentType' in content:
                                # 其他类型的未加密消息
                                logger.warning(f"[{msg_time}] 【{self.cookie_id}】【系统】其他类型消息: {content}")
                        return
                    else:
                        # 如果不是系统消息，将解析的数据作为message
                        message = parsed_data
                except Exception as e:
                    # 如果JSON解析失败，尝试解密
                    decrypted_data = decrypt(data)
                    message = json.loads(decrypted_data)
            except Exception as e:
                logger.error(f"消息解密失败: {self._safe_str(e)}")
                return

            # 确保message不为空
            if message is None:
                logger.error("消息解析后为空")
                return

            # 确保message是字典类型
            if not isinstance(message, dict):
                logger.error(f"消息格式错误，期望字典但得到: {type(message)}")
                logger.warning(f"消息内容: {message}")
                return

            # 【消息接收标识】记录收到消息的时间，用于控制Cookie刷新
            self.last_message_received_time = time.time()
            logger.warning(f"【{self.cookie_id}】收到消息，更新消息接收时间标识")

            # 【优先处理】尝试获取订单ID并获取订单详情
            order_id = None
            try:
                order_id = self._extract_order_id(message)
                if order_id:
                    msg_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    logger.info(f'[{msg_time}] 【{self.cookie_id}】✅ 检测到订单ID: {order_id}，开始获取订单详情')

                    # 通知订单状态处理器订单ID已提取
                    if self.order_status_handler:
                        logger.info(f"【{self.cookie_id}】准备调用订单状态处理器.on_order_id_extracted: {order_id}")
                        try:
                            self.order_status_handler.on_order_id_extracted(order_id, self.cookie_id, message)
                            logger.info(f"【{self.cookie_id}】订单状态处理器.on_order_id_extracted调用成功: {order_id}")
                        except Exception as e:
                            logger.error(f"【{self.cookie_id}】通知订单状态处理器订单ID提取失败: {self._safe_str(e)}")
                            import traceback
                            logger.error(f"【{self.cookie_id}】详细错误信息: {traceback.format_exc()}")
                    else:
                        logger.warning(f"【{self.cookie_id}】订单状态处理器为None，跳过订单ID提取通知: {order_id}")

                    # 立即获取订单详情信息
                    try:
                        # 先尝试提取用户ID和商品ID用于订单详情获取
                        temp_user_id = None
                        temp_item_id = None

                        # 提取用户ID
                        try:
                            message_1 = message.get("1")
                            if isinstance(message_1, str) and '@' in message_1:
                                temp_user_id = message_1.split('@')[0]
                            elif isinstance(message_1, dict):
                                # 从字典中提取用户ID
                                if "10" in message_1 and isinstance(message_1["10"], dict):
                                    temp_user_id = message_1["10"].get("senderUserId", "unknown_user")
                                else:
                                    temp_user_id = "unknown_user"
                            else:
                                temp_user_id = "unknown_user"
                        except:
                            temp_user_id = "unknown_user"

                        # 提取商品ID
                        try:
                            if "1" in message and isinstance(message["1"], dict) and "10" in message["1"] and isinstance(message["1"]["10"], dict):
                                url_info = message["1"]["10"].get("reminderUrl", "")
                                if isinstance(url_info, str) and "itemId=" in url_info:
                                    temp_item_id = url_info.split("itemId=")[1].split("&")[0]

                            if not temp_item_id:
                                temp_item_id = self.extract_item_id_from_message(message)
                        except:
                            pass

                        # 交易卡片只提供订单号、商品、买家和状态，金额与数量必须走卖家端接口。
                        # 先拉真实成交数据暂存，再落库；接口失败时仅保留状态，不伪造金额。
                        real_values = await self.fetch_order_real_values(order_id)
                        if real_values:
                            self._pending_order_real_values[order_id] = real_values

                        self._save_order_event_snapshot(
                            order_id=order_id,
                            message=message,
                            item_id=temp_item_id,
                            buyer_id=temp_user_id,
                        )

                        # 检查是否已经在获取该订单详情
                        order_detail_lock = self._order_detail_locks[order_id]
                        if order_detail_lock.locked():
                            logger.info(f'[{msg_time}] 【{self.cookie_id}】🔒 订单 {order_id} 详情正在被其他任务获取，跳过重复请求')
                        else:
                            # 调用订单详情获取方法
                            order_detail = await self.fetch_order_detail_info(order_id, temp_item_id, temp_user_id)
                            if order_detail:
                                logger.info(f'[{msg_time}] 【{self.cookie_id}】✅ 订单详情获取成功: {order_id}')
                            else:
                                logger.warning(f'[{msg_time}] 【{self.cookie_id}】⚠️ 订单详情获取失败: {order_id}')

                    except Exception as detail_e:
                        logger.error(f'[{msg_time}] 【{self.cookie_id}】❌ 获取订单详情异常: {self._safe_str(detail_e)}')
                else:
                    logger.warning(f"【{self.cookie_id}】未检测到订单ID")
            except Exception as e:
                logger.error(f"【{self.cookie_id}】提取订单ID失败: {self._safe_str(e)}")

            # 安全地获取用户ID
            user_id = None
            try:
                message_1 = message.get("1")
                if isinstance(message_1, str) and '@' in message_1:
                    user_id = message_1.split('@')[0]
                elif isinstance(message_1, dict):
                    # 如果message['1']是字典，从message["1"]["10"]["senderUserId"]中提取user_id
                    if "10" in message_1 and isinstance(message_1["10"], dict):
                        user_id = message_1["10"].get("senderUserId", "unknown_user")
                    else:
                        user_id = "unknown_user"
                else:
                    user_id = "unknown_user"
            except Exception as e:
                logger.warning(f"提取用户ID失败: {self._safe_str(e)}")
                user_id = "unknown_user"



            # 安全地提取商品ID
            item_id = None
            try:
                if "1" in message and isinstance(message["1"], dict) and "10" in message["1"] and isinstance(message["1"]["10"], dict):
                    url_info = message["1"]["10"].get("reminderUrl", "")
                    if isinstance(url_info, str) and "itemId=" in url_info:
                        item_id = url_info.split("itemId=")[1].split("&")[0]

                # 如果没有提取到，使用辅助方法
                if not item_id:
                    item_id = self.extract_item_id_from_message(message)

                if not item_id:
                    item_id = f"auto_{user_id}_{int(time.time())}"
                    logger.warning(f"无法提取商品ID，使用默认值: {item_id}")

            except Exception as e:
                logger.error(f"提取商品ID时发生错误: {self._safe_str(e)}")
                item_id = f"auto_{user_id}_{int(time.time())}"
            # 处理订单状态消息
            try:
                logger.info(message)
                msg_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

                # 安全地检查订单状态
                red_reminder = None
                if isinstance(message, dict) and "3" in message and isinstance(message["3"], dict):
                    red_reminder = message["3"].get("redReminder")

                if red_reminder == '等待买家付款':
                    user_url = f'https://www.goofish.com/personal?userId={user_id}'
                    logger.info(f'[{msg_time}] 【系统】等待买家 {user_url} 付款')
                    return
                elif red_reminder == '交易关闭':
                    user_url = f'https://www.goofish.com/personal?userId={user_id}'
                    logger.info(f'[{msg_time}] 【系统】买家 {user_url} 交易关闭')
                    return
                elif red_reminder == '等待卖家发货':
                    user_url = f'https://www.goofish.com/personal?userId={user_id}'
                    logger.info(f'[{msg_time}] 【系统】交易成功 {user_url} 等待卖家发货')
                    # return
            except:
                pass

            # 判断是否为聊天消息
            if not self.is_chat_message(message):
                logger.warning("非聊天消息")
                return

            # 处理聊天消息
            try:
                # 安全地提取聊天消息信息
                if not (isinstance(message, dict) and "1" in message and isinstance(message["1"], dict)):
                    logger.error("消息格式错误：缺少必要的字段结构")
                    return

                message_1 = message["1"]
                if not isinstance(message_1.get("10"), dict):
                    logger.error("消息格式错误：缺少消息详情字段")
                    return

                create_time = int(message_1.get("5", 0))
                message_10 = message_1["10"]
                send_user_name = message_10.get("senderNick", message_10.get("reminderTitle", "未知用户"))
                send_user_id = message_10.get("senderUserId", "unknown")
                send_message = message_10.get("reminderContent", "")

                chat_id_raw = message_1.get("2", "")
                chat_id = chat_id_raw.split('@')[0] if '@' in str(chat_id_raw) else str(chat_id_raw)

            except Exception as e:
                logger.error(f"提取聊天消息信息失败: {self._safe_str(e)}")
                return

            # 格式化消息时间
            msg_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(create_time/1000))



            # 判断消息方向
            if send_user_id == self.myid:
                logger.info(f"[{msg_time}] 【手动发出】 商品({item_id}): {send_message}")

                # 暂停该chat_id的自动回复10分钟
                pause_manager.pause_chat(chat_id, self.cookie_id)

                return
            else:
                logger.info(f"[{msg_time}] 【收到】用户: {send_user_name} (ID: {send_user_id}), 商品({item_id}): {send_message}")

                # 🔔 立即发送消息通知（独立于自动回复功能）
                # 检查是否为群组消息，如果是群组消息则跳过通知
                try:
                    session_type = message_10.get("sessionType", "1")  # 默认为个人消息类型
                    if session_type == "30":
                        logger.info(f"📱 检测到群组消息（sessionType=30），跳过消息通知")
                    else:
                        from app.db_manager import db_manager
                        matched_filter = db_manager.matches_message_filter(
                            self.cookie_id, send_message, "skip_notify"
                        )
                        if matched_filter:
                            logger.info(
                                f"📱 消息命中过滤规则“{matched_filter}”，跳过外部通知"
                            )
                        else:
                            # 只对个人消息发送通知
                            await self.send_notification(send_user_name, send_user_id, send_message, item_id, chat_id)
                except Exception as notify_error:
                    logger.error(f"📱 发送消息通知失败: {self._safe_str(notify_error)}")




            # 【优先处理】使用订单状态处理器处理系统消息
            if self.order_status_handler:
                try:
                    # 处理系统消息的订单状态更新
                    try:
                        handled = self.order_status_handler.handle_system_message(
                            message=message,
                            send_message=send_message,
                            cookie_id=self.cookie_id,
                            msg_time=msg_time
                        )
                    except Exception as e:
                        logger.error(f"【{self.cookie_id}】处理系统消息失败: {self._safe_str(e)}")
                        handled = False
                    
                    # 处理红色提醒消息
                    if not handled:
                        try:
                            if isinstance(message, dict) and "3" in message and isinstance(message["3"], dict):
                                red_reminder = message["3"].get("redReminder")
                                user_id = message["3"].get("userId", "unknown")
                                
                                if red_reminder:
                                    try:
                                        self.order_status_handler.handle_red_reminder_message(
                                            message=message,
                                            red_reminder=red_reminder,
                                            user_id=user_id,
                                            cookie_id=self.cookie_id,
                                            msg_time=msg_time
                                        )
                                    except Exception as e:
                                        logger.error(f"【{self.cookie_id}】处理红色提醒消息失败: {self._safe_str(e)}")
                        except Exception as red_e:
                            logger.warning(f"处理红色提醒消息失败: {self._safe_str(red_e)}")
                            
                except Exception as e:
                    logger.error(f"订单状态处理失败: {self._safe_str(e)}")

            # 【优先处理】检查系统消息和自动发货触发消息（不受人工接入暂停影响）
            if self._is_auto_delivery_trigger(send_message):
                logger.info(f'[{msg_time}] 【{self.cookie_id}】检测到自动发货触发消息，进入订单校验')
                await self._handle_auto_delivery(
                    websocket, message, send_user_name, send_user_id,
                    item_id, chat_id, msg_time
                )
                return
            if self._is_system_or_order_event(send_message):
                logger.info(f'[{msg_time}] 【{self.cookie_id}】系统或订单事件绕过普通自动回复')
                return
            if send_message == '[我已拍下，待付款]':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】系统消息不处理')
                return
            elif send_message == '[你关闭了订单，钱款已原路退返]':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】系统消息不处理')
                return
            elif send_message == '[不想宝贝被砍价?设置不砍价回复  ]':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】系统提示信息不处理')
                return 
            elif send_message == 'AI正在帮你回复消息，不错过每笔订单':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】系统提示信息不处理')
                return 
            elif send_message == '发来一条消息':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】系统通知消息不处理')
                return
            elif send_message == '发来一条新消息':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】系统通知消息不处理')
                return
            elif send_message == '[买家确认收货，交易成功]':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】交易完成，触发买家互动')
                await self.send_post_receipt_thanks(websocket, chat_id, send_user_id)
                await self.trigger_buyer_interactions_now('买家确认收货')
                return
            elif send_message == '快给ta一个评价吧~' or send_message == '快给ta一个评价吧～':
                # 闲鱼只在交易完成后才推这条提醒，是个可靠的补充信号：
                # 万一「交易成功」那条消息漏收，靠它也能触发。触发本身有去重。
                logger.info(f'[{msg_time}] 【{self.cookie_id}】收到评价提醒，触发买家互动')
                await self.send_post_receipt_thanks(websocket, chat_id, send_user_id)
                await self.trigger_buyer_interactions_now('评价提醒')
                return
            elif send_message == '卖家人不错？送Ta闲鱼小红花':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】小红花提醒消息不处理')
                return
            elif send_message == '[你已确认收货，交易成功]':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】确认收货，触发买家互动')
                await self.send_post_receipt_thanks(websocket, chat_id, send_user_id)
                await self.trigger_buyer_interactions_now('确认收货')
                return
            elif send_message == '[你已发货]':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】发货确认消息不处理')
                return
            elif send_message == '已发货':
                logger.info(f'[{msg_time}] 【{self.cookie_id}】发货确认消息不处理')
                return
            # 【重要】检查是否为自动发货触发消息 - 即使在人工接入暂停期间也要处理
            elif self._is_auto_delivery_trigger(send_message):
                logger.info(f'[{msg_time}] 【{self.cookie_id}】检测到自动发货触发消息，即使在暂停期间也继续处理: {send_message}')
                # 使用统一的自动发货处理方法
                await self._handle_auto_delivery(websocket, message, send_user_name, send_user_id,
                                               item_id, chat_id, msg_time)
                return
            # 【重要】检查是否为"我已小刀，待刀成"卡片消息 - 即使在人工接入暂停期间也要处理
            elif send_message == '[卡片消息]':
                # 检查是否为"我已小刀，待刀成"的卡片消息
                try:
                    # 从消息中提取卡片内容
                    card_title = None
                    if isinstance(message, dict) and "1" in message and isinstance(message["1"], dict):
                        message_1 = message["1"]
                        if "6" in message_1 and isinstance(message_1["6"], dict):
                            message_6 = message_1["6"]
                            if "3" in message_6 and isinstance(message_6["3"], dict):
                                message_6_3 = message_6["3"]
                                if "5" in message_6_3:
                                    # 解析JSON内容
                                    try:
                                        card_content = json.loads(message_6_3["5"])
                                        if "dxCard" in card_content and "item" in card_content["dxCard"]:
                                            card_item = card_content["dxCard"]["item"]
                                            if "main" in card_item and "exContent" in card_item["main"]:
                                                ex_content = card_item["main"]["exContent"]
                                                card_title = ex_content.get("title", "")
                                    except (json.JSONDecodeError, KeyError) as e:
                                        logger.warning(f"解析卡片消息失败: {e}")

                    # 检查是否为"我已小刀，待刀成"
                    if card_title == "我已小刀，待刀成":
                        logger.info(f'[{msg_time}] 【{self.cookie_id}】【系统】检测到"我已小刀，待刀成"，即使在暂停期间也继续处理')

                        # 检查商品是否属于当前cookies
                        if item_id and item_id != "未知商品":
                            try:
                                from app.db_manager import db_manager
                                item_info = db_manager.get_item_info(self.cookie_id, item_id)
                                if not item_info:
                                    logger.warning(f'[{msg_time}] 【{self.cookie_id}】❌ 商品 {item_id} 不属于当前账号，跳过免拼发货')
                                    return
                                logger.warning(f'[{msg_time}] 【{self.cookie_id}】✅ 商品 {item_id} 归属验证通过')
                            except Exception as e:
                                logger.error(f'[{msg_time}] 【{self.cookie_id}】检查商品归属失败: {self._safe_str(e)}，跳过免拼发货')
                                return

                        # 提取订单ID
                        order_id = self._extract_order_id(message)
                        if not order_id:
                            logger.warning(f'[{msg_time}] 【{self.cookie_id}】❌ 未能提取到订单ID，无法执行免拼发货')
                            return

                        # 更新订单的is_bargain字段为True（标记为小刀订单）
                        try:
                            from app.db_manager import db_manager
                            db_manager.insert_or_update_order(
                                order_id=order_id,
                                item_id=item_id,
                                buyer_id=send_user_id,
                                cookie_id=self.cookie_id,
                                is_bargain=True,
                                chat_id=chat_id
                            )
                            logger.info(f'[{msg_time}] 【{self.cookie_id}】✅ 订单 {order_id} 已标记为小刀订单')
                        except Exception as e:
                            logger.error(f'[{msg_time}] 【{self.cookie_id}】标记小刀订单失败: {self._safe_str(e)}')

                        # 延迟2秒后执行免拼发货
                        logger.info(f'[{msg_time}] 【{self.cookie_id}】延迟2秒后执行免拼发货...')
                        await asyncio.sleep(2)
                        # 调用自动免拼发货方法
                        result = await self.auto_freeshipping(order_id, item_id, send_user_id)
                        if result.get('success'):
                            logger.info(f'[{msg_time}] 【{self.cookie_id}】✅ 自动免拼发货成功')
                        else:
                            logger.warning(f'[{msg_time}] 【{self.cookie_id}】❌ 自动免拼发货失败: {result.get("error", "未知错误")}')
                        await self._handle_auto_delivery(websocket, message, send_user_name, send_user_id,
                                                       item_id, chat_id, msg_time)
                        return
                    else:
                        logger.info(f'[{msg_time}] 【{self.cookie_id}】收到卡片消息，标题: {card_title or "未知"}')
                        # 如果不是目标卡片消息，继续正常处理流程（会受到暂停影响）

                except Exception as e:
                    logger.error(f"处理卡片消息异常: {self._safe_str(e)}")
                    # 如果处理异常，继续正常处理流程（会受到暂停影响）

            # 使用防抖机制处理聊天消息回复
            # 如果用户连续发送消息，等待用户停止发送后再回复最后一条消息
            await self._schedule_debounced_reply(
                chat_id=chat_id,
                message_data=message_data,
                websocket=websocket,
                send_user_name=send_user_name,
                send_user_id=send_user_id,
                send_message=send_message,
                item_id=item_id,
                msg_time=msg_time
            )

        except Exception as e:
            logger.error(f"处理消息时发生错误: {self._safe_str(e)}")
            logger.warning(f"原始消息: {message_data}")

    async def main(self):
        """主程序入口"""
        try:
            logger.info(f"【{self.cookie_id}】开始启动XianyuLive主程序...")
            await self.create_session()  # 创建session
            logger.info(f"【{self.cookie_id}】Session创建完成，开始WebSocket连接循环...")

            while True:
                try:
                    # 检查账号是否启用
                    from app.cookie_manager import manager as cookie_manager
                    if cookie_manager and not cookie_manager.get_cookie_status(self.cookie_id):
                        logger.info(f"【{self.cookie_id}】账号已禁用，停止主循环")
                        break

                    headers = WEBSOCKET_HEADERS.copy()
                    headers['Cookie'] = self.cookies_str

                    # 更新连接状态为连接中
                    self._set_connection_state(ConnectionState.CONNECTING, "准备建立WebSocket连接")
                    logger.info(f"【{self.cookie_id}】WebSocket目标地址: {self.base_url}")

                    # 兼容不同版本的websockets库
                    async with await self._create_websocket_connection(headers) as websocket:
                        self.ws = websocket
                        logger.info(f"【{self.cookie_id}】WebSocket连接建立成功，开始初始化...")

                        try:
                            # 开始初始化
                            await self.init(websocket)
                            logger.info(f"【{self.cookie_id}】WebSocket初始化完成！")

                            # 初始化完成后才设置为已连接状态
                            self._set_connection_state(ConnectionState.CONNECTED, "初始化完成，连接就绪")
                            self.connection_failures = 0
                            self.last_successful_connection = time.time()

                            # 记录后台任务启动前的状态
                            logger.warning(f"【{self.cookie_id}】准备启动后台任务 - 当前状态: heartbeat={self.heartbeat_task}, token_refresh={self.token_refresh_task}, cleanup={self.cleanup_task}, cookie_refresh={self.cookie_refresh_task}")
                            
                            # 如果存在心跳任务引用，先清理（心跳任务依赖WebSocket，必须重启）
                            if self.heartbeat_task:
                                logger.warning(f"【{self.cookie_id}】检测到旧心跳任务引用，先清理...")
                                self._reset_background_tasks()

                            # 启动心跳任务（依赖WebSocket，每次重连都需要重启）
                            logger.info(f"【{self.cookie_id}】启动心跳任务...")
                            self.heartbeat_task = asyncio.create_task(self.heartbeat_loop(websocket))

                            # 启动其他后台任务（不依赖WebSocket，只在首次连接时启动）
                            tasks_started = []
                            
                            if not self.token_refresh_task or self.token_refresh_task.done():
                                logger.info(f"【{self.cookie_id}】启动Token刷新任务...")
                                self.token_refresh_task = asyncio.create_task(self.token_refresh_loop())
                                tasks_started.append("Token刷新")
                            else:
                                logger.info(f"【{self.cookie_id}】Token刷新任务已在运行，跳过启动")

                            if not self.cleanup_task or self.cleanup_task.done():
                                logger.info(f"【{self.cookie_id}】启动暂停记录清理任务...")
                                self.cleanup_task = asyncio.create_task(self.pause_cleanup_loop())
                                tasks_started.append("暂停清理")
                            else:
                                logger.info(f"【{self.cookie_id}】暂停记录清理任务已在运行，跳过启动")

                            if not self.cookie_refresh_task or self.cookie_refresh_task.done():
                                logger.info(f"【{self.cookie_id}】启动Cookie刷新任务...")
                                self.cookie_refresh_task = asyncio.create_task(self.cookie_refresh_loop())
                                tasks_started.append("Cookie刷新")
                            else:
                                logger.info(f"【{self.cookie_id}】Cookie刷新任务已在运行，跳过启动")

                            # 启动商品同步任务
                            if self.item_sync_enabled:
                                if not self.item_sync_task or self.item_sync_task.done():
                                    logger.info(f"【{self.cookie_id}】启动商品同步任务（间隔: {self.item_sync_interval}秒）...")
                                    self.item_sync_task = asyncio.create_task(self.item_sync_loop())
                                    tasks_started.append("商品同步")
                                else:
                                    logger.info(f"【{self.cookie_id}】商品同步任务已在运行，跳过启动")
                            else:
                                logger.info(f"【{self.cookie_id}】商品同步功能未启用")

                            # 启动订单同步任务：补齐监听离线期间产生的订单
                            if not self.order_sync_task or self.order_sync_task.done():
                                logger.info(f"【{self.cookie_id}】启动订单同步任务...")
                                self.order_sync_task = asyncio.create_task(self.order_sync_loop())
                                tasks_started.append("订单同步")
                            else:
                                logger.info(f"【{self.cookie_id}】订单同步任务已在运行，跳过启动")

                            # 连接成功后补齐账号资料。此前只有手动点"刷新"才会拉，
                            # 新登录的账号在列表里没有昵称和头像，看着像没登录成功。
                            if not self._profile_synced:
                                self._profile_synced = True
                                self._create_tracked_task(self._sync_account_profile())

                            # 启动商品擦亮任务（是否真正执行由设置开关决定）
                            if not self.item_polish_task or self.item_polish_task.done():
                                logger.info(f"【{self.cookie_id}】启动商品擦亮任务...")
                                self.item_polish_task = asyncio.create_task(self.item_polish_loop())
                                tasks_started.append("商品擦亮")
                            else:
                                logger.info(f"【{self.cookie_id}】商品擦亮任务已在运行，跳过启动")

                            # 启动发货超时检查：超时未发货会被平台处罚
                            if not self.delivery_timeout_task or self.delivery_timeout_task.done():
                                logger.info(f"【{self.cookie_id}】启动发货超时检查...")
                                self.delivery_timeout_task = asyncio.create_task(self.delivery_timeout_loop())
                                tasks_started.append("发货超时检查")
                            else:
                                logger.info(f"【{self.cookie_id}】发货超时检查已在运行，跳过启动")

                            # 启动买家互动任务（评价/求花，是否执行由开关决定）
                            if not self.buyer_interaction_task or self.buyer_interaction_task.done():
                                logger.info(f"【{self.cookie_id}】启动买家互动任务...")
                                self.buyer_interaction_task = asyncio.create_task(self.buyer_interaction_loop())
                                tasks_started.append("买家互动")
                            else:
                                logger.info(f"【{self.cookie_id}】买家互动任务已在运行，跳过启动")

                            # 记录所有后台任务状态
                            if tasks_started:
                                logger.info(f"【{self.cookie_id}】✅ 新启动的任务: {', '.join(tasks_started)}")
                            item_sync_status = '运行中' if self.item_sync_task and not self.item_sync_task.done() else '已启动' if self.item_sync_enabled else '未启用'
                            order_sync_status = '运行中' if self.order_sync_task and not self.order_sync_task.done() else '已启动'
                            logger.info(f"【{self.cookie_id}】✅ 所有后台任务状态: 心跳(已启动), Token刷新({'运行中' if self.token_refresh_task and not self.token_refresh_task.done() else '已启动'}), 暂停清理({'运行中' if self.cleanup_task and not self.cleanup_task.done() else '已启动'}), Cookie刷新({'运行中' if self.cookie_refresh_task and not self.cookie_refresh_task.done() else '已启动'}), 商品同步({item_sync_status}), 订单同步({order_sync_status})")
                            
                            logger.info(f"【{self.cookie_id}】开始监听WebSocket消息...")
                            logger.info(f"【{self.cookie_id}】WebSocket连接状态正常，等待服务器消息...")
                            logger.info(f"【{self.cookie_id}】准备进入消息循环...")

                            async for message in websocket:
                                logger.info(f"【{self.cookie_id}】收到WebSocket消息: {len(message) if message else 0} 字节")
                                try:
                                    message_data = json.loads(message)

                                    # API requests and push messages share this WebSocket.
                                    # Route request responses by mid before heartbeat/push handling.
                                    if self._resolve_im_response(message_data):
                                        continue

                                    # 处理心跳响应
                                    if await self.handle_heartbeat_response(message_data):
                                        continue

                                    # 处理其他消息
                                    # 使用追踪的异步任务处理消息，防止阻塞后续消息接收
                                    # 并通过信号量控制并发数量，防止内存泄漏
                                    self._create_tracked_task(self._handle_message_with_semaphore(message_data, websocket))

                                except Exception as e:
                                    logger.error(f"处理消息出错: {self._safe_str(e)}")
                                    continue
                        finally:
                            # 确保在退出 async with 块时清理 WebSocket 引用
                            # 注意：async with 会自动关闭 WebSocket，但我们需要清理引用
                            if self.ws == websocket:
                                self.ws = None
                                self._fail_pending_im_requests("闲鱼消息连接已断开")
                                logger.info(f"【{self.cookie_id}】WebSocket连接已退出，引用已清理")

                except Exception as e:
                    error_msg = self._safe_str(e)
                    import traceback
                    error_type = type(e).__name__
                    
                    # 检查是否是 ConnectionClosedError（正常的连接关闭）
                    is_connection_closed = (
                        'ConnectionClosedError' in error_type or 
                        'ConnectionClosed' in error_type or
                        'no close frame received or sent' in error_msg or
                        'IncompleteReadError' in error_type
                    )
                    
                    # 对于连接关闭错误，使用警告级别而不是错误级别
                    if is_connection_closed:
                        logger.warning(f"【{self.cookie_id}】WebSocket连接已关闭 ({self.connection_failures + 1}/{self.max_connection_failures})")
                        logger.warning(f"【{self.cookie_id}】关闭原因: {error_msg}")
                    else:
                        self.connection_failures += 1
                    # 更新连接状态为重连中
                    self._set_connection_state(ConnectionState.RECONNECTING, f"第{self.connection_failures}次失败")
                    logger.error(f"【{self.cookie_id}】WebSocket连接异常 ({self.connection_failures}/{self.max_connection_failures})")
                    logger.error(f"【{self.cookie_id}】异常类型: {error_type}")
                    logger.error(f"【{self.cookie_id}】异常信息: {error_msg}")
                    logger.warning(f"【{self.cookie_id}】异常堆栈:\n{traceback.format_exc()}")
                    
                    # 确保清理 WebSocket 引用
                    if self.ws:
                        try:
                            # 检查 WebSocket 是否仍然打开
                            if hasattr(self.ws, 'close_code') and self.ws.close_code is None:
                                # WebSocket 可能仍然打开，尝试关闭
                                try:
                                    await asyncio.wait_for(self.ws.close(), timeout=2.0)
                                except (asyncio.TimeoutError, Exception):
                                    pass
                        except Exception:
                            pass
                        finally:
                            self.ws = None
                            logger.info(f"【{self.cookie_id}】WebSocket引用已清理")
                    
                    # 对于连接关闭错误，也增加失败计数
                    if is_connection_closed:
                        self.connection_failures += 1
                        # 更新连接状态为重连中
                        self._set_connection_state(ConnectionState.RECONNECTING, f"连接关闭，第{self.connection_failures}次重连")

                    # 检查是否超过最大失败次数
                    if self.connection_failures >= self.max_connection_failures:
                        self._set_connection_state(ConnectionState.FAILED, f"连续失败{self.max_connection_failures}次")
                        logger.warning(f"【{self.cookie_id}】连续失败{self.max_connection_failures}次，尝试通过密码登录刷新Cookie...")
                        
                        try:
                            # 调用统一的密码登录刷新方法
                            refresh_success = await self._try_password_login_refresh(f"连续失败{self.max_connection_failures}次")
                            
                            if refresh_success:
                                logger.info(f"【{self.cookie_id}】✅ 密码登录刷新成功，将重置失败计数并继续重连")
                                # 重置失败计数，因为已经刷新了Cookie
                                self.connection_failures = 0
                                # 更新连接状态
                                self._set_connection_state(ConnectionState.RECONNECTING, "Cookie已刷新，准备重连")
                                # 短暂等待后继续重连循环
                                await asyncio.sleep(2)
                                continue
                            else:
                                logger.warning(f"【{self.cookie_id}】❌ 密码登录刷新失败，将重启实例...")
                        except Exception as refresh_e:
                            logger.error(f"【{self.cookie_id}】密码登录刷新过程异常: {self._safe_str(refresh_e)}")
                            logger.warning(f"【{self.cookie_id}】将重启实例...")
                        
                        # 如果密码登录刷新失败或异常，则重启实例
                        logger.error(f"【{self.cookie_id}】准备重启实例...")
                        self.connection_failures = 0  # 重置失败计数
                        
                        # 先清理后台任务，避免与重启过程冲突
                        logger.info(f"【{self.cookie_id}】重启前先清理后台任务...")
                        try:
                            await asyncio.wait_for(
                                self._cancel_background_tasks(),
                                timeout=8.0  # 给足够时间让任务响应
                            )
                            logger.info(f"【{self.cookie_id}】后台任务已清理完成")
                        except asyncio.TimeoutError:
                            logger.warning(f"【{self.cookie_id}】后台任务清理超时，强制继续重启")
                        except Exception as cleanup_e:
                            logger.error(f"【{self.cookie_id}】后台任务清理失败: {self._safe_str(cleanup_e)}")
                        
                        # 触发重启（不等待完成）
                        await self._restart_instance()
                        
                        # ⚠️ 重要：_restart_instance() 已触发重启，0.5秒后当前任务会被取消
                        # 不要在这里等待或执行其他操作，让任务自然退出
                        logger.info(f"【{self.cookie_id}】重启请求已触发，主程序即将退出，新实例将自动启动")
                        return  # 退出当前连接循环，等待被取消

                    # 计算重试延迟
                    # 风控期间的失败通常报"Token获取失败"，错误文本里不含风控特征，
                    # 只看 error_msg 会退避不足（20 秒一次），因此同时查熔断状态。
                    from utils import risk_control

                    guard = risk_control.registry.get(self.cookie_id)
                    if guard.is_blocked:
                        retry_delay = max(guard.remaining_seconds + 5, 60)
                        logger.warning(
                            f"【{self.cookie_id}】风控冷却中，将在 {retry_delay} 秒后重试连接"
                            f"（冷却剩余 {guard.remaining_seconds} 秒）"
                        )
                    else:
                        retry_delay = self._calculate_retry_delay(error_msg)
                    logger.warning(f"【{self.cookie_id}】将在 {retry_delay} 秒后重试连接...")

                    try:
                        # 清空当前token，确保重新连接时会重新获取
                        if self.current_token:
                            logger.warning(f"【{self.cookie_id}】清空当前token，重新连接时将重新获取")
                            self.current_token = None

                        # 直接重置任务引用，不等待取消（快速重连方案）
                        # 这样可以避免等待任务取消导致的阻塞问题
                        logger.info(f"【{self.cookie_id}】准备重置后台任务引用（快速重连模式）...")
                        self._reset_background_tasks()
                        logger.info(f"【{self.cookie_id}】后台任务引用已重置，可以立即重连")

                        # 等待后重试 - 使用可中断的sleep，并定期输出日志证明进程还活着
                        logger.info(f"【{self.cookie_id}】开始等待 {retry_delay} 秒...")
                        # 强制刷新日志缓冲区，确保日志被写入
                        try:
                            sys.stdout.flush()
                        except:
                            pass
                        
                        # 使用可中断的sleep，每5秒输出一次心跳日志
                        chunk_size = 5.0  # 每5秒输出一次日志
                        remaining = retry_delay
                        start_time = time.time()
                        
                        while remaining > 0:
                            sleep_time = min(chunk_size, remaining)
                            try:
                                await asyncio.sleep(sleep_time)
                                remaining -= sleep_time
                                elapsed = time.time() - start_time
                                if remaining > 0:
                                    logger.info(f"【{self.cookie_id}】等待中... 已等待 {elapsed:.1f} 秒，剩余 {remaining:.1f} 秒")
                                    # 定期刷新日志
                                    try:
                                        sys.stdout.flush()
                                    except:
                                        pass
                            except asyncio.CancelledError:
                                logger.warning(f"【{self.cookie_id}】等待期间收到取消信号")
                                raise
                            except Exception as sleep_error:
                                logger.error(f"【{self.cookie_id}】等待期间发生异常: {self._safe_str(sleep_error)}")
                                logger.warning(f"【{self.cookie_id}】等待异常堆栈:\n{traceback.format_exc()}")
                                # 即使出错也继续等待剩余时间
                                if remaining > 0:
                                    await asyncio.sleep(remaining)
                                break
                        
                        logger.info(f"【{self.cookie_id}】等待完成（总耗时 {time.time() - start_time:.1f} 秒），准备重新连接...")
                        # 再次强制刷新日志
                        try:
                            sys.stdout.flush()
                        except:
                            pass
                        
                    except Exception as cleanup_error:
                        logger.error(f"【{self.cookie_id}】清理过程出错: {self._safe_str(cleanup_error)}")
                        logger.warning(f"【{self.cookie_id}】清理异常堆栈:\n{traceback.format_exc()}")
                        # 即使清理失败，也要重置任务引用并等待后重试
                        self.heartbeat_task = None
                        self.token_refresh_task = None
                        self.cleanup_task = None
                        self.cookie_refresh_task = None
                        logger.warning(f"【{self.cookie_id}】清理失败，已强制重置所有任务引用")
                        # 使用可中断的sleep，并定期输出日志
                        logger.info(f"【{self.cookie_id}】清理失败后开始等待 {retry_delay} 秒...")
                        chunk_size = 5.0
                        remaining = retry_delay
                        start_time = time.time()
                        
                        while remaining > 0:
                            sleep_time = min(chunk_size, remaining)
                            try:
                                await asyncio.sleep(sleep_time)
                                remaining -= sleep_time
                                if remaining > 0:
                                    logger.info(f"【{self.cookie_id}】清理失败后等待中... 剩余 {remaining:.1f} 秒")
                            except asyncio.CancelledError:
                                logger.warning(f"【{self.cookie_id}】清理失败后等待期间收到取消信号")
                                raise
                            except Exception as sleep_error:
                                logger.error(f"【{self.cookie_id}】清理失败后等待期间发生异常: {self._safe_str(sleep_error)}")
                                if remaining > 0:
                                    await asyncio.sleep(remaining)
                                break
                        
                        logger.info(f"【{self.cookie_id}】清理失败后等待完成（总耗时 {time.time() - start_time:.1f} 秒）")
                    
                    # 继续下一次循环
                    logger.info(f"【{self.cookie_id}】开始新一轮WebSocket连接尝试...")
                    continue
        finally:
            # 更新连接状态为已关闭
            self._set_connection_state(ConnectionState.CLOSED, "程序退出")
            
            # 清空当前token
            if self.current_token:
                logger.info(f"【{self.cookie_id}】程序退出，清空当前token")
                self.current_token = None

            # 检查是否还有未取消的后台任务，如果有才执行清理
            has_pending_tasks = any([
                self.heartbeat_task and not self.heartbeat_task.done(),
                self.token_refresh_task and not self.token_refresh_task.done(),
                self.cleanup_task and not self.cleanup_task.done(),
                self.cookie_refresh_task and not self.cookie_refresh_task.done()
            ])
            
            if has_pending_tasks:
                logger.info(f"【{self.cookie_id}】检测到未完成的后台任务，执行清理...")
                # 使用统一的任务清理方法，添加超时保护
                try:
                    await asyncio.wait_for(
                        self._cancel_background_tasks(),
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    logger.error(f"【{self.cookie_id}】程序退出时任务取消超时，强制继续")
                except Exception as e:
                    logger.error(f"【{self.cookie_id}】程序退出时任务取消失败: {self._safe_str(e)}")
                finally:
                    # 确保任务引用被重置
                    self.heartbeat_task = None
                    self.token_refresh_task = None
                    self.cleanup_task = None
                    self.cookie_refresh_task = None
            else:
                logger.info(f"【{self.cookie_id}】所有后台任务已清理完成，跳过重复清理")
                # 确保任务引用被重置
                self.heartbeat_task = None
                self.token_refresh_task = None
                self.cleanup_task = None
                self.cookie_refresh_task = None
            
            # 清理所有后台任务
            if self.background_tasks:
                logger.info(f"【{self.cookie_id}】等待 {len(self.background_tasks)} 个后台任务完成...")
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*self.background_tasks, return_exceptions=True),
                        timeout=10.0  # 10秒超时
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"【{self.cookie_id}】后台任务清理超时，强制继续")
            
            # 确保关闭session
            await self.close_session()

            # 从全局实例字典中注销当前实例
            self._unregister_instance()
            logger.info(f"【{self.cookie_id}】XianyuLive主程序已完全退出")

    @staticmethod
    def _select_item_group(groups):
        """优先选择当前账号的“在售”分组。"""
        if not isinstance(groups, list):
            return None
        for group in groups:
            if isinstance(group, dict) and group.get('groupName') == '在售':
                return group
        for group in groups:
            conditions = group.get('searchCondition') if isinstance(group, dict) else None
            if isinstance(conditions, list) and any(
                str(condition.get('status')) == '0'
                for condition in conditions
                if isinstance(condition, dict)
            ):
                return group
        return None

    @staticmethod
    def _extract_item_image(*sources):
        """从不同版本的商品卡片结构中选出最可信的主图。"""
        candidates = []
        image_keys = ('image', 'pic', 'cover', 'thumb', 'poster')

        def visit(node, key_hint='', depth=0):
            if depth > 8:
                return
            if isinstance(node, str):
                value = node.strip()
                lower_value = value.lower()
                lower_key = key_hint.lower()
                is_url = value.startswith(('http://', 'https://', '//'))
                looks_like_image = any(
                    marker in lower_value
                    for marker in ('.jpg', '.jpeg', '.png', '.webp', '.avif', 'alicdn.com')
                )
                if is_url and looks_like_image:
                    score = 0
                    if any(marker in lower_key for marker in image_keys):
                        score += 40
                    if any(marker in lower_key for marker in ('main', 'cover', 'item')):
                        score += 40
                    if 'xy_item' in lower_value:
                        score += 100
                    if 'bao/uploaded' in lower_value:
                        score += 20
                    if any(marker in lower_key for marker in ('avatar', 'head', 'user', 'seller')):
                        score -= 100
                    candidates.append((score, value))
                return
            if isinstance(node, list):
                for child in node:
                    visit(child, key_hint, depth + 1)
                return
            if not isinstance(node, dict):
                return

            priority_keys = (
                'mainPic', 'mainImage', 'coverImage', 'itemImage', 'picUrl',
                'imageUrl', 'picInfo', 'image', 'pic', 'cover', 'url', 'src'
            )
            visited = set()
            for key in priority_keys:
                if key in node:
                    visited.add(key)
                    visit(node[key], key, depth + 1)
            for key, value in node.items():
                if key not in visited and isinstance(value, (dict, list)):
                    visit(value, key, depth + 1)

        for source in sources:
            visit(source)
        if not candidates:
            return ''
        return max(enumerate(candidates), key=lambda entry: (entry[1][0], -entry[0]))[1][1]

    @staticmethod
    def _normalize_item_card(card):
        """兼容旧cardList和新版itemTopicList中的商品对象。"""
        if not isinstance(card, dict):
            return None
        card_data = card.get('cardData') if isinstance(card.get('cardData'), dict) else card
        for key in ('itemInfo', 'itemData', 'item'):
            if isinstance(card_data.get(key), dict):
                card_data = card_data[key]
                break

        detail_params = card_data.get('detailParams', {})
        if not isinstance(detail_params, dict):
            detail_params = {}
        item_id = (
            detail_params.get('itemId')
            or card_data.get('itemId')
            or card_data.get('auctionId')
            or card_data.get('id')
        )
        if not item_id:
            return None

        price_info = card_data.get('priceInfo', {})
        if not isinstance(price_info, dict):
            price_info = {}
        price = price_info.get('price', card_data.get('price', ''))
        pic_info = card_data.get('picInfo', card.get('picInfo', {}))
        if not isinstance(pic_info, (dict, list, str)):
            pic_info = {}
        item_image = XianyuLive._extract_item_image(pic_info, card_data, card)

        return {
            'id': str(item_id),
            'title': card_data.get('title') or card_data.get('itemTitle') or card_data.get('name') or '',
            'price': price,
            'price_text': f"{price_info.get('preText', '')}{price}" if price_info else str(price or ''),
            'category_id': card_data.get('categoryId', ''),
            'auction_type': card_data.get('auctionType', ''),
            'item_status': card_data.get('itemStatus', 0),
            'detail_url': card_data.get('detailUrl', ''),
            'web_url': f'https://www.goofish.com/item?id={item_id}',
            'pic_info': pic_info,
            'item_image': item_image,
            'detail_params': detail_params,
            'track_params': card_data.get('trackParams', {}),
            'item_label_data': card_data.get('itemLabelDataVO', {}),
            'card_type': card.get('cardType', 0)
        }

    @classmethod
    def _extract_items_from_response(cls, items_data):
        """从新旧商品列表结构中递归提取商品，并按ID去重。"""
        candidates = list(items_data.get('cardList', []) or [])

        def visit(node):
            if isinstance(node, list):
                for child in node:
                    visit(child)
                return
            if not isinstance(node, dict):
                return
            if isinstance(node.get('cardData'), dict):
                candidates.append(node)
                return
            has_item_id = any(key in node for key in ('itemId', 'auctionId'))
            has_item_shape = any(
                key in node
                for key in ('title', 'itemTitle', 'priceInfo', 'detailParams', 'itemInfo', 'itemData')
            )
            if has_item_id and has_item_shape:
                candidates.append(node)
                return
            for child in node.values():
                if isinstance(child, (dict, list)):
                    visit(child)

        visit(items_data.get('itemTopicList', []) or [])
        items = []
        seen_ids = set()
        for candidate in candidates:
            item = cls._normalize_item_card(candidate)
            if item and item['id'] not in seen_ids:
                seen_ids.add(item['id'])
                items.append(item)
        return items

    async def get_item_list_info(self, page_number=1, page_size=20, retry_count=0):
        """动态发现当前账号的在售分组并获取商品列表。"""
        if retry_count >= 4:
            return {'error': '获取商品信息失败，重试次数过多'}
        if not self.session:
            await self.create_session()

        def empty_result(group_name='在售', confirmed=False, response_fields=None):
            """一件商品都没有，但这次同步是成功的。

            这里必须带上 success 和调用方要读的全部字段。只有正常路径设了
            `'success': True`，早期返回如果只给 {'items': []}，get_all_items 会按
            `not result.get('success')` 判成失败并抛 502 —— 表现为新加的空账号
            同步时只弹一句「Request failed with status code 502」。

            confirmed 表示「确认这个账号真的没有商品」。它会让上层把库里已有商品
            全标成已下架，所以只有在闲鱼明确回了分组、且分组商品数都是 0 时才置
            True；分组列表整个为空这种可疑情况一律留 False。
            """
            return {
                'success': True,
                'page_number': page_number,
                'page_size': page_size,
                'current_count': 0,
                'total_count': 0,
                'api_total_count': 0,
                'group_declared_count': 0,
                'count_reconciled': False,
                'items': [],
                'saved_count': 0,
                'next_page': False,
                'confirmed_empty': confirmed,
                'group_name': group_name,
                'group_id': None,
                'account_id': self.myid,
                'response_fields': response_fields or [],
            }

        async def request_item_api(data):
            params = {
                'jsv': '2.7.2',
                'appKey': '34839810',
                't': str(int(time.time() * 1000)),
                'sign': '',
                'v': '1.0',
                'type': 'originaljson',
                'accountSite': 'xianyu',
                'dataType': 'json',
                'timeout': '20000',
                'api': 'mtop.idle.web.xyh.item.list',
                'sessionOption': 'AutoLoginOnly',
                'spm_cnt': 'a21ybx.personal.0.0'
            }
            cookie_dict = trans_cookies(self.cookies_str)
            token_value = cookie_dict.get('_m_h5_tk', '')
            token = token_value.split('_')[0] if token_value else ''
            if not token:
                logger.warning(f"【{self.cookie_id}】商品同步Cookie缺少_m_h5_tk字段")

            data_val = json.dumps(data, separators=(',', ':'))
            params['sign'] = generate_sign(params['t'], token, data_val)
            async with self.session.post(
                'https://h5api.m.goofish.com/h5/mtop.idle.web.xyh.item.list/1.0/',
                params=params,
                data={'data': data_val}
            ) as response:
                # 网关故障要当场认出来。502/503 返回的是 HTML 错误页，
                # 直接 response.json() 要么抛解析异常、要么拿到不含 ret 的结构，
                # 最后被当成业务问题报成“未返回在售分组”，把临时抖动说成数据异常。
                if response.status >= 500:
                    raise ItemListTransientError(
                        f"闲鱼接口返回 HTTP {response.status}"
                    )
                try:
                    res_json = await response.json(content_type=None)
                except Exception as parse_error:
                    body = (await response.text())[:200]
                    raise ItemListTransientError(
                        f"闲鱼接口响应无法解析（HTTP {response.status}）: {parse_error}；响应片段: {body}"
                    )
                if not isinstance(res_json, dict):
                    raise ItemListTransientError(
                        f"闲鱼接口响应结构异常（HTTP {response.status}）"
                    )
                if 'set-cookie' in response.headers:
                    new_cookies = {}
                    for cookie in response.headers.getall('set-cookie', []):
                        if '=' in cookie:
                            name, value = cookie.split(';')[0].split('=', 1)
                            new_cookies[name.strip()] = value.strip()
                    if new_cookies:
                        self.cookies.update(new_cookies)
                        self.cookies_str = '; '.join(f"{key}={value}" for key, value in self.cookies.items())
                        self.session.headers['cookie'] = self.cookies_str
                        await self.update_config_cookies()
                        logger.info(
                            f"【{self.cookie_id}】商品同步响应更新了"
                            f"{len(new_cookies)}个Cookie字段"
                        )
                return res_json

        try:
            item_group = getattr(self, '_item_list_group', None)
            if page_number == 1 or not item_group:
                discovery_response = await request_item_api({
                    'needGroupInfo': True,
                    'pageNumber': 1,
                    'pageSize': page_size,
                    'userId': self.myid
                })
                discovery_ret = discovery_response.get('ret', [])
                if not discovery_ret or not str(discovery_ret[0]).startswith('SUCCESS::'):
                    error_msg = discovery_ret[0] if discovery_ret else '未知错误'
                    if 'TOKEN' in str(error_msg).upper():
                        await asyncio.sleep(0.5)
                        return await self.get_item_list_info(page_number, page_size, retry_count + 1)
                    return {'error': f"商品分组发现失败: {error_msg}"}

                # 用 `or []` 兜住显式 None：闲鱼对无分组账号有时省略这个键
                # （get 拿到默认的 []），有时又明确回 null（get 拿到 None）。
                # 后者会让下面的遍历直接抛 TypeError，被外层吞成一句同步失败。
                groups = discovery_response.get('data', {}).get('itemGroupList') or []
                group_summary = [
                    {
                        'name': group.get('groupName'),
                        'id': group.get('groupId'),
                        'count': group.get('itemNumber')
                    }
                    for group in groups
                    if isinstance(group, dict)
                ]
                logger.info(
                    f"【{self.cookie_id}】商品分组发现: account={self.myid}, "
                    f"groups={group_summary}"
                )
                item_group = self._select_item_group(groups)
                if not item_group:
                    # 没匹配到“在售”不代表拿不到商品：闲鱼可能改了分组文案，
                    # 账号也可能只有自定义分组。这里退回“按商品数最多的分组”，
                    # 真的一件商品都没有才如实返回空列表，而不是报成接口异常。
                    fallback_group = None
                    for group in groups:
                        if not isinstance(group, dict):
                            continue
                        if int(group.get('itemNumber') or 0) <= 0:
                            continue
                        if fallback_group is None or int(group.get('itemNumber') or 0) > int(
                            fallback_group.get('itemNumber') or 0
                        ):
                            fallback_group = group

                    if fallback_group:
                        logger.warning(
                            f"【{self.cookie_id}】未找到“在售”分组，改用"
                            f"“{fallback_group.get('groupName')}”"
                            f"（{fallback_group.get('itemNumber')} 件）继续同步"
                        )
                        item_group = fallback_group
                    elif groups:
                        logger.info(
                            f"【{self.cookie_id}】账号所有分组均为 0 件商品，按空列表处理"
                        )
                        return empty_result(confirmed=True)
                    else:
                        # 分组列表为空，但发现请求本身返回了 SUCCESS —— 登录态是好的。
                        # 关键在于：这次请求的响应里往往已经带着商品（cardList），
                        # 只是没有分组信息。实测某账号 itemGroupList=None、
                        # totalCount=0，而 cardList 里就有它的 4 件商品。
                        #
                        # 原先这里直接报错，接口以 502 返回，用户只看到一句
                        # 「Request failed with status code 502」，而商品明明已经
                        # 在手里。所以先尝试直接解析这次响应，解析不到才按空处理。
                        discovery_data = discovery_response.get('data', {}) or {}
                        discovered_items = self._extract_items_from_response(discovery_data)
                        if discovered_items:
                            logger.warning(
                                f"【{self.cookie_id}】账号无商品分组，改用分组发现响应里的"
                                f"商品列表：解析到 {len(discovered_items)} 件"
                            )
                            saved = await self.save_items_list_to_db(discovered_items)
                            return {
                                'success': True,
                                'page_number': page_number,
                                'page_size': page_size,
                                'current_count': len(discovered_items),
                                'total_count': len(discovered_items),
                                'api_total_count': int(discovery_data.get('totalCount') or 0),
                                'group_declared_count': 0,
                                'count_reconciled': int(discovery_data.get('totalCount') or 0)
                                != len(discovered_items),
                                'items': discovered_items,
                                'saved_count': saved,
                                'next_page': bool(discovery_data.get('nextPage')),
                                'confirmed_empty': False,
                                'group_name': '全部',
                                'group_id': None,
                                'account_id': self.myid,
                                'response_fields': sorted(discovery_data.keys()),
                            }

                        # 连商品也解析不到：可能真的没上架，也可能是接口抖动。
                        # 按空列表处理但不置 confirmed_empty —— 后者会让上层把库里
                        # 已有商品全标成已下架，不能凭一次可疑的空响应就清空状态。
                        logger.info(
                            f"【{self.cookie_id}】闲鱼未返回商品分组，响应里也没有商品，"
                            f"按空列表处理（字段: {sorted(discovery_data.keys())}）"
                        )
                        return empty_result(
                            confirmed=False,
                            response_fields=sorted(discovery_data.keys()),
                        )
                self._item_list_group = item_group

            group_id = item_group.get('groupId')
            group_name = item_group.get('groupName', '在售')
            res_json = await request_item_api({
                'needGroupInfo': False,
                'pageNumber': page_number,
                'pageSize': page_size,
                'groupName': group_name,
                'groupId': str(group_id),
                'defaultGroup': bool(item_group.get('defaultGroup', True)),
                'userId': self.myid
            })
            response_ret = res_json.get('ret', [])
            if not response_ret or not str(response_ret[0]).startswith('SUCCESS::'):
                error_msg = response_ret[0] if response_ret else '未知错误'
                if 'TOKEN' in str(error_msg).upper():
                    await asyncio.sleep(0.5)
                    return await self.get_item_list_info(page_number, page_size, retry_count + 1)
                return {'error': f"获取商品信息失败: {error_msg}"}

            items_data = res_json.get('data', {})
            items_list = self._extract_items_from_response(items_data)
            total_count = int(items_data.get('totalCount') or 0)
            declared_count = int(item_group.get('itemNumber') or 0)
            effective_total_count = max(total_count, declared_count, len(items_list))
            response_fields = sorted(items_data.keys())
            logger.info(
                f"【{self.cookie_id}】商品列表响应: account={self.myid}, "
                f"group={group_name}({group_id}), page={page_number}, "
                f"fields={response_fields}, totalCount={total_count}, "
                f"groupItemNumber={declared_count}, parsed={len(items_list)}, "
                f"effectiveTotal={effective_total_count}, "
                f"nextPage={bool(items_data.get('nextPage'))}"
            )

            if total_count > 0 and not items_list:
                return {
                    'error': f"闲鱼接口显示“{group_name}”有 {total_count} 件商品，但当前响应结构无法解析",
                    'response_fields': response_fields
                }
            if total_count == 0 and declared_count > 0 and not items_list:
                return {
                    'error': f"闲鱼分组显示“{group_name}”有 {declared_count} 件商品，但列表接口返回0件，请稍后重试",
                    'response_fields': response_fields
                }
            if items_list and total_count == 0:
                logger.warning(
                    f"【{self.cookie_id}】闲鱼商品列表 totalCount=0，"
                    f"但实际解析到 {len(items_list)} 件，按商品数组继续同步"
                )

            saved_count = 0
            if items_list:
                saved_count = await self.save_items_list_to_db(items_list)

            return {
                'success': True,
                'page_number': page_number,
                'page_size': page_size,
                'current_count': len(items_list),
                'total_count': effective_total_count,
                'api_total_count': total_count,
                'group_declared_count': declared_count,
                'count_reconciled': effective_total_count != total_count,
                'items': items_list,
                'saved_count': saved_count,
                'next_page': bool(items_data.get('nextPage')),
                'confirmed_empty': not items_list and total_count == 0 and declared_count == 0,
                'group_name': group_name,
                'group_id': group_id,
                'account_id': self.myid,
                'response_fields': response_fields
            }
        except ItemListTransientError as e:
            # 网关抖动：退避重试，比固定 0.5 秒更有机会等到恢复。
            # 重试用尽后如实说明是接口临时故障，不要让用户去查账号和商品。
            if retry_count + 1 >= 4:
                logger.error(f"【{self.cookie_id}】商品列表接口持续异常: {self._safe_str(e)}")
                return {'error': f"闲鱼接口暂时不可用（{self._safe_str(e)}），请稍后重试"}
            backoff = min(2 ** retry_count, 8)
            logger.warning(
                f"【{self.cookie_id}】商品列表接口异常，{backoff}秒后重试"
                f"（第{retry_count + 1}次）: {self._safe_str(e)}"
            )
            await asyncio.sleep(backoff)
            return await self.get_item_list_info(page_number, page_size, retry_count + 1)
        except Exception as e:
            logger.error(f"商品信息API请求异常: {self._safe_str(e)}")
            await asyncio.sleep(0.5)
            return await self.get_item_list_info(page_number, page_size, retry_count + 1)

    async def get_all_items(self, page_size=20, max_pages=None):
        """获取所有在售商品信息（自动分页）。"""
        all_items = []
        page_number = 1
        pages_fetched = 0
        total_saved = 0
        confirmed_empty = False
        group_name = '在售'
        api_total_count = 0
        group_declared_count = 0
        count_reconciled = False

        logger.info(f"开始获取所有商品信息，每页{page_size}条")
        while True:
            if max_pages and page_number > max_pages:
                logger.info(f"达到最大页数限制 {max_pages}，停止获取")
                break

            result = await self.get_item_list_info(page_number, page_size)
            if not result.get('success'):
                logger.error(f"获取第 {page_number} 页失败: {result}")
                return {
                    'success': False,
                    'error': result.get('error', '商品同步失败'),
                    'details': result
                }

            pages_fetched += 1
            current_items = result.get('items', [])
            confirmed_empty = result.get('confirmed_empty', False)
            group_name = result.get('group_name', group_name)
            api_total_count = max(api_total_count, result.get('api_total_count', 0))
            group_declared_count = max(
                group_declared_count,
                result.get('group_declared_count', 0)
            )
            count_reconciled = count_reconciled or result.get('count_reconciled', False)
            if not current_items:
                break

            all_items.extend(current_items)
            total_saved += result.get('saved_count', 0)
            if not result.get('next_page', len(current_items) >= page_size):
                break

            page_number += 1
            await asyncio.sleep(1)

        logger.info(
            f"【{self.cookie_id}】商品获取完成: account={self.myid}, "
            f"group={group_name}, total={len(all_items)}, saved={total_saved}, "
            f"confirmed_empty={confirmed_empty}"
        )

        # 校准上下架状态。同步原先只做 upsert，接口不再返回的商品会永久留在
        # 列表里，和在售的长得一样 —— 用户既分不清也筛不掉。
        #
        # 只在「完整且成功」的同步后才校准，否则会把在售商品误标成下架：
        #   - 被 max_pages 截断时，后面几页的商品根本没被拉取；
        #   - 一件都没返回时，除非接口明确确认为空，否则更可能是接口抖动。
        off_shelf_count = 0
        truncated = bool(max_pages and pages_fetched >= max_pages)
        if truncated:
            logger.info(f"【{self.cookie_id}】同步被 max_pages 截断，跳过上下架校准")
        elif not all_items and not confirmed_empty:
            logger.warning(
                f"【{self.cookie_id}】接口未返回任何商品且未确认为空，"
                f"跳过上下架校准以免误标"
            )
        else:
            from app.db_manager import db_manager
            stats = db_manager.reconcile_item_listing_status(
                self.cookie_id, [item.get('id') for item in all_items]
            )
            off_shelf_count = stats.get('off_shelf', 0)

        return {
            'success': True,
            'total_pages': pages_fetched,
            'total_count': len(all_items),
            'total_saved': total_saved,
            'items': all_items,
            'api_total_count': api_total_count,
            'group_declared_count': group_declared_count,
            'parsed_count': len(all_items),
            'count_reconciled': count_reconciled,
            'confirmed_empty': confirmed_empty,
            'group_name': group_name,
            'account_id': self.myid,
            'off_shelf_count': off_shelf_count
        }

    async def send_image_msg(self, ws, cid, toid, image_url, width=800, height=600, card_id=None):
        """发送图片消息"""
        try:
            # 检查图片URL是否需要上传到CDN
            original_url = image_url

            if self._is_cdn_url(image_url):
                # 已经是CDN链接，直接使用
                logger.info(f"【{self.cookie_id}】使用已有的CDN图片链接: {image_url}")
            elif image_url.startswith('/static/uploads/') or image_url.startswith('static/uploads/'):
                # 本地图片，需要上传到闲鱼CDN
                local_image_path = image_url.replace('/static/uploads/', 'static/uploads/')
                if os.path.exists(local_image_path):
                    logger.info(f"【{self.cookie_id}】准备上传本地图片到闲鱼CDN: {local_image_path}")

                    # 使用图片上传器上传到闲鱼CDN
                    from utils.image_uploader import ImageUploader
                    uploader = ImageUploader(self.cookies_str)

                    async with uploader:
                        cdn_url = await uploader.upload_image(local_image_path)
                        if cdn_url:
                            logger.info(f"【{self.cookie_id}】图片上传成功，CDN URL: {cdn_url}")
                            image_url = cdn_url

                            # 如果是卡券图片，更新数据库中的图片URL
                            if card_id is not None:
                                await self._update_card_image_url(card_id, cdn_url)

                            # 获取实际图片尺寸
                            from utils.image_utils import image_manager
                            try:
                                actual_width, actual_height = image_manager.get_image_size(local_image_path)
                                if actual_width and actual_height:
                                    width, height = actual_width, actual_height
                                    logger.info(f"【{self.cookie_id}】获取到实际图片尺寸: {width}x{height}")
                            except Exception as e:
                                logger.warning(f"【{self.cookie_id}】获取图片尺寸失败，使用默认尺寸: {e}")
                        else:
                            logger.error(f"【{self.cookie_id}】图片上传失败: {local_image_path}")
                            logger.error(f"【{self.cookie_id}】❌ Cookie可能已失效！请检查配置并更新Cookie")
                            raise Exception(f"图片上传失败（Cookie可能已失效）: {local_image_path}")
                else:
                    logger.error(f"【{self.cookie_id}】本地图片文件不存在: {local_image_path}")
                    raise Exception(f"本地图片文件不存在: {local_image_path}")
            else:
                logger.warning(f"【{self.cookie_id}】未知的图片URL格式: {image_url}")

            # 记录详细的图片信息
            logger.info(f"【{self.cookie_id}】准备发送图片消息:")
            logger.info(f"  - 原始URL: {original_url}")
            logger.info(f"  - CDN URL: {image_url}")
            logger.info(f"  - 图片尺寸: {width}x{height}")
            logger.info(f"  - 聊天ID: {cid}")
            logger.info(f"  - 接收者ID: {toid}")

            # 构造图片消息内容 - 使用正确的闲鱼格式
            image_content = {
                "contentType": 2,  # 图片消息类型
                "image": {
                    "pics": [
                        {
                            "height": int(height),
                            "type": 0,
                            "url": image_url,
                            "width": int(width)
                        }
                    ]
                }
            }

            # Base64编码
            content_json = json.dumps(image_content, ensure_ascii=False)
            content_base64 = str(base64.b64encode(content_json.encode('utf-8')), 'utf-8')

            logger.info(f"【{self.cookie_id}】图片内容JSON: {content_json}")
            logger.info(f"【{self.cookie_id}】Base64编码长度: {len(content_base64)}")

            # 构造WebSocket消息（完全参考send_msg的格式）
            msg = {
                "lwp": "/r/MessageSend/sendByReceiverScope",
                "headers": {
                    "mid": generate_mid()
                },
                "body": [
                    {
                        "uuid": generate_uuid(),
                        "cid": f"{cid}@goofish",
                        "conversationType": 1,
                        "content": {
                            "contentType": 101,
                            "custom": {
                                "type": 1,
                                "data": content_base64
                            }
                        },
                        "redPointPolicy": 0,
                        "extension": {
                            "extJson": "{}"
                        },
                        "ctx": {
                            "appVersion": "1.0",
                            "platform": "web"
                        },
                        "mtags": {},
                        "msgReadStatusSetting": 1
                    },
                    {
                        "actualReceivers": [
                            f"{toid}@goofish",
                            f"{self.myid}@goofish"
                        ]
                    }
                ]
            }

            await ws.send(json.dumps(msg))
            logger.info(f"【{self.cookie_id}】图片消息发送成功: {image_url}")

        except Exception as e:
            logger.error(f"【{self.cookie_id}】发送图片消息失败: {self._safe_str(e)}")
            raise

    async def send_image_from_file(self, ws, cid, toid, image_path):
        """从本地文件发送图片"""
        try:
            # 上传图片到闲鱼CDN
            logger.info(f"【{self.cookie_id}】开始上传图片: {image_path}")

            from utils.image_uploader import ImageUploader
            uploader = ImageUploader(self.cookies_str)

            async with uploader:
                image_url = await uploader.upload_image(image_path)

            if image_url:
                # 获取图片信息
                try:
                    from PIL import Image
                    with Image.open(image_path) as img:
                        width, height = img.size
                except Exception as e:
                    logger.warning(f"无法获取图片尺寸，使用默认值: {e}")
                    width, height = 800, 600

                # 发送图片消息
                await self.send_image_msg(ws, cid, toid, image_url, width, height)
                logger.info(f"【{self.cookie_id}】图片发送完成: {image_path} -> {image_url}")
                return True
            else:
                logger.error(f"【{self.cookie_id}】图片上传失败: {image_path}")
                logger.error(f"【{self.cookie_id}】❌ Cookie可能已失效！请检查配置并更新Cookie")
                return False

        except Exception as e:
            logger.error(f"【{self.cookie_id}】从文件发送图片失败: {self._safe_str(e)}")
            return False

if __name__ == '__main__':
    cookies_str = os.getenv('COOKIES_STR')
    xianyuLive = XianyuLive(cookies_str)
    asyncio.run(xianyuLive.main())
