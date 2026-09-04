"""物流报价表识别结果的持久化服务（按系统用户隔离，仅保存解析摘要）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger

PAYLOAD_MAX_BYTES = 512 * 1024


def _to_iso_utc(value: Any) -> str | None:
    """SQLite CURRENT_TIMESTAMP 为 UTC，统一转成带时区的 ISO 字符串。"""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("T", " ").split(".")[0])
        except ValueError:
            return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _decode_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


class LogisticsQuoteBookService:
    def __init__(self, db_manager: Any):
        self.db = db_manager

    def list_books(self, user_id: int) -> list[dict[str, Any]]:
        """返回当前用户的全部报价表识别结果，最近识别的在前。"""
        with self.db.lock:
            cursor = self.db.conn.execute(
                """
                SELECT id, filename, file_type, size_bytes, sha256, book_kind,
                       service_count, route_count, payload, created_at, updated_at
                FROM logistics_quote_books
                WHERE user_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()

        books = []
        for row in rows:
            books.append(
                {
                    "id": row[0],
                    "filename": row[1],
                    "file_type": row[2] or "",
                    "size_bytes": row[3] or 0,
                    "sha256": row[4] or "",
                    "book_kind": row[5],
                    "service_count": row[6] or 0,
                    "route_count": row[7] or 0,
                    "payload": _decode_payload(row[8]),
                    "created_at": _to_iso_utc(row[9]),
                    "updated_at": _to_iso_utc(row[10]),
                }
            )
        return books

    def save_book(self, user_id: int, filename: str, result: dict[str, Any]) -> dict[str, Any]:
        """保存识别摘要；同一用户重复上传相同文件时刷新原记录，不产生重复。"""
        source = result.get("source") or {}
        sha256 = str(source.get("sha256") or "")
        payload = {key: value for key, value in result.items() if key != "success"}
        try:
            payload_json = json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("识别结果序列化失败，无法保存") from exc
        if len(payload_json.encode("utf-8")) > PAYLOAD_MAX_BYTES:
            payload_json = json.dumps(
                {**payload, "rows": [], "carriers": []}, ensure_ascii=False
            )

        with self.db.lock:
            cursor = self.db.conn.execute(
                """
                INSERT INTO logistics_quote_books (
                    user_id, filename, file_type, size_bytes, sha256,
                    book_kind, service_count, route_count, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, sha256) DO UPDATE SET
                    filename = excluded.filename,
                    file_type = excluded.file_type,
                    size_bytes = excluded.size_bytes,
                    book_kind = excluded.book_kind,
                    service_count = excluded.service_count,
                    route_count = excluded.route_count,
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    filename,
                    str(source.get("file_type") or ""),
                    int(source.get("size") or 0),
                    sha256,
                    result.get("book_kind"),
                    int(result.get("service_count") or 0),
                    int(result.get("route_count") or 0),
                    payload_json,
                ),
            )
            self.db.conn.commit()
            row_id = cursor.lastrowid
            if not row_id:
                cursor = self.db.conn.execute(
                    "SELECT id FROM logistics_quote_books WHERE user_id = ? AND sha256 = ?",
                    (user_id, sha256),
                )
                found = cursor.fetchone()
                row_id = found[0] if found else None
        return self.get_book(user_id, row_id) if row_id else None

    def get_book(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        with self.db.lock:
            cursor = self.db.conn.execute(
                """
                SELECT id, filename, file_type, size_bytes, sha256, book_kind,
                       service_count, route_count, payload, created_at, updated_at
                FROM logistics_quote_books
                WHERE user_id = ? AND id = ?
                """,
                (user_id, book_id),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "filename": row[1],
            "file_type": row[2] or "",
            "size_bytes": row[3] or 0,
            "sha256": row[4] or "",
            "book_kind": row[5],
            "service_count": row[6] or 0,
            "route_count": row[7] or 0,
            "payload": _decode_payload(row[8]),
            "created_at": _to_iso_utc(row[9]),
            "updated_at": _to_iso_utc(row[10]),
        }

    def delete_book(self, user_id: int, book_id: int) -> bool:
        with self.db.lock:
            cursor = self.db.conn.execute(
                "DELETE FROM logistics_quote_books WHERE user_id = ? AND id = ?",
                (user_id, book_id),
            )
            self.db.conn.commit()
        if cursor.rowcount:
            logger.info(f"用户 {user_id} 删除物流报价表识别结果 #{book_id}")
        return bool(cursor.rowcount)
