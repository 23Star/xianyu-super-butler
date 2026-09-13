"""报价文件解析入口：按模式分发到完整解析或两种摘要解析。"""

from __future__ import annotations

import hashlib
from typing import Any

from .carriers import _parse_carrier_summary
from .constants import MAX_FILE_BYTES, PARSER_VERSION
from .readers import _detect_file_type
from .spreadsheet import _parse_spreadsheet
from .summary import _parse_rate_book_summary


def parse_quote_file(
    data: bytes,
    filename: str,
    content_type: str = "",
    carrier_only: bool = False,
    rate_book_summary: bool = False,
) -> dict[str, Any]:
    """解析报价文件；摘要模式不返回逐行报价结果。"""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 大小限制")
    if not filename:
        raise ValueError("缺少文件名")

    file_type = _detect_file_type(data, filename)

    if carrier_only and rate_book_summary:
        raise ValueError("承运商名单模式与报价表摘要模式不能同时使用")
    if carrier_only:
        result = _parse_carrier_summary(data, file_type)
    elif rate_book_summary:
        result = _parse_rate_book_summary(data, file_type)
    else:
        result = _parse_spreadsheet(data, file_type)
    result["source"] = {
        "filename": filename,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content_type": content_type or None,
        "file_type": file_type,
        "parser_version": PARSER_VERSION,
        "status": "needs_review" if result["summary"]["review"] or result["summary"]["rejected"] else "parsed",
    }
    return result
