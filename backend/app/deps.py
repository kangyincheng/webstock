"""认证依赖 + 审计装饰器，所有路由统一通过这里取当前用户并写审计。"""
from __future__ import annotations

import json
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from .services import auth_service as auth
from .services import audit_service as audit_mod
from .services.audit_service import AuditService

# auto_error=False：即便没有 Bearer Token 也返回 None，
# 我们在依赖里统一处理 → 允许匿名访问，但登录态能取到用户。
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def _client_ip(req: Request) -> str:
    forwarded = req.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return req.client.host if req.client else ""


def _client_ua(req: Request) -> str:
    return req.headers.get("User-Agent", "")[:255]


async def get_current_user_or_none(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[Dict[str, Any]]:
    """可选 token：匿名返回 None；无效 token 直接 401（防止伪造）。"""
    if not token:
        return None
    payload = auth.decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    try:
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="无效 token")
    user = auth.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="账号已删除，请重新注册")
    return user


async def get_current_user(
    user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none),
) -> Dict[str, Any]:
    """强制登录。"""
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录后再操作")
    return user


# ---------------- 审计装饰器 ----------------
def audit_action(
    category: str,
    action_template: Optional[str] = None,
    *,
    require_auth: bool = False,
    capture_request: bool = True,
    capture_response: bool = True,
    target_key: Optional[Callable[..., Optional[str]]] = None,
):
    """在 FastAPI 路由函数上使用的装饰器（支持 async / sync）。

    用法：
        @router.post("/...")
        @audit_action("favorites.add", "新增自选股 {payload.code} {payload.name}")
        async def add(payload: FavoriteStock, user=..., request: Request): ...

    规则：
    - 被装饰函数的参数里**必须有** `request: Request`（用于 IP/UA 读取）；
    - 被装饰函数的第一个业务参数是请求体 Payload（若有），会自动传入 `payload=...` 到 action_template；
    - 装饰器会捕获业务返回结果（字典 / Pydantic / DataResponse 均可），并记录为 result；
    - require_auth=True 时，会强制校验 user 必须非空（等价于使用 Depends(get_current_user)）。
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
        import inspect
        sig = inspect.signature(fn)
        is_async = inspect.iscoroutinefunction(fn)

        @wraps(fn)
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = kwargs.get("request") or next(
                (a for a in args if isinstance(a, Request)), None)
            if request is None:
                raise RuntimeError("使用 @audit_action 的路由必须接收 request: Request 作为参数")

            # 定位 user（支持 Depends 直接传，也兼容 kwargs 里的 user / current_user）
            user = kwargs.get("user") or kwargs.get("current_user")

            if require_auth and not user:
                raise HTTPException(status_code=401, detail="请先登录")

            # 业务 payload：取 kwargs 里名为 "payload" 或 "params" 或第一个 Pydantic 对象
            payload = kwargs.get("payload")
            if payload is None:
                for k, v in kwargs.items():
                    if k in ("request", "user", "current_user", "background", "name_kwarg"):
                        continue
                    if hasattr(v, "model_dump"):
                        payload = v
                        break
            # 路由路径参数（供模板/target_key使用）：把其它非 payload/request/user 的 kwargs 拼进 payload 视图
            extra_ctx: Dict[str, Any] = {}
            for k, v in kwargs.items():
                if k in ("request", "user", "current_user", "background", "payload", "params"):
                    continue
                if isinstance(v, (str, int, float, bool)) or v is None:
                    extra_ctx[k] = v
            try:
                result = await fn(*args, **kwargs) if is_async else fn(*args, **kwargs)
                ok = True
                exc = None
            except Exception as e:
                result = None
                ok = False
                exc = e

            # ---------- 组装审计信息 ----------
            detail: Dict[str, Any] = {}
            if capture_request and payload is not None:
                try:
                    detail["request"] = payload.model_dump() if hasattr(payload, "model_dump") else payload
                except Exception:
                    detail["request"] = str(payload)
            if capture_response and result is not None:
                try:
                    detail["response"] = result.model_dump() if hasattr(result, "model_dump") else result
                except Exception:
                    detail["response"] = str(result)
                if len(json.dumps(detail.get("response", ""), ensure_ascii=False)) > 4096:
                    detail["response"] = "<response too large>"
            if exc is not None:
                detail["error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}

            action_text = action_template or category
            # 简单模板替换：{payload.xxx} / {user.xxx} / {path.xxx}
            try:
                ctx: Dict[str, Any] = {}
                if payload is not None:
                    ctx["payload"] = payload.model_dump() if hasattr(payload, "model_dump") else payload
                if user is not None:
                    ctx["user"] = user
                ctx.update(extra_ctx)
                # 顶层变量：{code} {name} {fav_id} 等
                if payload is not None:
                    pd = ctx.get("payload")
                    if isinstance(pd, dict):
                        for k, v in pd.items():
                            if k not in ctx: ctx[k] = v
                for k, v in extra_ctx.items():
                    ctx[k] = v
                if "{" in action_text:
                    # Format 容错：未知占位符保留原值
                    import string as _string
                    class _SafeDict(dict):
                        def __missing__(self, k): return "{" + k + "}"
                    def _flatten_for_fmt(d: Dict[str, Any]):
                        out = {}
                        for k, v in d.items():
                            if isinstance(v, (str, int, float, bool)) or v is None:
                                out[k] = v if v is not None else ""
                            elif isinstance(v, dict):
                                for kk, vv in v.items():
                                    if isinstance(vv, (str, int, float, bool)) or vv is None:
                                        out[f"{k}.{kk}"] = vv if vv is not None else ""
                        return out
                    action_text = action_text.format_map(_SafeDict(_flatten_for_fmt(ctx)))
            except Exception:
                pass

            # target_key：可由显式传入函数生成，否则用 id/code/name 字段
            tk: Optional[str] = None
            if target_key:
                try:
                    # 兼容两种签名：(user,payload,result,exc) 和 带额外 kwargs 的版本
                    import inspect as _insp
                    sig2 = _insp.signature(target_key)
                    names = list(sig2.parameters.keys())
                    if len(names) <= 4:
                        tk = target_key(user, payload, result, exc)
                    else:
                        bound_extra = {k: v for k, v in extra_ctx.items()}
                        tk = target_key(user, payload, result, exc, **bound_extra)
                except Exception:
                    tk = None
            if not tk and payload is not None:
                pdict = payload.model_dump() if hasattr(payload, "model_dump") else payload
                if isinstance(pdict, dict):
                    tk = (pdict.get("id") or pdict.get("code") or pdict.get("name") or
                          pdict.get("stock_code") or pdict.get("model_name") or pdict.get("task_id"))
                    tk = str(tk) if tk is not None else None

            user_id = int(user["id"]) if user else None
            username = user.get("username") if user else None

            AuditService_inst: AuditService = audit_mod.audit()
            AuditService_inst.log(
                user_id=user_id, username=username,
                category=category, action=action_text, ok=ok, target_key=tk,
                detail=detail or None,
                ip=_client_ip(request), ua=_client_ua(request),
            )

            if exc is not None:
                raise exc
            return result

        # 保留原签名（FastAPI 需要根据签名推断 Depends）
        wrapper.__signature__ = sig  # type: ignore[attr-defined]
        return wrapper

    return decorator


def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out
