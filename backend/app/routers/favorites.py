"""自选股 CRUD + 行情刷新 + 到期事件扫描（登录用户 / 匿名共享同一库，但每个用户只看自己的记录）。"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Request

from ..schemas import DataResponse, FavoriteStock

from ..services.audit_service import (CATEGORY_FAV_ADD, CATEGORY_FAV_UPDATE,
                                      CATEGORY_FAV_DELETE, CATEGORY_FAV_REFRESH,
                                      CATEGORY_FAV_CHECK_EVENTS)
from ..deps import audit_action, get_current_user, get_current_user_or_none

router = APIRouter()

# ======== 用户隔离 ========
# 匿名用户（None） → 全部写入 user_id=0（同一个"访客共享池"，保持旧行为兼容）
# 登录用户       → user_id = 实际 user.id（只能看自己的）
def _safe_uid(user: Optional[Dict[str, Any]]) -> int:
    return int(user["id"]) if user else 0


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from data_loader import StockDataLoader  # noqa: E402
from ..services.favorites_service import FavoritesService  # noqa: E402

_svc: Optional[FavoritesService] = None
_svc_lock = threading.Lock()


def svc() -> FavoritesService:
    global _svc
    if _svc is None:
        with _svc_lock:
            if _svc is None:
                _svc = FavoritesService()
    return _svc


# 加 user_id 字段到自选股表（如果不存在）
def _ensure_userid_column():
    try:
        with svc()._conn() as c:
            cols = [r[1] for r in c.execute("PRAGMA table_info(favorite_stocks)").fetchall()]
            if "user_id" not in cols:
                c.execute("ALTER TABLE favorite_stocks ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
                c.execute("CREATE INDEX IF NOT EXISTS idx_fav_user ON favorite_stocks(user_id)")
    except Exception:
        pass


_ensure_userid_column()


# =============== CRUD ===============
@router.get("", response_model=DataResponse)
async def list_favs(user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    uid = _safe_uid(user)
    items = svc().list_all()
    # 用户隔离
    items = [it for it in items if (it.get("user_id") or 0) == uid]
    return DataResponse(data={"rows": items, "count": len(items)})


@router.post("", response_model=DataResponse)
@audit_action(CATEGORY_FAV_ADD, "新增自选股 {payload.code} {payload.name}",
              capture_response=True,
              target_key=lambda u, p, r, e: f"{getattr(p, 'code', '')}-{getattr(p, 'name', '')}")
async def add_fav(payload: FavoriteStock,
                  request: Request,
                  user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    uid = _safe_uid(user)
    data = payload.model_dump()
    data["user_id"] = uid
    new_id = svc().add(data)
    return DataResponse(data={"id": new_id}, message="已添加")


@router.put("/{fav_id}", response_model=DataResponse)
@audit_action(CATEGORY_FAV_UPDATE, "更新自选股 id={fav_id}",
              capture_response=True,
              target_key=lambda u, p, r, e, fav_id=None: fav_id)
async def update_fav(fav_id: int, payload: FavoriteStock,
                     request: Request,
                     user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    uid = _safe_uid(user)
    with svc()._conn() as c:
        row = c.execute("SELECT id, user_id FROM favorite_stocks WHERE id=?", (fav_id,)).fetchone()
        if not row:
            raise HTTPException(404, "记录不存在")
        if int(row["user_id"]) != uid:
            raise HTTPException(403, "无权修改他人的自选股")
    data = payload.model_dump()
    data["user_id"] = uid
    ok = svc().update(fav_id, data)
    if not ok:
        raise HTTPException(404, "记录不存在")
    return DataResponse(message="已更新")


@router.delete("/{fav_id}", response_model=DataResponse)
@audit_action(CATEGORY_FAV_DELETE, "删除自选股 id={fav_id}",
              target_key=lambda u, p, r, e, fav_id=None: fav_id)
async def delete_fav(fav_id: int,
                     request: Request,
                     user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    uid = _safe_uid(user)
    with svc()._conn() as c:
        row = c.execute("SELECT id, user_id FROM favorite_stocks WHERE id=?", (fav_id,)).fetchone()
        if not row:
            raise HTTPException(404, "记录不存在")
        if int(row["user_id"]) != uid:
            raise HTTPException(403, "无权删除他人的自选股")
    ok = svc().delete(fav_id)
    if not ok:
        raise HTTPException(404, "记录不存在")
    return DataResponse(message="已删除")


@router.post("/refresh-prices", response_model=DataResponse)
@audit_action(CATEGORY_FAV_REFRESH, "刷新自选股最新价", capture_response=False)
async def refresh_prices(background: BackgroundTasks,
                         request: Request,
                         user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    uid = _safe_uid(user)
    items = [it for it in svc().list_all() if (it.get("user_id") or 0) == uid]
    codes = [it["code"] for it in items if it.get("code")]
    if not codes:
        return DataResponse(message="自选股为空，无需刷新")
    background.add_task(_refresh_task, codes)
    return DataResponse(message=f"已提交刷新 {len(codes)} 只，请稍后 GET / 查看结果")


def _refresh_task(codes: List[str]):
    """baostock 批量拉最新收盘价。"""
    try:
        loader = StockDataLoader()
        loader.login()
        try:
            prices = {}
            for code in codes:
                try:
                    df = loader.fetch_data(code, start_date="", end_date="", fields="date,code,close")
                    if df is not None and not df.empty and "close" in df.columns:
                        last = df["close"].iloc[-1]
                        prices[code] = float(last) if last is not None else None
                except Exception:
                    continue
            if prices:
                svc().update_prices(prices)
        finally:
            loader.logout()
    except Exception:
        pass


@router.post("/check-events", response_model=DataResponse)
@audit_action(CATEGORY_FAV_CHECK_EVENTS, "扫描自选股到期事件", capture_response=True)
async def check_due_events(request: Request,
                           user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    uid = _safe_uid(user)
    all_evts = svc().check_due_events()
    my_evts = [e for e in all_evts if (e.get("fav_id") is not None and
                                       _event_belongs_user(int(e["fav_id"]), uid))]
    return DataResponse(data={"due_events": my_evts, "count": len(my_evts)},
                        message="到期事件已标记为已通知" if my_evts else "无到期事件")


def _event_belongs_user(fav_id: int, user_id: int) -> bool:
    with svc()._conn() as c:
        row = c.execute("SELECT user_id FROM favorite_stocks WHERE id=?", (fav_id,)).fetchone()
        if not row:
            return False
        return int(row["user_id"]) == user_id
