import asyncio
from websockets.legacy.client import WebSocketClientProtocol, connect
from typing import Optional, Dict, Any, Callable
from loguru import logger

class WebSocketClient:
    def __init__(self, url: str, headers: Dict[str, str], on_message: Callable[[Dict[str, Any]], None]):
        """初始化WebSocket客户端"""
        self.url = url
        self.headers = headers
        self.on_message = on_message
        self.websocket: Optional[WebSocketClientProtocol] = None
        self.is_connected = False
        self.reconnect_delay = 5  # 重连延迟，单位秒
        
    async def connect(self):
        """建立WebSocket连接"""
        try:
            self.websocket = await connect(
                self.url,
                extra_headers=self.headers,
                ping_interval=None,
                ping_timeout=None
            )
            self.is_connected = True
            logger.info("WebSocket连接建立成功")
            return True
        except Exception as e:
            logger.error(f"WebSocket连接失败: {e}")
            return False
            
    async def disconnect(self):
        """关闭WebSocket连接"""
        if self.websocket:
            await self.websocket.close()
            self.is_connected = False
            logger.info("WebSocket连接已关闭")
            
    async def send(self, message: str):
        """发送消息"""
        if not self.is_connected:
            logger.warning("WebSocket未连接，无法发送消息")
            return False
            
        try:
            await self.websocket.send(message)
            return True
        except Exception as e:
            logger.error(f"消息发送失败: {e}")
            self.is_connected = False
            return False
            
    async def receive(self):
        """接收消息"""
        if not self.is_connected:
            logger.warning("WebSocket未连接，无法接收消息")
            return None
            
        try:
            message = await self.websocket.recv()
            return message
        except Exception as e:
            logger.error(f"消息接收失败: {e}")
            self.is_connected = False
            return None
            
    async def reconnect(self):
        """重新连接"""
        logger.info(f"准备在{self.reconnect_delay}秒后重新连接...")
        await asyncio.sleep(self.reconnect_delay)
        return await self.connect()
        
    async def run(self):
        """运行WebSocket客户端"""
        while True:
            if not self.is_connected:
                success = await self.connect()
                if not success:
                    await self.reconnect()
                    continue
                    
            try:
                message = await self.receive()
                if message:
                    await self.on_message(message)
            except Exception as e:
                logger.error(f"消息处理失败: {e}")
                await self.disconnect()
                await self.reconnect()
