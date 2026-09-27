"""训练进度 WebSocket 广播总线。

拆分的原因：main.py include_router(predict.router) 时，
predict.py 需要发 WS 推送；不能直接反向 import main（循环导入）。
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

WS_QUEUES: Dict[str, Set[asyncio.Queue]] = {}
WS_LOCK = threading.Lock()

# 模块级 event loop——在第一个 WS 连接建立时 capture。
# 这样后台训练线程也能 call_soon_threadsafe 推消息。
_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


async def ws_endpoint(websocket: WebSocket, task_id: str):
    global _MAIN_LOOP
    if _MAIN_LOOP is None:
        _MAIN_LOOP = asyncio.get_running_loop()

    await websocket.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=512)
    with WS_LOCK:
        WS_QUEUES.setdefault(task_id, set()).add(q)
    try:
        while True:
            msg = await q.get()
            await websocket.send_text(json.dumps(msg, ensure_ascii=False, default=str))
    except WebSocketDisconnect:
        pass
    finally:
        with WS_LOCK:
            s = WS_QUEUES.get(task_id)
            if s:
                s.discard(q)
                if not s:
                    WS_QUEUES.pop(task_id, None)


def broadcast_progress(task_id: str, payload: Dict[str, Any]):
    """在任意线程（包括后台训练线程）安全推消息。"""
    loop = _MAIN_LOOP
    if loop is None:
        # 还没 WS 连接——后台训练先于前端 WS 连接也完全正常，
        # 此时纯靠 HTTP 轮询 /task/{id} 兜底即可。
        return

    def _put():
        subs = WS_QUEUES.get(task_id)
        if not subs:
            return
        for q in list(subs):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    try:
        loop.call_soon_threadsafe(_put)
    except Exception:
        pass


def ws_progress_adapter(task_id: str):
    def _cb(payload):
        broadcast_progress(task_id, payload)
    return _cb
