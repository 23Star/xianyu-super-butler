#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
闲鱼滑块验证 - 增强反检测版本
基于最新的反检测技术，专门针对闲鱼、淘宝、阿里平台的滑块验证
"""

import time
import random
import json
import os
import math
import threading
import tempfile
import shutil
from datetime import datetime
from playwright.sync_api import sync_playwright, ElementHandle
from typing import Optional, Tuple, List, Dict, Any, Callable
from loguru import logger
from collections import defaultdict

# 导入配置
try:
    from app.config import SLIDER_VERIFICATION
    SLIDER_MAX_CONCURRENT = SLIDER_VERIFICATION.get('max_concurrent', 3)
    SLIDER_WAIT_TIMEOUT = SLIDER_VERIFICATION.get('wait_timeout', 60)
except ImportError:
    # 如果无法导入配置，使用默认值
    SLIDER_MAX_CONCURRENT = 3
    SLIDER_WAIT_TIMEOUT = 60

# 使用loguru日志库，与主程序保持一致

# 全局并发控制
class SliderConcurrencyManager:
    """滑块验证并发管理器"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.max_concurrent = SLIDER_MAX_CONCURRENT  # 从配置文件读取最大并发数
            self.wait_timeout = SLIDER_WAIT_TIMEOUT  # 从配置文件读取等待超时时间
            self.active_instances = {}  # 活跃实例
            self.waiting_queue = []  # 等待队列
            self.instance_lock = threading.Lock()
            self._initialized = True
            logger.info(f"滑块验证并发管理器初始化: 最大并发数={self.max_concurrent}, 等待超时={self.wait_timeout}秒")
    
    def can_start_instance(self, user_id: str) -> bool:
        """检查是否可以启动新实例"""
        with self.instance_lock:
            return len(self.active_instances) < self.max_concurrent
    
    def wait_for_slot(self, user_id: str, timeout: int = None) -> bool:
        """等待可用槽位"""
        if timeout is None:
            timeout = self.wait_timeout
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self.instance_lock:
                if len(self.active_instances) < self.max_concurrent:
                    return True
            
            # 检查是否在等待队列中
            with self.instance_lock:
                if user_id not in self.waiting_queue:
                    self.waiting_queue.append(user_id)
                    # 提取纯用户ID用于日志显示
                    pure_user_id = self._extract_pure_user_id(user_id)
                    logger.info(f"【{pure_user_id}】进入等待队列，当前队列长度: {len(self.waiting_queue)}")
            
            # 等待1秒后重试
            time.sleep(1)
        
        # 超时后从队列中移除
        with self.instance_lock:
            if user_id in self.waiting_queue:
                self.waiting_queue.remove(user_id)
                # 提取纯用户ID用于日志显示
                pure_user_id = self._extract_pure_user_id(user_id)
                logger.warning(f"【{pure_user_id}】等待超时，从队列中移除")
        
        return False
    
    def register_instance(self, user_id: str, instance):
        """注册实例"""
        with self.instance_lock:
            self.active_instances[user_id] = {
                'instance': instance,
                'start_time': time.time()
            }
            # 从等待队列中移除
            if user_id in self.waiting_queue:
                self.waiting_queue.remove(user_id)
    
    def unregister_instance(self, user_id: str):
        """注销实例"""
        with self.instance_lock:
            if user_id in self.active_instances:
                del self.active_instances[user_id]
                # 提取纯用户ID用于日志显示
                pure_user_id = self._extract_pure_user_id(user_id)
                logger.info(f"【{pure_user_id}】实例已注销，当前活跃: {len(self.active_instances)}")
    
    def _extract_pure_user_id(self, user_id: str) -> str:
        """提取纯用户ID（移除时间戳部分）"""
        if '_' in user_id:
            # 检查最后一部分是否为数字（时间戳）
            parts = user_id.split('_')
            if len(parts) >= 2 and parts[-1].isdigit() and len(parts[-1]) >= 10:
                # 最后一部分是时间戳，移除它
                return '_'.join(parts[:-1])
            else:
                # 不是时间戳格式，使用原始ID
                return user_id
        else:
            # 没有下划线，直接使用
            return user_id
    
    def get_stats(self):
        """获取统计信息"""
        with self.instance_lock:
            return {
                'active_count': len(self.active_instances),
                'max_concurrent': self.max_concurrent,
                'available_slots': self.max_concurrent - len(self.active_instances),
                'queue_length': len(self.waiting_queue),
                'waiting_users': self.waiting_queue.copy()
            }

# 全局并发管理器实例
concurrency_manager = SliderConcurrencyManager()

# 策略统计管理器
class RetryStrategyStats:
    """重试策略成功率统计管理器"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.stats_lock = threading.Lock()
            self.strategy_stats = {
                'attempt_1_default': {'total': 0, 'success': 0, 'fail': 0},
                'attempt_2_cautious': {'total': 0, 'success': 0, 'fail': 0},
                'attempt_3_fast': {'total': 0, 'success': 0, 'fail': 0},
                'attempt_3_slow': {'total': 0, 'success': 0, 'fail': 0},
            }
            self.stats_file = 'trajectory_history/strategy_stats.json'
            self._load_stats()
            self._initialized = True
            logger.info("策略统计管理器初始化完成")
    
    def _load_stats(self):
        """从文件加载统计数据"""
        try:
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    loaded_stats = json.load(f)
                    self.strategy_stats.update(loaded_stats)
                logger.info(f"已加载历史策略统计数据: {self.stats_file}")
        except Exception as e:
            logger.warning(f"加载策略统计数据失败: {e}")
    
    def _save_stats(self):
        """保存统计数据到文件"""
        try:
            os.makedirs(os.path.dirname(self.stats_file), exist_ok=True)
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.strategy_stats, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存策略统计数据失败: {e}")
    
    def record_attempt(self, attempt: int, strategy_type: str, success: bool):
        """记录一次尝试结果
        
        Args:
            attempt: 尝试次数 (1, 2, 3)
            strategy_type: 策略类型 ('default', 'cautious', 'fast', 'slow')
            success: 是否成功
        """
        with self.stats_lock:
            key = f'attempt_{attempt}_{strategy_type}'
            if key not in self.strategy_stats:
                self.strategy_stats[key] = {'total': 0, 'success': 0, 'fail': 0}
            
            self.strategy_stats[key]['total'] += 1
            if success:
                self.strategy_stats[key]['success'] += 1
            else:
                self.strategy_stats[key]['fail'] += 1
            
            # 每次记录后保存
            self._save_stats()
    
    def get_stats_summary(self):
        """获取统计摘要"""
        with self.stats_lock:
            summary = {}
            for key, stats in self.strategy_stats.items():
                if stats['total'] > 0:
                    success_rate = (stats['success'] / stats['total']) * 100
                    summary[key] = {
                        'total': stats['total'],
                        'success': stats['success'],
                        'fail': stats['fail'],
                        'success_rate': f"{success_rate:.2f}%"
                    }
            return summary
    
    def log_summary(self):
        """输出统计摘要到日志"""
        summary = self.get_stats_summary()
        if summary:
            logger.info("=" * 60)
            logger.info("📊 重试策略成功率统计")
            logger.info("=" * 60)
            for key, stats in summary.items():
                logger.info(f"{key:25s} | 总计:{stats['total']:4d} | 成功:{stats['success']:4d} | 失败:{stats['fail']:4d} | 成功率:{stats['success_rate']}")
            logger.info("=" * 60)

# 全局策略统计实例
strategy_stats = RetryStrategyStats()

class XianyuSliderStealth:
    
    def __init__(self, user_id: str = "default", enable_learning: bool = True, headless: bool = True):
        self.user_id = user_id
        self.enable_learning = enable_learning
        self.headless = headless  # 是否使用无头模式（默认True，使用无头模式）
        self.browser = None
        self.page = None
        self.context = None
        self.playwright = None
        
        # 提取纯用户ID（移除时间戳部分）
        self.pure_user_id = concurrency_manager._extract_pure_user_id(user_id)
        
        # 检查日期限制
        if not self._check_date_validity():
            raise Exception(f"【{self.pure_user_id}】日期验证失败，功能已过期")
        
        # 为每个实例创建独立的临时目录
        self.temp_dir = tempfile.mkdtemp(prefix=f"slider_{user_id}_")
        logger.debug(f"【{self.pure_user_id}】创建临时目录: {self.temp_dir}")
        
        # 等待可用槽位（排队机制）
        logger.info(f"【{self.pure_user_id}】检查并发限制...")
        if not concurrency_manager.wait_for_slot(self.user_id):
            stats = concurrency_manager.get_stats()
            logger.error(f"【{self.pure_user_id}】等待槽位超时，当前活跃: {stats['active_count']}/{stats['max_concurrent']}")
            raise Exception(f"滑块验证等待槽位超时，请稍后重试")
        
        # 注册实例
        concurrency_manager.register_instance(self.user_id, self)
        stats = concurrency_manager.get_stats()
        logger.info(f"【{self.pure_user_id}】实例已注册，当前并发: {stats['active_count']}/{stats['max_concurrent']}")
        
        # 轨迹学习相关属性
        
        self.success_history_file = f"trajectory_history/{self.pure_user_id}_success.json"
        self.trajectory_params = {
            "total_steps_range": [70, 95],  # 采样点数：快速甩动约 70-95 点，仍在真人量级
            "base_delay_range": [0.007, 0.012],  # 每步 7-12ms，对齐真实鼠标 80-140Hz 采样率
            "jitter_x_range": [-1, 1],  # X 轴微颤，需双向，单向偏移是机器特征
            "jitter_y_range": [-3, 3],  # Y 轴漂移，人手无法保持水平
            "slow_factor_range": [8, 12],  # 保留字段，供学习态回写
            "acceleration_phase": 0.1,  # 起步加速占比
            "fast_phase": 0.75,  # 匀速段占比，其后进入减速逼近
            "slow_start_ratio_base": 1.0,  # 落点即目标，超调另由 overshoot 控制
            "completion_usage_rate": 0.05,  # 极少补全使用率
            "avg_completion_steps": 1.0,  # 极少补全步数
            "trajectory_length_stats": [],
            "learning_enabled": True
        }
        
        # 保存最后一次使用的轨迹参数（用于分析优化）
        self.last_trajectory_params = {}

        # 当前验证页地址，重试时需要重新导航以获得全新滑块
        self._current_url = None
    
    def _check_date_validity(self) -> bool:
        """检查日期有效性 - 已禁用
        
        Returns:
            bool: 始终返回 True
        """
        return True
        
    def init_browser(self):
        """初始化浏览器 - 增强反检测版本"""
        try:
            # 启动 Playwright
            logger.info(f"【{self.pure_user_id}】启动Playwright...")
            self.playwright = sync_playwright().start()
            logger.info(f"【{self.pure_user_id}】Playwright启动成功")
            
            # 随机选择浏览器特征
            browser_features = self._get_random_browser_features()
            
            # 启动浏览器，使用随机特征
            logger.info(f"【{self.pure_user_id}】启动浏览器，headless模式: {self.headless}")

            # 实测结论：Playwright 自带的 Chromium（Chrome for Testing）指纹会被阿里 nc
            # 识破，连真人手动拖动都判定失败；换成系统正式版 Chrome + 持久化用户目录后
            # 同样的手动拖动即可通过。因此这里必须走 channel='chrome' 的持久化上下文，
            # 让 CDP 之外的指纹（二进制版本、插件、WebGL、历史 profile）都保持真实。
            user_data_dir = os.path.join(
                os.getcwd(), 'browser_data', f'slider_{self.pure_user_id}'
            )
            os.makedirs(user_data_dir, exist_ok=True)

            launch_args = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--start-maximized",
                f"--window-size={browser_features['window_size']}",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                f"--lang={browser_features['lang']}",
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--disable-popup-blocking",
                "--disable-search-engine-choice-screen",
                "--password-store=basic",
                "--use-mock-keychain",
            ]

            # 持久化上下文没有独立的 browser 对象，context 即入口
            context_options = {
                'locale': browser_features['locale'],
                'timezone_id': browser_features['timezone_id'],
                'color_scheme': random.choice(['light', 'dark', 'no-preference']),
                'ignore_https_errors': False,
            }
            if not self.headless:
                context_options['no_viewport'] = True
            else:
                context_options['viewport'] = {
                    'width': browser_features['viewport_width'],
                    'height': browser_features['viewport_height'],
                }

            try:
                self.context = self.playwright.chromium.launch_persistent_context(
                    user_data_dir,
                    channel='chrome',  # 系统安装的正式版 Chrome
                    headless=self.headless,
                    args=launch_args,
                    **context_options,
                )
                self.browser = None  # 持久化模式下无独立 browser 句柄
                logger.info(f"【{self.pure_user_id}】已启动系统 Chrome（持久化目录）")
            except Exception as chrome_error:
                # 机器上没装 Chrome 时退回自带 Chromium，虽然大概率过不了，
                # 但至少不让整个流程直接崩掉。
                logger.warning(
                    f"【{self.pure_user_id}】系统 Chrome 不可用（{chrome_error}），"
                    "退回 Chromium —— 滑块通过率会显著下降"
                )
                self.browser = self.playwright.chromium.launch(
                    headless=self.headless, args=launch_args
                )
                self.context = self.browser.new_context(
                    user_agent=browser_features['user_agent'], **context_options
                )

            # 验证上下文已创建
            if not self.context:
                raise Exception("浏览器上下文创建失败")
            logger.info(f"【{self.pure_user_id}】浏览器上下文创建成功")

            # 创建新页面（持久化上下文会自带一个空白页，复用它避免多开窗口）
            logger.info(f"【{self.pure_user_id}】创建新页面...")
            existing = self.context.pages
            self.page = existing[0] if existing else self.context.new_page()
            
            # 验证页面已创建
            if not self.page:
                raise Exception("页面创建失败")
            logger.info(f"【{self.pure_user_id}】页面创建成功（{'最大化窗口模式' if not self.headless else '无头模式'}）")
            
            # 添加增强反检测脚本
            logger.info(f"【{self.pure_user_id}】添加反检测脚本...")
            self.page.add_init_script(self._get_stealth_script(browser_features))
            logger.info(f"【{self.pure_user_id}】浏览器初始化完成")
            
            return self.page
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】初始化浏览器失败: {e}")
            import traceback
            logger.error(f"【{self.pure_user_id}】详细错误堆栈: {traceback.format_exc()}")
            # 确保在异常时也清理已创建的资源
            self._cleanup_on_init_failure()
            raise
    
    def _cleanup_on_init_failure(self):
        """初始化失败时的清理"""
        try:
            if hasattr(self, 'page') and self.page:
                self.page.close()
                self.page = None
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】清理页面时出错: {e}")
        
        try:
            if hasattr(self, 'context') and self.context:
                self.context.close()
                self.context = None
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】清理上下文时出错: {e}")
        
        try:
            if hasattr(self, 'browser') and self.browser:
                self.browser.close()
                self.browser = None
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】清理浏览器时出错: {e}")
        
        try:
            if hasattr(self, 'playwright') and self.playwright:
                self.playwright.stop()
                self.playwright = None
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】清理Playwright时出错: {e}")
    
    def _load_success_history(self) -> List[Dict[str, Any]]:
        """加载历史成功数据"""
        try:
            if not os.path.exists(self.success_history_file):
                return []
            
            with open(self.success_history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
                logger.info(f"【{self.pure_user_id}】加载历史成功数据: {len(history)}条记录")
                return history
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】加载历史数据失败: {e}")
            return []
    
    def _save_success_record(self, trajectory_data: Dict[str, Any]):
        """保存成功记录"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.success_history_file), exist_ok=True)
            
            # 加载现有历史
            history = self._load_success_history()
            
            # 添加新记录 - 只保存必要参数，不保存完整轨迹点（节省内存和磁盘空间）
            record = {
                "timestamp": time.time(),
                "user_id": self.pure_user_id,
                "distance": trajectory_data.get("distance", 0),
                "total_steps": trajectory_data.get("total_steps", 0),
                "base_delay": trajectory_data.get("base_delay", 0),
                "jitter_x_range": trajectory_data.get("jitter_x_range", [0, 0]),
                "jitter_y_range": trajectory_data.get("jitter_y_range", [0, 0]),
                "slow_factor": trajectory_data.get("slow_factor", 0),
                "acceleration_phase": trajectory_data.get("acceleration_phase", 0),
                "fast_phase": trajectory_data.get("fast_phase", 0),
                "slow_start_ratio": trajectory_data.get("slow_start_ratio", 0),
                # 【优化】不再保存完整轨迹点，节省 90% 存储空间
                # "trajectory_points": trajectory_data.get("trajectory_points", []),
                "trajectory_point_count": len(trajectory_data.get("trajectory_points", [])),  # 只记录数量
                "final_left_px": trajectory_data.get("final_left_px", 0),
                "completion_used": trajectory_data.get("completion_used", False),
                "completion_steps": trajectory_data.get("completion_steps", 0),
                "success": True
            }
            
            history.append(record)
            
            # 只保留最近100条成功记录
            if len(history) > 100:
                history = history[-100:]
            
            # 保存到文件
            with open(self.success_history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            
            logger.info(f"【{self.pure_user_id}】保存成功记录: 距离{record['distance']}px, 步数{record['total_steps']}, 轨迹点{record['trajectory_point_count']}个")
            
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】保存成功记录失败: {e}")
    
    def _optimize_trajectory_params(self) -> Dict[str, Any]:
        """基于历史成功数据优化轨迹参数"""
        try:
            if not self.enable_learning:
                return self.trajectory_params
            
            history = self._load_success_history()
            if len(history) < 3:  # 至少需要3条成功记录才开始优化
                logger.info(f"【{self.pure_user_id}】历史成功数据不足({len(history)}条)，使用默认参数")
                return self.trajectory_params
            
            # 计算成功记录的平均值
            total_steps_list = [record["total_steps"] for record in history]
            base_delay_list = [record["base_delay"] for record in history]
            slow_factor_list = [record["slow_factor"] for record in history]
            acceleration_phase_list = [record["acceleration_phase"] for record in history]
            fast_phase_list = [record["fast_phase"] for record in history]
            slow_start_ratio_list = [record["slow_start_ratio"] for record in history]
            
            # 基于完整轨迹数据的学习
            completion_usage_rate = 0
            avg_completion_steps = 0
            trajectory_length_stats = []
            
            if len(history) > 0:
                # 计算补全使用率
                completion_used_count = sum(1 for record in history if record.get("completion_used", False))
                completion_usage_rate = completion_used_count / len(history)
                
                # 计算平均补全步数
                completion_steps_list = [record.get("completion_steps", 0) for record in history if record.get("completion_used", False)]
                if completion_steps_list:
                    avg_completion_steps = sum(completion_steps_list) / len(completion_steps_list)
                
                # 分析轨迹长度分布
                trajectory_lengths = [len(record.get("trajectory_points", [])) for record in history]
                if trajectory_lengths:
                    trajectory_length_stats = [min(trajectory_lengths), max(trajectory_lengths), sum(trajectory_lengths) / len(trajectory_lengths)]
            
            # 计算平均值和标准差
            def safe_avg(values):
                return sum(values) / len(values) if values else 0
            
            def safe_std(values):
                if len(values) < 2:
                    return 0
                avg = safe_avg(values)
                variance = sum((x - avg) ** 2 for x in values) / len(values)
                return variance ** 0.5
            
            # 优化参数 - 真实人类模式（优先真实度而非速度）
            # 计算步数范围（确保最小值 < 最大值）
            steps_min = max(70, int(safe_avg(total_steps_list) - safe_std(total_steps_list) * 0.8))
            steps_max = min(95, int(safe_avg(total_steps_list) + safe_std(total_steps_list) * 0.8))
            if steps_min >= steps_max:
                steps_min = 75
                steps_max = 90
            
            # 计算延迟范围（确保最小值 < 最大值）
            # 下界与默认值保持一致，否则学习态会把实际成功的节奏又拉回慢档
            delay_min = max(0.007, safe_avg(base_delay_list) - safe_std(base_delay_list) * 0.6)
            delay_max = min(0.030, safe_avg(base_delay_list) + safe_std(base_delay_list) * 0.6)
            if delay_min >= delay_max:
                delay_min = 0.008
                delay_max = 0.012
            
            # 计算慢速因子范围（确保最小值 < 最大值）
            slow_min = max(5, int(safe_avg(slow_factor_list) - safe_std(slow_factor_list)))
            slow_max = min(20, int(safe_avg(slow_factor_list) + safe_std(slow_factor_list)))
            if slow_min >= slow_max:
                slow_min = 8
                slow_max = 15
            
            optimized_params = {
                "total_steps_range": [steps_min, steps_max],
                "base_delay_range": [delay_min, delay_max],
                "jitter_x_range": [-3, 12],  # 保持固定范围
                "jitter_y_range": [-2, 12],  # 保持固定范围
                "slow_factor_range": [slow_min, slow_max],
                "acceleration_phase": max(0.08, min(0.12, safe_avg(acceleration_phase_list))),
                "fast_phase": max(0.7, min(0.8, safe_avg(fast_phase_list))),
                "slow_start_ratio_base": max(0.98, min(1.02, safe_avg(slow_start_ratio_list))),
                "completion_usage_rate": completion_usage_rate,
                "avg_completion_steps": avg_completion_steps,
                "trajectory_length_stats": trajectory_length_stats,
                "learning_enabled": True
            }
            
            logger.info(f"【{self.pure_user_id}】基于{len(history)}条成功记录优化轨迹参数: 步数{optimized_params['total_steps_range']}, 延迟{optimized_params['base_delay_range']}")

            return optimized_params
            
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】优化轨迹参数失败: {e}")
            return self.trajectory_params
    
    def _get_cookies_after_success(self):
        """滑块验证成功后获取cookie"""
        try:
            logger.info(f"【{self.pure_user_id}】开始获取滑块验证成功后的页面cookie...")
            
            # 检查当前页面URL
            current_url = self.page.url
            logger.info(f"【{self.pure_user_id}】当前页面URL: {current_url}")
            
            # 检查页面标题
            page_title = self.page.title()
            logger.info(f"【{self.pure_user_id}】当前页面标题: {page_title}")
            
            # 等待一下确保cookie完全更新
            time.sleep(1)
            
            # 获取浏览器中的所有cookie
            cookies = self.context.cookies()
            
            if cookies:
                # 将cookie转换为字典格式
                new_cookies = {}
                for cookie in cookies:
                    new_cookies[cookie['name']] = cookie['value']
                
                logger.info(f"【{self.pure_user_id}】滑块验证成功后已获取cookie，共{len(new_cookies)}个cookie")
                
                # 记录所有cookie的详细信息
                logger.info(f"【{self.pure_user_id}】获取到的所有cookie: {list(new_cookies.keys())}")
                
                # 只提取x5sec相关的cookie
                filtered_cookies = {}
                
                # 筛选出x5相关的cookies（包括x5sec, x5step等）
                for cookie_name, cookie_value in new_cookies.items():
                    cookie_name_lower = cookie_name.lower()
                    if cookie_name_lower.startswith('x5') or 'x5sec' in cookie_name_lower:
                        filtered_cookies[cookie_name] = cookie_value
                        logger.info(f"【{self.pure_user_id}】x5相关cookie已获取: {cookie_name} = {cookie_value}")
                
                logger.info(f"【{self.pure_user_id}】找到{len(filtered_cookies)}个x5相关cookies: {list(filtered_cookies.keys())}")
                
                if filtered_cookies:
                    logger.info(f"【{self.pure_user_id}】返回过滤后的x5相关cookie: {list(filtered_cookies.keys())}")
                    return filtered_cookies
                else:
                    logger.warning(f"【{self.pure_user_id}】未找到x5相关cookie")
                    return None
            else:
                logger.warning(f"【{self.pure_user_id}】未获取到任何cookie")
                return None
                
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】获取滑块验证成功后的cookie失败: {str(e)}")
            return None
    
    def _save_cookies_to_file(self, cookies):
        """保存cookie到文件"""
        try:
            # 确保目录存在
            cookie_dir = f"slider_cookies/{self.user_id}"
            os.makedirs(cookie_dir, exist_ok=True)
            
            # 保存cookie到JSON文件
            cookie_file = f"{cookie_dir}/cookies_{int(time.time())}.json"
            with open(cookie_file, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            
            logger.info(f"【{self.pure_user_id}】Cookie已保存到文件: {cookie_file}")
            
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】保存cookie到文件失败: {str(e)}")
    
    def _get_random_browser_features(self):
        """获取随机浏览器特征"""
        # 随机选择窗口大小（使用更大的尺寸以适应最大化）
        window_sizes = [
            "1920,1080", "1920,1200", "2560,1440", "1680,1050", "1600,900"
        ]
        
        # 随机选择语言
        languages = [
            ("zh-CN", "zh-CN,zh;q=0.9,en;q=0.8"),
            ("zh-CN", "zh-CN,zh;q=0.9"),
            ("zh-CN", "zh-CN,zh;q=0.8,en;q=0.6")
        ]
        
        # 随机选择用户代理
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ]
        
        window_size = random.choice(window_sizes)
        lang, accept_lang = random.choice(languages)
        user_agent = random.choice(user_agents)
        
        # 解析窗口大小
        width, height = map(int, window_size.split(','))
        
        return {
            'window_size': window_size,
            'lang': lang,
            'accept_lang': accept_lang,
            'user_agent': user_agent,
            'locale': lang,
            'viewport_width': width,
            'viewport_height': height,
            'device_scale_factor': random.choice([1.0, 1.25, 1.5]),
            'is_mobile': False,
            'has_touch': False,
            'timezone_id': 'Asia/Shanghai'
        }
    
    def _get_stealth_script(self, browser_features):
        """获取增强反检测脚本"""
        return f"""
            // 隐藏webdriver属性
            Object.defineProperty(navigator, 'webdriver', {{
                get: () => undefined,
            }});
            
            // 隐藏自动化相关属性
            delete navigator.__proto__.webdriver;
            delete window.navigator.webdriver;
            delete window.navigator.__proto__.webdriver;
            
            // 模拟真实浏览器环境
            window.chrome = {{
                runtime: {{}},
                loadTimes: function() {{}},
                csi: function() {{}},
                app: {{}}
            }};
            
            // 覆盖plugins - 随机化
            const pluginCount = {random.randint(3, 8)};
            Object.defineProperty(navigator, 'plugins', {{
                get: () => Array.from({{length: pluginCount}}, (_, i) => ({{
                    name: 'Plugin' + i,
                    description: 'Plugin ' + i
                }})),
            }});
            
            // 覆盖languages
            Object.defineProperty(navigator, 'languages', {{
                get: () => ['{browser_features['locale']}', 'zh', 'en'],
            }});
            
            // 模拟真实的屏幕信息
            Object.defineProperty(screen, 'availWidth', {{ get: () => {browser_features['viewport_width']} }});
            Object.defineProperty(screen, 'availHeight', {{ get: () => {browser_features['viewport_height'] - 40} }});
            Object.defineProperty(screen, 'width', {{ get: () => {browser_features['viewport_width']} }});
            Object.defineProperty(screen, 'height', {{ get: () => {browser_features['viewport_height']} }});
            
            // 隐藏自动化检测 - 随机化硬件信息
            Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {random.choice([2, 4, 6, 8])} }});
            Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {random.choice([4, 8, 16])} }});
            
            // 模拟真实的时区
            Object.defineProperty(Intl.DateTimeFormat.prototype, 'resolvedOptions', {{
                value: function() {{
                    return {{ timeZone: '{browser_features['timezone_id']}' }};
                }}
            }});
            
            // 隐藏自动化痕迹
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            
            // 模拟有头模式的特征
            Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => 0 }});
            Object.defineProperty(navigator, 'platform', {{ get: () => 'Win32' }});
            Object.defineProperty(navigator, 'vendor', {{ get: () => 'Google Inc.' }});
            Object.defineProperty(navigator, 'vendorSub', {{ get: () => '' }});
            Object.defineProperty(navigator, 'productSub', {{ get: () => '20030107' }});
            
            // 模拟真实的连接信息
            Object.defineProperty(navigator, 'connection', {{
                get: () => ({{
                    effectiveType: "{random.choice(['3g', '4g', '5g'])}",
                    rtt: {random.randint(20, 100)},
                    downlink: {round(random.uniform(1, 10), 2)}
                }})
            }});
            
            // 隐藏无头模式特征
            Object.defineProperty(navigator, 'headless', {{ get: () => undefined }});
            Object.defineProperty(window, 'outerHeight', {{ get: () => {browser_features['viewport_height']} }});
            Object.defineProperty(window, 'outerWidth', {{ get: () => {browser_features['viewport_width']} }});
            
            // 模拟真实的媒体设备
            Object.defineProperty(navigator, 'mediaDevices', {{
                get: () => ({{
                    enumerateDevices: () => Promise.resolve([])
                }}),
            }});
            
            // 隐藏自动化检测特征
            Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
            Object.defineProperty(navigator, '__webdriver_script_fn', {{ get: () => undefined }});
            Object.defineProperty(navigator, '__webdriver_evaluate', {{ get: () => undefined }});
            Object.defineProperty(navigator, '__webdriver_unwrapped', {{ get: () => undefined }});
            Object.defineProperty(navigator, '__fxdriver_evaluate', {{ get: () => undefined }});
            Object.defineProperty(navigator, '__driver_evaluate', {{ get: () => undefined }});
            Object.defineProperty(navigator, '__webdriver_script_func', {{ get: () => undefined }});
            
            // 隐藏Playwright特定的对象
            delete window.playwright;
            delete window.__playwright;
            delete window.__pw_manual;
            delete window.__pw_original;
            
            // 模拟真实的用户代理
            Object.defineProperty(navigator, 'userAgent', {{
                get: () => '{browser_features['user_agent']}'
            }});
            
            // 隐藏自动化相关的全局变量
            delete window.webdriver;
            delete window.__webdriver_script_fn;
            delete window.__webdriver_evaluate;
            delete window.__webdriver_unwrapped;
            delete window.__fxdriver_evaluate;
            delete window.__driver_evaluate;
            delete window.__webdriver_script_func;
            delete window._selenium;
            delete window._phantom;
            delete window.callPhantom;
            delete window._phantom;
            delete window.phantom;
            delete window.Buffer;
            delete window.emit;
            delete window.spawn;
            
            // Canvas指纹随机化
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function() {{
                const context = this.getContext('2d');
                if (context) {{
                    const imageData = context.getImageData(0, 0, this.width, this.height);
                    const data = imageData.data;
                    for (let i = 0; i < data.length; i += 4) {{
                        if (Math.random() < 0.001) {{
                            data[i] = Math.floor(Math.random() * 256);
                        }}
                    }}
                    context.putImageData(imageData, 0, 0);
                }}
                return originalToDataURL.apply(this, arguments);
            }};
            
            // 音频指纹随机化
            const originalGetChannelData = AudioBuffer.prototype.getChannelData;
            AudioBuffer.prototype.getChannelData = function(channel) {{
                const data = originalGetChannelData.call(this, channel);
                for (let i = 0; i < data.length; i += 1000) {{
                    if (Math.random() < 0.01) {{
                        data[i] += Math.random() * 0.0001;
                    }}
                }}
                return data;
            }};
            
            // WebGL指纹随机化
            const originalGetParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) {{ // UNMASKED_VENDOR_WEBGL
                    return 'Intel Inc.';
                }}
                if (parameter === 37446) {{ // UNMASKED_RENDERER_WEBGL
                    return 'Intel Iris OpenGL Engine';
                }}
                return originalGetParameter.call(this, parameter);
            }};
            
            // 模拟真实的鼠标事件
            const originalAddEventListener = EventTarget.prototype.addEventListener;
            EventTarget.prototype.addEventListener = function(type, listener, options) {{
                if (type === 'mousedown' || type === 'mouseup' || type === 'mousemove') {{
                    const originalListener = listener;
                    listener = function(event) {{
                        setTimeout(() => originalListener.call(this, event), Math.random() * 10);
                    }};
                }}
                return originalAddEventListener.call(this, type, listener, options);
            }};
            
            // 随机化字体检测
            Object.defineProperty(document, 'fonts', {{
                get: () => ({{
                    ready: Promise.resolve(),
                    check: () => true,
                    load: () => Promise.resolve([])
                }})
            }});
            
            // 隐藏自动化检测的常见特征
            Object.defineProperty(window, 'chrome', {{
                get: () => ({{
                    runtime: {{}},
                    loadTimes: function() {{}},
                    csi: function() {{}},
                    app: {{}}
                }})
            }});
            
            // 增强鼠标移动轨迹记录
            let mouseMovements = [];
            let lastMouseTime = Date.now();
            document.addEventListener('mousemove', function(e) {{
                const now = Date.now();
                const timeDiff = now - lastMouseTime;
                mouseMovements.push({{
                    x: e.clientX,
                    y: e.clientY,
                    time: now,
                    timeDiff: timeDiff
                }});
                lastMouseTime = now;
                // 保持最近100个移动记录
                if (mouseMovements.length > 100) {{
                    mouseMovements.shift();
                }}
            }}, true);
            
            // 模拟真实的屏幕触摸点数
            Object.defineProperty(navigator, 'maxTouchPoints', {{
                get: () => {random.choice([0, 1, 5, 10])}
            }});
            
            // 模拟真实的电池API
            if (navigator.getBattery) {{
                const originalGetBattery = navigator.getBattery;
                navigator.getBattery = async function() {{
                    const battery = await originalGetBattery.call(navigator);
                    Object.defineProperty(battery, 'charging', {{ get: () => {random.choice(['true', 'false'])} }});
                    Object.defineProperty(battery, 'level', {{ get: () => {random.uniform(0.3, 0.95):.2f} }});
                    return battery;
                }};
            }}
            
            // 伪装鼠标移动加速度（反检测关键）
            let velocityProfile = [];
            window.addEventListener('mousemove', function(e) {{
                const now = performance.now();
                velocityProfile.push({{ x: e.clientX, y: e.clientY, t: now }});
                if (velocityProfile.length > 50) velocityProfile.shift();
            }}, true);
            
            // 伪装Permission API
            const originalQuery = Permissions.prototype.query;
            Permissions.prototype.query = function(parameters) {{
                if (parameters.name === 'notifications') {{
                    return Promise.resolve({{ state: 'denied' }});
                }}
                return originalQuery.apply(this, arguments);
            }};
            
            // 伪装Performance API
            const originalNow = Performance.prototype.now;
            Performance.prototype.now = function() {{
                return originalNow.call(this) + Math.random() * 0.1;
            }};
            
            // 伪装Date API（添加微小随机偏移）
            const OriginalDate = Date;
            Date = function(...args) {{
                if (args.length === 0) {{
                    const date = new OriginalDate();
                    const offset = Math.floor(Math.random() * 3) - 1; // -1到1毫秒
                    return new OriginalDate(date.getTime() + offset);
                }}
                return new OriginalDate(...args);
            }};
            Date.prototype = OriginalDate.prototype;
            Date.now = function() {{
                return OriginalDate.now() + Math.floor(Math.random() * 3) - 1;
            }};
            
            // 伪装RTCPeerConnection（WebRTC指纹）
            if (window.RTCPeerConnection) {{
                const originalRTC = window.RTCPeerConnection;
                window.RTCPeerConnection = function(...args) {{
                    const pc = new originalRTC(...args);
                    const originalCreateOffer = pc.createOffer;
                    pc.createOffer = function(...args) {{
                        return originalCreateOffer.apply(this, args).then(offer => {{
                            // 修改SDP指纹
                            offer.sdp = offer.sdp.replace(/a=fingerprint:.*\\r\\n/g, 
                                `a=fingerprint:sha-256 ${{Array.from({{length:64}}, ()=>Math.floor(Math.random()*16).toString(16)).join('')}}\\r\\n`);
                            return offer;
                        }});
                    }};
                    return pc;
                }};
            }}
            
            // 伪装 Notification 权限（防止被检测为自动化）
            Object.defineProperty(Notification, 'permission', {{
                get: function() {{
                    return ['default', 'granted', 'denied'][Math.floor(Math.random() * 3)];
                }}
            }});
            
            // 伪装 Connection API（添加网络信息变化）
            if (navigator.connection) {{
                const connection = navigator.connection;
                const originalEffectiveType = connection.effectiveType;
                Object.defineProperty(connection, 'effectiveType', {{
                    get: function() {{
                        const types = ['slow-2g', '2g', '3g', '4g'];
                        return types[Math.floor(Math.random() * types.length)];
                    }}
                }});
                Object.defineProperty(connection, 'rtt', {{
                    get: function() {{
                        return Math.floor(Math.random() * 100) + 50; // 50-150ms
                    }}
                }});
                Object.defineProperty(connection, 'downlink', {{
                    get: function() {{
                        return Math.random() * 10 + 1; // 1-11 Mbps
                    }}
                }});
            }}
            
            // 伪装 DeviceMemory（设备内存）
            Object.defineProperty(navigator, 'deviceMemory', {{
                get: function() {{
                    const memories = [2, 4, 8, 16];
                    return memories[Math.floor(Math.random() * memories.length)];
                }}
            }});
            
            // 伪装 HardwareConcurrency（CPU核心数）
            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: function() {{
                    const cores = [2, 4, 6, 8, 12, 16];
                    return cores[Math.floor(Math.random() * cores.length)];
                }}
            }});
            
            // 伪装 maxTouchPoints（触摸点数量）
            Object.defineProperty(navigator, 'maxTouchPoints', {{
                get: function() {{
                    return Math.floor(Math.random() * 5) + 1; // 1-5个触摸点
                }}
            }});
            
            // 伪装 DoNotTrack
            Object.defineProperty(navigator, 'doNotTrack', {{
                get: function() {{
                    return ['1', '0', 'unspecified', null][Math.floor(Math.random() * 4)];
                }}
            }});
            
            // 伪装 Geolocation（添加微小延迟和误差）
            if (navigator.geolocation) {{
                const originalGetCurrentPosition = navigator.geolocation.getCurrentPosition;
                navigator.geolocation.getCurrentPosition = function(success, error, options) {{
                    const wrappedSuccess = function(position) {{
                        // 添加微小的位置偏移（模拟真实GPS误差）
                        const offset = Math.random() * 0.001;
                        position.coords.latitude += offset;
                        position.coords.longitude += offset;
                        success(position);
                    }};
                    // 添加随机延迟
                    setTimeout(() => {{
                        originalGetCurrentPosition.call(this, wrappedSuccess, error, options);
                    }}, Math.random() * 100);
                }};
            }}
            
            // 伪装 Clipboard API（防止检测剪贴板访问模式）
            if (navigator.clipboard) {{
                const originalReadText = navigator.clipboard.readText;
                navigator.clipboard.readText = async function() {{
                    // 添加微小延迟
                    await new Promise(resolve => setTimeout(resolve, Math.random() * 50));
                    return originalReadText.call(this);
                }};
            }}
            
            // 🔑 关键优化：隐藏CDP运行时特征
            Object.defineProperty(navigator, 'webdriver', {{
                get: () => undefined
            }});
            
            // 🔑 隐藏自动化控制特征
            window.navigator.chrome = {{
                runtime: {{}},
                loadTimes: function() {{}},
                csi: function() {{}},
                app: {{}}
            }};
            
            // 🔑 隐藏Playwright特征
            delete window.__playwright;
            delete window.__pw_manual;
            delete window.__PW_inspect;
            
            // 🔑 伪装chrome对象（防止检测headless）
            if (!window.chrome) {{
                window.chrome = {{}};
            }}
            window.chrome.runtime = {{
                id: undefined,
                sendMessage: function() {{}},
                connect: function() {{}}
            }};
            
            // 🔑 伪装Permissions API
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({{ state: Notification.permission }}) :
                    originalQuery(parameters)
            );
            
            // 🔑 覆盖Function.prototype.toString以隐藏代理
            const oldToString = Function.prototype.toString;
            Function.prototype.toString = function() {{
                if (this === navigator.permissions.query) {{
                    return 'function query() {{ [native code] }}';
                }}
                return oldToString.call(this);
            }};
        """
    
    def _bezier_curve(self, p0, p1, p2, p3, t):
        """三次贝塞尔曲线 - 生成更自然的轨迹"""
        return (1-t)**3 * p0 + 3*(1-t)**2*t * p1 + 3*(1-t)*t**2 * p2 + t**3 * p3
    
    def _easing_function(self, t, mode='easeOutQuad'):
        """缓动函数 - 模拟真实人类滑动的速度变化"""
        if mode == 'easeOutQuad':
            return t * (2 - t)
        elif mode == 'easeInOutCubic':
            return 4*t**3 if t < 0.5 else 1 - pow(-2*t + 2, 3) / 2
        elif mode == 'easeOutBack':
            c1 = 1.70158
            c3 = c1 + 1
            return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)
        else:
            return t
    
    def _generate_physics_trajectory(self, distance: float):
        """基于最小急动度模型生成轨迹 - 拟人模式

        风控拦截的是行为特征而非落点精度，因此这里对齐人手的真实运动学：
        1. 最小急动度曲线（10t³-15t⁴+6t⁵）：钟形速度包络，起步加速、末段减速
        2. 百级采样点 + 20-30ms 步进：单次拖拽耗时 2.5-4 秒
        3. 双向微颤 + Y 轴漂移：人手无法走出单向直线
        4. 轻微超调后回拉修正：人眼确认到位需要一次微调
        5. 随机迟疑：低概率插入额外停顿，破坏等间隔节奏
        """
        trajectory = []
        params = self._optimize_trajectory_params()

        steps_range = params.get("total_steps_range", [110, 130])
        delay_range = params.get("base_delay_range", [0.020, 0.030])
        jitter_x_range = params.get("jitter_x_range", [-1, 1])
        jitter_y_range = params.get("jitter_y_range", [-3, 3])

        steps = random.randint(int(steps_range[0]), int(steps_range[1]))
        base_delay = random.uniform(float(delay_range[0]), float(delay_range[1]))

        # 甩出量取轨道长度的 40%-85%：手感是"用力甩到底"而非"精确对准"
        overshoot = random.uniform(distance * 0.4, distance * 0.85)
        peak_distance = distance + overshoot

        # Y 轴走非水平弧线：人手绕手腕转动，起落点不在同一高度，
        # 且整条轨迹是斜的 —— 纯水平移动是机器特征。
        drift_direction = random.choice([-1, 1])
        arc_amplitude = random.uniform(6.0, 16.0)      # 弧线高度
        tilt = drift_direction * random.uniform(4.0, 12.0)  # 整体倾斜，终点比起点高/低

        # 主行程：最小急动度曲线
        for i in range(steps):
            progress = (i + 1) / steps
            # 10t³-15t⁴+6t⁵，速度呈钟形，两端平滑
            eased = 10 * progress ** 3 - 15 * progress ** 4 + 6 * progress ** 5

            x = peak_distance * eased + random.uniform(*jitter_x_range)
            # 弧线 + 线性倾斜 + 高频微颤，三者叠加成非水平轨迹
            y = (drift_direction * arc_amplitude * math.sin(progress * math.pi)
                 + tilt * progress
                 + random.uniform(*jitter_y_range) * 0.4)

            delay = base_delay * random.uniform(0.85, 1.15)
            # 约 4% 概率出现迟疑，打破等间隔节奏
            if random.random() < 0.04:
                delay += random.uniform(0.02, 0.05)

            trajectory.append((x, y, delay))

        # 回弹：手指松力后滑块被弹回一点，再小幅晃动稳定。
        # 这是甩到底时的自然物理反应，与"精确回拉修正"完全不同。
        rebound = random.uniform(6.0, 18.0)
        rebound_steps = random.randint(3, 5)
        last_y = trajectory[-1][1] if trajectory else 0.0
        for i in range(rebound_steps):
            progress = (i + 1) / rebound_steps
            x = peak_distance - rebound * progress + random.uniform(-0.8, 0.8)
            y = last_y + random.uniform(-1.5, 1.5)
            trajectory.append((x, y, random.uniform(0.015, 0.035)))

        # 稳定：回弹后小幅抖动，模拟手停住但仍有生理震颤
        settle_x = peak_distance - rebound
        for _ in range(random.randint(2, 3)):
            trajectory.append((
                settle_x + random.uniform(-1.2, 1.2),
                last_y + random.uniform(-1.2, 1.2),
                random.uniform(0.02, 0.045),
            ))

        self.last_trajectory_params = {
            "base_delay": base_delay,
            "jitter_x_range": jitter_x_range,
            "jitter_y_range": jitter_y_range,
            "overshoot": overshoot,
            "correction_steps": rebound_steps,
        }

        logger.info(
            f"【{self.pure_user_id}】拟人模式：{len(trajectory)}步，"
            f"耗时{sum(p[2] for p in trajectory):.2f}秒，"
            f"甩出{overshoot:.0f}px后回弹{rebound:.0f}px"
        )
        return trajectory
    
    def generate_human_trajectory(self, distance: float):
        """生成人类化滑动轨迹 - 最小急动度运动模型"""
        try:
            logger.info(f"【{self.pure_user_id}】📐 使用拟人运动模型生成轨迹")
            trajectory = self._generate_physics_trajectory(distance)

            logger.debug(f"【{self.pure_user_id}】拟人模式：超调后回拉修正")

            # 保存轨迹数据（字段需与 _save_success_record 对齐，否则学习态取不到值）
            last_params = self.last_trajectory_params or {}
            self.current_trajectory_data = {
                "distance": distance,
                "model": "physics_human",
                "total_steps": len(trajectory),
                "trajectory_points": trajectory.copy(),
                "base_delay": last_params.get("base_delay", 0),
                "jitter_x_range": last_params.get("jitter_x_range", [0, 0]),
                "jitter_y_range": last_params.get("jitter_y_range", [0, 0]),
                "slow_factor": self.trajectory_params.get("slow_factor_range", [0, 0])[0],
                "acceleration_phase": self.trajectory_params.get("acceleration_phase", 0),
                "fast_phase": self.trajectory_params.get("fast_phase", 0),
                "slow_start_ratio": self.trajectory_params.get("slow_start_ratio_base", 0),
                "final_left_px": 0,
                "completion_used": False,
                "completion_steps": last_params.get("correction_steps", 0)
            }

            return trajectory

        except Exception as e:
            logger.error(f"【{self.pure_user_id}】生成轨迹时出错: {str(e)}")
            return []
    
    def simulate_slide(self, slider_button: ElementHandle, trajectory):
        """模拟滑动 - 优化版本（基于高成功率策略）"""
        try:
            logger.info(f"【{self.pure_user_id}】开始优化滑动模拟...")
            
            # 等待页面稳定
            time.sleep(random.uniform(0.1, 0.3))
            
            # 获取滑块按钮中心位置
            button_box = slider_button.bounding_box()
            if not button_box:
                logger.error(f"【{self.pure_user_id}】无法获取滑块按钮位置")
                return False
            
            start_x = button_box["x"] + button_box["width"] / 2
            start_y = button_box["y"] + button_box["height"] / 2
            logger.debug(f"【{self.pure_user_id}】滑块位置: ({start_x}, {start_y})")
            
            # 第一阶段：移动到滑块附近（模拟人类寻找滑块）
            try:
                # 先移动到滑块附近（稍微偏左）
                offset_x = random.uniform(-30, -10)
                offset_y = random.uniform(-15, 15)
                self.page.mouse.move(
                    start_x + offset_x,
                    start_y + offset_y,
                    steps=random.randint(5, 10)
                )
                time.sleep(random.uniform(0.15, 0.3))
                
                # 再精确移动到滑块中心
                self.page.mouse.move(
                    start_x,
                    start_y,
                    steps=random.randint(3, 6)
                )
                time.sleep(random.uniform(0.1, 0.25))
            except Exception as e:
                logger.warning(f"【{self.pure_user_id}】移动到滑块失败: {e}，继续尝试")
            
            # 第二阶段：悬停在滑块上
            try:
                slider_button.hover(timeout=2000)
                time.sleep(random.uniform(0.1, 0.3))
            except Exception as e:
                logger.warning(f"【{self.pure_user_id}】悬停滑块失败: {e}")
            
            # 第三阶段：按下鼠标
            try:
                self.page.mouse.move(start_x, start_y)
                time.sleep(random.uniform(0.05, 0.15))
                self.page.mouse.down()
                time.sleep(random.uniform(0.05, 0.15))
            except Exception as e:
                logger.error(f"【{self.pure_user_id}】按下鼠标失败: {e}")
                return False
            
            # 第四阶段：执行滑动轨迹
            try:
                start_time = time.time()
                current_x = start_x
                current_y = start_y
                last_x = start_x  # 用于按位移量拆分移动步数
                
                # 执行拖动轨迹
                for i, (x, y, delay) in enumerate(trajectory):
                    # 更新当前位置
                    current_x = start_x + x
                    current_y = start_y + y
                    
                    # 移动鼠标。
                    # 轨迹本身已有 70-95 个密集采样点，相邻点间距仅几 px，
                    # movementX 天然落在真人区间，无需再用 steps 细分 ——
                    # steps=N 会产生 N 次独立 CDP 往返，把 1.3 秒的甩动拖成 4 秒。
                    self.page.mouse.move(current_x, current_y)
                    last_x = current_x
                    
                    # 延迟（添加微小随机变化）
                    actual_delay = delay * random.uniform(0.9, 1.1)
                    time.sleep(actual_delay)
                    
                    # 记录最终位置
                    if i == len(trajectory) - 1:
                        try:
                            current_style = slider_button.get_attribute("style")
                            if current_style and "left:" in current_style:
                                import re
                                left_match = re.search(r'left:\s*([^;]+)', current_style)
                                if left_match:
                                    left_value = left_match.group(1).strip()
                                    left_px = float(left_value.replace('px', ''))
                                    if hasattr(self, 'current_trajectory_data'):
                                        self.current_trajectory_data["final_left_px"] = left_px
                                    logger.info(f"【{self.pure_user_id}】滑动完成: {len(trajectory)}步 - 最终位置: {left_value}")
                        except:
                            pass
                
                # 🎨 刮刮乐特殊处理：在目标位置停顿观察
                is_scratch = self.is_scratch_captcha()
                if is_scratch:
                    pause_duration = random.uniform(0.3, 0.5)
                    logger.warning(f"【{self.pure_user_id}】🎨 刮刮乐模式：在目标位置停顿{pause_duration:.2f}秒观察...")
                    time.sleep(pause_duration)
                
                # 释放前停顿：人手到位后会先确认再松开，立即释放是脚本特征
                time.sleep(random.uniform(0.12, 0.28))
                self.page.mouse.up()
                time.sleep(random.uniform(0.05, 0.12))

                # 注意：此处不再补发合成 click 事件。
                # dispatchEvent 造出的事件 isTrusted 为 false，是风控的直接判定依据，
                # 而 mouse.up() 本身已由 CDP 产生可信的原生事件序列。

                elapsed_time = time.time() - start_time
                logger.info(f"【{self.pure_user_id}】滑动完成: 耗时={elapsed_time:.2f}秒, 最终位置=({current_x:.1f}, {current_y:.1f})")
                
                return True
                
            except Exception as e:
                logger.error(f"【{self.pure_user_id}】执行滑动轨迹失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # 确保释放鼠标
                try:
                    self.page.mouse.up()
                except:
                    pass
                return False
            
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】滑动模拟异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _simulate_human_page_behavior(self):
        """模拟人类在验证页面的前置行为 - 极速模式已禁用"""
        # 极速模式：不进行页面行为模拟，直接开始滑动
        pass
    
    def find_slider_elements(self, fast_mode=False):
        """查找滑块元素（支持在主页面和所有frame中查找）
        
        Args:
            fast_mode: 快速模式，不使用wait_for_selector，减少等待时间（当已确认滑块存在时使用）
        """
        try:
            # 快速等待页面稳定（快速模式下跳过）
            if not fast_mode:
                time.sleep(0.1)
            
            # ===== 【优化】优先在 frames 中快速查找最常见的滑块组合 =====
            # 根据实际日志，滑块按钮和轨道通常在同一个 frame 中
            # 按钮: #nc_1_n1z, 轨道: #nc_1_n1t
            logger.debug(f"【{self.pure_user_id}】优先在frames中快速查找常见滑块组合...")
            try:
                frames = self.page.frames
                for idx, frame in enumerate(frames):
                    try:
                        # 优先查找最常见的按钮选择器
                        button_element = frame.query_selector("#nc_1_n1z")
                        if button_element and button_element.is_visible():
                            # 在同一个 frame 中查找轨道
                            track_element = frame.query_selector("#nc_1_n1t")
                            if track_element and track_element.is_visible():
                                # 找到容器（可以用按钮或其他选择器）
                                container_element = frame.query_selector("#baxia-dialog-content")
                                if not container_element:
                                    container_element = frame.query_selector(".nc-container")
                                if not container_element:
                                    # 如果找不到容器，用按钮作为容器标识
                                    container_element = button_element
                                
                                logger.info(f"【{self.pure_user_id}】✅ 在Frame {idx} 快速找到完整滑块组合！")
                                logger.info(f"【{self.pure_user_id}】  - 按钮: #nc_1_n1z")
                                logger.info(f"【{self.pure_user_id}】  - 轨道: #nc_1_n1t")
                                
                                # 保存frame引用
                                self._detected_slider_frame = frame
                                return container_element, button_element, track_element
                    except Exception as e:
                        logger.debug(f"【{self.pure_user_id}】Frame {idx} 快速查找失败: {e}")
                        continue
            except Exception as e:
                logger.debug(f"【{self.pure_user_id}】frames 快速查找出错: {e}")
            
            # ===== 如果快速查找失败，使用原来的完整查找逻辑 =====
            logger.debug(f"【{self.pure_user_id}】快速查找未成功，使用完整查找逻辑...")
            
            # 定义滑块容器选择器（支持多种类型）
            container_selectors = [
                "#nc_1_n1z",  # 滑块按钮也可以作为容器标识
                "#baxia-dialog-content",
                ".nc-container",
                ".nc_wrapper",
                ".nc_scale",
                "[class*='nc-container']",
                # 刮刮乐类型滑块
                "#nocaptcha",
                ".scratch-captcha-container",
                ".scratch-captcha-question-bg",
                # 通用选择器
                "[class*='slider']",
                "[class*='captcha']"
            ]
            
            # 查找滑块容器
            slider_container = None
            found_frame = None
            
            # 如果检测时已经知道滑块在哪个frame中，直接在该frame中查找
            if hasattr(self, '_detected_slider_frame'):
                if self._detected_slider_frame is not None:
                    # 在已知的frame中查找
                    logger.info(f"【{self.pure_user_id}】已知滑块在frame中，直接在frame中查找...")
                    target_frame = self._detected_slider_frame
                    for selector in container_selectors:
                        try:
                            element = target_frame.query_selector(selector)
                            if element:
                                try:
                                    if element.is_visible():
                                        logger.info(f"【{self.pure_user_id}】在已知Frame中找到滑块容器: {selector}")
                                        slider_container = element
                                        found_frame = target_frame
                                        break
                                except:
                                    # 如果无法检查可见性，也尝试使用
                                    logger.info(f"【{self.pure_user_id}】在已知Frame中找到滑块容器（无法检查可见性）: {selector}")
                                    slider_container = element
                                    found_frame = target_frame
                                    break
                        except Exception as e:
                            logger.debug(f"【{self.pure_user_id}】已知Frame选择器 {selector} 未找到: {e}")
                            continue
                else:
                    # _detected_slider_frame 是 None，表示在主页面
                    logger.info(f"【{self.pure_user_id}】已知滑块在主页面，直接在主页面查找...")
                    for selector in container_selectors:
                        try:
                            element = self.page.wait_for_selector(selector, timeout=1000)
                            if element:
                                logger.info(f"【{self.pure_user_id}】在已知主页面找到滑块容器: {selector}")
                                slider_container = element
                                found_frame = self.page
                                break
                        except Exception as e:
                            logger.debug(f"【{self.pure_user_id}】主页面选择器 {selector} 未找到: {e}")
                            continue
            
            # 如果已知位置中没找到，或者没有已知位置，先尝试在主页面查找
            if not slider_container:
                for selector in container_selectors:
                    try:
                        element = self.page.wait_for_selector(selector, timeout=1000)  # 减少超时时间，快速跳过
                        if element:
                            logger.info(f"【{self.pure_user_id}】在主页面找到滑块容器: {selector}")
                            slider_container = element
                            found_frame = self.page
                            break
                    except Exception as e:
                        logger.debug(f"【{self.pure_user_id}】主页面选择器 {selector} 未找到: {e}")
                        continue
            
            # 如果主页面没找到，在所有frame中查找
            if not slider_container and self.page:
                try:
                    frames = self.page.frames
                    logger.info(f"【{self.pure_user_id}】主页面未找到滑块，开始在所有frame中查找（共{len(frames)}个frame）...")
                    for idx, frame in enumerate(frames):
                        try:
                            for selector in container_selectors:
                                try:
                                    # 在frame中使用query_selector，因为frame可能不支持wait_for_selector
                                    element = frame.query_selector(selector)
                                    if element:
                                        # 检查元素是否可见
                                        try:
                                            if element.is_visible():
                                                logger.info(f"【{self.pure_user_id}】在Frame {idx} 找到滑块容器: {selector}")
                                                slider_container = element
                                                found_frame = frame
                                                break
                                        except:
                                            # 如果无法检查可见性，也尝试使用
                                            logger.info(f"【{self.pure_user_id}】在Frame {idx} 找到滑块容器（无法检查可见性）: {selector}")
                                            slider_container = element
                                            found_frame = frame
                                            break
                                except Exception as e:
                                    logger.debug(f"【{self.pure_user_id}】Frame {idx} 选择器 {selector} 未找到: {e}")
                                    continue
                            if slider_container:
                                break
                        except Exception as e:
                            logger.debug(f"【{self.pure_user_id}】检查Frame {idx} 时出错: {e}")
                            continue
                except Exception as e:
                    logger.debug(f"【{self.pure_user_id}】获取frame列表时出错: {e}")
            
            if not slider_container:
                logger.error(f"【{self.pure_user_id}】未找到任何滑块容器（主页面和所有frame都已检查）")
                return None, None, None
            
            # 定义滑块按钮选择器（支持多种类型）
            button_selectors = [
                # nc 系列滑块
                "#nc_1_n1z",
                ".nc_iconfont",
                ".btn_slide",
                # 刮刮乐类型滑块
                "#scratch-captcha-btn",
                ".scratch-captcha-slider .button",
                # 通用选择器
                "[class*='slider']",
                "[class*='btn']",
                "[role='button']"
            ]
            
            # 查找滑块按钮（在找到容器的同一个frame中查找）
            slider_button = None
            search_frame = found_frame if found_frame and found_frame != self.page else self.page
            
            # 如果容器是在主页面找到的，按钮也应该在主页面查找
            # 如果容器是在frame中找到的，按钮也应该在同一个frame中查找
            for selector in button_selectors:
                try:
                    element = None
                    if fast_mode:
                        # 快速模式：直接使用 query_selector，不等待
                        element = search_frame.query_selector(selector)
                    else:
                        # 正常模式：使用 wait_for_selector
                        if search_frame == self.page:
                            element = self.page.wait_for_selector(selector, timeout=3000)
                        else:
                            # 在frame中先尝试wait_for_selector（如果支持）
                            try:
                                # 尝试使用wait_for_selector（Playwright的frame支持）
                                element = search_frame.wait_for_selector(selector, timeout=3000)
                            except:
                                # 如果不支持wait_for_selector，使用query_selector并等待
                                time.sleep(0.5)  # 等待元素加载
                                element = search_frame.query_selector(selector)
                    
                    if element:
                        # 检查元素是否可见，但不要因为不可见就放弃
                        try:
                            is_visible = element.is_visible()
                            if not is_visible:
                                logger.debug(f"【{self.pure_user_id}】找到元素但不可见: {selector}，继续尝试其他选择器")
                                element = None
                        except Exception as vis_e:
                            # 如果无法检查可见性，仍然使用该元素
                            logger.debug(f"【{self.pure_user_id}】无法检查元素可见性: {vis_e}，继续使用该元素")
                            pass
                    
                    if element:
                        frame_info = "主页面" if search_frame == self.page else f"Frame"
                        logger.info(f"【{self.pure_user_id}】在{frame_info}找到滑块按钮: {selector}")
                        slider_button = element
                        break
                except Exception as e:
                    logger.debug(f"【{self.pure_user_id}】选择器 {selector} 未找到: {e}")
                    continue
            
            # 如果在找到容器的frame中没找到按钮，尝试在所有frame中查找
            # 无论容器是在主页面还是frame中找到的，如果按钮找不到，都应该在所有frame中查找
            if not slider_button:
                logger.warning(f"【{self.pure_user_id}】在找到容器的位置未找到按钮，尝试在所有frame中查找...")
                try:
                    frames = self.page.frames
                    for idx, frame in enumerate(frames):
                        # 如果容器是在frame中找到的，跳过已经检查过的frame
                        if found_frame and found_frame != self.page and frame == found_frame:
                            continue
                        # 如果容器是在主页面找到的，跳过主页面（因为已经检查过了）
                        if found_frame == self.page and frame == self.page:
                            continue
                            
                        for selector in button_selectors:
                            try:
                                element = None
                                if fast_mode:
                                    # 快速模式：直接使用 query_selector
                                    element = frame.query_selector(selector)
                                else:
                                    # 正常模式：先尝试wait_for_selector
                                    try:
                                        element = frame.wait_for_selector(selector, timeout=2000)
                                    except:
                                        time.sleep(0.3)  # 等待元素加载
                                        element = frame.query_selector(selector)
                                
                                if element:
                                    try:
                                        is_visible = element.is_visible()
                                        if is_visible:
                                            logger.info(f"【{self.pure_user_id}】在Frame {idx} 找到滑块按钮: {selector}")
                                            slider_button = element
                                            found_frame = frame  # 更新found_frame
                                            break
                                        else:
                                            logger.debug(f"【{self.pure_user_id}】在Frame {idx} 找到元素但不可见: {selector}")
                                    except:
                                        # 如果无法检查可见性，仍然使用该元素
                                        logger.info(f"【{self.pure_user_id}】在Frame {idx} 找到滑块按钮（无法检查可见性）: {selector}")
                                        slider_button = element
                                        found_frame = frame  # 更新found_frame
                                        break
                            except Exception as e:
                                logger.debug(f"【{self.pure_user_id}】Frame {idx} 选择器 {selector} 查找失败: {e}")
                                continue
                        if slider_button:
                            break
                except Exception as e:
                    logger.debug(f"【{self.pure_user_id}】在所有frame中查找按钮时出错: {e}")
            
            # 如果还是没找到，尝试在主页面查找（如果之前没在主页面查找过）
            if not slider_button and found_frame != self.page:
                logger.warning(f"【{self.pure_user_id}】在所有frame中未找到按钮，尝试在主页面查找...")
                for selector in button_selectors:
                    try:
                        element = None
                        if fast_mode:
                            # 快速模式：直接使用 query_selector
                            element = self.page.query_selector(selector)
                        else:
                            # 正常模式：使用 wait_for_selector
                            element = self.page.wait_for_selector(selector, timeout=2000)
                        
                        if element:
                            try:
                                if element.is_visible():
                                    logger.info(f"【{self.pure_user_id}】在主页面找到滑块按钮: {selector}")
                                    slider_button = element
                                    found_frame = self.page  # 更新found_frame
                                    break
                                else:
                                    logger.debug(f"【{self.pure_user_id}】在主页面找到元素但不可见: {selector}")
                            except:
                                # 如果无法检查可见性，仍然使用该元素
                                logger.info(f"【{self.pure_user_id}】在主页面找到滑块按钮（无法检查可见性）: {selector}")
                                slider_button = element
                                found_frame = self.page  # 更新found_frame
                                break
                    except Exception as e:
                        logger.debug(f"【{self.pure_user_id}】主页面选择器 {selector} 查找失败: {e}")
                        continue
            
            # 如果还是没找到，尝试使用更宽松的查找方式（不检查可见性）
            if not slider_button:
                logger.warning(f"【{self.pure_user_id}】使用宽松模式查找滑块按钮（不检查可见性）...")
                # 先在所有frame中查找
                try:
                    frames = self.page.frames
                    for idx, frame in enumerate(frames):
                        for selector in button_selectors[:3]:  # 只使用前3个最常用的选择器
                            try:
                                element = frame.query_selector(selector)
                                if element:
                                    logger.info(f"【{self.pure_user_id}】在Frame {idx} 找到滑块按钮（宽松模式）: {selector}")
                                    slider_button = element
                                    found_frame = frame
                                    break
                            except:
                                continue
                        if slider_button:
                            break
                except:
                    pass
                
                # 如果还是没找到，在主页面查找
                if not slider_button:
                    for selector in button_selectors[:3]:
                        try:
                            element = self.page.query_selector(selector)
                            if element:
                                logger.info(f"【{self.pure_user_id}】在主页面找到滑块按钮（宽松模式）: {selector}")
                                slider_button = element
                                found_frame = self.page
                                break
                        except:
                            continue
            
            if not slider_button:
                logger.error(f"【{self.pure_user_id}】未找到任何滑块按钮（主页面和所有frame都已检查，包括宽松模式）")
                return slider_container, None, None
            
            # 定义滑块轨道选择器
            track_selectors = [
                "#nc_1_n1t",
                ".nc_scale",
                ".nc_1_n1t",
                "[class*='track']",
                "[class*='scale']"
            ]
            
            # 查找滑块轨道（在找到按钮的同一个frame中查找，因为按钮和轨道应该在同一个位置）
            slider_track = None
            # 使用找到按钮的frame来查找轨道
            track_search_frame = found_frame if found_frame and found_frame != self.page else self.page
            
            for selector in track_selectors:
                try:
                    element = None
                    if fast_mode:
                        # 快速模式：直接使用 query_selector
                        element = track_search_frame.query_selector(selector)
                    else:
                        # 正常模式：使用 wait_for_selector
                        if track_search_frame == self.page:
                            element = self.page.wait_for_selector(selector, timeout=3000)
                        else:
                            # 在frame中使用query_selector
                            element = track_search_frame.query_selector(selector)
                    
                    if element:
                        try:
                            if not element.is_visible():
                                element = None
                        except:
                            pass
                    
                    if element:
                        frame_info = "主页面" if track_search_frame == self.page else f"Frame"
                        logger.info(f"【{self.pure_user_id}】在{frame_info}找到滑块轨道: {selector}")
                        slider_track = element
                        break
                except Exception as e:
                    logger.debug(f"【{self.pure_user_id}】选择器 {selector} 未找到: {e}")
                    continue
            
            # 如果在找到按钮的frame中没找到轨道，先点击frame激活它，然后再查找
            if not slider_track and track_search_frame and track_search_frame != self.page:
                logger.warning(f"【{self.pure_user_id}】在已知Frame中未找到轨道，尝试点击frame激活后再查找...")
                try:
                    # 点击frame以激活它，让轨道出现
                    # 尝试点击frame中的容器或按钮来激活
                    if slider_container:
                        try:
                            slider_container.click(timeout=1000)
                            logger.info(f"【{self.pure_user_id}】已点击滑块容器以激活frame")
                            time.sleep(0.3)  # 等待轨道出现
                        except:
                            pass
                    elif slider_button:
                        try:
                            slider_button.click(timeout=1000)
                            logger.info(f"【{self.pure_user_id}】已点击滑块按钮以激活frame")
                            time.sleep(0.3)  # 等待轨道出现
                        except:
                            pass
                    
                    # 再次在同一个frame中查找轨道
                    for selector in track_selectors:
                        try:
                            element = track_search_frame.query_selector(selector)
                            if element:
                                try:
                                    if element.is_visible():
                                        logger.info(f"【{self.pure_user_id}】点击frame后在Frame中找到滑块轨道: {selector}")
                                        slider_track = element
                                        break
                                except:
                                    # 如果无法检查可见性，也尝试使用
                                    logger.info(f"【{self.pure_user_id}】点击frame后在Frame中找到滑块轨道（无法检查可见性）: {selector}")
                                    slider_track = element
                                    break
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"【{self.pure_user_id}】点击frame后查找轨道时出错: {e}")
                
                # 如果点击frame后还是没找到，尝试在所有frame中查找
                if not slider_track:
                    logger.warning(f"【{self.pure_user_id}】点击frame后仍未找到轨道，尝试在所有frame中查找...")
                    try:
                        frames = self.page.frames
                        for idx, frame in enumerate(frames):
                            if frame == track_search_frame:
                                continue  # 跳过已经检查过的frame
                            for selector in track_selectors:
                                try:
                                    element = frame.query_selector(selector)
                                    if element:
                                        try:
                                            if element.is_visible():
                                                logger.info(f"【{self.pure_user_id}】在Frame {idx} 找到滑块轨道: {selector}")
                                                slider_track = element
                                                break
                                        except:
                                            pass
                                except:
                                    continue
                            if slider_track:
                                break
                    except Exception as e:
                        logger.debug(f"【{self.pure_user_id}】在所有frame中查找轨道时出错: {e}")
            
            # 如果还是没找到，尝试在主页面查找
            if not slider_track:
                logger.warning(f"【{self.pure_user_id}】在所有frame中未找到轨道，尝试在主页面查找...")
                for selector in track_selectors:
                    try:
                        element = self.page.wait_for_selector(selector, timeout=1000)
                        if element:
                            logger.info(f"【{self.pure_user_id}】在主页面找到滑块轨道: {selector}")
                            slider_track = element
                            break
                    except:
                        continue
            
            if not slider_track:
                logger.error(f"【{self.pure_user_id}】未找到任何滑块轨道（主页面和所有frame都已检查）")
                return slider_container, slider_button, None
            
            # 保存找到滑块的frame引用，供后续验证使用
            if found_frame and found_frame != self.page:
                self._detected_slider_frame = found_frame
                logger.info(f"【{self.pure_user_id}】保存滑块frame引用，供后续验证使用")
            elif found_frame == self.page:
                # 如果是在主页面找到的，设置为None
                self._detected_slider_frame = None
            
            return slider_container, slider_button, slider_track
            
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】查找滑块元素时出错: {str(e)}")
            return None, None, None
    
    def is_scratch_captcha(self):
        """检测是否为刮刮乐类型验证码"""
        try:
            page_content = self.page.content()
            # 检测刮刮乐特征（更精确的判断）
            # 必须包含明确的刮刮乐特征词
            scratch_required = ['scratch-captcha', 'scratch-captcha-btn', 'scratch-captcha-slider']
            has_scratch_feature = any(keyword in page_content for keyword in scratch_required)
            
            # 或者包含刮刮乐的指令文字
            scratch_instructions = ['Release the slider', 'pillows', 'fully appears', 'after', 'appears']
            has_scratch_instruction = sum(1 for keyword in scratch_instructions if keyword in page_content) >= 2
            
            is_scratch = has_scratch_feature or has_scratch_instruction
            
            if is_scratch:
                logger.info(f"【{self.pure_user_id}】🎨 检测到刮刮乐类型验证码")
            
            return is_scratch
        except Exception as e:
            logger.debug(f"【{self.pure_user_id}】检测刮刮乐类型时出错: {e}")
            return False
    
    def calculate_slide_distance(self, slider_button: ElementHandle, slider_track: ElementHandle):
        """计算滑动距离 - 增强精度，支持刮刮乐"""
        try:
            # 获取滑块按钮位置和大小
            button_box = slider_button.bounding_box()
            if not button_box:
                logger.error(f"【{self.pure_user_id}】无法获取滑块按钮位置")
                return 0
            
            # 获取滑块轨道位置和大小
            track_box = slider_track.bounding_box()
            if not track_box:
                logger.error(f"【{self.pure_user_id}】无法获取滑块轨道位置")
                return 0
            
            # 🎨 检测是否为刮刮乐类型
            is_scratch = self.is_scratch_captcha()
            
            # 🔑 关键优化1：使用JavaScript获取更精确的尺寸（避免DPI缩放影响）
            try:
                precise_distance = self.page.evaluate("""
                    () => {
                        const button = document.querySelector('#nc_1_n1z') || document.querySelector('.nc_iconfont');
                        const track = document.querySelector('#nc_1_n1t') || document.querySelector('.nc_scale');
                        if (button && track) {
                            const buttonRect = button.getBoundingClientRect();
                            const trackRect = track.getBoundingClientRect();
                            // 计算实际可滑动距离（考虑padding和边距）
                            return trackRect.width - buttonRect.width;
                        }
                        return null;
                    }
                """)
                
                if precise_distance and precise_distance > 0:
                    logger.info(f"【{self.pure_user_id}】使用JavaScript精确计算滑动距离: {precise_distance:.2f}px")
                    
                    # 🎨 刮刮乐特殊处理：只滑动75-85%的距离
                    if is_scratch:
                        scratch_ratio = random.uniform(0.25, 0.35)
                        final_distance = precise_distance * scratch_ratio
                        logger.warning(f"【{self.pure_user_id}】🎨 刮刮乐模式：滑动{scratch_ratio*100:.1f}%距离 ({final_distance:.2f}px)")
                        return final_distance
                    
                    # 🔑 关键优化2：添加微小随机偏移（防止每次都完全相同）
                    # 真人操作时，滑动距离会有微小偏差
                    random_offset = random.uniform(-0.5, 0.5)
                    return precise_distance + random_offset
            except Exception as e:
                logger.debug(f"【{self.pure_user_id}】JavaScript精确计算失败，使用后备方案: {e}")
            
            # 后备方案：使用bounding_box计算
            slide_distance = track_box["width"] - button_box["width"]
            
            # 🎨 刮刮乐特殊处理：只滑动75-85%的距离
            if is_scratch:
                scratch_ratio = random.uniform(0.25, 0.35)
                slide_distance = slide_distance * scratch_ratio
                logger.warning(f"【{self.pure_user_id}】🎨 刮刮乐模式：滑动{scratch_ratio*100:.1f}%距离 ({slide_distance:.2f}px)")
            else:
                # 添加微小随机偏移
                random_offset = random.uniform(-0.5, 0.5)
                slide_distance += random_offset
            
            logger.info(f"【{self.pure_user_id}】计算滑动距离: {slide_distance:.2f}px (轨道宽度: {track_box['width']}px, 滑块宽度: {button_box['width']}px)")
            
            return slide_distance
            
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】计算滑动距离时出错: {str(e)}")
            return 0
    
    def check_verification_success_fast(self, slider_button: ElementHandle):
        """检查验证结果 - 极速模式

        Returns:
            tuple: (success: bool, retry_element: ElementHandle or None)
        """
        try:
            logger.info(f"【{self.pure_user_id}】检查验证结果（极速模式）...")

            # 确定滑块所在的frame（如果已知）
            target_frame = None
            if hasattr(self, '_detected_slider_frame') and self._detected_slider_frame is not None:
                target_frame = self._detected_slider_frame
                logger.info(f"【{self.pure_user_id}】在已知Frame中检查验证结果")
                # 先检查frame是否还存在（未被分离）
                try:
                    # 尝试访问frame的属性来检查是否被分离
                    _ = target_frame.url if hasattr(target_frame, 'url') else None
                except Exception as frame_check_error:
                    error_msg = str(frame_check_error).lower()
                    # 如果frame被分离（detached），说明验证成功，容器已消失
                    if 'detached' in error_msg or 'disconnected' in error_msg:
                        logger.info(f"【{self.pure_user_id}】✓ Frame已被分离，验证成功")
                        return True, None
            else:
                target_frame = self.page
                logger.info(f"【{self.pure_user_id}】在主页面检查验证结果")

            # 等待一小段时间让验证结果出现
            time.sleep(0.3)

            # 核心逻辑：首先检查frame容器状态
            # 如果容器消失，直接返回成功；如果容器还在，检查失败提示
            def check_container_status():
                """检查容器状态，返回(存在, 可见)"""
                try:
                    if target_frame == self.page:
                        container = self.page.query_selector(".nc-container")
                    else:
                        # 检查frame是否还存在（未被分离）
                        try:
                            # 再次检查frame是否被分离
                            _ = target_frame.url if hasattr(target_frame, 'url') else None
                            container = target_frame.query_selector(".nc-container")
                        except Exception as frame_error:
                            error_msg = str(frame_error).lower()
                            # 如果frame被分离（detached），说明容器已经不存在
                            if 'detached' in error_msg or 'disconnected' in error_msg:
                                logger.info(f"【{self.pure_user_id}】Frame已被分离，容器不存在")
                                return (False, False)
                            # 其他错误，继续尝试
                            raise frame_error

                    if container is None:
                        return (False, False)  # 容器不存在

                    try:
                        is_visible = container.is_visible()
                        return (True, is_visible)
                    except Exception as vis_error:
                        vis_error_msg = str(vis_error).lower()
                        # 如果元素被分离，说明容器不存在
                        if 'detached' in vis_error_msg or 'disconnected' in vis_error_msg:
                            logger.info(f"【{self.pure_user_id}】容器元素已被分离，容器不存在")
                            return (False, False)
                        # 无法检查可见性，假设存在且可见
                        return (True, True)
                except Exception as e:
                    error_msg = str(e).lower()
                    # 如果frame或元素被分离，说明容器不存在
                    if 'detached' in error_msg or 'disconnected' in error_msg:
                        logger.info(f"【{self.pure_user_id}】Frame或容器已被分离，容器不存在")
                        return (False, False)
                    # 其他错误，保守处理，假设存在
                    logger.warning(f"【{self.pure_user_id}】检查容器状态时出错: {e}")
                    return (True, True)

            # 第一次检查容器状态
            container_exists, container_visible = check_container_status()

            # 如果容器不存在或不可见，直接返回成功
            if not container_exists or not container_visible:
                logger.info(f"【{self.pure_user_id}】✓ 滑块容器已消失（不存在或不可见），验证成功")
                return True, None

            # 容器还在，需要等待更长时间并检查失败提示
            logger.info(f"【{self.pure_user_id}】滑块容器仍存在且可见，等待验证结果...")
            time.sleep(1.2)  # 等待验证结果

            # 再次检查容器状态
            container_exists, container_visible = check_container_status()

            # 如果容器消失了，返回成功
            if not container_exists or not container_visible:
                logger.info(f"【{self.pure_user_id}】✓ 滑块容器已消失，验证成功")
                return True, None

            # 容器还在，检查是否有验证失败提示
            logger.info(f"【{self.pure_user_id}】滑块容器仍存在，检查验证失败提示...")
            has_failure, retry_element = self.check_verification_failure()

            if has_failure:
                logger.warning(f"【{self.pure_user_id}】检测到验证失败提示，验证失败")
                return False, retry_element

            # 容器还在，但没有失败提示，可能还在验证中或验证失败
            # 再等待一小段时间后再次检查
            time.sleep(0.5)
            container_exists, container_visible = check_container_status()

            if not container_exists or not container_visible:
                logger.info(f"【{self.pure_user_id}】✓ 滑块容器已消失，验证成功")
                return True, None

            # 容器仍然存在，且没有失败提示，可能是验证失败但没有显示失败提示
            # 或者验证还在进行中，但为了不无限等待，返回失败
            logger.warning(f"【{self.pure_user_id}】滑块容器仍存在且可见，且未检测到失败提示，但验证可能失败")
            return False, None

        except Exception as e:
            logger.error(f"【{self.pure_user_id}】检查验证结果时出错: {str(e)}")
            return False, None
    
    def check_page_changed(self):
        """检查页面是否改变"""
        try:
            # 检查页面标题是否改变
            current_title = self.page.title()
            logger.info(f"【{self.pure_user_id}】当前页面标题: {current_title}")
            
            # 如果标题不再是验证码相关，说明页面已改变
            if "captcha" not in current_title.lower() and "验证" not in current_title and "拦截" not in current_title:
                logger.info(f"【{self.pure_user_id}】页面标题已改变，验证成功")
                return True
            
            # 检查URL是否改变
            current_url = self.page.url
            logger.info(f"【{self.pure_user_id}】当前页面URL: {current_url}")
            
            # 如果URL不再包含验证码相关参数，说明页面已改变
            if "captcha" not in current_url.lower() and "action=captcha" not in current_url:
                logger.info(f"【{self.pure_user_id}】页面URL已改变，验证成功")
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】检查页面改变时出错: {e}")
            return False
    
    def check_verification_failure(self):
        """检查验证失败提示"""
        try:
            logger.info(f"【{self.pure_user_id}】检查验证失败提示...")
            
            # 等待一下让失败提示出现（由于调用前已经等待了，这里等待时间缩短）
            time.sleep(1.5)
            
            # 检查页面内容中是否包含验证失败相关文字
            page_content = self.page.content()
            failure_keywords = [
                "验证失败",
                "点击框体重试", 
                "重试",
                "失败",
                "请重试",
                "验证码错误",
                "滑动验证失败"
            ]
            
            found_failure = False
            for keyword in failure_keywords:
                if keyword in page_content:
                    logger.info(f"【{self.pure_user_id}】页面内容包含失败关键词: {keyword}")
                    found_failure = True
                    break
            
            if found_failure:
                logger.info(f"【{self.pure_user_id}】检测到验证失败关键词，验证失败")
                # 必须返回二元组：调用方按 (has_failure, retry_element) 解包。
                # 此处若返回裸 True 会抛 unpack 异常，导致重试按钮丢失、滑块无法重置，
                # 后续尝试便会因控件停留在失败态而找不到轨道。
                # 关键词命中时尚未定位元素，重试按钮交由 click_retry_button 自行查找。
                return True, None
            
            # 检查各种可能的验证失败提示元素
            failure_selectors = [
                "text=验证失败，点击框体重试",
                "text=验证失败",
                "text=点击框体重试", 
                "text=重试",
                ".nc-lang-cnt",
                "[class*='retry']",
                "[class*='fail']",
                "[class*='error']",
                ".captcha-tips",
                "#captcha-loading",
                ".nc_1_nocaptcha",
                ".nc_wrapper",
                ".nc-container"
            ]
            
            retry_button = None
            for selector in failure_selectors:
                try:
                    element = self.page.query_selector(selector)
                    if element and element.is_visible():
                        # 获取元素文本内容
                        element_text = ""
                        try:
                            element_text = element.text_content()
                        except:
                            pass
                        
                        logger.info(f"【{self.pure_user_id}】找到验证失败提示: {selector}, 文本: {element_text}")
                        retry_button = element
                        break
                except:
                    continue
            
            if retry_button:
                logger.info(f"【{self.pure_user_id}】检测到验证失败提示元素，验证失败")
                return True, retry_button  # 返回找到的重试按钮元素
            else:
                logger.info(f"【{self.pure_user_id}】未找到验证失败提示，可能验证成功了")
                return False, None

        except Exception as e:
            logger.error(f"【{self.pure_user_id}】检查验证失败时出错: {e}")
            return False, None

    def click_retry_button(self, retry_element=None):
        """点击重试按钮以重置滑块验证

        Args:
            retry_element: 重试按钮元素（如果已知），如果为None则自动查找

        Returns:
            bool: 成功点击返回True，否则返回False
        """
        try:
            logger.info(f"【{self.pure_user_id}】尝试点击重试按钮...")

            # 如果没有传入重试元素，先查找
            if retry_element is None:
                # 定义重试按钮选择器（按优先级排序）
                retry_selectors = [
                    "text=验证失败，点击框体重试",  # 完整文本匹配
                    "text=点击框体重试",  # 部分文本匹配
                    ".nc-lang-cnt",  # 通用提示容器
                    "[class*='retry']",  # 包含retry的类名
                    ".captcha-tips",  # 验证码提示
                ]

                for selector in retry_selectors:
                    try:
                        # 在主页面和所有frame中查找
                        frames_to_check = [self.page] + self.page.frames
                        for frame in frames_to_check:
                            try:
                                element = frame.query_selector(selector)
                                if element and element.is_visible():
                                    element_text = element.text_content() or ""
                                    logger.info(f"【{self.pure_user_id}】找到重试元素: {selector}, 文本: {element_text}")

                                    # 检查是否包含"重试"相关文本
                                    if "重试" in element_text or "retry" in element_text.lower():
                                        retry_element = element
                                        break
                            except:
                                continue

                        if retry_element:
                            break
                    except:
                        continue

            # 如果找到了重试元素，点击它
            if retry_element:
                try:
                    # 使用JavaScript点击（更可靠）
                    retry_element.evaluate("el => el.click()")
                    logger.success(f"【{self.pure_user_id}】✅ 已点击重试按钮（JavaScript点击）")

                    # 等待滑块重置
                    time.sleep(random.uniform(0.5, 1.0))
                    return True

                except Exception as js_error:
                    logger.warning(f"【{self.pure_user_id}】JavaScript点击失败: {js_error}，尝试鼠标点击")

                    try:
                        # 备用方案：使用鼠标点击
                        retry_element.click()
                        logger.success(f"【{self.pure_user_id}】✅ 已点击重试按钮（鼠标点击）")

                        # 等待滑块重置
                        time.sleep(random.uniform(0.5, 1.0))
                        return True
                    except Exception as mouse_error:
                        logger.error(f"【{self.pure_user_id}】鼠标点击也失败: {mouse_error}")
                        return False
            else:
                logger.warning(f"【{self.pure_user_id}】未找到重试按钮，无法点击")
                return False

        except Exception as e:
            logger.error(f"【{self.pure_user_id}】点击重试按钮时出错: {e}")
            return False

    def _analyze_failure(self, attempt: int, slide_distance: float, trajectory_data: dict):
        """分析失败原因并记录"""
        try:
            failure_reason = {
                "attempt": attempt,
                "slide_distance": slide_distance,
                "total_steps": trajectory_data.get("total_steps", 0),
                "base_delay": trajectory_data.get("base_delay", 0),
                "final_left_px": trajectory_data.get("final_left_px", 0),
                "completion_used": trajectory_data.get("completion_used", False),
                "timestamp": datetime.now().isoformat()
            }
            
            # 记录失败信息
            logger.warning(f"【{self.pure_user_id}】第{attempt}次尝试失败 - 距离:{slide_distance}px, "
                         f"步数:{failure_reason['total_steps']}, "
                         f"最终位置:{failure_reason['final_left_px']}px")
            
            return failure_reason
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】分析失败原因时出错: {e}")
            return {}
    
    def solve_slider(self, max_retries: int = 3, fast_mode: bool = False):
        """处理滑块验证（极速模式）
        
        Args:
            max_retries: 最大重试次数（默认3次，因为同一个页面连续失败3次后就不会成功了）
            fast_mode: 快速查找模式（当已确认滑块存在时使用，减少等待时间）
        """
        failure_records = []
        current_strategy = 'human_like'  # 拟人策略（旧的 ultra_fast 统计已作废，不再混算）
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"【{self.pure_user_id}】开始处理滑块验证... (第{attempt}/{max_retries}次尝试)")
                
                # 如果不是第一次尝试，短暂等待后重试
                if attempt > 1:
                    retry_delay = random.uniform(0.5, 1.0)  # 减少等待时间
                    logger.info(f"【{self.pure_user_id}】等待{retry_delay:.2f}秒后重试...")
                    time.sleep(retry_delay)
                    
                    # 不刷新页面，直接在原来的frame中重试
                    # 保留frame引用，让重试时可以直接使用原来的frame查找滑块
                    if hasattr(self, '_detected_slider_frame'):
                        frame_info = "主页面" if self._detected_slider_frame is None else "Frame"
                        logger.info(f"【{self.pure_user_id}】保留frame引用，将在原来的{frame_info}中重试")
                    else:
                        logger.info(f"【{self.pure_user_id}】未找到frame引用，将重新检测滑块位置")
                
                # 1. 查找滑块元素（使用快速模式）
                slider_container, slider_button, slider_track = self.find_slider_elements(fast_mode=fast_mode)
                if not all([slider_container, slider_button, slider_track]):
                    logger.error(f"【{self.pure_user_id}】滑块元素查找失败")
                    continue
                
                # 2. 计算滑动距离
                slide_distance = self.calculate_slide_distance(slider_button, slider_track)
                if slide_distance <= 0:
                    logger.error(f"【{self.pure_user_id}】滑动距离计算失败")
                    continue
                
                # 3. 生成人类化轨迹
                trajectory = self.generate_human_trajectory(slide_distance)
                if not trajectory:
                    logger.error(f"【{self.pure_user_id}】轨迹生成失败")
                    continue
                
                # 4. 模拟滑动
                if not self.simulate_slide(slider_button, trajectory):
                    logger.error(f"【{self.pure_user_id}】滑动模拟失败")
                    continue
                
                # 5. 检查验证结果（极速模式）
                verification_success, retry_element = self.check_verification_success_fast(slider_button)
                if verification_success:
                    logger.info(f"【{self.pure_user_id}】✅ 滑块验证成功! (第{attempt}次尝试)")

                    # 📊 记录策略成功
                    strategy_stats.record_attempt(attempt, current_strategy, success=True)
                    logger.info(f"【{self.pure_user_id}】📊 记录策略: 第{attempt}次-{current_strategy}策略-成功")

                    # 保存成功记录用于学习
                    if self.enable_learning and hasattr(self, 'current_trajectory_data'):
                        self._save_success_record(self.current_trajectory_data)
                        logger.info(f"【{self.pure_user_id}】已保存成功记录用于参数优化")

                    # 如果不是第一次就成功，记录重试信息
                    if attempt > 1:
                        logger.info(f"【{self.pure_user_id}】经过{attempt}次尝试后验证成功")

                    # 输出当前统计摘要
                    strategy_stats.log_summary()

                    return True
                else:
                    logger.warning(f"【{self.pure_user_id}】❌ 第{attempt}次验证失败")

                    # 📊 记录策略失败
                    strategy_stats.record_attempt(attempt, current_strategy, success=False)
                    logger.info(f"【{self.pure_user_id}】📊 记录策略: 第{attempt}次-{current_strategy}策略-失败")

                    # 分析失败原因
                    if hasattr(self, 'current_trajectory_data'):
                        failure_info = self._analyze_failure(attempt, slide_distance, self.current_trajectory_data)
                        failure_records.append(failure_info)

                    # 🔑 如果不是最后一次尝试，重置滑块后继续
                    if attempt < max_retries:
                        reset_ok = False
                        # 优先点重试按钮，这是最轻量的重置方式
                        if retry_element is not None:
                            logger.info(f"【{self.pure_user_id}】检测到重试按钮，点击重置滑块...")
                            if self.click_retry_button(retry_element):
                                logger.success(f"【{self.pure_user_id}】✅ 已点击重试按钮，滑块已重置")
                                time.sleep(random.uniform(0.3, 0.6))
                                reset_ok = True
                            else:
                                logger.warning(f"【{self.pure_user_id}】点击重试按钮失败")

                        # 没有重试按钮（或点击无效）时重新加载惩罚页。
                        # 验证失败后 nc 控件会停在失败态：轨道消失、按钮不可拖，
                        # 此时直接重试等于在坏掉的控件上空拖 —— 实测第3次成功率 0%。
                        # 重新导航能拿到一个全新的滑块，让重试真正有意义。
                        if not reset_ok and self._current_url:
                            try:
                                logger.info(f"【{self.pure_user_id}】控件已失效，重新加载验证页...")
                                self.page.goto(
                                    self._current_url,
                                    wait_until="domcontentloaded",
                                    timeout=20000,
                                )
                                time.sleep(random.uniform(1.0, 1.8))
                                # 页面重建后原有的 frame 引用全部失效，必须清掉
                                self.slider_frame = None
                                logger.success(f"【{self.pure_user_id}】✅ 验证页已重新加载")
                            except Exception as reload_err:
                                logger.warning(
                                    f"【{self.pure_user_id}】重新加载验证页失败: {reload_err}"
                                )
                        continue
                
            except Exception as e:
                logger.error(f"【{self.pure_user_id}】第{attempt}次处理滑块验证时出错: {str(e)}")
                if attempt < max_retries:
                    continue
        
        # 所有尝试都失败了
        logger.error(f"【{self.pure_user_id}】滑块验证失败，已尝试{max_retries}次")
        
        # 输出失败分析摘要
        if failure_records:
            logger.info(f"【{self.pure_user_id}】失败分析摘要:")
            for record in failure_records:
                logger.info(f"  - 第{record['attempt']}次: 距离{record['slide_distance']}px, "
                          f"步数{record['total_steps']}, 最终位置{record['final_left_px']}px")
        
        # 输出当前统计摘要
        strategy_stats.log_summary()
        
        return False
    
    def close_browser(self):
        """安全关闭浏览器并清理资源"""
        logger.info(f"【{self.pure_user_id}】开始清理资源...")
        
        # 清理页面
        try:
            if hasattr(self, 'page') and self.page:
                self.page.close()
                logger.debug(f"【{self.pure_user_id}】页面已关闭")
                self.page = None
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】关闭页面时出错: {e}")
        
        # 清理上下文
        try:
            if hasattr(self, 'context') and self.context:
                self.context.close()
                logger.debug(f"【{self.pure_user_id}】上下文已关闭")
                self.context = None
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】关闭上下文时出错: {e}")
        
        # 【修复】同步关闭浏览器，确保资源真正释放
        try:
            if hasattr(self, 'browser') and self.browser:
                self.browser.close()  # 直接同步关闭，不使用异步任务
                logger.info(f"【{self.pure_user_id}】浏览器已关闭")
                self.browser = None
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】关闭浏览器时出错: {e}")
        
        # 【修复】同步停止Playwright，确保资源真正释放
        try:
            if hasattr(self, 'playwright') and self.playwright:
                self.playwright.stop()  # 直接同步停止，不使用异步任务
                logger.info(f"【{self.pure_user_id}】Playwright已停止")
                self.playwright = None
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】停止Playwright时出错: {e}")
        
        # 清理临时目录
        try:
            if hasattr(self, 'temp_dir') and self.temp_dir:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                logger.debug(f"【{self.pure_user_id}】临时目录已清理: {self.temp_dir}")
                self.temp_dir = None  # 设置为None，防止重复清理
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】清理临时目录时出错: {e}")
        
        # 注销实例（最后执行，确保其他清理完成）
        try:
            concurrency_manager.unregister_instance(self.user_id)
            stats = concurrency_manager.get_stats()
            logger.info(f"【{self.pure_user_id}】实例已注销，当前并发: {stats['active_count']}/{stats['max_concurrent']}，等待队列: {stats['queue_length']}")
        except Exception as e:
            logger.warning(f"【{self.pure_user_id}】注销实例时出错: {e}")
        
        logger.info(f"【{self.pure_user_id}】资源清理完成")
    
    def __del__(self):
        """析构函数，确保资源释放（保险机制）"""
        try:
            # 检查是否有未关闭的浏览器
            if hasattr(self, 'browser') and self.browser:
                logger.warning(f"【{self.pure_user_id}】析构函数检测到未关闭的浏览器，执行清理")
                self.close_browser()
        except Exception as e:
            # 析构函数中不要抛出异常
            logger.debug(f"【{self.pure_user_id}】析构函数清理时出错: {e}")
    
    # ==================== Playwright 登录辅助方法 ====================
    
    def _check_login_success_by_element(self, page) -> bool:
        """通过页面元素检测登录是否成功
        
        Args:
            page: Page对象
        
        Returns:
            bool: 登录成功返回True，否则返回False
        """
        try:
            # 检查目标元素
            selector = '.rc-virtual-list-holder-inner'
            logger.info(f"【{self.pure_user_id}】========== 检查登录状态（通过页面元素） ==========")
            logger.info(f"【{self.pure_user_id}】检查选择器: {selector}")
            
            # 查找元素
            element = page.query_selector(selector)
            
            if element:
                # 获取元素的子元素数量
                child_count = element.evaluate('el => el.children.length')
                inner_html = element.inner_html()
                inner_text = element.inner_text() if element.is_visible() else ""
                
                logger.info(f"【{self.pure_user_id}】找到目标元素:")
                logger.info(f"【{self.pure_user_id}】  - 子元素数量: {child_count}")
                logger.info(f"【{self.pure_user_id}】  - 是否可见: {element.is_visible()}")
                logger.info(f"【{self.pure_user_id}】  - innerText长度: {len(inner_text)}")
                logger.info(f"【{self.pure_user_id}】  - innerHTML长度: {len(inner_html)}")
                
                # 判断是否有数据：子元素数量大于0
                if child_count > 0:
                    logger.success(f"【{self.pure_user_id}】✅ 登录成功！检测到列表有 {child_count} 个子元素")
                    logger.info(f"【{self.pure_user_id}】================================================")
                    return True
                else:
                    logger.debug(f"【{self.pure_user_id}】列表为空，登录未完成")
                    logger.info(f"【{self.pure_user_id}】================================================")
                    return False
            else:
                logger.debug(f"【{self.pure_user_id}】未找到目标元素: {selector}")
                logger.info(f"【{self.pure_user_id}】================================================")
                return False
                
        except Exception as e:
            logger.debug(f"【{self.pure_user_id}】检查登录状态时出错: {e}")
            import traceback
            logger.debug(f"【{self.pure_user_id}】错误堆栈: {traceback.format_exc()}")
            return False
    
    def _check_login_error(self, page) -> tuple:
        """检测登录是否出现错误（如账密错误）
        
        Args:
            page: Page对象
        
        Returns:
            tuple: (has_error, error_message) - 是否有错误，错误消息
        """
        try:
            logger.debug(f"【{self.pure_user_id}】检查登录错误...")
            
            # 检测账密错误
            error_selectors = [
                '.login-error-msg',  # 主要的错误消息类
                '[class*="error-msg"]',  # 包含error-msg的类
                'div:has-text("账密错误")',  # 包含"账密错误"文本的div
                'text=账密错误',  # 直接文本匹配
            ]
            
            # 在主页面和所有frame中查找
            frames_to_check = [page] + page.frames
            
            for frame in frames_to_check:
                try:
                    for selector in error_selectors:
                        try:
                            element = frame.query_selector(selector)
                            if element and element.is_visible():
                                error_text = element.inner_text()
                                logger.error(f"【{self.pure_user_id}】❌ 检测到登录错误: {error_text}")
                                return True, error_text
                        except:
                            continue
                            
                    # 也检查页面HTML中是否包含错误文本
                    try:
                        content = frame.content()
                        if '账密错误' in content or '账号密码错误' in content or '用户名或密码错误' in content:
                            logger.error(f"【{self.pure_user_id}】❌ 页面内容中检测到账密错误")
                            return True, "账密错误"
                    except:
                        pass
                        
                except:
                    continue
            
            return False, None
            
        except Exception as e:
            logger.debug(f"【{self.pure_user_id}】检查登录错误时出错: {e}")
            return False, None
    
    def _detect_qr_code_verification(self, page) -> tuple:
        """检测是否存在二维码/人脸验证（排除滑块验证）
        
        Args:
            page: Page对象
        
        Returns:
            tuple: (has_qr, qr_frame) - 是否有二维码/人脸验证，验证frame
                   (False, None) - 如果检测到滑块验证，会先处理滑块，然后返回
        """
        try:
            logger.info(f"【{self.pure_user_id}】检测二维码/人脸验证...")
            
            # 先检查是否是滑块验证，如果是滑块验证，立即处理并返回
            slider_selectors = [
                '#nc_1_n1z',
                '.nc-container',
                '.nc_scale',
                '.nc-wrapper',
                '.nc_iconfont',
                '[class*="nc_"]'
            ]
            
            # 在主页面和所有frame中检查滑块
            frames_to_check = [page] + list(page.frames)
            for frame in frames_to_check:
                try:
                    for selector in slider_selectors:
                        try:
                            element = frame.query_selector(selector)
                            if element and element.is_visible():
                                logger.info(f"【{self.pure_user_id}】检测到滑块验证元素，立即处理滑块: {selector}")
                                # 检测到滑块验证，记录是在哪个frame中找到的
                                frame_info = "主页面" if frame == page else f"Frame: {frame.url if hasattr(frame, 'url') else '未知'}"
                                logger.info(f"【{self.pure_user_id}】滑块元素位置: {frame_info}")
                                
                                # 保存找到滑块的frame，供find_slider_elements使用
                                # 如果是在frame中找到的，保存frame引用；如果在主页面找到，保存None
                                if frame == page:
                                    self._detected_slider_frame = None  # 主页面
                                else:
                                    self._detected_slider_frame = frame  # 保存frame引用
                                
                                # 检测到滑块验证，立即处理
                                logger.warning(f"【{self.pure_user_id}】检测到滑块验证，开始自动处理...")
                                slider_success = self.solve_slider(max_retries=3)
                                if slider_success:
                                    logger.success(f"【{self.pure_user_id}】✅ 滑块验证成功！")
                                    time.sleep(3)  # 等待滑块验证后的状态更新
                                else:
                                    # 3次失败后，刷新页面重试
                                    logger.warning(f"【{self.pure_user_id}】⚠️ 滑块处理3次都失败，刷新页面后重试...")
                                    try:
                                        self.page.reload(wait_until="domcontentloaded", timeout=30000)
                                        logger.info(f"【{self.pure_user_id}】✅ 页面刷新完成")
                                        time.sleep(2)
                                        slider_success = self.solve_slider(max_retries=3)
                                        if not slider_success:
                                            logger.error(f"【{self.pure_user_id}】❌ 刷新后滑块验证仍然失败")
                                        else:
                                            logger.success(f"【{self.pure_user_id}】✅ 刷新后滑块验证成功！")
                                            time.sleep(3)
                                    except Exception as e:
                                        logger.error(f"【{self.pure_user_id}】❌ 页面刷新失败: {e}")
                                
                                # 清理临时变量
                                if hasattr(self, '_detected_slider_frame'):
                                    delattr(self, '_detected_slider_frame')
                                
                                # 返回 False, None 表示不是二维码/人脸验证（已处理滑块）
                                return False, None
                        except:
                            continue
                except:
                    continue
            
            # 检测所有frames中的二维码/人脸验证
            # 首先检查是否有 alibaba-login-box iframe（人脸验证或短信验证）
            try:
                iframes = page.query_selector_all('iframe')
                for iframe in iframes:
                    try:
                        iframe_id = iframe.get_attribute('id')
                        if iframe_id == 'alibaba-login-box':
                            logger.info(f"【{self.pure_user_id}】✅ 检测到 alibaba-login-box iframe（人脸验证/短信验证）")
                            frame = iframe.content_frame()
                            if frame:
                                logger.info(f"【{self.pure_user_id}】人脸验证/短信验证Frame URL: {frame.url if hasattr(frame, 'url') else '未知'}")
                                
                                # 尝试自动点击"其他验证方式"，然后找到"通过拍摄脸部"的验证按钮
                                face_verify_url = self._get_face_verification_url(frame)
                                if face_verify_url:
                                    logger.info(f"【{self.pure_user_id}】✅ 获取到人脸验证链接: {face_verify_url}")
                                    
                                    # 截图并保存
                                    screenshot_path = None
                                    try:
                                        # 等待页面加载完成
                                        time.sleep(2)
                                        
                                        # 先删除该账号的旧截图
                                        import glob
                                        screenshots_dir = "static/uploads/images"
                                        os.makedirs(screenshots_dir, exist_ok=True)
                                        old_screenshots = glob.glob(os.path.join(screenshots_dir, f"face_verify_{self.pure_user_id}_*.jpg"))
                                        for old_file in old_screenshots:
                                            try:
                                                os.remove(old_file)
                                                logger.info(f"【{self.pure_user_id}】删除旧的验证截图: {old_file}")
                                            except Exception as e:
                                                logger.warning(f"【{self.pure_user_id}】删除旧截图失败: {e}")
                                        
                                        # 尝试截取iframe元素的截图
                                        screenshot_bytes = None
                                        try:
                                            # 获取iframe元素并截图
                                            iframe_element = page.query_selector('iframe#alibaba-login-box')
                                            if iframe_element:
                                                screenshot_bytes = iframe_element.screenshot()
                                                logger.info(f"【{self.pure_user_id}】已截取iframe元素")
                                            else:
                                                # 如果找不到iframe，截取整个页面
                                                screenshot_bytes = page.screenshot(full_page=False)
                                                logger.info(f"【{self.pure_user_id}】已截取整个页面")
                                        except Exception as e:
                                            logger.warning(f"【{self.pure_user_id}】截取iframe失败，尝试截取整个页面: {e}")
                                            screenshot_bytes = page.screenshot(full_page=False)
                                        
                                        if screenshot_bytes:
                                            # 生成带时间戳的文件名并直接保存
                                            from datetime import datetime
                                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                                            filename = f"face_verify_{self.pure_user_id}_{timestamp}.jpg"
                                            file_path = os.path.join(screenshots_dir, filename)
                                            
                                            try:
                                                with open(file_path, 'wb') as f:
                                                    f.write(screenshot_bytes)
                                                # 返回相对路径
                                                screenshot_path = file_path.replace('\\', '/')
                                                logger.info(f"【{self.pure_user_id}】✅ 人脸验证截图已保存: {screenshot_path}")
                                            except Exception as e:
                                                logger.error(f"【{self.pure_user_id}】保存截图失败: {e}")
                                                screenshot_path = None
                                        else:
                                            logger.warning(f"【{self.pure_user_id}】⚠️ 截图失败，无法获取截图数据")
                                    except Exception as e:
                                        logger.error(f"【{self.pure_user_id}】截图时出错: {e}")
                                        import traceback
                                        logger.debug(traceback.format_exc())
                                    
                                    # 创建一个特殊的frame对象，包含截图路径
                                    class VerificationFrame:
                                        def __init__(self, original_frame, verify_url, screenshot_path=None):
                                            self._original_frame = original_frame
                                            self.verify_url = verify_url
                                            self.screenshot_path = screenshot_path
                                        
                                        def __getattr__(self, name):
                                            return getattr(self._original_frame, name)
                                    
                                    return True, VerificationFrame(frame, face_verify_url, screenshot_path)
                                
                                return True, frame
                    except Exception as e:
                        logger.debug(f"【{self.pure_user_id}】检查iframe时出错: {e}")
                        continue
            except Exception as e:
                logger.debug(f"【{self.pure_user_id}】检查alibaba-login-box iframe时出错: {e}")
            
            for idx, frame in enumerate(page.frames):
                try:
                    frame_url = frame.url
                    logger.debug(f"【{self.pure_user_id}】检查Frame {idx} 是否有二维码: {frame_url}")
                    
                    # 检查frame URL是否包含 mini_login（人脸验证或短信验证页面）
                    if 'mini_login' in frame_url:
                        # 进一步确认不是滑块验证
                        is_slider = False
                        for selector in slider_selectors:
                            try:
                                element = frame.query_selector(selector)
                                if element and element.is_visible():
                                    is_slider = True
                                    break
                            except:
                                continue
                        
                        if not is_slider:
                            logger.info(f"【{self.pure_user_id}】✅ 在Frame {idx} 检测到 mini_login 页面（人脸验证/短信验证）")
                            logger.info(f"【{self.pure_user_id}】人脸验证/短信验证Frame URL: {frame_url}")
                            return True, frame
                    
                    # 检查frame的父iframe是否是alibaba-login-box
                    try:
                        # 尝试通过frame的父元素查找
                        frame_element = frame.frame_element()
                        if frame_element:
                            parent_iframe_id = frame_element.get_attribute('id')
                            if parent_iframe_id == 'alibaba-login-box':
                                logger.info(f"【{self.pure_user_id}】✅ 在Frame {idx} 检测到 alibaba-login-box（人脸验证/短信验证）")
                                logger.info(f"【{self.pure_user_id}】人脸验证/短信验证Frame URL: {frame_url}")
                                return True, frame
                    except:
                        pass
                    
                    # 先检查这个frame是否是滑块验证
                    is_slider_frame = False
                    for selector in slider_selectors:
                        try:
                            element = frame.query_selector(selector)
                            if element and element.is_visible():
                                logger.debug(f"【{self.pure_user_id}】Frame {idx} 包含滑块验证元素，跳过")
                                is_slider_frame = True
                                break
                        except:
                            continue
                    
                    if is_slider_frame:
                        continue  # 跳过滑块验证的frame
                    
                    # 二维码验证的选择器（更精确，避免误判滑块验证）
                    qr_selectors = [
                        'img[alt*="二维码"]',
                        'img[alt*="扫码"]',
                        'img[src*="qrcode"]',
                        'canvas[class*="qrcode"]',
                        '.qr-code',
                        '#qr-code',
                        '[class*="qr-code"]',
                        '[id*="qr-code"]'
                    ]
                    
                    # 检查是否有真正的二维码图片（不是滑块验证中的qrcode类）
                    for selector in qr_selectors:
                        try:
                            element = frame.query_selector(selector)
                            if element and element.is_visible():
                                # 进一步验证：检查是否包含滑块元素，如果包含则跳过
                                has_slider_in_frame = False
                                for slider_sel in slider_selectors:
                                    try:
                                        slider_elem = frame.query_selector(slider_sel)
                                        if slider_elem and slider_elem.is_visible():
                                            has_slider_in_frame = True
                                            break
                                    except:
                                        continue
                                
                                if not has_slider_in_frame:
                                    logger.info(f"【{self.pure_user_id}】✅ 在Frame {idx} 检测到二维码验证: {selector}")
                                    logger.info(f"【{self.pure_user_id}】二维码Frame URL: {frame_url}")
                                    return True, frame
                        except:
                            continue
                    
                    # 人脸验证的关键词（更精确）
                    face_keywords = ['拍摄脸部', '人脸验证', '人脸识别', '面部验证', '请进行人脸验证', '请完成人脸识别']
                    try:
                        frame_content = frame.content()
                        # 检查是否包含人脸验证关键词，但不包含滑块相关关键词
                        has_face_keyword = False
                        for keyword in face_keywords:
                            if keyword in frame_content:
                                has_face_keyword = True
                                break
                        
                        # 如果包含人脸验证关键词，且不包含滑块关键词，则认为是人脸验证
                        if has_face_keyword:
                            slider_keywords = ['滑块', '拖动', 'nc_', 'nc-container']
                            has_slider_keyword = any(keyword in frame_content for keyword in slider_keywords)
                            
                            if not has_slider_keyword:
                                logger.info(f"【{self.pure_user_id}】✅ 在Frame {idx} 检测到人脸验证")
                                logger.info(f"【{self.pure_user_id}】人脸验证Frame URL: {frame_url}")
                                return True, frame
                    except:
                        pass
                        
                except Exception as e:
                    logger.debug(f"【{self.pure_user_id}】检查Frame {idx} 失败: {e}")
                    continue
            
            logger.info(f"【{self.pure_user_id}】未检测到二维码/人脸验证")
            return False, None
            
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】检测二维码/人脸验证时出错: {e}")
            return False, None
    
    def _get_face_verification_url(self, frame) -> str:
        """在alibaba-login-box frame中，点击'其他验证方式'，然后找到'通过拍摄脸部'的验证按钮，获取链接"""
        try:
            logger.info(f"【{self.pure_user_id}】开始查找人脸验证链接...")
            
            # 等待frame加载完成
            time.sleep(2)
            
            # 查找"其他验证方式"链接并点击
            other_verify_clicked = False
            try:
                # 尝试通过文本内容查找所有链接
                all_links = frame.query_selector_all('a')
                for link in all_links:
                    try:
                        text = link.inner_text()
                        if '其他验证方式' in text or ('其他' in text and '验证' in text):
                            logger.info(f"【{self.pure_user_id}】找到'其他验证方式'链接，点击中...")
                            link.click()
                            time.sleep(2)  # 等待页面切换
                            other_verify_clicked = True
                            break
                    except:
                        continue
            except Exception as e:
                logger.debug(f"【{self.pure_user_id}】查找'其他验证方式'链接时出错: {e}")
            
            if not other_verify_clicked:
                logger.warning(f"【{self.pure_user_id}】未找到'其他验证方式'链接，可能已经在验证方式选择页面")
            
            # 等待页面加载
            time.sleep(2)
            
            # 查找"通过拍摄脸部"相关的验证按钮，获取href并点击按钮
            face_verify_url = None
            
            # 方法1: 使用JavaScript精确查找，获取href并点击按钮（根据HTML结构：li > div.desc包含"通过 拍摄脸部" + a.ui-button包含"立即验证"）
            try:
                href = frame.evaluate("""
                    () => {
                        // 查找所有li元素
                        const listItems = document.querySelectorAll('li');
                        for (let li of listItems) {
                            // 查找包含"通过 拍摄脸部"或"通过拍摄脸部"的desc div，但不能包含"手机"
                            const descDiv = li.querySelector('div.desc');
                            if (descDiv && !descDiv.innerText.includes('手机') && (descDiv.innerText.includes('通过 拍摄脸部') || descDiv.innerText.includes('通过拍摄脸部') || descDiv.innerText.includes('拍摄脸部'))) {
                                // 在同一li中查找"立即验证"按钮
                                const verifyButton = li.querySelector('a.ui-button, a.ui-button-small, button');
                                if (verifyButton && verifyButton.innerText && verifyButton.innerText.includes('立即验证')) {
                                    // 获取按钮的href属性
                                    const href = verifyButton.href || verifyButton.getAttribute('href') || null;
                                    // 点击按钮
                                    verifyButton.click();
                                    // 返回href
                                    return href;
                                }
                            }
                        }
                        return null;
                    }
                """)
                if href:
                    face_verify_url = href
                    logger.info(f"【{self.pure_user_id}】通过JavaScript找到'通过拍摄脸部'验证按钮的href并已点击: {face_verify_url}")
            except Exception as e:
                logger.debug(f"【{self.pure_user_id}】方法1（JavaScript）查找失败: {e}")
            
            # 方法2: 如果方法1失败，使用Playwright API查找并点击
            if not face_verify_url:
                try:
                    # 查找所有li元素
                    list_items = frame.query_selector_all('li')
                    for li in list_items:
                        try:
                            # 查找desc div
                            desc_div = li.query_selector('div.desc')
                            if desc_div:
                                desc_text = desc_div.inner_text()
                                if '手机' not in desc_text and ('通过 拍摄脸部' in desc_text or '通过拍摄脸部' in desc_text or '拍摄脸部' in desc_text):
                                    logger.info(f"【{self.pure_user_id}】找到'通过拍摄脸部'选项（方法2）")
                                    # 在同一li中查找验证按钮
                                    verify_button = li.query_selector('a.ui-button, a.ui-button-small, button')
                                    if verify_button:
                                        button_text = verify_button.inner_text()
                                        if '立即验证' in button_text:
                                            # 获取按钮的href属性
                                            href = verify_button.get_attribute('href')
                                            if href:
                                                face_verify_url = href
                                                logger.info(f"【{self.pure_user_id}】找到'通过拍摄脸部'验证按钮的href: {face_verify_url}")
                                                # 点击按钮
                                                logger.info(f"【{self.pure_user_id}】点击'立即验证'按钮...")
                                                verify_button.click()
                                                logger.info(f"【{self.pure_user_id}】已点击'立即验证'按钮")
                                                break
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"【{self.pure_user_id}】方法2查找失败: {e}")
            
            if face_verify_url:
                # 如果是相对路径，转换为绝对路径
                if not face_verify_url.startswith('http'):
                    base_url = frame.url.split('/iv/')[0] if '/iv/' in frame.url else 'https://passport.goofish.com'
                    if face_verify_url.startswith('/'):
                        face_verify_url = base_url + face_verify_url
                    else:
                        face_verify_url = base_url + '/' + face_verify_url
                
                return face_verify_url
            else:
                logger.warning(f"【{self.pure_user_id}】未找到人脸验证链接，返回原始frame URL")
                return frame.url if hasattr(frame, 'url') else None
                
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】获取人脸验证链接时出错: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    def login_with_password_playwright(self, account: str, password: str, show_browser: bool = False, notification_callback: Optional[Callable] = None) -> dict:
        """使用Playwright进行密码登录（新方法，替代DrissionPage）
        
        Args:
            account: 登录账号（必填）
            password: 登录密码（必填）
            show_browser: 是否显示浏览器窗口（默认False为无头模式）
            notification_callback: 可选的通知回调函数，用于发送二维码/人脸验证通知（接受错误消息字符串作为参数）
        
        Returns:
            dict: Cookie字典，失败返回None
        """
        try:
            # 检查日期有效性
            if not self._check_date_validity():
                logger.error(f"【{self.pure_user_id}】日期验证失败，无法执行登录")
                return None
            
            # 验证必需参数
            if not account or not password:
                logger.error(f"【{self.pure_user_id}】账号或密码不能为空")
                return None
            
            browser_mode = "有头" if show_browser else "无头"
            logger.info(f"【{self.pure_user_id}】开始{browser_mode}模式密码登录流程（使用Playwright）...")
            logger.info(f"【{self.pure_user_id}】账号: {account}")
            logger.info("=" * 60)
            
            # 启动浏览器（使用持久化上下文）
            import os
            user_data_dir = os.path.join(os.getcwd(), 'browser_data', f'user_{self.pure_user_id}')
            os.makedirs(user_data_dir, exist_ok=True)
            logger.info(f"【{self.pure_user_id}】使用用户数据目录: {user_data_dir}")
            
            # 设置浏览器启动参数
            browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-web-security',
                '--disable-features=VizDisplayCompositor',
                '--lang=zh-CN',  # 设置浏览器语言为中文
            ]
            
            # 在启动Playwright之前，重新检查和设置浏览器路径
            # 确保使用正确的浏览器版本（避免版本不匹配问题）
            import sys
            from pathlib import Path
            if getattr(sys, 'frozen', False):
                # 如果是打包后的exe，检查exe同目录下的浏览器
                exe_dir = Path(sys.executable).parent
                playwright_dir = exe_dir / 'playwright'
                
                if playwright_dir.exists():
                    chromium_dirs = list(playwright_dir.glob('chromium-*'))
                    # 找到第一个完整的浏览器目录
                    for chromium_dir in chromium_dirs:
                        chrome_exe = chromium_dir / 'chrome-win' / 'chrome.exe'
                        if chrome_exe.exists() and chrome_exe.stat().st_size > 0:
                            # 清除旧的环境变量，使用实际存在的浏览器
                            if 'PLAYWRIGHT_BROWSERS_PATH' in os.environ:
                                old_path = os.environ['PLAYWRIGHT_BROWSERS_PATH']
                                if old_path != str(playwright_dir):
                                    logger.info(f"【{self.pure_user_id}】清除旧的环境变量: {old_path}")
                                    del os.environ['PLAYWRIGHT_BROWSERS_PATH']
                            # 设置正确的环境变量
                            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(playwright_dir)
                            logger.info(f"【{self.pure_user_id}】已设置PLAYWRIGHT_BROWSERS_PATH: {playwright_dir}")
                            logger.info(f"【{self.pure_user_id}】使用浏览器版本: {chromium_dir.name}")
                            break
            
            # 启动浏览器
            playwright = sync_playwright().start()
            context = playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=not show_browser,
                args=browser_args,
                viewport={'width': 1980, 'height': 1024},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
                locale='zh-CN',  # 设置浏览器区域为中文
                accept_downloads=True,
                ignore_https_errors=True,
                extra_http_headers={
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'  # 设置HTTP Accept-Language header为中文
                }
            )
            logger.info(f"【{self.pure_user_id}】已设置浏览器语言为中文（zh-CN）")
            
            browser = context.browser
            page = context.new_page()
            logger.info(f"【{self.pure_user_id}】浏览器已成功启动（{browser_mode}模式）")
            
            try:
                # 访问登录页面
                login_url = "https://www.goofish.com/im"
                logger.info(f"【{self.pure_user_id}】访问登录页面: {login_url}")
                page.goto(login_url, wait_until='networkidle', timeout=60000)
                
                # 等待页面加载
                wait_time = 2 if not show_browser else 2
                logger.info(f"【{self.pure_user_id}】等待页面加载（{wait_time}秒）...")
                time.sleep(wait_time)
                
                # 页面诊断信息
                logger.info(f"【{self.pure_user_id}】========== 页面诊断信息 ==========")
                logger.info(f"【{self.pure_user_id}】当前URL: {page.url}")
                logger.info(f"【{self.pure_user_id}】页面标题: {page.title()}")
                logger.info(f"【{self.pure_user_id}】=====================================")
                
                # 【步骤1】查找登录frame（闲鱼登录通常在iframe中）
                logger.info(f"【{self.pure_user_id}】查找登录frame...")
                login_frame = None
                found_login_form = False
                
                # 等待页面和iframe加载完成
                logger.info(f"【{self.pure_user_id}】等待页面和iframe加载...")
                time.sleep(1)  # 增加等待时间，确保iframe加载完成
                
                # 先尝试在主页面查找登录表单
                logger.info(f"【{self.pure_user_id}】在主页面查找登录表单...")
                main_page_selectors = [
                    '#fm-login-id',
                    'input[name="fm-login-id"]',
                    'input[placeholder*="手机号"]',
                    'input[placeholder*="邮箱"]',
                    '.fm-login-id',
                    '#J_LoginForm input[type="text"]'
                ]
                for selector in main_page_selectors:
                    try:
                        element = page.query_selector(selector)
                        if element and element.is_visible():
                            logger.info(f"【{self.pure_user_id}】✓ 在主页面找到登录表单元素: {selector}")
                            # 主页面找到登录表单，使用page作为login_frame
                            login_frame = page
                            found_login_form = True
                            break
                    except:
                        continue
                
                # 如果主页面没找到，再在iframe中查找
                if not found_login_form:
                    iframes = page.query_selector_all('iframe')
                    logger.info(f"【{self.pure_user_id}】找到 {len(iframes)} 个 iframe")
                    
                    # 尝试在iframe中查找登录表单
                    for idx, iframe in enumerate(iframes):
                        try:
                            frame = iframe.content_frame()
                            if frame:
                                # 等待iframe内容加载
                                try:
                                    frame.wait_for_selector('#fm-login-id', timeout=3000)
                                except:
                                    pass
                                
                                # 检查是否有登录表单
                                login_selectors = [
                                    '#fm-login-id',
                                    'input[name="fm-login-id"]',
                                    'input[placeholder*="手机号"]',
                                    'input[placeholder*="邮箱"]'
                                ]
                                for selector in login_selectors:
                                    try:
                                        element = frame.query_selector(selector)
                                        if element and element.is_visible():
                                            logger.info(f"【{self.pure_user_id}】✓ 在Frame {idx} 找到登录表单: {selector}")
                                            login_frame = frame
                                            found_login_form = True
                                            break
                                    except:
                                        continue
                                
                                if found_login_form:
                                    break
                                else:
                                    # Frame存在但没有登录表单，可能是滑块验证frame
                                    logger.debug(f"【{self.pure_user_id}】Frame {idx} 未找到登录表单")
                        except Exception as e:
                            logger.debug(f"【{self.pure_user_id}】检查Frame {idx}时出错: {e}")
                            continue
                
                # 【情况1】找到frame且找到登录表单 → 正常登录流程
                if found_login_form:
                    logger.info(f"【{self.pure_user_id}】找到登录表单，开始正常登录流程...")
                
                # 【情况2】找到frame但未找到登录表单 → 可能已登录，直接检测滑块
                elif len(iframes) > 0:
                    logger.warning(f"【{self.pure_user_id}】找到iframe但未找到登录表单，可能已登录，检测滑块...")
                    
                    # 先将page和context保存到实例变量（供solve_slider使用）
                    original_page = self.page
                    original_context = self.context
                    original_browser = self.browser
                    original_playwright = self.playwright
                    
                    self.page = page
                    self.context = context
                    self.browser = browser
                    self.playwright = playwright
                    
                    try:
                        # 检测滑块元素（在主页面和所有frame中查找）
                        slider_selectors = [
                            '#nc_1_n1z',
                            '.nc-container',
                            '.nc_scale',
                            '.nc-wrapper'
                        ]
                        
                        has_slider = False
                        detected_slider_frame = None
                        
                        # 先在主页面查找
                        for selector in slider_selectors:
                            try:
                                element = page.query_selector(selector)
                                if element and element.is_visible():
                                    logger.info(f"【{self.pure_user_id}】✅ 在主页面检测到滑块验证元素: {selector}")
                                    has_slider = True
                                    detected_slider_frame = None  # None表示主页面
                                    break
                            except:
                                continue
                        
                        # 如果主页面没找到，在所有frame中查找
                        if not has_slider:
                            for idx, iframe in enumerate(iframes):
                                try:
                                    frame = iframe.content_frame()
                                    if frame:
                                        # 等待frame内容加载
                                        try:
                                            frame.wait_for_load_state('domcontentloaded', timeout=2000)
                                        except:
                                            pass
                                        
                                        for selector in slider_selectors:
                                            try:
                                                element = frame.query_selector(selector)
                                                if element and element.is_visible():
                                                    logger.info(f"【{self.pure_user_id}】✅ 在Frame {idx} 检测到滑块验证元素: {selector}")
                                                    has_slider = True
                                                    detected_slider_frame = frame
                                                    break
                                            except:
                                                continue
                                        
                                        if has_slider:
                                            break
                                except Exception as e:
                                    logger.debug(f"【{self.pure_user_id}】检查Frame {idx}时出错: {e}")
                                    continue
                        
                        if has_slider:
                            # 设置检测到的frame，供solve_slider使用
                            self._detected_slider_frame = detected_slider_frame
                            
                            logger.warning(f"【{self.pure_user_id}】检测到滑块验证，开始处理...")
                            time.sleep(3)
                            slider_success = self.solve_slider(max_retries=3)
                            
                            if not slider_success:
                                # 3次失败后，刷新页面重试
                                logger.warning(f"【{self.pure_user_id}】⚠️ 滑块处理3次都失败，刷新页面后重试...")
                                try:
                                    page.reload(wait_until="domcontentloaded", timeout=30000)
                                    logger.info(f"【{self.pure_user_id}】✅ 页面刷新完成")
                                    time.sleep(2)
                                    slider_success = self.solve_slider(max_retries=3)
                                    if not slider_success:
                                        logger.error(f"【{self.pure_user_id}】❌ 刷新后滑块验证仍然失败")
                                        return None
                                    else:
                                        logger.success(f"【{self.pure_user_id}】✅ 刷新后滑块验证成功！")
                                except Exception as e:
                                    logger.error(f"【{self.pure_user_id}】❌ 页面刷新失败: {e}")
                                    return None
                            else:
                                logger.success(f"【{self.pure_user_id}】✅ 滑块验证成功！")
                            
                            # 等待页面加载和状态更新（第一次等待3秒）
                            logger.info(f"【{self.pure_user_id}】等待3秒，让页面加载完成...")
                            time.sleep(3)
                            
                            # 第一次检查登录状态
                            login_success = self._check_login_success_by_element(page)
                            
                            # 如果第一次没检测到，再等待5秒后重试
                            if not login_success:
                                logger.info(f"【{self.pure_user_id}】第一次检测未发现登录状态，等待5秒后重试...")
                                time.sleep(5)
                                login_success = self._check_login_success_by_element(page)
                            
                            if login_success:
                                logger.success(f"【{self.pure_user_id}】✅ 滑块验证后登录成功")
                                
                                # 只有在登录成功后才获取Cookie
                                cookies_dict = {}
                                try:
                                    cookies_list = context.cookies()
                                    for cookie in cookies_list:
                                        cookies_dict[cookie.get('name', '')] = cookie.get('value', '')
                                    
                                    logger.info(f"【{self.pure_user_id}】成功获取Cookie，包含 {len(cookies_dict)} 个字段")
                                    
                                    if cookies_dict:
                                        logger.success("✅ Cookie有效")
                                        return cookies_dict
                                    else:
                                        logger.error("❌ Cookie为空")
                                        return None
                                except Exception as e:
                                    logger.error(f"【{self.pure_user_id}】获取Cookie失败: {e}")
                                    return None
                            else:
                                logger.warning(f"【{self.pure_user_id}】⚠️ 滑块验证后登录状态不明确，不获取Cookie")
                                return None
                        else:
                            logger.info(f"【{self.pure_user_id}】未检测到滑块验证")
                            
                            # 未检测到滑块时，检查是否已登录
                            if self._check_login_success_by_element(page):
                                logger.success(f"【{self.pure_user_id}】✅ 检测到已登录状态")
                                
                                # 只有在登录成功后才获取Cookie
                                cookies_dict = {}
                                try:
                                    cookies_list = context.cookies()
                                    for cookie in cookies_list:
                                        cookies_dict[cookie.get('name', '')] = cookie.get('value', '')
                                    
                                    logger.info(f"【{self.pure_user_id}】成功获取Cookie，包含 {len(cookies_dict)} 个字段")
                                    
                                    if cookies_dict:
                                        logger.success("✅ Cookie有效")
                                        return cookies_dict
                                    else:
                                        logger.error("❌ Cookie为空")
                                        return None
                                except Exception as e:
                                    logger.error(f"【{self.pure_user_id}】获取Cookie失败: {e}")
                                    return None
                            else:
                                logger.warning(f"【{self.pure_user_id}】⚠️ 未检测到滑块且未登录，不获取Cookie")
                                return None
                    
                    finally:
                        # 恢复原始值
                        self.page = original_page
                        self.context = original_context
                        self.browser = original_browser
                        self.playwright = original_playwright
                
                # 【情况3】未找到frame → 检查是否已登录
                else:
                    logger.warning(f"【{self.pure_user_id}】未找到任何iframe，检查是否已登录...")
                    
                    # 等待一下让页面完全加载
                    time.sleep(2)
                    
                    # 检查是否已登录（只有过了滑块才会有这个元素）
                    if self._check_login_success_by_element(page):
                        logger.success(f"【{self.pure_user_id}】✅ 检测到已登录状态")
                        
                        # 获取Cookie
                        cookies_dict = {}
                        try:
                            cookies_list = context.cookies()
                            for cookie in cookies_list:
                                cookies_dict[cookie.get('name', '')] = cookie.get('value', '')
                            
                            if cookies_dict:
                                logger.success("✅ 登录成功！Cookie有效")
                                return cookies_dict
                            else:
                                logger.error("❌ Cookie为空")
                                return None
                        except Exception as e:
                            logger.error(f"【{self.pure_user_id}】获取Cookie失败: {e}")
                            return None
                    else:
                        logger.error(f"【{self.pure_user_id}】❌ 未找到登录表单且未检测到已登录")
                        return None
                
                # 点击密码登录标签
                logger.info(f"【{self.pure_user_id}】查找密码登录标签...")
                try:
                    password_tab = login_frame.query_selector('a.password-login-tab-item')
                    if password_tab:
                        logger.info(f"【{self.pure_user_id}】✓ 找到密码登录标签，点击中...")
                        password_tab.click()
                        time.sleep(1.5)
                except Exception as e:
                    logger.warning(f"【{self.pure_user_id}】查找密码登录标签失败: {e}")
                
                # 输入账号
                logger.info(f"【{self.pure_user_id}】输入账号: {account}")
                time.sleep(1)
                
                account_input = login_frame.query_selector('#fm-login-id')
                if account_input:
                    logger.info(f"【{self.pure_user_id}】✓ 找到账号输入框")
                    account_input.fill(account)
                    logger.info(f"【{self.pure_user_id}】✓ 账号已输入")
                    time.sleep(random.uniform(0.5, 1.0))
                else:
                    logger.error(f"【{self.pure_user_id}】✗ 未找到账号输入框")
                    return None
                
                # 输入密码
                logger.info(f"【{self.pure_user_id}】输入密码...")
                password_input = login_frame.query_selector('#fm-login-password')
                if password_input:
                    password_input.fill(password)
                    logger.info(f"【{self.pure_user_id}】✓ 密码已输入")
                    time.sleep(random.uniform(0.5, 1.0))
                else:
                    logger.error(f"【{self.pure_user_id}】✗ 未找到密码输入框")
                    return None
                
                # 勾选用户协议
                logger.info(f"【{self.pure_user_id}】查找并勾选用户协议...")
                try:
                    agreement_checkbox = login_frame.query_selector('#fm-agreement-checkbox')
                    if agreement_checkbox:
                        is_checked = agreement_checkbox.evaluate('el => el.checked')
                        if not is_checked:
                            agreement_checkbox.click()
                            time.sleep(0.3)
                            logger.info(f"【{self.pure_user_id}】✓ 用户协议已勾选")
                except Exception as e:
                    logger.warning(f"【{self.pure_user_id}】勾选用户协议失败: {e}")
                
                # 点击登录按钮
                logger.info(f"【{self.pure_user_id}】点击登录按钮...")
                time.sleep(1)
                
                login_button = login_frame.query_selector('button.password-login')
                if login_button:
                    logger.info(f"【{self.pure_user_id}】✓ 找到登录按钮")
                    login_button.click()
                    logger.info(f"【{self.pure_user_id}】✓ 登录按钮已点击")
                else:
                    logger.error(f"【{self.pure_user_id}】✗ 未找到登录按钮")
                    return None
                
                # 【关键】点击登录后，等待一下再检测滑块
                logger.info(f"【{self.pure_user_id}】========== 登录后监控 ==========")
                logger.info(f"【{self.pure_user_id}】等待页面响应...")
                time.sleep(3)
                
                # 【核心】检测是否有滑块验证 → 如果有，调用 solve_slider() 处理
                logger.info(f"【{self.pure_user_id}】检测是否有滑块验证...")
                
                # 先将page和context保存到实例变量（供solve_slider使用）
                original_page = self.page
                original_context = self.context
                original_browser = self.browser
                original_playwright = self.playwright
                
                self.page = page
                self.context = context
                self.browser = browser
                self.playwright = playwright
                
                try:
                    # 检查页面内容是否包含滑块相关元素
                    page_content = page.content()
                    has_slider = False
                    
                    # 检测滑块元素
                    slider_selectors = [
                        '#nc_1_n1z',
                        '.nc-container',
                        '.nc_scale',
                        '.nc-wrapper'
                    ]
                    
                    for selector in slider_selectors:
                        try:
                            element = page.query_selector(selector)
                            if element and element.is_visible():
                                logger.info(f"【{self.pure_user_id}】✅ 检测到滑块验证元素: {selector}")
                                has_slider = True
                                break
                        except:
                            continue
                    
                    if has_slider:
                        logger.warning(f"【{self.pure_user_id}】检测到滑块验证，开始处理...")
                        
                        # 【复用】直接调用 solve_slider() 方法处理滑块
                        slider_success = self.solve_slider(max_retries=3)
                        
                        if slider_success:
                            logger.success(f"【{self.pure_user_id}】✅ 滑块验证成功！")
                        else:
                            # 3次失败后，刷新页面重试
                            logger.warning(f"【{self.pure_user_id}】⚠️ 滑块处理3次都失败，刷新页面后重试...")
                            try:
                                page.reload(wait_until="domcontentloaded", timeout=30000)
                                logger.info(f"【{self.pure_user_id}】✅ 页面刷新完成")
                                time.sleep(2)
                                slider_success = self.solve_slider(max_retries=3)
                                if not slider_success:
                                    logger.error(f"【{self.pure_user_id}】❌ 刷新后滑块验证仍然失败")
                                    return None
                                else:
                                    logger.success(f"【{self.pure_user_id}】✅ 刷新后滑块验证成功！")
                            except Exception as e:
                                logger.error(f"【{self.pure_user_id}】❌ 页面刷新失败: {e}")
                                return None
                    else:
                        logger.info(f"【{self.pure_user_id}】未检测到滑块验证")
                    
                    # 等待登录完成
                    logger.info(f"【{self.pure_user_id}】等待登录完成...")
                    time.sleep(5)
                    
                    # 再次检查是否有滑块验证（可能在等待过程中出现）
                    logger.info(f"【{self.pure_user_id}】等待1秒后检查是否有滑块验证...")
                    time.sleep(1)
                    has_slider_after_wait = False
                    for selector in slider_selectors:
                        try:
                            element = page.query_selector(selector)
                            if element and element.is_visible():
                                logger.info(f"【{self.pure_user_id}】✅ 等待后检测到滑块验证元素: {selector}")
                                has_slider_after_wait = True
                                break
                        except:
                            continue
                    
                    if has_slider_after_wait:
                        logger.warning(f"【{self.pure_user_id}】检测到滑块验证，开始处理...")
                        slider_success = self.solve_slider(max_retries=3)
                        if slider_success:
                            logger.success(f"【{self.pure_user_id}】✅ 滑块验证成功！")
                            time.sleep(3)  # 等待滑块验证后的状态更新
                        else:
                            # 3次失败后，刷新页面重试
                            logger.warning(f"【{self.pure_user_id}】⚠️ 滑块处理3次都失败，刷新页面后重试...")
                            try:
                                page.reload(wait_until="domcontentloaded", timeout=30000)
                                logger.info(f"【{self.pure_user_id}】✅ 页面刷新完成")
                                time.sleep(2)
                                slider_success = self.solve_slider(max_retries=3)
                                if not slider_success:
                                    logger.error(f"【{self.pure_user_id}】❌ 刷新后滑块验证仍然失败")
                                    return None
                                else:
                                    logger.success(f"【{self.pure_user_id}】✅ 刷新后滑块验证成功！")
                                    time.sleep(3)
                            except Exception as e:
                                logger.error(f"【{self.pure_user_id}】❌ 页面刷新失败: {e}")
                                return None
                    
                    # 检查登录状态
                    logger.info(f"【{self.pure_user_id}】等待1秒后检查登录状态...")
                    time.sleep(1)
                    login_success = self._check_login_success_by_element(page)
                    
                    if login_success:
                        logger.success(f"【{self.pure_user_id}】✅ 登录验证成功！")
                    else:
                        # 检查是否有账密错误
                        logger.info(f"【{self.pure_user_id}】等待1秒后检查是否有账密错误...")
                        time.sleep(1)
                        has_error, error_message = self._check_login_error(page)
                        if has_error:
                            logger.error(f"【{self.pure_user_id}】❌ 登录失败：{error_message}")
                            # 抛出异常，包含错误消息，让调用者能够获取
                            raise Exception(error_message if error_message else "登录失败，请检查账号密码是否正确")
                        
                        # 【重要】检测是否需要二维码/人脸验证（排除滑块验证）
                        # 注意：_detect_qr_code_verification 如果检测到滑块，会立即处理滑块
                        logger.info(f"【{self.pure_user_id}】等待1秒后检测是否需要二维码/人脸验证...")
                        time.sleep(1)
                        logger.info(f"【{self.pure_user_id}】检测是否需要二维码/人脸验证...")
                        has_qr, qr_frame = self._detect_qr_code_verification(page)
                        
                        # 如果检测到滑块并已处理，再次检查登录状态
                        if not has_qr:
                            # 滑块可能已被处理，再次检查登录状态
                            logger.info(f"【{self.pure_user_id}】等待1秒后再次检查登录状态...")
                            time.sleep(1)
                            login_success_after_slider = self._check_login_success_by_element(page)
                            if login_success_after_slider:
                                logger.success(f"【{self.pure_user_id}】✅ 滑块验证后，登录验证成功！")
                                login_success = True
                            else:
                                # 滑块验证后仍未登录成功，继续检测二维码/人脸验证（此时应该不会再检测到滑块）
                                logger.info(f"【{self.pure_user_id}】等待1秒后继续检测是否需要二维码/人脸验证...")
                                time.sleep(1)
                                logger.info(f"【{self.pure_user_id}】滑块验证后，继续检测是否需要二维码/人脸验证...")
                                has_qr, qr_frame = self._detect_qr_code_verification(page)
                        
                        if has_qr:
                            logger.warning(f"【{self.pure_user_id}】⚠️ 检测到二维码/人脸验证")
                            logger.info(f"【{self.pure_user_id}】请在浏览器中完成二维码/人脸验证")
                            
                            # 获取验证链接URL和截图路径
                            frame_url = None
                            screenshot_path = None
                            if qr_frame:
                                try:
                                    # 检查是否有验证链接（从VerificationFrame对象）
                                    if hasattr(qr_frame, 'verify_url') and qr_frame.verify_url:
                                        frame_url = qr_frame.verify_url
                                        logger.info(f"【{self.pure_user_id}】使用获取到的人脸验证链接: {frame_url}")
                                    else:
                                        frame_url = qr_frame.url if hasattr(qr_frame, 'url') else None
                                    
                                    # 检查是否有截图路径（从VerificationFrame对象）
                                    if hasattr(qr_frame, 'screenshot_path') and qr_frame.screenshot_path:
                                        screenshot_path = qr_frame.screenshot_path
                                        logger.info(f"【{self.pure_user_id}】使用获取到的人脸验证截图: {screenshot_path}")
                                except Exception as e:
                                    logger.warning(f"【{self.pure_user_id}】获取frame信息失败: {e}")
                                    import traceback
                                    logger.debug(traceback.format_exc())
                            
                            # 显示验证信息
                            if screenshot_path:
                                logger.warning(f"【{self.pure_user_id}】" + "=" * 60)
                                logger.warning(f"【{self.pure_user_id}】二维码/人脸验证截图:")
                                logger.warning(f"【{self.pure_user_id}】{screenshot_path}")
                                logger.warning(f"【{self.pure_user_id}】" + "=" * 60)
                            elif frame_url:
                                logger.warning(f"【{self.pure_user_id}】" + "=" * 60)
                                logger.warning(f"【{self.pure_user_id}】二维码/人脸验证链接:")
                                logger.warning(f"【{self.pure_user_id}】{frame_url}")
                                logger.warning(f"【{self.pure_user_id}】" + "=" * 60)
                            else:
                                logger.warning(f"【{self.pure_user_id}】" + "=" * 60)
                                logger.warning(f"【{self.pure_user_id}】二维码/人脸验证已检测到，但无法获取验证信息")
                                logger.warning(f"【{self.pure_user_id}】请在浏览器中查看验证页面")
                                logger.warning(f"【{self.pure_user_id}】" + "=" * 60)
                            
                            logger.info(f"【{self.pure_user_id}】请在浏览器中完成验证，程序将持续等待...")
                            
                            # 【重要】发送通知给客户
                            if notification_callback:
                                try:
                                    if screenshot_path or frame_url:
                                        # 构造清晰的通知消息
                                        if screenshot_path:
                                            
                                            notification_msg = (
                                                f"⚠️ 账号密码登录需要人脸验证\n\n"
                                                f"账号: {self.pure_user_id}\n"
                                                f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                                f"请登录自动化网站，访问账号管理模块，进行对应账号的人脸验证"
                                                f"在验证期间，闲鱼自动回复暂时无法使用。"
                                            )
                                        else:
                                            notification_msg = (
                                                f"⚠️ 账号密码登录需要人脸验证\n\n"
                                                f"账号: {self.pure_user_id}\n"
                                                f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                                f"请点击验证链接完成验证:\n{frame_url}\n\n"
                                                f"在验证期间，闲鱼自动回复暂时无法使用。"
                                            )
                                        
                                        logger.info(f"【{self.pure_user_id}】准备发送人脸验证通知，截图路径: {screenshot_path}, URL: {frame_url}")
                                        
                                        # 如果回调是异步函数，使用 asyncio.run 在新的事件循环中运行
                                        import asyncio
                                        import inspect
                                        if inspect.iscoroutinefunction(notification_callback):
                                            # 在新的线程中运行异步回调，避免阻塞
                                            def run_async_callback():
                                                loop = asyncio.new_event_loop()
                                                asyncio.set_event_loop(loop)
                                                try:
                                                    # 传递通知消息、截图路径和URL给回调
                                                    # 参数顺序：message, screenshot_path, verification_url
                                                    loop.run_until_complete(notification_callback(notification_msg, screenshot_path, frame_url))
                                                    logger.info(f"【{self.pure_user_id}】✅ 异步通知回调已执行")
                                                except Exception as async_err:
                                                    logger.error(f"【{self.pure_user_id}】异步通知回调执行失败: {async_err}")
                                                    import traceback
                                                    logger.error(traceback.format_exc())
                                                finally:
                                                    loop.close()
                                            
                                            import threading
                                            thread = threading.Thread(target=run_async_callback)
                                            thread.start()
                                            logger.info(f"【{self.pure_user_id}】异步通知线程已启动")
                                            # 不等待线程完成，让通知在后台发送
                                        else:
                                            # 同步回调直接调用（传递通知消息、截图路径和URL）
                                            notification_callback(notification_msg, None, frame_url, screenshot_path)
                                            logger.info(f"【{self.pure_user_id}】✅ 同步通知回调已执行")
                                    else:
                                        logger.warning(f"【{self.pure_user_id}】无法获取验证信息，跳过通知发送")
                                        
                                except Exception as notify_err:
                                    logger.error(f"【{self.pure_user_id}】发送人脸验证通知失败: {notify_err}")
                                    import traceback
                                    logger.error(traceback.format_exc())
                            else:
                                logger.warning(f"【{self.pure_user_id}】⚠️ notification_callback 未提供，无法发送通知")
                                logger.warning(f"【{self.pure_user_id}】请确保调用 login_with_password_playwright 时传入 notification_callback 参数")
                            
                            # 持续等待用户完成二维码/人脸验证
                            logger.info(f"【{self.pure_user_id}】等待二维码/人脸验证完成...")
                            check_interval = 10  # 每10秒检查一次
                            max_wait_time = 450  # 最多等待7.5分钟
                            waited_time = 0
                            
                            while waited_time < max_wait_time:
                                time.sleep(check_interval)
                                waited_time += check_interval
                                
                                # 先检测是否有滑块，如果有就处理
                                try:
                                    logger.debug(f"【{self.pure_user_id}】检测是否存在滑块...")
                                    slider_detected = False
                                    
                                    # 快速检测滑块元素（不等待，仅检测）
                                    slider_selectors = [
                                        "#nc_1_n1z",
                                        ".nc-container",
                                        "#baxia-dialog-content",
                                        ".nc_wrapper",
                                        "#nocaptcha"
                                    ]
                                    
                                    # 先在主页面检测
                                    for selector in slider_selectors:
                                        try:
                                            element = page.query_selector(selector)
                                            if element and element.is_visible():
                                                slider_detected = True
                                                logger.info(f"【{self.pure_user_id}】🔍 检测到滑块元素: {selector}")
                                                break
                                        except:
                                            pass
                                    
                                    # 如果主页面没找到，检查所有frame
                                    if not slider_detected:
                                        try:
                                            frames = page.frames
                                            for frame in frames:
                                                for selector in slider_selectors:
                                                    try:
                                                        element = frame.query_selector(selector)
                                                        if element and element.is_visible():
                                                            slider_detected = True
                                                            logger.info(f"【{self.pure_user_id}】🔍 在frame中检测到滑块元素: {selector}")
                                                            break
                                                    except:
                                                        pass
                                                if slider_detected:
                                                    break
                                        except:
                                            pass
                                    
                                    # 如果检测到滑块，尝试处理
                                    if slider_detected:
                                        logger.info(f"【{self.pure_user_id}】⚡ 检测到滑块，开始自动处理...")
                                        time.sleep(3)
                                        try:
                                            # 调用滑块处理方法（使用快速模式，因为已确认滑块存在）
                                            # 最多尝试3次，因为同一个页面连续失败3次后就不会成功了
                                            if self.solve_slider(max_retries=3, fast_mode=True):
                                                logger.success(f"【{self.pure_user_id}】✅ 滑块处理成功！")
                                                
                                                # 滑块处理成功后，刷新页面
                                                try:
                                                    logger.info(f"【{self.pure_user_id}】🔄 滑块处理成功，刷新页面...")
                                                    page.reload(wait_until="domcontentloaded", timeout=30000)
                                                    logger.info(f"【{self.pure_user_id}】✅ 页面刷新完成")
                                                    # 刷新后短暂等待，让页面稳定
                                                    time.sleep(2)
                                                except Exception as reload_err:
                                                    logger.warning(f"【{self.pure_user_id}】⚠️ 页面刷新失败: {reload_err}")
                                            else:
                                                # 3次都失败了，刷新页面后再尝试一次
                                                logger.warning(f"【{self.pure_user_id}】⚠️ 滑块处理3次都失败，刷新页面后重试...")
                                                try:
                                                    logger.info(f"【{self.pure_user_id}】🔄 刷新页面以重置滑块状态...")
                                                    page.reload(wait_until="domcontentloaded", timeout=30000)
                                                    logger.info(f"【{self.pure_user_id}】✅ 页面刷新完成")
                                                    time.sleep(2)
                                                    
                                                    # 刷新后再次尝试处理滑块（给一次机会）
                                                    logger.info(f"【{self.pure_user_id}】🔄 页面刷新后，再次尝试处理滑块...")
                                                    if self.solve_slider(max_retries=3, fast_mode=True):
                                                        logger.success(f"【{self.pure_user_id}】✅ 刷新后滑块处理成功！")
                                                    else:
                                                        logger.error(f"【{self.pure_user_id}】❌ 刷新后滑块处理仍然失败，继续等待...")
                                                except Exception as reload_err:
                                                    logger.warning(f"【{self.pure_user_id}】⚠️ 页面刷新失败: {reload_err}")
                                        except Exception as slider_err:
                                            logger.warning(f"【{self.pure_user_id}】⚠️ 滑块处理出错: {slider_err}")
                                            logger.debug(traceback.format_exc())
                                except Exception as e:
                                    logger.debug(f"【{self.pure_user_id}】滑块检测时出错: {e}")
                                
                                # 检查登录状态（通过页面元素）
                                try:
                                    if self._check_login_success_by_element(page):
                                        logger.success(f"【{self.pure_user_id}】✅ 验证成功，登录状态已确认！")
                                        login_success = True
                                        break
                                    else:
                                        logger.info(f"【{self.pure_user_id}】等待验证中... (已等待{waited_time}秒/{max_wait_time}秒)")
                                except Exception as e:
                                    logger.debug(f"【{self.pure_user_id}】检查登录状态时出错: {e}")
                            
                            # 删除截图（无论成功或失败）
                            if screenshot_path:
                                try:
                                    import glob
                                    # 删除该账号的所有验证截图
                                    screenshots_dir = "static/uploads/images"
                                    all_screenshots = glob.glob(os.path.join(screenshots_dir, f"face_verify_{self.pure_user_id}_*.jpg"))
                                    for screenshot_file in all_screenshots:
                                        try:
                                            if os.path.exists(screenshot_file):
                                                os.remove(screenshot_file)
                                                logger.info(f"【{self.pure_user_id}】✅ 已删除验证截图: {screenshot_file}")
                                            else:
                                                logger.warning(f"【{self.pure_user_id}】⚠️ 截图文件不存在: {screenshot_file}")
                                        except Exception as e:
                                            logger.warning(f"【{self.pure_user_id}】⚠️ 删除截图失败: {e}")
                                except Exception as e:
                                    logger.error(f"【{self.pure_user_id}】删除截图时出错: {e}")
                            
                            if login_success:
                                logger.info(f"【{self.pure_user_id}】二维码/人脸验证已完成")
                            else:
                                logger.error(f"【{self.pure_user_id}】❌ 等待验证超时（{max_wait_time}秒）")
                                return None
                        else:
                            logger.info(f"【{self.pure_user_id}】未检测到二维码/人脸验证")
                            # 再次检查登录状态，确保登录成功
                            logger.info(f"【{self.pure_user_id}】等待1秒后再次检查登录状态...")
                            time.sleep(1)
                            login_success = self._check_login_success_by_element(page)
                            if not login_success:
                                logger.error(f"【{self.pure_user_id}】❌ 登录状态未确认，无法获取Cookie")
                                return None
                            else:
                                logger.success(f"【{self.pure_user_id}】✅ 登录状态已确认")
                    
                    # 【重要】只有在 login_success = True 的情况下，才获取Cookie
                    if not login_success:
                        logger.error(f"【{self.pure_user_id}】❌ 登录未成功，无法获取Cookie")
                        return None
                    
                    # 获取Cookie
                    logger.info(f"【{self.pure_user_id}】等待1秒后获取Cookie...")
                    time.sleep(1)
                    cookies_dict = {}
                    try:
                        cookies_list = context.cookies()
                        for cookie in cookies_list:
                            cookies_dict[cookie.get('name', '')] = cookie.get('value', '')
                        
                        logger.info(f"【{self.pure_user_id}】成功获取Cookie，包含 {len(cookies_dict)} 个字段")
                        
                        # 打印关键Cookie字段
                        important_keys = ['unb', '_m_h5_tk', '_m_h5_tk_enc', 'cookie2', 't', 'sgcookie', 'cna']
                        logger.info(f"【{self.pure_user_id}】关键Cookie字段检查:")
                        for key in important_keys:
                            if key in cookies_dict:
                                val = cookies_dict[key]
                                logger.info(f"【{self.pure_user_id}】  ✅ {key}: {'存在' if val else '为空'} (长度: {len(str(val)) if val else 0})")
                            else:
                                logger.info(f"【{self.pure_user_id}】  ❌ {key}: 缺失")
                        
                        logger.info("=" * 60)
                        
                        if cookies_dict:
                            logger.success("✅ 登录成功！Cookie有效")
                            return cookies_dict
                        else:
                            logger.error("❌ 未获取到Cookie")
                            return None
                    except Exception as e:
                        logger.error(f"【{self.pure_user_id}】获取Cookie失败: {e}")
                        return None
                
                finally:
                    # 恢复原始值
                    self.page = original_page
                    self.context = original_context
                    self.browser = original_browser
                    self.playwright = original_playwright
            
            finally:
                # 关闭浏览器
                try:
                    context.close()
                    playwright.stop()
                    logger.info(f"【{self.pure_user_id}】浏览器已关闭，缓存已保存")
                except Exception as e:
                    logger.warning(f"【{self.pure_user_id}】关闭浏览器时出错: {e}")
                    try:
                        playwright.stop()
                    except:
                        pass
        
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】密码登录流程异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def login_with_password_headful(self, account: str = None, password: str = None, show_browser: bool = False):
        """通过浏览器进行密码登录并获取Cookie (使用DrissionPage)
        
        Args:
            account: 登录账号（必填）
            password: 登录密码（必填）
            show_browser: 是否显示浏览器窗口（默认False为无头模式）
                         True: 有头模式，登录后等待5分钟（可手动处理验证码）
                         False: 无头模式，登录后等待10秒
            
        Returns:
            dict: 获取到的cookie字典，失败返回None
        """
        page = None
        try:
            # 检查日期有效性
            if not self._check_date_validity():
                logger.error(f"【{self.pure_user_id}】日期验证失败，无法执行登录")
                return None
            
            # 验证必需参数
            if not account or not password:
                logger.error(f"【{self.pure_user_id}】账号或密码不能为空")
                return None
            
            browser_mode = "有头" if show_browser else "无头"
            logger.info(f"【{self.pure_user_id}】开始{browser_mode}模式密码登录流程（使用DrissionPage）...")
            
            # 导入 DrissionPage
            try:
                from DrissionPage import ChromiumPage, ChromiumOptions
                logger.info(f"【{self.pure_user_id}】DrissionPage导入成功")
            except ImportError:
                logger.error(f"【{self.pure_user_id}】DrissionPage未安装，请执行: pip install DrissionPage")
                return None
            
            # 配置浏览器选项
            logger.info(f"【{self.pure_user_id}】配置浏览器选项（{browser_mode}模式）...")
            co = ChromiumOptions()
            
            # 根据 show_browser 参数决定是否启用无头模式
            if not show_browser:
                co.headless()
                logger.info(f"【{self.pure_user_id}】已启用无头模式")
            else:
                logger.info(f"【{self.pure_user_id}】已启用有头模式（浏览器可见）")
            
            # 设置浏览器参数（反检测）
            co.set_argument('--no-sandbox')
            co.set_argument('--disable-setuid-sandbox')
            co.set_argument('--disable-dev-shm-usage')
            co.set_argument('--disable-blink-features=AutomationControlled')
            co.set_argument('--disable-infobars')
            co.set_argument('--disable-extensions')
            co.set_argument('--disable-popup-blocking')
            co.set_argument('--disable-notifications')
            
            # 无头模式需要的额外参数
            if not show_browser:
                co.set_argument('--disable-gpu')
                co.set_argument('--disable-software-rasterizer')
            else:
                # 有头模式窗口最大化
                co.set_argument('--start-maximized')
            
            # 设置用户代理
            browser_features = self._get_random_browser_features()
            co.set_user_agent(browser_features['user_agent'])
            
            # 设置中文语言
            co.set_argument('--lang=zh-CN')
            logger.info(f"【{self.pure_user_id}】已设置浏览器语言为中文（zh-CN）")
            
            # 禁用自动化特征检测
            co.set_pref('excludeSwitches', ['enable-automation'])
            co.set_pref('useAutomationExtension', False)
            
            # 创建浏览器页面，添加重试机制
            logger.info(f"【{self.pure_user_id}】启动DrissionPage浏览器（{browser_mode}模式）...")
            max_retries = 3
            retry_count = 0
            page = None
            
            while retry_count < max_retries and page is None:
                try:
                    if retry_count > 0:
                        logger.info(f"【{self.pure_user_id}】第 {retry_count + 1} 次尝试启动浏览器...")
                        time.sleep(2)  # 等待2秒后重试
                    
                    page = ChromiumPage(addr_or_opts=co)
                    logger.info(f"【{self.pure_user_id}】浏览器已成功启动（{browser_mode}模式）")
                    break
                    
                except Exception as browser_error:
                    retry_count += 1
                    logger.warning(f"【{self.pure_user_id}】浏览器启动失败 (尝试 {retry_count}/{max_retries}): {str(browser_error)}")
                    
                    if retry_count >= max_retries:
                        logger.error(f"【{self.pure_user_id}】浏览器启动失败，已达到最大重试次数")
                        logger.error(f"【{self.pure_user_id}】可能的原因：")
                        logger.error(f"【{self.pure_user_id}】1. Chrome/Chromium 浏览器未正确安装或路径不正确")
                        logger.error(f"【{self.pure_user_id}】2. 远程调试端口被占用，请关闭其他Chrome实例")
                        logger.error(f"【{self.pure_user_id}】3. 系统资源不足")
                        logger.error(f"【{self.pure_user_id}】建议：")
                        logger.error(f"【{self.pure_user_id}】- 检查Chrome浏览器是否已安装")
                        logger.error(f"【{self.pure_user_id}】- 关闭所有Chrome浏览器窗口后重试")
                        logger.error(f"【{self.pure_user_id}】- 检查任务管理器中是否有残留的chrome.exe进程")
                        raise
                    
                    # 尝试清理可能残留的Chrome进程
                    try:
                        import subprocess
                        import platform
                        if platform.system() == 'Windows':
                            subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], 
                                         capture_output=True, timeout=5)
                            logger.info(f"【{self.pure_user_id}】已尝试清理残留Chrome进程")
                    except Exception as cleanup_error:
                        logger.debug(f"【{self.pure_user_id}】清理进程时出错: {cleanup_error}")
            
            if page is None:
                logger.error(f"【{self.pure_user_id}】无法启动浏览器")
                return None
            
            # 访问登录页面
            target_url = "https://www.goofish.com/im"
            logger.info(f"【{self.pure_user_id}】访问登录页面: {target_url}")
            page.get(target_url)
            
            # 等待页面加载
            logger.info(f"【{self.pure_user_id}】等待页面加载...")
            time.sleep(5)
            
            # 检查页面状态
            logger.info(f"【{self.pure_user_id}】========== 页面诊断信息 ==========")
            current_url = page.url
            logger.info(f"【{self.pure_user_id}】当前URL: {current_url}")
            page_title = page.title
            logger.info(f"【{self.pure_user_id}】页面标题: {page_title}")
            
            
            logger.info(f"【{self.pure_user_id}】====================================")
            
            # 查找并点击密码登录标签
            logger.info(f"【{self.pure_user_id}】查找密码登录标签...")
            password_tab_selectors = [
                '.password-login-tab-item',
                'text:密码登录',
                'text:账号密码登录',
            ]
            
            password_tab_found = False
            for selector in password_tab_selectors:
                try:
                    tab = page.ele(selector, timeout=3)
                    if tab:
                        logger.info(f"【{self.pure_user_id}】找到密码登录标签: {selector}")
                        tab.click()
                        logger.info(f"【{self.pure_user_id}】密码登录标签已点击")
                        time.sleep(2)
                        password_tab_found = True
                        break
                except:
                    continue
            
            if not password_tab_found:
                logger.warning(f"【{self.pure_user_id}】未找到密码登录标签，可能页面默认就是密码登录模式")
            
            # 查找登录表单
            logger.info(f"【{self.pure_user_id}】开始检测登录表单...")
            username_selectors = [
                '#fm-login-id',
                'input:name=fm-login-id',
                'input:placeholder^=手机',
                'input:placeholder^=账号',
                'input:type=text',
                '#TPL_username_1',
            ]
            
            login_input = None
            for selector in username_selectors:
                try:
                    login_input = page.ele(selector, timeout=2)
                    if login_input:
                        logger.info(f"【{self.pure_user_id}】找到登录表单: {selector}")
                        break
                except:
                    continue
            
            if not login_input:
                logger.error(f"【{self.pure_user_id}】未找到登录表单")
                return None
            
            # 输入账号
            logger.info(f"【{self.pure_user_id}】输入账号: {account}")
            try:
                login_input.click()
                time.sleep(0.5)
                login_input.input(account)
                logger.info(f"【{self.pure_user_id}】账号已输入")
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"【{self.pure_user_id}】输入账号失败: {str(e)}")
                return None
            
            # 输入密码
            logger.info(f"【{self.pure_user_id}】输入密码...")
            password_selectors = [
                '#fm-login-password',
                'input:name=fm-login-password',
                'input:type=password',
                'input:placeholder^=密码',
                '#TPL_password_1',
            ]
            
            password_input = None
            for selector in password_selectors:
                try:
                    password_input = page.ele(selector, timeout=2)
                    if password_input:
                        logger.info(f"【{self.pure_user_id}】找到密码输入框: {selector}")
                        break
                except:
                    continue
            
            if not password_input:
                logger.error(f"【{self.pure_user_id}】未找到密码输入框")
                return None
            
            try:
                password_input.click()
                time.sleep(0.5)
                password_input.input(password)
                logger.info(f"【{self.pure_user_id}】密码已输入")
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"【{self.pure_user_id}】输入密码失败: {str(e)}")
                return None
            
            # 勾选协议（可选）
            logger.info(f"【{self.pure_user_id}】查找并勾选用户协议...")
            agreement_selectors = [
                '#fm-agreement-checkbox',
                'input:type=checkbox',
            ]
            
            for selector in agreement_selectors:
                try:
                    checkbox = page.ele(selector, timeout=1)
                    if checkbox and not checkbox.states.is_checked:
                        checkbox.click()
                        logger.info(f"【{self.pure_user_id}】用户协议已勾选")
                        time.sleep(0.5)
                        break
                except:
                    continue
            
            # 点击登录按钮
            logger.info(f"【{self.pure_user_id}】点击登录按钮...")
            login_button_selectors = [
                '@class=fm-button fm-submit password-login ',
                '.fm-button.fm-submit.password-login',
                'button.password-login',
                '.password-login',
                'button.fm-submit',
                'text:登录',
            ]
            
            login_button_found = False
            for selector in login_button_selectors:
                try:
                    button = page.ele(selector, timeout=2)
                    if button:
                        logger.info(f"【{self.pure_user_id}】找到登录按钮: {selector}")
                        button.click()
                        logger.info(f"【{self.pure_user_id}】登录按钮已点击")
                        login_button_found = True
                        break
                except:
                    continue
            
            if not login_button_found:
                logger.warning(f"【{self.pure_user_id}】未找到登录按钮，尝试按Enter键...")
                try:
                    password_input.input('\n')  # 模拟按Enter
                    logger.info(f"【{self.pure_user_id}】已按Enter键")
                except Exception as e:
                    logger.error(f"【{self.pure_user_id}】按Enter键失败: {str(e)}")
            
            # 等待登录完成
            logger.info(f"【{self.pure_user_id}】等待登录完成...")
            time.sleep(5)
            
            # 检查当前URL和标题
            current_url = page.url
            logger.info(f"【{self.pure_user_id}】登录后URL: {current_url}")
            page_title = page.title
            logger.info(f"【{self.pure_user_id}】登录后页面标题: {page_title}")
            
            # 根据浏览器模式决定等待时间
            # 有头模式：等待5分钟（用户可能需要手动处理验证码等）
            # 无头模式：等待10秒
            if show_browser:
                wait_seconds = 300  # 5分钟
                logger.info(f"【{self.pure_user_id}】有头模式：等待5分钟让Cookie完全生成（期间可手动处理验证码等）...")
            else:
                wait_seconds = 10
                logger.info(f"【{self.pure_user_id}】无头模式：等待10秒让Cookie完全生成...")
            
            time.sleep(wait_seconds)
            logger.info(f"【{self.pure_user_id}】等待完成，准备获取Cookie")
            
            # 获取Cookie
            logger.info(f"【{self.pure_user_id}】开始获取Cookie...")
            cookies_raw = page.cookies()
            
            # 将cookies转换为字典格式
            cookies = {}
            if isinstance(cookies_raw, list):
                # 如果返回的是列表格式，转换为字典
                for cookie in cookies_raw:
                    if isinstance(cookie, dict) and 'name' in cookie and 'value' in cookie:
                        cookies[cookie['name']] = cookie['value']
                    elif isinstance(cookie, tuple) and len(cookie) >= 2:
                        cookies[cookie[0]] = cookie[1]
            elif isinstance(cookies_raw, dict):
                # 如果已经是字典格式，直接使用
                cookies = cookies_raw
            
            if cookies:
                logger.info(f"【{self.pure_user_id}】成功获取 {len(cookies)} 个Cookie")
                value_lengths = sorted(len(value) if value else 0 for value in cookies.values())
                logger.info(
                    f"【{self.pure_user_id}】Cookie摘要: "
                    f"字段数={len(cookies)}, 值长度分布={value_lengths}"
                )
                
                # 将cookie转换为字符串格式
                logger.info(f"【{self.pure_user_id}】登录成功，准备关闭浏览器")
                
                return cookies
            else:
                logger.error(f"【{self.pure_user_id}】未获取到任何Cookie")
                return None
                
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】密码登录流程出错: {str(e)}")
            import traceback
            logger.error(f"【{self.pure_user_id}】详细错误信息: {traceback.format_exc()}")
            return None
        finally:
            # 关闭浏览器
            logger.info(f"【{self.pure_user_id}】关闭浏览器...")
            try:
                if page:
                    page.quit()
                    logger.info(f"【{self.pure_user_id}】DrissionPage浏览器已关闭")
            except Exception as e:
                logger.warning(f"【{self.pure_user_id}】关闭浏览器时出错: {e}")
    
    def run(self, url: str, cookies_str: str = None):
        """运行主流程，返回(成功状态, cookie数据)

        Args:
            url: 滑块惩罚页地址
            cookies_str: 账号 Cookie。必须注入，否则验证通过后拿到的
                         x5sec 不绑定该账号，风控不会解除。
        """
        cookies = None
        try:
            # 检查日期有效性
            if not self._check_date_validity():
                logger.error(f"【{self.pure_user_id}】日期验证失败，无法执行")
                return False, None

            # 初始化浏览器
            self.init_browser()

            # 注入账号 Cookie —— 惩罚页的 x5secdata 绑定的是账号会话，
            # 不带 Cookie 时即便滑块拖过，回收到的也只是空浏览器凭证（实测仅 164 字符），
            # 风控状态不会解除。
            if cookies_str:
                try:
                    pw_cookies = []
                    for part in cookies_str.split(";"):
                        part = part.strip()
                        if "=" not in part:
                            continue
                        name, value = part.split("=", 1)
                        pw_cookies.append({
                            "name": name.strip(),
                            "value": value.strip(),
                            "domain": ".goofish.com",
                            "path": "/",
                        })
                    if pw_cookies:
                        self.context.add_cookies(pw_cookies)
                        logger.info(
                            f"【{self.pure_user_id}】已注入账号 Cookie（{len(pw_cookies)} 个字段）"
                        )
                except Exception as ck_err:
                    logger.warning(f"【{self.pure_user_id}】注入 Cookie 失败: {ck_err}")
            else:
                logger.warning(
                    f"【{self.pure_user_id}】未提供账号 Cookie —— 验证通过后风控可能不解除"
                )

            # 导航到目标URL，快速加载
            logger.info(f"【{self.pure_user_id}】导航到URL: {url}")
            # 记录下来供重试时重新加载 —— 验证失败后控件会锁死，
            # 只有重新导航才能拿到可用的新滑块
            self._current_url = url
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"【{self.pure_user_id}】页面加载异常，尝试继续: {str(e)}")
                # 如果页面加载失败，尝试等待一下
                time.sleep(2)
            
            # 短暂延迟，快速处理
            delay = random.uniform(0.3, 0.8)
            logger.info(f"【{self.pure_user_id}】等待页面加载: {delay:.2f}秒")
            time.sleep(delay)
            
            # 快速滚动（可选）
            self.page.mouse.move(640, 360)
            time.sleep(random.uniform(0.02, 0.05))
            self.page.mouse.wheel(0, random.randint(200, 500))
            time.sleep(random.uniform(0.02, 0.05))
            
            # 检查页面标题
            page_title = self.page.title()
            logger.info(f"【{self.pure_user_id}】页面标题: {page_title}")
            
            # 检查页面内容
            page_content = self.page.content()
            if any(keyword in page_content for keyword in ["验证码", "captcha", "滑块", "slider"]):
                logger.info(f"【{self.pure_user_id}】页面内容包含验证码相关关键词")
                
                # 处理滑块验证
                success = self.solve_slider()
                
                if success:
                    logger.info(f"【{self.pure_user_id}】滑块验证成功")
                    
                    # 等待页面完全加载和跳转，让新的cookie生效（快速模式）
                    try:
                        logger.info(f"【{self.pure_user_id}】等待页面加载...")
                        time.sleep(1)  # 快速等待，从3秒减少到1秒
                        
                        # 等待页面跳转或刷新
                        self.page.wait_for_load_state("networkidle", timeout=10000)
                        time.sleep(0.5)  # 快速确认，从2秒减少到0.5秒
                        
                        logger.info(f"【{self.pure_user_id}】页面加载完成，开始获取cookie")
                    except Exception as e:
                        logger.warning(f"【{self.pure_user_id}】等待页面加载时出错: {str(e)}")
                    
                    # 在关闭浏览器前获取cookie
                    try:
                        cookies = self._get_cookies_after_success()
                    except Exception as e:
                        logger.warning(f"【{self.pure_user_id}】获取cookie时出错: {str(e)}")
                else:
                    logger.warning(f"【{self.pure_user_id}】滑块验证失败")
                
                return success, cookies
            else:
                logger.info(f"【{self.pure_user_id}】页面内容不包含验证码相关关键词，可能不需要验证")
                return True, None
                
        except Exception as e:
            logger.error(f"【{self.pure_user_id}】执行过程中出错: {str(e)}")
            return False, None
        finally:
            # 关闭浏览器
            self.close_browser()

def get_slider_stats():
    """获取滑块验证并发统计信息"""
    return concurrency_manager.get_stats()

if __name__ == "__main__":
    # 简单的命令行示例
    import sys
    if len(sys.argv) < 2:
        print("用法: python xianyu_slider_stealth.py <URL>")
        sys.exit(1)
    
    url = sys.argv[1]
    # 第三个参数可以指定 headless 模式，默认为 True（无头）
    headless = sys.argv[2].lower() == 'true' if len(sys.argv) > 2 else True
    slider = XianyuSliderStealth("test_user", enable_learning=True, headless=headless)
    try:
        success, cookies = slider.run(url)
        print(f"验证结果: {'成功' if success else '失败'}")
        if cookies:
            print(f"获取到 {len(cookies)} 个cookies")
    except Exception as e:
        print(f"验证异常: {e}")
