import os
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler


def _import_baostock():
    """延迟导入 baostock，避免未安装时无法启动 GUI"""
    try:
        import baostock as bs
        return bs
    except ImportError:
        raise ImportError(
            "未安装 baostock 模块，请先执行：pip install baostock"
        )


class StockDataLoader:
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

    def login(self):
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

    def fetch_data(self, stock_code, start_date, end_date, frequency="d",
                   adjustflag="2", fields=None, progress_callback=None):
        if fields is None:
            fields = "date,code,open,high,low,close,preclose,volume,amount,turn,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"

        cache_file = os.path.join(
            self.data_dir, f"{stock_code}_{start_date}_{end_date}_{frequency}_{adjustflag}.csv"
        )

        if os.path.exists(cache_file):
            if progress_callback:
                progress_callback("正在从缓存加载数据...")
            self.df = pd.read_csv(cache_file)
            if progress_callback:
                progress_callback(f"缓存加载完成，共 {len(self.df)} 条数据")
            return self.df

        if progress_callback:
            progress_callback("正在登录 Baostock...")
        self.login()

        if progress_callback:
            progress_callback(f"正在下载 {stock_code} 数据 ({start_date} ~ {end_date})...")

        rs = _import_baostock().query_history_k_data_plus(
            stock_code,
            fields,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjustflag=adjustflag,
        )

        data_list = []
        while rs.error_code == "0" and rs.next():
            data_list.append(rs.get_row_data())

        if rs.error_code != "0":
            self.logout()
            raise RuntimeError(f"数据下载失败: {rs.error_msg}")

        self.df = pd.DataFrame(data_list, columns=rs.fields)

        for col in self.df.columns:
            if col not in ["date", "code", "isST"]:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

        self.df.dropna(inplace=True)
        self.df.reset_index(drop=True, inplace=True)

        self.df.to_csv(cache_file, index=False)
        if progress_callback:
            progress_callback(f"数据下载完成，共 {len(self.df)} 条，已缓存")

        self.logout()
        return self.df

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
