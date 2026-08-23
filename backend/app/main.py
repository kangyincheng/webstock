"""FastAPI application entry for webstock.

部署拓扑（客户端最快访问）：
  [Client Browser]  --HTTPS/TCP-->  [Nginx (gzip/brotli/static/keepalive)]
                                         |
                    +--------------------+----------------------+
                    |                                           |
               [/api/*] proxy_pass                         [/ws/*] proxy_pass
                    |                                           |
         [Uvicorn/FastAPI Workers]                    [Uvicorn WebSocket]
                    |                                           |
         [MarketServices / TrainService / Favorites]  [ws_bus 广播]
                    |
        +-----------+-----------+-----------+
        |                       |           |
     baostock              tushare      Redis(缓存)
     SQLite(favorites)   (可选token)    5min~1h TTL
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .cache import CacheLayer
from .routers import system, auth, audit, market, predict, favorites, cbond, admin
from .ws_bus import ws_endpoint
# 初始化 auth + audit 数据库（首次启动自动建表）
from .services import auth_service as _auth  # noqa: F401
from .services import audit_service as _audit_svc  # noqa: F401
_auth.auth_db()
_audit_svc.audit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    CacheLayer.instance()
    yield


app = FastAPI(
    title="webstock API",
    version="2.0.0",
    description="A股收盘价预测/市场分析系统 Web API（FastAPI）",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=86400,
)

# ---- routers ----
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(audit.router, prefix="/api/audit", tags=["audit"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(predict.router, prefix="/api/predict", tags=["predict"])
app.include_router(favorites.router, prefix="/api/favorites", tags=["favorites"])
app.include_router(cbond.router, prefix="/api/cbond", tags=["cbond"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

# ---- 静态前端 fallback（Nginx 直接托管 frontend/dist 更快；这里仅兜底）----
FRONTEND_DIST = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
if os.path.isdir(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("assets/") or full_path.startswith("ws/"):
            raise HTTPException(status_code=404, detail="Not Found")
        index = os.path.join(FRONTEND_DIST, "index.html")
        if not os.path.exists(index):
            raise HTTPException(status_code=404, detail="Frontend not built")
        return FileResponse(index)


# -------- WebSocket：训练进度广播 --------
@app.websocket("/ws/train/{task_id}")
async def ws_train(websocket: WebSocket, task_id: str):
    await ws_endpoint(websocket, task_id)
