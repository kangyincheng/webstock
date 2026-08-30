"""ST 股票摘帽分析。

数据源：baostock。

核心策略（名称比对法）：
  1. 拉取最新交易日全市场 A 股（含名称）—— baostock query_all_stock(day=最新交易日)
  2. 拉取 N 个月前交易日全市场 A 股（含名称）—— baostock query_all_stock(day=N月前交易日)
  3. 名称比对：N 个月前名称含 ST、最新名称不含 ST ——> 该股已摘帽
  4. 对每只摘帽股，用日 K 的 isST 字段定位摘帽日（窗口内最近一次 isST 1->0），
     再计算摘帽前 N 天 / 摘帽后 N 天涨跌幅，并取摘帽日收盘价、peTTM、pbMRQ

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


class STAnalyzer:
    """ST 摘帽分析器（名称比对法）。

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
        for col in ["close", "preclose", "pctChg", "isST", "peTTM", "pbMRQ"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    # ---------------- 在窗口内定位摘帽日 ----------------
    @staticmethod
    def _find_uncap_date_in_window(df, start_date, end_date):
        """在 [start_date, end_date] 窗口内找出最近一次摘帽日（isST 由 1 -> 0）。

        名称比对已确认：start_date 时含 ST、end_date 时不含 ST，
        故窗口内必存在一次 isST 1->0 的摘帽；取最近一次以应对多次进出 ST 的情况。

        返回 (uncap_date, st_start_date) 或 None：
          - uncap_date: 窗口内最后一次 isST 1->0 的交易日
          - st_start_date: 摘帽前最近一段 ST 的起始日（isST 首次为 1 的日期）
        """
        if df is None or df.empty or "isST" not in df.columns:
            return None
        df = df.sort_values("date").reset_index(drop=True)
        mask = (df["date"] >= start_date) & (df["date"] <= end_date)
        df = df[mask].reset_index(drop=True)
        if df.empty:
            return None
        st_mask = df["isST"] == 1
        if not st_mask.any():
            return None  # 窗口内从未 ST（isST 字段与名称比对不一致）
        # 找最后一次 isST 由 1 变 0 的位置
        uncap_idx = None
        for i in range(1, len(df)):
            if df.loc[i - 1, "isST"] == 1 and df.loc[i, "isST"] == 0:
                uncap_idx = i  # 持续覆盖以取最近一次
        if uncap_idx is None:
            return None  # 窗口内仍处于 ST（isST 字段与名称比对不一致）
        uncap_date = df.loc[uncap_idx, "date"]
        # 摘帽前最近一段 ST 的起始日
        st_before = df.iloc[:uncap_idx]
        st_before_mask = st_before["isST"] == 1
        if not st_before_mask.any():
            return None
        st_start = st_before.loc[st_before_mask, "date"].iloc[0]
        return uncap_date, st_start

    # ---------------- 计算涨幅 ----------------
    @staticmethod
    def _compute_change(df, uncap_date, before_days, after_days):
        """计算摘帽前 N 天 / 后 N 天涨跌幅。

        返回 (pre_change_pct, post_change_pct, close_at_uncap, pe_at_uncap, pb_at_uncap)。
        若数据不足返回 None。
        """
        if df is None or df.empty:
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
        """通过名称比对识别摘帽 ST 股，并计算摘帽前/后涨跌幅。

        策略：
          1. 拉取最新交易日全市场 A 股（含名称）
          2. 拉取 N 个月前交易日全市场 A 股（含名称）
          3. 名称比对：N 个月前名称含 ST、最新名称不含 ST -> 已摘帽
          4. 对每只摘帽股，用日 K 的 isST 字段定位摘帽日，计算摘帽前/后涨跌幅

        Args:
            months_back: 名称比对回溯的月数（默认 10）
            before_days: 摘帽前 N 个交易日（默认 30）
            after_days: 摘帽后 N 个交易日（默认 30）
            progress_callback: 回调函数 (msg) -> None

        Returns:
            DataFrame，列：股票名称, 代码, 开始ST日期, 结束ST日期,
                          摘帽前涨幅, 摘帽后涨幅, 市盈率, 市净率, 收盘价
        """
        today = _today_str()
        start_target = _months_ago(months_back)
        # 为了计算摘帽前 N 天，K 线再多回溯 3 个月作为缓冲
        buffer_start = _months_ago(months_back + 3)

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

            # 2. N 个月前交易日全市场 A 股（含名称）
            log(f"获取 {months_back} 个月前全市场股票名称（目标 {start_target}）...")
            old_map, start_date = self._get_all_stock_with_names(bs, start_target)
            log(f"起始交易日 {start_date}：共 {len(old_map)} 只 A 股")

            # 3. 名称比对：识别摘帽股
            #    N 个月前名称含 ST、最新名称不含 ST -> 已摘帽
            hat_removed = []
            for code, new_name in latest_map.items():
                old_name = old_map.get(code)
                if not old_name:
                    continue  # N 个月前尚未上市
                if _name_has_st(old_name) and not _name_has_st(new_name):
                    hat_removed.append((code, new_name))
            log(f"名称比对：{start_date} 含 ST 而 {end_date} 不含 ST -> "
                f"{len(hat_removed)} 只摘帽股")

            # 4. 逐只定位摘帽日 + 计算涨跌幅
            results = []
            total = len(hat_removed)
            success = 0
            for i, (code, name) in enumerate(hat_removed, 1):
                try:
                    df = self._fetch_kline(bs, code, buffer_start, end_date)
                    if df is None or df.empty:
                        continue
                    info = self._find_uncap_date_in_window(df, start_date, end_date)
                    if not info:
                        continue  # isST 字段与名称比对不一致，跳过
                    uncap_date, st_start = info
                    chg = self._compute_change(df, uncap_date, before_days, after_days)
                    if chg is None:
                        continue
                    pre_change, post_change, close, pe, pb = chg
                    results.append({
                        "股票名称": name,
                        "代码": code,
                        "开始ST日期": st_start,
                        "结束ST日期": uncap_date,
                        "摘帽前涨幅": round(pre_change, 2),
                        "摘帽后涨幅": round(post_change, 2),
                        "市盈率": round(pe, 2) if pe is not None else None,
                        "市净率": round(pb, 2) if pb is not None else None,
                        "收盘价": round(close, 3) if close is not None and not pd.isna(close) else None,
                    })
                    success += 1
                except Exception:
                    # 单只失败不影响整体
                    pass
                if i % 10 == 0 or i == total:
                    log(f"进度 {i}/{total}  已成功 {success} 只")
                # baostock 限速
                time.sleep(0.01)
        finally:
            self._logout(bs)

        log(f"扫描完成，共找到 {len(results)} 只摘帽 ST 股")
        cols = ["股票名称", "代码", "开始ST日期", "结束ST日期",
                "摘帽前涨幅", "摘帽后涨幅", "市盈率", "市净率", "收盘价"]
        if not results:
            return pd.DataFrame(columns=cols)
        df_out = pd.DataFrame(results, columns=cols)
        # 按摘帽日倒序
        df_out = df_out.sort_values("结束ST日期", ascending=False).reset_index(drop=True)
        return df_out
