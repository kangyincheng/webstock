"""单元测试：验证 train_service 的预测反归一化 + 下一交易日窗口逻辑（无需 torch/tf）。

模拟场景：真实收盘价 40+，模型输出落在 [0,1] 缩放区间。
"""
import os
import sys
import numpy as np
import pandas as pd

SRC = "/workspace/src"
sys.path.insert(0, SRC)
BACKEND = "/workspace/backend"
sys.path.insert(0, BACKEND)

from data_loader import StockDataLoader


class MockTrainer:
    """模拟一个已训练好的模型：predict 直接返回输入窗口最后一帧的缩放目标值。"""
    def __init__(self, loader):
        self.loader = loader
        self.target_col = loader.target_col

    def predict(self, X):
        target_idx = self.loader.feature_cols.index(self.target_col)
        last = X[:, -1, target_idx]              # (N,)
        return last.reshape(-1, 1).astype(np.float32)


def build_loader(n=400, seq_len=60, base_price=43.5):
    loader = StockDataLoader(data_dir="/workspace/_predict_test_data")
    loader.target_col = "close"
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    close = base_price + np.cumsum(rng.normal(0, 0.4, n))
    df = pd.DataFrame({
        "date": dates,
        "open": close - 0.2,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": rng.integers(1e6, 1e7, n).astype(float),
        "amount": rng.integers(1e7, 1e8, n).astype(float),
        "turn": rng.uniform(0.1, 3, n),
    })
    loader.df = df
    loader.preprocess(
        feature_cols=["open", "high", "low", "close", "volume", "amount", "turn"],
        target_col="close", seq_len=seq_len, train_ratio=0.8,
    )
    return loader, df


def main():
    seq_len = 60
    loader, df = build_loader(n=400, seq_len=seq_len, base_price=43.5)
    trainer = MockTrainer(loader)

    pred_scaled = trainer.predict(loader.X_test)
    n = len(loader.df)
    n_train = int(n * 0.8)
    test_df = loader.df.iloc[n_train:]
    dates = test_df["date"].astype(str).tolist()
    actual = [round(float(x), 4) for x in test_df["close"].tolist()]

    pred_inv = loader.inverse_transform_close(pred_scaled, loader.target_col)
    pred_list = [round(float(x), 4) for x in pred_inv.ravel().tolist()]
    k = min(len(dates), len(actual), len(pred_list))
    dates = dates[-k:]; actual = actual[-k:]; pred_list = pred_list[-k:]

    last_window = loader.scaled_data[-seq_len:].reshape(1, seq_len, -1)
    next_scaled = trainer.predict(last_window)
    next_inv = loader.inverse_transform_close(next_scaled, loader.target_col)
    next_pred = round(float(np.asarray(next_inv).ravel()[0]), 4)

    print(f"actual  范围: [{min(actual):.2f}, {max(actual):.2f}]  (期望 ~40+)")
    print(f"pred    范围: [{min(pred_list):.2f}, {max(pred_list):.2f}]  (期望 ~40+)")
    print(f"next_day_pred: {next_pred}  (期望 ~40+, 接近最后一个实际值 {actual[-1]})")

    ok_pred_scale = min(pred_list) > 5 and max(pred_list) < 100
    ok_next_scale = next_pred > 5 and next_pred < 100
    ok_close = abs(next_pred - actual[-1]) < 2.0

    print("\n--- 结果 ---")
    print("预测值回到原始价格区间:", "PASS" if ok_pred_scale else "FAIL")
    print("下一交易日预测回到原始区间:", "PASS" if ok_next_scale else "FAIL")
    print("下一交易日预测合理(接近最后实际值):", "PASS" if ok_close else "FAIL")

    old_pred_max = max(float(x) for x in pred_scaled.ravel().tolist())
    print(f"\n[旧bug复现] 未反归一化的 pred 最大值 = {old_pred_max:.4f} (应 < 1)")
    assert old_pred_max <= 1.0, "scaled pred 应在 [0,1]"
    assert ok_pred_scale and ok_next_scale and ok_close, "反归一化/下一交易日逻辑校验失败"
    print("\nALL PASS")


if __name__ == "__main__":
    main()
