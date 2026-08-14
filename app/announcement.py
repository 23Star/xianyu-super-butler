"""全局公告与版本检查。

数据源是用户自己的公网服务器上的一个静态 JSON，管家定时拉取。
之所以由后端代拉而不是前端直接请求：
  1. 避免跨域，也不用在前端硬编码公告地址；
  2. 拉取失败/超时不能影响页面，后端可以兜底返回上一次的结果；
  3. 公告地址属于部署配置，放在系统设置里可改，不必改代码。

远端 JSON 约定格式（字段都可选）::

    {
      "announcements": [
        {"id": "2026-08-13-maintain",
         "title": "系统维护通知",
         "content": "今晚 22:00 起闲鱼接口维护，发货可能延迟。",
         "level": "warning",              // info | warning | danger
         "published_at": "2026-08-13 10:00"}
      ],
      "latest_version": "1.2.0",
      "download_url": "https://example.com/download",
      "release_notes": "修复滑块验证成功率问题"
    }
"""
import asyncio
import time
from typing import Any, Dict, Optional

from loguru import logger

# 公告地址与检查间隔存在系统设置里，键名集中在这里便于前后端对齐
ANNOUNCEMENT_URL_KEY = 'announcement_source_url'
ANNOUNCEMENT_ENABLED_KEY = 'announcement_enabled'
# 拉回来的内容分两块，各自决定展不展示：
# 有人只想收公告不想看到升级提醒，也有人反过来。
ANNOUNCEMENT_SHOW_NOTICE_KEY = 'announcement_show_notice'
ANNOUNCEMENT_SHOW_UPDATE_KEY = 'announcement_show_update'

# 官方公告源。不配置就用它，否则新装的用户在「关于」页只会看到
# 「未配置更新源」，发布方也就没有任何办法把公告和新版本推送出去。
# 想换成自建地址、或者不想连官方源，在系统设置里改掉或关掉开关即可。
DEFAULT_ANNOUNCEMENT_URL = 'https://connect.corleom.com/announcement.json'

# 远端不可用时沿用上一次成功的结果，避免公告栏忽隐忽现
_cache: Dict[str, Any] = {
    'data': None,
    'fetched_at': 0.0,
    'error': '',
}

# 拉取间隔：公告变动不频繁，10 分钟足够，避免给用户服务器造成无谓压力
CACHE_TTL = 600
FETCH_TIMEOUT = 8


# 本软件版本号。发布新版时改这里，并同步更新公网服务器上 JSON 的 latest_version。
# 注意不要复用 global_config.yml 里的 APP_CONFIG.app_version —— 那是伪装成闲鱼
# 客户端时上报给平台的协议版本，与本软件版本无关。
APP_VERSION = '3.0.0-beta'


def get_local_version() -> str:
    """当前运行的软件版本号。"""
    return APP_VERSION


def _normalize(payload: Any) -> Dict[str, Any]:
    """把远端返回整理成前端可直接使用的结构，容忍字段缺失或类型不对。"""
    if not isinstance(payload, dict):
        return {'announcements': [], 'latest_version': '', 'download_url': '', 'release_notes': ''}

    raw_list = payload.get('announcements')
    announcements = []
    if isinstance(raw_list, list):
        for index, item in enumerate(raw_list):
            if not isinstance(item, dict):
                continue
            content = str(item.get('content') or '').strip()
            if not content:
                continue
            level = str(item.get('level') or 'info').strip().lower()
            announcements.append({
                # 没给 id 时用内容哈希兜底，前端要靠它记录“已读”
                'id': str(item.get('id') or f'auto-{index}-{abs(hash(content)) % 10**8}'),
                'title': str(item.get('title') or '').strip(),
                'content': content,
                'level': level if level in ('info', 'warning', 'danger') else 'info',
                'published_at': str(item.get('published_at') or '').strip(),
            })

    return {
        'announcements': announcements,
        'latest_version': str(payload.get('latest_version') or '').strip(),
        'download_url': str(payload.get('download_url') or '').strip(),
        'release_notes': str(payload.get('release_notes') or '').strip(),
    }


def _version_tuple(value: str):
    """把 '1.2.10' 变成 (1, 2, 10) 以便正确比较。

    字符串比较会把 '1.10' 判成小于 '1.2'，这里按数字段逐位比。
    """
    parts = []
    for chunk in str(value or '').strip().lstrip('vV').split('.'):
        digits = ''.join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def has_update(local: str, remote: str) -> bool:
    """远端版本高于本地才算有更新；任一为空则认为没有。"""
    if not remote or not local:
        return False
    a, b = _version_tuple(local), _version_tuple(remote)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return b > a


async def fetch_remote(url: str) -> Optional[Dict[str, Any]]:
    """拉取远端公告 JSON，失败返回 None 并记录原因。"""
    import aiohttp

    try:
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    _cache['error'] = f'远端返回 HTTP {resp.status}'
                    return None
                # 用户服务器可能没配 application/json，这里不校验 content-type
                payload = await resp.json(content_type=None)
        _cache['error'] = ''
        return _normalize(payload)
    except asyncio.TimeoutError:
        _cache['error'] = f'拉取超时（{FETCH_TIMEOUT}s）'
    except Exception as exc:
        _cache['error'] = f'拉取失败: {exc}'
    return None


async def get_announcement_payload(force: bool = False) -> Dict[str, Any]:
    """返回公告与版本信息，带缓存。force=True 时忽略缓存立即拉取。"""
    from app.db_manager import db_manager

    local_version = get_local_version()
    base = {
        'local_version': local_version,
        'announcements': [],
        'latest_version': '',
        'download_url': '',
        'release_notes': '',
        'has_update': False,
        'source_configured': False,
        'error': '',
    }

    enabled = str(db_manager.get_system_setting(ANNOUNCEMENT_ENABLED_KEY) or '').strip().lower()
    if enabled in ('0', 'false', 'no'):
        return base

    url = str(db_manager.get_system_setting(ANNOUNCEMENT_URL_KEY) or '').strip()
    if not url:
        # 没填就用官方源。用户想换自建地址可以在设置里改，
        # 完全不想连外网则关掉「启用公告与更新检查」。
        url = DEFAULT_ANNOUNCEMENT_URL

    base['source_configured'] = True

    fresh = (time.time() - _cache['fetched_at']) < CACHE_TTL
    if not force and fresh and _cache['data'] is not None:
        data = _cache['data']
    else:
        data = await fetch_remote(url)
        if data is not None:
            _cache['data'] = data
            _cache['fetched_at'] = time.time()
        elif _cache['data'] is not None:
            # 拉取失败时退回上次结果，页面不至于突然空掉
            data = _cache['data']
            logger.debug(f'公告拉取失败，沿用缓存: {_cache["error"]}')
        else:
            base['error'] = _cache['error']
            return base

    base.update(data)
    base['has_update'] = has_update(local_version, data.get('latest_version', ''))
    base['error'] = _cache['error']

    # 按展示开关裁剪。放在最后统一处理，顶部横幅和「关于」页读的是同一份数据，
    # 关掉哪一块两处就一起消失，不用各自判断。
    def _shown(key: str) -> bool:
        raw = str(db_manager.get_system_setting(key) or '').strip().lower()
        # 没设置过按展示处理，避免升级后公告突然消失
        return raw not in ('0', 'false', 'no')

    if not _shown(ANNOUNCEMENT_SHOW_NOTICE_KEY):
        base['announcements'] = []
    if not _shown(ANNOUNCEMENT_SHOW_UPDATE_KEY):
        base['has_update'] = False

    return base
