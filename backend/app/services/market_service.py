"""Market services：ST 摘帽 / 恢复上市 / 市场温度计 / 板块热度 / 热门股票 / 可转债 / 要约收购。

原则：复用 workspace/src/*Analyzer/*Client 的纯 Python 接口，GUI 相关 Tkinter 全部绕过。
"""
from __future__ import annotations

import os
import sys
import time
import json
import tempfile
import traceback
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

# ---- pandas 3.0+ 移除了 DataFrame.append，但 baostock 00.9.30 仍依赖它 ----
# 同时 patch ResultSet.get_data 避免 O(n^2) 逐行 append
if not getattr(pd.DataFrame, '_patched_append', False):
    def _df_append_compat(self, other, *args, **kwargs):
        return pd.concat([self, other], *args, **kwargs)
    pd.DataFrame.append = _df_append_compat
    pd.DataFrame._patched_append = True

def _patch_get_data():
    """替换 baostock ResultSet.get_data 为高效版本（一次 concat，不逐行 append）。"""
    try:
        from baostock.data.resultset import ResultSet
    except ImportError:
        return
    if getattr(ResultSet.get_data, '_patched', False):
        return
    def _get_data(self):
        rows = []
        while self.error_code == "0" and self.next():
            rows.append(self.get_row_data())
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=self.fields)
    ResultSet.get_data = _get_data
    ResultSet.get_data._patched = True

_patch_get_data()

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
# ST 扫描用 spawn 多进程并行，子进程是全新解释器，不继承父进程运行期的
# sys.path 修改；把 SRC_DIR 写入 PYTHONPATH，保证子进程能导入 src 下的分析器模块
_pp = os.environ.get("PYTHONPATH", "")
if SRC_DIR not in _pp.split(os.pathsep):
    os.environ["PYTHONPATH"] = SRC_DIR + (os.pathsep + _pp if _pp else "")

from st_analyzer import STAnalyzer                       # noqa: E402
from st_reinstate_analyzer import STReinstateAnalyzer    # noqa: E402
from market_thermometer import MarketThermometerAnalyzer  # noqa: E402
from market_data import TushareClient                     # noqa: E402
from cbond_analyzer import ConvertibleBondAnalyzer        # noqa: E402
from tender_offer_analyzer import TenderOfferAnalyzer     # noqa: E402


DATA_DIR = os.path.join(BASE_DIR, "backend", "data")


def _df_to_records(df: Optional[pd.DataFrame]) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    # 处理 NaN/inf 等 JSON 不友好值
    clean = df.where(pd.notnull(df), None)
    return json.loads(clean.to_json(orient="records", force_ascii=False,
                                    date_format="iso"))


class MarketServices:

    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    # ------------- ST 摘帽 -------------
    def scan_st(self, months_back: int = 10, before_days: int = 30, after_days: int = 30,
                progress_cb: Optional[Callable[[str], None]] = None) -> List[Dict[str, Any]]:
        az = STAnalyzer(data_dir=self.data_dir)
        df = az.scan_and_analyze(
            months_back=months_back, before_days=before_days, after_days=after_days,
            progress_callback=progress_cb,
        )
        return _df_to_records(df)

    # ------------- ST 恢复上市（预计可申请摘帽日）-------------
    def scan_st_reinstate(self, months_back: int = 24,
                          progress_cb: Optional[Callable[[str], None]] = None
                          ) -> List[Dict[str, Any]]:
        az = STReinstateAnalyzer(data_dir=self.data_dir)
        df = az.scan(months_back=months_back, progress_callback=progress_cb)
        return _df_to_records(df)

    # ------------- 市场温度计 -------------
    def market_thermometer(self, progress_cb: Optional[Callable[[str], None]] = None
                           ) -> Optional[Dict[str, Any]]:
        az = MarketThermometerAnalyzer(data_dir=self.data_dir)
        return az.compute(progress_callback=progress_cb)

    # ------------- 板块热度 -------------
    def sector_heat(self, trade_date: str = "", use_cache: bool = True,
                    progress_cb: Optional[Callable[[str], None]] = None
                    ) -> List[Dict[str, Any]]:
        cli = TushareClient(data_dir=self.data_dir)
        df = cli.sector_heat(trade_date=trade_date or None, use_cache=use_cache,
                             progress_callback=progress_cb)
        return _df_to_records(df)

    # ------------- 热门股票 -------------
    def hot_stocks(self, trade_date: str = "", sort_by: str = "pct_chg", top_n: int = 50,
                   filter_keyword: str = "", use_cache: bool = True,
                   progress_cb: Optional[Callable[[str], None]] = None
                   ) -> List[Dict[str, Any]]:
        cli = TushareClient(data_dir=self.data_dir)
        df = cli.hot_stocks(trade_date=trade_date or None, sort_by=sort_by, top_n=top_n,
                            use_cache=use_cache, progress_callback=progress_cb)
        if df is None or df.empty:
            return []
        kw = (filter_keyword or "").strip()
        if kw:
            mask = False
            if "code" in df.columns:
                mask = mask | df["code"].astype(str).str.contains(kw, case=False, na=False)
            if "name" in df.columns:
                mask = mask | df["name"].astype(str).str.contains(kw, case=False, na=False)
            if isinstance(mask, pd.Series):
                df = df[mask]
        return _df_to_records(df)

    # ------------- 可转债 -------------
    def cbond(self, category: str = "subscribe",
              progress_cb: Optional[Callable[[str], None]] = None
              ) -> List[Dict[str, Any]]:
        """可转债：申购 / 上市 / 发审。

        subscribe / listing: 用 akshare.bond_zh_cov()（东方财富数据源，真实数据）
        review: 用 ConvertibleBondAnalyzer.fetch_review（tushare + mock）
        """
        if category == "review":
            az = ConvertibleBondAnalyzer(data_dir=self.data_dir)
            df = az.fetch_review(progress_callback=progress_cb)
            return _df_to_records(df)

        # ---- subscribe / listing 用 akshare 真实数据 ----
        try:
            import akshare as ak
        except ImportError:
            if progress_cb:
                progress_cb("akshare 未安装，回退到 mock")
            az = ConvertibleBondAnalyzer(data_dir=self.data_dir)
            pair = az.fetch_new_ipo(progress_callback=progress_cb)
            if not pair:
                return []
            sub_df, list_df = pair
            df = list_df if category == "listing" else sub_df
            return _df_to_records(df)

        today = time.strftime("%Y-%m-%d", time.localtime())
        if progress_cb:
            progress_cb(f"从东方财富获取可转债 {category} 数据...")

        try:
            df = ak.bond_zh_cov()
        except Exception as e:
            if progress_cb:
                progress_cb(f"akshare 获取失败: {e}，回退 mock")
            az = ConvertibleBondAnalyzer(data_dir=self.data_dir)
            pair = az.fetch_new_ipo(progress_callback=progress_cb)
            if not pair:
                return []
            sub_df, list_df = pair
            df = list_df if category == "listing" else sub_df
            return _df_to_records(df)

        # 字段名映射（akshare bond_zh_cov → 前端期望）
        COL_MAP = {
            "债券代码": "转债代码",
            "债券简称": "转债名称",
            "申购日期": "申购日期",
            "上市时间": "上市日期",
            "正股代码": "正股代码",
            "正股简称": "正股名称",
            "正股价": "正股价",
            "转股价": "转股价",
            "转股价值": "转股价值",
            "债现价": "转债开盘价",   # 上市当日用
            "转股溢价率": "可转债溢价率(%)",
            "申购代码": "配售代码",
            "申购上限": "申购上限(万元)",
        }

        if category == "subscribe":
            # 当日可申购：申购日期 == 今天
            # bond_zh_cov 的"申购上限"列单位是万元（akshare 注释）
            today_df = df[df["申购日期"] == today].copy()
        else:
            # 当日上市：上市时间 == 今天（跳过 NaT）
            today_df = df[(df["上市时间"].notna()) & (df["上市时间"] != "NaT") &
                          (df["上市时间"].astype(str).str.startswith(today))].copy()

        if today_df.empty:
            if progress_cb:
                progress_cb(f"今日无 {category} 可转债")
            return []

        # 列名对齐 + 加发行价
        out = pd.DataFrame()
        for src, dst in COL_MAP.items():
            if src in today_df.columns:
                out[dst] = today_df[src]
        out["债发行价"] = 100.0

        # 上市类额外字段
        if category == "listing":
            out["首日涨幅(%)"] = (out["转债开盘价"].astype(float) - 100.0)

        out["可转债溢价率(%)"] = pd.to_numeric(out["可转债溢价率(%)"], errors="coerce")

        if progress_cb:
            progress_cb(f"共 {len(out)} 只（来源：东方财富）")

        return _df_to_records(out)

    # ------------- 要约收购 -------------
    def tender_offer(self, market: str = "cn",
                     progress_cb: Optional[Callable[[str], None]] = None
                     ) -> List[Dict[str, Any]]:
        az = TenderOfferAnalyzer(data_dir=self.data_dir)
        pair = az.fetch_tender_offers(progress_callback=progress_cb) or (None, None)
        a_df, h_df = pair
        import pandas as _pd
        if market == "hk":
            df = h_df
        elif market == "cn":
            df = a_df
        else:
            # 合并 A + 港，加「市场」列
            pieces = []
            if a_df is not None and not a_df.empty:
                a_df = a_df.copy()
                a_df.insert(0, "市场", "A股")
                pieces.append(a_df)
            if h_df is not None and not h_df.empty:
                h_df = h_df.copy()
                h_df.insert(0, "市场", "港股")
                pieces.append(h_df)
            df = _pd.concat(pieces, ignore_index=True) if pieces else None
        if df is None:
            return []
        return _df_to_records(df)
