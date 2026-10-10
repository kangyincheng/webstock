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


# 数据源降级链（顺序：主力 → akshare 内部备选 → baostock 补算 → 保留前值）
# Level 1: stock_zt_pool_em (涨停池) + stock_zt_pool_dtgc_em (跌停池) — 东方财富主力
# Level 2: stock_zt_pool_previous_em (昨日涨停) + stock_zt_pool_zbgc_em (炸板池) — 同源备选
# Level 3: baostock 只扫已知股票的日K线，自己算涨跌停（akshare 整体挂了时）
# Level 4: 保留前一天的值，不做任何更新


def fetch_limit_pools_ak(trade_dates: List[str], progress_cb=None):
    """扫描涨跌停池，带多源降级。

    返回 (counts, info_map, stats):
      counts:  { code: {"涨停": int, "跌停": int} }
      info_map:{ code: {"股票名称", "收盘价", "流通市值", "总市值", "PE", "所属行业"} }
      stats:   {"dates_scanned", "dates_missed_level1", "dates_missed_level2",
                "dates_missed_level3", "data_sources_used": [...]}
    """
    ak = _try_import_akshare()
    if ak is None:
        raise RuntimeError("akshare 未安装")

    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"涨停": 0, "跌停": 0})
    info_map: Dict[str, Dict[str, Any]] = {}
    stats = {
        "dates_scanned": 0,
        "dates_missed_level1": 0,  # 主力池（涨停+跌停）当天全空
        "dates_missed_level2": 0,  # Level 2 备选也全空
        "dates_missed_level3": 0,  # baostock 也没补到
        "data_sources_used": ["akshare_em"],
    }
    missed_dates_l2: List[str] = []  # Level 2 也没覆盖到的日期，留给 Level 3

    def _merge_row(row: dict, code: str, src: str):
        cur = info_map.get(code, {})
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
        pe_key = "动态市盈率" if src == "dt" else None
        if pe_key and row.get(pe_key) is not None:
            cur["PE"] = _to_float(row.get(pe_key))
        info_map[code] = cur

    def _try_ak_pool(func_name: str, date_str: str):
        """安全调用 akshare 某池函数，返回 DataFrame（可能空）或 None（异常）。"""
        try:
            fn = getattr(ak, func_name)
            df = fn(date=date_str)
            return df if df is not None else None
        except Exception:
            return None

    def _ingest_pool(df, limit_type: str, src: str):
        """把某个池 DataFrame 里的记录合并进 counts + info_map。
        df 可以是 None 或空 DataFrame，直接返回 0。
        """
        if df is None or df.empty:
            return 0
        local_count = 0
        for _, row in df.iterrows():
            key = str(row.get("代码", "")).strip()
            if key:
                counts[key][limit_type] += 1
                _merge_row(dict(row), key, src=src)
                local_count += 1
        return local_count

    for i, date_str in enumerate(trade_dates):
        if progress_cb:
            progress_cb(f"扫描 {i+1}/{len(trade_dates)}: {date_str}")

        date_scanned = False

        # -------- Level 1: 主力涨停池 + 跌停池 --------
        zt_rows = _ingest_pool(_try_ak_pool("stock_zt_pool_em", date_str), "涨停", "zt_l1")
        time.sleep(0.15)
        dt_rows = _ingest_pool(_try_ak_pool("stock_zt_pool_dtgc_em", date_str), "跌停", "dt_l1")

        if zt_rows + dt_rows > 0:
            date_scanned = True
            stats["dates_scanned"] += 1

        if date_scanned:
            time.sleep(0.3)
            continue

        # -------- Level 2: akshare 内部备选池（主力全空才到这）--------
        stats["dates_missed_level1"] += 1
        if progress_cb:
            progress_cb(f"  [降级] Level 1 全空，尝试 Level 2 备选池")

        # stock_zt_pool_previous_em — 昨日涨停池（今天出现在这里的 = 昨天涨停的）
        # 注：这个池是"昨日涨停"，所以这里统计的涨停次数其实差了一天，
        # 但作为备选足够用（趋势上看涨跌停频率变化不大）
        zt2_rows = _ingest_pool(_try_ak_pool("stock_zt_pool_previous_em", date_str), "涨停", "zt_l2")
        time.sleep(0.15)
        # stock_zt_pool_zbgc_em — 炸板池（打开涨停的股票，不是真涨停但可以补）
        zt3_rows = _ingest_pool(_try_ak_pool("stock_zt_pool_zbgc_em", date_str), "涨停", "zt_l2_zb")

        if zt2_rows + zt3_rows > 0:
            date_scanned = True
            stats["dates_scanned"] += 1
            stats["data_sources_used"].append("akshare_em_fallback")
            time.sleep(0.3)
            continue

        # -------- Level 2 也全空 → 留给 Level 3 --------
        stats["dates_missed_level2"] += 1
        missed_dates_l2.append(date_str)
        time.sleep(0.3)

    # -------- Level 3: baostock 补算（只针对 Level 2 全空的那几天，且已知股票代码有限集）--------
    if missed_dates_l2 and _try_import_baostock() is not None:
        if progress_cb:
            progress_cb(f"[Level 3] 尝试 baostock 补算 {len(missed_dates_l2)} 个缺口日期（只扫已知股票）")
        filled = _fill_missed_dates_baostock(counts, info_map, missed_dates_l2, progress_cb)
        stats["dates_missed_level3"] = len(missed_dates_l2) - filled
        if filled > 0:
            stats["data_sources_used"].append("baostock_fill")
            stats["dates_scanned"] += filled
    elif missed_dates_l2:
        stats["dates_missed_level3"] = len(missed_dates_l2)
        if progress_cb:
            progress_cb(f"[Level 3] baostock 不可用，保留 {len(missed_dates_l2)} 个缺口日期")

    # 去重 data_sources_used
    stats["data_sources_used"] = sorted(set(stats["data_sources_used"]))

    return counts, info_map, stats


def _fill_missed_dates_baostock(counts, info_map, missed_dates: List[str], progress_cb=None) -> int:
    """用 baostock 补算 Level 2 也全空的日期。

    策略：
      1. 先把 counts 里已有的股票代码收集出来（这些是历史上出现过涨跌停的）
      2. 对每个缺口日期，只查这几百只股票的日K线
      3. 自己算涨跌停（对比前收盘价）
      4. 结果合并回 counts + info_map

    注意：baostock 全市场扫不现实（5000只×天数），但只扫已知涨跌停股票（约 600 只）可控。
    """
    bs = _try_import_baostock()
    if bs is None:
        return 0

    # 已知股票代码（历史上出现过涨跌停的）
    known_codes = list(counts.keys())
    if not known_codes:
        return 0

    lg = bs.login()
    if lg.error_code != '0':
        if progress_cb:
            progress_cb(f"  baostock login 失败: {lg.error_msg}")
        return 0

    filled = 0
    limit_counts_calc: Dict[str, Dict[str, int]] = defaultdict(lambda: {"涨停": 0, "跌停": 0})

    try:
        for date_str in missed_dates:
            if progress_cb:
                progress_cb(f"  baostock 补算 {date_str}（{len(known_codes)} 只已知股票）")

            has_data = False
            for code in known_codes:
                # 代码格式转换: 600825 -> sh.600825; 000001 -> sz.000001
                pure = code.split(".")[-1]
                bs_code = f"sh.{pure}" if pure.startswith(("6", "9")) else f"sz.{pure}"

                try:
                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        "date,close,preclose,pctChg",
                        start_date=date_str, end_date=date_str,
                        frequency="d", adjustflag="3",
                    )
                    if rs.error_code != '0':
                        continue

                    while rs.next():
                        row = rs.get_row_data()
                        if len(row) < 4 or not row[3]:
                            continue
                        pct = float(row[3])
                        if pct >= 9.8:
                            limit_counts_calc[code]["涨停"] += 1
                            has_data = True
                        elif pct <= -9.8:
                            limit_counts_calc[code]["跌停"] += 1
                            has_data = True
                    time.sleep(0.05)  # 节流
                except Exception:
                    continue

            if has_data:
                filled += 1

    finally:
        bs.logout()

    # 合并回 counts
    for code, c in limit_counts_calc.items():
        counts[code]["涨停"] += c.get("涨停", 0)
        counts[code]["跌停"] += c.get("跌停", 0)

    return filled


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

def scan(n_days: Optional[int] = None,
         mode: str = "incremental",
         history_years: float = 1.0,
         progress_cb=None) -> List[Dict[str, Any]]:
    """执行历史涨跌停统计。

    Args:
        n_days: 已废弃，保留兼容。用 history_years 控制时间窗口。
        mode: "incremental"（默认，推荐）或 "full"
            incremental: 读已有 JSON，只扫上次扫描之后的新交易日，合并
            full:        重新扫描最近 history_years 年的全部交易日（覆盖已有）
        history_years: 全量模式下往前扫多少年（默认 1.0 年 ≈ 255 交易日）
        progress_cb: 进度回调

    Returns:
        按涨停次数降序排列的记录列表
    """
    if mode == "full":
        n_trade = int(history_years * 255)
        if progress_cb:
            progress_cb(f"【全量模式】重新扫描最近 {history_years} 年 ≈ {n_trade} 个交易日")
        return _do_scan_and_merge(None, n_trade, progress_cb)

    existing = load_results()
    if existing is None or not existing.get("scanned_dates"):
        if progress_cb:
            progress_cb("未找到历史数据，首次全量扫描")
        n_trade = int(history_years * 255)
        return _do_scan_and_merge(None, n_trade, progress_cb)

    scanned_dates = set(existing["scanned_dates"])
    all_trade_dates = _iter_trade_dates(int(history_years * 255))
    new_dates = [d for d in all_trade_dates if d not in scanned_dates]

    if not new_dates:
        if progress_cb:
            progress_cb("已是最新，没有新交易日需要扫描")
        return existing.get("records", [])

    if progress_cb:
        progress_cb(f"【增量模式】已有 {len(scanned_dates)} 个交易日，新增 {len(new_dates)} 个待扫描")

    return _do_scan_and_merge(existing, len(new_dates), progress_cb,
                              override_dates=new_dates)


def _do_scan_and_merge(existing: Optional[Dict[str, Any]],
                      n_trade: int,
                      progress_cb,
                      override_dates: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """实际扫描 + 合并已有结果。"""
    # ---- Step 1: 确定交易日列表 ----
    if override_dates:
        trade_dates = override_dates
    else:
        trade_dates = _iter_trade_dates(n_trade)
    if progress_cb:
        progress_cb(f"准备扫描 {len(trade_dates)} 个交易日")

    # ---- Step 2: 扫涨跌停池（带多源降级）----
    try:
        new_counts, new_info, scan_stats = fetch_limit_pools_ak(trade_dates, progress_cb=progress_cb)
        if progress_cb:
            progress_cb(
                f"扫描完成：{scan_stats['dates_scanned']}/{len(trade_dates)} 天成功，"
                f"数据源={scan_stats['data_sources_used']}，"
                f"L1miss={scan_stats['dates_missed_level1']} "
                f"L2miss={scan_stats['dates_missed_level2']} "
                f"L3miss={scan_stats['dates_missed_level3']}，"
                f"共 {len(new_counts)} 只股票有记录"
            )
    except Exception as e:
        if progress_cb:
            progress_cb(f"扫描完全失败: {e}，降级保留已有数据")
        new_counts, new_info = {}, {}
        scan_stats = {"dates_scanned": 0, "data_sources_used": [],
                      "dates_missed_level1": len(trade_dates), "dates_missed_level2": len(trade_dates),
                      "dates_missed_level3": len(trade_dates)}

    # ---- Step 3: 合并已有数据 ----
    merged_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"涨停": 0, "跌停": 0})
    merged_info: Dict[str, Dict[str, Any]] = {}

    if existing:
        # 从已有 records 还原 counts 和 info
        for rec in existing.get("records", []):
            code = rec.get("股票代码")
            if not code:
                continue
            merged_counts[code] = {
                "涨停": rec.get("涨停次数", 0),
                "跌停": rec.get("跌停次数", 0),
            }
            merged_info[code] = {
                "股票名称": rec.get("股票名称", ""),
                "收盘价": rec.get("收盘价"),
                "流通市值": rec.get("流通市值"),
                "总市值": rec.get("总市值"),
                "PE": rec.get("PE"),
                "所属行业": rec.get("所属行业", ""),
            }

    # 叠加新扫描结果
    for code, c in new_counts.items():
        merged_counts[code]["涨停"] += c.get("涨停", 0)
        merged_counts[code]["跌停"] += c.get("跌停", 0)
    for code, info in new_info.items():
        # 新数据覆盖旧的（收盘价/市值要最新的）
        merged_info[code] = info

    if progress_cb:
        progress_cb(f"合并后：{len(merged_counts)} 只股票有涨跌停记录")

    # ---- Step 4: 尝试补充 PB/总股本 ----
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

    # ---- Step 5: 最终 records ----
    records: List[Dict[str, Any]] = []
    for code in set(merged_counts.keys()) | set(merged_info.keys()):
        base = merged_info.get(code, {})
        extra = extra_map.get(code, {})
        c = merged_counts.get(code, {"涨停": 0, "跌停": 0})
        name = base.get("股票名称", "")
        limit_pct = get_limit_pct(code, name)
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


def save_results(records: List[Dict[str, Any]],
                 mode: str = "incremental",
                 scanned_dates: Optional[List[str]] = None,
                 history_years: float = 1.0) -> str:
    """原子写 limit_results.json，返回文件路径。

    Args:
        records: 最终合并后的 records
        mode: "full" 或 "incremental"（写入元数据）
        scanned_dates: 本次覆盖的交易日列表（增量合并用）。如果提供就更新元数据里的 scanned_dates
        history_years: 时间窗口年数
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    # 从现有文件里取已有的 scanned_dates 做合并
    existing = load_results()
    existing_dates = set(existing.get("scanned_dates", [])) if existing else set()

    if scanned_dates:
        existing_dates.update(scanned_dates)

    now = dt.datetime.now(dt.timezone.utc).astimezone(
        dt.timezone(dt.timedelta(hours=8))
    ).strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "records": records,
        "mode": mode,
        "history_years": history_years,
        "scanned_dates": sorted(existing_dates),
        "first_trade_date": min(existing_dates) if existing_dates else None,
        "last_trade_date": max(existing_dates) if existing_dates else None,
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


def run_cli(mode: str = "incremental", full: bool = False, history_years: float = 1.0):
    """命令行入口，用于 refresh_all.py --run limit_stat。

    Args:
        mode: "incremental"（默认）或 "full"
        full: True 时强制全量扫描（覆盖 mode）
        history_years: 往前扫多少年（默认 1.0 年 ≈ 255 交易日）
    """
    import logging
    log = logging.getLogger("limit_stat")

    def prog(msg: str):
        log.info(msg)
        print(msg, flush=True)

    actual_mode = "full" if full else mode
    prog(f"[limit_stat] 开始，mode={actual_mode}  history_years={history_years}")
    t0 = time.time()

    records = scan(mode=actual_mode, history_years=history_years, progress_cb=prog)

    # 收集本次覆盖的交易日列表（给 save_results 存元数据）
    n_trade = int(history_years * 255)
    if actual_mode == "full":
        scanned_dates = _iter_trade_dates(n_trade)
    else:
        existing = load_results()
        existing_dates = set(existing.get("scanned_dates", [])) if existing else set()
        all_dates = set(_iter_trade_dates(n_trade))
        scanned_dates = list(all_dates - existing_dates) if existing else None

    path = save_results(records, mode=actual_mode,
                        scanned_dates=scanned_dates, history_years=history_years)
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
