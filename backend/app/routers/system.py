"""系统级接口：健康检查、缓存、版本。"""
from __future__ import annotations

import os
import time
from fastapi import APIRouter
from ..cache import CacheLayer
from ..schemas import DataResponse

router = APIRouter()

STARTED_AT = int(time.time())


@router.get("/healthz", response_model=DataResponse)
async def healthz():
    c = CacheLayer.instance()
    return DataResponse(success=True, data={
        "ok": True,
        "uptime": int(time.time()) - STARTED_AT,
        "cache": "redis" if c.use_redis else "memory",
        "pid": os.getpid(),
    })


@router.get("/version", response_model=DataResponse)
async def version():
    return DataResponse(data={
        "name": "webstock",
        "version": "2.0.0",
        "stack": "FastAPI + Vue3 + Nginx + Redis",
        "target_os": "Alibaba Cloud Linux 3.2104 LTS",
    })


@router.delete("/cache", response_model=DataResponse)
async def clear_cache(pattern: str = "webstock:*"):
    n = CacheLayer.instance().delete(pattern)
    return DataResponse(message=f"已清除 {n} 条缓存", data={"cleared": n})
