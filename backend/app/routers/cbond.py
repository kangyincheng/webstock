"""可转债 + 要约收购。"""
from __future__ import annotations

import asyncio
import threading
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..schemas import DataResponse, CBondParams, TenderParams
from ..services.market_service import MarketServices
from ..cache import CacheLayer
from ..services.audit_service import CATEGORY_CBOND
from ..deps import audit_action, get_current_user_or_none

router = APIRouter()

_ms: MarketServices | None = None
_ms_lock = threading.Lock()


def get_ms() -> MarketServices:
    global _ms
    if _ms is None:
        with _ms_lock:
            if _ms is None:
                _ms = MarketServices()
    return _ms


async def _cbond_common(category: str, ex: int = 3600 * 6) -> Dict[str, Any]:
    if category not in ("subscribe", "listing", "review"):
        raise HTTPException(400, "category 必须是 subscribe/listing/review")
    cache = CacheLayer.instance()
    key = f"webstock:cbond:{category}:v1"
    cached = cache.get_json(key)
    if cached is not None:
        return {"data": cached, "hit": True}
    ms = get_ms()
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, lambda: ms.cbond(category))
    result = {"rows": rows}
    cache.set_json(key, result, ex=ex)
    return {"data": result, "hit": False}


@router.post("/subscribe", response_model=DataResponse)
@audit_action(CATEGORY_CBOND, "可转债 - 申购查询", capture_response=False)
async def cbond_subscribe(params: CBondParams,
                          request: Request,
                          user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    r = await _cbond_common("subscribe")
    return DataResponse(data=r["data"], cache_hit=r["hit"])


@router.post("/listing", response_model=DataResponse)
@audit_action(CATEGORY_CBOND, "可转债 - 上市查询", capture_response=False)
async def cbond_listing(params: CBondParams,
                        request: Request,
                        user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    r = await _cbond_common("listing")
    return DataResponse(data=r["data"], cache_hit=r["hit"])


@router.post("/review", response_model=DataResponse)
@audit_action(CATEGORY_CBOND, "可转债 - 发审查询", capture_response=False)
async def cbond_review(params: CBondParams,
                       request: Request,
                       user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    r = await _cbond_common("review")
    return DataResponse(data=r["data"], cache_hit=r["hit"])


@router.post("/tender", response_model=DataResponse)
@audit_action(CATEGORY_CBOND, "要约收购：{payload.market} 市场", capture_response=False)
async def tender(params: TenderParams,
                 request: Request,
                 user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    cache = CacheLayer.instance()
    key = f"webstock:tender:{params.market}:v2"
    cached = cache.get_json(key)
    if cached is not None:
        return DataResponse(data=cached, cache_hit=True)
    ms = get_ms()
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, lambda: ms.tender_offer(params.market))
    result = {"rows": rows}
    cache.set_json(key, result, ex=3600 * 6)
    return DataResponse(data=result)
