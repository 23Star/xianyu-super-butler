#!/usr/bin/env python3
"""
闲鱼扫码登录工具
基于API接口实现二维码生成和Cookie获取（参照myfish-main项目）
"""

import asyncio
import time
import uuid
import json
import re
from random import random
from typing import Optional, Dict, Any
import httpx
import qrcode
import qrcode.constants
from loguru import logger
import hashlib


def generate_headers():
    """生成请求头"""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'Referer': 'https://passport.goofish.com/',
        'Origin': 'https://passport.goofish.com',
    }


class GetLoginParamsError(Exception):
    """获取登录参数错误"""


class GetLoginQRCodeError(Exception):
    """获取登录二维码失败"""


class NotLoginError(Exception):
    """未登录错误"""


class QRLoginSession:
    """二维码登录会话"""

    # 人脸验证需要用户掏手机、扫码、刷脸，二维码原本的 5 分钟往往不够
    VERIFICATION_EXTRA_SECONDS = 300

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.status = 'waiting'  # waiting, scanned, success, expired, cancelled, verification_required
        self.qr_code_url = None
        self.qr_content = None
        self.cookies = {}
        self.unb = None
        self.created_time = time.time()
        self.expire_time = 300  # 5分钟过期
        self.params = {}  # 存储登录参数
        self.verification_url = None  # 风控验证URL
        self.verification_qr_code_url = None  # 验证URL的二维码，生成一次后复用
        self.verification_extended = False
        self.last_remote_status = None

    def extend_for_verification(self) -> None:
        """进入手机验证后延长会话寿命，只延一次。"""
        if self.verification_extended:
            return
        self.verification_extended = True
        self.expire_time += self.VERIFICATION_EXTRA_SECONDS

    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() - self.created_time > self.expire_time

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'status': self.status,
            'qr_code_url': self.qr_code_url,
            'created_time': self.created_time,
            'is_expired': self.is_expired()
        }


class QRLoginManager:
    """二维码登录管理器"""

    def __init__(self):
        self.sessions: Dict[str, QRLoginSession] = {}
        self.headers = generate_headers()
        self.host = "https://passport.goofish.com"
        self.api_mini_login = f"{self.host}/mini_login.htm"
        self.api_generate_qr = f"{self.host}/newlogin/qrcode/generate.do"
        self.api_scan_status = f"{self.host}/newlogin/qrcode/query.do"
        self.api_h5_tk = "https://h5api.m.goofish.com/h5/mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get/1.0/"
        
        # 配置代理（如果需要的话，取消注释并修改代理地址）
        # self.proxy = "http://127.0.0.1:7890"
        self.proxy = None
        
        # 配置超时时间
        self.timeout = httpx.Timeout(connect=30.0, read=60.0, write=30.0, pool=60.0)

    def _cookie_marshal(self, cookies: dict) -> str:
        """将Cookie字典转换为字符串"""
        return "; ".join([f"{k}={v}" for k, v in cookies.items()])

    async def _get_mh5tk(self, session: QRLoginSession) -> dict:
        """获取m_h5_tk和m_h5_tk_enc"""
        data = {"bizScene": "home"}
        data_str = json.dumps(data, separators=(',', ':'))
        t = str(int(time.time() * 1000))
        app_key = "34839810"

        # 先发一次 GET 请求，获取 cookie 中的 m_h5_tk
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, proxy=self.proxy) as client:
            try:
                resp = await client.get(self.api_h5_tk, headers=self.headers)
                cookies = {k: v for k, v in resp.cookies.items()}
                session.cookies.update(cookies)

                m_h5_tk = cookies.get("m_h5_tk", "")
                token = m_h5_tk.split("_")[0] if "_" in m_h5_tk else ""

                # 生成签名
                sign_input = f"{token}&{t}&{app_key}&{data_str}"
                sign = hashlib.md5(sign_input.encode()).hexdigest()

                # 构造最终请求参数
                params = {
                    "jsv": "2.7.2",
                    "appKey": app_key,
                    "t": t,
                    "sign": sign,
                    "v": "1.0",
                    "type": "originaljson",
                    "dataType": "json",
                    "timeout": 20000,
                    "api": "mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get",
                    "data": data_str,
                }

                # 发请求正式获取数据，确保 token 有效
                await client.post(self.api_h5_tk, params=params, headers=self.headers, cookies=session.cookies)

                return cookies
            except httpx.ConnectTimeout:
                logger.error("获取m_h5_tk时连接超时")
                raise
            except httpx.ReadTimeout:
                logger.error("获取m_h5_tk时读取超时")
                raise
            except httpx.ConnectError:
                logger.error("获取m_h5_tk时连接错误")
                raise

    async def _get_login_params(self, session: QRLoginSession) -> dict:
        """获取二维码登录时需要的表单参数"""
        params = {
            "lang": "zh_cn",
            "appName": "xianyu",
            "appEntrance": "web",
            "styleType": "vertical",
            "bizParams": "",
            "notLoadSsoView": False,
            "notKeepLogin": False,
            "isMobile": False,
            "qrCodeFirst": False,
            "stie": 77,
            "rnd": random(),
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout, proxy=self.proxy) as client:
            try:
                resp = await client.get(
                    self.api_mini_login,
                    params=params,
                    cookies=session.cookies,
                    headers=self.headers,
                )

                # 正则匹配需要的json数据
                pattern = r"window\.viewData\s*=\s*(\{.*?\});"
                match = re.search(pattern, resp.text)
                if match:
                    json_string = match.group(1)
                    view_data = json.loads(json_string)
                    data = view_data.get("loginFormData")
                    if data:
                        data["umidTag"] = "SERVER"
                        session.params.update(data)
                        return data
                    else:
                        raise GetLoginParamsError("未找到loginFormData")
                else:
                    raise GetLoginParamsError("获取登录参数失败")
            except httpx.ConnectTimeout:
                logger.error("获取登录参数时连接超时")
                raise
            except httpx.ReadTimeout:
                logger.error("获取登录参数时读取超时")
                raise
            except httpx.ConnectError:
                logger.error("获取登录参数时连接错误")
                raise
    
    async def generate_qr_code(self) -> Dict[str, Any]:
        """生成二维码"""
        try:
            # 创建新的会话
            session_id = str(uuid.uuid4())
            session = QRLoginSession(session_id)

            # 1. 获取m_h5_tk
            await self._get_mh5tk(session)
            logger.info(f"获取m_h5_tk成功: {session_id}")

            # 2. 获取登录参数
            login_params = await self._get_login_params(session)
            logger.info(f"获取登录参数成功: {session_id}")

            # 3. 生成二维码
            async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout, proxy=self.proxy) as client:
                resp = await client.get(
                    self.api_generate_qr,
                    params=login_params,
                    headers=self.headers
                )
                logger.debug(f"[调试] 获取二维码接口原始响应: {resp.text}")

                try:
                    results = resp.json()
                    logger.debug(f"[调试] 获取二维码接口解析后: {json.dumps(results, ensure_ascii=False)}")
                except Exception as e:
                    logger.exception("二维码接口返回不是JSON")
                    raise GetLoginQRCodeError(f"二维码接口返回异常: {resp.text}")

                if results.get("content", {}).get("success") == True:
                    # 更新会话参数
                    session.params.update({
                        "t": results["content"]["data"]["t"],
                        "ck": results["content"]["data"]["ck"],
                    })

                    # 获取二维码内容
                    qr_content = results["content"]["data"]["codeContent"]
                    session.qr_content = qr_content

                    # 生成二维码图片（base64格式）
                    qr = qrcode.QRCode(
                        version=5,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=10,
                        border=2,
                    )
                    qr.add_data(qr_content)
                    qr.make()

                    # 将二维码转换为base64
                    from io import BytesIO
                    import base64

                    qr_img = qr.make_image()
                    buffer = BytesIO()
                    qr_img.save(buffer, format='PNG')
                    qr_base64 = base64.b64encode(buffer.getvalue()).decode()
                    qr_data_url = f"data:image/png;base64,{qr_base64}"

                    session.qr_code_url = qr_data_url
                    session.status = 'waiting'

                    # 保存会话
                    self.sessions[session_id] = session

                    # 启动状态检查任务
                    asyncio.create_task(self._monitor_qr_status(session_id))

                    logger.info(f"二维码生成成功: {session_id}")
                    return {
                        'success': True,
                        'session_id': session_id,
                        'qr_code_url': qr_data_url
                    }
                else:
                    raise GetLoginQRCodeError("获取登录二维码失败")

        except httpx.ConnectTimeout as e:
            logger.error(f"连接超时: {e}")
            return {'success': False, 'message': f'连接超时，请检查网络或尝试使用代理'}
        except httpx.ReadTimeout as e:
            logger.error(f"读取超时: {e}")
            return {'success': False, 'message': f'读取超时，服务器响应过慢'}
        except httpx.ConnectError as e:
            logger.error(f"连接错误: {e}")
            return {'success': False, 'message': f'连接错误，请检查网络或代理设置'}
        except Exception as e:
            logger.exception("二维码生成过程中发生异常")
            return {'success': False, 'message': f'生成二维码失败: {str(e)}'}
    
    async def _poll_qrcode_status(self, session: QRLoginSession) -> httpx.Response:
        """获取二维码扫描状态"""
        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout, proxy=self.proxy) as client:
            resp = await client.post(
                self.api_scan_status,
                data=session.params,
                cookies=session.cookies,
                headers=self.headers,
            )
            return resp

    async def _monitor_qr_status(self, session_id: str):
        """监控二维码状态"""
        try:
            session = self.sessions.get(session_id)
            if not session:
                return

            logger.info(f"开始监控二维码状态: {session_id}")

            # 监控时长跟随会话有效期 —— 进入人脸验证后 expire_time 会被延长，
            # 两处必须一致，否则监控先退出、会话还活着，状态就永远不再推进。
            start_time = time.time()

            while time.time() - start_time < session.expire_time:
                try:
                    # 检查会话是否还存在
                    if session_id not in self.sessions:
                        break

                    # 轮询二维码状态
                    resp = await self._poll_qrcode_status(session)
                    qrcode_status = (
                        resp.json()
                        .get("content", {})
                        .get("data", {})
                        .get("qrCodeStatus")
                    )
                    if qrcode_status != session.last_remote_status:
                        logger.info(
                            f"二维码远端状态变化: {session_id}, "
                            f"{session.last_remote_status or 'INIT'} -> {qrcode_status or 'EMPTY'}, "
                            f"响应Cookie字段: {sorted(resp.cookies.keys())}"
                        )
                        session.last_remote_status = qrcode_status

                    if qrcode_status == "CONFIRMED":
                        data = (
                            resp.json()
                            .get("content", {})
                            .get("data", {})
                        )

                        # 先收 Cookie —— 人脸/短信验证走完的那一轮响应里就带着登录态
                        for k, v in resp.cookies.items():
                            session.cookies[k] = v
                            if k == 'unb':
                                session.unb = v

                        if data.get("iframeRedirect") is True and not session.unb:
                            # 账号被风控，需要手机验证。
                            #
                            # 这里绝不能 break：用户在手机上完成人脸验证后，只有
                            # 继续轮询 query.do 才会拿到带登录态的 CONFIRMED。
                            # 原实现一进验证态就结束监控协程，于是用户验证走完，
                            # 页面永远停在「请完成验证」—— 这就是「验证做完不跳回」。
                            iframe_url = data.get("iframeRedirectUrl")
                            if session.status != 'verification_required':
                                session.status = 'verification_required'
                                session.verification_url = iframe_url
                                # 人脸验证要用户掏手机、扫码、刷脸，原本的 5 分钟
                                # 从二维码生成起算，往往不够用
                                session.extend_for_verification()
                                logger.warning(
                                    f"账号被风控，需要手机验证: {session_id}, URL: {iframe_url}"
                                )
                            elif iframe_url and iframe_url != session.verification_url:
                                # 验证链路中途换 URL，跟上以免二维码失效
                                session.verification_url = iframe_url
                                session.verification_qr_code_url = None
                            await asyncio.sleep(1.5)
                            continue

                        # 登录成功
                        session.status = 'success'
                        cookie_names = sorted(session.cookies.keys())
                        logger.info(
                            f"扫码确认成功: {session_id}, UNB: {session.unb or '缺失'}, "
                            f"Cookie字段数: {len(cookie_names)}, 字段: {cookie_names}"
                        )
                        if not session.unb:
                            logger.error(
                                f"扫码确认响应未包含unb，无法创建账号: {session_id}"
                            )
                        break

                    elif qrcode_status == "NEW":
                        # 二维码未被扫描，继续轮询。
                        # 这里必须自己 sleep：原实现直接 continue 跳过了循环底部的
                        # 节流，未扫码期间会对 passport 接口无间隔空转轮询，既吃 CPU
                        # 又容易把 IP 送进风控。
                        await asyncio.sleep(0.8)
                        continue

                    elif qrcode_status == "EXPIRED":
                        # 二维码已过期
                        session.status = 'expired'
                        logger.info(f"二维码已过期: {session_id}")
                        break

                    elif qrcode_status == "SCANED":
                        # 二维码已被扫描，等待确认
                        if session.status == 'waiting':
                            session.status = 'scanned'
                            logger.info(f"二维码已扫描，等待确认: {session_id}")
                    elif session.status == 'verification_required':
                        # 验证期间远端可能短暂返回空状态，此时不能当成"用户取消"
                        # 把会话打死 —— 用户正在手机上刷脸，等下一轮即可。
                        logger.debug(
                            f"验证期间收到非预期状态，继续等待: {session_id}, "
                            f"status={qrcode_status or 'EMPTY'}"
                        )
                    else:
                        # 用户取消确认
                        session.status = 'cancelled'
                        logger.info(f"用户取消登录: {session_id}")
                        break

                    await asyncio.sleep(0.8)  # 每0.8秒检查一次

                except Exception as e:
                    logger.error(f"监控二维码状态异常: {e}")
                    await asyncio.sleep(2)

            # 超时处理。验证态超时同样要收口，否则前端会一直等一个不会再变的状态。
            if session.status == 'verification_required':
                session.status = 'expired'
                logger.info(f"手机验证超时未完成，标记为过期: {session_id}")
            elif session.status not in ['success', 'expired', 'cancelled']:
                session.status = 'expired'
                logger.info(f"二维码监控超时，标记为过期: {session_id}")

        except Exception as e:
            logger.error(f"监控二维码状态失败: {e}")
            if session_id in self.sessions:
                self.sessions[session_id].status = 'expired'
        finally:
            # 监控结束后自清。原先只有 check 接口会调 cleanup_expired_sessions()，
            # 用户扫完码直接关掉弹窗就没人再触发，会话连同整份登录 Cookie 会一直
            # 留在内存里。留一段窗口期让前端取走最终状态，再删。
            asyncio.create_task(self._discard_session_later(session_id))

    async def _discard_session_later(self, session_id: str, delay: float = 60.0) -> None:
        """延迟丢弃会话，给前端留出读取最终状态的时间。"""
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self.sessions.pop(session_id, None) is not None:
            logger.debug(f"扫码会话已释放: {session_id}")
    
    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """获取会话状态"""
        session = self.sessions.get(session_id)
        if not session:
            return {'status': 'not_found'}

        if session.is_expired() and session.status != 'success':
            session.status = 'expired'

        result = {
            'status': session.status,
            'session_id': session_id
        }
        logger.debug(
            f"获取扫码会话状态: session={session_id}, status={session.status}, "
            f"cookie_count={len(session.cookies)}, has_unb={bool(session.unb)}"
        )
        # 如果需要验证，返回验证URL和对应二维码
        if session.status == 'verification_required' and session.verification_url:
            result['verification_url'] = session.verification_url
            result['verification_qr_code_url'] = self._verification_qr_code(session)
            result['message'] = '账号被风控，请用手机完成验证，本页会自动继续'

        # 如果登录成功，返回Cookie信息
        if session.status == 'success' and session.cookies and session.unb:
            result['cookies'] = self._cookie_marshal(session.cookies)
            result['unb'] = session.unb

        return result

    def _verification_qr_code(self, session: QRLoginSession) -> Optional[str]:
        """把验证 URL 画成二维码供手机扫描，按会话缓存。

        前端每秒都在轮询状态，每次重画一张 PNG 纯属浪费；URL 不变时直接复用。
        """
        if session.verification_qr_code_url:
            return session.verification_qr_code_url
        if not session.verification_url:
            return None

        try:
            from io import BytesIO
            import base64

            buffer = BytesIO()
            qrcode.make(session.verification_url).save(buffer, format='PNG')
            session.verification_qr_code_url = (
                'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')
            )
            return session.verification_qr_code_url
        except Exception as e:
            logger.warning(f"生成验证二维码失败: {session.session_id}, {e}")
            return None

    def cleanup_expired_sessions(self):
        """清理过期会话"""
        expired_sessions = []
        for session_id, session in self.sessions.items():
            if session.is_expired():
                expired_sessions.append(session_id)

        for session_id in expired_sessions:
            del self.sessions[session_id]
            logger.info(f"清理过期会话: {session_id}")

    def get_session_cookies(self, session_id: str) -> Optional[Dict[str, str]]:
        """获取会话Cookie"""
        session = self.sessions.get(session_id)
        if session and session.status == 'success':
            return {
                'cookies': self._cookie_marshal(session.cookies),
                'unb': session.unb
            }
        return None

# 全局二维码登录管理器实例
qr_login_manager = QRLoginManager()
