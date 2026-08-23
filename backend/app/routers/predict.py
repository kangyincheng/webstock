"""训练/预测路由：PyTorch / TensorFlow 双框架，训练进度走 WebSocket。"""
from __future__ import annotations

import asyncio
import threading
from typing import Dict, Any, Optional

from fastapi import APIRouter, Query

from ..schemas import DataResponse, PredictParams
from ..services.train_service import TrainingService
from ..ws_bus import ws_progress_adapter

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
async def run_train(params: PredictParams):
    ts = get_ts()
    loop = asyncio.get_running_loop()

    task_id = None
    progress_cb = None

    # 生成临时 task_id（TrainingService 会再生成一个，这里在回调里映射）
    payload_box: Dict[str, Any] = {}

    def _real_cb(msg: Dict[str, Any]):
        nonlocal task_id
        tid = msg.get("task_id")
        if tid:
            task_id = tid
        ws_fn = ws_progress_adapter(tid or "")
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
async def delete_model(name: str):
    ts = get_ts()
    ok = ts.delete_model(name)
    return DataResponse(success=ok, message=("已删除" if ok else "未找到或不允许删除"))
