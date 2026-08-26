"""ST 股票转正分析。

数据源：baostock（与 STAnalyzer 相同）。

核心逻辑：
  1. 拉取指定日期范围内所有 A 股的日 K 线（含 isST 字段）
  2. 扫描每只股票的 isST 时间序列
     - ST 开始日期：isST 由 0 -> 1 的首个交易日
     - ST 转正日期：isST 由 1 -> 0 的首个交易日（仍处于 ST 状态则为 None）
  3. 在扫描范围内出现过 ST 状态的股票都进入结果
  4. 同时取最新交易日的：收盘价、市盈率（peTTM）、市净率（pbMRQ）、换手率（turn）
  5. 计算：量比（当日成交量 / 过去 N 日平均成交量）、每股净资产（收盘价 / pbMRQ）

字段定义：
  isST = 1 表示当日处于 ST/*ST 状态；isST = 0 表示正常
  ST 转正日期 = ST 起始之后 isST 第一次回到 0 的交易日
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


class STReinstateAnalyzer:
    """ST 转正分析器。

    使用方式：
        analyzer = STReinstateAnalyzer(data_dir="data")
        df = analyzer.scan_and_analyze(
            months_back=12,
            volume_ratio_days=5,
            progress_callback=print)
    """

    # 日 K 线查询字段：日期、代码、收盘价、成交量、换手率、isST、peTTM、pbMRQ
    KLINE_FIELDS = "date,code,close,volume,turn,isST,peTTM,pbMRQ"

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
        for col in ["close", "volume", "turn", "isST", "peTTM", "pbMRQ"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    # ---------------- 股票名称 ----------------
    def _get_stock_names(self, bs):
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

    # ---------------- 找出 ST 起始日 / 转正日 ----------------
    @staticmethod
    def _find_st_transitions(df):
        """在单只股票的日 K 中找出 ST 起始日与转正日。

        返回 (st_start_date, reinstate_date)：
          - st_start_date: isST 第一次为 1 的日期（进入 ST 的起始日）
          - reinstate_date: ST 起始之后 isST 第一次回到 0 的日期；
                            若当前仍处于 ST 状态则为 None
          若该股票扫描范围内从未进入 ST，返回 None。
        """
        if df.empty or "isST" not in df.columns:
            return None
        df = df.sort_values("date").reset_index(drop=True)
        st_mask = df["isST"] == 1
        if not st_mask.any():
            return None  # 从来没 ST 过

        st_start = df.loc[st_mask, "date"].iloc[0]
        st_first_idx = st_mask.idxmax()  # isST 第一次为 1 的位置

        # 在 ST 起始之后找 isST 回到 0 的首个交易日
        reinstate_idx = None
        for i in range(st_first_idx + 1, len(df)):
            if df.loc[i, "isST"] == 0:
                reinstate_idx = i
                break
        reinstate_date = df.loc[reinstate_idx, "date"] if reinstate_idx is not None else None
        return st_start, reinstate_date

    # ---------------- 计算最新行情 + 量比 + 净资产 ----------------
    @staticmethod
    def _compute_latest_metrics(df, volume_ratio_days=5):
        """从日 K 中提取最新交易日的指标，并计算量比与每股净资产。

        返回 dict：close, turn, pe, pb, volume_ratio, bps。
        数据不足或缺失的指标为 None。
        """
        if df is None or df.empty:
            return {}
        df = df.sort_values("date").reset_index(drop=True)
        last_row = df.iloc[-1]
        close = last_row.get("close")
        turn = last_row.get("turn")
        pe = last_row.get("peTTM")
        pb = last_row.get("pbMRQ")
        last_vol = last_row.get("volume")

        # 量比 = 当日成交量 / 过去 N 个交易日平均成交量
        volume_ratio = None
        if last_vol is not None and not pd.isna(last_vol):
            # 取当日之前 N 个交易日
            prev = df.iloc[:-1].tail(volume_ratio_days)
            if len(prev) >= 1:
                prev_vols = pd.to_numeric(prev["volume"], errors="coerce").dropna()
                if len(prev_vols) > 0 and prev_vols.mean() > 0:
                    volume_ratio = float(last_vol) / float(prev_vols.mean())

        # 每股净资产（BPS）= 收盘价 / 市净率
        # 原理：pbMRQ = 总市值 / 净资产 = (股价 × 总股本) / 净资产
        #        => 净资产 = 股价 × 总股本 / pbMRQ
        #        => 每股净资产 = 净资产 / 总股本 = 股价 / pbMRQ
        bps = None
        try:
            if close is not None and pb is not None and not pd.isna(close) and not pd.isna(pb) and pb > 0:
                bps = float(close) / float(pb)
        except Exception:
            bps = None

        return {
            "close": None if (close is None or pd.isna(close)) else float(close),
            "turn": None if (turn is None or pd.isna(turn)) else float(turn),
            "pe": None if (pe is None or pd.isna(pe)) else float(pe),
            "pb": None if (pb is None or pd.isna(pb)) else float(pb),
            "volume_ratio": volume_ratio,
            "bps": bps,
        }

    # ---------------- 主入口：扫描并分析 ----------------
    def scan_and_analyze(self, months_back=12, volume_ratio_days=5,
                         progress_callback=None):
        """扫描最近 N 个月内出现 ST 状态的股票，返回结果 DataFrame。

        Args:
            months_back: 向前查看的月数（默认 12）
            volume_ratio_days: 量比的计算窗口（默认 5 个交易日）
            progress_callback: 回调函数 (msg) -> None

        Returns:
            DataFrame，列：股票名称, 代码, ST开始日期, ST转正日期,
                          股价, 净资产, 市盈率, 市净率, 量比, 换手
        """
        # 兼容旧调用名：backend 使用 az.scan(...) 而非 az.scan_and_analyze(...)
        # scan() 别名片段见下方
        end_date = _today_str()
        start_date = _months_ago(months_back)

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
            name_map = self._get_stock_names(bs)

            # 3. 逐只扫描
            results = []
            total = len(codes)
            success = 0
            for i, code in enumerate(codes, 1):
                try:
                    df = self._fetch_kline(bs, code, start_date, end_date)
                    if df.empty:
                        continue
                    info = self._find_st_transitions(df)
                    if not info:
                        continue  # 该股在扫描范围内从未进入 ST
                    st_start, reinstate_date = info

                    metrics = self._compute_latest_metrics(df, volume_ratio_days)
                    close = metrics.get("close")
                    turn = metrics.get("turn")
                    pe = metrics.get("pe")
                    pb = metrics.get("pb")
                    volume_ratio = metrics.get("volume_ratio")
                    bps = metrics.get("bps")

                    results.append({
                        "股票名称": name_map.get(code, ""),
                        "代码": code,
                        "ST开始日期": st_start,
                        "ST转正日期": reinstate_date if reinstate_date is not None else None,
                        "股价": round(close, 3) if close is not None else None,
                        "净资产": round(bps, 3) if bps is not None else None,
                        "市盈率": round(pe, 2) if pe is not None else None,
                        "市净率": round(pb, 2) if pb is not None else None,
                        "量比": round(volume_ratio, 3) if volume_ratio is not None else None,
                        "换手": round(turn, 3) if turn is not None else None,
                    })
                    success += 1
                except Exception:
                    # 单只失败不影响整体
                    pass
                if i % 50 == 0 or i == total:
                    log(f"进度 {i}/{total}  已找到 {success} 只 ST 股")
                # baostock 限速：每只间隔 0.1s
                time.sleep(0.1)
        finally:
            self._logout(bs)

        log(f"扫描完成，共找到 {len(results)} 只 ST 股")
        cols = ["股票名称", "代码", "ST开始日期", "ST转正日期",
                "股价", "净资产", "市盈率", "市净率", "量比", "换手"]
        if not results:
            return pd.DataFrame(columns=cols)
        df_out = pd.DataFrame(results, columns=cols)
        # 默认按 ST 转正日期降序（已转正的靠前，仍 ST 的 None 放最后）
        df_out = df_out.sort_values("ST转正日期", ascending=False,
                                   na_position="last").reset_index(drop=True)
        return df_out

    # 兼容别称：backend 通过 az.scan(...) 调用
    scan = scan_and_analyze
