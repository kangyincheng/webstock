"""历史涨跌停统计路由。

数据来源：akshare（主力）。
模式：只读本地预计算文件 limit_results.json（每周一凌晨由 refresh_all.py 定时生成）。
      不再兜底实时扫描，避免触发 90 天×2 池=180+ 次 akshare 调用被封 IP。
      ?refresh=1 仅限后端运维（频率限制 12h 一次），前端不再暴露入口。
"""
from __future__ import annotations

import asyncio
import os
import time as _time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from ..cache import CacheLayer
from ..services import limit_stat_service

router = APIRouter()


# refresh 限频标记文件（记录上次手动扫描的时间戳）
_REFRESH_COOLDOWN_FILE = os.path.join(
    os.path.dirname(limit_stat_service.RESULT_FILE or ""),
    ".limit_stat_last_refresh"
)
_REFRESH_COOLDOWN_SEC = 12 * 3600  # 12 小时内不允许重复 refresh


def _can_refresh() -> tuple[bool, float]:
    """检查是否允许手动 refresh。返回 (能否刷新, 剩余等待秒数)。"""
    if not os.path.isfile(_REFRESH_COOLDOWN_FILE):
        return True, 0.0
    try:
        with open(_REFRESH_COOLDOWN_FILE, "r") as f:
            ts = float(f.read().strip())
        elapsed = _time.time() - ts
        remain = _REFRESH_COOLDOWN_SEC - elapsed
        if remain <= 0:
            return True, 0.0
        return False, remain
    except Exception:
        return True, 0.0


def _mark_refreshed():
    try:
        os.makedirs(os.path.dirname(_REFRESH_COOLDOWN_FILE), exist_ok=True)
        with open(_REFRESH_COOLDOWN_FILE, "w") as f:
            f.write(str(_time.time()))
    except Exception:
        pass


@router.get("/limit-stats", response_model=Dict[str, Any])
async def limit_stats(
    n_days: int = Query(90, ge=5, le=365),
    refresh: bool = Query(False, description="[运维专用] 强制实时扫描，12h 内限一次"),
):
    """历史涨跌停统计（A 股）。

    数据优先级：
      1) Redis 缓存（1h TTL）
      2) 本地预计算文件 backend/data/limit_results.json（每周一由 refresh_all.py 生成）

    注意：不再兜底实时扫描，文件不存在时返回提示。
    """
    cache = CacheLayer.instance()
    cache_key = f"webstock:limit_stats:n_days={n_days}:v1"

    if refresh:
        ok, remain = _can_refresh()
        if not ok:
            hours = int(remain // 3600)
            mins = int((remain % 3600) // 60)
            raise HTTPException(
                status_code=429,
                detail=f"手动刷新冷却中，还需等待 {hours}h{mins}min（12h 内限一次，避免封 IP）"
            )
        _mark_refreshed()
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
        result = {
            "records": records,
            "total": total,
            "scanned_days": pre.get("scanned_days", n_days),
            "updated_at": pre.get("updated_at"),
            "cache_hit": False,
            "weekly_update_hint": "数据由定时任务每周一凌晨自动刷新，当前为最新快照",
            "message": f"使用预计算文件（{pre.get('updated_at', '未知时间')}），共 {total} 条",
        }
        cache.set_json(cache_key, {k: v for k, v in result.items() if k != "cache_hit"}, ex=3600)
        return result

    # 文件不存在 → 返回提示，不做兜底实时扫描（防封 IP）
    raise HTTPException(
        status_code=503,
        detail=(
            "历史涨跌停统计数据尚未就绪。"
            "本数据由定时任务每周一凌晨自动刷新生成，"
            "请稍后重试，或联系运维手动触发 refresh_all.py --run limit_stat"
        )
    )


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
        "message": f"运维手动扫描完成，共 {len(records)} 条（已保存到 {path}）",
    }
