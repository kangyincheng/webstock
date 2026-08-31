"""市场行情相关路由：ST 摘帽、ST 恢复、温度计、板块热度、热门股票。"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request

from ..cache import CacheLayer
from ..schemas import (DataResponse, STScanParams, GenericScanParams,
                       MarketDateParams, HotStocksParams)
from ..services.market_service import MarketServices
from ..services.audit_service import (CATEGORY_ST_SCAN, CATEGORY_ST_REINSTATE_SCAN,
                                      CATEGORY_SECTOR_HEAT, CATEGORY_HOT_STOCKS)
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


def _cache_key(ns: str, **kwargs) -> str:
    parts = [f"{k}={v}" for k, v in sorted(kwargs.items()) if v is not None]
    return "webstock:" + ns + ":" + ("|".join(parts) or "default")


# ---------- ST 摘帽（长任务）----------
@router.post("/st/scan", response_model=DataResponse)
@audit_action(CATEGORY_ST_SCAN, "ST摘帽扫描（回溯 {payload.months_back} 个月）",
              capture_response=False,
              target_key=lambda u, p, r, e: f"mb={p.months_back if p else None}")
async def st_scan(params: STScanParams,
                  request: Request,
                  user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    cache = CacheLayer.instance()
    # v2：修复摘帽识别算法（isST 转折检测）后升级命名空间，绕过旧算法写入的空缓存
    key = _cache_key("st-scan-v2", months_back=params.months_back,
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

    is_demo = False
    try:
        # 长任务：全市场 5000+ 只并行扫描约 3~5 分钟，给足 600s
        records = await asyncio.wait_for(
            loop.run_in_executor(None, _run), timeout=600.0)
    except (Exception, asyncio.TimeoutError) as exc:
        # baostock 不可达 / 超时时返回演示数据，按钮不崩
        demo = [
            {"股票名称": "演示-华银电力", "代码": "sh.600744", "开始ST日期": "2024-03-15",
             "结束ST日期": "2024-09-10", "摘帽前涨幅": -3.2, "摘帽后涨幅": 12.8,
             "市盈率": 35.6, "市净率": 2.1, "收盘价": 5.82},
            {"股票名称": "演示-ST 中程", "代码": "sz.000975", "开始ST日期": "2024-06-01",
             "结束ST日期": None, "摘帽前涨幅": 5.1, "摘帽后涨幅": None,
             "市盈率": -8.4, "市净率": 1.3, "收盘价": 3.45},
        ]
        records = demo
        logs.append(f"[演示数据] baostock 不可达或超时: {exc}")
        is_demo = True
    result: Dict[str, Any] = {"records": records, "logs": logs[-20:]}
    if not is_demo:
        cache.set_json(key, result, ex=3600 * 6)
    msg = f"扫描 {len(records)} 条记录" + ("（演示数据）" if is_demo else "")
    return DataResponse(data=result, message=msg)


@router.post("/st-reinstate/scan", response_model=DataResponse)
@audit_action(CATEGORY_ST_REINSTATE_SCAN, "ST 恢复上市扫描（回溯 {payload.months_back} 个月）",
              capture_response=False)
async def st_reinstate_scan(params: GenericScanParams,
                            request: Request,
                            user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    cache = CacheLayer.instance()
    key = _cache_key("st-reinstate", months_back=params.months_back)
    cached = cache.get_json(key)
    if cached is not None:
        return DataResponse(data=cached, cache_hit=True, message="使用缓存")

    ms = get_ms()
    loop = asyncio.get_running_loop()
    logs: list[str] = []
    is_demo = False
    try:
        # 长任务：给足 120s
        records = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: ms.scan_st_reinstate(params.months_back, progress_cb=logs.append)),
            timeout=120.0)
    except (Exception, asyncio.TimeoutError) as exc:
        demo = [
            {"股票名称": "演示-退市国发", "代码": "sh.600001",
             "ST开始日期": "2023-12-01", "可申请摘帽日": "2024-12-02",
             "股价": 1.23, "净资产": 2.05, "市盈率": -18.5,
             "市净率": 0.6, "量比": 1.25, "换手": 0.9},
        ]
        records = demo
        logs.append(f"[演示数据] baostock 不可达或超时: {exc}")
        is_demo = True
    result: Dict[str, Any] = {"records": records, "logs": logs[-20:]}
    if not is_demo:
        cache.set_json(key, result, ex=3600 * 6)
    msg = f"扫描 {len(records)} 条" + ("（演示数据）" if is_demo else "")
    return DataResponse(data=result, message=msg)


# ---------- 市场温度计（只读：不审计，避免仪表板每次打开都刷日志）----------
@router.get("/thermometer", response_model=DataResponse)
async def thermometer():
    cache = CacheLayer.instance()
    key = "webstock:thermometer:v1"
    data = cache.get_json(key)
    if data is not None:
        return DataResponse(data=data, cache_hit=True)
    ms = get_ms()
    loop = asyncio.get_running_loop()
    try:
        data = await asyncio.wait_for(
            loop.run_in_executor(None, ms.market_thermometer),
            timeout=15.0)
    except (Exception, asyncio.TimeoutError) as exc:
        # baostock 不可达/超时：返回演示数据
        data = {"percent": 52, "level": "normal", "above_count": 2600,
                "total": 5000, "date": "演示数据",
                "message": f"baostock 不可达，显示演示数据: {exc}"}
    if data:
        cache.set_json(key, data, ex=60 * 15)
    return DataResponse(data=data)


# ---------- 板块热度 ----------
@router.post("/sector-heat", response_model=DataResponse)
@audit_action(CATEGORY_SECTOR_HEAT, "板块热度查询（交易日 {payload.trade_date|今天}）",
              capture_response=False)
async def sector_heat(params: MarketDateParams,
                      request: Request,
                      user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
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
@audit_action(CATEGORY_HOT_STOCKS, "热门股票：按 {payload.sort_by} Top {payload.top_n}",
              capture_response=False)
async def hot_stocks(params: HotStocksParams,
                     request: Request,
                     user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
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
