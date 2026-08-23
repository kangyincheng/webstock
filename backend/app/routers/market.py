"""市场行情相关路由：ST 摘帽、ST 恢复、温度计、板块热度、热门股票。"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Query

from ..cache import CacheLayer
from ..schemas import (DataResponse, STScanParams, GenericScanParams,
                       MarketDateParams, HotStocksParams)
from ..services.market_service import MarketServices

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


def _cache_key(ns: str, **kwargs) -> str:
    parts = [f"{k}={v}" for k, v in sorted(kwargs.items()) if v is not None]
    return "webstock:" + ns + ":" + ("|".join(parts) or "default")


# ---------- ST 摘帽（长任务，后台线程 + 进度先不做 ws，直接同步，时间长但可接受） ----------
@router.post("/st/scan", response_model=DataResponse)
async def st_scan(params: STScanParams):
    cache = CacheLayer.instance()
    key = _cache_key("st-scan", months_back=params.months_back,
                     before_days=params.before_days, after_days=params.after_days)
    cached = cache.get_json(key)
    if cached is not None:
        return DataResponse(data=cached, cache_hit=True, message="使用缓存")

    ms = get_ms()
    logs: list[str] = []
    loop = asyncio.get_running_loop()

    def _prog(msg):
        logs.append(str(msg))

    def _run():
        return ms.scan_st(params.months_back, params.before_days, params.after_days,
                          progress_cb=_prog)

    records = await loop.run_in_executor(None, _run)
    result: Dict[str, Any] = {"records": records, "logs": logs[-20:]}
    cache.set_json(key, result, ex=3600 * 6)
    return DataResponse(data=result, message=f"扫描 {len(records)} 条记录")


@router.post("/st-reinstate/scan", response_model=DataResponse)
async def st_reinstate_scan(params: GenericScanParams):
    ms = get_ms()
    loop = asyncio.get_running_loop()
    logs: list[str] = []
    records = await loop.run_in_executor(
        None,
        lambda: ms.scan_st_reinstate(params.months_back, progress_cb=logs.append))
    return DataResponse(data={"records": records, "logs": logs[-20:]},
                        message=f"扫描 {len(records)} 条")


# ---------- 市场温度计 ----------
@router.get("/thermometer", response_model=DataResponse)
async def thermometer():
    cache = CacheLayer.instance()
    key = "webstock:thermometer:v1"
    data = cache.get_json(key)
    if data is not None:
        return DataResponse(data=data, cache_hit=True)
    ms = get_ms()
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, ms.market_thermometer)
    if data:
        cache.set_json(key, data, ex=60 * 15)
    return DataResponse(data=data)


# ---------- 板块热度 ----------
@router.post("/sector-heat", response_model=DataResponse)
async def sector_heat(params: MarketDateParams):
    cache = CacheLayer.instance()
    key = _cache_key("sector-heat", td=params.trade_date)
    if params.use_cache:
        data = cache.get_json(key)
        if data is not None:
            return DataResponse(data=data, cache_hit=True)
    ms = get_ms()
    loop = asyncio.get_running_loop()
    logs: list[str] = []
    rows = await loop.run_in_executor(
        None,
        lambda: ms.sector_heat(params.trade_date, params.use_cache, logs.append))
    result = {"rows": rows, "logs": logs[-20:]}
    cache.set_json(key, result, ex=3600 * 6)
    return DataResponse(data=result)


# ---------- 热门股票 ----------
@router.post("/hot-stocks", response_model=DataResponse)
async def hot_stocks(params: HotStocksParams):
    cache = CacheLayer.instance()
    key = _cache_key("hot-stocks", td=params.trade_date, sort=params.sort_by,
                     top=params.top_n, kw=params.filter_keyword)
    if params.use_cache:
        data = cache.get_json(key)
        if data is not None:
            return DataResponse(data=data, cache_hit=True)
    ms = get_ms()
    loop = asyncio.get_running_loop()
    logs: list[str] = []
    rows = await loop.run_in_executor(
        None,
        lambda: ms.hot_stocks(params.trade_date, params.sort_by, params.top_n,
                              params.filter_keyword, params.use_cache, logs.append))
    result = {"rows": rows, "logs": logs[-20:]}
    cache.set_json(key, result, ex=3600 * 6)
    return DataResponse(data=result)
