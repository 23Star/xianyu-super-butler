"""完整逐行解析模式：每个工作表解析出全部报价行。"""

from __future__ import annotations

from typing import Any

from .carriers import _sheet_name_carrier
from .constants import MAX_ROWS_PER_SHEET, MAX_SHEETS, MAX_WARNINGS
from .headers import _detect_header, _header_implied_weight
from .readers import _is_skippable_source_row, _iter_csv_rows, _iter_xls_rows, _iter_xlsx_rows
from .rows import _build_row_result
from .values import _cell_text, _normalize_text


def _parse_spreadsheet(data: bytes, file_type: str) -> dict[str, Any]:
    warnings: list[str] = []
    rows_out: list[dict[str, Any]] = []

    if file_type == "csv":
        rows, csv_warnings = _iter_csv_rows(data)
        warnings.extend(csv_warnings)
        sheets = [("CSV", rows, True)]
    elif file_type == "xls":
        sheets, xls_warnings = _iter_xls_rows(data)
        warnings.extend(xls_warnings)
    else:
        sheets, xlsx_warnings = _iter_xlsx_rows(data)
        warnings.extend(xlsx_warnings)
    if len(sheets) > MAX_SHEETS:
        warnings.append(f"工作表数量超过 {MAX_SHEETS} 个，仅解析前 {MAX_SHEETS} 个")
        sheets = sheets[:MAX_SHEETS]

    mapping: dict[str, str] = {}
    unmatched_headers: set[str] = set()
    services: list[dict[str, Any]] = []
    valid = review = rejected = 0

    for sheet_name, rows, visible in sheets:
        if not visible:
            warnings.append(f"工作表「{sheet_name}」为隐藏状态，已跳过")
            continue
        header_index, column_mapping, column_specs, header_warnings = _detect_header(rows)
        warnings.extend(header_warnings)
        if header_index is None:
            continue

        sheet_carrier: str | None = None
        if file_type != "csv" and "carrier" not in column_mapping.values():
            candidate = _sheet_name_carrier(sheet_name)
            if candidate:
                sheet_carrier = candidate
                warnings.append(f"工作表「{sheet_name}」未识别到承运商列，已按工作表名作为承运商来源")

        for column, field in column_mapping.items():
            if field == "continued_tier":
                mapping.setdefault("continued_tiers", _cell_text(rows[header_index][column]))
                continue
            if field == "fixed_tier":
                mapping.setdefault("fixed_tiers", _cell_text(rows[header_index][column]))
                continue
            mapping.setdefault(field, _cell_text(rows[header_index][column]))
            if field in ("first_price", "continued_price"):
                header_text = _normalize_text(rows[header_index][column])
                spec = column_specs.setdefault(column, {})
                implied = _header_implied_weight(header_text)
                if implied is not None:
                    spec["implied_weight"] = implied
                    spec["field"] = field
                if "最低价" in header_text:
                    spec["semantics"] = "最低价"
                    spec.setdefault("header", _cell_text(rows[header_index][column]))
        header_cells = {column: _cell_text(rows[header_index][column]) for column in column_mapping}
        for column, cell in enumerate(rows[header_index]):
            header = _normalize_text(cell)
            if header and column not in column_mapping:
                unmatched_headers.add(header)

        sheet_rows: list[dict[str, Any]] = []
        for offset, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
            if not any(_normalize_text(cell) for cell in row):
                continue
            if _is_skippable_source_row(row):
                warnings.append(f"已跳过「{sheet_name}」第 {offset} 行的合计/统计行")
                continue
            result = _build_row_result(
                f"row-{sheet_name}-{offset}",
                sheet_name,
                offset,
                header_cells,
                column_mapping,
                row,
                column_specs,
                sheet_carrier,
            )
            if result["review_state"] == "valid":
                valid += 1
            elif result["review_state"] == "review":
                review += 1
            else:
                rejected += 1
            rows_out.append(result)
            sheet_rows.append(result)

        if sheet_rows:
            route_count = len({row["route"] for row in sheet_rows if row["route"]}) or len(sheet_rows)
            rule_types = {row["rule_type"] for row in sheet_rows if row["rule_type"]}
            book_kinds = {row["book_kind"] for row in sheet_rows if row["book_kind"]}
            service_mapping = {
                field: _cell_text(rows[header_index][column])
                for column, field in column_mapping.items()
                if field not in {"continued_tier", "fixed_tier"}
            }
            services.append(
                {
                    "name": sheet_carrier or sheet_name,
                    "sheet_name": sheet_name,
                    "row_count": len(sheet_rows),
                    "route_count": route_count,
                    "rule_type": next(iter(rule_types)) if len(rule_types) == 1 else "mixed",
                    "book_kind": next(iter(book_kinds)) if len(book_kinds) == 1 else None,
                    "mapping": service_mapping,
                }
            )

    if not rows_out:
        header_warning = next((warning for warning in warnings if "表头" in warning), None)
        raise ValueError(header_warning or "未能在文件中解析出报价行，请确认文件是否为报价表")

    if unmatched_headers:
        sample = "、".join(sorted(unmatched_headers)[:10])
        warnings.append(f"以下列未纳入字段映射：{sample}（可在人工映射中补充）")

    route_count = len({(row["carrier"], row["route"]) for row in rows_out if row["route"]}) or len(rows_out)
    book_kinds = {row["book_kind"] for row in rows_out if row["book_kind"]}
    return {
        "mapping": {"matched": mapping, "unmatched": sorted(unmatched_headers)},
        "summary": {"total": valid + review + rejected, "valid": valid, "review": review, "rejected": rejected},
        "book_kind": next(iter(book_kinds)) if len(book_kinds) == 1 else None,
        "service_count": len(services),
        "route_count": route_count,
        "services": services,
        "rows": rows_out,
        "warning_count": len(warnings),
        "warnings": warnings[:MAX_WARNINGS],
    }
