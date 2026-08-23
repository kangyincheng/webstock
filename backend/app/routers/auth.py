"""登录/注册/刷新/登出/改密/当前用户。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status, Form
from pydantic import BaseModel, EmailStr, Field

from ..schemas import DataResponse
from ..services import auth_service as auth
from ..services.audit_service import (audit as audit_inst,
                                      CATEGORY_LOGIN, CATEGORY_LOGOUT,
                                      CATEGORY_REGISTER, CATEGORY_CHANGE_PASSWORD)
from ..deps import get_current_user, get_current_user_or_none

router = APIRouter()


# ============== 请求模型 ==============
class RegisterReq(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    email: Optional[str] = Field(default=None, max_length=128)
    nickname: Optional[str] = Field(default=None, max_length=64)


class LoginReq(BaseModel):
    username: str
    password: str


class ChangePwdReq(BaseModel):
    old_password: str = Field(..., min_length=6)
    new_password: str = Field(..., min_length=6)


def _ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


def _ua(request: Request) -> str:
    return request.headers.get("User-Agent", "")[:255]


# ============== 公共：/me（既用于登录态回显，也返回上次操作 + 最近历史）==============
@router.get("/me", response_model=DataResponse)
async def me(request: Request,
             user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    """未登录：返回 {auth: false}；登录：返回用户资料 + 上次操作 + 最近 5 条历史。"""
    if not user:
        return DataResponse(data={"auth": False, "user": None})
    aud = audit_inst()
    last = aud.last_action(int(user["id"]))
    recent = aud.list_history(user_id=int(user["id"]), page=1, page_size=5)["rows"]
    return DataResponse(data={
        "auth": True,
        "user": user,
        "last_action": last,
        "recent_history": recent,
    })


# ============== 注册 ==============
@router.post("/register", response_model=DataResponse)
async def register(payload: RegisterReq, request: Request):
    ok, msg, user = auth.create_user(
        username=payload.username, password=payload.password,
        email=payload.email, nickname=payload.nickname)
    if not ok or not user:
        raise HTTPException(status_code=400, detail=msg)

    audit_inst().log(
        user_id=int(user["id"]), username=user.get("username"),
        category=CATEGORY_REGISTER, action="新用户注册成功",
        target_key=user.get("username"),
        detail={"email": user.get("email"), "nickname": user.get("nickname")},
        ip=_ip(request), ua=_ua(request),
    )
    return DataResponse(message="注册成功", data={"user": user})


# ============== 登录（JSON Body，方便前端）==============
@router.post("/login", response_model=DataResponse)
async def login_json(payload: LoginReq, request: Request):
    return await _do_login(payload.username, payload.password, request)


# ============== 登录（OAuth2PasswordRequestForm 表单，给 Swagger / 自动化工具用）==============
@router.post("/login/form", response_model=DataResponse, include_in_schema=False)
async def login_form(request: Request,
                     username: str = Form(...),
                     password: str = Form(...)):
    return await _do_login(username, password, request)


async def _do_login(username: str, password: str, request: Request):
    ip = _ip(request)
    user = auth.authenticate_password(username, password, ip=ip)
    if not user:
        audit_inst().log(
            user_id=None, username=username,
            category=CATEGORY_LOGIN, action="登录失败：账号或密码错误",
            ok=False, target_key=username,
            detail={"username": username},
            ip=ip, ua=_ua(request),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    tokens = auth.issue_tokens(int(user["id"]), user.get("username") or "")
    aud = audit_inst()
    aud.log(
        user_id=int(user["id"]), username=user.get("username"),
        category=CATEGORY_LOGIN, action="登录成功",
        target_key=user.get("username"),
        detail={"last_login_at": user.get("last_login_at")},
        ip=ip, ua=_ua(request),
    )
    # 登录响应额外带「上次操作」，便于前端再次登录时立刻显示
    last = aud.last_action(int(user["id"]))
    return DataResponse(message="登录成功", data={
        "tokens": tokens,
        "user": user,
        "last_action": last,
    })


# ============== 刷新 Token ==============
@router.post("/refresh", response_model=DataResponse)
async def refresh_token(request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        # 兼容 refresh_token 放 body JSON
        try:
            body = await request.json()
            token = body.get("refresh_token") or None
        except Exception:
            token = None
    if not token:
        raise HTTPException(status_code=400, detail="缺少 refresh_token")
    payload = auth.decode_token(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="refresh_token 无效或已过期")
    jti = payload.get("jti")
    if jti and auth.is_refresh_revoked(jti):
        raise HTTPException(status_code=401, detail="refresh_token 已被吊销")
    try:
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="无效 refresh_token")
    user = auth.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在")
    if jti:
        auth.revoke_refresh(jti, user_id, int(payload.get("exp", 0)))
    new_tokens = auth.issue_tokens(user_id, user.get("username") or "")
    return DataResponse(data={"tokens": new_tokens})


# ============== 登出 ==============
@router.post("/logout", response_model=DataResponse)
async def logout(request: Request,
                 user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    # 可选：吊销当前 access 的 jti 意义不大（短 TTL），主要吊销 refresh（前端调 /logout 时把 refresh 的 jti 一起传）
    refresh_jti = None
    try:
        body = await request.json()
        refresh_jti = body.get("refresh_jti") or None
    except Exception:
        pass
    if user and refresh_jti:
        # 没有精确 exp 就按 14 天兜底
        import time
        auth.revoke_refresh(refresh_jti, int(user["id"]), int(time.time()) + 86400 * 14)
        audit_inst().log(
            user_id=int(user["id"]), username=user.get("username"),
            category=CATEGORY_LOGOUT, action="主动登出",
            ip=_ip(request), ua=_ua(request),
        )
    return DataResponse(message="已登出")


# ============== 修改密码 ==============
@router.post("/change-password", response_model=DataResponse)
async def change_password(payload: ChangePwdReq, request: Request,
                          user: Dict[str, Any] = Depends(get_current_user)):
    ok, msg = auth.change_password(int(user["id"]), payload.old_password, payload.new_password)
    audit_inst().log(
        user_id=int(user["id"]), username=user.get("username"),
        category=CATEGORY_CHANGE_PASSWORD,
        action=("修改密码成功" if ok else f"修改密码失败：{msg}"),
        ok=ok,
        detail={"reason": msg} if not ok else None,
        ip=_ip(request), ua=_ua(request),
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return DataResponse(message=msg)
