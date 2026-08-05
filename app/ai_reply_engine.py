"""
AI回复引擎模块
集成XianyuAutoAgent的AI回复功能到现有项目中

【P0/P1 最小化修改版】
- 修复 P1-1 (高成本): detect_intent 改为本地关键词
- 修复 P0-2 (部署陷阱): 移除客户端缓存，实现无状态
- 修复 P1-3 (健壮性): 增强 Gemini 消息格式化
- 遵照指示，未修复 P0-1 (议价竞争条件)
"""

import os
import json
import time
import sqlite3
import requests  # 确保已导入
import threading
import re
from typing import List, Dict, Optional
from loguru import logger
from openai import OpenAI
from app.db_manager import db_manager


class AIReplyEngine:
    """AI回复引擎"""
    
    def __init__(self):
        # 修复 P0-2: 移除有状态的缓存，以支持多进程部署
        # self.clients = {}  # 已移除
        # self.agents = {}   # 已移除
        # self.client_last_used = {}  # 已移除
        self._init_default_prompts()
        # 用于控制同一chat_id消息的串行处理
        self._chat_locks = {}
        self._chat_locks_lock = threading.Lock()
    
    def _init_default_prompts(self):
        """初始化默认提示词"""
        self.default_prompts = {
            'classify': '''你是一个意图分类专家...（此提示词已不再被 detect_intent 使用）''',
            
            'price': '''你是一位经验丰富的销售专家，擅长议价。
语言要求：简短直接，每句≤10字，总字数≤40字。
议价策略：
1. 根据议价次数递减优惠：第1次小幅优惠，第2次中等优惠，第3次最大优惠
2. 接近最大议价轮数时要坚持底线，强调商品价值
3. 优惠不能超过设定的最大百分比和金额
4. 语气要友好但坚定，突出商品优势
注意：结合商品信息、对话历史和议价设置，给出合适的回复。''',
            
            'tech': '''你是一位技术专家，专业解答产品相关问题。
语言要求：简短专业，每句≤10字，总字数≤40字。
回答重点：产品功能、使用方法、注意事项。
注意：基于商品信息回答，避免过度承诺。''',
            
            'default': '''你是一位资深电商卖家，提供优质客服。
语言要求：简短友好，每句≤10字，总字数≤40字。
回答重点：商品介绍、物流、售后等常见问题。
注意：结合商品信息，给出实用建议。'''
        }
    
    def _create_openai_client(self, cookie_id: str) -> Optional[OpenAI]:
        """
        (原 get_client) 创建指定账号的OpenAI客户端
        修复 P0-2: 移除了缓存逻辑，以支持多进程无状态部署
        """
        settings = db_manager.get_ai_reply_settings(cookie_id)
        if not settings['ai_enabled'] or not settings['api_key']:
            return None
        
        try:
            logger.info(f"创建新的OpenAI客户端实例 {cookie_id}: base_url={settings['base_url']}, api_key={'***' + settings['api_key'][-4:] if settings['api_key'] else 'None'}")
            client = OpenAI(
                api_key=settings['api_key'],
                base_url=settings['base_url'],
                timeout=30.0,
            )
            logger.info(f"为账号 {cookie_id} 创建OpenAI客户端成功，实际base_url: {client.base_url}")
            return client
        except Exception as e:
            logger.error(f"创建OpenAI客户端失败 {cookie_id}: {e}")
            return None

    def _is_dashscope_api(self, settings: dict) -> bool:
        """判断是否为DashScope API - 只有选择自定义模型时才使用"""
        model_name = settings.get('model_name', '')
        base_url = settings.get('base_url', '')

        is_custom_model = model_name.lower() in ['custom', '自定义', 'dashscope', 'qwen-custom']
        is_dashscope_url = 'dashscope.aliyuncs.com' in base_url

        logger.info(f"API类型判断: model_name={model_name}, is_custom_model={is_custom_model}, is_dashscope_url={is_dashscope_url}")

        return is_custom_model and is_dashscope_url

    def _is_gemini_api(self, settings: dict) -> bool:
        """判断是否为Gemini API (通过模型名称)"""
        model_name = settings.get('model_name', '').lower()
        return 'gemini' in model_name

    def _call_dashscope_api(self, settings: dict, messages: list, max_tokens: int = 100, temperature: float = 0.7) -> str:
        """调用DashScope API"""
        base_url = settings['base_url']
        if '/apps/' in base_url:
            app_id = base_url.split('/apps/')[-1].split('/')[0]
        else:
            raise ValueError("DashScope API URL中未找到app_id")

        url = f"https://dashscope.aliyuncs.com/api/v1/apps/{app_id}/completion"

        role_labels = {'system': '系统规则', 'user': '买家', 'assistant': '卖家'}
        prompt = "\n".join(
            f"{role_labels.get(msg['role'], msg['role'])}：{msg['content']}"
            for msg in messages
        )
        prompt += "\n卖家："

        data = {
            "input": {"prompt": prompt},
            "parameters": {"max_tokens": max_tokens, "temperature": temperature},
            "debug": {}
        }
        headers = {
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json"
        }

        logger.info(f"DashScope API请求: {url}")
        logger.debug("DashScope 请求已构建，prompt 内容不写入日志")

        response = requests.post(url, headers=headers, json=data, timeout=30)

        if response.status_code != 200:
            logger.error(f"DashScope API请求失败: HTTP {response.status_code}")
            raise RuntimeError(f"DashScope API请求失败: HTTP {response.status_code}")

        result = response.json()
        if 'output' in result and 'text' in result['output']:
            return result['output']['text'].strip()
        else:
            raise RuntimeError("DashScope API响应格式错误")

    def _call_gemini_api(self, settings: dict, messages: list, max_tokens: int = 100, temperature: float = 0.7) -> str:
        """
        调用Google Gemini REST API (v1beta)
        """
        api_key = settings['api_key']
        model_name = settings['model_name'] 
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

        headers = {"Content-Type": "application/json"}

        system_instruction = ""
        contents = []
        for msg in messages:
            if msg['role'] == 'system':
                system_instruction = msg['content']
            elif msg['role'] in {'user', 'assistant'}:
                contents.append({
                    "role": "user" if msg['role'] == 'user' else "model",
                    "parts": [{"text": msg['content']}],
                })

        if not contents or contents[-1]["role"] != "user":
            logger.warning("Gemini API 调用未找到 user 角色内容")
            raise ValueError("未在消息中找到用户内容 (user content)")

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        logger.info(f"Calling Gemini REST API: {url.split('?')[0]}")
        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code != 200:
            logger.error(f"Gemini API 请求失败: HTTP {response.status_code}")
            raise RuntimeError(f"Gemini API 请求失败: HTTP {response.status_code}")
            
        result = response.json()
        try:
            reply_text = result['candidates'][0]['content']['parts'][0]['text']
            return reply_text.strip()
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Gemini API 响应格式错误: {type(e).__name__}")
            raise RuntimeError("Gemini API 响应格式错误")

    def _call_openai_api(self, client: OpenAI, settings: dict, messages: list, max_tokens: int = 100, temperature: float = 0.7) -> str:
        """调用OpenAI兼容API"""
        try:
            logger.info(f"调用OpenAI API: model={settings['model_name']}, base_url={settings.get('base_url', 'default')}")
            response = client.chat.completions.create(
                model=settings['model_name'],
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            status_code = getattr(getattr(e, 'response', None), 'status_code', None)
            logger.error(
                f"OpenAI API调用失败: {type(e).__name__}"
                + (f", HTTP {status_code}" if status_code else "")
            )
            raise

    def _resolve_system_prompt(self, raw_prompts: str, intent: str) -> str:
        """兼容旧版 JSON 提示词和新版纯文本风格说明。"""
        base_prompt = self.default_prompts.get(intent, self.default_prompts['default'])
        if not raw_prompts or not raw_prompts.strip():
            return base_prompt

        try:
            parsed = json.loads(raw_prompts)
        except (TypeError, json.JSONDecodeError):
            return f"{base_prompt}\n\n卖家补充规则：\n{raw_prompts.strip()}"

        if isinstance(parsed, dict):
            selected = parsed.get(intent) or parsed.get('default')
            if isinstance(selected, str) and selected.strip():
                return selected.strip()
        return base_prompt

    def _normalize_reply(self, reply: object) -> Optional[str]:
        """清理模型输出，拒绝空内容并限制自动发送长度。"""
        if not isinstance(reply, str):
            return None
        normalized = re.sub(r'\s+', ' ', reply).strip()
        normalized = normalized.strip('"\'`')
        if not normalized:
            return None
        return normalized[:300]

    @staticmethod
    def is_system_or_order_event(message: object) -> bool:
        """识别不应进入关键词、AI或默认回复链路的闲鱼系统事件。"""
        if not isinstance(message, str):
            return False
        text = message.strip()
        exact_messages = {
            '[我已拍下，待付款]',
            '[你关闭了订单，钱款已原路退返]',
            '[买家确认收货，交易成功]',
            '[你已确认收货，交易成功]',
            '[你已发货]',
            '已发货',
            '快给ta一个评价吧~',
            '快给ta一个评价吧～',
            '卖家人不错？送Ta闲鱼小红花',
            'AI正在帮你回复消息，不错过每笔订单',
            '发来一条消息',
            '发来一条新消息',
            '[不想宝贝被砍价?设置不砍价回复  ]',
        }
        if text in exact_messages:
            return True
        if text.startswith('[') and text.endswith(']'):
            event_words = ('付款', '发货', '收货', '退款', '交易成功', '订单关闭', '待评价')
            return any(word in text for word in event_words)
        return False

    def is_ai_enabled(self, cookie_id: str) -> bool:
        """检查指定账号是否启用AI回复"""
        settings = db_manager.get_ai_reply_settings(cookie_id)
        return settings['ai_enabled']
    
    def detect_intent(self, message: str, cookie_id: str) -> str:
        """
        检测用户消息意图 (基于关键词的本地检测)
        修复 P1-1: 移除了AI调用，以降低成本和延迟。
        """
        try:
            # 检查AI是否启用，如果未启用，不应执行任何AI相关逻辑
            # 注意：此检查在 generate_reply 的开头已经做过，但保留此处作为第二道防线
            settings = db_manager.get_ai_reply_settings(cookie_id)
            if not settings['ai_enabled']:
                return 'default'

            msg_lower = message.lower()

            # 价格相关关键词
            price_keywords = [
                '便宜', '优惠', '刀', '降价', '包邮', '价格', '多少钱', '能少', '还能', '最低', '底价',
                '实诚价', '到100', '能到', '包个邮', '给个价', '什么价' # <-- 增加这些“口语化”的词
            ]
            
            # 同样，你也可以通过正则表达式来匹配纯数字，比如 "100" "80"
            # 但那可能有点复杂，先加关键词是最小改动
            if any(kw in msg_lower for kw in price_keywords):
                logger.debug("本地意图检测: price")
                return 'price'

            # 技术相关关键词
            tech_keywords = ['怎么用', '参数', '坏了', '故障', '设置', '说明书', '功能', '用法', '教程', '驱动']
            if any(kw in msg_lower for kw in tech_keywords):
                logger.debug("本地意图检测: tech")
                return 'tech'
            
            logger.debug("本地意图检测: default")
            return 'default'
        
        except Exception as e:
            logger.error(f"本地意图检测失败 {cookie_id}: {e}")
            return 'default'
    
    def _get_chat_lock(self, chat_id: str) -> threading.Lock:
        """获取指定chat_id的锁，如果不存在则创建"""
        with self._chat_locks_lock:
            if chat_id not in self._chat_locks:
                self._chat_locks[chat_id] = threading.Lock()
            return self._chat_locks[chat_id]
    
    def generate_reply(self, message: str, item_info: dict, chat_id: str,
                      cookie_id: str, user_id: str, item_id: str,
                      skip_wait: bool = False) -> Optional[str]:
        """生成AI回复"""
        if not self.is_ai_enabled(cookie_id):
            return None
        if self.is_system_or_order_event(message):
            logger.info(f"系统/订单事件绕过AI回复: 账号={cookie_id}, chat_id={chat_id}")
            return None
        
        try:
            # 先检测意图（用于后续保存）
            intent = self.detect_intent(message, cookie_id)
            logger.info(f"检测到意图: {intent} (账号: {cookie_id})")
            
            # 在锁外先保存用户消息到数据库，让所有消息都能立即保存
            message_created_at = self.save_conversation(chat_id, cookie_id, user_id, item_id, "user", message, intent)
            
            # 如果调用方已经实现了去抖（debounce），可以通过 skip_wait=True 跳过内部等待
            if not skip_wait:
                logger.info(f"【{cookie_id}】消息已保存，等待10秒收集后续消息 (时间:{message_created_at})")
                # 固定等待10秒，等待可能的后续消息（在锁外延迟，避免阻塞其他消息保存）
                time.sleep(10)
            else:
                logger.info(f"【{cookie_id}】消息已保存（外部防抖已启用，跳过内部等待） (时间:{message_created_at})")
            
            # 获取该chat_id的锁，确保同一对话的消息串行处理
            chat_lock = self._get_chat_lock(chat_id)
            
            # 使用锁确保同一chat_id的消息串行处理
            with chat_lock:
                # 获取最近时间窗口内的所有用户消息
                # 如果 skip_wait=True（外部防抖），查询窗口为6秒（1秒防抖 + 5秒缓冲）
                # 如果 skip_wait=False（内部等待），查询窗口为25秒（10秒等待 + 10秒消息间隔 + 5秒缓冲）
                query_seconds = 6 if skip_wait else 25
                recent_messages = self._get_recent_user_messages(chat_id, cookie_id, seconds=query_seconds)
                logger.info(f"【{cookie_id}】最近{query_seconds}秒内用户消息数={len(recent_messages)}")
                
                if recent_messages and len(recent_messages) > 0:
                    # 只处理最后一条消息（时间戳最新的）
                    latest_message = recent_messages[-1]
                    if message_created_at != latest_message['created_at']:
                        logger.info(f"【{cookie_id}】检测到更新消息，跳过较早消息 (时间:{message_created_at})")
                        return None
                    else:
                        logger.info(f"【{cookie_id}】当前消息是最新消息，开始处理 (时间:{message_created_at})")
                
                # 1. 获取AI回复设置
                settings = db_manager.get_ai_reply_settings(cookie_id)

                # 3. 获取对话历史
                context = []
                if settings.get('context_enabled', True):
                    context = self.get_conversation_context(
                        chat_id,
                        cookie_id,
                        item_id=item_id,
                        limit=max(2, min(30, int(settings.get('context_message_limit', 12)))),
                        max_age_minutes=max(5, min(1440, int(settings.get('context_expire_minutes', 120)))),
                        exclude_current={
                            'role': 'user',
                            'content': message,
                            'created_at': message_created_at,
                        },
                    )

                # 4. 获取议价次数
                bargain_count = max(0, self.get_bargain_count(chat_id, cookie_id) - (1 if intent == "price" else 0))

                # 5. 检查议价轮数限制 (P0-1 竞争条件风险点 - 遵照指示未修改)
                if intent == "price":
                    max_bargain_rounds = settings.get('max_bargain_rounds', 3)
                    if bargain_count >= max_bargain_rounds:
                        logger.info(f"议价次数已达上限 ({bargain_count}/{max_bargain_rounds})，拒绝继续议价")
                        refuse_reply = f"抱歉，这个价格已经是最优惠的了，不能再便宜了哦！"
                        self.save_conversation(chat_id, cookie_id, user_id, item_id, "assistant", refuse_reply, intent)
                        return refuse_reply

                # 6. 构建提示词
                system_prompt = self._resolve_system_prompt(
                    settings.get('custom_prompts', ''),
                    intent,
                )

                # 7. 构建商品信息
                item_desc = f"商品标题: {item_info.get('title', '未知')}\n"
                item_desc += f"商品价格: {item_info.get('price', '未知')}元\n"
                item_desc += f"商品描述: {item_info.get('desc', '无')}"

                # 8. 构建角色化对话消息
                max_bargain_rounds = settings.get('max_bargain_rounds', 3)
                max_discount_percent = settings.get('max_discount_percent', 10)
                max_discount_amount = settings.get('max_discount_amount', 100)

                safety_prompt = f"""

商品与业务事实：
{item_desc}

议价设置：
- 当前议价次数：{bargain_count}
- 最大议价轮数：{max_bargain_rounds}
- 最大优惠百分比：{max_discount_percent}%
- 最大优惠金额：{max_discount_amount}元

安全边界：
- 只能依据上述商品事实回答，不得编造库存、规格、物流或售后承诺。
- 付款、发货、退款、收货和订单完成由系统订单状态与自动发货规则处理。
- 未经系统确认，不得声称上述操作已成功，也不得要求买家重复付款。
- 直接输出适合发送给买家的简短回复，不要解释规则。"""

                messages = [
                    {"role": "system", "content": system_prompt + safety_prompt},
                    *[
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in context
                        if msg.get("role") in {"user", "assistant"}
                        and not self.is_system_or_order_event(msg.get("content"))
                    ],
                    {"role": "user", "content": message},
                ]

                reply = None # 初始化 reply 变量

                if self._is_dashscope_api(settings):
                    logger.info(f"使用DashScope API生成回复")
                    reply = self._call_dashscope_api(settings, messages, max_tokens=100, temperature=0.7)
                
                elif self._is_gemini_api(settings):
                    logger.info(f"使用Gemini API生成回复")
                    reply = self._call_gemini_api(settings, messages, max_tokens=100, temperature=0.7)
                
                else:
                    logger.info(f"使用OpenAI兼容API生成回复")
                    # 修复 P0-2: 调用已修改的无状态客户端创建方法
                    client = self._create_openai_client(cookie_id)
                    if not client:
                        return None
                    reply = self._call_openai_api(client, settings, messages, max_tokens=100, temperature=0.7)

                reply = self._normalize_reply(reply)
                if not reply:
                    logger.warning(f"AI服务返回空回复，账号={cookie_id}, intent={intent}")
                    return None

                # 11. 保存AI回复到对话记录
                self.save_conversation(chat_id, cookie_id, user_id, item_id, "assistant", reply, intent)

                # 12. 更新议价次数 (此方法已在 get_bargain_count 中通过 SQL COUNT(*) 隐式实现)
                if intent == "price":
                    # self.increment_bargain_count(chat_id, cookie_id) # 此行原先就没有，保持不变
                    pass
                
                logger.info(
                    f"AI回复生成成功: 账号={cookie_id}, intent={intent}, 字符数={len(reply)}"
                )
                return reply
                
        except Exception as e:
            logger.error(f"AI回复生成失败: 账号={cookie_id}, 错误={type(e).__name__}: {e}")
            return None

    async def generate_reply_async(self, message: str, item_info: dict, chat_id: str,
                                   cookie_id: str, user_id: str, item_id: str,
                                   skip_wait: bool = False) -> Optional[str]:
        """
        异步包装器：在独立线程池中执行同步的 `generate_reply`，并返回结果。
        这样可以在异步代码中直接 await，而不阻塞事件循环。
        """
        try:
            import asyncio as _asyncio
            return await _asyncio.to_thread(self.generate_reply, message, item_info, chat_id, cookie_id, user_id, item_id, skip_wait)
        except Exception as e:
            logger.error(f"异步生成回复失败: {e}")
            return None
    
    def get_conversation_context(self, chat_id: str, cookie_id: str, item_id: Optional[str] = None,
                                 limit: int = 20, max_age_minutes: int = 120,
                                 exclude_current: Optional[Dict] = None) -> List[Dict]:
        """获取对话上下文"""
        try:
            with db_manager.lock:
                cursor = db_manager.conn.cursor()
                cursor.execute('''
                SELECT id, role, content, created_at FROM ai_conversations
                WHERE chat_id = ? AND cookie_id = ?
                  AND (? IS NULL OR item_id = ?)
                  AND created_at >= datetime('now', '-' || ? || ' minutes')
                ORDER BY created_at DESC LIMIT ?
                ''', (chat_id, cookie_id, item_id, item_id, max_age_minutes, limit + 1))
                
                results = cursor.fetchall()
                skipped_current = False
                context = []
                for row in results:
                    candidate = {
                        "id": row[0], "role": row[1], "content": row[2], "created_at": row[3]
                    }
                    if (
                        exclude_current and not skipped_current
                        and candidate["role"] == exclude_current.get("role")
                        and candidate["content"] == exclude_current.get("content")
                        and candidate["created_at"] == exclude_current.get("created_at")
                    ):
                        skipped_current = True
                        continue
                    if not self.is_system_or_order_event(candidate["content"]):
                        context.append({"role": candidate["role"], "content": candidate["content"]})
                context = list(reversed(context[:limit]))
                return context
        except Exception as e:
            logger.error(f"获取对话上下文失败: {e}")
            return []
    
    def save_conversation(self, chat_id: str, cookie_id: str, user_id: str, 
                         item_id: str, role: str, content: str, intent: str = None) -> Optional[str]:
        """保存对话记录，返回创建时间"""
        try:
            with db_manager.lock:
                cursor = db_manager.conn.cursor()
                cursor.execute('''
                INSERT INTO ai_conversations 
                (cookie_id, chat_id, user_id, item_id, role, content, intent)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (cookie_id, chat_id, user_id, item_id, role, content, intent))
                db_manager.conn.commit()
                
                # 获取刚插入记录的created_at
                cursor.execute('''
                SELECT created_at FROM ai_conversations 
                WHERE rowid = last_insert_rowid()
                ''')
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"保存对话记录失败: {e}")
            return None
    def get_bargain_count(self, chat_id: str, cookie_id: str) -> int:
        """获取议价次数"""
        try:
            with db_manager.lock:
                cursor = db_manager.conn.cursor()
                cursor.execute('''
                SELECT COUNT(*) FROM ai_conversations 
                WHERE chat_id = ? AND cookie_id = ? AND intent = 'price' AND role = 'user'
                ''', (chat_id, cookie_id))
                
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"获取议价次数失败: {e}")
            return 0
    
    def _get_recent_user_messages(self, chat_id: str, cookie_id: str, seconds: int = 2) -> List[Dict]:
        """获取最近seconds秒内的所有用户消息（包含内容和时间戳）"""
        try:
            with db_manager.lock:
                cursor = db_manager.conn.cursor()
                cursor.execute('''
                SELECT content, created_at FROM ai_conversations 
                WHERE chat_id = ? AND cookie_id = ? AND role = 'user' 
                AND julianday('now') - julianday(created_at) < (? / 86400.0)
                ORDER BY created_at ASC
                ''', (chat_id, cookie_id, seconds))
                
                results = cursor.fetchall()
                return [{"content": row[0], "created_at": row[1]} for row in results]
        except Exception as e:
            logger.error(f"获取最近用户消息列表失败: {e}")
            return []
    
    def increment_bargain_count(self, chat_id: str, cookie_id: str):
        """(此方法已废弃，通过 get_bargain_count 的 SQL 查询实现)"""
        pass
    
    #
    # --- 修复 P0-2: 移除所有有状态的缓存管理方法 ---
    #
    
    # def clear_client_cache(self, cookie_id: str = None):
    #     """(已移除) 清理客户端缓存"""
    #     pass
    
    # def cleanup_unused_clients(self, max_idle_hours: int = 24):
    #     """(已移除) 清理长时间未使用的客户端"""
    #     pass


# 全局AI回复引擎实例
ai_reply_engine = AIReplyEngine()
