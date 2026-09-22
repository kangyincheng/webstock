"""市场行情相关路由：ST 摘帽、ST 恢复、温度计、板块热度、热门股票。"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..cache import CacheLayer
from ..schemas import (DataResponse, STScanParams, STAddParams, GenericScanParams,
                       MarketDateParams, HotStocksParams)
from ..services.market_service import MarketServices
from ..services import st_data_service
from ..services import st_time_service
from ..services.audit_service import (CATEGORY_ST_SCAN, CATEGORY_ST_REINSTATE_SCAN,
                                      CATEGORY_SECTOR_HEAT, CATEGORY_HOT_STOCKS)
from ..deps import audit_action, get_current_user_or_none, get_current_admin

router = APIRouter()

_ms: MarketServices | None = None
_ms_lock = threading.Lock()


def get_ms() -> MarketServices:
    global _ms
    if _ms is None:
        with _ms_lock:
            if _ms is None:
                _ms = MarketServices()
    return _ms


def _cache_key(ns: str, **kwargs) -> str:
    parts = [f"{k}={v}" for k, v in sorted(kwargs.items()) if v is not None]
    return "webstock:" + ns + ":" + ("|".join(parts) or "default")


# ---------- ST 摘帽（长任务）----------
# 预计算数据文件路径（与 st_data_service.DATA_FILE 一致，仅用于兜底参考）
_PRECOMPUTED_ST_SCAN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "st_scan_results.json")


def _load_precomputed_st_scan() -> Optional[Dict[str, Any]]:
    """加载预计算的 ST 摘帽前后表现数据（由管理员后台维护）。"""
    data = st_data_service.load_data()
    if data.get("records"):
        return data
    return None


# 演示数据：当 baostock 不可达/超时/或扫描结果为空时回退，保证页面统计卡与图表可见
_ST_SCAN_DEMO = [
    {"股票名称": "演示-华银电力", "代码": "sh.600744", "开始ST日期": "2024-03-15",
     "结束ST日期": "2024-09-10", "摘帽前涨幅": -3.2, "摘帽后涨幅": 12.8,
     "市盈率": 35.6, "市净率": 2.1, "收盘价": 5.82},
    {"股票名称": "演示-ST 酒鬼", "代码": "sz.000975", "开始ST日期": "2024-06-01",
     "结束ST日期": "2024-11-22", "摘帽前涨幅": 8.4, "摘帽后涨幅": 25.6,
     "市盈率": 22.1, "市净率": 3.4, "收盘价": 12.35},
    {"股票名称": "演示-ST 中程", "代码": "sz.000975", "开始ST日期": "2024-06-01",
     "结束ST日期": "2024-08-15", "摘帽前涨幅": 5.1, "摘帽后涨幅": -6.3,
     "市盈率": -8.4, "市净率": 1.3, "收盘价": 3.45},
    {"股票名称": "演示-*ST 海航", "代码": "sh.600654", "开始ST日期": "2024-01-20",
     "结束ST日期": "2024-07-05", "摘帽前涨幅": -8.7, "摘帽后涨幅": 45.2,
     "市盈率": 9.8, "市净率": 0.8, "收盘价": 1.87},
    {"股票名称": "演示-ST 光缆", "代码": "sz.002089", "开始ST日期": "2024-02-10",
     "结束ST日期": "2024-05-28", "摘帽前涨幅": 2.3, "摘帽后涨幅": 8.9,
     "市盈率": 15.2, "市净率": 2.7, "收盘价": 9.16},
    {"股票名称": "演示-ST 环保", "代码": "sz.000826", "开始ST日期": "2024-04-01",
     "结束ST日期": "2024-10-18", "摘帽前涨幅": 11.6, "摘帽后涨幅": -12.4,
     "市盈率": -5.9, "市净率": 1.1, "收盘价": 2.74},
    {"股票名称": "演示-ST 隆鑫", "代码": "sh.601363", "开始ST日期": "2023-12-08",
     "结束ST日期": "2024-06-20", "摘帽前涨幅": 4.8, "摘帽后涨幅": 3.2,
     "市盈率": 18.4, "市净率": 1.9, "收盘价": 6.58},
    {"股票名称": "演示-ST 佳电", "代码": "sz.000922", "开始ST日期": "2024-05-12",
     "结束ST日期": "2024-12-30", "摘帽前涨幅": -2.6, "摘帽后涨幅": 15.7,
     "市盈率": 40.2, "市净率": 3.1, "收盘价": 8.42},
    {"股票名称": "演示-ST 南化", "代码": "sh.600228", "开始ST日期": "2024-03-01",
     "结束ST日期": "2024-09-03", "摘帽前涨幅": 6.9, "摘帽后涨幅": -4.1,
     "市盈率": 12.6, "市净率": 1.5, "收盘价": 4.19},
    {"股票名称": "演示-*ST 雪发", "代码": "sz.002485", "开始ST日期": "2024-07-01",
     "结束ST日期": "2025-01-15", "摘帽前涨幅": -5.5, "摘帽后涨幅": 18.3,
     "市盈率": 27.8, "市净率": 2.3, "收盘价": 11.07},
]

@router.post("/st/scan", response_model=DataResponse)
@audit_action(CATEGORY_ST_SCAN, "ST摘帽扫描（回溯 {payload.months_back} 个月）",
              capture_response=False,
              target_key=lambda u, p, r, e: f"mb={p.months_back if p else None}")
async def st_scan(params: STScanParams,
                  request: Request,
                  user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    cache = CacheLayer.instance()
    key = _cache_key("st-scan-v3", months_back=params.months_back,
                     before_days=params.before_days, after_days=params.after_days)
    cached = cache.get_json(key)
    if cached is not None:
        return DataResponse(data=cached, cache_hit=True, message="使用缓存")

    # 优先使用预计算数据（baostock 不可达时的可靠数据源）
    precomputed = _load_precomputed_st_scan()
    if precomputed is not None:
        records = precomputed.get("records", [])
        logs = precomputed.get("logs", [])
        # 如果有 records 就直接返回，不再等 baostock 超时
        result: Dict[str, Any] = {"records": records, "logs": logs[-20:]}
        cache.set_json(key, result, ex=3600 * 6)
        msg = f"扫描 {len(records)} 条记录（预计算数据）"
        return DataResponse(data=result, message=msg)

    # baostock 回退（生产环境直连可用时）
    ms = get_ms()
    logs: list[str] = []
    loop = asyncio.get_running_loop()

    def _prog(msg):
        logs.append(str(msg))

    def _run():
        return ms.scan_st(params.months_back, params.before_days, params.after_days,
                          progress_cb=_prog)

    is_demo = False
    try:
        records = await asyncio.wait_for(
            loop.run_in_executor(None, _run), timeout=600.0)
    except (Exception, asyncio.TimeoutError) as exc:
        # baostock 不可达 / 超时 -> 演示数据，按钮不崩
        records = list(_ST_SCAN_DEMO)
        logs.append(f"[演示数据] baostock 不可达或超时: {exc}")
        is_demo = True
    # baostock 可达但扫描结果为空（无匹配数据）时也回退演示数据
    if not is_demo and not records:
        records = list(_ST_SCAN_DEMO)
        logs.append("[演示数据] 扫描结果为空，输出演示数据展示")
        is_demo = True
    result: Dict[str, Any] = {"records": records, "logs": logs[-20:]}
    if not is_demo:
        cache.set_json(key, result, ex=3600 * 6)
    msg = f"扫描 {len(records)} 条记录" + ("（演示数据）" if is_demo else "")
    return DataResponse(data=result, message=msg)


# ---------- ST 摘帽：管理员后台维护（输入股票代码自动加入列表）----------
@router.get("/st/list", response_model=DataResponse)
async def st_list():
    """公开：返回预计算文件中所有 ST 摘帽记录（管理员后台维护）。"""
    records = st_data_service.list_records()
    return DataResponse(data={"records": records, "total": len(records)},
                       message=f"共 {len(records)} 条")


@router.post("/st/add", response_model=DataResponse)
@audit_action(CATEGORY_ST_SCAN, "管理员添加ST摘帽股票 {payload.code}",
              capture_response=False,
              target_key=lambda u, p, r, e: f"code={p.code if p else None}")
async def st_add(payload: STAddParams,
                 request: Request,
                 admin: Dict[str, Any] = Depends(get_current_admin)):
    """管理员：输入股票代码 -> 自动抓取巨潮撤销ST公告 + 新浪K线 + 实时价，
    计算摘帽前后 [5,10,15,20] 交易日涨幅，写入预计算文件。代码已存在则覆盖更新。
    """
    loop = asyncio.get_running_loop()
    try:
        rec = await asyncio.wait_for(
            loop.run_in_executor(None,
                lambda: st_data_service.add_stock(payload.code)),
            timeout=120.0)
    except asyncio.TimeoutError:
        raise HTTPException(504, "抓取超时（巨潮/新浪响应慢），请稍后重试")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"添加失败: {e}")
    # 清除 /st/scan 缓存，让公开页能立即看到新数据
    try:
        CacheLayer.instance().delete("webstock:st-scan-v3:*")
    except Exception:
        pass
    return DataResponse(
        data=rec,
        message=f"已添加 {rec.get('股票名称')}({rec.get('代码')}) 摘帽日={rec.get('结束ST日期')}")


@router.delete("/st/{code}", response_model=DataResponse)
@audit_action(CATEGORY_ST_SCAN, "管理员删除ST摘帽股票 {code}",
              capture_response=False,
              target_key=lambda u, p, r, e, code=None: f"code={code}")
async def st_delete(code: str,
                    request: Request,
                    admin: Dict[str, Any] = Depends(get_current_admin)):
    """管理员：从预计算文件中删除一只股票。"""
    loop = asyncio.get_running_loop()
    try:
        ok = await loop.run_in_executor(
            None, lambda: st_data_service.delete_stock(code))
    except Exception as e:
        raise HTTPException(500, f"删除失败: {e}")
    if not ok:
        raise HTTPException(404, f"未找到该股票: {code}")
    try:
        CacheLayer.instance().delete("webstock:st-scan-v3:*")
    except Exception:
        pass
    return DataResponse(message=f"已删除 {code}")


# ---------- ST 恢复上市（公开：当前 ST 股票 + 可申请摘帽日）----------
_ST_TIME_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "st_time_results.json")


def _load_st_time_cache() -> Optional[Dict[str, Any]]:
    try:
        if os.path.isfile(_ST_TIME_FILE):
            with open(_ST_TIME_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict) and isinstance(d.get("records"), list):
                    return d
    except Exception:
        pass
    return None


@router.get("/st/time", response_model=DataResponse)
async def st_time(refresh: bool = Query(False)):
    """公开：返回当前交易中的 ST 股票列表 + ST 开始日期 + 可申请摘帽日。

    性能原则（重要！）：
      - 默认请求绝不触发实时扫描，只读预计算文件（每周日 0 点由定时脚本刷新）。
      - 只有显式 ?refresh=1 才会实时爬新浪/巨潮（约 30s，建议仅运维用）。
      - 预计算文件不存在时返回空 + 提示，避免前端卡死 30s 超时。
    """
    cache = CacheLayer.instance()
    cache_key = "webstock:st-time:refresh=" + str(refresh)
    cached = cache.get_json(cache_key)
    if cached is not None:
        return DataResponse(data=cached, cache_hit=True, message="使用缓存")

    pre = _load_st_time_cache()

    if pre:
        # 有预计算文件 → 返回（无论 refresh 与否都直接用，避免重复扫描）
        data = {"records": pre["records"], "logs": pre.get("logs", [])}
        cache.set_json(cache_key, data, ex=3600 * 6)
        return DataResponse(data=data, message=f"扫描 {len(pre['records'])} 条（预计算）")

    if not refresh:
        # 无文件且用户没要求 refresh → 直接返回空，不扫描
        # 给运维提示运行 refresh_all.py 或带 ?refresh=1 手动构建
        tip = (
            "数据文件未就绪，请联系管理员在服务器上运行: "
            "python3 /workspace/tmp_script/refresh_all.py --no-delay  "
            "（每周日 0 点定时脚本会自动刷新）"
        )
        empty = {"records": [], "logs": [tip, "当前线上 backend/data/st_time_results.json 不存在"]}
        # 这个空结果也缓存 5 分钟，避免反复撞墙
        cache.set_json(cache_key, empty, ex=300)
        return DataResponse(data=empty, message="数据未就绪，请稍后再试")

    # refresh=true 且无文件 → 实时扫描（约 30s，仅运维用）
    loop = asyncio.get_running_loop()
    try:
        records = await asyncio.wait_for(
            loop.run_in_executor(None, st_time_service.scan_all),
            timeout=180.0)
    except (Exception, asyncio.TimeoutError) as exc:
        return DataResponse(
            data={"records": [], "logs": [f"实时扫描失败: {exc}"]},
            message="实时扫描失败")

    # 扫描成功 → 写入预计算文件 + 返回
    try:
        os.makedirs(os.path.dirname(_ST_TIME_FILE), exist_ok=True)
        import json as _json
        with open(_ST_TIME_FILE, "w", encoding="utf-8") as f:
            _json.dump({"records": records, "logs": []}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        records = records  # 扫描结果照样返回，写入失败只记日志
        print(f"[st/time] 写入预计算文件失败: {e}", flush=True)

    data = {"records": records, "logs": ["实时扫描（refresh=1）"]}
    cache.set_json(cache_key, data, ex=3600 * 6)
    return DataResponse(data=data, message=f"扫描 {len(records)} 条（实时）")


@router.post("/st-reinstate/scan", response_model=DataResponse)
@audit_action(CATEGORY_ST_REINSTATE_SCAN, "ST 恢复上市扫描（回溯 {payload.months_back} 个月）",
              capture_response=False)
async def st_reinstate_scan(params: GenericScanParams,
                            request: Request,
                            user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    cache = CacheLayer.instance()
    key = _cache_key("st-reinstate", months_back=params.months_back)
    cached = cache.get_json(key)
    if cached is not None:
        return DataResponse(data=cached, cache_hit=True, message="使用缓存")

    ms = get_ms()
    loop = asyncio.get_running_loop()
    logs: list[str] = []
    is_demo = False
    try:
        # 长任务：给足 120s
        records = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: ms.scan_st_reinstate(params.months_back, progress_cb=logs.append)),
            timeout=120.0)
    except (Exception, asyncio.TimeoutError) as exc:
        demo = [
            {"股票名称": "演示-退市国发", "代码": "sh.600001",
             "ST开始日期": "2023-12-01", "可申请摘帽日": "2024-12-02",
             "股价": 1.23, "净资产": 2.05, "市盈率": -18.5,
             "市净率": 0.6, "量比": 1.25, "换手": 0.9},
        ]
        records = demo
        logs.append(f"[演示数据] baostock 不可达或超时: {exc}")
        is_demo = True
    result: Dict[str, Any] = {"records": records, "logs": logs[-20:]}
    if not is_demo:
        cache.set_json(key, result, ex=3600 * 6)
    msg = f"扫描 {len(records)} 条" + ("（演示数据）" if is_demo else "")
    return DataResponse(data=result, message=msg)


# ---------- 市场温度计（只读：不审计，避免仪表板每次打开都刷日志）----------
@router.get("/thermometer", response_model=DataResponse)
async def thermometer():
    cache = CacheLayer.instance()
    key = "webstock:thermometer:v1"
    data = cache.get_json(key)
    if data is not None:
        return DataResponse(data=data, cache_hit=True)
    ms = get_ms()
    loop = asyncio.get_running_loop()
    try:
        data = await asyncio.wait_for(
            loop.run_in_executor(None, ms.market_thermometer),
            timeout=15.0)
    except (Exception, asyncio.TimeoutError) as exc:
        # baostock 不可达/超时：返回演示数据
        data = {"percent": 52, "level": "normal", "above_count": 2600,
                "total": 5000, "date": "演示数据",
                "message": f"baostock 不可达，显示演示数据: {exc}"}
    if data:
        cache.set_json(key, data, ex=60 * 15)
    return DataResponse(data=data)


# ---------- 板块热度 ----------
@router.post("/sector-heat", response_model=DataResponse)
@audit_action(CATEGORY_SECTOR_HEAT, "板块热度查询（交易日 {payload.trade_date|今天}）",
              capture_response=False)
async def sector_heat(params: MarketDateParams,
                      request: Request,
                      user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    cache = CacheLayer.instance()
    key = _cache_key("sector-heat", td=params.trade_date)
    if params.use_cache:
        data = cache.get_json(key)
        if data is not None:
            return DataResponse(data=data, cache_hit=True)
    ms = get_ms()
    loop = asyncio.get_running_loop()
    logs: list[str] = []
    rows = await loop.run_in_executor(
        None,
        lambda: ms.sector_heat(params.trade_date, params.use_cache, logs.append))
    result = {"rows": rows, "logs": logs[-20:]}
    cache.set_json(key, result, ex=3600 * 6)
    return DataResponse(data=result)


# ---------- 热门股票 ----------
@router.post("/hot-stocks", response_model=DataResponse)
@audit_action(CATEGORY_HOT_STOCKS, "热门股票：按 {payload.sort_by} Top {payload.top_n}",
              capture_response=False)
async def hot_stocks(params: HotStocksParams,
                     request: Request,
                     user: Optional[Dict[str, Any]] = Depends(get_current_user_or_none)):
    cache = CacheLayer.instance()
    key = _cache_key("hot-stocks", td=params.trade_date, sort=params.sort_by,
                     top=params.top_n, kw=params.filter_keyword)
    if params.use_cache:
        data = cache.get_json(key)
        if data is not None:
            return DataResponse(data=data, cache_hit=True)
    ms = get_ms()
    loop = asyncio.get_running_loop()
    logs: list[str] = []
    rows = await loop.run_in_executor(
        None,
        lambda: ms.hot_stocks(params.trade_date, params.sort_by, params.top_n,
                              params.filter_keyword, params.use_cache, logs.append))
    result = {"rows": rows, "logs": logs[-20:]}
    cache.set_json(key, result, ex=3600 * 6)
    return DataResponse(data=result)
