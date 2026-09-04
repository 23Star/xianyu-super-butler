"""物流报价表解析服务（仅解析预览，不落盘、不持久化）。

设计约束（对应 LOGISTICS_QUOTE_REPAIR_PLAN.md 第 5 节、
LOGISTICS_QUOTE_CARRIER_RECOGNITION_PLAN.md 第 6 节）：
- 支持 .xlsx/.xlsm（openpyxl）、旧版 .xls（xlrd）与文本 CSV；图片返回明确的不支持错误。
- 表头按别名词典在前若干行内识别；未识别的列进入 warnings，不猜测含义。
- XLSX 未识别到承运商列时，以可见工作表名作为承运商来源，并记录 carrier_source。
- 缺失或无法判断的字段保持 None，由调用方进入人工复核，不填充默认值。

模块划分：
- constants：版本、上限与文件魔数。
- values：单元格文本与金额/重量/时效/区域解析。
- headers：字段别名词典与表头行检测。
- rules：计价规则与表类型推断。
- readers：文件类型探测与 CSV/XLSX/XLS 行迭代。
- rows：单行报价结果构建。
- carriers：承运商识别与承运商名单摘要模式。
- summary：报价表服务摘要模式（识别卡片数据）。
- spreadsheet：完整逐行解析模式。
- service：parse_quote_file 入口与分发。
"""

from __future__ import annotations

from .carriers import (
    _carrier_summary_result,
    _collect_column_carriers,
    _detect_carrier_header,
    _register_carrier,
    _sheet_name_carrier,
)
from .constants import (
    HEADER_SCAN_ROWS,
    MAX_CELL_TEXT,
    MAX_FILE_BYTES,
    MAX_ROWS_PER_SHEET,
    MAX_SHEETS,
    MAX_WARNINGS,
    OLD_XLS_MAGIC,
    PARSER_VERSION,
    SUPPORTED_EXTENSIONS,
    XLSX_MAGIC,
)
from .headers import (
    FIELD_ALIASES,
    REQUIRED_PRICE_FIELDS,
    _detect_header,
    _header_implied_weight,
    _match_fixed_tier_header,
    _match_header_field,
    _match_tier_header,
)
from .readers import _detect_file_type, _iter_csv_rows, _iter_xls_rows, _iter_xlsx_rows
from .rows import _build_row_result
from .rules import _infer_book_kind, _infer_rule_type, _missing_price_fields
from .service import parse_quote_file
from .spreadsheet import _parse_spreadsheet
from .summary import _parse_rate_book_summary
from .values import (
    _cell_text,
    _label,
    _normalize_text,
    _parse_amount,
    _parse_eta,
    _parse_weight,
    _region_text,
)

__all__ = [
    "parse_quote_file",
    "PARSER_VERSION",
    "SUPPORTED_EXTENSIONS",
    "MAX_FILE_BYTES",
    "MAX_SHEETS",
    "MAX_ROWS_PER_SHEET",
    "HEADER_SCAN_ROWS",
    "MAX_WARNINGS",
    "MAX_CELL_TEXT",
    "OLD_XLS_MAGIC",
    "XLSX_MAGIC",
    "FIELD_ALIASES",
    "REQUIRED_PRICE_FIELDS",
    "_detect_file_type",
    "_iter_csv_rows",
    "_iter_xlsx_rows",
    "_iter_xls_rows",
    "_normalize_text",
    "_cell_text",
    "_label",
    "_parse_amount",
    "_parse_weight",
    "_parse_eta",
    "_region_text",
    "_match_header_field",
    "_match_tier_header",
    "_match_fixed_tier_header",
    "_header_implied_weight",
    "_detect_header",
    "_infer_rule_type",
    "_infer_book_kind",
    "_missing_price_fields",
    "_build_row_result",
    "_detect_carrier_header",
    "_register_carrier",
    "_collect_column_carriers",
    "_sheet_name_carrier",
    "_carrier_summary_result",
    "_parse_carrier_summary",
    "_parse_rate_book_summary",
    "_parse_spreadsheet",
]
