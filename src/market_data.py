"""Tushare 行情客户端。

功能：
  - 加载 token（环境变量 > tushare_token.txt > 失败提示）
  - 拉取全市场当日行情（pro.daily）
  - 拉取股票基本信息（pro.stock_basic，含 industry 字段）
  - 本地缓存（按 trade_date 命名 CSV，避免重复调用）
  - 自动查找最近交易日（往前回退 10 天）

token 加载顺序：
  1) 环境变量 TUSHARE_TOKEN
  2) 项目根目录下的 tushare_token.txt（首行）
  3) 抛出未配置异常

注意：tushare_token.txt 已加入 .gitignore，**不会被提交到 git**。
"""
import os
from datetime import datetime, timedelta

import pandas as pd


def _import_tushare():
    try:
        import tushare as ts
        return ts
    except ImportError:
        raise ImportError(
            "未安装 tushare 模块，请先执行：pip install tushare")


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_token():
    """按优先级加载 tushare token。"""
    # 1) 环境变量
    tok = os.environ.get("TUSHARE_TOKEN", "").strip()
    if tok:
        return tok
    # 2) 项目根的 tushare_token.txt
    path = os.path.join(_project_root(), "tushare_token.txt")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#"):
                        return s
        except Exception:
            pass
    return ""


class TushareClient:
    """Tushare 行情客户端。"""

    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = os.path.join(_project_root(), "data")
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self._token = load_token()
        self._pro = None

    # ---------------- token / 登录 ----------------
    def is_configured(self):
        return bool(self._token)

    def _get_pro(self):
        if not self.is_configured():
            raise RuntimeError(
                "未配置 Tushare token。请：\n"
                "  1) 在项目根目录创建 tushare_token.txt 文件，把 token 写入第一行；或\n"
                "  2) 设置环境变量 TUSHARE_TOKEN")
        if self._pro is None:
            ts = _import_tushare()
            ts.set_token(self._token)
            self._pro = ts.pro_api()
        return self._pro

    # ---------------- 最近交易日 ----------------
    @staticmethod
    def _to_tushare_date(d):
        """datetime -> 'YYYYMMDD'"""
        return d.strftime("%Y%m%d")

    def find_latest_trade_date(self, max_back=15):
        """往前回退，找到有行情数据的最近交易日。"""
        pro = self._get_pro()
        for back in range(0, max_back + 1):
            d = datetime.now() - timedelta(days=back)
            trade_date = self._to_tushare_date(d)
            try:
                df = pro.daily(trade_date=trade_date,
                               fields="ts_code,trade_date,close,pct_chg,amount")
                if df is not None and len(df) > 50:
                    return trade_date, df
            except Exception:
                continue
        return None, None

    # ---------------- 行情拉取 + 缓存 ----------------
    def fetch_daily(self, trade_date=None):
        """拉取指定交易日的全市场日线行情。

        Args:
            trade_date: 'YYYYMMDD' 格式；若为 None 则自动找最近交易日

        Returns:
            DataFrame，列：ts_code, trade_date, open, high, low, close,
                          pct_chg, amount, vol
            若未找到数据返回 None
        """
        if trade_date:
            cache = os.path.join(self.data_dir, f"daily_{trade_date}.csv")
            if os.path.exists(cache):
                return pd.read_csv(cache, dtype={"ts_code": str, "trade_date": str})
            pro = self._get_pro()
            df = pro.daily(trade_date=trade_date,
                           fields="ts_code,trade_date,open,high,low,close,pct_chg,amount,vol")
            if df is None or df.empty:
                return None
            df.to_csv(cache, index=False)
            return df
        # 自动找最近交易日
        latest_trade_date, df = self.find_latest_trade_date()
        if latest_trade_date is None:
            return None
        cache = os.path.join(self.data_dir, f"daily_{latest_trade_date}.csv")
        if not os.path.exists(cache):
            df.to_csv(cache, index=False)
        return df

    def fetch_stock_basic(self):
        """拉取股票基本信息（含 industry 字段）。

        Returns:
            DataFrame，列：ts_code, symbol, name, industry, market, list_date
        """
        cache = os.path.join(self.data_dir, "stock_basic.csv")
        # 缓存 1 天有效
        if os.path.exists(cache):
            age = datetime.now().timestamp() - os.path.getmtime(cache)
            if age < 86400:
                return pd.read_csv(cache, dtype={"ts_code": str, "symbol": str})
        pro = self._get_pro()
        df = pro.stock_basic(exchange="", list_status="L",
                             fields="ts_code,symbol,name,industry,market,list_date")
        if df is None or df.empty:
            return None
        df.to_csv(cache, index=False)
        return df
