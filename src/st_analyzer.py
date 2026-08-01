"""ST 股票摘帽分析。

数据源：baostock（与 StockDataLoader 相同）。

核心逻辑：
  1. 拉取指定日期范围内所有 A 股的日 K 线（含 isST 字段）
  2. 扫描每只股票的 isST 时间序列，找出由 1 -> 0 的转折点 = 摘帽日
  3. 计算摘帽前 N 天、摘帽后 N 天的涨跌幅
  4. 同时取下摘帽日的市盈率（peTTM）、市净率（pbMRQ）、收盘价

字段定义：
  isST = 1 表示当日处于 ST/*ST 状态；isST = 0 表示正常
  摘帽日 = 第一条 isST 由 1 变成 0 的交易日
"""
import os
import time
from datetime import datetime, timedelta

import pandas as pd


def _import_baostock():
    try:
        import baostock as bs
        return bs
    except ImportError:
        raise ImportError("未安装 baostock 模块，请先执行：pip install baostock")


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _months_ago(months):
    """获取 N 个月前的日期字符串。"""
    today = datetime.now()
    # 近似：每月按 30 天
    target = today - timedelta(days=30 * months)
    return target.strftime("%Y-%m-%d")


class STAnalyzer:
    """ST 摘帽分析器。

    使用方式：
        analyzer = STAnalyzer(data_dir="data")
        df = analyzer.scan_and_analyze(
            months_back=10, before_days=30, after_days=30,
            progress_callback=print)
    """

    # 日 K 线查询字段（含 isST 与估值指标）
    KLINE_FIELDS = "date,code,close,preclose,pctChg,isST,peTTM,pbMRQ"

    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    # ---------------- baostock 登录/登出 ----------------
    def _login(self):
        bs = _import_baostock()
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"Baostock login failed: {lg.error_msg}")
        return bs

    def _logout(self, bs):
        try:
            bs.logout()
        except Exception:
            pass

    # ---------------- 股票列表 ----------------
    def _get_all_stock_codes(self, bs, date):
        """获取指定日期全市场 A 股代码列表（排除指数）。"""
        rs = bs.query_all_stock(day=date)
        if rs.error_code != "0":
            raise RuntimeError(f"query_all_stock 失败: {rs.error_msg}")
        df = rs.get_data()
        if df is None or df.empty:
            return []
        # 过滤 A 股主板/创业板/科创板，排除指数、基金
        # baostock 股票代码：sh.6xxxxx / sh.688xxx / sz.000xxx / sz.002xxx / sz.300xxx
        codes = df[df["code"].str.match(r"^(sh\.6|sh\.688|sz\.0|sz\.3)")]["code"]
        return codes.tolist()

    # ---------------- 拉取日 K ----------------
    def _fetch_kline(self, bs, code, start_date, end_date):
        rs = bs.query_history_k_data_plus(
            code,
            self.KLINE_FIELDS,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",  # 前复权
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=rs.fields)
        # 数值化
        for col in ["close", "preclose", "pctChg", "isST", "peTTM", "pbMRQ"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    # ---------------- 股票名称 ----------------
    def _get_stock_names(self, bs, codes):
        """通过 query_stock_basic 拉股票名称映射。"""
        rs = bs.query_stock_basic()
        name_map = {}
        if rs.error_code != "0":
            return name_map
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            # query_stock_basic 返回字段：code, code_name, ipoDate, outDate, type, status
            if len(row) >= 2:
                name_map[row[0]] = row[1]
        return name_map

    # ---------------- 找出摘帽日 ----------------
    @staticmethod
    def _find_uncap_date(df):
        """在单只股票的日 K 中找出摘帽日（isST 由 1 -> 0）。

        返回 (uncap_date, st_start_date) 或 None。
        - uncap_date: 摘帽日（isST 由 1 变 0 的首个交易日）
        - st_start_date: 进入 ST 的起始日（isST 第一次为 1 的日期）
        """
        if df.empty or "isST" not in df.columns:
            return None
        df = df.sort_values("date").reset_index(drop=True)
        st_mask = df["isST"] == 1
        if not st_mask.any():
            return None  # 从来没 ST 过
        # 找 ST 起始日
        st_start = df.loc[st_mask, "date"].iloc[0]
        # 找摘帽日：isST 从 1 变 0
        # 即找 st_mask 中由 True 变 False 的第一处
        uncap_idx = None
        for i in range(1, len(df)):
            if df.loc[i - 1, "isST"] == 1 and df.loc[i, "isST"] == 0:
                uncap_idx = i
                break
        if uncap_idx is None:
            return None  # 当前仍 ST，未摘帽
        uncap_date = df.loc[uncap_idx, "date"]
        return uncap_date, st_start

    # ---------------- 计算涨幅 ----------------
    @staticmethod
    def _compute_change(df, uncap_date, before_days, after_days):
        """计算摘帽前 N 天 / 后 N 天涨跌幅。

        返回 (pre_change_pct, post_change_pct, close_at_uncap, pe_at_uncap, pb_at_uncap)。
        若数据不足返回 None。
        """
        if df.empty:
            return None
        df = df.sort_values("date").reset_index(drop=True)
        # 找摘帽日的位置
        idx_list = df.index[df["date"] == uncap_date].tolist()
        if not idx_list:
            return None
        uncap_idx = idx_list[0]

        # 摘帽前 N 天
        start_pre = max(0, uncap_idx - before_days)
        if start_pre >= uncap_idx:
            return None
        pre_close_start = df.loc[start_pre, "close"]
        pre_close_end = df.loc[uncap_idx - 1, "close"]
        pre_change = (pre_close_end - pre_close_start) / pre_close_start * 100.0

        # 摘帽后 N 天
        end_post = min(len(df) - 1, uncap_idx + after_days)
        if end_post <= uncap_idx:
            post_change = 0.0
        else:
            post_close_start = df.loc[uncap_idx, "close"]
            post_close_end = df.loc[end_post, "close"]
            post_change = (post_close_end - post_close_start) / post_close_start * 100.0

        # 摘帽日的估值与收盘价
        row_uncap = df.loc[uncap_idx]
        close_at_uncap = row_uncap.get("close")
        pe_at_uncap = row_uncap.get("peTTM")
        pb_at_uncap = row_uncap.get("pbMRQ")
        # 处理 NaN
        if pd.isna(pe_at_uncap):
            pe_at_uncap = None
        if pd.isna(pb_at_uncap):
            pb_at_uncap = None
        return pre_change, post_change, close_at_uncap, pe_at_uncap, pb_at_uncap

    # ---------------- 主入口：扫描并分析 ----------------
    def scan_and_analyze(self, months_back=10, before_days=30, after_days=30,
                         progress_callback=None):
        """扫描最近 N 个月内的摘帽 ST 股，返回结果 DataFrame。

        Args:
            months_back: 向前查看的月数（默认 10）
            before_days: 摘帽前 N 个交易日（默认 30）
            after_days: 摘帽后 N 个交易日（默认 30）
            progress_callback: 回调函数 (msg) -> None

        Returns:
            DataFrame，列：股票名称, 代码, 开始ST日期, 结束ST日期,
                          摘帽前涨幅, 摘帽后涨幅, 市盈率, 市净率, 收盘价
        """
        end_date = _today_str()
        start_date = _months_ago(months_back)
        # 为了计算摘帽前 N 天，需要再往前多取 before_days + buffer
        # 这里直接多取 3 个月作为缓冲
        buffer_start = (_months_ago(months_back + 3))

        def log(msg):
            if progress_callback:
                progress_callback(msg)

        log(f"登录 baostock ...")
        bs = self._login()
        try:
            # 1. 全市场股票列表
            log(f"获取 {end_date} 全市场股票代码 ...")
            codes = self._get_all_stock_codes(bs, end_date)
            log(f"共 {len(codes)} 只股票，开始扫描 ...")

            # 2. 股票名称
            log("拉取股票名称表 ...")
            name_map = self._get_stock_names(bs, codes)

            # 3. 逐只扫描
            results = []
            total = len(codes)
            success = 0
            for i, code in enumerate(codes, 1):
                try:
                    df = self._fetch_kline(bs, code, buffer_start, end_date)
                    if df.empty:
                        continue
                    info = self._find_uncap_date(df)
                    if not info:
                        continue
                    uncap_date, st_start = info
                    # 只统计摘帽日在 [start_date, end_date] 范围内的
                    if uncap_date < start_date:
                        continue
                    chg = self._compute_change(df, uncap_date, before_days, after_days)
                    if chg is None:
                        continue
                    pre_change, post_change, close, pe, pb = chg
                    results.append({
                        "股票名称": name_map.get(code, ""),
                        "代码": code,
                        "开始ST日期": st_start,
                        "结束ST日期": uncap_date,
                        "摘帽前涨幅": round(pre_change, 2),
                        "摘帽后涨幅": round(post_change, 2),
                        "市盈率": round(pe, 2) if pe is not None else None,
                        "市净率": round(pb, 2) if pb is not None else None,
                        "收盘价": round(close, 3) if not pd.isna(close) else None,
                    })
                    success += 1
                except Exception as e:
                    # 单只失败不影响整体
                    pass
                if i % 50 == 0 or i == total:
                    log(f"进度 {i}/{total}  已找到 {success} 只摘帽股")
                # baostock 限速：每只间隔 0.1s
                time.sleep(0.1)
        finally:
            self._logout(bs)

        log(f"扫描完成，共找到 {len(results)} 只摘帽 ST 股")
        if not results:
            return pd.DataFrame(columns=[
                "股票名称", "代码", "开始ST日期", "结束ST日期",
                "摘帽前涨幅", "摘帽后涨幅", "市盈率", "市净率", "收盘价"])
        df_out = pd.DataFrame(results)
        # 按摘帽日倒序
        df_out = df_out.sort_values("结束ST日期", ascending=False).reset_index(drop=True)
        return df_out
