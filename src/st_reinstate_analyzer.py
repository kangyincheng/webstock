"""ST 股票摘帽时间分析（预计可申请摘帽日）。

数据源：baostock。

核心策略：
  1. 拉取最新交易日全市场 A 股（含名称），筛选出名称含 ST 的股票
  2. 对每只 ST 股，用日 K 的 isST 字段找出当前 ST 段的起始日（最近一次 0->1；
     若窗口内 isST 全程为 1，说明 ST 早于窗口，取窗口最早日期作近似）
  3. 可申请摘帽日 = ST 起始日 + 1 个日历年
  4. 若可申请摘帽日为节假日，向后顺延至下一个交易日
  5. 同时取最新交易日的收盘价、市盈率（peTTM）、市净率（pbMRQ）、换手率（turn），
     并计算量比（当日成交量 / 过去 N 日平均成交量）、每股净资产（收盘价 / pbMRQ）

字段定义：
  isST = 1 表示当日处于 ST/*ST 状态；isST = 0 表示正常
  名称含 ST = 股票名称中包含 "ST"（ST / *ST / S*ST 等）
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


def _name_has_st(name):
    """判断股票名称是否包含 ST 标识（ST / *ST / S*ST 等）。

    A 股名称均为中文，其中出现 "ST" 必然代表 ST 状态。
    """
    if not name:
        return False
    return "ST" in str(name).upper()


def _add_one_year(date_str):
    """日期 + 1 个日历年（2 月 29 日 -> 次年 2 月 28 日）。返回 YYYY-MM-DD 字符串。"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    try:
        nd = d.replace(year=d.year + 1)
    except ValueError:
        nd = d.replace(year=d.year + 1, day=28)
    return nd.strftime("%Y-%m-%d")


class STReinstateAnalyzer:
    """ST 摘帽时间分析器（预计可申请摘帽日）。

    使用方式：
        analyzer = STReinstateAnalyzer(data_dir="data")
        df = analyzer.scan_and_analyze(
            months_back=12, volume_ratio_days=5, progress_callback=print)
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

    # ---------------- 全市场 A 股 + 名称（按日期快照）----------------
    def _get_all_stock_with_names(self, bs, target_date, max_lookback=15):
        """获取指定日期（或最近交易日）全市场 A 股代码与名称。

        baostock query_all_stock(day=X) 返回 X 当日上市股票及其当时的名称，
        非交易日可能为空，因此向前回溯最多 max_lookback 天寻找有效交易日。

        返回 (name_map, actual_date)：
          name_map = {code: name}（仅 A 股主板/创业板/科创板，排除指数、基金）
          actual_date = 实际命中的交易日字符串（YYYY-MM-DD）
        """
        base = datetime.strptime(target_date, "%Y-%m-%d")
        for back in range(max_lookback):
            day = (base - timedelta(days=back)).strftime("%Y-%m-%d")
            rs = bs.query_all_stock(day=day)
            if rs.error_code != "0":
                continue
            try:
                df = rs.get_data()
            except Exception:
                df = None
            if df is None or df.empty or "code" not in df.columns:
                continue
            mask = df["code"].astype(str).str.match(r"^(sh\.6|sh\.688|sz\.0|sz\.3)")
            df_a = df[mask]
            if df_a.empty:
                continue
            name_col = next(
                (c for c in df_a.columns if "name" in c.lower()), None)
            name_map = {}
            for _, r in df_a.iterrows():
                code = str(r["code"])
                name = str(r[name_col]) if (name_col and name_col in df_a.columns) else ""
                name_map[code] = name
            return name_map, day
        return {}, target_date

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
        if rs.error_code != "0":
            return pd.DataFrame()
        try:
            df = rs.get_data()
            if df is None or df.empty:
                return pd.DataFrame()
        except Exception:
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

    # ---------------- 交易日历 ----------------
    def _load_trading_calendar(self, bs, start_date, end_date):
        """加载 [start_date, end_date] 范围内的交易日集合。

        使用 baostock query_trade_dates 获取交易日历，返回 {date_str, ...}。
        失败时返回空集合（后续回退为跳过周末）。
        """
        rs = bs.query_trade_dates(start_date=start_date, end_date=end_date)
        if rs.error_code != "0":
            return set()
        try:
            df = rs.get_data()
        except Exception:
            df = None
        if df is None or df.empty:
            return set()
        date_col = next(
            (c for c in df.columns if "date" in c.lower() or "calendar" in c.lower()),
            None)
        trade_col = next(
            (c for c in df.columns if "trading" in c.lower()), None)
        if date_col is None or trade_col is None:
            return set()
        trading = df[df[trade_col].astype(str).isin(["1", "1.0"])]
        return set(trading[date_col].astype(str).tolist())

    @staticmethod
    def _next_trading_day(trading_days_set, target_date):
        """从预加载交易日集合中找 >= target_date 的最近交易日。

        若 target_date 超出交易日历范围（未来日期），回退为跳过周末。
        """
        on_or_after = sorted(d for d in trading_days_set if d >= target_date)
        if on_or_after:
            return on_or_after[0]
        # 回退：仅跳过周末（未来日期超出交易日历范围时）
        d = datetime.strptime(target_date, "%Y-%m-%d")
        while d.weekday() >= 5:  # 周六=5, 周日=6
            d += timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    # ---------------- 找出当前 ST 段起始日 ----------------
    @staticmethod
    def _find_st_start(df):
        """找出当前 ST 段的起始日（最近一次 isST 0->1）。

        若窗口内 isST 全程为 1（ST 早于窗口开始），返回窗口最早日期作为近似。
        返回日期字符串或 None（窗口内未 ST，与名称不符时跳过）。
        """
        if df is None or df.empty or "isST" not in df.columns:
            return None
        df = df.sort_values("date").reset_index(drop=True)
        st_mask = df["isST"] == 1
        if not st_mask.any():
            return None  # 窗口内未 ST（与名称含 ST 不符，跳过）
        # 最近一次 0->1 转折
        st_start_idx = None
        for i in range(1, len(df)):
            if df.loc[i - 1, "isST"] == 0 and df.loc[i, "isST"] == 1:
                st_start_idx = i  # 持续覆盖以取最近一次
        if st_start_idx is not None:
            return df.loc[st_start_idx, "date"]
        # 全程 ST（含首行）：起始早于窗口，取最早日期近似
        return df.loc[0, "date"]

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
            prev = df.iloc[:-1].tail(volume_ratio_days)
            if len(prev) >= 1:
                prev_vols = pd.to_numeric(prev["volume"], errors="coerce").dropna()
                if len(prev_vols) > 0 and prev_vols.mean() > 0:
                    volume_ratio = float(last_vol) / float(prev_vols.mean())

        # 每股净资产（BPS）= 收盘价 / 市净率
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
        """扫描当前处于 ST 状态的股票，计算预计可申请摘帽日。

        策略：
          1. 拉取最新交易日全市场 A 股（含名称），筛选名称含 ST 的股票
          2. 对每只 ST 股，用日 K 的 isST 字段找出当前 ST 段起始日
          3. 可申请摘帽日 = ST 起始日 + 1 个日历年
          4. 若可申请摘帽日为节假日，向后顺延至下一个交易日

        Args:
            months_back: 日 K 回溯月数（用于寻找 ST 起始日，默认 12）
            volume_ratio_days: 量比的计算窗口（默认 5 个交易日）
            progress_callback: 回调函数 (msg) -> None

        Returns:
            DataFrame，列：股票名称, 代码, ST开始日期, 可申请摘帽日,
                          股价, 净资产, 市盈率, 市净率, 量比, 换手
        """
        today = _today_str()
        lookback_start = _months_ago(months_back)

        def log(msg):
            if progress_callback:
                progress_callback(msg)

        log(f"登录 baostock ...")
        bs = self._login()
        try:
            # 1. 最新交易日全市场 A 股（含名称）
            log(f"获取最新交易日全市场股票名称（目标 {today}）...")
            latest_map, end_date = self._get_all_stock_with_names(bs, today)
            log(f"最新交易日 {end_date}：共 {len(latest_map)} 只 A 股")

            # 2. 筛选 ST 股（名称含 ST）
            st_stocks = [(code, name)
                         for code, name in latest_map.items()
                         if _name_has_st(name)]
            log(f"名称含 ST 的股票：{len(st_stocks)} 只")

            # 3. 预加载交易日历（覆盖所有可能的可申请摘帽日）
            #    可申请摘帽日 = ST起始 + 1年，范围约 [lookback_start+1年, today+1年]
            cal_start = lookback_start
            cal_end = (datetime.now() + timedelta(days=365 + 30)).strftime("%Y-%m-%d")
            log("加载交易日历 ...")
            trading_days = self._load_trading_calendar(bs, cal_start, cal_end)
            log(f"交易日历：{len(trading_days)} 个交易日")

            # 4. 逐只分析
            results = []
            total = len(st_stocks)
            success = 0
            for i, (code, name) in enumerate(st_stocks, 1):
                try:
                    df = self._fetch_kline(bs, code, lookback_start, end_date)
                    if df is None or df.empty:
                        continue
                    st_start = self._find_st_start(df)
                    if st_start is None:
                        continue  # 窗口内未 ST（与名称不符），跳过
                    # 可申请摘帽日 = ST起始 + 1 个日历年
                    eligibility = _add_one_year(st_start)
                    # 若为节假日则顺延至下一个交易日
                    eligibility = self._next_trading_day(trading_days, eligibility)

                    metrics = self._compute_latest_metrics(df, volume_ratio_days)
                    close = metrics.get("close")
                    turn = metrics.get("turn")
                    pe = metrics.get("pe")
                    pb = metrics.get("pb")
                    volume_ratio = metrics.get("volume_ratio")
                    bps = metrics.get("bps")

                    results.append({
                        "股票名称": name,
                        "代码": code,
                        "ST开始日期": st_start,
                        "可申请摘帽日": eligibility,
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
                if i % 20 == 0 or i == total:
                    log(f"进度 {i}/{total}  已成功 {success} 只")
                # baostock 限速
                time.sleep(0.01)
        finally:
            self._logout(bs)

        log(f"扫描完成，共 {len(results)} 只 ST 股")
        cols = ["股票名称", "代码", "ST开始日期", "可申请摘帽日",
                "股价", "净资产", "市盈率", "市净率", "量比", "换手"]
        if not results:
            return pd.DataFrame(columns=cols)
        df_out = pd.DataFrame(results, columns=cols)
        # 默认按可申请摘帽日降序
        df_out = df_out.sort_values("可申请摘帽日", ascending=False,
                                    na_position="last").reset_index(drop=True)
        return df_out

    # 兼容别称：backend 通过 az.scan(...) 调用
    scan = scan_and_analyze
