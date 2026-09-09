"""线路明细服务：导入批次管理、按收发地匹配线路、省市反查。

线路匹配优先级（由高到低）：
1. 发货市 + 收货市
2. 发货市 + 收货省
3. 发货省 + 收货市
4. 发货省 + 收货省

每个承运商只取其数据粒度能支持的最精确匹配；省市两级都查不到时，
标记"需要买家补充城市"而不是直接判无线路。
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from app.services.logistics_quote_routes.region import normalize_region

_MATCH_LEVELS: tuple[tuple[str, str, str], ...] = (
    ("city_city", "origin_city", "dest_city"),
    ("city_province", "origin_city", "dest_province"),
    ("province_city", "origin_province", "dest_city"),
    ("province_province", "origin_province", "dest_province"),
)

_LEVEL_LABELS = {
    "city_city": "市→市",
    "city_province": "市→省",
    "province_city": "省→市",
    "province_province": "省→省",
}

_BATCH_SIZE = 5_000


def _decode(value: Any, default: Any) -> Any:
    if isinstance(value, dict | list):
        return value
    if value in (None, ""):
        return default
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return default
    return decoded if isinstance(decoded, type(default)) else default


class LogisticsRouteService:
    """线路明细的持久化与查询；数据按系统用户隔离。"""

    def __init__(self, db_manager: Any):
        self.db = db_manager

    # ---------- 导入 ----------

    def import_book(self, user_id: int, filename: str, parse_result: dict[str, Any], route_rows: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any]:
        """保存一次导入批次及其全部线路；同一用户重复导入相同文件时整批替换。"""
        source = parse_result.get("source") or {}
        sha256 = str(source.get("sha256") or "")
        book_kind = parse_result.get("book_kind")
        if not sha256:
            raise ValueError("解析结果缺少文件哈希，无法导入")
        book_kinds = {row["book_kind"] for row in route_rows if row.get("book_kind")}
        if len(book_kinds) == 1:
            book_kind = next(iter(book_kinds))
        warnings_json = json.dumps(warnings, ensure_ascii=False)

        with self.db.lock:
            cursor = self.db.conn.execute(
                "SELECT id FROM logistics_quote_route_imports WHERE user_id = ? AND sha256 = ?",
                (user_id, sha256),
            )
            existing = cursor.fetchone()
            import_id = existing[0] if existing else None
            try:
                if import_id is None:
                    cursor = self.db.conn.execute(
                        """
                        INSERT INTO logistics_quote_route_imports (
                            user_id, filename, file_type, size_bytes, sha256,
                            book_kind, service_count, route_count, status, warnings
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?)
                        """,
                        (
                            user_id, filename, str(source.get("file_type") or ""),
                            int(source.get("size") or 0), sha256, book_kind,
                            int(parse_result.get("service_count") or 0), len(route_rows),
                            warnings_json,
                        ),
                    )
                    import_id = cursor.lastrowid
                else:
                    self.db.conn.execute(
                        """
                        UPDATE logistics_quote_route_imports SET
                            filename = ?, file_type = ?, size_bytes = ?, book_kind = ?,
                            service_count = ?, route_count = ?, status = 'completed',
                            warnings = ?, created_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            filename, str(source.get("file_type") or ""),
                            int(source.get("size") or 0), book_kind,
                            int(parse_result.get("service_count") or 0), len(route_rows),
                            warnings_json, import_id,
                        ),
                    )
                    self.db.conn.execute(
                        "DELETE FROM logistics_quote_routes WHERE import_id = ?", (import_id,)
                    )
                self._insert_routes(user_id, import_id, route_rows)
                self.db.conn.commit()
            except Exception:
                self.db.conn.rollback()
                raise
        logger.info(f"用户 {user_id} 导入线路明细 {len(route_rows)} 条（批次 #{import_id}，文件：{filename}）")
        return self.get_import(user_id, import_id)

    def _insert_routes(self, user_id: int, import_id: int, route_rows: list[dict[str, Any]]) -> None:
        params = [
            (
                user_id, import_id, row["carrier"], row["book_kind"],
                row["origin_province"], row["origin_city"], row["dest_province"],
                row["dest_city"], json.dumps(row["price_model"], ensure_ascii=False),
            )
            for row in route_rows
        ]
        for start in range(0, len(params), _BATCH_SIZE):
            self.db.conn.executemany(
                """
                INSERT INTO logistics_quote_routes (
                    user_id, import_id, carrier, book_kind,
                    origin_province, origin_city, dest_province, dest_city, price_model
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params[start : start + _BATCH_SIZE],
            )

    def list_imports(self, user_id: int) -> list[dict[str, Any]]:
        with self.db.lock:
            cursor = self.db.conn.execute(
                """
                SELECT id, filename, file_type, size_bytes, sha256, book_kind,
                       service_count, route_count, status, warnings, created_at
                FROM logistics_quote_route_imports
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            carrier_rows = self.db.conn.execute(
                "SELECT DISTINCT import_id, carrier FROM logistics_quote_routes WHERE user_id = ? ORDER BY carrier",
                (user_id,),
            ).fetchall()
        carriers: dict[int, list[str]] = {}
        for import_id, carrier in carrier_rows:
            carriers.setdefault(import_id, []).append(carrier)
        return [
            {
                "id": row[0], "filename": row[1], "file_type": row[2] or "",
                "size_bytes": row[3] or 0, "sha256": row[4] or "", "book_kind": row[5],
                "service_count": row[6] or 0, "route_count": row[7] or 0,
                "status": row[8] or "", "warnings": _decode(row[9], []),
                "created_at": row[10],
                "carriers": carriers.get(row[0], []),
            }
            for row in rows
        ]

    def get_import(self, user_id: int, import_id: int) -> dict[str, Any] | None:
        found = next(
            (item for item in self.list_imports(user_id) if item["id"] == import_id),
            None,
        )
        return found

    def get_import_meta(self, user_id: int, import_id: int) -> dict[str, Any] | None:
        """读取批次元数据（含哈希），供报价版本记录使用。"""
        found = self.get_import(user_id, import_id)
        if not found:
            return None
        return {
            "id": found["id"],
            "sha256": found["sha256"],
            "book_kind": found["book_kind"],
            "filename": found["filename"],
            "route_count": found["route_count"],
        }

    def delete_import_by_sha(self, user_id: int, sha256: str) -> bool:
        """按文件哈希删除导入批次；第一步删除识别结果时同步清理使用。"""
        if not sha256:
            return False
        with self.db.lock:
            cursor = self.db.conn.execute(
                "SELECT id FROM logistics_quote_route_imports WHERE user_id = ? AND sha256 = ?",
                (user_id, sha256),
            )
            row = cursor.fetchone()
        if not row:
            return False
        return self.delete_import(user_id, int(row[0]))

    def delete_import(self, user_id: int, import_id: int) -> bool:
        with self.db.lock:
            cursor = self.db.conn.execute(
                "DELETE FROM logistics_quote_routes WHERE import_id = ? AND user_id = ?",
                (import_id, user_id),
            )
            cursor = self.db.conn.execute(
                "DELETE FROM logistics_quote_route_imports WHERE id = ? AND user_id = ?",
                (import_id, user_id),
            )
            self.db.conn.commit()
        if cursor.rowcount:
            logger.info(f"用户 {user_id} 删除线路导入批次 #{import_id}")
        return bool(cursor.rowcount)

    def carriers_for_books(self, user_id: int, import_ids: list[int], book_kind: str) -> list[str]:
        """所选批次在某类别下实际存在的承运商列表。"""
        if not import_ids:
            return []
        placeholders = ",".join("?" * len(import_ids))
        with self.db.lock:
            cursor = self.db.conn.execute(
                f"""
                SELECT DISTINCT carrier FROM logistics_quote_routes
                WHERE user_id = ? AND import_id IN ({placeholders}) AND book_kind = ?
                ORDER BY carrier
                """,
                (user_id, *import_ids, book_kind),
            )
            rows = cursor.fetchall()
        return [row[0] for row in rows]

    # ---------- 地址反查 ----------

    def resolve_province_by_city(self, user_id: int, city: str, side: str = "origin") -> dict[str, Any]:
        """按市名反查省份；同名市跨省时返回 ambiguous。"""
        if not city:
            return {"province": "", "ambiguous": False}
        if side not in ("origin", "destination", "dest"):
            raise ValueError("地址方向必须为 origin 或 destination")
        prefix = "origin" if side == "origin" else "dest"
        column = f"{prefix}_province"
        city_column = f"{prefix}_city"
        with self.db.lock:
            cursor = self.db.conn.execute(
                f"""
                SELECT DISTINCT {column} FROM logistics_quote_routes
                WHERE user_id = ? AND {city_column} = ? AND {column} <> ''
                ORDER BY {column}
                LIMIT 2
                """,
                (user_id, normalize_region(city)),
            )
            rows = cursor.fetchall()
        if not rows:
            return {"province": "", "ambiguous": False}
        return {"province": rows[0][0] if len(rows) == 1 else "", "ambiguous": len(rows) > 1}

    # ---------- 线路匹配 ----------

    def match_routes(
        self,
        user_id: int,
        origin: dict[str, str],
        destination: dict[str, str],
        book_kind: str,
        import_ids: list[int] | None = None,
        carriers: list[str] | None = None,
    ) -> dict[str, Any]:
        """按收发地匹配线路。

        origin/destination 形如 {"province": "江西", "city": "赣州"}；
        逐级尝试四种粒度，每个承运商只保留最精确的一次命中；某承运商
        数据粒度不足时进入 needs_city_carriers，提示买家补充城市。
        """
        import_filter = ""
        import_params: list[Any] = []
        if import_ids:
            import_filter = f" AND import_id IN ({','.join('?' * len(import_ids))})"
            import_params = list(import_ids)
        carrier_filter = ""
        carrier_params: list[Any] = []
        if carriers:
            carrier_filter = f" AND carrier IN ({','.join('?' * len(carriers))})"
            carrier_params = list(carriers)

        matches: dict[str, dict[str, Any]] = {}
        hit_level: str | None = None
        with self.db.lock:
            for level_key, origin_field, dest_field in _MATCH_LEVELS:
                origin_city = origin.get("city", "") if origin_field == "origin_city" else ""
                dest_city = destination.get("city", "") if dest_field == "dest_city" else ""
                if (origin_field == "origin_city" and not origin_city) or (
                    dest_field == "dest_city" and not dest_city
                ):
                    continue
                cursor = self.db.conn.execute(
                    f"""
                    SELECT carrier, import_id, origin_province, origin_city,
                           dest_province, dest_city, price_model
                    FROM logistics_quote_routes
                    WHERE user_id = ? AND book_kind = ?
                      AND origin_province = ? AND origin_city = ?
                      AND dest_province = ? AND dest_city = ?
                      {import_filter}{carrier_filter}
                    """,
                    (
                        user_id, book_kind,
                        origin.get("province", ""), origin_city,
                        destination.get("province", ""), dest_city,
                        *import_params, *carrier_params,
                    ),
                )
                for row in cursor.fetchall():
                    carrier = row[0]
                    if carrier in matches:
                        continue
                    matches[carrier] = {
                        "carrier": carrier,
                        "import_id": row[1],
                        "origin": {"province": row[2], "city": row[3]},
                        "destination": {"province": row[4], "city": row[5]},
                        "price_model": _decode(row[6], {}),
                        "match_level": level_key,
                        "match_level_label": _LEVEL_LABELS[level_key],
                    }
                    if hit_level is None:
                        hit_level = level_key

        all_carriers = self.carriers_for_books(user_id, import_ids or [], book_kind)
        if carriers:
            all_carriers = [name for name in all_carriers if name in set(carriers)]
        unmatched = [name for name in all_carriers if name not in matches]
        needs_city = self._carriers_needing_city(
            user_id, origin, destination, book_kind, import_ids, unmatched
        ) if unmatched else []
        return {
            "matched": matches,
            "match_level": hit_level,
            "match_level_label": _LEVEL_LABELS.get(hit_level or "", ""),
            "needs_city_carriers": needs_city,
            "unmatched_carriers": unmatched,
            "route_not_found": not matches and not needs_city,
        }

    def _carriers_needing_city(
        self,
        user_id: int,
        origin: dict[str, str],
        destination: dict[str, str],
        book_kind: str,
        import_ids: list[int] | None,
        carriers: list[str] | None,
    ) -> list[str]:
        """找出省市两级都匹配不到、但同省线路需要城市粒度的承运商。"""
        if not origin.get("province") or not destination.get("province"):
            return []
        conditions = [
            "user_id = ?", "book_kind = ?",
            "origin_province = ?", "dest_province = ?",
        ]
        params: list[Any] = [user_id, book_kind, origin["province"], destination["province"]]
        missing_city_conditions = []
        for region, column in ((origin, "origin_city"), (destination, "dest_city")):
            if region.get("city"):
                conditions.append(f"({column} = '' OR {column} = ?)")
                params.append(region["city"])
            else:
                missing_city_conditions.append(f"{column} <> ''")
        if not missing_city_conditions:
            return []
        conditions.append(f"({' OR '.join(missing_city_conditions)})")
        if import_ids:
            conditions.append(f"import_id IN ({','.join('?' * len(import_ids))})")
            params.extend(import_ids)
        if carriers:
            conditions.append(f"carrier IN ({','.join('?' * len(carriers))})")
            params.extend(carriers)
        with self.db.lock:
            cursor = self.db.conn.execute(
                f"""
                SELECT DISTINCT carrier FROM logistics_quote_routes
                WHERE {' AND '.join(conditions)}
                """,
                params,
            )
            rows = cursor.fetchall()
        return [row[0] for row in rows]

    def count_routes(self, user_id: int) -> int:
        with self.db.lock:
            cursor = self.db.conn.execute(
                "SELECT COUNT(*) FROM logistics_quote_routes WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
        return int(row[0]) if row else 0
