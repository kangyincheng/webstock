import os
import re
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler


# ============ Token & 常量 ============

# Tushare Token：优先环境变量（允许空字符串 fallback 到默认值）
# docker-compose.yml 里传了 TUSHARE_TOKEN=${TUSHARE_TOKEN:-} 会把空值也传进来
TUSHARE_TOKEN = (os.environ.get("TUSHARE_TOKEN") or
                 "11149a06751c90585c1aaf59510f71c05b2633b4d56d20d50e85c4e0")

# 数据源优先级：baostock 主用 → tushare 备用
_DATA_SOURCES = ["baostock", "tushare"]


# ============ 导入 & 工具 ============

def _import_baostock():
    try:
        import baostock as bs
        return bs
    except ImportError:
        raise ImportError("未安装 baostock：pip install baostock")


def _import_tushare():
    try:
        import tushare as ts
        ts.set_token(TUSHARE_TOKEN)
        pro = ts.pro_api()
        return pro
    except ImportError:
        raise ImportError("未安装 tushare：pip install tushare")


def _to_bs_code(code: str) -> str:
    """把 sh.600036 / sz000975 / 600036.SH / 600036 统一成 baostock 格式 sh.600036"""
    s = str(code).strip().upper().replace(" ", "")
    # 去掉尾部 .SH / .SZ / .BJ
    if s.endswith(".SH"):
        return "sh." + s[:-3]
    if s.endswith(".SZ"):
        return "sz." + s[:-3]
    if s.endswith(".BJ"):
        return "bj." + s[:-3]
    # 带前缀但没点：sh600036 → sh.600036
    m = re.match(r"^(SH|SZ|BJ)(\d{6})$", s)
    if m:
        return m.group(1).lower() + "." + m.group(2)
    # 已标准：sh.600036 / sz.000975
    if re.match(r"^(sh|sz|bj)\.\d{6}$", s):
        return s
    # 纯数字：600036
    if re.match(r"^\d{6}$", s):
        if s.startswith(("60", "68", "90")):
            return "sh." + s
        return "sz." + s
    return code


def _to_ts_code(code: str) -> str:
    """把任意代码 → tushare 格式 600036.SH"""
    bs = _to_bs_code(code)
    m = re.match(r"^(sh|sz|bj)\.(\d{6})$", bs)
    if m:
        return m.group(2) + "." + m.group(1).upper()
    return code


def _to_ts_freq(frequency: str) -> str:
    """d → D / w → W / m → M"""
    return (frequency or "d").upper()


def _to_ts_adjust(adjustflag: str) -> str:
    """baostock adjustflag: 1=前复权 2=后复权 3=不复权 → tushare adj: qfq/hfq/"""
    mapping = {"1": "qfq", "2": "hfq", "3": ""}
    return mapping.get(str(adjustflag or "2"), "hfq")


# ============ StockDataLoader ============

class StockDataLoader:
    """多数据源自动降级的股票数据加载器。

    主用 baostock（免费、字段全），登录黑名单 / 查询失败 / 模块未安装时
    自动切换到 tushare。对外接口 fetch_data() 完全不变，内部透明处理。
    """

    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.scaler = MinMaxScaler(feature_range=(0, 1))
        self.df = None
        self.scaled_data = None
        self.train_data = None
        self.test_data = None
        self.X_train = None
        self.y_train = None
        self.X_test = None
        self.y_test = None
        self.feature_cols = []
        self._last_source = None  # 记录最后成功的数据源（调试用）

    # ------ 旧接口保留 ------

    def login(self):
        """兼容旧代码：只做 baostock login，失败会抛黑名单异常。"""
        bs = _import_baostock()
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"Baostock login failed: {lg.error_msg}")
        return lg

    def logout(self):
        try:
            bs = _import_baostock()
            bs.logout()
        except ImportError:
            pass

    # ------ 私有下载方法（baostock / tushare）------

    def _fetch_via_baostock(self, stock_code, start_date, real_end,
                            frequency, adjustflag, fields, progress_callback):
        bs_code = _to_bs_code(stock_code)

        if progress_callback:
            progress_callback(f"[baostock] 登录并下载 {bs_code} ({start_date} ~ {real_end})...")

        bs = _import_baostock()
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"Baostock login failed: {lg.error_msg}")

        try:
            rs = bs.query_history_k_data_plus(
                bs_code, fields,
                start_date=start_date, end_date=real_end,
                frequency=frequency, adjustflag=adjustflag,
            )
            data_list = []
            while rs.error_code == "0" and rs.next():
                data_list.append(rs.get_row_data())
            if rs.error_code != "0":
                raise RuntimeError(f"Baostock query failed: {rs.error_msg}")
        finally:
            bs.logout()

        if not data_list:
            raise RuntimeError("Baostock 返回空数据")

        df = pd.DataFrame(data_list, columns=rs.fields)
        return self._normalize_df(df, stock_code=bs_code)

    def _fetch_via_tushare(self, stock_code, start_date, real_end,
                           frequency, adjustflag, progress_callback):
        """用 tushare daily 接口下载日 K，手动拼后复权 / 前复权。

        tushare 基础 token 权限有限：
          - pro_bar (旧接口) 报错 "请指定正确的接口名" 或权限不足
          - daily 接口稳定可用（基础权限）
          - adj_factor 1次/分钟 频率限制，try/except 兜底
        所以这里用 daily + adj_factor 手动算复权，拼不出来就用不复权。
        """
        ts_code = _to_ts_code(stock_code)
        start_t = start_date.replace("-", "")
        end_t = real_end.replace("-", "")

        if progress_callback:
            progress_callback(f"[tushare] daily 下载 {ts_code} ({start_t} ~ {end_t})...")

        pro = _import_tushare()

        # 1) 日线（tushare 基础权限）
        df = pro.daily(ts_code=ts_code, start_date=start_t, end_date=end_t)
        if df is None or df.empty:
            raise RuntimeError(f"Tushare daily 空数据 ({ts_code})")

        df = df.sort_values("trade_date").reset_index(drop=True)

        # 2) 复权（可选，频率/权限限制时 gracefully 跳过）
        need_adj = str(adjustflag or "2") in ("1", "2")
        adj_applied = False
        if need_adj:
            try:
                adj = pro.adj_factor(ts_code=ts_code, start_date=start_t, end_date=end_t)
                if adj is not None and not adj.empty:
                    df = df.merge(adj[["trade_date", "adj_factor"]], on="trade_date", how="left")
                    base_adj = df["adj_factor"].dropna().iloc[-1]  # 最后交易日的 factor
                    price_cols = ["open", "high", "low", "close", "pre_close"]
                    if str(adjustflag or "2") == "2":  # 后复权
                        for col in price_cols:
                            df[col] = df[col] * df["adj_factor"] / base_adj
                    else:  # 前复权
                        first_adj = df["adj_factor"].dropna().iloc[0]
                        for col in price_cols:
                            df[col] = df[col] * df["adj_factor"] / first_adj
                    df.drop(columns=["adj_factor"], inplace=True, errors="ignore")
                    adj_applied = True
                    if progress_callback:
                        progress_callback("[tushare] 复权因子应用成功")
            except Exception as e:
                if progress_callback:
                    progress_callback(f"[tushare] 复权跳过: {e}")

        # 3) tushare 列名 → baostock 列名，保持下游完全兼容
        # daily: ts_code, trade_date, open, high, low, close, pre_close,
        #        change, pct_chg, vol, amount
        # baostock: date, code, open, high, low, close, preclose, volume,
        #           amount, turn, peTTM, pbMRQ, psTTM, pcfNcfTTM, isST
        rename_map = {
            "trade_date": "date",
            "ts_code": "_ts_code",       # 先存，后面转 code
            "vol": "volume",
            "pre_close": "preclose",
        }
        df = df.rename(columns=rename_map)

        # date: YYYYMMDD → YYYY-MM-DD
        df["date"] = df["date"].astype(str).str.replace(
            r"^(\d{4})(\d{2})(\d{2})$", r"\1-\2-\3", regex=True
        )

        # code: 用 baostock 格式
        df["code"] = _to_bs_code(ts_code)

        # 缺失列补空字符串（isST / turn / peTTM / pbMRQ ...）
        for col in ["isST", "turn", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM"]:
            if col not in df.columns:
                df[col] = ""

        return self._normalize_df(df, stock_code=ts_code)

    @staticmethod
    def _normalize_df(df, stock_code=None):
        """把 DataFrame 的数值列强制转 numeric、dropna（保持和原 baostock 路径一致）。

        关键设计：baostock 返回的缺失字段是空字符串 ""，tushare 根本没有 turn/peTTM 等列。
        策略：
          1) 所有列 to_numeric（date/code/_ts_code 保留字符串）
          2) dropna **只在真正有数值的列上** 执行，跳过所有行都为空的列
          3) 最后删掉全 NaN 的列，避免下游 preprocess 选到空特征
        """
        for col in df.columns:
            if col in ("date", "code", "_ts_code"):
                continue
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 找出真正有数值的列
        real_numeric_cols = [
            c for c in df.columns
            if c not in ("date", "code", "_ts_code")
            and df[c].notna().any()
        ]
        if real_numeric_cols:
            df.dropna(subset=real_numeric_cols, how="any", inplace=True)

        # 删掉全 NaN 的列（避免下游 preprocess 选到空列）
        all_nan_cols = [
            c for c in df.columns
            if c not in ("date", "code", "_ts_code")
            and df[c].isna().all()
        ]
        if all_nan_cols:
            df.drop(columns=all_nan_cols, inplace=True)

        df.reset_index(drop=True, inplace=True)
        return df

    # ------ 主入口：自动降级 ------

    def fetch_data(self, stock_code, start_date, end_date, frequency="d",
                   adjustflag="2", fields=None, progress_callback=None):
        from datetime import date

        today_str = date.today().strftime("%Y-%m-%d")

        if fields is None:
            fields = "date,code,open,high,low,close,preclose,volume,amount,turn,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"

        real_end = end_date if end_date else today_str
        cache_file = os.path.join(
            self.data_dir, f"{stock_code}_{start_date}_{real_end}_{frequency}_{adjustflag}.csv"
        )

        # ---------- 缓存命中（和之前完全一样）----------
        CACHE_MAX_DAYS = 3
        use_cache = False
        if os.path.exists(cache_file):
            try:
                _head = pd.read_csv(cache_file, usecols=["date"])
                if not _head.empty:
                    last_cache_date = str(_head["date"].iloc[-1])[:10]
                    last_cache_dt = date.fromisoformat(last_cache_date)
                    age_days = (date.today() - last_cache_dt).days
                    if age_days <= CACHE_MAX_DAYS:
                        use_cache = True
                        if progress_callback:
                            progress_callback(f"命中缓存，最后交易日 {last_cache_date} ({age_days} 天前)")
                    else:
                        if progress_callback:
                            progress_callback(f"缓存过旧（最后 {last_cache_date}，距今 {age_days} 天），重新下载…")
            except Exception:
                use_cache = False

        if use_cache:
            if progress_callback:
                progress_callback("正在从缓存加载数据...")
            self.df = pd.read_csv(cache_file)
            if progress_callback:
                progress_callback(f"缓存加载完成，共 {len(self.df)} 条数据")
            return self.df

        # ---------- 数据源自动降级 ----------
        errors = []
        df = None
        for src in _DATA_SOURCES:
            try:
                if src == "baostock":
                    df = self._fetch_via_baostock(
                        stock_code, start_date, real_end,
                        frequency, adjustflag, fields, progress_callback)
                elif src == "tushare":
                    df = self._fetch_via_tushare(
                        stock_code, start_date, real_end,
                        frequency, adjustflag, progress_callback)
                self._last_source = src
                break  # 成功就跳出
            except Exception as e:
                errors.append(f"{src}: {e}")
                if progress_callback:
                    progress_callback(f"[warn] {src} 失败: {e}")

        if df is None:
            raise RuntimeError(
                f"所有数据源都失败：{' | '.join(errors)}"
            )

        # ---------- 写缓存 ----------
        df.to_csv(cache_file, index=False)
        if progress_callback:
            progress_callback(
                f"[{self._last_source}] 数据下载完成，共 {len(df)} 条，已缓存"
            )

        self.df = df
        return df

    # ------ preprocess / inverse_transform / dates（不变）------

    def preprocess(self, feature_cols=None, seq_len=60, train_ratio=0.8,
                   target_col="close", progress_callback=None):
        if self.df is None or len(self.df) == 0:
            raise ValueError("数据为空，请先下载数据")

        if feature_cols is None:
            feature_cols = ["open", "high", "low", "close", "volume", "amount", "turn"]

        available_cols = [c for c in feature_cols if c in self.df.columns]
        if not available_cols:
            raise ValueError("没有可用的特征列")
        self.feature_cols = available_cols

        if progress_callback:
            progress_callback(f"使用特征列: {available_cols}")
            progress_callback("正在归一化数据...")

        data = self.df[available_cols].values.astype(np.float32)
        self.scaled_data = self.scaler.fit_transform(data)

        target_idx = available_cols.index(target_col) if target_col in available_cols else 0

        if progress_callback:
            progress_callback(f"目标列: {target_col} (索引={target_idx})")
            progress_callback("正在构建时间序列数据集...")

        X, y = [], []
        for i in range(seq_len, len(self.scaled_data)):
            X.append(self.scaled_data[i - seq_len : i])
            y.append(self.scaled_data[i, target_idx])

        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.float32).reshape(-1, 1)

        train_size = int(len(X) * train_ratio)
        self.X_train, self.X_test = X[:train_size], X[train_size:]
        self.y_train, self.y_test = y[:train_size], y[train_size:]

        if progress_callback:
            progress_callback(
                f"数据集构建完成 - 训练集: {len(self.X_train)}, 测试集: {len(self.X_test)}, "
                f"序列长度: {seq_len}, 特征数: {len(available_cols)}"
            )

        return self.X_train, self.y_train, self.X_test, self.y_test

    def inverse_transform_close(self, scaled_values, target_col="close"):
        if self.scaler is None or self.feature_cols is None:
            return scaled_values
        target_idx = self.feature_cols.index(target_col) if target_col in self.feature_cols else 0
        dummy = np.zeros((len(scaled_values), len(self.feature_cols)))
        dummy[:, target_idx] = scaled_values.flatten()
        return self.scaler.inverse_transform(dummy)[:, target_idx]

    def get_dates(self):
        if self.df is None:
            return None
        return self.df["date"].values

    def get_test_dates(self, seq_len=60, train_ratio=0.8):
        if self.df is None:
            return None
        dates = self.df["date"].values
        train_size = int((len(dates) - seq_len) * train_ratio)
        return dates[seq_len + train_size:]
