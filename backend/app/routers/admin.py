"""管理员后台：用户管理 + 全局审计 + 首页统计。"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..schemas import DataResponse
from ..services import auth_service as auth
from ..services.audit_service import audit as audit_inst
from ..deps import get_current_admin

router = APIRouter()


def _ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


def _ua(request: Request) -> str:
    return request.headers.get("User-Agent", "")[:255]


# ============== 请求模型 ==============
class SetAdminReq(BaseModel):
    is_admin: bool


class SetActiveReq(BaseModel):
    is_active: bool


class ResetPwdReq(BaseModel):
    new_password: str = Field(..., min_length=6)


# ============== 首页统计 ==============
@router.get("/stats", response_model=DataResponse)
async def admin_stats(admin: Dict[str, Any] = Depends(get_current_admin)):
    """管理员后台首页统计：用户数 / 今日活跃 / 操作总数 / 失败数。"""
    with auth.auth_db()._conn() as c:
        total_users = int(c.execute("SELECT COUNT(1) AS n FROM users").fetchone()["n"])
        admin_cnt = int(c.execute("SELECT COUNT(1) AS n FROM users WHERE is_admin=1").fetchone()["n"])
        active_cnt = int(c.execute(
            "SELECT COUNT(1) AS n FROM users WHERE is_active=1").fetchone()["n"])
    aud = audit_inst()
    with aud._conn() as c:
        total_ops = int(c.execute("SELECT COUNT(1) AS n FROM audit_logs").fetchone()["n"])
        fail_ops = int(c.execute("SELECT COUNT(1) AS n FROM audit_logs WHERE ok=0").fetchone()["n"])
        today_login = int(c.execute(
            "SELECT COUNT(1) AS n FROM audit_logs WHERE category='auth.login' "
            "AND ok=1 AND date(created_at)=date('now','localtime')").fetchone()["n"])
        # 最近 7 天每日操作数
        rows7 = c.execute(
            "SELECT date(created_at) AS d, COUNT(1) AS n, "
            "SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) ok_n "
            "FROM audit_logs WHERE created_at>=datetime('now','localtime','-7 days') "
            "GROUP BY date(created_at) ORDER BY d DESC").fetchall()
        # 操作分类分布 Top 10
        cat_rows = c.execute(
            "SELECT category, COUNT(1) AS n FROM audit_logs "
            "GROUP BY category ORDER BY n DESC LIMIT 10").fetchall()
    return DataResponse(data={
        "users": {"total": total_users, "admins": admin_cnt, "active": active_cnt},
        "operations": {"total": total_ops, "failed": fail_ops, "today_login": today_login},
        "last_7_days": [dict(r) for r in rows7],
        "category_top": [dict(r) for r in cat_rows],
    })


# ============== 用户管理 ==============
@router.get("/users", response_model=DataResponse)
async def admin_list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str = Query("", max_length=64),
    admin_only: bool = Query(False),
    admin: Dict[str, Any] = Depends(get_current_admin),
):
    data = auth.list_users(page=page, page_size=page_size, keyword=keyword, admin_only=admin_only)
    return DataResponse(data=data)


@router.put("/users/{user_id}/admin", response_model=DataResponse)
async def admin_set_admin(user_id: int, payload: SetAdminReq, request: Request,
                          admin: Dict[str, Any] = Depends(get_current_admin)):
    if user_id == int(admin["id"]) and not payload.is_admin:
        raise HTTPException(400, "不能取消自己的管理员权限")
    ok, msg = auth.admin_set_user_admin(user_id, payload.is_admin)
    audit_inst().log(
        user_id=int(admin["id"]), username=admin.get("username"),
        category="admin.user", action=f"{'设置' if payload.is_admin else '取消'}管理员: user_id={user_id}",
        ok=ok, target_key=str(user_id), detail={"is_admin": payload.is_admin, "msg": msg},
        ip=_ip(request), ua=_ua(request),
    )
    if not ok:
        raise HTTPException(400, detail=msg)
    return DataResponse(message=msg)


@router.put("/users/{user_id}/active", response_model=DataResponse)
async def admin_set_active(user_id: int, payload: SetActiveReq, request: Request,
                            admin: Dict[str, Any] = Depends(get_current_admin)):
    if user_id == int(admin["id"]) and not payload.is_active:
        raise HTTPException(400, "不能停用自己的账号")
    ok, msg = auth.admin_set_user_active(user_id, payload.is_active)
    audit_inst().log(
        user_id=int(admin["id"]), username=admin.get("username"),
        category="admin.user", action=f"{'启用' if payload.is_active else '停用'}账号: user_id={user_id}",
        ok=ok, target_key=str(user_id), detail={"is_active": payload.is_active, "msg": msg},
        ip=_ip(request), ua=_ua(request),
    )
    if not ok:
        raise HTTPException(400, detail=msg)
    return DataResponse(message=msg)


@router.post("/users/{user_id}/reset-password", response_model=DataResponse)
async def admin_reset_pwd(user_id: int, payload: ResetPwdReq, request: Request,
                          admin: Dict[str, Any] = Depends(get_current_admin)):
    ok, msg = auth.admin_reset_password(user_id, payload.new_password)
    audit_inst().log(
        user_id=int(admin["id"]), username=admin.get("username"),
        category="admin.user", action=f"重置密码: user_id={user_id}",
        ok=ok, target_key=str(user_id), detail={"msg": msg},
        ip=_ip(request), ua=_ua(request),
    )
    if not ok:
        raise HTTPException(400, detail=msg)
    return DataResponse(message=msg)


@router.delete("/users/{user_id}", response_model=DataResponse)
async def admin_delete_user(user_id: int, request: Request,
                            admin: Dict[str, Any] = Depends(get_current_admin)):
    if user_id == int(admin["id"]):
        raise HTTPException(400, "不能删除自己")
    ok, msg = auth.admin_delete_user(user_id)
    audit_inst().log(
        user_id=int(admin["id"]), username=admin.get("username"),
        category="admin.user", action=f"删除用户: user_id={user_id}",
        ok=ok, target_key=str(user_id), detail={"msg": msg},
        ip=_ip(request), ua=_ua(request),
    )
    if not ok:
        raise HTTPException(400, detail=msg)
    return DataResponse(message=msg)


# ============== 全局审计 ==============
@router.get("/audit/history", response_model=DataResponse)
async def admin_audit_history(
    user_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    only_errors: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    admin: Dict[str, Any] = Depends(get_current_admin),
):
    aud = audit_inst()
    data = aud.list_history(
        user_id=user_id, category=category, only_errors=only_errors,
        page=page, page_size=page_size,
    )
    return DataResponse(data=data)


@router.get("/audit/detail/{audit_id}", response_model=DataResponse)
async def admin_audit_detail(audit_id: int,
                             admin: Dict[str, Any] = Depends(get_current_admin)):
    aud = audit_inst()
    with aud._conn() as c:
        row = c.execute("SELECT * FROM audit_logs WHERE id=?", (audit_id,)).fetchone()
        if not row:
            raise HTTPException(404, "记录不存在")
        d = dict(row)
        raw = d.get("detail")
        if raw:
            try:
                d["detail"] = json.loads(raw)
            except Exception:
                pass
    return DataResponse(data=d)


@router.get("/audit/failed", response_model=DataResponse)
async def admin_audit_failed(
    limit: int = Query(20, ge=1, le=200),
    admin: Dict[str, Any] = Depends(get_current_admin),
):
    rows = audit_inst().recent_failed(user_id=None, limit=limit)
    return DataResponse(data={"rows": rows, "count": len(rows)})
