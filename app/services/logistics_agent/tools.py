"""Agent 工具实现：调用确定性 Workflow 计算运费。

计费公式只在 `workflows/logistics-quote.mjs` 里维护，这里通过 Node CLI
子进程调用（stdin/UTF-8 JSON），保留 Workflow 的 success/partial/errors
语义；Python 侧不复制任何计费逻辑。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger

from app.services.logistics_agent.settings import AgentSettings, CarrierPricingConfig

_WORKFLOW_CLI = Path(__file__).resolve().parents[3] / "workflows" / "logistics-quote.cli.mjs"
_WORKFLOW_TIMEOUT_SECONDS = 30

_node_platform_cache: str | None = None


class WorkflowUnavailable(RuntimeError):
    """Node 或 Workflow 文件不可用。"""


class WorkflowError(RuntimeError):
    """Workflow 调用失败（输入被拒、解析失败或超时）。"""


def _resolve_node() -> str:
    node = shutil.which("node")
    if not node:
        raise WorkflowUnavailable("未找到 node 命令，无法调用物流报价 Workflow")
    return node


def _node_platform(node: str) -> str:
    """探测 node 的运行平台（Windows node 读不了 WSL 路径，需要换算）。"""
    global _node_platform_cache
    if _node_platform_cache is None:
        try:
            probe = subprocess.run(
                [node, "-p", "process.platform"],
                capture_output=True, text=True, encoding="utf-8", timeout=10,
            )
            _node_platform_cache = (probe.stdout or "").strip() or "linux"
        except (OSError, subprocess.SubprocessError):
            _node_platform_cache = "linux"
    return _node_platform_cache


def _script_path_for(platform: str) -> str:
    """把 Workflow CLI 路径换算成当前 node 能识别的形态。"""
    path = str(_WORKFLOW_CLI)
    if platform == "win32" and path.startswith("/mnt/") and shutil.which("wslpath"):
        try:
            probe = subprocess.run(
                ["wslpath", "-w", path], capture_output=True, text=True, encoding="utf-8", timeout=10,
            )
            converted = (probe.stdout or "").strip()
            if converted:
                return converted
        except (OSError, subprocess.SubprocessError):
            pass
    return path


def call_workflow(input_payload: dict[str, Any], timeout: float = _WORKFLOW_TIMEOUT_SECONDS) -> dict[str, Any]:
    """调用 logistics_quote Workflow CLI，返回结构化结果。

    退出码：0 成功（含 partial）；1 业务校验/计算失败；2 输入解析/命令错误。
    """
    node = _resolve_node()
    if not _WORKFLOW_CLI.exists():
        raise WorkflowUnavailable(f"Workflow CLI 不存在：{_WORKFLOW_CLI}")
    stdin_json = json.dumps(input_payload, ensure_ascii=False)
    try:
        process = subprocess.run(
            [node, _script_path_for(_node_platform(node))],
            input=stdin_json,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError(f"Workflow 计算超时（{timeout:g}s）") from exc
    except OSError as exc:
        raise WorkflowUnavailable(f"Workflow 进程启动失败：{exc}") from exc

    stdout = (process.stdout or "").strip()
    if not stdout:
        raise WorkflowError(
            f"Workflow 无输出（exit={process.returncode}）：{(process.stderr or '')[:200]}"
        )
    try:
        result = json.loads(stdout)
    except ValueError as exc:
        raise WorkflowError(f"Workflow 输出不是合法 JSON：{stdout[:200]}") from exc
    if process.returncode not in (0, 1):
        reason = result.get("reason") if isinstance(result, dict) else None
        raise WorkflowError(f"Workflow 调用失败（exit={process.returncode}，reason={reason}）")
    return result


def selected_book_sha(imports: list[dict[str, Any]], book_ids: list[int]) -> str:
    """所选批次里第一条导入记录的文件哈希（resolve_routes 与发送闸门同源）。"""
    return next(
        (item["sha256"] for item in imports if item["id"] in set(book_ids)),
        "",
    )


def build_quote_config(
    settings: AgentSettings,
    matched_routes: dict[str, dict[str, Any]],
    default_volume_ratios: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把命中的线路组装成 Workflow 输入的 quote_config。

    - 抛比优先级：承运商自身配置 > 店家默认规则 > Workflow 内置默认；
    - 加价/减免使用第五步配置，未配置时全部为 0（运费即报价表原价）。
    """
    carriers: dict[str, Any] = {}
    for carrier, match in matched_routes.items():
        config: CarrierPricingConfig = settings.carrier_config.get(carrier) or CarrierPricingConfig()
        entry: dict[str, Any] = {
            "price_table": match["price_model"],
            "payment_mode": "direct",
        }
        if config.volume_ratio:
            entry["volume_ratio"] = config.volume_ratio
        if config.markup_cost:
            entry["markup_cost"] = config.markup_cost
        if config.markup_manual:
            entry["markup_manual"] = config.markup_manual
        if config.discount_rate:
            entry["discount_rate"] = config.discount_rate
        if config.discount_amount:
            entry["discount_amount"] = config.discount_amount
        carriers[carrier] = entry

    ratios = default_volume_ratios if default_volume_ratios is not None else settings.default_volume_ratios
    quote_config: dict[str, Any] = {
        "price_basis": "cost",
        "carriers": carriers,
    }
    if ratios:
        quote_config["default_volume_ratios"] = ratios
    return quote_config


def build_workflow_input(state: Any, quote_config: dict[str, Any]) -> dict[str, Any]:
    """组装 Workflow 输入（计划 8.3 契约）。

    state 是 SessionState；carrier_payment_mode 影响顺心捷达等按支付方式
    分段的抛比，未识别时保持缺省（按线上口径）。
    """
    input_payload: dict[str, Any] = {
        "quote_config": quote_config,
    }
    if state.weight_kg:
        input_payload["weight_kg"] = state.weight_kg
    if state.length_cm is not None:
        input_payload["length_cm"] = state.length_cm
    if state.width_cm is not None:
        input_payload["width_cm"] = state.width_cm
    if state.height_cm is not None:
        input_payload["height_cm"] = state.height_cm
    if state.sender:
        input_payload["sender"] = state.sender
    if state.receiver:
        input_payload["receiver"] = state.receiver
    if state.payment_mode:
        input_payload["carrier_payment_mode"] = state.payment_mode
    return input_payload
