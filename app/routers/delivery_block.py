"""Authenticated management API for delivery-block rules."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.delivery_block_rules import DeliveryBlockRuleService, RULE_METADATA


class RuleUpdate(BaseModel):
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=0, le=999)
    block_reason: Optional[str] = Field(default=None, max_length=500)
    auto_close_order: Optional[bool] = None
    only_card_after_close: Optional[bool] = None
    excluded_item_ids: Optional[list[str]] = None
    config: Optional[dict[str, Any]] = None


class BlacklistCreate(BaseModel):
    account_id: Optional[str] = None
    buyer_id: str = Field(min_length=1, max_length=64)
    buyer_nick: str = Field(default="", max_length=120)
    item_id: Optional[str] = None
    reason: str = Field(default="", max_length=500)
    is_enabled: bool = True


class BlacklistUpdate(BaseModel):
    account_id: Optional[str] = None
    buyer_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    buyer_nick: Optional[str] = Field(default=None, max_length=120)
    item_id: Optional[str] = None
    reason: Optional[str] = Field(default=None, max_length=500)
    is_enabled: Optional[bool] = None


def create_delivery_block_router(
    get_current_user: Callable[..., dict[str, Any]],
    db_manager: Any,
) -> APIRouter:
    router = APIRouter()
    service = DeliveryBlockRuleService(db_manager)

    def require_account(cookie_id: str, current_user: dict[str, Any]) -> dict[str, Any]:
        details = db_manager.get_cookie_details(cookie_id)
        if not details or details.get("user_id") != current_user["user_id"]:
            raise HTTPException(status_code=404, detail="账号不存在或无权限")
        return details

    @router.get("/delivery-block-rules/metadata")
    def get_rule_metadata(current_user: dict[str, Any] = Depends(get_current_user)):
        return {"success": True, "rules": list(RULE_METADATA)}

    @router.get("/delivery-block-rules/{cookie_id}")
    def get_rules(cookie_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
        require_account(cookie_id, current_user)
        return {"success": True, "rules": service.list_rules(cookie_id)}

    @router.put("/delivery-block-rules/{cookie_id}/{rule_code}")
    def update_rule(
        cookie_id: str,
        rule_code: str,
        update: RuleUpdate,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        require_account(cookie_id, current_user)
        try:
            rule = service.update_rule(cookie_id, rule_code, update.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, "rule": rule}

    @router.get("/blacklist")
    def get_blacklist(
        cookie_id: Optional[str] = Query(default=None),
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        if cookie_id:
            require_account(cookie_id, current_user)
        return {
            "success": True,
            "entries": service.list_blacklist(current_user["user_id"], cookie_id),
        }

    @router.post("/blacklist")
    def create_blacklist(
        item: BlacklistCreate,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        if item.account_id:
            require_account(item.account_id, current_user)
        try:
            entry = service.add_blacklist(current_user["user_id"], item.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"success": True, "entry": entry}

    @router.put("/blacklist/{entry_id}")
    def update_blacklist(
        entry_id: int,
        item: BlacklistUpdate,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        changes = item.model_dump(exclude_unset=True)
        if changes.get("account_id"):
            require_account(changes["account_id"], current_user)
        try:
            entry = service.update_blacklist(current_user["user_id"], entry_id, changes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not entry:
            raise HTTPException(status_code=404, detail="黑名单记录不存在")
        return {"success": True, "entry": entry}

    @router.delete("/blacklist/{entry_id}")
    def delete_blacklist(
        entry_id: int,
        current_user: dict[str, Any] = Depends(get_current_user),
    ):
        if not service.delete_blacklist(current_user["user_id"], entry_id):
            raise HTTPException(status_code=404, detail="黑名单记录不存在")
        return {"success": True}

    return router
