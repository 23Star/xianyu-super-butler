"""LangGraph StateGraph 组装与编译入口。

图负责多轮状态与节点编排；确定性业务逻辑仍在 routes/tools/render 中。
正式消息入口与第五步测试入口通过同一个工厂编译并共用同一个图实例。
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.services.logistics_agent.checkpointer import get_checkpointer
from app.services.logistics_agent.graph_state import LogisticsGraphState
from app.services.logistics_agent.nodes import (
    GraphDeps,
    call_workflow_node,
    check_missing_node,
    extract_node,
    finalize_node,
    merge_state_node,
    render_reply_node,
    resolve_routes_node,
)
from app.services.logistics_agent.settings import AgentSettingsStore
from app.services.logistics_quote_routes.service import LogisticsRouteService


def _route_after_merge(state: LogisticsGraphState) -> str:
    """非物流询价（正式入口）：跳过业务节点直接收尾。"""
    return "finalize" if state.get("action") == "ignore" else "check_missing"


def _route_after_check(state: LogisticsGraphState) -> str:
    """缺参走追问渲染，参数齐备走线路匹配（missing_fields 每轮由节点重写）。"""
    return "render_reply" if state.get("missing_fields") else "resolve_routes"


def _route_after_resolve(state: LogisticsGraphState) -> str:
    """命中线路才进入计费，否则渲染追问/转人工文案。"""
    return "call_workflow" if state.get("routes") is not None else "render_reply"


def build_logistics_graph(deps: GraphDeps, checkpointer: Any = None) -> CompiledStateGraph:
    """编译物流报价 Agent 图；checkpointer 缺省使用进程级共享实现。"""
    builder = StateGraph(LogisticsGraphState)
    nodes = {
        "extract": partial(extract_node, deps),
        "merge_state": partial(merge_state_node, deps),
        "check_missing": partial(check_missing_node, deps),
        "resolve_routes": partial(resolve_routes_node, deps),
        "call_workflow": partial(call_workflow_node, deps),
        "render_reply": partial(render_reply_node, deps),
        "finalize": partial(finalize_node, deps),
    }
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, "extract")
    builder.add_edge("extract", "merge_state")
    builder.add_conditional_edges("merge_state", _route_after_merge, ["check_missing", "finalize"])
    builder.add_conditional_edges("check_missing", _route_after_check, ["resolve_routes", "render_reply"])
    builder.add_conditional_edges("resolve_routes", _route_after_resolve, ["call_workflow", "render_reply"])
    builder.add_edge("call_workflow", "render_reply")
    builder.add_edge("render_reply", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def build_default_graph(db_manager: Any) -> CompiledStateGraph:
    """按项目默认依赖（db_manager + 各 Store）编译共享图实例。"""
    deps = GraphDeps(
        db=db_manager,
        settings_store=AgentSettingsStore(db_manager),
        route_service=LogisticsRouteService(db_manager),
    )
    return build_logistics_graph(deps, checkpointer=get_checkpointer(db_manager))
