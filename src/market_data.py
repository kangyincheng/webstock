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

    # --------- 板块热度：按 industry 聚合 daily ---------
    def sector_heat(self, trade_date=None, use_cache=True, progress_callback=None):
        """返回 DataFrame。字段：rank/industry/count/avg_chg/med_chg/amount/up_cnt/down_cnt/limit_up."""
        def log(msg):
            if progress_callback:
                progress_callback(msg)
        # 若 token 未配置，返回 mock
        if not self.is_configured():
            log("未配置 Tushare token，返回演示板块数据")
            return self._mock_sector_heat()
        try:
            daily = self.fetch_daily(trade_date=trade_date)
            basic = self.fetch_stock_basic()
            if daily is None or daily.empty or basic is None or basic.empty:
                return self._mock_sector_heat()
            df = daily.merge(basic[["ts_code", "name", "industry"]], on="ts_code", how="left")
            df["industry"] = df["industry"].fillna("其他")
            df["amount_wan"] = pd.to_numeric(df.get("amount", 0), errors="coerce") / 10000.0
            df["pct_chg"] = pd.to_numeric(df.get("pct_chg", 0), errors="coerce")
            def _agg(g):
                up = int((g["pct_chg"] > 0).sum())
                down = int((g["pct_chg"] < 0).sum())
                limit_up = int((g["pct_chg"] >= 9.8).sum())
                return pd.Series({
                    "count": len(g),
                    "avg_chg": round(float(g["pct_chg"].mean()), 2),
                    "med_chg": round(float(g["pct_chg"].median()), 2),
                    "amount": round(float(g["amount_wan"].sum()), 2),
                    "up_cnt": up,
                    "down_cnt": down,
                    "limit_up": limit_up,
                })
            out = df.groupby("industry", dropna=False).apply(_agg).reset_index()
            out = out.sort_values("avg_chg", ascending=False).reset_index(drop=True)
            out.insert(0, "rank", out.index + 1)
            log(f"板块聚合完成：{len(out)} 个行业")
            return out
        except Exception as e:
            log(f"板块热度异常，回退演示数据：{e}")
            return self._mock_sector_heat()

    @staticmethod
    def _mock_sector_heat():
        import random
        inds = ["银行", "半导体", "医药生物", "新能源", "白酒", "计算机", "房地产",
                "汽车", "煤炭", "钢铁", "电力", "有色金属", "国防军工", "通信", "家电",
                "食品饮料", "机械设备", "化工", "农林牧渔", "传媒"]
        rows = []
        for i, ind in enumerate(sorted(inds)):
            avg = round(random.uniform(-5, 5), 2)
            cnt = random.randint(20, 150)
            rows.append({
                "rank": 0, "industry": ind, "count": cnt,
                "avg_chg": avg, "med_chg": round(avg + random.uniform(-1,1),2),
                "amount": round(random.uniform(10, 1000),2),
                "up_cnt": random.randint(0, cnt),
                "down_cnt": random.randint(0, cnt),
                "limit_up": random.randint(0, 8),
            })
        rows.sort(key=lambda r: r["avg_chg"], reverse=True)
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        import pandas as pd
        return pd.DataFrame(rows)

    # --------- 热门股票 TOP N ---------
    def hot_stocks(self, trade_date=None, sort_by="pct_chg", top_n=50,
                   use_cache=True, progress_callback=None):
        def log(msg):
            if progress_callback:
                progress_callback(msg)
        if not self.is_configured():
            log("未配置 Tushare token，返回演示热门股票")
            return self._mock_hot(top_n)
        try:
            daily = self.fetch_daily(trade_date=trade_date)
            basic = self.fetch_stock_basic()
            if daily is None or daily.empty or basic is None or basic.empty:
                return self._mock_hot(top_n)
            df = daily.merge(basic[["ts_code", "name", "industry"]], on="ts_code", how="left")
            for c in ["close", "pct_chg", "amount", "vol"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            if sort_by not in ("pct_chg", "amount", "vol"):
                sort_by = "pct_chg"
            df = df.sort_values(sort_by, ascending=False).head(top_n).reset_index(drop=True)
            df.insert(0, "rank", df.index + 1)
            df = df.rename(columns={
                "ts_code": "code",
                "name": "name",
                "industry": "industry",
                "trade_date": "trade_date",
            })
            if "amount" in df.columns:
                df["amount"] = (df["amount"] / 10000.0).round(2)
                df = df.rename(columns={"amount": "amount(万元)"})
            if "vol" in df.columns:
                df = df.rename(columns={"vol": "vol(手)"})
            log(f"热门股票：{len(df)} 条，按 {sort_by}")
            return df
        except Exception as e:
            log(f"热门股票异常，回退演示数据：{e}")
            return self._mock_hot(top_n)

    @staticmethod
    def _mock_hot(n=50):
        import random
        import pandas as pd
        random.seed(42)
        prefix = [("sh.", "60"), ("sz.", "00"), ("sh.", "688"), ("sz.", "30")]
        names = ["东财科技", "恒瑞医药", "宁德时代", "贵州茅台", "招商银行", "比亚迪",
                 "中国平安", "隆基绿能", "北方华创", "长江电力", "海康威视", "药明康德",
                 "伊利股份", "美的集团", "海尔智家", "紫金矿业", "中信证券", "立讯精密"]
        inds = ["半导体", "医药", "新能源", "白酒", "银行", "汽车", "保险", "光伏", "电力",
                "电子", "消费", "家电", "有色", "券商"]
        rows = []
        for i in range(n):
            p, suf = random.choice(prefix)
            # suf 为股票代码前缀（2 或 3 位），补足到 6 位标准代码
            pad = 6 - len(suf)
            tail = random.randint(0, 10 ** pad - 1) if pad > 0 else 0
            code = p + suf + str(tail).zfill(pad)
            pct = round(random.uniform(-10, 10), 2)
            close = round(random.uniform(3, 300), 2)
            rows.append({
                "rank": i + 1,
                "name": random.choice(names),
                "code": code,
                "industry": random.choice(inds),
                "close": close,
                "pct_chg(%)": pct,
                "amount(万元)": round(random.uniform(100, 200000), 2),
                "vol(手)": random.randint(1000, 5000000),
            })
        return pd.DataFrame(rows)
