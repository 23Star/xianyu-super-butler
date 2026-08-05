import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger


def _json_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _json_value(value: Any, fallback: Any) -> Any:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _as_dict(cursor, row) -> Dict[str, Any]:
    return dict(zip((column[0] for column in cursor.description), row))


class ProductAutomationService:
    """Local product automation with explicit ownership and dry-run deletion."""

    def __init__(self, manager):
        self.db = manager
        self.init_schema()

    def init_schema(self) -> None:
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.executescript(
                """
                CREATE TABLE IF NOT EXISTS product_filter_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    cookie_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    include_keywords TEXT DEFAULT '[]',
                    exclude_keywords TEXT DEFAULT '[]',
                    min_price REAL,
                    max_price REAL,
                    category TEXT DEFAULT '',
                    daily_limit INTEGER DEFAULT 50,
                    enabled INTEGER DEFAULT 1,
                    today_count INTEGER DEFAULT 0,
                    total_count INTEGER DEFAULT 0,
                    counter_date TEXT,
                    last_run_at TIMESTAMP,
                    last_run_status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (cookie_id) REFERENCES cookies(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS product_materials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    cookie_id TEXT NOT NULL,
                    rule_id INTEGER,
                    source_item_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    price REAL,
                    images TEXT DEFAULT '[]',
                    source_url TEXT DEFAULT '',
                    short_url TEXT DEFAULT '',
                    delivery_content TEXT DEFAULT '',
                    publish_status TEXT DEFAULT 'draft',
                    published_item_id TEXT DEFAULT '',
                    publish_trace_code TEXT DEFAULT '',
                    auto_card_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, cookie_id, source_item_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (cookie_id) REFERENCES cookies(id) ON DELETE CASCADE,
                    FOREIGN KEY (rule_id) REFERENCES product_filter_rules(id) ON DELETE SET NULL,
                    FOREIGN KEY (auto_card_id) REFERENCES cards(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS product_delete_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    cookie_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    min_publish_days INTEGER DEFAULT 30,
                    daily_limit INTEGER DEFAULT 10,
                    skip_reply_activity INTEGER DEFAULT 1,
                    skip_order_activity INTEGER DEFAULT 1,
                    enabled INTEGER DEFAULT 0,
                    execution_mode TEXT DEFAULT 'dry_run',
                    last_run_at TIMESTAMP,
                    last_run_status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, cookie_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (cookie_id) REFERENCES cookies(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS automation_task_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    cookie_id TEXT,
                    task_type TEXT NOT NULL,
                    rule_id INTEGER,
                    execution_mode TEXT DEFAULT 'local',
                    checked_count INTEGER DEFAULT 0,
                    matched_count INTEGER DEFAULT 0,
                    changed_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    summary TEXT DEFAULT '',
                    details TEXT DEFAULT '[]',
                    error_message TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_product_materials_owner
                    ON product_materials(user_id, cookie_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_automation_task_runs_owner
                    ON automation_task_runs(user_id, created_at DESC);
                """
            )
            self.db.conn.commit()

    def _owned_accounts(self, user_id: int) -> Dict[str, str]:
        return self.db.get_all_cookies(user_id) or {}

    def require_account(self, user_id: int, cookie_id: str) -> None:
        if cookie_id not in self._owned_accounts(user_id):
            raise PermissionError("账号不存在或不属于当前用户")

    def _record_run(
        self,
        user_id: int,
        cookie_id: Optional[str],
        task_type: str,
        rule_id: Optional[int],
        mode: str,
        checked: int,
        matched: int,
        changed: int,
        failed: int,
        summary: str,
        details: Optional[List[Dict[str, Any]]] = None,
        error: str = "",
    ) -> int:
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                """
                INSERT INTO automation_task_runs (
                    user_id, cookie_id, task_type, rule_id, execution_mode,
                    checked_count, matched_count, changed_count, failed_count,
                    summary, details, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    cookie_id,
                    task_type,
                    rule_id,
                    mode,
                    checked,
                    matched,
                    changed,
                    failed,
                    summary,
                    json.dumps(details or [], ensure_ascii=False),
                    error,
                ),
            )
            self.db.conn.commit()
            return cursor.lastrowid

    def list_runs(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                """
                SELECT * FROM automation_task_runs
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, max(1, min(limit, 200))),
            )
            rows = [_as_dict(cursor, row) for row in cursor.fetchall()]
        for row in rows:
            row["details"] = _json_value(row.get("details"), [])
        return rows

    def list_materials(self, user_id: int, cookie_id: Optional[str] = None) -> List[Dict[str, Any]]:
        params: List[Any] = [user_id]
        condition = "user_id = ?"
        if cookie_id:
            self.require_account(user_id, cookie_id)
            condition += " AND cookie_id = ?"
            params.append(cookie_id)
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                f"""
                SELECT * FROM product_materials
                WHERE {condition}
                ORDER BY updated_at DESC, id DESC
                """,
                params,
            )
            rows = [_as_dict(cursor, row) for row in cursor.fetchall()]
        for row in rows:
            row["images"] = _json_list(row.get("images"))
        return rows

    def update_material(self, user_id: int, material_id: int, changes: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {
            "title",
            "description",
            "category",
            "price",
            "images",
            "source_url",
            "short_url",
            "delivery_content",
            "publish_status",
            "published_item_id",
            "publish_trace_code",
        }
        updates = []
        params: List[Any] = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            updates.append(f"{key} = ?")
            params.append(json.dumps(value, ensure_ascii=False) if key == "images" else value)
        if not updates:
            raise ValueError("没有可更新的字段")
        params.extend([material_id, user_id])
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                f"""
                UPDATE product_materials
                SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                params,
            )
            if cursor.rowcount == 0:
                raise LookupError("素材不存在")
            self.db.conn.commit()
            cursor.execute(
                "SELECT * FROM product_materials WHERE id = ? AND user_id = ?",
                (material_id, user_id),
            )
            result = _as_dict(cursor, cursor.fetchone())
        result["images"] = _json_list(result.get("images"))
        return result

    def delete_material(self, user_id: int, material_id: int) -> bool:
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                "DELETE FROM product_materials WHERE id = ? AND user_id = ?",
                (material_id, user_id),
            )
            self.db.conn.commit()
            return cursor.rowcount > 0

    def list_filter_rules(self, user_id: int) -> List[Dict[str, Any]]:
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                """
                SELECT * FROM product_filter_rules
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (user_id,),
            )
            rows = [_as_dict(cursor, row) for row in cursor.fetchall()]
        for row in rows:
            row["include_keywords"] = _json_list(row.get("include_keywords"))
            row["exclude_keywords"] = _json_list(row.get("exclude_keywords"))
            row["enabled"] = bool(row.get("enabled"))
        return rows

    def save_filter_rule(
        self, user_id: int, data: Dict[str, Any], rule_id: Optional[int] = None
    ) -> Dict[str, Any]:
        cookie_id = str(data.get("cookie_id") or "").strip()
        self.require_account(user_id, cookie_id)
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("规则名称不能为空")
        values = {
            "cookie_id": cookie_id,
            "name": name,
            "include_keywords": json.dumps(_json_list(data.get("include_keywords")), ensure_ascii=False),
            "exclude_keywords": json.dumps(_json_list(data.get("exclude_keywords")), ensure_ascii=False),
            "min_price": data.get("min_price"),
            "max_price": data.get("max_price"),
            "category": str(data.get("category") or "").strip(),
            "daily_limit": max(1, min(int(data.get("daily_limit") or 50), 1000)),
            "enabled": 1 if data.get("enabled", True) else 0,
        }
        with self.db.lock:
            cursor = self.db.conn.cursor()
            if rule_id is None:
                cursor.execute(
                    """
                    INSERT INTO product_filter_rules (
                        user_id, cookie_id, name, include_keywords, exclude_keywords,
                        min_price, max_price, category, daily_limit, enabled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, *values.values()),
                )
                rule_id = cursor.lastrowid
            else:
                cursor.execute(
                    """
                    UPDATE product_filter_rules SET
                        cookie_id = ?, name = ?, include_keywords = ?,
                        exclude_keywords = ?, min_price = ?, max_price = ?,
                        category = ?, daily_limit = ?, enabled = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ?
                    """,
                    (*values.values(), rule_id, user_id),
                )
                if cursor.rowcount == 0:
                    raise LookupError("筛选规则不存在")
            self.db.conn.commit()
        return next(rule for rule in self.list_filter_rules(user_id) if rule["id"] == rule_id)

    def delete_filter_rule(self, user_id: int, rule_id: int) -> bool:
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                "DELETE FROM product_filter_rules WHERE id = ? AND user_id = ?",
                (rule_id, user_id),
            )
            self.db.conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _price(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
        return float(match.group()) if match else None

    def run_filter_rule(self, user_id: int, rule_id: int) -> Dict[str, Any]:
        rules = [rule for rule in self.list_filter_rules(user_id) if rule["id"] == rule_id]
        if not rules:
            raise LookupError("筛选规则不存在")
        rule = rules[0]
        if not rule["enabled"]:
            raise ValueError("筛选规则未启用")
        self.require_account(user_id, rule["cookie_id"])
        today = datetime.now(timezone.utc).astimezone().date().isoformat()
        used_today = rule["today_count"] if rule.get("counter_date") == today else 0
        remaining = max(0, int(rule["daily_limit"]) - int(used_today or 0))

        items = self.db.get_items_by_cookie(rule["cookie_id"])
        matched: List[Dict[str, Any]] = []
        details: List[Dict[str, Any]] = []
        for item in items:
            title = str(item.get("item_title") or "")
            description = str(item.get("item_description") or item.get("item_detail") or "")
            haystack = f"{title}\n{description}".lower()
            price = self._price(item.get("item_price"))
            include = rule["include_keywords"]
            exclude = rule["exclude_keywords"]
            reason = ""
            if include and not any(keyword.lower() in haystack for keyword in include):
                reason = "未命中包含关键词"
            elif exclude and any(keyword.lower() in haystack for keyword in exclude):
                reason = "命中排除关键词"
            elif rule.get("min_price") is not None and (price is None or price < rule["min_price"]):
                reason = "低于最低价格"
            elif rule.get("max_price") is not None and (price is None or price > rule["max_price"]):
                reason = "高于最高价格"
            elif rule.get("category") and rule["category"].lower() not in str(item.get("item_category") or "").lower():
                reason = "分类不匹配"
            if reason:
                details.append({"item_id": item.get("item_id"), "status": "skipped", "reason": reason})
                continue
            matched.append(item)

        selected = matched[:remaining]
        changed = 0
        with self.db.lock:
            cursor = self.db.conn.cursor()
            for item in selected:
                item_id = str(item.get("item_id") or "")
                image = str(item.get("item_image") or "")
                trace = f"XYB-{item_id[-8:]}"
                cursor.execute(
                    """
                    INSERT INTO product_materials (
                        user_id, cookie_id, rule_id, source_item_id, title,
                        description, category, price, images, source_url,
                        publish_trace_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, cookie_id, source_item_id) DO UPDATE SET
                        rule_id = excluded.rule_id,
                        title = excluded.title,
                        description = CASE
                            WHEN product_materials.description = '' THEN excluded.description
                            ELSE product_materials.description
                        END,
                        category = excluded.category,
                        price = excluded.price,
                        images = CASE
                            WHEN product_materials.images = '[]' THEN excluded.images
                            ELSE product_materials.images
                        END,
                        source_url = excluded.source_url,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        user_id,
                        rule["cookie_id"],
                        rule_id,
                        item_id,
                        item.get("item_title") or f"商品 {item_id}",
                        item.get("item_description") or item.get("item_detail") or "",
                        item.get("item_category") or "",
                        self._price(item.get("item_price")),
                        json.dumps([image] if image else [], ensure_ascii=False),
                        f"https://www.goofish.com/item?id={item_id}",
                        trace,
                    ),
                )
                changed += 1
                details.append({"item_id": item_id, "status": "saved", "reason": "写入素材库"})
            cursor.execute(
                """
                UPDATE product_filter_rules SET
                    today_count = ?, total_count = total_count + ?,
                    counter_date = ?, last_run_at = CURRENT_TIMESTAMP,
                    last_run_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (used_today + changed, changed, today, "success", rule_id, user_id),
            )
            self.db.conn.commit()

        summary = f"检查 {len(items)} 件，匹配 {len(matched)} 件，写入 {changed} 件"
        run_id = self._record_run(
            user_id, rule["cookie_id"], "material_filter", rule_id, "local",
            len(items), len(matched), changed, 0, summary, details,
        )
        return {"run_id": run_id, "summary": summary, "details": details}

    def list_delete_rules(self, user_id: int) -> List[Dict[str, Any]]:
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                """
                SELECT * FROM product_delete_rules
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (user_id,),
            )
            rows = [_as_dict(cursor, row) for row in cursor.fetchall()]
        for row in rows:
            row["enabled"] = bool(row["enabled"])
            row["skip_reply_activity"] = bool(row["skip_reply_activity"])
            row["skip_order_activity"] = bool(row["skip_order_activity"])
        return rows

    def save_delete_rule(
        self, user_id: int, data: Dict[str, Any], rule_id: Optional[int] = None
    ) -> Dict[str, Any]:
        cookie_id = str(data.get("cookie_id") or "").strip()
        self.require_account(user_id, cookie_id)
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("计划名称不能为空")
        mode = str(data.get("execution_mode") or "dry_run")
        if mode != "dry_run":
            raise ValueError("当前版本仅支持 dry_run 预演")
        values = (
            cookie_id,
            name,
            max(1, int(data.get("min_publish_days") or 30)),
            max(1, min(int(data.get("daily_limit") or 10), 200)),
            1 if data.get("skip_reply_activity", True) else 0,
            1 if data.get("skip_order_activity", True) else 0,
            1 if data.get("enabled", False) else 0,
            "dry_run",
        )
        with self.db.lock:
            cursor = self.db.conn.cursor()
            if rule_id is None:
                cursor.execute(
                    """
                    INSERT INTO product_delete_rules (
                        user_id, cookie_id, name, min_publish_days, daily_limit,
                        skip_reply_activity, skip_order_activity, enabled, execution_mode
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, cookie_id) DO UPDATE SET
                        name = excluded.name,
                        min_publish_days = excluded.min_publish_days,
                        daily_limit = excluded.daily_limit,
                        skip_reply_activity = excluded.skip_reply_activity,
                        skip_order_activity = excluded.skip_order_activity,
                        enabled = excluded.enabled,
                        execution_mode = 'dry_run',
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, *values),
                )
                cursor.execute(
                    "SELECT id FROM product_delete_rules WHERE user_id = ? AND cookie_id = ?",
                    (user_id, cookie_id),
                )
                rule_id = cursor.fetchone()[0]
            else:
                cursor.execute(
                    """
                    UPDATE product_delete_rules SET
                        cookie_id = ?, name = ?, min_publish_days = ?, daily_limit = ?,
                        skip_reply_activity = ?, skip_order_activity = ?, enabled = ?,
                        execution_mode = 'dry_run', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ?
                    """,
                    (*values, rule_id, user_id),
                )
                if cursor.rowcount == 0:
                    raise LookupError("删除计划不存在")
            self.db.conn.commit()
        return next(rule for rule in self.list_delete_rules(user_id) if rule["id"] == rule_id)

    def delete_delete_rule(self, user_id: int, rule_id: int) -> bool:
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                "DELETE FROM product_delete_rules WHERE id = ? AND user_id = ?",
                (rule_id, user_id),
            )
            self.db.conn.commit()
            return cursor.rowcount > 0

    def preview_delete_rule(self, user_id: int, rule_id: int) -> Dict[str, Any]:
        rules = [rule for rule in self.list_delete_rules(user_id) if rule["id"] == rule_id]
        if not rules:
            raise LookupError("删除计划不存在")
        rule = rules[0]
        self.require_account(user_id, rule["cookie_id"])
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                """
                SELECT item_id, item_title, created_at,
                       CAST(julianday('now') - julianday(created_at) AS INTEGER) AS age_days
                FROM item_info
                WHERE cookie_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (rule["cookie_id"],),
            )
            items = [_as_dict(cursor, row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT DISTINCT item_id FROM auto_reply_message_logs
                WHERE cookie_id = ? AND item_id IS NOT NULL AND item_id != ''
                """,
                (rule["cookie_id"],),
            )
            replied = {str(row[0]) for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT DISTINCT item_id FROM orders
                WHERE cookie_id = ? AND item_id IS NOT NULL AND item_id != ''
                """,
                (rule["cookie_id"],),
            )
            ordered = {str(row[0]) for row in cursor.fetchall()}

        candidates = []
        skipped = []
        for item in items:
            item_id = str(item["item_id"])
            reason = ""
            if int(item.get("age_days") or 0) < int(rule["min_publish_days"]):
                reason = f"上架不足 {rule['min_publish_days']} 天"
            elif rule["skip_reply_activity"] and item_id in replied:
                reason = "存在自动回复活动"
            elif rule["skip_order_activity"] and item_id in ordered:
                reason = "存在订单记录"
            target = {**item, "reason": reason or "符合预演条件"}
            (skipped if reason else candidates).append(target)
        candidates = candidates[: int(rule["daily_limit"])]
        summary = f"检查 {len(items)} 件，候选 {len(candidates)} 件，跳过 {len(skipped)} 件；未执行真实删除"
        run_id = self._record_run(
            user_id, rule["cookie_id"], "delete_preview", rule_id, "dry_run",
            len(items), len(candidates), 0, 0, summary, candidates + skipped,
        )
        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                """
                UPDATE product_delete_rules SET
                    last_run_at = CURRENT_TIMESTAMP, last_run_status = 'dry_run',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (rule_id, user_id),
            )
            self.db.conn.commit()
        return {
            "run_id": run_id,
            "mode": "dry_run",
            "summary": summary,
            "candidates": candidates,
            "skipped": skipped,
        }

    def repair_published_ids(self, user_id: int) -> Dict[str, Any]:
        materials = self.list_materials(user_id)
        owned = self._owned_accounts(user_id)
        checked = matched = changed = failed = 0
        details = []
        with self.db.lock:
            cursor = self.db.conn.cursor()
            for material in materials:
                if material["cookie_id"] not in owned or material.get("published_item_id"):
                    continue
                trace = str(material.get("publish_trace_code") or "").strip()
                if not trace:
                    continue
                checked += 1
                cursor.execute(
                    """
                    SELECT item_id, item_title FROM item_info
                    WHERE cookie_id = ? AND item_title LIKE ?
                    ORDER BY updated_at DESC LIMIT 2
                    """,
                    (material["cookie_id"], f"%{trace}%"),
                )
                rows = cursor.fetchall()
                if len(rows) == 1:
                    matched += 1
                    cursor.execute(
                        """
                        UPDATE product_materials SET
                            published_item_id = ?, publish_status = 'published',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND user_id = ?
                        """,
                        (str(rows[0][0]), material["id"], user_id),
                    )
                    changed += 1
                    details.append({"material_id": material["id"], "status": "repaired", "item_id": str(rows[0][0])})
                else:
                    details.append({
                        "material_id": material["id"],
                        "status": "skipped",
                        "reason": "未找到唯一匹配的追踪标记",
                    })
            self.db.conn.commit()
        summary = f"检查 {checked} 条，匹配 {matched} 条，回写 {changed} 条"
        run_id = self._record_run(
            user_id, None, "published_id_repair", None, "local",
            checked, matched, changed, failed, summary, details,
        )
        return {"run_id": run_id, "summary": summary, "details": details}

    def repair_short_links(self, user_id: int) -> Dict[str, Any]:
        materials = self.list_materials(user_id)
        checked = matched = changed = 0
        details = []
        with self.db.lock:
            cursor = self.db.conn.cursor()
            for material in materials:
                checked += 1
                link = str(material.get("short_url") or material.get("source_url") or "").strip()
                if not link and material.get("published_item_id"):
                    link = f"https://www.goofish.com/item?id={material['published_item_id']}"
                if not link:
                    details.append({"material_id": material["id"], "status": "skipped", "reason": "没有可用链接"})
                    continue
                matched += 1
                description = str(material.get("description") or "").rstrip()
                marker = "购买链接："
                new_description = re.sub(r"(?:\n|^)?购买链接：\S+", "", description).rstrip()
                new_description = f"{new_description}\n{marker}{link}".strip()
                if new_description == description:
                    details.append({"material_id": material["id"], "status": "unchanged"})
                    continue
                cursor.execute(
                    """
                    UPDATE product_materials SET
                        description = ?, short_url = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND user_id = ?
                    """,
                    (new_description, link, material["id"], user_id),
                )
                changed += 1
                details.append({"material_id": material["id"], "status": "repaired", "url": link})
            self.db.conn.commit()
        summary = f"检查 {checked} 条，可修复 {matched} 条，更新 {changed} 条"
        run_id = self._record_run(
            user_id, None, "short_link_repair", None, "local",
            checked, matched, changed, 0, summary, details,
        )
        return {"run_id": run_id, "summary": summary, "details": details}

    def compensate_cards(self, user_id: int) -> Dict[str, Any]:
        materials = self.list_materials(user_id)
        cards = self.db.get_all_cards(user_id)
        rules = self.db.get_all_delivery_rules(user_id)
        checked = matched = changed = failed = 0
        details = []
        card_by_id = {card["id"]: card for card in cards}
        rule_by_keyword = {str(rule.get("keyword") or ""): rule for rule in rules}
        for material in materials:
            item_id = str(material.get("published_item_id") or "").strip()
            content = str(material.get("delivery_content") or "").strip()
            if not item_id or not content:
                continue
            checked += 1
            try:
                card_id = material.get("auto_card_id")
                card = card_by_id.get(card_id)
                if not card:
                    name = f"素材发货-{item_id}"
                    existing = next(
                        (
                            item for item in cards
                            if item.get("name") == name
                            and item.get("type") == "text"
                            and item.get("text_content") == content
                        ),
                        None,
                    )
                    if existing:
                        card_id = existing["id"]
                    else:
                        card_id = self.db.create_card(
                            name=name,
                            card_type="text",
                            text_content=content,
                            description=f"商品自动化补偿，精确绑定商品 {item_id}",
                            enabled=True,
                            user_id=user_id,
                        )
                        cards.append(self.db.get_card_by_id(card_id, user_id))
                    with self.db.lock:
                        cursor = self.db.conn.cursor()
                        cursor.execute(
                            """
                            UPDATE product_materials SET auto_card_id = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ? AND user_id = ?
                            """,
                            (card_id, material["id"], user_id),
                        )
                        self.db.conn.commit()
                    changed += 1
                if item_id not in rule_by_keyword:
                    rule_id = self.db.create_delivery_rule(
                        keyword=item_id,
                        card_id=card_id,
                        delivery_count=1,
                        enabled=True,
                        description=f"素材自动补偿：{material['title']}",
                        user_id=user_id,
                    )
                    rule_by_keyword[item_id] = {"id": rule_id, "keyword": item_id, "card_id": card_id}
                    changed += 1
                matched += 1
                details.append({"material_id": material["id"], "status": "bound", "item_id": item_id, "card_id": card_id})
            except Exception as exc:
                failed += 1
                logger.exception("素材卡券补偿失败")
                details.append({"material_id": material["id"], "status": "failed", "reason": str(exc)})
        summary = f"检查 {checked} 条，完成绑定 {matched} 条，新增或修复 {changed} 项，失败 {failed} 项"
        run_id = self._record_run(
            user_id, None, "card_compensation", None, "local",
            checked, matched, changed, failed, summary, details,
        )
        return {"run_id": run_id, "summary": summary, "details": details}
