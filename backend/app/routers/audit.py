"""操作历史：登录后查看自己的操作日志 / 上次操作记录。"""
from __future__ import annotations

from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..schemas import DataResponse
from ..deps import get_current_user
from ..services.audit_service import audit as audit_inst

router = APIRouter()


@router.get("/last", response_model=DataResponse)
async def get_last_action(user: Dict[str, Any] = Depends(get_current_user)):
    last = audit_inst().last_action(int(user["id"]))
    return DataResponse(data={"last": last})


@router.get("/history", response_model=DataResponse)
async def get_history(
    category: Optional[str] = None,
    only_errors: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user: Dict[str, Any] = Depends(get_current_user),
):
    data = audit_inst().list_history(
        user_id=int(user["id"]),
        category=category, only_errors=only_errors,
        page=page, page_size=page_size,
    )
    return DataResponse(data=data)


@router.get("/detail/{audit_id}", response_model=DataResponse)
async def get_detail(audit_id: int, user: Dict[str, Any] = Depends(get_current_user)):
    import json as _json
    aud = audit_inst()
    with aud._conn() as c:
        row = c.execute("SELECT * FROM audit_logs WHERE id=?", (audit_id,)).fetchone()
        if not row:
            raise HTTPException(404, "记录不存在")
        d = dict(row)
        # 仅允许查自己的
        if d.get("user_id") != int(user["id"]):
            raise HTTPException(403, "无权查看他人操作记录")
        raw = d.get("detail")
        if raw:
            try:
                d["detail"] = _json.loads(raw)
            except Exception:
                pass
        return DataResponse(data=d)


@router.get("/summary", response_model=DataResponse)
async def get_summary(user: Dict[str, Any] = Depends(get_current_user)):
    """过去 7 / 30 天操作概览。"""
    aud = audit_inst()
    with aud._conn() as c:
        row = c.execute(
            """SELECT
                 SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) AS ok_cnt,
                 SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) AS err_cnt,
                 COUNT(*) AS total_cnt,
                 COUNT(DISTINCT date(created_at)) AS active_days
               FROM audit_logs WHERE user_id=?""", (int(user["id"]),)).fetchone()
        rows7 = c.execute(
            """SELECT date(created_at) AS d, COUNT(*) AS n, SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END) ok_n
               FROM audit_logs WHERE user_id=? AND created_at>=datetime('now','localtime','-7 days')
               GROUP BY date(created_at) ORDER BY d DESC""",
            (int(user["id"]),)).fetchall()
    return DataResponse(data={
        "totals": dict(row or {}),
        "last_7_days": [dict(r) for r in rows7],
    })
