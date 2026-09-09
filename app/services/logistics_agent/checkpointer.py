"""LangGraph checkpointer 构建：SQLite 本地默认，Postgres 生产可选。

数据库连接不写死在节点里：SQLite 复用 `db_manager` 的库文件路径（与项目
其他数据同一个 SQLite 文件），Postgres 通过环境变量注入 DSN。进程内按后
端标识缓存同一个 checkpointer，正式消息入口与第五步测试入口共用。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any

from loguru import logger
from langgraph.checkpoint.base import BaseCheckpointSaver

_BACKEND_SQLITE = "sqlite"
_BACKEND_POSTGRES = "postgres"

# checkpointer 配置入口（生产部署切 Postgres 时设置）：
#   LOGISTICS_AGENT_CHECKPOINT_BACKEND=postgres
#   LOGISTICS_AGENT_CHECKPOINT_DSN=postgresql://user:pass@host:5432/db
_BACKEND_ENV = "LOGISTICS_AGENT_CHECKPOINT_BACKEND"
_DSN_ENV = "LOGISTICS_AGENT_CHECKPOINT_DSN"

_cache_lock = threading.Lock()
_cache: dict[str, BaseCheckpointSaver] = {}


def get_checkpointer(db_manager: Any) -> BaseCheckpointSaver:
    """返回进程级共享的 checkpointer（按后端 + 数据库标识缓存）。"""
    key = _cache_key(db_manager)
    with _cache_lock:
        saver = _cache.get(key)
        if saver is None:
            saver = _build(db_manager)
            _cache[key] = saver
            logger.info(f"物流 Agent checkpointer 已初始化：{key.split(':', 1)[0]}")
        return saver


def _cache_key(db_manager: Any) -> str:
    backend = os.getenv(_BACKEND_ENV, _BACKEND_SQLITE).strip().lower() or _BACKEND_SQLITE
    if backend == _BACKEND_POSTGRES:
        return f"{_BACKEND_POSTGRES}:{os.getenv(_DSN_ENV, '').strip()}"
    return f"{_BACKEND_SQLITE}:{os.path.abspath(str(getattr(db_manager, 'db_path', '')))}"


def _build(db_manager: Any) -> BaseCheckpointSaver:
    backend = os.getenv(_BACKEND_ENV, _BACKEND_SQLITE).strip().lower() or _BACKEND_SQLITE
    if backend == _BACKEND_POSTGRES:
        return _build_postgres()
    return _build_sqlite(db_manager)


def _build_sqlite(db_manager: Any) -> BaseCheckpointSaver:
    from langgraph.checkpoint.sqlite import SqliteSaver

    db_path = getattr(db_manager, "db_path", "")
    if not db_path:
        raise RuntimeError("物流 Agent 需要 SQLite 数据库路径（db_manager.db_path）才能持久化会话")
    # 独立连接：db_manager 持有业务连接并自带锁，checkpointer 用自己的连接
    # 加 busy 超时避免偶发写冲突；两者操作同一个库文件。
    connection = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    saver = SqliteSaver(connection, serde=_build_serde())
    saver.setup()
    return saver


def _build_serde() -> Any:
    """图状态序列化白名单：只允许本项目业务类型随 checkpoint 反序列化。"""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    from app.services.logistics_agent.models import ExtractedQuote, SessionState
    from app.services.logistics_agent.routes import RouteResolution

    return JsonPlusSerializer(allowed_msgpack_modules=(SessionState, ExtractedQuote, RouteResolution))


def _build_postgres() -> BaseCheckpointSaver:
    dsn = os.getenv(_DSN_ENV, "").strip()
    if not dsn:
        raise RuntimeError(f"使用 Postgres checkpointer 需要设置 {_DSN_ENV}")
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError as exc:  # pragma: no cover - 可选依赖
        raise RuntimeError(
            "使用 Postgres checkpointer 需要安装 langgraph-checkpoint-postgres"
        ) from exc
    # 进程生命周期内保持连接池打开；表结构在首次使用时创建。
    saver = PostgresSaver.from_conn_string(dsn).__enter__()
    saver.setup()
    return saver
