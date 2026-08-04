import os
import yaml
from pathlib import Path
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class Config:
    """配置管理类
    
    用于加载和管理全局配置文件(global_config.yml)。
    支持配置的读取、修改和保存。
    """
    
    _instance = None
    _config = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """加载配置文件
        
        从global_config.yml文件中加载配置信息。
        如果文件不存在则抛出FileNotFoundError异常。
        """
        config_path = PROJECT_ROOT / 'global_config.yml'
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项
        
        Args:
            key: 配置项的键，支持点号分隔的多级键
            default: 当配置项不存在时返回的默认值
            
        Returns:
            配置项的值或默认值
        """
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """设置配置项
        
        Args:
            key: 配置项的键，支持点号分隔的多级键
            value: 要设置的值
        """
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    def save(self) -> None:
        """保存配置到文件
        
        将当前配置保存回global_config.yml文件
        """
        config_path = PROJECT_ROOT / 'global_config.yml'
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(self._config, f, allow_unicode=True, default_flow_style=False)

    @property
    def config(self) -> Dict[str, Any]:
        """获取完整配置
        
        Returns:
            包含所有配置项的字典
        """
        return self._config

# 创建全局配置实例
config = Config()

# 导出常用配置项
COOKIES_STR = config.get('COOKIES.value', '')
COOKIES_LAST_UPDATE = config.get('COOKIES.last_update_time', '')
WEBSOCKET_URL = config.get('WEBSOCKET_URL', 'wss://wss-goofish.dingtalk.com/')
HEARTBEAT_INTERVAL = config.get('HEARTBEAT_INTERVAL', 15)
HEARTBEAT_TIMEOUT = config.get('HEARTBEAT_TIMEOUT', 30)
TOKEN_REFRESH_INTERVAL = config.get('TOKEN_REFRESH_INTERVAL', 72000)
TOKEN_RETRY_INTERVAL = config.get('TOKEN_RETRY_INTERVAL', 7200)
MESSAGE_EXPIRE_TIME = config.get('MESSAGE_EXPIRE_TIME', 300000)
SLIDER_VERIFICATION = config.get('SLIDER_VERIFICATION', {
    'max_concurrent': 3,
    'wait_timeout': 60
})
API_ENDPOINTS = config.get('API_ENDPOINTS', {})
DEFAULT_HEADERS = config.get('DEFAULT_HEADERS', {})
WEBSOCKET_HEADERS = config.get('WEBSOCKET_HEADERS', {})
APP_CONFIG = config.get('APP_CONFIG', {})
AUTO_REPLY = config.get('AUTO_REPLY', {
    'enabled': True,
    'default_message': '亲爱的"{send_user_name}" 老板你好！所有宝贝都可以拍，秒发货的哈~不满意的话可以直接申请退款哈~',
    'api': {
        'enabled': False,
        'url': 'http://localhost:8080/xianyu/reply',
        'timeout': 10
    }
})
MANUAL_MODE = config.get('MANUAL_MODE', {})
LOG_CONFIG = config.get('LOG_CONFIG', {}) 
_cookies_raw = config.get('COOKIES', [])
if isinstance(_cookies_raw, list):
    COOKIES_LIST = _cookies_raw
else:
    # 兼容旧格式，仅有 value 字段
    val = _cookies_raw.get('value') if isinstance(_cookies_raw, dict) else None
    COOKIES_LIST = [{'id': 'default', 'value': val}] if val else []
