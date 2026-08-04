#!/usr/bin/env python3
"""
闲鱼商品搜索模块
基于 Playwright 实现真实的闲鱼商品搜索功能
"""

import asyncio
import json
import time
import sys
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger

# 修复Docker环境中的asyncio事件循环策略问题
if sys.platform.startswith('linux') or os.getenv('DOCKER_ENV'):
    try:
        # 在Linux/Docker环境中设置事件循环策略
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    except Exception as e:
        logger.warning(f"设置事件循环策略失败: {e}")

# 确保在Docker环境中使用正确的事件循环
if os.getenv('DOCKER_ENV'):
    try:
        # 强制使用SelectorEventLoop（在Docker中更稳定）
        if hasattr(asyncio, 'SelectorEventLoop'):
            loop = asyncio.SelectorEventLoop()
            asyncio.set_event_loop(loop)
    except Exception as e:
        logger.warning(f"设置SelectorEventLoop失败: {e}")

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright 未安装，将使用模拟数据")


class XianyuSearcher:
    """闲鱼商品搜索器 - 基于 Playwright"""

    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self.api_responses = []
        self.user_id = "default"  # 默认用户ID

    async def _handle_scratch_captcha_manual(self, page, max_retries=3, wait_for_completion=True):
        """人工处理刮刮乐滑块（远程控制 + 截图备份）
        
        参数:
            wait_for_completion: 是否等待用户完成验证
                - True: 等待用户完成验证（默认，用于直接处理）
                - False: 创建会话后立即返回（用于前端处理）
        """
        import random
        
        logger.warning("=" * 60)
        logger.warning("🎨 检测到刮刮乐验证，需要人工处理！")
        logger.warning("=" * 60)
        
        # 获取会话ID
        session_id = getattr(self, 'user_id', 'default')
        
        # 【新方案】启用远程控制
        use_remote_control = getattr(self, 'use_remote_control', True)
        
        if use_remote_control:
            try:
                from utils.captcha_remote_control import captcha_controller
                
                # 创建远程控制会话
                logger.warning(f"🌐 启动远程控制会话: {session_id}")
                session_info = await captcha_controller.create_session(session_id, page)
                
                # 获取控制页面URL
                import socket
                import os
                
                # 尝试多种方式获取IP
                local_ip = "localhost"
                
                # 方法1：从环境变量获取（Docker/配置文件）
                local_ip = os.getenv('SERVER_HOST') or os.getenv('PUBLIC_IP')
                
                if not local_ip:
                    # 方法2：尝试获取外网IP
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.connect(("8.8.8.8", 80))
                        local_ip = s.getsockname()[0]
                        s.close()
                        
                        # 检查是否是Docker内网IP（172.x.x.x 或 10.x.x.x）
                        if local_ip.startswith('172.') or local_ip.startswith('10.'):
                            logger.warning(f"⚠️ 检测到Docker内网IP: {local_ip}")
                            local_ip = None  # 重置，使用localhost
                    except:
                        pass
                
                if not local_ip:
                    local_ip = "localhost"
                    logger.warning("⚠️ 无法获取外网IP，使用 localhost")
                    logger.warning("💡 如果在Docker中，请设置环境变量 SERVER_HOST 为公网IP")
                
                control_url = f"http://{local_ip}:8000/api/captcha/control/{session_id}"
                
                logger.warning("=" * 60)
                logger.warning(f"🌐 远程控制已启动！")
                logger.warning(f"📱 请访问以下网址进行验证：")
                logger.warning(f"   {control_url}")
                logger.warning("=" * 60)
                logger.warning(f"💡 或直接访问: http://{local_ip}:8000/api/captcha/control")
                logger.warning(f"   然后输入会话ID: {session_id}")
                logger.warning("=" * 60)
                
                # 如果不等待完成，立即返回特殊值给调用者
                if not wait_for_completion:
                    logger.warning("⚠️ 不等待验证完成，立即返回给前端处理")
                    return 'need_captcha'  # 返回特殊值，表示需要前端处理
                
                # 等待用户完成
                logger.warning("⏳ 等待用户通过网页完成验证...")
                
                # 循环检查是否完成
                max_wait_time = 180  # 3分钟
                check_interval = 1  # 每秒检查一次
                elapsed_time = 0
                
                while elapsed_time < max_wait_time:
                    await asyncio.sleep(check_interval)
                    elapsed_time += check_interval
                    
                    # 检查是否完成
                    if captcha_controller.is_completed(session_id):
                        logger.success("✅ 远程验证成功！")
                        await captcha_controller.close_session(session_id)
                        return True
                    
                    # 每10秒提示一次
                    if elapsed_time % 10 == 0:
                        logger.info(f"⏳ 仍在等待...已等待 {elapsed_time} 秒")
                
                logger.error(f"❌ 远程验证超时（{max_wait_time}秒）")
                await captcha_controller.close_session(session_id)
                return False
                
            except Exception as e:
                logger.error(f"远程控制启动失败: {e}")
                logger.warning("⚠️ 降级使用传统方式")
        
        logger.error("❌ 人工验证超时，已达到最大等待时间")
        return False
    
    async def _handle_scratch_captcha_async(self, page, max_retries=15):
        """异步处理刮刮乐类型滑块"""
        import random
        
        # 保存原始page对象（用于鼠标操作）
        original_page = page
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"🎨 刮刮乐滑块处理尝试 {attempt}/{max_retries}")
                
                # 重置page为原始对象
                page = original_page
                
                # 短暂等待（滑块已经存在，无需长时间等待）
                if attempt == 1:
                    await asyncio.sleep(0.3)
                else:
                    await asyncio.sleep(0.5)
                
                # 1. 快速检查刮刮乐容器（不阻塞，极短超时）
                try:
                    await page.wait_for_selector('#nocaptcha', timeout=500, state='attached')
                    logger.debug("✅ 刮刮乐容器 #nocaptcha 已加载")
                    await asyncio.sleep(0.2)  # 等待容器内部元素加载
                except:
                    # 容器未找到也继续，可能滑块还没出现
                    logger.debug("刮刮乐容器未立即加载，继续查找按钮...")
                
                # 2. 查找滑块按钮（先尝试主页面，再尝试iframe）
                button_selectors = [
                    '#scratch-captcha-btn',
                    '.button#scratch-captcha-btn',
                    'div#scratch-captcha-btn',
                    '.scratch-captcha-slider .button',
                    '#nocaptcha .button',
                    '#nocaptcha .scratch-captcha-slider .button',
                    '.button'
                ]
                
                slider_button = None
                found_in_iframe = False
                search_context = page  # 用于查找元素的上下文
                
                # 先在主页面查找（极速查找）
                for selector in button_selectors:
                    try:
                        # 先尝试等待可见（极短超时）
                        slider_button = await page.wait_for_selector(selector, timeout=800, state='visible')
                        if slider_button:
                            logger.info(f"✅ 在主页面找到刮刮乐滑块按钮（可见）: {selector}")
                            search_context = page
                            break
                    except:
                        # 如果等待可见失败，尝试只等待存在（attached）
                        try:
                            slider_button = await page.wait_for_selector(selector, timeout=300, state='attached')
                            if slider_button:
                                logger.warning(f"⚠️ 在主页面找到刮刮乐滑块按钮（不可见但存在）: {selector}")
                                search_context = page
                                break
                        except:
                            continue
                
                # 如果主页面没找到，尝试在iframe中查找（极速查找）
                if not slider_button:
                    try:
                        frames = page.frames
                        logger.debug(f"检查 {len(frames)} 个frame...")
                        for frame in frames:
                            if frame == page.main_frame:
                                continue
                            for selector in button_selectors:
                                try:
                                    slider_button = await frame.wait_for_selector(selector, timeout=500, state='visible')
                                    if slider_button:
                                        logger.info(f"✅ 在iframe中找到刮刮乐滑块按钮: {selector}")
                                        found_in_iframe = True
                                        search_context = frame  # iframe上下文用于查找
                                        break
                                except:
                                    continue
                            if slider_button:
                                break
                    except Exception as e:
                        logger.debug(f"检查iframe时出错: {e}")
                
                # 最后尝试：使用JavaScript直接查找（在search_context中）
                if not slider_button:
                    try:
                        logger.debug("尝试使用JavaScript直接查找滑块按钮...")
                        js_found = await search_context.evaluate("""
                            () => {
                                const btn = document.getElementById('scratch-captcha-btn') || 
                                           document.querySelector('#scratch-captcha-btn') ||
                                           document.querySelector('.button#scratch-captcha-btn');
                                if (btn) {
                                    return {
                                        found: true,
                                        visible: btn.offsetParent !== null,
                                        display: window.getComputedStyle(btn).display,
                                        visibility: window.getComputedStyle(btn).visibility
                                    };
                                }
                                return { found: false };
                            }
                        """)
                        
                        if js_found and js_found.get('found'):
                            logger.warning(f"⚠️ JavaScript找到按钮但Playwright无法访问: visible={js_found.get('visible')}, display={js_found.get('display')}, visibility={js_found.get('visibility')}")
                            # 尝试通过query_selector获取元素（强制操作）
                            slider_button = await search_context.query_selector('#scratch-captcha-btn')
                            if slider_button:
                                logger.info("✅ query_selector找到按钮")
                    except Exception as e:
                        logger.debug(f"JavaScript查找失败: {e}")
                
                if not slider_button:
                    logger.error("❌ 未找到刮刮乐滑块按钮（所有方法都已尝试）")
                    await asyncio.sleep(random.uniform(0.5, 1))
                    continue
                
                # 2. 获取滑块位置和大小
                button_box = await slider_button.bounding_box()
                if not button_box:
                    # 尝试使用JavaScript强制获取位置
                    try:
                        logger.warning("⚠️ 尝试使用JavaScript获取按钮位置...")
                        js_box = await search_context.evaluate("""
                            () => {
                                const btn = document.getElementById('scratch-captcha-btn');
                                if (btn) {
                                    const rect = btn.getBoundingClientRect();
                                    return {
                                        x: rect.x,
                                        y: rect.y,
                                        width: rect.width,
                                        height: rect.height
                                    };
                                }
                                return null;
                            }
                        """)
                        if js_box:
                            logger.info(f"✅ JavaScript获取到按钮位置: {js_box}")
                            button_box = js_box
                        else:
                            logger.error("❌ JavaScript也无法获取滑块按钮位置")
                            await asyncio.sleep(random.uniform(0.5, 1))
                            continue
                    except Exception as e:
                        logger.error(f"❌ 无法获取滑块按钮位置: {e}")
                        await asyncio.sleep(random.uniform(0.5, 1))
                        continue
                
                # 3. 计算滑动距离（25-35%）
                # 假设轨道宽度约为300px（可以根据实际调整）
                estimated_track_width = 300
                scratch_ratio = random.uniform(0.25, 0.35)
                slide_distance = estimated_track_width * scratch_ratio
                
                logger.warning(f"🎨 刮刮乐模式：计划滑动{scratch_ratio*100:.1f}%距离 ({slide_distance:.2f}px)")
                
                # 4. 执行滑动
                start_x = button_box['x'] + button_box['width'] / 2
                start_y = button_box['y'] + button_box['height'] / 2
                
                # 移动到滑块（优化等待时间）
                await page.mouse.move(start_x, start_y)
                await asyncio.sleep(random.uniform(0.1, 0.2))
                
                # 按下鼠标
                await page.mouse.down()
                await asyncio.sleep(random.uniform(0.05, 0.1))
                
                # 模拟人类化滑动轨迹（加快速度）
                steps = random.randint(10, 15)
                for i in range(steps):
                    progress = (i + 1) / steps
                    current_distance = slide_distance * progress
                    
                    # 添加Y轴抖动
                    y_jitter = random.uniform(-2, 2)
                    
                    await page.mouse.move(
                        start_x + current_distance,
                        start_y + y_jitter
                    )
                    await asyncio.sleep(random.uniform(0.005, 0.015))
                
                # 5. 在目标位置停顿观察（缩短时间）
                pause_duration = random.uniform(0.2, 0.3)
                logger.warning(f"🎨 在目标位置停顿{pause_duration:.2f}秒观察...")
                await asyncio.sleep(pause_duration)
                
                # 6. 释放鼠标
                await page.mouse.up()
                await asyncio.sleep(random.uniform(0.3, 0.5))
                
                # 7. 检查是否成功（检查滑块frame是否消失）
                try:
                    # 等待验证结果
                    await asyncio.sleep(0.8)
                    
                    # 检查主页面的滑块容器
                    captcha_in_main = await page.query_selector('#nocaptcha')
                    main_visible = False
                    if captcha_in_main:
                        try:
                            main_visible = await captcha_in_main.is_visible()
                        except:
                            main_visible = False
                    
                    # 检查iframe中的滑块
                    iframe_visible = False
                    try:
                        frames = page.frames
                        for frame in frames:
                            if frame != page.main_frame:
                                captcha_in_iframe = await frame.query_selector('#nocaptcha')
                                if captcha_in_iframe:
                                    try:
                                        if await captcha_in_iframe.is_visible():
                                            iframe_visible = True
                                            break
                                    except:
                                        pass
                    except:
                        pass
                    
                    # 判断成功：主页面和iframe都没有可见的滑块
                    if not main_visible and not iframe_visible:
                        logger.success(f"✅ 刮刮乐验证成功！滑块已消失（第{attempt}次尝试）")
                        return True
                    else:
                        if main_visible:
                            logger.warning(f"⚠️ 主页面滑块仍可见，继续重试...")
                        if iframe_visible:
                            logger.warning(f"⚠️ iframe滑块仍可见，继续重试...")
                except Exception as e:
                    logger.warning(f"⚠️ 检查验证结果时出错: {e}，继续重试...")
                
            except Exception as e:
                logger.error(f"❌ 刮刮乐处理异常: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                await asyncio.sleep(random.uniform(0.5, 1))
                continue
        
        logger.error(f"❌ 刮刮乐验证失败，已达到最大重试次数 {max_retries}")
        return False
    
    async def handle_slider_verification(self, page, context=None, browser=None, playwright=None, max_retries=5):
        """
        通用的滑块验证处理方法
        
        参数:
            page: Playwright 页面对象（必需）
            context: Playwright 上下文对象（可选，如果不传则使用 self.context）
            browser: Playwright 浏览器对象（可选，如果不传则使用 self.browser）
            playwright: Playwright 实例（可选，如果不传则使用 self.playwright）
            max_retries: 最大重试次数，默认5次
            
        返回:
            bool: True表示成功（包括没有滑块或滑块验证成功），False表示失败
        """
        try:
            # 等待页面加载滑块元素（优化等待时间）
            await asyncio.sleep(1)
            logger.info("🔍 开始检测滑块验证...")
            
            # 使用传入的对象或实例属性
            context = context or self.context
            browser = browser or self.browser
            playwright = playwright or getattr(self, 'playwright', None)
            
            # 【调试】打印页面HTML内容，查找滑块相关关键词
            try:
                page_content = await page.content()
                has_captcha_keyword = any(keyword in page_content.lower() for keyword in [
                    'nocaptcha', 'scratch-captcha', 'captcha', 'slider', '滑块', '验证'
                ])
                if has_captcha_keyword:
                    logger.warning("⚠️ 页面HTML中包含滑块相关关键词")
                    # 保存页面内容用于调试
                    if 'nocaptcha' in page_content or 'scratch-captcha' in page_content:
                        logger.warning("🎯 检测到刮刮乐类型滑块特征词！")
                else:
                    logger.info("✅ 页面HTML中未发现滑块关键词")
            except Exception as e:
                logger.debug(f"检查页面内容时出错: {e}")
            
            # 检测滑块元素（支持多种类型的滑块）
            slider_selectors = [
                # 阿里云盾 nc 系列滑块
                '#nc_1_n1z',
                '.nc-container',
                '.nc_scale',
                '.nc-wrapper',
                '[class*="nc_"]',
                '[id*="nc_"]',
                # 刮刮乐 (scratch-captcha) 类型滑块
                '#nocaptcha',
                '.scratch-captcha-container',
                '.scratch-captcha-slider',
                '#scratch-captcha-btn',
                '[class*="scratch-captcha"]',
                'div[id="nocaptcha"]',
                'div.scratch-captcha-container',
                # 其他常见滑块类型
                '.captcha-slider',
                '.slider-captcha',
                '[class*="captcha"]',
                '[id*="captcha"]'
            ]
            
            has_slider = False
            detected_selector = None
            found_elements = []
            
            for selector in slider_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        found_elements.append(selector)
                        is_visible = await element.is_visible()
                        logger.debug(f"找到元素 {selector}，可见性: {is_visible}")
                        if is_visible:
                            logger.info(f"✅ 检测到滑块验证元素: {selector}")
                            has_slider = True
                            detected_selector = selector
                            break
                except Exception as e:
                    logger.debug(f"选择器 {selector} 检测出错: {e}")
                    continue
            
            # 输出调试信息
            if found_elements:
                logger.warning(f"🔍 找到以下滑块元素（但可能不可见）: {', '.join(found_elements)}")
                # 如果找到了元素但不可见，强制认为有滑块
                if not has_slider and any('captcha' in sel.lower() or 'slider' in sel.lower() for sel in found_elements):
                    logger.warning("⚠️ 检测到滑块元素但不可见，仍然尝试处理")
                    has_slider = True
                    detected_selector = found_elements[0]
            else:
                logger.debug("未找到任何滑块选择器匹配的元素")
            
            # 【额外检测】检查 iframe 中的滑块
            if not has_slider:
                try:
                    frames = page.frames
                    logger.debug(f"检测到 {len(frames)} 个 frame")
                    for frame in frames:
                        if frame != page.main_frame:
                            try:
                                iframe_content = await frame.content()
                                # 更精确的刮刮乐检测：必须包含明确特征
                                has_scratch_features = 'scratch-captcha' in iframe_content or \
                                                      ('nocaptcha' in iframe_content and 'scratch' in iframe_content)
                                if has_scratch_features:
                                    logger.warning("🎯 在 iframe 中检测到刮刮乐滑块！")
                                    has_slider = True
                                    detected_selector = "iframe-scratch-captcha"
                                    break
                            except:
                                continue
                except Exception as e:
                    logger.debug(f"检查 iframe 时出错: {e}")
            
            # 如果没有检测到滑块，直接返回成功
            if not has_slider:
                logger.info("✅ 未检测到滑块验证，继续执行")
                return True
            
            # 检测到滑块，开始处理
            logger.warning(f"⚠️ 检测到滑块验证（{detected_selector}），开始处理...")
            
            # 检测是否为刮刮乐类型（更精确的判断）
            is_scratch_captcha = False
            
            # 明确的刮刮乐特征
            if 'scratch' in detected_selector.lower():
                is_scratch_captcha = True
            # 如果选择器是 #nocaptcha 但不是 nc 系列的标准滑块，则进一步检查
            elif detected_selector in ['#nocaptcha', 'iframe-scratch-captcha']:
                try:
                    page_html = await page.content()
                    # 检查是否有刮刮乐的明确特征
                    has_scratch_features = 'scratch-captcha' in page_html or \
                                          ('Release the slider' in page_html) or \
                                          ('fully appears' in page_html)
                    is_scratch_captcha = has_scratch_features
                except:
                    is_scratch_captcha = False
            
            if is_scratch_captcha:
                logger.warning("🎨 检测到刮刮乐类型滑块")
                
                # 人工处理模式 - 等待用户完成验证
                logger.warning("⚠️ 刮刮乐需要人工处理，等待验证完成")
                slider_success = await self._handle_scratch_captcha_manual(page, max_retries=3, wait_for_completion=True)
            else:
                actual_max_retries = max_retries
                slider_success = None
            
            try:
                # 刮刮乐已经处理过了，直接检查结果
                if is_scratch_captcha:
                    pass  # slider_success 已经在上面设置
                else:
                    # 普通滑块：使用 XianyuSliderStealth（同步API）
                    from utils.xianyu_slider_stealth import XianyuSliderStealth
                    
                    # 创建滑块处理实例
                    slider_handler = XianyuSliderStealth(
                        user_id=getattr(self, 'user_id', 'default'),
                        enable_learning=True,
                        headless=True
                    )
                    
                    # 将现有的浏览器对象传递给滑块处理器（复用现有浏览器）
                    slider_handler.page = page
                    slider_handler.context = context
                    slider_handler.browser = browser
                    slider_handler.playwright = playwright
                    
                    # 调用滑块处理方法
                    logger.info(f"🎯 开始处理滑块验证（最多尝试 {actual_max_retries} 次）...")
                    slider_success = slider_handler.solve_slider(max_retries=actual_max_retries)
                    
                    # 清除引用，防止 XianyuSliderStealth 尝试关闭我们的浏览器
                    slider_handler.page = None
                    slider_handler.context = None
                    slider_handler.browser = None
                    slider_handler.playwright = None
                
                if slider_success:
                    logger.success("✅ 滑块验证成功！")
                    return True
                else:
                    logger.error("❌ 滑块验证失败")
                    return False
                    
            except Exception as e:
                logger.error(f"❌ 滑块验证处理异常: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                
                # 确保清除引用
                try:
                    if 'slider_handler' in locals():
                        slider_handler.page = None
                        slider_handler.context = None
                        slider_handler.browser = None
                        slider_handler.playwright = None
                except:
                    pass
                
                return False
                
        except Exception as e:
            logger.error(f"❌ 滑块检测过程异常: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def safe_get(self, data, *keys, default="暂无"):
        """安全获取嵌套字典值"""
        for key in keys:
            try:
                data = data[key]
            except (KeyError, TypeError, IndexError):
                return default
        return data

    async def get_first_valid_cookie(self):
        """获取第一个有效的cookie"""
        try:
            from app.db_manager import db_manager

            # 获取所有cookies，返回格式是 {id: value}
            cookies = db_manager.get_all_cookies()

            # 找到第一个有效的cookie（长度大于50的认为是有效的）
            for cookie_id, cookie_value in cookies.items():
                if len(cookie_value) > 50:
                    logger.info(f"找到有效cookie: {cookie_id}")
                    return {
                        'id': cookie_id,
                        'value': cookie_value
                    }

            return None

        except Exception as e:
            logger.error(f"获取cookie失败: {str(e)}")
            return None

    async def set_browser_cookies(self, cookie_value: str):
        """设置浏览器cookies"""
        try:
            if not cookie_value:
                return False

            # 解析cookie字符串
            cookies = []
            for cookie_pair in cookie_value.split(';'):
                cookie_pair = cookie_pair.strip()
                if '=' in cookie_pair:
                    name, value = cookie_pair.split('=', 1)
                    cookies.append({
                        'name': name.strip(),
                        'value': value.strip(),
                        'domain': '.goofish.com',
                        'path': '/'
                    })

            # 设置cookies到浏览器
            await self.context.add_cookies(cookies)
            logger.info(f"成功设置 {len(cookies)} 个cookies到浏览器")
            return True

        except Exception as e:
            logger.error(f"设置浏览器cookies失败: {str(e)}")
            return False

    async def init_browser(self):
        """初始化浏览器（使用持久化上下文，保留缓存和cookies）"""
        if not PLAYWRIGHT_AVAILABLE:
            raise Exception("Playwright 未安装，无法使用真实搜索功能")

        if not self.browser:
            playwright = await async_playwright().start()
            
            # 设置持久化数据目录（保存缓存、cookies等）
            import tempfile
            user_data_dir = os.path.join(tempfile.gettempdir(), 'xianyu_browser_cache')
            os.makedirs(user_data_dir, exist_ok=True)
            logger.info(f"使用持久化数据目录（保留缓存）: {user_data_dir}")
            
            # 简化的浏览器启动参数，避免冲突
            browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--no-first-run',
                '--disable-extensions',
                '--disable-default-apps',
                '--no-default-browser-check',
                # 中文语言设置
                '--lang=zh-CN',
                '--accept-lang=zh-CN,zh,en-US,en'
            ]

            # 只在确实是Docker环境时添加额外参数
            if os.getenv('DOCKER_ENV') == 'true':
                browser_args.extend([
                    '--disable-gpu',
                    # 移除--single-process参数，使用多进程模式提高稳定性
                    # '--single-process'  # 注释掉，避免崩溃
                ])

            logger.info("正在启动浏览器（中文模式，持久化缓存）...")
            
            # 使用 launch_persistent_context 实现跨会话的缓存持久化
            # 这样通过一次滑块验证后，下次搜索可以复用缓存，避免再次出现滑块
            self.context = await playwright.chromium.launch_persistent_context(
                user_data_dir,  # 第一个参数是用户数据目录，用于持久化
                headless=True,  # 无头模式，后台运行
                args=browser_args,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 720},
                locale='zh-CN',  # 设置语言为中文
                # 持久化上下文会自动保存和加载：
                # - Cookies
                # - 缓存
                # - LocalStorage
                # - SessionStorage
                # - 其他浏览器状态
            )
            
            # launch_persistent_context 返回的是 context，不是 browser
            # 需要通过 context.browser 获取 browser 对象
            self.browser = self.context.browser

            logger.info("浏览器启动成功（持久化上下文已创建）...")

            logger.info("创建页面...")
            self.page = await self.context.new_page()

            logger.info("浏览器初始化完成（缓存将持久化保存）")

    async def close_browser(self):
        """关闭浏览器（持久化上下文会自动保存缓存和cookies）"""
        try:
            if self.page:
                await self.page.close()
                self.page = None
            # 注意：使用 persistent_context 时，关闭 context 会自动保存所有数据
            if self.context:
                await self.context.close()
                self.context = None
            # persistent_context 的 browser 会在 context 关闭时自动关闭
            # 不需要单独关闭 browser
            self.browser = None
            logger.debug("商品搜索器浏览器已关闭（缓存已保存）")
        except Exception as e:
            logger.warning(f"关闭商品搜索器浏览器时出错: {e}")
    
    async def search_items(self, keyword: str, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """
        搜索闲鱼商品 - 使用 Playwright 获取真实数据

        Args:
            keyword: 搜索关键词
            page: 页码，从1开始
            page_size: 每页数量

        Returns:
            搜索结果字典，包含items列表和总数
        """
        try:
            if not PLAYWRIGHT_AVAILABLE:
                logger.error("Playwright 不可用，无法获取真实数据")
                return {
                    'items': [],
                    'total': 0,
                    'error': 'Playwright 不可用，无法获取真实数据'
                }

            logger.info(f"使用 Playwright 搜索闲鱼商品: 关键词='{keyword}', 页码={page}, 每页={page_size}")

            await self.init_browser()

            # 清空之前的API响应
            self.api_responses = []
            data_list = []

            # 设置API响应监听器
            async def on_response(response):
                """处理API响应，解析数据"""
                if "h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search" in response.url:
                    try:
                        # 检查响应状态
                        if response.status != 200:
                            logger.warning(f"API响应状态异常: {response.status}")
                            return

                        # 安全地获取响应内容
                        try:
                            result_json = await response.json()
                        except Exception as json_error:
                            logger.warning(f"无法解析响应JSON: {str(json_error)}")
                            return

                        self.api_responses.append(result_json)
                        logger.info(f"捕获到API响应，URL: {response.url}")

                        items = result_json.get("data", {}).get("resultList", [])
                        logger.info(f"从API获取到 {len(items)} 条原始数据")

                        for item in items:
                            try:
                                parsed_item = await self._parse_real_item(item)
                                if parsed_item:
                                    data_list.append(parsed_item)
                            except Exception as parse_error:
                                logger.warning(f"解析单个商品失败: {str(parse_error)}")
                                continue

                    except Exception as e:
                        logger.warning(f"响应处理异常: {str(e)}")

            try:
                # 获取并设置cookies进行登录
                logger.info("正在获取有效的cookies账户...")
                cookie_data = await self.get_first_valid_cookie()
                if not cookie_data:
                    raise Exception("未找到有效的cookies账户，请先在Cookie管理中添加有效的闲鱼账户")

                logger.info(f"使用账户: {cookie_data.get('id', 'unknown')}")

                logger.info("正在访问闲鱼首页...")
                await self.page.goto("https://www.goofish.com", timeout=30000)

                # 设置cookies进行登录
                logger.info("正在设置cookies进行登录...")
                cookie_success = await self.set_browser_cookies(cookie_data.get('value', ''))
                if not cookie_success:
                    logger.warning("设置cookies失败，将以未登录状态继续")
                else:
                    logger.info("✅ cookies设置成功，已登录")
                    # 刷新页面以应用cookies
                    await self.page.reload()
                    await asyncio.sleep(2)
               
                    

                await self.page.wait_for_load_state("networkidle", timeout=10000)

                logger.info(f"正在搜索关键词: {keyword}")
                await self.page.fill('input[class*="search-input"]', keyword)

                # 注册响应监听
                self.page.on("response", on_response)

                await self.page.click('button[type="submit"]')
                                  
                await self.page.wait_for_load_state("networkidle", timeout=15000)

                # 等待第一页API响应（缩短等待时间）
                logger.info("等待第一页API响应...")
                await asyncio.sleep(2)
                
                # 尝试处理弹窗
                try:
                    await self.page.keyboard.press('Escape')
                    await asyncio.sleep(0.5)
                except:
                    pass
                # 【核心】检测并处理滑块验证 → 使用公共方法
                logger.info(f"检测是否有滑块验证...")
                slider_result = await self.handle_slider_verification(
                    page=self.page,
                    context=self.context,
                    browser=self.browser,
                    playwright=getattr(self, 'playwright', None),
                    max_retries=5
                )
                
                if not slider_result:
                    logger.error(f"❌ 滑块验证失败，搜索终止")
                    return None
                # 等待更多数据
                await asyncio.sleep(3)

                first_page_count = len(data_list)
                logger.info(f"第1页完成，获取到 {first_page_count} 条数据")

                # 如果需要获取指定页数据，实现翻页逻辑
                if page > 1:
                    # 清空之前的数据，只保留目标页的数据
                    data_list.clear()
                    await self._navigate_to_page(page)

                # 根据"人想要"数量进行倒序排列
                data_list.sort(key=lambda x: x.get('want_count', 0), reverse=True)

                total_count = len(data_list)
                logger.info(f"搜索完成，总共获取到 {total_count} 条真实数据，已按想要人数排序")

                return {
                    'items': data_list,
                    'total': total_count,
                    'is_real_data': True,
                    'source': 'playwright'
                }

            finally:
                await self.close_browser()

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Playwright 搜索失败: {error_msg}")

            # 检查是否是浏览器安装问题
            if "Executable doesn't exist" in error_msg or "playwright install" in error_msg:
                error_msg = "浏览器未安装。请在Docker容器中运行: playwright install chromium"
            elif "BrowserType.launch" in error_msg:
                error_msg = "浏览器启动失败。请确保Docker容器有足够的权限和资源"

            # 如果 Playwright 失败，返回错误信息
            return {
                'items': [],
                'total': 0,
                'error': f'搜索失败: {error_msg}'
            }

    async def _get_fallback_data(self, keyword: str, page: int, page_size: int) -> Dict[str, Any]:
        """获取备选数据（模拟数据）"""
        logger.info(f"使用备选数据: 关键词='{keyword}', 页码={page}, 每页={page_size}")

        # 模拟搜索延迟
        await asyncio.sleep(0.5)

        # 生成模拟数据
        mock_items = []
        start_index = (page - 1) * page_size

        for i in range(page_size):
            item_index = start_index + i + 1
            mock_items.append({
                'item_id': f'mock_{keyword}_{item_index}',
                'title': f'{keyword}相关商品 #{item_index} [模拟数据]',
                'price': f'{100 + item_index * 10}',
                'seller_name': f'卖家{item_index}',
                'item_url': f'https://www.goofish.com/item?id=mock_{keyword}_{item_index}',
                'publish_time': '2025-07-28',
                'tags': [f'标签{i+1}', f'分类{i+1}'],
                'main_image': f'https://via.placeholder.com/200x200?text={keyword}商品{item_index}',
                'raw_data': {
                    'mock': True,
                    'keyword': keyword,
                    'index': item_index
                }
            })

        # 模拟总数
        total_items = 100 + hash(keyword) % 500

        logger.info(f"备选数据生成完成: 找到{len(mock_items)}个商品，总计{total_items}个")

        return {
            'items': mock_items,
            'total': total_items,
            'is_fallback': True
        }

    async def _parse_real_item(self, item_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析真实的闲鱼商品数据"""
        try:
            main_data = await self.safe_get(item_data, "data", "item", "main", "exContent", default={})
            click_params = await self.safe_get(item_data, "data", "item", "main", "clickParam", "args", default={})

            # 解析商品信息
            title = await self.safe_get(main_data, "title", default="未知标题")

            # 价格处理
            price_parts = await self.safe_get(main_data, "price", default=[])
            price = "价格异常"
            if isinstance(price_parts, list):
                price = "".join([str(p.get("text", "")) for p in price_parts if isinstance(p, dict)])
                price = price.replace("当前价", "").strip()

                # 统一价格格式处理
                if price and price != "价格异常":
                    # 先移除所有¥符号，避免重复
                    clean_price = price.replace('¥', '').strip()

                    # 处理万单位的价格
                    if "万" in clean_price:
                        try:
                            numeric_price = clean_price.replace('万', '').strip()
                            price_value = float(numeric_price) * 10000
                            price = f"¥{price_value:.0f}"
                        except:
                            price = f"¥{clean_price}"  # 如果转换失败，保持原样但确保有¥符号
                    else:
                        # 普通价格，确保有¥符号
                        if clean_price and (clean_price[0].isdigit() or clean_price.replace('.', '').isdigit()):
                            price = f"¥{clean_price}"
                        else:
                            price = clean_price if clean_price else "价格异常"

            # 只提取"想要人数"标签
            fish_tags_content = ""
            fish_tags = await self.safe_get(main_data, "fishTags", default={})

            # 遍历所有类型的标签 (r2, r3, r4等)
            for tag_type, tag_data in fish_tags.items():
                if isinstance(tag_data, dict) and "tagList" in tag_data:
                    tag_list = tag_data.get("tagList", [])
                    for tag_item in tag_list:
                        if isinstance(tag_item, dict) and "data" in tag_item:
                            content = tag_item["data"].get("content", "")
                            # 只保留包含"人想要"的标签
                            if content and "人想要" in content:
                                fish_tags_content = content
                                break
                    if fish_tags_content:  # 找到后就退出
                        break

            # 其他字段解析
            area = await self.safe_get(main_data, "area", default="地区未知")
            seller = await self.safe_get(main_data, "userNickName", default="匿名卖家")
            raw_link = await self.safe_get(item_data, "data", "item", "main", "targetUrl", default="")
            image_url = await self.safe_get(main_data, "picUrl", default="")

            # 获取商品ID
            item_id = await self.safe_get(click_params, "item_id", default="未知ID")

            # 处理发布时间
            publish_time = "未知时间"
            publish_timestamp = click_params.get("publishTime", "")
            if publish_timestamp and publish_timestamp.isdigit():
                try:
                    publish_time = datetime.fromtimestamp(
                        int(publish_timestamp)/1000
                    ).strftime("%Y-%m-%d %H:%M")
                except:
                    pass

            # 提取"人想要"的数字用于排序
            want_count = self._extract_want_count(fish_tags_content)

            return {
                "item_id": item_id,
                "title": title,
                "price": price,
                "seller_name": seller,
                "item_url": raw_link.replace("fleamarket://", "https://www.goofish.com/"),
                "main_image": f"https:{image_url}" if image_url and not image_url.startswith("http") else image_url,
                "publish_time": publish_time,
                "tags": [fish_tags_content] if fish_tags_content else [],
                "area": area,
                "want_count": want_count,  # 添加想要人数用于排序
                "raw_data": item_data
            }

        except Exception as e:
            logger.warning(f"解析真实商品数据失败: {str(e)}")
            return None

    def _extract_want_count(self, tags_content: str) -> int:
        """从标签内容中提取"人想要"的数字"""
        try:
            if not tags_content or "人想要" not in tags_content:
                return 0

            # 使用正则表达式提取数字
            import re
            # 匹配类似 "123人想要" 或 "1.2万人想要" 的格式
            pattern = r'(\d+(?:\.\d+)?(?:万)?)\s*人想要'
            match = re.search(pattern, tags_content)

            if match:
                number_str = match.group(1)
                if '万' in number_str:
                    # 处理万单位
                    number = float(number_str.replace('万', '')) * 10000
                    return int(number)
                else:
                    return int(float(number_str))

            return 0
        except Exception as e:
            logger.warning(f"提取想要人数失败: {str(e)}")
            return 0

    async def _navigate_to_page(self, target_page: int):
        """导航到指定页面"""
        try:
            logger.info(f"正在导航到第 {target_page} 页...")

            # 等待页面稳定
            await asyncio.sleep(2)

            # 查找并点击下一页按钮
            next_button_selectors = [
                '.search-page-tiny-arrow-right--oXVFaRao',  # 用户找到的正确选择器
                '[class*="search-page-tiny-arrow-right"]',  # 更通用的版本
                'button[aria-label="下一页"]',
                'button:has-text("下一页")',
                'a:has-text("下一页")',
                '.ant-pagination-next',
                'li.ant-pagination-next a',
                'a[aria-label="下一页"]',
                '[class*="next"]',
                '[class*="pagination-next"]',
                'button[title="下一页"]',
                'a[title="下一页"]'
            ]

            # 从第2页开始点击
            for current_page in range(2, target_page + 1):
                logger.info(f"正在点击到第 {current_page} 页...")

                next_button_found = False
                for selector in next_button_selectors:
                    try:
                        next_button = self.page.locator(selector).first

                        if await next_button.is_visible(timeout=3000):
                            # 检查按钮是否可点击（不是禁用状态）
                            is_disabled = await next_button.get_attribute("disabled")
                            has_disabled_class = await next_button.evaluate("el => el.classList.contains('ant-pagination-disabled') || el.classList.contains('disabled')")

                            if not is_disabled and not has_disabled_class:
                                logger.info(f"找到下一页按钮，正在点击...")

                                # 滚动到按钮位置
                                await next_button.scroll_into_view_if_needed()
                                await asyncio.sleep(1)

                                # 点击下一页
                                await next_button.click()
                                await self.page.wait_for_load_state("networkidle", timeout=15000)

                                # 等待新数据加载
                                await asyncio.sleep(5)

                                logger.info(f"成功导航到第 {current_page} 页")
                                next_button_found = True
                                break

                    except Exception as e:
                        continue

                if not next_button_found:
                    logger.warning(f"无法找到下一页按钮，停止在第 {current_page-1} 页")
                    break

        except Exception as e:
            logger.error(f"导航到第 {target_page} 页失败: {str(e)}")

    async def search_multiple_pages(self, keyword: str, total_pages: int = 1) -> Dict[str, Any]:
        """
        搜索多页闲鱼商品

        Args:
            keyword: 搜索关键词
            total_pages: 总页数

        Returns:
            搜索结果字典，包含所有页面的items列表和总数
        """
        browser_initialized = False
        try:
            if not PLAYWRIGHT_AVAILABLE:
                logger.error("Playwright 不可用，无法获取真实数据")
                return {
                    'items': [],
                    'total': 0,
                    'error': 'Playwright 不可用，无法获取真实数据'
                }

            logger.info(f"使用 Playwright 搜索多页闲鱼商品: 关键词='{keyword}', 总页数={total_pages}")

            # 确保浏览器初始化
            await self.init_browser()
            browser_initialized = True

            # 验证浏览器状态
            if not self.browser or not self.page:
                raise Exception("浏览器初始化失败")

            logger.info("浏览器初始化成功，开始搜索...")

            # 清空之前的API响应
            self.api_responses = []
            all_data_list = []

            # 设置API响应监听器
            async def on_response(response):
                """处理API响应，解析数据"""
                if "h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search" in response.url:
                    try:
                        # 检查响应状态
                        if response.status != 200:
                            logger.warning(f"API响应状态异常: {response.status}")
                            return

                        # 安全地获取响应内容
                        try:
                            result_json = await response.json()
                        except Exception as json_error:
                            logger.warning(f"无法解析响应JSON: {str(json_error)}")
                            return

                        self.api_responses.append(result_json)
                        logger.info(f"捕获到API响应，URL: {response.url}")

                        items = result_json.get("data", {}).get("resultList", [])
                        logger.info(f"从API获取到 {len(items)} 条原始数据")

                        for item in items:
                            try:
                                parsed_item = await self._parse_real_item(item)
                                if parsed_item:
                                    all_data_list.append(parsed_item)
                            except Exception as parse_error:
                                logger.warning(f"解析单个商品失败: {str(parse_error)}")
                                continue

                    except Exception as e:
                        logger.warning(f"响应处理异常: {str(e)}")

            try:
                # 检查浏览器状态
                if not self.page or self.page.is_closed():
                    raise Exception("页面已关闭或不可用")

                # 获取并设置cookies进行登录
                logger.info("正在获取有效的cookies账户...")
                cookie_data = await self.get_first_valid_cookie()
                if not cookie_data:
                    raise Exception("未找到有效的cookies账户，请先在Cookie管理中添加有效的闲鱼账户")

                logger.info(f"使用账户: {cookie_data.get('id', 'unknown')}")

                logger.info("正在访问闲鱼首页...")
                await self.page.goto("https://www.goofish.com", timeout=30000)

                # 设置cookies进行登录
                logger.info("正在设置cookies进行登录...")
                cookie_success = await self.set_browser_cookies(cookie_data.get('value', ''))
                if not cookie_success:
                    logger.warning("设置cookies失败，将以未登录状态继续")
                else:
                    logger.info("✅ cookies设置成功，已登录")
                    # 刷新页面以应用cookies
                    await self.page.reload()
                    await asyncio.sleep(2)

                # 再次检查页面状态
                if self.page.is_closed():
                    raise Exception("页面在导航后被关闭")

                logger.info("等待页面加载完成...")
                await self.page.wait_for_load_state("networkidle", timeout=15000)

                # 等待页面稳定
                logger.info("等待页面稳定...")
                await asyncio.sleep(3)  # 增加等待时间

                # 再次检查页面状态
                if self.page.is_closed():
                    raise Exception("页面在等待加载后被关闭")

                # 获取页面标题和URL用于调试
                page_title = await self.page.title()
                page_url = self.page.url
                logger.info(f"当前页面标题: {page_title}")
                logger.info(f"当前页面URL: {page_url}")

                logger.info(f"正在搜索关键词: {keyword}")

                # 尝试多种搜索框选择器
                search_selectors = [
                    'input[class*="search-input"]',
                    'input[placeholder*="搜索"]',
                    'input[type="text"]',
                    '.search-input',
                    '#search-input'
                ]

                search_input = None
                for selector in search_selectors:
                    try:
                        logger.info(f"尝试查找搜索框，选择器: {selector}")
                        search_input = await self.page.wait_for_selector(selector, timeout=5000)
                        if search_input:
                            logger.info(f"✅ 找到搜索框，使用选择器: {selector}")
                            break
                    except Exception as e:
                        logger.info(f"❌ 选择器 {selector} 未找到搜索框: {str(e)}")
                        continue

                if not search_input:
                    raise Exception("未找到搜索框元素")

                # 检查页面状态
                if self.page.is_closed():
                    raise Exception("页面在查找搜索框后被关闭")

                await search_input.fill(keyword)
                logger.info(f"✅ 搜索关键词 '{keyword}' 已填入搜索框")

                # 注册响应监听
                self.page.on("response", on_response)

                logger.info("🖱️ 准备点击搜索按钮...")
                await self.page.click('button[type="submit"]')
                logger.info("✅ 搜索按钮已点击")
                    
                await self.page.wait_for_load_state("networkidle", timeout=15000)

                # 等待第一页API响应（优化等待时间）
                logger.info("等待第一页API响应...")
                await asyncio.sleep(3)

                # 尝试处理弹窗
                try:
                    await self.page.keyboard.press('Escape')
                    await asyncio.sleep(0.5)
                except:
                    pass
                # 【核心】检测并处理滑块验证 → 使用公共方法
                logger.info(f"检测是否有滑块验证...")
                slider_result = await self.handle_slider_verification(
                    page=self.page,
                    context=self.context,
                    browser=self.browser,
                    playwright=getattr(self, 'playwright', None),
                    max_retries=5
                )
                
                if not slider_result:
                    logger.error(f"❌ 滑块验证失败，搜索终止")
                    return {
                        'items': [],
                        'total': 0,
                        'error': '滑块验证失败'
                    }
                # 等待更多数据
                await asyncio.sleep(3)

                first_page_count = len(all_data_list)
                logger.info(f"第1页完成，获取到 {first_page_count} 条数据")

                # 如果需要获取更多页数据
                if total_pages > 1:
                    for page_num in range(2, total_pages + 1):
                        logger.info(f"正在获取第 {page_num} 页数据...")

                        # 等待页面稳定
                        await asyncio.sleep(2)

                        # 查找并点击下一页按钮
                        next_button_found = False
                        next_button_selectors = [
                            '.search-page-tiny-arrow-right--oXVFaRao',
                            '[class*="search-page-tiny-arrow-right"]',
                            'button[aria-label="下一页"]',
                            'button:has-text("下一页")',
                            'a:has-text("下一页")',
                            '.ant-pagination-next',
                            'li.ant-pagination-next a',
                            'a[aria-label="下一页"]'
                        ]

                        for selector in next_button_selectors:
                            try:
                                next_button = self.page.locator(selector).first

                                if await next_button.is_visible(timeout=3000):
                                    # 检查按钮是否可点击
                                    is_disabled = await next_button.get_attribute("disabled")
                                    has_disabled_class = await next_button.evaluate("el => el.classList.contains('ant-pagination-disabled') || el.classList.contains('disabled')")

                                    if not is_disabled and not has_disabled_class:
                                        logger.info(f"找到下一页按钮，正在点击到第 {page_num} 页...")

                                        # 记录点击前的数据量
                                        before_click_count = len(all_data_list)

                                        # 滚动到按钮位置并点击
                                        await next_button.scroll_into_view_if_needed()
                                        await asyncio.sleep(1)
                                        await next_button.click()
                                        await self.page.wait_for_load_state("networkidle", timeout=15000)

                                        # 等待新数据加载
                                        await asyncio.sleep(5)

                                        # 检查是否有新数据
                                        after_click_count = len(all_data_list)
                                        new_items = after_click_count - before_click_count

                                        if new_items > 0:
                                            logger.info(f"第 {page_num} 页成功，新增 {new_items} 条数据")
                                            next_button_found = True
                                            break
                                        else:
                                            logger.warning(f"第 {page_num} 页点击后没有新数据，可能已到最后一页")
                                            next_button_found = False
                                            break

                            except Exception as e:
                                continue

                        if not next_button_found:
                            logger.warning(f"无法获取第 {page_num} 页数据，停止在第 {page_num-1} 页")
                            break

                # 根据"人想要"数量进行倒序排列
                all_data_list.sort(key=lambda x: x.get('want_count', 0), reverse=True)

                total_count = len(all_data_list)
                logger.info(f"多页搜索完成，总共获取到 {total_count} 条真实数据，已按想要人数排序")

                return {
                    'items': all_data_list,
                    'total': total_count,
                    'is_real_data': True,
                    'source': 'playwright'
                }

            finally:
                # 确保浏览器被正确关闭
                if browser_initialized:
                    try:
                        await self.close_browser()
                        logger.info("浏览器已安全关闭")
                    except Exception as close_error:
                        logger.warning(f"关闭浏览器时出错: {str(close_error)}")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Playwright 多页搜索失败: {error_msg}")

            # 检查是否是浏览器相关问题
            if "Executable doesn't exist" in error_msg or "playwright install" in error_msg:
                error_msg = "浏览器未安装。请在Docker容器中运行: playwright install chromium"
            elif "BrowserType.launch" in error_msg:
                error_msg = "浏览器启动失败。请确保Docker容器有足够的权限和资源"
            elif "Target page, context or browser has been closed" in error_msg:
                error_msg = "浏览器页面被意外关闭。这可能是由于网站反爬虫检测或系统资源限制导致的"
            elif "Page.goto" in error_msg and "closed" in error_msg:
                error_msg = "页面导航失败，浏览器连接已断开"
            elif "Timeout" in error_msg and "exceeded" in error_msg:
                error_msg = "页面加载超时。网络连接可能不稳定或网站响应缓慢"

            # 如果 Playwright 失败，返回错误信息
            return {
                'items': [],
                'total': 0,
                'error': f'多页搜索失败: {error_msg}'
            }

    async def _get_multiple_fallback_data(self, keyword: str, total_pages: int) -> Dict[str, Any]:
        """获取多页备选数据（模拟数据）"""
        logger.info(f"使用多页备选数据: 关键词='{keyword}', 总页数={total_pages}")

        # 模拟搜索延迟
        await asyncio.sleep(1)

        # 生成多页模拟数据
        all_mock_items = []

        for page in range(1, total_pages + 1):
            page_size = 20  # 每页20条
            start_index = (page - 1) * page_size

            for i in range(page_size):
                item_index = start_index + i + 1
                all_mock_items.append({
                    'item_id': f'mock_{keyword}_{item_index}',
                    'title': f'{keyword}相关商品 #{item_index} [模拟数据-第{page}页]',
                    'price': f'{100 + item_index * 10}',
                    'seller_name': f'卖家{item_index}',
                    'item_url': f'https://www.goofish.com/item?id=mock_{keyword}_{item_index}',
                    'publish_time': '2025-07-28',
                    'tags': [f'标签{i+1}', f'分类{i+1}'],
                    'main_image': f'https://via.placeholder.com/200x200?text={keyword}商品{item_index}',
                    'raw_data': {
                        'mock': True,
                        'keyword': keyword,
                        'index': item_index,
                        'page': page
                    }
                })

        total_count = len(all_mock_items)
        logger.info(f"多页备选数据生成完成: 找到{total_count}个商品，共{total_pages}页")

        return {
            'items': all_mock_items,
            'total': total_count,
            'is_fallback': True
        }


# 搜索器工具函数

async def search_xianyu_items(keyword: str, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    """
    搜索闲鱼商品的便捷函数，带重试机制

    Args:
        keyword: 搜索关键词
        page: 页码
        page_size: 每页数量

    Returns:
        搜索结果
    """
    max_retries = 2
    retry_delay = 5  # 秒，增加重试间隔

    for attempt in range(max_retries + 1):
        searcher = None
        try:
            # 每次搜索都创建新的搜索器实例，避免浏览器状态混乱
            searcher = XianyuSearcher()

            logger.info(f"开始单页搜索，尝试次数: {attempt + 1}/{max_retries + 1}")
            result = await searcher.search_items(keyword, page, page_size)

            # 如果成功获取到数据，直接返回
            if result.get('items') or not result.get('error'):
                logger.info(f"单页搜索成功，获取到 {len(result.get('items', []))} 条数据")
                return result

        except Exception as e:
            error_msg = str(e)
            logger.error(f"搜索商品失败 (尝试 {attempt + 1}/{max_retries + 1}): {error_msg}")

            # 如果是最后一次尝试，返回错误
            if attempt == max_retries:
                return {
                    'items': [],
                    'total': 0,
                    'error': f"搜索失败，已重试 {max_retries} 次: {error_msg}"
                }

            # 等待后重试
            logger.info(f"等待 {retry_delay} 秒后重试...")
            await asyncio.sleep(retry_delay)

        finally:
            # 确保搜索器被正确关闭
            if searcher:
                try:
                    await searcher.close_browser()
                except Exception as close_error:
                    logger.warning(f"关闭搜索器时出错: {str(close_error)}")

    # 理论上不会到达这里
    return {
        'items': [],
        'total': 0,
        'error': "未知错误"
    }


async def search_multiple_pages_xianyu(keyword: str, total_pages: int = 1) -> Dict[str, Any]:
    """
    搜索多页闲鱼商品的便捷函数，带重试机制

    Args:
        keyword: 搜索关键词
        total_pages: 总页数

    Returns:
        搜索结果
    """
    max_retries = 0
    retry_delay = 5  # 秒，增加重试间隔

    for attempt in range(max_retries + 1):
        searcher = None
        try:
            # 每次搜索都创建新的搜索器实例，避免浏览器状态混乱
            searcher = XianyuSearcher()

            logger.info(f"开始多页搜索，尝试次数: {attempt + 1}/{max_retries + 1}")
            result = await searcher.search_multiple_pages(keyword, total_pages)

            # 如果成功获取到数据，直接返回
            if result.get('items') or not result.get('error'):
                logger.info(f"多页搜索成功，获取到 {len(result.get('items', []))} 条数据")
                return result

        except Exception as e:
            error_msg = str(e)
            logger.error(f"多页搜索商品失败 (尝试 {attempt + 1}/{max_retries + 1}): {error_msg}")

            # 如果是最后一次尝试，返回错误
            if attempt == max_retries:
                return {
                    'items': [],
                    'total': 0,
                    'error': f"搜索失败，已重试 {max_retries} 次: {error_msg}"
                }

            # 等待后重试
            logger.info(f"等待 {retry_delay} 秒后重试...")
            await asyncio.sleep(retry_delay)

        finally:
            # 确保搜索器被正确关闭
            if searcher:
                try:
                    await searcher.close_browser()
                except Exception as close_error:
                    logger.warning(f"关闭搜索器时出错: {str(close_error)}")

    # 理论上不会到达这里
    return {
        'items': [],
        'total': 0,
        'error': "未知错误"
    }



