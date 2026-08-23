"""自选股 CRUD + 行情刷新 + 到期事件扫描。"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
from typing import List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks

from ..schemas import DataResponse, FavoriteStock

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from data_loader import StockDataLoader  # noqa: E402
from ..services.favorites_service import FavoritesService  # noqa: E402

router = APIRouter()

_svc: Optional[FavoritesService] = None
_lock = threading.Lock()


def svc() -> FavoritesService:
    global _svc
    if _svc is None:
        with _lock:
            if _svc is None:
                _svc = FavoritesService()
    return _svc


@router.get("", response_model=DataResponse)
async def list_favs():
    items = svc().list_all()
    return DataResponse(data={"rows": items, "count": len(items)})


@router.post("", response_model=DataResponse)
async def add_fav(payload: FavoriteStock):
    new_id = svc().add(payload.dict())
    return DataResponse(data={"id": new_id}, message="已添加")


@router.put("/{fav_id}", response_model=DataResponse)
async def update_fav(fav_id: int, payload: FavoriteStock):
    ok = svc().update(fav_id, payload.dict())
    if not ok:
        raise HTTPException(404, "记录不存在")
    return DataResponse(message="已更新")


@router.delete("/{fav_id}", response_model=DataResponse)
async def delete_fav(fav_id: int):
    ok = svc().delete(fav_id)
    if not ok:
        raise HTTPException(404, "记录不存在")
    return DataResponse(message="已删除")


@router.post("/refresh-prices", response_model=DataResponse)
async def refresh_prices(background: BackgroundTasks):
    items = svc().list_all()
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
async def check_due_events():
    evts = svc().check_due_events()
    return DataResponse(data={"due_events": evts, "count": len(evts)},
                        message="到期事件已标记为已通知" if evts else "无到期事件")
