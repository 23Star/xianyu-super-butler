"""Local delivery-block rule storage and evaluation."""

from __future__ import annotations

import json
from typing import Any, Optional

from loguru import logger


RULE_METADATA: tuple[dict[str, Any], ...] = (
    {
        "rule_code": "personal_blacklist",
        "rule_name": "个人黑名单",
        "rule_description": "按商品、账号或当前系统用户范围拦截指定买家",
        "default_config": {},
        "default_priority": 5,
    },
    {
        "rule_code": "buyer_credit_zero",
        "rule_name": "买家信用度检查",
        "rule_description": "检查买家被评价总数，评价数不高于设定阈值时拦截发货",
        "default_config": {"threshold": 0},
        "default_priority": 10,
    },
    {
        "rule_code": "buyer_has_order",
        "rule_name": "买家已有订单",
        "rule_description": "买家在当前账号存在其他有效订单时拦截发货",
        "default_config": {"same_item_only": False},
        "default_priority": 20,
    },
    {
        "rule_code": "buyer_has_order_global",
        "rule_name": "买家跨账号已有订单",
        "rule_description": "买家在当前系统用户的任一闲鱼账号存在其他有效订单时拦截发货",
        "default_config": {"same_item_only": False},
        "default_priority": 25,
    },
    {
        "rule_code": "buyer_unconfirmed",
        "rule_name": "买家存在未确认收货订单",
        "rule_description": "买家在当前账号存在达到阈值的已发货订单时拦截发货",
        "default_config": {"min_count": 1, "same_item_only": False},
        "default_priority": 30,
    },
)

RULE_METADATA_BY_CODE = {item["rule_code"]: item for item in RULE_METADATA}
IGNORED_EXISTING_ORDER_STATUSES = ("cancelled", "refunding", "refund_cancelled")


def resolve_delivery_action(block_result: dict[str, Any], order_closed: bool = False) -> str:
    """Convert a rule result and close-order outcome into the delivery action."""
    if not block_result.get("hit"):
        return "allow"
    if (
        block_result.get("auto_close_order")
        and order_closed
        and block_result.get("only_card_after_close")
    ):
        return "card_only"
    return "block"


def _decode_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return decoded if isinstance(decoded, type(fallback)) else fallback


class DeliveryBlockRuleService:
    def __init__(self, db_manager: Any):
        self.db = db_manager

    def list_rules(self, account_id: str) -> list[dict[str, Any]]:
        stored = {}
        with self.db.lock:
            cursor = self.db.conn.execute(
                """
                SELECT rule_code, enabled, priority, block_reason,
                       auto_close_order, only_card_after_close,
                       excluded_item_ids, config
                FROM delivery_block_rules
                WHERE account_id = ?
                """,
                (account_id,),
            )
            for row in cursor.fetchall():
                stored[row[0]] = row

        rules = []
        for meta in RULE_METADATA:
            row = stored.get(meta["rule_code"])
            auto_close_order = bool(row[4]) if row else False
            rules.append(
                {
                    **meta,
                    "enabled": bool(row[1]) if row else False,
                    "priority": row[2] if row else meta["default_priority"],
                    "block_reason": (row[3] or "") if row else "",
                    "auto_close_order": auto_close_order,
                    "only_card_after_close": bool(row[5]) if row and auto_close_order else False,
                    "excluded_item_ids": _decode_json(row[6], []) if row else [],
                    "config": _decode_json(row[7], meta["default_config"].copy()) if row else meta["default_config"].copy(),
                }
            )
        return sorted(rules, key=lambda item: (item["priority"], item["rule_code"]))

    def update_rule(self, account_id: str, rule_code: str, changes: dict[str, Any]) -> dict[str, Any]:
        meta = RULE_METADATA_BY_CODE.get(rule_code)
        if not meta:
            raise ValueError(f"不支持的规则: {rule_code}")

        current = next(item for item in self.list_rules(account_id) if item["rule_code"] == rule_code)
        merged = {**current, **changes}
        if merged.get("priority") is None:
            raise ValueError("priority 不能为空")
        if merged.get("excluded_item_ids") is None:
            raise ValueError("excluded_item_ids 不能为空")
        excluded_item_ids = [
            str(item).strip()
            for item in merged.get("excluded_item_ids", [])
            if str(item).strip()
        ]
        config = merged.get("config") or {}
        if not isinstance(config, dict):
            raise ValueError("config 必须是对象")
        auto_close_order = bool(merged.get("auto_close_order"))
        only_card_after_close = bool(merged.get("only_card_after_close")) if auto_close_order else False

        with self.db.lock:
            self.db.conn.execute(
                """
                INSERT INTO delivery_block_rules (
                    account_id, rule_code, enabled, priority, block_reason,
                    auto_close_order, only_card_after_close,
                    excluded_item_ids, config, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(account_id, rule_code) DO UPDATE SET
                    enabled = excluded.enabled,
                    priority = excluded.priority,
                    block_reason = excluded.block_reason,
                    auto_close_order = excluded.auto_close_order,
                    only_card_after_close = excluded.only_card_after_close,
                    excluded_item_ids = excluded.excluded_item_ids,
                    config = excluded.config,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    account_id,
                    rule_code,
                    int(bool(merged.get("enabled"))),
                    int(merged.get("priority", meta["default_priority"])),
                    str(merged.get("block_reason") or "").strip(),
                    int(auto_close_order),
                    int(only_card_after_close),
                    json.dumps(excluded_item_ids, ensure_ascii=False),
                    json.dumps(config, ensure_ascii=False),
                ),
            )
            self.db.conn.commit()
        return next(item for item in self.list_rules(account_id) if item["rule_code"] == rule_code)

    def list_blacklist(self, owner_id: int, account_id: Optional[str] = None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, owner_id, account_id, buyer_id, buyer_nick, item_id,
                   reason, is_enabled, created_at, updated_at
            FROM personal_blacklist
            WHERE owner_id = ?
        """
        params: list[Any] = [owner_id]
        if account_id:
            sql += " AND (account_id = ? OR account_id IS NULL)"
            params.append(account_id)
        sql += " ORDER BY id DESC"
        with self.db.lock:
            rows = self.db.conn.execute(sql, params).fetchall()
        return [self._blacklist_row(row) for row in rows]

    def add_blacklist(self, owner_id: int, data: dict[str, Any]) -> dict[str, Any]:
        buyer_id = str(data.get("buyer_id") or "").strip()
        if not buyer_id:
            raise ValueError("buyer_id 不能为空")
        account_id = str(data.get("account_id") or "").strip() or None
        item_id = str(data.get("item_id") or "").strip() or None
        if item_id and not account_id:
            raise ValueError("商品级黑名单必须指定 account_id")

        with self.db.lock:
            cursor = self.db.conn.execute(
                """
                INSERT INTO personal_blacklist (
                    owner_id, account_id, buyer_id, buyer_nick,
                    item_id, reason, is_enabled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_id,
                    account_id,
                    buyer_id,
                    str(data.get("buyer_nick") or "").strip(),
                    item_id,
                    str(data.get("reason") or "").strip(),
                    int(bool(data.get("is_enabled", True))),
                ),
            )
            self.db.conn.commit()
            row = self.db.conn.execute(
                """
                SELECT id, owner_id, account_id, buyer_id, buyer_nick, item_id,
                       reason, is_enabled, created_at, updated_at
                FROM personal_blacklist WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return self._blacklist_row(row)

    def update_blacklist(self, owner_id: int, entry_id: int, changes: dict[str, Any]) -> Optional[dict[str, Any]]:
        current = self.get_blacklist(owner_id, entry_id)
        if not current:
            return None
        proposed_buyer_id = changes.get("buyer_id", current["buyer_id"])
        if not str(proposed_buyer_id or "").strip():
            raise ValueError("buyer_id 不能为空")
        proposed_account_id = changes.get("account_id", current["account_id"])
        proposed_item_id = changes.get("item_id", current["item_id"])
        if str(proposed_item_id or "").strip() and not str(proposed_account_id or "").strip():
            raise ValueError("商品级黑名单必须指定 account_id")

        allowed = {"account_id", "buyer_id", "buyer_nick", "item_id", "reason", "is_enabled"}
        assignments = []
        values: list[Any] = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == "is_enabled":
                value = int(bool(value))
            elif key in {"account_id", "item_id"}:
                value = str(value or "").strip() or None
            else:
                value = str(value or "").strip()
            assignments.append(f"{key} = ?")
            values.append(value)
        if not assignments:
            return current

        with self.db.lock:
            values.extend([owner_id, entry_id])
            self.db.conn.execute(
                f"UPDATE personal_blacklist SET {', '.join(assignments)}, updated_at = CURRENT_TIMESTAMP "
                "WHERE owner_id = ? AND id = ?",
                values,
            )
            self.db.conn.commit()
        return self.get_blacklist(owner_id, entry_id)

    def get_blacklist(self, owner_id: int, entry_id: int) -> Optional[dict[str, Any]]:
        with self.db.lock:
            row = self.db.conn.execute(
                """
                SELECT id, owner_id, account_id, buyer_id, buyer_nick, item_id,
                       reason, is_enabled, created_at, updated_at
                FROM personal_blacklist WHERE owner_id = ? AND id = ?
                """,
                (owner_id, entry_id),
            ).fetchone()
        return self._blacklist_row(row) if row else None

    def delete_blacklist(self, owner_id: int, entry_id: int) -> bool:
        with self.db.lock:
            cursor = self.db.conn.execute(
                "DELETE FROM personal_blacklist WHERE owner_id = ? AND id = ?",
                (owner_id, entry_id),
            )
            self.db.conn.commit()
        return cursor.rowcount > 0

    def evaluate(
        self,
        account_id: str,
        order_id: str,
        buyer_id: str,
        item_id: Optional[str] = None,
        owner_id: Optional[int] = None,
        buyer_rating_count: Optional[int] = None,
    ) -> dict[str, Any]:
        allowed = {
            "hit": False,
            "rule_code": None,
            "rule_name": None,
            "reason": "",
            "block_reason": "",
            "auto_close_order": False,
            "only_card_after_close": False,
            "extra_data": {},
        }
        if not account_id or not order_id or not buyer_id:
            return allowed

        if owner_id is None:
            details = self.db.get_cookie_details(account_id)
            owner_id = details.get("user_id") if details else None

        try:
            for rule in self.list_rules(account_id):
                if not rule["enabled"]:
                    continue
                if item_id and str(item_id) in set(rule["excluded_item_ids"]):
                    continue
                result = self._evaluate_rule(
                    rule["rule_code"],
                    account_id,
                    order_id,
                    buyer_id,
                    item_id,
                    owner_id,
                    rule["config"],
                    buyer_rating_count,
                )
                if result:
                    logger.warning(
                        f"【{account_id}】发货被规则 {rule['rule_code']} 拦截: "
                        f"order_id={order_id}, buyer_id={buyer_id}, reason={result['reason']}"
                    )
                    return {
                        "hit": True,
                        "rule_code": rule["rule_code"],
                        "rule_name": rule["rule_name"],
                        "reason": result["reason"],
                        "block_reason": rule["block_reason"],
                        "auto_close_order": rule["auto_close_order"],
                        "only_card_after_close": rule["only_card_after_close"],
                        "extra_data": result.get("extra_data", {}),
                    }
        except Exception as exc:
            logger.error(f"【{account_id}】发货拦截规则执行失败，按放行处理: {exc}")
        return allowed

    def _evaluate_rule(
        self,
        rule_code: str,
        account_id: str,
        order_id: str,
        buyer_id: str,
        item_id: Optional[str],
        owner_id: Optional[int],
        config: dict[str, Any],
        buyer_rating_count: Optional[int],
    ) -> Optional[dict[str, Any]]:
        if rule_code == "personal_blacklist":
            return self._check_blacklist(account_id, buyer_id, item_id, owner_id)
        if rule_code == "buyer_credit_zero":
            if buyer_rating_count is None or buyer_rating_count < 0:
                return None
            try:
                threshold = max(0, int(config.get("threshold", 0)))
            except (TypeError, ValueError):
                threshold = 0
            if buyer_rating_count <= threshold:
                return {
                    "reason": f"买家评价数为 {buyer_rating_count}（阈值 {threshold}）",
                    "extra_data": {
                        "total_count": buyer_rating_count,
                        "threshold": threshold,
                    },
                }
        if rule_code == "buyer_has_order":
            count = self._count_orders(account_id, order_id, buyer_id, item_id, config)
            if count:
                return {"reason": f"买家在当前账号已有 {count} 笔其他有效订单", "extra_data": {"order_count": count}}
        if rule_code == "buyer_has_order_global" and owner_id is not None:
            count = self._count_orders_global(owner_id, order_id, buyer_id, item_id, config)
            if count:
                return {"reason": f"买家在当前用户的账号中已有 {count} 笔其他有效订单", "extra_data": {"order_count": count}}
        if rule_code == "buyer_unconfirmed":
            count = self._count_unconfirmed(account_id, order_id, buyer_id, item_id, config)
            min_count = max(1, int(config.get("min_count", 1)))
            if count >= min_count:
                return {
                    "reason": f"买家有 {count} 笔未确认收货订单",
                    "extra_data": {"unconfirmed_count": count, "min_count": min_count},
                }
        return None

    def _check_blacklist(
        self, account_id: str, buyer_id: str, item_id: Optional[str], owner_id: Optional[int]
    ) -> Optional[dict[str, Any]]:
        if owner_id is None:
            return None
        with self.db.lock:
            rows = self.db.conn.execute(
                """
                SELECT id, account_id, item_id, reason
                FROM personal_blacklist
                WHERE owner_id = ? AND buyer_id = ? AND is_enabled = 1
                  AND (
                    (account_id = ? AND item_id = ?)
                    OR (account_id = ? AND item_id IS NULL)
                    OR (account_id IS NULL AND item_id IS NULL)
                  )
                ORDER BY
                  CASE
                    WHEN account_id = ? AND item_id = ? THEN 1
                    WHEN account_id = ? AND item_id IS NULL THEN 2
                    ELSE 3
                  END
                LIMIT 1
                """,
                (owner_id, buyer_id, account_id, item_id, account_id, account_id, item_id, account_id),
            ).fetchone()
        if not rows:
            return None
        level = "商品级" if rows[1] and rows[2] else ("账号级" if rows[1] else "用户级")
        reason = f"买家命中{level}个人黑名单"
        if rows[3]:
            reason += f"：{rows[3]}"
        return {"reason": reason, "extra_data": {"blacklist_id": rows[0], "level": level}}

    def _count_orders(
        self, account_id: str, order_id: str, buyer_id: str, item_id: Optional[str], config: dict[str, Any]
    ) -> int:
        sql = """
            SELECT COUNT(*) FROM orders
            WHERE cookie_id = ? AND buyer_id = ? AND order_id != ?
              AND order_status NOT IN (?, ?, ?)
        """
        params: list[Any] = [account_id, buyer_id, order_id, *IGNORED_EXISTING_ORDER_STATUSES]
        if config.get("same_item_only") and item_id:
            sql += " AND item_id = ?"
            params.append(item_id)
        with self.db.lock:
            return int(self.db.conn.execute(sql, params).fetchone()[0] or 0)

    def _count_orders_global(
        self, owner_id: int, order_id: str, buyer_id: str, item_id: Optional[str], config: dict[str, Any]
    ) -> int:
        sql = """
            SELECT COUNT(*) FROM orders
            INNER JOIN cookies ON cookies.id = orders.cookie_id
            WHERE cookies.user_id = ? AND orders.buyer_id = ? AND orders.order_id != ?
              AND orders.order_status NOT IN (?, ?, ?)
        """
        params: list[Any] = [owner_id, buyer_id, order_id, *IGNORED_EXISTING_ORDER_STATUSES]
        if config.get("same_item_only") and item_id:
            sql += " AND orders.item_id = ?"
            params.append(item_id)
        with self.db.lock:
            return int(self.db.conn.execute(sql, params).fetchone()[0] or 0)

    def _count_unconfirmed(
        self, account_id: str, order_id: str, buyer_id: str, item_id: Optional[str], config: dict[str, Any]
    ) -> int:
        sql = """
            SELECT COUNT(*) FROM orders
            WHERE cookie_id = ? AND buyer_id = ? AND order_id != ? AND order_status = 'shipped'
        """
        params: list[Any] = [account_id, buyer_id, order_id]
        if config.get("same_item_only") and item_id:
            sql += " AND item_id = ?"
            params.append(item_id)
        with self.db.lock:
            return int(self.db.conn.execute(sql, params).fetchone()[0] or 0)

    @staticmethod
    def _blacklist_row(row: Any) -> dict[str, Any]:
        return {
            "id": row[0],
            "owner_id": row[1],
            "account_id": row[2],
            "buyer_id": row[3],
            "buyer_nick": row[4] or "",
            "item_id": row[5],
            "reason": row[6] or "",
            "is_enabled": bool(row[7]),
            "created_at": row[8],
            "updated_at": row[9],
        }
