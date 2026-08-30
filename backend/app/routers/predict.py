"""训练/预测路由：PyTorch / TensorFlow 双框架，训练进度走 WebSocket。"""
from __future__ import annotations

import asyncio
import threading
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from ..schemas import DataResponse, PredictParams
from ..services.train_service import TrainingService
from ..services.stock_search_service import StockSearchService
from ..ws_bus import ws_progress_adapter
from ..services.audit_service import CATEGORY_PREDICT_TRAIN, CATEGORY_MODEL_DELETE
from ..deps import audit_action, get_current_user_or_none

router = APIRouter()

_ts: Optional[TrainingService] = None
_ts_lock = threading.Lock()

_TASK_RESULT: Dict[str, Dict[str, Any]] = {}


def get_ts() -> TrainingService:
    global _ts
    if _ts is None:
        with _ts_lock:
            if _ts is None:
                _ts = TrainingService()
    return _ts


@router.post("/train", response_model=DataResponse)
@audit_action(CATEGORY_PREDICT_TRAIN,
              "{payload.framework} / {payload.model_type} 训练 {payload.stock_code}",
              capture_response=False,
              target_key=lambda u, p, r, e: getattr(p, "stock_code", None))
async def run_train(params: PredictParams,
                    request: Request,
                    user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    ts = get_ts()
    loop = asyncio.get_running_loop()

    def _real_cb(msg: Dict[str, Any]):
        tid = msg.get("task_id") or ""
        ws_fn = ws_progress_adapter(tid)
        ws_fn(msg)

    def _run() -> Dict[str, Any]:
        return ts.run_training(params.dict(), progress_cb=_real_cb)

    result = await loop.run_in_executor(None, _run)
    _TASK_RESULT[result.get("task_id", "no-id")] = result
    return DataResponse(data=result, success=result.get("status") == "success",
                        message=result.get("error") or "训练完成")


@router.get("/task/{task_id}", response_model=DataResponse)
async def get_task(task_id: str):
    r = _TASK_RESULT.get(task_id)
    if r is None:
        return DataResponse(success=False, message="任务不存在或仍在执行中，请连接 /ws/train/{task_id} 接收进度")
    return DataResponse(data=r)


@router.get("/models", response_model=DataResponse)
async def list_models(framework: Optional[str] = Query(default=None, pattern="^(pytorch|tensorflow)$")):
    ts = get_ts()
    names = ts.list_models(framework)
    return DataResponse(data={"models": names, "count": len(names)})


@router.delete("/models/{name}", response_model=DataResponse)
@audit_action(CATEGORY_MODEL_DELETE, "删除模型 {name}",
              capture_response=True,
              target_key=lambda u, p, r, e, name_kwarg=None: name_kwarg)
async def delete_model(name: str,
                       request: Request,
                       user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    ts = get_ts()
    ok = ts.delete_model(name)
    return DataResponse(success=ok, message=("已删除" if ok else "未找到或不允许删除"))


@router.get("/search", response_model=DataResponse)
async def search_stock(q: str = Query(default="", description="搜索关键词：代码/名称/简拼"),
                       limit: int = Query(default=20, ge=1, le=50)):
    """股票智能搜索：支持代码、名称、拼音首字母简拼。"""
    svc = StockSearchService.instance()
    results = svc.search(q, limit=limit)
    return DataResponse(data={"results": results, "count": len(results)})
