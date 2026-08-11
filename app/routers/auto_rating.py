from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auto_rate_task import rate_order_once, run_auto_rate_batch


class AutoRatingSettingsUpdate(BaseModel):
    enabled: bool


class CommentTemplateUpdate(BaseModel):
    name: str = Field(default="默认好评", max_length=80)
    content: str = Field(min_length=1, max_length=500)


class ManualRateRequest(BaseModel):
    cookie_id: str
    comment: Optional[str] = Field(default=None, max_length=500)


def create_auto_rating_router(get_current_user: Callable, db_manager: Any) -> APIRouter:
    router = APIRouter(prefix="/api/auto-rating", tags=["auto-rating"])

    def ensure_account(user: Dict[str, Any], cookie_id: str) -> None:
        if cookie_id not in db_manager.get_all_cookies(user["user_id"]):
            raise HTTPException(status_code=403, detail="无权操作该账号")

    @router.get("/accounts/{cookie_id}")
    def get_settings(cookie_id: str, user=Depends(get_current_user)):
        ensure_account(user, cookie_id)
        return {
            "enabled": db_manager.get_auto_comment(cookie_id),
            "template": db_manager.get_active_comment_template(cookie_id),
            "templates": db_manager.get_comment_templates(cookie_id),
        }

    @router.put("/accounts/{cookie_id}")
    def update_settings(cookie_id: str, payload: AutoRatingSettingsUpdate, user=Depends(get_current_user)):
        ensure_account(user, cookie_id)
        if payload.enabled and not db_manager.get_active_comment_template(cookie_id):
            raise HTTPException(status_code=400, detail="请先保存评价模板，再开启自动评价")
        if not db_manager.update_auto_comment(cookie_id, payload.enabled):
            raise HTTPException(status_code=500, detail="自动评价设置保存失败")
        return {"success": True, "enabled": payload.enabled}

    @router.put("/accounts/{cookie_id}/template")
    def save_template(cookie_id: str, payload: CommentTemplateUpdate, user=Depends(get_current_user)):
        ensure_account(user, cookie_id)
        template_id = db_manager.save_active_comment_template(
            cookie_id, payload.name.strip() or "默认好评", payload.content.strip()
        )
        return {"success": True, "template_id": template_id,
                "template": db_manager.get_active_comment_template(cookie_id)}

    @router.post("/run")
    async def run_once(user=Depends(get_current_user)):
        # 调度器内部会遍历所有账号；这里显式限制为当前用户的已开启账号。
        allowed = set(db_manager.get_all_cookies(user["user_id"]))
        result = await run_auto_rate_batch(allowed_cookie_ids=allowed)
        return {"success": True, "data": result}

    @router.post("/orders/{order_id}")
    async def rate_order(order_id: str, payload: ManualRateRequest, user=Depends(get_current_user)):
        ensure_account(user, payload.cookie_id)
        order = db_manager.get_order_by_id(order_id)
        if not order or str(order.get("cookie_id") or "") != payload.cookie_id:
            raise HTTPException(status_code=404, detail="订单不存在或不属于该账号")
        result = await rate_order_once(payload.cookie_id, order_id, payload.comment, source="manual")
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message") or "评价失败")
        return result

    @router.get("/logs")
    def logs(cookie_id: Optional[str] = None, limit: int = Query(50, ge=1, le=500),
             offset: int = Query(0, ge=0), user=Depends(get_current_user)):
        if cookie_id:
            ensure_account(user, cookie_id)
        return {"success": True, "data": db_manager.get_scheduled_rate_logs(
            user_id=user["user_id"], cookie_id=cookie_id, limit=limit, offset=offset
        )}

    return router
