"""DeepSeek / LangChain 模型适配器。

复用账号 AI 回复设置里的 base_url 与 API Key（与现有 OpenAI 兼容客户端
同一套凭据），LangChain 只负责把相同配置转换为 ChatModel 并提供结构化
输出；模型名使用第五步配置里的预设。
"""

from __future__ import annotations

import time
from typing import Any, TypeVar

from loguru import logger
from pydantic import BaseModel

from app.services.logistics_agent.settings import AgentSettings

_EXTRACT_MAX_TOKENS = 2000
_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 1.0

TModel = TypeVar("TModel", bound=BaseModel)


class ModelNotConfigured(RuntimeError):
    """账号缺少可用的模型凭据，Agent 无法识别消息。"""


class ModelCallError(RuntimeError):
    """模型调用失败（网络、限流、输出不合法等）。"""


def resolve_model_credentials(cookie_id: str) -> dict[str, str]:
    """从 AI 回复设置解析模型凭据；没有可用凭据时抛 ModelNotConfigured。"""
    from app.db_manager import db_manager

    settings = db_manager.get_ai_reply_settings(cookie_id)
    api_key = str(settings.get("api_key") or "").strip()
    base_url = str(settings.get("base_url") or "").strip()
    if not api_key or not base_url:
        raise ModelNotConfigured(f"账号 {cookie_id} 未配置 AI 模型凭据，无法识别物流询价")
    return {"api_key": api_key, "base_url": base_url}


def build_chat_model(settings: AgentSettings, credentials: dict[str, str]):
    """构建 ChatDeepSeek；LangChain 依赖缺失时给出明确错误。"""
    try:
        from langchain_deepseek import ChatDeepSeek
    except ImportError as exc:  # pragma: no cover - 环境缺依赖时直接失败
        raise ModelCallError(
            "服务端缺少 langchain/langchain-deepseek 依赖，请先安装 requirements.txt 中固定版本"
        ) from exc
    if settings.model_name not in ("deepseek-v4-flash", "deepseek-v4-pro"):
        logger.warning(f"未知模型名 {settings.model_name}，回退 deepseek-v4-flash")
    # DeepSeek V4 默认开启思考模式，思考模式下强制 tool_choice 会 400
    # （"Thinking mode does not support this tool_choice"），而结构化抽取
    # 依赖强制工具调用；关闭思考模式后该限制解除，且抽取任务不需要思考链。
    return ChatDeepSeek(
        model=settings.model_name,
        api_key=credentials["api_key"],
        api_base=credentials["base_url"],
        temperature=0,
        timeout=60,
        max_retries=1,
        max_tokens=_EXTRACT_MAX_TOKENS,
        extra_body={"thinking": {"type": "disabled"}},
    )


def extract_structured(model: Any, system_prompt: str, user_prompt: str, schema: type[TModel]) -> TModel:
    """结构化抽取，带一次退避重试；输出不合法视为失败。"""
    structured = model.with_structured_output(schema, method="function_calling")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_error: Exception | None = None
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            result = structured.invoke(messages)
            if isinstance(result, schema):
                return result
            raise ModelCallError(f"模型输出类型不符：{type(result).__name__}")
        except ModelCallError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < _ATTEMPTS and _is_retryable(exc):
                logger.warning(f"物流询价识别失败，{_RETRY_DELAY_SECONDS}s 后重试：{type(exc).__name__}")
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            break
    raise ModelCallError(f"物流询价识别失败：{type(last_error).__name__}: {last_error}") from last_error


def _is_retryable(exc: Exception) -> bool:
    """限流、超时、网关错误值得重试；鉴权与参数错误重试无意义。"""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return status in (408, 409, 425, 429, 500, 502, 503, 504)
    name = type(exc).__name__.lower()
    return any(marker in name for marker in ("timeout", "connection", "unavailable", "ratelimit"))
