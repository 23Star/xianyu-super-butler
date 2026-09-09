"""物流 Agent API：线路明细导入、第五步配置、启用前检测与会话试算。"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services import logistics_quote_parser
from app.services.logistics_agent import LogisticsQuoteAgent
from app.services.logistics_agent import history as agent_history
from app.services.logistics_agent.settings import normalize_settings_payload
from app.services.logistics_quote_routes import (
    LogisticsRouteService,
    build_route_rows,
)

_PARSE_MAX_BYTES = 32 * 1024 * 1024

# 启用前检测里的规则确认项：口径已在实施时由业务确认，展示给店家核对。
RULE_CONFIRMATIONS = {
    "weight_rule": "≥30kg 按计费重（实重与体积重取大）走物流报价，其余走快递报价",
    "unit_rule": "重量统一公斤，尺寸统一厘米；斤=0.5公斤，克=0.001公斤",
}


class AgentTestRequest(BaseModel):
    """物流 Agent 试算请求（显式会话协议）。"""

    cookie_id: str
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str = Field(default="", max_length=128, description="测试会话 ID；为空时服务端生成")
    chat_id: str = Field(default="agent-test", max_length=128)
    item_id: str = Field(default="", max_length=128)
    message_id: str = Field(default="", max_length=128, description="本条消息唯一 ID；为空时服务端生成")
    reset: bool = False


class AgentThreadCreateRequest(BaseModel):
    """新建测试会话请求。"""

    cookie_id: str

class AgentTrainingSample(BaseModel):
    thread_id: str = Field(min_length=1, max_length=128)
    buyer_message: str = Field(min_length=1, max_length=2000)
    agent_reply: str = Field(min_length=1, max_length=5000)
    decision: dict[str, Any] = Field(default_factory=dict)


def create_logistics_agent_router(
    get_current_user: Callable[..., dict[str, Any]],
    db_manager: Any = None,
) -> APIRouter:
    router = APIRouter()
    route_service = LogisticsRouteService(db_manager) if db_manager is not None else None

    def _agent() -> LogisticsQuoteAgent:
        if db_manager is None:
            raise HTTPException(status_code=503, detail="物流 Agent 存储未启用")
        return LogisticsQuoteAgent(db_manager)

    def _require_user_cookie(cookie_id: str, current_user: dict[str, Any]) -> None:
        user_cookies = db_manager.get_all_cookies(current_user["user_id"])
        if cookie_id not in user_cookies:
            raise HTTPException(status_code=403, detail="无权限访问该Cookie")

    # ---------- 线路明细导入 ----------

    @router.post("/api/logistics/routes/import")
    async def import_route_book(
        file: UploadFile = File(...),
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """解析上传报价文件并把全部线路导入线路明细表（按文件哈希幂等）。"""
        if route_service is None:
            raise HTTPException(status_code=503, detail="线路明细存储未启用")
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="上传文件为空")
        if len(data) > _PARSE_MAX_BYTES:
            raise HTTPException(status_code=400, detail="文件过大，请拆分报价表后再导入")
        filename = file.filename or "报价表"
        try:
            parse_result = await asyncio.to_thread(
                logistics_quote_parser.parse_quote_file,
                data,
                filename=filename,
                content_type=file.content_type or "",
                rate_book_summary=False,
            )
            route_rows, warnings = await asyncio.to_thread(build_route_rows, parse_result)
            if not route_rows:
                raise HTTPException(status_code=400, detail="文件中没有可导入的线路，请确认是正式报价表")
            imported = await asyncio.to_thread(
                route_service.import_book,
                current_user["user_id"], filename, parse_result, route_rows, warnings,
            )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - 统一转为可读错误
            raise HTTPException(status_code=500, detail=f"线路导入失败：{exc}") from exc
        return {"success": True, "import": imported}

    @router.get("/api/logistics/routes/imports")
    def list_route_imports(current_user: dict[str, Any] = Depends(get_current_user)):
        """返回当前用户已导入的线路批次。"""
        if route_service is None:
            raise HTTPException(status_code=503, detail="线路明细存储未启用")
        return {"success": True, "imports": route_service.list_imports(current_user["user_id"])}

    @router.delete("/api/logistics/routes/imports/{import_id}")
    def delete_route_import(
        import_id: int,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """删除一条线路导入批次及其全部线路。"""
        if route_service is None:
            raise HTTPException(status_code=503, detail="线路明细存储未启用")
        if not route_service.delete_import(current_user["user_id"], import_id):
            raise HTTPException(status_code=404, detail="线路导入批次不存在")
        return {"success": True}

    # ---------- 第五步配置 ----------

    @router.get("/api/logistics/agent/settings/{cookie_id}")
    def get_agent_settings(
        cookie_id: str,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """读取指定账号的物流 Agent 配置。"""
        if db_manager is None:
            raise HTTPException(status_code=503, detail="物流 Agent 存储未启用")
        _require_user_cookie(cookie_id, current_user)
        agent = _agent()
        settings = agent.settings_store.load(cookie_id)
        imports = route_service.list_imports(current_user["user_id"]) if route_service else []
        return {
            "success": True,
            "settings": settings.model_dump(),
            "available_books": imports,
            "has_saved_settings": agent.settings_store.exists(cookie_id),
        }

    @router.put("/api/logistics/agent/settings/{cookie_id}")
    async def update_agent_settings(
        cookie_id: str,
        payload: dict[str, Any],
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """保存指定账号的物流 Agent 配置。"""
        if db_manager is None:
            raise HTTPException(status_code=503, detail="物流 Agent 存储未启用")
        _require_user_cookie(cookie_id, current_user)
        agent = _agent()
        cleaned = normalize_settings_payload(payload)
        from app.services.logistics_agent.settings import AgentSettings

        settings = AgentSettings(**cleaned)
        if not agent.settings_store.save(cookie_id, settings):
            raise HTTPException(status_code=500, detail="物流 Agent 配置保存失败，请重试")
        return {"success": True, "settings": settings.model_dump()}

    # ---------- 启用前检测 ----------

    @router.get("/api/logistics/agent/status/{cookie_id}")
    def agent_status(
        cookie_id: str,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """启用自动报价前的状态检测（计划 11 节检查项）。"""
        if db_manager is None or route_service is None:
            raise HTTPException(status_code=503, detail="物流 Agent 存储未启用")
        _require_user_cookie(cookie_id, current_user)
        agent = _agent()
        settings = agent.settings_store.load(cookie_id)
        user_id = current_user["user_id"]
        imports = route_service.list_imports(user_id)
        available_ids = [item["id"] for item in imports if item.get("status") == "completed"]
        book_ids = settings.resolved_book_ids(available_ids)
        selected_books = [item for item in imports if item["id"] in set(book_ids)]

        checks: list[dict[str, Any]] = []

        checks.append(_check(
            "rate_book", "已导入可用的报价表",
            bool(selected_books),
            "已导入 %d 份报价表" % len(selected_books) if selected_books else "尚未导入报价表，请在第一步识别并导入",
        ))

        route_total = sum(item.get("route_count") or 0 for item in selected_books)
        checks.append(_check(
            "routes_queryable", "报价表包含可查询的线路明细",
            route_total > 0,
            f"共 {route_total} 条线路" if route_total else "报价表里没有可查询的线路，请重新导入",
        ))

        checks.append(_check(
            "weight_rule", "30kg 分界口径已确认",
            True,
            RULE_CONFIRMATIONS["weight_rule"],
        ))
        checks.append(_check(
            "unit_rule", "重量与尺寸单位规则已确认",
            True,
            RULE_CONFIRMATIONS["unit_rule"],
        ))

        templates_ok = bool(settings.templates.quote_message.strip()) and bool(settings.templates.missing_params.strip())
        checks.append(_check(
            "templates", "回复模板可渲染",
            templates_ok,
            "报价与追问模板已配置" if templates_ok else "报价/追问模板为空，请补充模板",
        ))

        workflow_ok, workflow_detail = _check_workflow_runtime()
        checks.append(_check("workflow", "报价计算引擎可用", workflow_ok, workflow_detail))

        test_ok, test_detail = _check_test_calculation(agent, settings, user_id, book_ids)
        checks.append(_check(
            "test_calculation", "测试消息可完成一次真实计算",
            test_ok, test_detail,
        ))

        cookie_row = db_manager.get_cookie_owner_user(cookie_id)
        checks.append(_check(
            "send_capability", "当前账号具备发送能力",
            cookie_row is not None,
            "账号已绑定，可在启用自动发送后执行真实发送" if cookie_row is not None else "账号不存在，请重新登录闲鱼账号",
        ))

        ready = all(check["passed"] for check in checks)
        return {
            "success": True,
            "ready": ready,
            "enabled": settings.enabled,
            "auto_send": settings.auto_send,
            "checks": checks,
        }

    # ---------- 测试会话 ----------

    @router.post("/api/logistics/agent/threads")
    def create_agent_thread(
        payload: AgentThreadCreateRequest,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """创建新的测试会话 ID（第五步"新建会话"）。"""
        if db_manager is None:
            raise HTTPException(status_code=503, detail="物流 Agent 存储未启用")
        _require_user_cookie(payload.cookie_id, current_user)
        return {"success": True, "thread_id": LogisticsQuoteAgent.new_thread_id()}

    def _load_owned_thread_snapshot(
        thread_id: str, cookie_id: str, *, chat_id: str = "", item_id: str = ""
    ) -> dict[str, Any]:
        """读取测试会话快照并校验归属：命名空间、账号与聊天/商品绑定。"""
        if agent_history.is_reserved_thread_id(thread_id):
            raise HTTPException(status_code=400, detail="无效的会话 ID：该前缀保留给正式消息链路")
        agent = _agent()
        try:
            snapshot = agent.thread_snapshot(thread_id)
        except Exception as exc:  # noqa: BLE001 - checkpoint 故障要给店家可读原因
            raise HTTPException(status_code=500, detail=f"读取测试会话失败：{exc}") from exc
        if not snapshot.get("exists"):
            return snapshot
        if snapshot.get("cookie_id") != cookie_id:
            raise HTTPException(status_code=403, detail="无权限访问该测试会话")
        # 会话与账号/聊天/商品的绑定必须与请求一致，防止跨聊天/商品串读状态。
        if (chat_id or item_id) and (
            snapshot.get("chat_id", "") != chat_id or snapshot.get("item_id", "") != item_id
        ):
            raise HTTPException(
                status_code=403,
                detail="该会话已绑定其他聊天或商品，请新建测试会话",
            )
        return snapshot

    @router.get("/api/logistics/agent/threads/{thread_id}")
    def get_agent_thread(
        thread_id: str,
        cookie_id: str,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """读取测试会话快照与消息记录（组件重新挂载时恢复上下文）。"""
        _require_user_cookie(cookie_id, current_user)
        snapshot = _load_owned_thread_snapshot(thread_id, cookie_id)
        if not snapshot.get("exists"):
            raise HTTPException(status_code=404, detail="测试会话不存在或已过期")
        return {"success": True, **snapshot}

    @router.delete("/api/logistics/agent/threads/{thread_id}")
    def delete_agent_thread(
        thread_id: str,
        cookie_id: str,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """清空指定测试会话（状态与消息记录一并删除）。"""
        _require_user_cookie(cookie_id, current_user)
        snapshot = _load_owned_thread_snapshot(thread_id, cookie_id)
        if not snapshot.get("exists"):
            return {"success": True}
        if not _agent().reset_thread(thread_id):
            raise HTTPException(status_code=500, detail="测试会话清空失败，请重试")
        return {"success": True}

    @router.post("/api/logistics/agent/training-samples")
    def save_training_samples(
        payload: list[AgentTrainingSample],
        cookie_id: str,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """保存店家从测试会话勾选的高质量问答，供后续提示词/评估使用。"""
        if db_manager is None:
            raise HTTPException(status_code=503, detail="物流 Agent 存储未启用")
        _require_user_cookie(cookie_id, current_user)
        import json
        with db_manager.lock:
            for sample in payload:
                db_manager.conn.execute(
                    "INSERT OR IGNORE INTO logistics_agent_training_samples "
                    "(user_id,cookie_id,thread_id,buyer_message,agent_reply,decision_json) VALUES (?,?,?,?,?,?)",
                    (current_user["user_id"], cookie_id, sample.thread_id, sample.buyer_message,
                     sample.agent_reply, json.dumps(sample.decision, ensure_ascii=False)),
                )
            db_manager.conn.commit()
        return {"success": True, "saved": len(payload)}

    # ---------- 试算 ----------

    @router.post("/api/logistics/agent/test")
    async def agent_test(
        payload: AgentTestRequest,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """物流 Agent 试算：完整走一遍图链路，不发送真实消息。"""
        if db_manager is None:
            raise HTTPException(status_code=503, detail="物流 Agent 存储未启用")
        _require_user_cookie(payload.cookie_id, current_user)
        thread_id = _resolve_test_thread_id(payload)
        message_id = payload.message_id.strip() or uuid.uuid4().hex
        # 读取/重置前统一校验会话归属与绑定（跨账号提交已有 thread_id 返回 403）。
        snapshot = _load_owned_thread_snapshot(
            thread_id, payload.cookie_id, chat_id=payload.chat_id, item_id=payload.item_id or "",
        )
        if snapshot.get("exists") and payload.reset:
            if not _agent().reset_thread(thread_id):
                raise HTTPException(status_code=500, detail="测试会话重置失败，请重试")
        agent = _agent()
        try:
            decision = await asyncio.to_thread(
                agent.preview_message,
                message=payload.message,
                chat_id=payload.chat_id,
                cookie_id=payload.cookie_id,
                item_id=payload.item_id or "",
                message_id=message_id,
                thread_id=thread_id,
            )
        except Exception as exc:  # noqa: BLE001 - 试算失败要给店家可读原因
            raise HTTPException(status_code=500, detail=f"试算失败：{exc}") from exc
        try:
            snapshot = agent.thread_snapshot(thread_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"读取测试会话快照失败：{exc}") from exc
        if decision is None:
            return {
                "success": True,
                "handled": False,
                "thread_id": thread_id,
                "detail": "消息未被识别为物流询价，将走通用 AI 回复",
            }
        return {
            "success": True,
            "handled": True,
            "thread_id": thread_id,
            "decision": decision.model_dump(),
            "state": snapshot.get("session") or {},
            "messages": snapshot.get("messages") or [],
            "events": snapshot.get("events") or [],
        }

    return router


def _resolve_test_thread_id(payload: AgentTestRequest) -> str:
    """校验客户端传入的 thread_id；为空时生成新 ID，禁止使用正式会话命名空间。"""
    thread_id = payload.thread_id.strip()
    if not thread_id:
        return agent_history.new_test_thread_id()
    if agent_history.is_reserved_thread_id(thread_id):
        raise HTTPException(status_code=400, detail="无效的会话 ID：该前缀保留给正式消息链路")
    return thread_id


def _check(key: str, label: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "passed": bool(passed), "detail": detail}


def _check_workflow_runtime() -> tuple[bool, str]:
    from app.services.logistics_agent.tools import call_workflow

    if shutil.which("node") is None:
        return False, "未检测到 Node.js，无法运行报价计算引擎"
    try:
        result = call_workflow({
            "weight_kg": 5,
            "quote_config": {
                "carriers": {"检测": {"price_table": {"first_weight_price": 10, "continued_weight_price": 2}}},
            },
        })
    except Exception as exc:  # noqa: BLE001
        return False, f"计算引擎自检失败：{exc}"
    if result.get("success"):
        return True, f"计算引擎正常（版本 {result.get('version', '1.1.0')}）"
    return False, f"计算引擎自检未通过：{result.get('reason')}"


def _check_test_calculation(agent: LogisticsQuoteAgent, settings: Any, user_id: int, book_ids: list[int]) -> tuple[bool, str]:
    """用一条真实线路完成一次不带模型的完整计算（识别步骤单独检测）。"""
    if not book_ids:
        return False, "没有可用报价表，无法完成试算"
    sample = _first_route_sample(agent.route_service, user_id, book_ids)
    if sample is None:
        return False, "报价表里没有可计算的价格形态"
    from app.services.logistics_agent.tools import build_quote_config, build_workflow_input, call_workflow

    try:
        state = sample["state"]
        quote_config = build_quote_config(settings, {"检测": sample["route"]})
        result = call_workflow(build_workflow_input(state, quote_config))
    except Exception as exc:  # noqa: BLE001
        return False, f"试算失败：{exc}"
    if result.get("success") and result.get("quotes"):
        quote = result["quotes"][0]
        return True, (
            f"试算通过：{quote['carrier']} 计费重 {quote['chargeable_weight_kg']}kg，"
            f"运费 ¥{quote['total_price']:.2f}"
        )
    return False, f"试算未通过：{result.get('reason')}"


def _first_route_sample(route_service: LogisticsRouteService, user_id: int, book_ids: list[int]) -> dict[str, Any] | None:
    """取所选批次的第一条可计算线路，组装成试算输入。"""
    from app.services.logistics_agent.models import SessionState

    placeholders = ",".join("?" * len(book_ids))
    with route_service.db.lock:
        cursor = route_service.db.conn.execute(
            f"""
            SELECT carrier, book_kind, origin_province, origin_city, dest_province, dest_city, price_model
            FROM logistics_quote_routes
            WHERE user_id = ? AND import_id IN ({placeholders})
            ORDER BY id
            LIMIT 1
            """,
            (user_id, *book_ids),
        )
        row = cursor.fetchone()
    if not row:
        return None
    price_model = _decode_json(row[6], {})
    if not price_model:
        return None
    return {
        "carrier": row[0],
        "route": {
            "carrier": row[0],
            "origin": {"province": row[2], "city": row[3]},
            "destination": {"province": row[4], "city": row[5]},
            "price_model": price_model,
        },
        "state": SessionState(
            sender=f"{row[2]}{row[3]}",
            receiver=f"{row[4]}{row[5]}",
            weight_kg=5.0,
        ),
    }


def _decode_json(value: Any, default: dict[str, Any]) -> dict[str, Any]:
    import json

    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, ValueError):
        return default
    return decoded if isinstance(decoded, dict) else default
