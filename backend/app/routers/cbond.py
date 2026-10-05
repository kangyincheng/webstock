"""可转债 + 要约收购。"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query

from ..schemas import DataResponse, CBondParams, TenderParams
from ..services.market_service import MarketServices
from ..cache import CacheLayer
from ..services.audit_service import CATEGORY_CBOND
from ..deps import audit_action, get_current_user_or_none

router = APIRouter()

_ms: MarketServices | None = None
_ms_lock = threading.Lock()

# 要约收购预计算文件（类似 ST 摘帽的 st_time_results.json）
_TENDER_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "tender_results.json")


def _load_tender_cache() -> Optional[Dict[str, Any]]:
    """读本地预计算文件：tender_results.json。

    文件结构：{"cn": {...}, "hk": {...}, "updated_at": "2026-10-06 01:30:12"}
    每个市场的结构：{"rows": [...]}
    """
    try:
        if os.path.isfile(_TENDER_FILE):
            with open(_TENDER_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return None


def _save_tender_cache(data: Dict[str, Any]) -> None:
    """写本地预计算文件（原子写）。"""
    try:
        os.makedirs(os.path.dirname(_TENDER_FILE), exist_ok=True)
        tmp = _TENDER_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _TENDER_FILE)
    except Exception as e:
        print(f"[tender] 写预计算文件失败: {e}", flush=True)


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
                 refresh: bool = Query(False, description="是否忽略缓存实时抓取（仅运维用）"),
                 user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    """要约收购（A 股 / 港股）。

    数据优先级（从快到慢）：
      1) Redis 内存缓存（6h TTL）
      2) 本地预计算文件 backend/data/tender_results.json（每个交易日 01:30 更新）
      3) 实时爬集思录 + 写本地 + 写 Redis（约 10s）

    性能原则（重要！）：
      - 默认请求绝不触发实时抓取，只读预计算文件。
      - 只有显式 ?refresh=1 才会实时爬（约 10s，建议仅运维用）。
    """
    cache = CacheLayer.instance()
    cache_key = f"webstock:tender:{params.market}:v3"

    # -------- refresh=1：强制实时 --------
    if refresh:
        ms = get_ms()
        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(None, lambda: ms.tender_offer(params.market))
        # 同时更新另一个市场到本地文件（避免下次又要爬）
        other_market = "hk" if params.market == "cn" else "cn"
        other_rows = await loop.run_in_executor(None, lambda: ms.tender_offer(other_market))
        now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        pre = _load_tender_cache() or {}
        pre[params.market] = {"rows": rows}
        pre[other_market] = {"rows": other_rows}
        pre["updated_at"] = now_str
        _save_tender_cache(pre)
        result = {"rows": rows, "updated_at": now_str}
        cache.set_json(cache_key, {"rows": rows}, ex=3600 * 6)
        return DataResponse(data=result, cache_hit=False,
                            message=f"实时抓取（{params.market}）")

    # -------- 默认：优先 Redis 缓存 --------
    cached = cache.get_json(cache_key)
    if cached is not None:
        pre = _load_tender_cache() or {}
        result = dict(cached)
        if "updated_at" not in result and pre.get("updated_at"):
            result["updated_at"] = pre["updated_at"]
        return DataResponse(data=result, cache_hit=True)

    # -------- 次选：本地预计算文件 --------
    pre = _load_tender_cache()
    if pre and params.market in pre:
        market_data = pre[params.market]
        rows = market_data.get("rows") or []
        result = {"rows": rows, "updated_at": pre.get("updated_at")}
        cache.set_json(cache_key, {"rows": rows}, ex=3600 * 6)
        return DataResponse(data=result, cache_hit=False,
                            message=f"使用预计算文件（{pre.get('updated_at', '未记录')}）")

    # -------- 兜底：实时爬（文件也没有，首次启动场景）--------
    ms = get_ms()
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, lambda: ms.tender_offer(params.market))
    now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    pre = pre or {}
    pre[params.market] = {"rows": rows}
    pre["updated_at"] = now_str
    _save_tender_cache(pre)
    result = {"rows": rows, "updated_at": now_str}
    cache.set_json(cache_key, {"rows": rows}, ex=3600 * 6)
    return DataResponse(data=result, cache_hit=False,
                        message=f"首次启动实时抓取（建议稍后访问自动刷新）")
