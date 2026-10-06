"""历史涨跌停统计路由。

数据来源：akshare（主力）、baostock / tushare（可选）
模式：优先读本地预计算文件 limit_results.json（定时刷新），支持 ?refresh=1 强制实时扫描。
"""
from __future__ import annotations

import asyncio
import os
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..cache import CacheLayer
from ..services import limit_stat_service
from ..deps import audit_action, get_current_user_or_none

router = APIRouter()


class LimitStatParams(BaseModel):
    n_days: int = Field(90, ge=5, le=365, description="往前扫描多少个交易日")
    data_sources: List[str] = Field(default_factory=lambda: ["akshare"],
                                    description="数据源：akshare / baostock / tushare")


@router.get("/limit-stats", response_model=Dict[str, Any])
async def limit_stats(
    n_days: int = Query(90, ge=5, le=365),
    refresh: bool = Query(False, description="是否忽略缓存强制实时扫描（建议仅运维用）"),
    request: Request = None,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none) if False else None,
):
    """历史涨跌停统计（A 股）。

    数据优先级：
      1) Redis 缓存（1h TTL）
      2) 本地预计算文件 backend/data/limit_results.json
      3) 实时扫描（约 2~10min，建议仅运维用）
    """
    cache = CacheLayer.instance()
    cache_key = f"webstock:limit_stats:n_days={n_days}:v1"

    if refresh:
        result = await _realtime_scan(n_days)
        cache.set_json(cache_key, result, ex=3600)
        return result

    cached = cache.get_json(cache_key)
    if cached is not None:
        return {**cached, "cache_hit": True}

    pre = limit_stat_service.load_results()
    if pre:
        records = pre.get("records", [])
        total = len(records)
        # 如果扫描天数不匹配，返回提示但仍可用
        result = {
            "records": records,
            "total": total,
            "scanned_days": pre.get("scanned_days", n_days),
            "updated_at": pre.get("updated_at"),
            "cache_hit": False,
            "message": f"使用预计算文件（{pre.get('updated_at', '未知时间')}），共 {total} 条",
        }
        cache.set_json(cache_key, {k: v for k, v in result.items() if k != "cache_hit"}, ex=3600)
        return result

    # 兜底：实时扫描
    result = await _realtime_scan(n_days)
    cache.set_json(cache_key, {k: v for k, v in result.items() if k != "cache_hit"}, ex=3600)
    return result


async def _realtime_scan(n_days: int) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()

    def _run():
        return limit_stat_service.scan(n_days=n_days)

    records = await loop.run_in_executor(None, _run)
    path = limit_stat_service.save_results(records, n_days)
    pre = limit_stat_service.load_results()
    return {
        "records": records,
        "total": len(records),
        "scanned_days": n_days,
        "updated_at": pre.get("updated_at") if pre else None,
        "cache_hit": False,
        "message": f"实时扫描完成，共 {len(records)} 条（已保存到 {path}）",
    }
