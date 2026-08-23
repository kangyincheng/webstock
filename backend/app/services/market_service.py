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

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

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

    # ------------- ST 恢复上市 -------------
    def scan_st_reinstate(self, months_back: int = 6,
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
        az = ConvertibleBondAnalyzer(data_dir=self.data_dir)
        if category == "review":
            df = az.fetch_review(progress_callback=progress_cb)
            return _df_to_records(df)
        # subscribe / listing 从 fetch_new_ipo 的二元组里取
        pair = az.fetch_new_ipo(progress_callback=progress_cb)
        if not pair:
            return []
        sub_df, list_df = pair
        df = list_df if category == "listing" else sub_df
        return _df_to_records(df)

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
