"""物流报价文件解析与识别结果管理 API（识别结果持久化，原始文件不落盘）。

第一步上传识别报价表时，同一份文件的线路明细会一并导入线路数据层，
供第五步物流 Agent 按收发地匹配真实费率；删除识别结果时同步清理对应批次。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from loguru import logger

from app.services import logistics_quote_parser
from app.services.logistics_quote_books import LogisticsQuoteBookService
from app.services.logistics_quote_routes import LogisticsRouteService, build_route_rows


def create_logistics_quote_router(
    get_current_user: Callable[..., dict[str, Any]],
    db_manager: Any = None,
) -> APIRouter:
    router = APIRouter()
    book_service = LogisticsQuoteBookService(db_manager) if db_manager is not None else None
    route_service = LogisticsRouteService(db_manager) if db_manager is not None else None

    @router.post("/api/logistics/quote-sources/parse")
    async def parse_quote_source(
        file: UploadFile = File(...),
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """识别上传报价表的服务摘要；文件内容不落盘，结果不保存。"""
        return await _parse_and_respond(file)

    @router.get("/api/logistics/quote-books")
    def list_quote_books(current_user: dict[str, Any] = Depends(get_current_user)):
        """返回当前用户已保存的全部报价表识别结果。"""
        if book_service is None:
            raise HTTPException(status_code=503, detail="识别结果存储未启用")
        return {"success": True, "books": book_service.list_books(current_user["user_id"])}

    @router.post("/api/logistics/quote-books")
    async def create_quote_book(
        file: UploadFile = File(...),
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """识别上传报价表并保存识别结果；相同文件重复上传时刷新原记录。

        识别成功后会把同一份文件的线路明细导入线路库（与第五步 Agent 共用），
        线路同步失败不影响识别结果保存，会在响应中以 route_warning 提示。
        """
        if book_service is None:
            raise HTTPException(status_code=503, detail="识别结果存储未启用")
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="上传文件为空")
        filename = file.filename or ""
        content_type = file.content_type or ""
        result = await _parse_summary(data, filename, content_type)
        book = book_service.save_book(current_user["user_id"], filename, result)
        if book is None:
            raise HTTPException(status_code=500, detail="识别结果保存失败，请重试")
        route_import, route_warning = await _sync_route_import(
            current_user["user_id"], filename, content_type, data
        )
        return {
            "success": True,
            "book": book,
            "route_import": route_import,
            "route_warning": route_warning,
        }

    @router.delete("/api/logistics/quote-books/{book_id}")
    def delete_quote_book(
        book_id: int,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """删除当前用户的一条报价表识别结果，并同步清理对应线路明细批次。"""
        if book_service is None:
            raise HTTPException(status_code=503, detail="识别结果存储未启用")
        book = book_service.get_book(current_user["user_id"], book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="识别结果不存在")
        if not book_service.delete_book(current_user["user_id"], book_id):
            raise HTTPException(status_code=404, detail="识别结果不存在")
        if route_service is not None and book.get("sha256"):
            route_service.delete_import_by_sha(current_user["user_id"], book["sha256"])
        return {"success": True}

    async def _parse_summary(data: bytes, filename: str, content_type: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                logistics_quote_parser.parse_quote_file,
                data,
                filename=filename,
                content_type=content_type,
                rate_book_summary=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def _parse_and_respond(file: UploadFile) -> dict[str, Any]:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="上传文件为空")
        result = await _parse_summary(data, file.filename or "", file.content_type or "")
        return {"success": True, **result}

    async def _sync_route_import(
        user_id: int, filename: str, content_type: str, data: bytes
    ) -> tuple[dict[str, Any] | None, str]:
        """识别成功后把线路明细导入 Agent 线路库；失败不阻塞识别结果保存。"""
        if route_service is None:
            return None, ""
        try:
            full_result = await asyncio.to_thread(
                logistics_quote_parser.parse_quote_file,
                data,
                filename=filename,
                content_type=content_type,
                rate_book_summary=False,
            )
            route_rows, warnings = await asyncio.to_thread(build_route_rows, full_result)
            if not route_rows:
                return None, "文件中没有可导入的线路明细，第五步 Agent 暂无法使用该报价表"
            imported = await asyncio.to_thread(
                route_service.import_book, user_id, filename, full_result, route_rows, warnings
            )
            return imported, ""
        except Exception as exc:  # noqa: BLE001 - 同步失败只提示，不让识别上传失败
            logger.warning(f"线路明细同步失败（用户 {user_id}，文件：{filename}）：{exc}")
            return None, f"线路明细同步失败：{exc}"

    return router
