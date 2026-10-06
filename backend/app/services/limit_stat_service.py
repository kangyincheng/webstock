"""历史涨跌停统计 service。

数据源：akshare（主力）、baostock（备选基础行情）、tushare（备选基础行情）。
核心逻辑：
  1. 扫描过去 N 个交易日的涨停池 + 跌停池（东方财富数据源）
  2. 统计每只股票的涨停次数 / 跌停次数
  3. 获取基础信息：收盘价、PE、PB、总股本、总市值
  4. 判定涨跌停百分比（主板 10%、科创/创业 20%、北交所 30%、ST 5%）

结果写入 backend/data/limit_results.json，由 refresh_all.py 定时刷新。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from typing import Any, Dict, List, Optional

import pandas as pd

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA_DIR = os.path.join(BASE_DIR, "backend", "data")


# ============================================================
# 涨跌停幅度判定
# ============================================================

def get_limit_pct(code: str, name: str = "") -> float:
    """根据股票代码判定涨跌停幅度（%）。

    规则：
      - 300xxx / 301xxx 创业板 → 20%
      - 688xxx 科创板 → 20%
      - 8xxxxx / 4xxxxx 北交所 → 30%
      - ST / *ST 股票 → 5%
      - 其他（主板 600/000/001/002/003） → 10%
    """
    code = str(code).strip()
    name = str(name) if name else ""

    # ST 判定（名称里含 ST 但不含 ST摘帽/去ST/摘ST）
    if "ST" in name.upper() and "摘" not in name and "去" not in name:
        return 5.0

    pure = code.split(".")[-1] if "." in code else code

    if pure.startswith(("300", "301")):
        return 20.0
    if pure.startswith("688"):
        return 20.0
    if pure.startswith(("8", "4")):
        return 30.0
    # 北交所 920 开头也可能
    if pure.startswith("920"):
        return 30.0
    return 10.0


def get_market_name(code: str) -> str:
    pure = str(code).split(".")[-1] if "." in code else str(code)
    if pure.startswith(("300", "301")):
        return "创业板"
    if pure.startswith("688"):
        return "科创板"
    if pure.startswith(("8", "4", "920")):
        return "北交所"
    return "主板"


# ============================================================
# 交易日历（简单版：跳过周末）
# ============================================================

def _iter_trade_dates(n_days: int = 90) -> List[str]:
    """往前推 n_days 个自然日里的交易日（简单跳过周末，忽略法定假日）。"""
    today = dt.date.today()
    dates = []
    offset = 0
    while len(dates) < n_days:
        d = today - dt.timedelta(days=offset)
        # 跳过周末
        if d.weekday() < 5:
            dates.append(d.strftime("%Y%m%d"))
        offset += 1
    return dates


# ============================================================
# akshare 数据源封装
# ============================================================

def _try_import_akshare():
    try:
        import akshare as ak
        return ak
    except ImportError:
        return None


def _try_import_baostock():
    try:
        import baostock as bs
        return bs
    except ImportError:
        return None


def _try_import_tushare():
    try:
        import tushare as ts
        return ts
    except ImportError:
        return None


def fetch_limit_pools_ak(trade_dates: List[str], progress_cb=None):
    """用 akshare 扫描涨停池 + 跌停池。

    返回 (counts, info_map):
      counts:  { code: {"涨停": int, "跌停": int} }
      info_map:{ code: {"股票名称", "收盘价", "流通市值", "总市值", "PE", "所属行业"} }

    基本信息直接从涨跌停池里提取（涨停池/跌停池都自带名称、最新价、市值），
    这样就不依赖 stock_zh_a_spot_em（东方财富实时行情接口在容器里经常连不上）。
    """
    ak = _try_import_akshare()
    if ak is None:
        raise RuntimeError("akshare 未安装")

    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"涨停": 0, "跌停": 0})
    info_map: Dict[str, Dict[str, Any]] = {}  # code -> 基本信息（保留最新一天的值）

    def _merge_row(row: dict, code: str, src: str):
        """从涨跌停池的一行里提取基本信息，合并进 info_map。"""
        cur = info_map.get(code, {})
        # 名称、最新价、市值 —— 用最后一次出现的（最近的交易日）
        if row.get("名称"):
            cur["股票名称"] = str(row["名称"]).strip()
        if row.get("最新价") is not None:
            cur["收盘价"] = _to_float(row.get("最新价"))
        if row.get("流通市值") is not None:
            cur["流通市值"] = _to_float(row.get("流通市值"))
        if row.get("总市值") is not None:
            cur["总市值"] = _to_float(row.get("总市值"))
        if row.get("成交额") is not None:
            cur["成交额"] = _to_float(row.get("成交额"))
        if row.get("所属行业"):
            cur["所属行业"] = str(row["所属行业"]).strip()
        # PE —— 只有跌停池有"动态市盈率"列
        pe_key = "动态市盈率" if src == "dt" else None
        if pe_key and row.get(pe_key) is not None:
            cur["PE"] = _to_float(row.get(pe_key))
        info_map[code] = cur

    for i, date_str in enumerate(trade_dates):
        if progress_cb:
            progress_cb(f"扫描涨停/跌停池 {i+1}/{len(trade_dates)}: {date_str}")

        # 涨停池
        try:
            df_zt = ak.stock_zt_pool_em(date=date_str)
            if df_zt is not None and not df_zt.empty:
                for _, row in df_zt.iterrows():
                    key = str(row.get("代码", "")).strip()
                    if key:
                        counts[key]["涨停"] += 1
                        _merge_row(dict(row), key, src="zt")
        except Exception:
            time.sleep(0.6)
            pass

        time.sleep(0.15)

        # 跌停池
        try:
            df_dt = ak.stock_zt_pool_dtgc_em(date=date_str)
            if df_dt is not None and not df_dt.empty:
                for _, row in df_dt.iterrows():
                    key = str(row.get("代码", "")).strip()
                    if key:
                        counts[key]["跌停"] += 1
                        _merge_row(dict(row), key, src="dt")
        except Exception:
            time.sleep(0.6)
            pass

        time.sleep(0.3)

    return counts, info_map


def fetch_basic_info_ak() -> pd.DataFrame:
    """用 akshare 获取全市场 A 股基本信息（东方财富实时行情）。

    返回 DataFrame:
      columns: 代码, 名称, 最新价, 涨跌幅, 市盈率-动态, 市净率, 总股本, 总市值, 流通市值 ...
    """
    ak = _try_import_akshare()
    if ak is None:
        return pd.DataFrame()
    try:
        df = ak.stock_zh_a_spot_em()
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        print(f"[limit_stat] akshare.stock_zh_a_spot_em 失败: {e}", flush=True)
        return pd.DataFrame()


# ============================================================
# 主流程
# ============================================================

def scan(n_days: int = 90,
         data_sources: Optional[List[str]] = None,
         progress_cb=None) -> List[Dict[str, Any]]:
    """执行完整的历史涨跌停统计。

    Args:
        n_days: 往前扫描多少个交易日（默认 90 ≈ 4.5 个月）
        data_sources: 备用列表 ["baostock", "tushare"]，默认用 akshare 主力
        progress_cb: 进度回调函数 progress_cb(msg: str)

    Returns:
        按涨停次数降序排列的记录列表
    """
    if data_sources is None:
        data_sources = ["baostock", "tushare"]

    # ---- Step 1: 扫描涨跌停池（同时拿基本信息）----
    trade_dates = _iter_trade_dates(n_days)
    if progress_cb:
        progress_cb(f"准备扫描 {len(trade_dates)} 个交易日")

    counts, info_map = fetch_limit_pools_ak(trade_dates, progress_cb=progress_cb)
    if progress_cb:
        progress_cb(f"涨跌停池扫描完成：{len(counts)} 只股票有记录，{len(info_map)} 只有基本信息")

    # ---- Step 2: 尝试用 stock_zh_a_spot_em 补充更多字段（PB、总股本等）----
    # 这个接口经常连不上（sandbox 代理 + production 容器无外网），
    # 连不上也不影响，核心字段都在 info_map 里了
    extra_map: Dict[str, Dict[str, Any]] = {}
    basic_df = fetch_basic_info_ak()
    if not basic_df.empty:
        for _, row in basic_df.iterrows():
            code = str(row.get("代码", "")).strip()
            if not code:
                continue
            extra_map[code] = {
                "PB": _to_float(row.get("市净率")),
                "总股本": _to_float(row.get("总股本")),
                "PE_full": _to_float(row.get("市盈率-动态")),
            }
        if progress_cb:
            progress_cb(f"补充信息拿到 {len(extra_map)} 只（PB/总股本）")

    # ---- Step 3: 合并 ----
    records: List[Dict[str, Any]] = []
    for code in set(counts.keys()) | set(info_map.keys()):
        base = info_map.get(code, {})
        extra = extra_map.get(code, {})
        c = counts.get(code, {"涨停": 0, "跌停": 0})
        name = base.get("股票名称", "")
        limit_pct = get_limit_pct(code, name)

        # PE 优先用完整行情接口的，没有就用跌停池里的"动态市盈率"
        pe = extra.get("PE_full") or base.get("PE")

        records.append({
            "股票名称": name or "",
            "股票代码": code,
            "收盘价": base.get("收盘价"),
            "涨停次数": c.get("涨停", 0),
            "跌停次数": c.get("跌停", 0),
            "涨跌停幅度(%)": limit_pct,
            "板块": get_market_name(code),
            "PE": pe,
            "PB": extra.get("PB"),
            "总股本": extra.get("总股本"),
            "总市值": base.get("总市值"),
            "流通市值": base.get("流通市值"),
            "所属行业": base.get("所属行业", ""),
        })

    # ---- Step 4: 默认按涨停次数降序 ----
    records.sort(key=lambda x: (-x["涨停次数"], -x["跌停次数"], x["股票代码"]))
    return records


def _to_float(val) -> Optional[float]:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except Exception:
        return None


# ============================================================
# 文件持久化（和 tender_results.json 同模式）
# ============================================================

RESULT_FILE = os.path.join(DATA_DIR, "limit_results.json")


def save_results(records: List[Dict[str, Any]], n_days: int) -> str:
    """原子写 limit_results.json，返回文件路径。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).astimezone(
        dt.timezone(dt.timedelta(hours=8))
    ).strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "records": records,
        "scanned_days": n_days,
        "updated_at": now,
        "total": len(records),
    }
    tmp = RESULT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, RESULT_FILE)
    return RESULT_FILE


def load_results() -> Optional[Dict[str, Any]]:
    if not os.path.isfile(RESULT_FILE):
        return None
    try:
        with open(RESULT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ============================================================
# CLI 入口（refresh_all.py 调用）
# ============================================================

def run_cli(n_days: int = 90):
    """命令行入口，用于 refresh_all.py --run limit_stat。"""
    import logging
    log = logging.getLogger("limit_stat")

    def prog(msg: str):
        log.info(msg)
        print(msg, flush=True)

    prog(f"[limit_stat] 开始扫描，最近 {n_days} 个交易日")
    t0 = time.time()

    records = scan(n_days=n_days, progress_cb=prog)

    path = save_results(records, n_days)
    elapsed = time.time() - t0

    prog(f"[limit_stat] 完成：{len(records)} 条记录 → {path}（耗时 {elapsed:.1f}s）")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    try:
        ok = run_cli(n_days=days)
        sys.exit(0 if ok else 1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
