"""物流报价表解析常量：版本、上限与文件魔数。"""

from __future__ import annotations

PARSER_VERSION = "2026-09-04.3"

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_SHEETS = 50
MAX_ROWS_PER_SHEET = 200_000
HEADER_SCAN_ROWS = 15
MAX_WARNINGS = 20
MAX_CELL_TEXT = 50

SUPPORTED_EXTENSIONS = (".xlsx", ".xlsm", ".xls", ".csv")  # 供路由层提示使用

OLD_XLS_MAGIC = b"\xd0\xcf\x11\xe0"
XLSX_MAGIC = b"PK\x03\x04"
IMAGE_MAGICS = (
    b"\xff\xd8\xff",
    b"\x89PNG\r\n\x1a\n",
    b"GIF87a",
    b"GIF89a",
)
WEBP_MAGIC = b"RIFF"
