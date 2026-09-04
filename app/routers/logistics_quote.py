"""物流报价文件解析与识别结果管理 API（识别结果持久化，原始文件不落盘）。"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.services import logistics_quote_parser
from app.services.logistics_quote_books import LogisticsQuoteBookService


def create_logistics_quote_router(
    get_current_user: Callable[..., dict[str, Any]],
    db_manager: Any = None,
) -> APIRouter:
    router = APIRouter()
    book_service = LogisticsQuoteBookService(db_manager) if db_manager is not None else None

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
        """识别上传报价表并保存识别结果；相同文件重复上传时刷新原记录。"""
        if book_service is None:
            raise HTTPException(status_code=503, detail="识别结果存储未启用")
        result = await _parse_and_respond(file)
        book = book_service.save_book(
            current_user["user_id"], file.filename or "", result
        )
        if book is None:
            raise HTTPException(status_code=500, detail="识别结果保存失败，请重试")
        return {"success": True, "book": book}

    @router.delete("/api/logistics/quote-books/{book_id}")
    def delete_quote_book(
        book_id: int,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        """删除当前用户的一条报价表识别结果。"""
        if book_service is None:
            raise HTTPException(status_code=503, detail="识别结果存储未启用")
        if not book_service.delete_book(current_user["user_id"], book_id):
            raise HTTPException(status_code=404, detail="识别结果不存在")
        return {"success": True}

    async def _parse_and_respond(file: UploadFile) -> dict[str, Any]:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="上传文件为空")
        try:
            result = await asyncio.to_thread(
                logistics_quote_parser.parse_quote_file,
                data,
                filename=file.filename or "",
                content_type=file.content_type or "",
                rate_book_summary=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, **result}

    return router
