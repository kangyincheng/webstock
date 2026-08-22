"""市场温度计：计算当天股价在 20 日均线以上的股票占比。

数据源：baostock。

算法：
  1. 拉取全市场 A 股最近 25 个交易日的日 K 线（取 close 字段）
  2. 对每只股票计算 MA20（最近 20 个交易日收盘价均值）
  3. 比较最新收盘价与 MA20：
     - close > MA20：计为"在均线上方"
  4. 占比 = 在均线上方的股票数 / 有效股票总数 × 100%

档位（用于 UI 颜色）：
  - >= 80%：高温（红色）
  - <= 20%：低温（绿色）
  - 其它：常温（蓝色）
"""
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


def _days_ago(days):
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


# 温度档位
LEVEL_HOT = "hot"      # >= 80% 红
LEVEL_COLD = "cold"    # <= 20% 绿
LEVEL_NORMAL = "normal"  # 其它 蓝


def level_of(percent):
    """根据占比返回温度档位。"""
    if percent >= 80:
        return LEVEL_HOT
    if percent <= 20:
        return LEVEL_COLD
    return LEVEL_NORMAL


class MarketThermometerAnalyzer:
    """市场温度计分析器。

    用法：
        az = MarketThermometerAnalyzer()
        result = az.compute(progress_callback=print)
        # result = {percent, above_count, total, ma_days, date, level}
    """

    MA_DAYS = 20
    # 多拉几天以应对停牌（保证至少能凑齐 20 个交易日）
    LOOKBACK_DAYS = 40

    def __init__(self, data_dir="data"):
        self.data_dir = data_dir

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
            "date,code,close",
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
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        # 去掉停牌（close 为空）
        df = df.dropna(subset=["close"])
        return df.sort_values("date").reset_index(drop=True)

    # ---------------- 主入口 ----------------
    def compute(self, progress_callback=None):
        """计算当天在 20 日均线上方的股票占比。

        Returns:
            dict: percent, above_count, total, ma_days, date, level
            失败时返回 None。
        """
        end_date = _today_str()
        start_date = _days_ago(self.LOOKBACK_DAYS)

        def log(msg):
            if progress_callback:
                progress_callback(msg)

        log("登录 baostock ...")
        bs = self._login()
        try:
            log(f"获取 {end_date} 全市场股票代码 ...")
            codes = self._get_all_stock_codes(bs, end_date)
            total = len(codes)
            log(f"共 {total} 只股票，开始计算 {self.MA_DAYS} 日均线 ...")

            above_count = 0
            valid_count = 0
            latest_date = end_date
            success = 0
            for i, code in enumerate(codes, 1):
                try:
                    df = self._fetch_kline(bs, code, start_date, end_date)
                    if df is None or df.empty or len(df) < self.MA_DAYS:
                        continue
                    # 最近 MA_DAYS 个交易日的收盘价均值
                    ma = df["close"].tail(self.MA_DAYS).mean()
                    last_close = df["close"].iloc[-1]
                    if ma and ma > 0 and last_close is not None:
                        valid_count += 1
                        if last_close > ma:
                            above_count += 1
                        # 记录最新交易日（取所有股票的最近日期）
                        d = df["date"].iloc[-1]
                        if d and d > latest_date:
                            latest_date = d
                    success += 1
                except Exception:
                    pass
                if i % 100 == 0 or i == total:
                    log(f"进度 {i}/{total}  有效 {valid_count}  均线上 {above_count}")
                time.sleep(0.05)  # baostock 限速
        finally:
            self._logout(bs)

        if valid_count == 0:
            log("未取得有效数据")
            return None

        percent = round(above_count * 100.0 / valid_count, 2)
        result = {
            "percent": percent,
            "above_count": above_count,
            "total": valid_count,
            "ma_days": self.MA_DAYS,
            "date": latest_date,
            "level": level_of(percent),
        }
        log(f"完成：{above_count}/{valid_count} = {percent}% 在 {self.MA_DAYS} 日均线上方")
        return result
