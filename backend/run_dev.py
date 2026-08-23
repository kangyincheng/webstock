#!/usr/bin/env python3
"""开发启动脚本：uvicorn backend.app.main:app --reload"""
import os
import sys
import uvicorn

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "backend.app.main:app",
        host=host, port=port,
        reload=bool(int(os.environ.get("RELOAD", "1"))),
        workers=int(os.environ.get("WORKERS", "1")),
        proxy_headers=True, forwarded_allow_ips="*",
    )
