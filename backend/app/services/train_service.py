"""把训练/预测业务从 gui.py / tf_gui.py 中抽离为纯 Python 接口。

对外暴露：TrainingService.run_training(params, progress_cb) -> TrainResult
"""
from __future__ import annotations

import os
import sys
import time
import uuid
import traceback
from typing import Any, Callable, Dict, Optional

import numpy as np

# 允许直接使用 workspace/src 中的核心模块
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from data_loader import StockDataLoader  # noqa: E402


DATA_DIR = os.path.join(BASE_DIR, "backend", "data")
MODEL_DIR = os.path.join(BASE_DIR, "backend", "models")


def _import_pytorch_trainer():
    from trainer import StockTrainer
    return StockTrainer


def _import_tf_trainer():
    from tf_trainer import TFStockTrainer
    return TFStockTrainer


def _df_to_lists(df_loader: StockDataLoader):
    """返回测试集上的 dates/actual/predicted（对齐长度）。"""
    dates = []
    actual = []
    if df_loader.df is not None:
        n = len(df_loader.df)
        n_train = int(n * 0.8)
        test_df = df_loader.df.iloc[n_train:]
        dates = test_df["date"].astype(str).tolist() if "date" in test_df.columns else []
        target = df_loader.target_col if hasattr(df_loader, "target_col") else "close"
        if target in test_df.columns:
            actual = [round(float(x), 4) for x in test_df[target].tolist()]
    return dates, actual


class TrainingService:
    """统一封装 PyTorch / TensorFlow 双框架训练流程。"""

    def __init__(self, data_dir: str = DATA_DIR, model_dir: str = MODEL_DIR):
        self.data_dir = data_dir
        self.model_dir = model_dir
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(model_dir, exist_ok=True)

    # -------- 进度回调包装器 --------
    @staticmethod
    def _wrap_cb(task_id: str, progress_cb: Optional[Callable], stage: str, **extra):
        def _cb(msg=None, epoch=0, total_epochs=0, train_loss=None, val_loss=None):
            if progress_cb is None:
                return
            payload: Dict[str, Any] = {
                "task_id": task_id,
                "stage": stage,
                "epoch": epoch,
                "total_epochs": total_epochs,
                "train_loss": train_loss,
                "val_loss": val_loss,
                "message": msg or "",
            }
            payload.update(extra)
            try:
                progress_cb(payload)
            except Exception:
                pass
        return _cb

    # -------- 主流程 --------
    def run_training(self, params: Dict[str, Any],
                     progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None
                     ) -> Dict[str, Any]:
        task_id = uuid.uuid4().hex[:10]
        log = self._wrap_cb(task_id, progress_cb, "init")
        result = {
            "task_id": task_id,
            "status": "error",
            "save_path": None,
            "train_losses": [],
            "val_losses": [],
            "metrics": {},
            "actual": [],
            "predicted": [],
            "dates": [],
            "error": None,
        }
        try:
            # 1) 加载数据
            log(msg=f"[1/4] 加载数据 {params.get('stock_code')} ...")
            loader = StockDataLoader(data_dir=self.data_dir)
            loader.target_col = params.get("target_col", "close")
            feature_cols = [c.strip() for c in params.get("feature_cols", "").split(",") if c.strip()]
            fetched = loader.fetch_data(
                stock_code=params.get("stock_code", "sh.600036"),
                start_date=params.get("start_date", "2018-01-01"),
                end_date=params.get("end_date") or None,
                frequency=params.get("frequency", "d"),
                adjustflag=params.get("adjustflag", "2"),
                fields=None,
            )
            if fetched is None or loader.df is None or loader.df.empty:
                raise RuntimeError("加载行情数据失败，请检查股票代码/日期/网络")

            loader.preprocess(
                feature_cols=feature_cols or ["open", "high", "low", "close", "volume", "amount", "turn"],
                target_col=loader.target_col,
                seq_len=int(params.get("seq_len", 60)),
                train_ratio=float(params.get("train_ratio", 0.8)),
            )
            log(msg=f"[2/4] 数据就绪：训练 {len(loader.X_train)} 条，测试 {len(loader.X_test)} 条")

            # 2) 构建模型
            framework = str(params.get("framework", "pytorch")).lower()
            log = self._wrap_cb(task_id, progress_cb, "build")
            log(msg=f"[3/4] 构建 {framework} {params.get('model_type')} 模型 ...")

            if framework == "tensorflow":
                TFStockTrainer = _import_tf_trainer()
                trainer: Any = TFStockTrainer(model_dir=self.model_dir)
                params["input_size"] = loader.X_train.shape[2]
                params["seq_len"] = int(params.get("seq_len", 60))
                trainer.build_model(params)
            else:
                PTStockTrainer = _import_pytorch_trainer()
                trainer = PTStockTrainer(model_dir=self.model_dir)
                params["input_size"] = loader.X_train.shape[2]
                trainer.build_model(params)

            # 3) 训练（带 epoch 回调）
            log = self._wrap_cb(task_id, progress_cb, "train")
            epochs = int(params.get("epochs", 80))
            batch_size = int(params.get("batch_size", 32))
            lr = float(params.get("learning_rate", 1e-3))

            def _epoch_cb(ep, tl, vl):
                log(epoch=ep, total_epochs=epochs, train_loss=float(tl) if tl is not None else None,
                    val_loss=float(vl) if vl is not None else None,
                    msg=f"epoch {ep}/{epochs} loss={tl} val={vl}")

            X_train, y_train = loader.X_train, loader.y_train
            # 切出 10% 做 val
            n_val = max(32, int(len(X_train) * 0.1))
            X_val, y_val = X_train[-n_val:], y_train[-n_val:]
            X_tr, y_tr = X_train[:-n_val], y_train[:-n_val]

            train_losses, val_losses = trainer.train(
                X_tr, y_tr, X_val, y_val,
                epochs=epochs, batch_size=batch_size, learning_rate=lr,
                optimizer_type=params.get("optimizer_type", "Adam"),
                loss_type=params.get("loss_type", "MSE"),
                early_stopping_patience=int(params.get("early_stopping_patience", 15)),
                progress_callback=None,
                epoch_callback=_epoch_cb,
            )
            result["train_losses"] = [float(x) for x in (train_losses or [])]
            result["val_losses"] = [float(x) for x in (val_losses or [])]

            # 4) 预测 & 保存
            log = self._wrap_cb(task_id, progress_cb, "predict")
            log(msg="[4/4] 测试集推理 & 保存模型 ...")
            pred = trainer.predict(loader.X_test)
            dates, actual = _df_to_lists(loader)
            # 对齐长度：pred 可能比 dates 短 seq_len
            pred_list = [round(float(x), 4) for x in pred.ravel().tolist()]
            k = min(len(dates), len(actual), len(pred_list))
            if k < len(dates):
                dates = dates[-k:] if k else dates
                actual = actual[-k:] if k else actual

            result["predicted"] = pred_list[-k:] if k else pred_list
            result["actual"] = actual
            result["dates"] = dates

            # 计算简单指标
            if result["actual"] and result["predicted"]:
                a = np.array(result["actual"])
                p = np.array(result["predicted"][: len(a)])
                mae = float(np.mean(np.abs(a - p)))
                rmse = float(np.sqrt(np.mean((a - p) ** 2)))
                mape = float(np.mean(np.abs((a - p) / np.where(a == 0, 1e-9, a))) * 100)
                result["metrics"] = {"MAE": round(mae, 4), "RMSE": round(rmse, 4), "MAPE%": round(mape, 3)}

            model_name = params.get("model_name") or (
                f"{params.get('stock_code','stk').replace('.','_')}"
                f"_{framework}_{params.get('model_type','LSTM')}_{int(time.time())}"
            )
            try:
                save_path = trainer.save_model(model_name, loader)
                result["save_path"] = str(save_path) if save_path else None
            except Exception as e:
                result["save_path"] = None
                result["error"] = f"模型保存失败：{e}"

            result["status"] = "success"
            log = self._wrap_cb(task_id, progress_cb, "done")
            log(msg="任务完成")
            return result

        except Exception as e:
            result["status"] = "error"
            result["error"] = f"{e}\n{traceback.format_exc(limit=4)}"
            if progress_cb:
                try:
                    progress_cb({"task_id": task_id, "stage": "error", "message": result["error"]})
                except Exception:
                    pass
            return result

    # -------- 模型管理 --------
    def list_models(self, framework: Optional[str] = None):
        names = set()
        for fn in os.listdir(self.model_dir) if os.path.isdir(self.model_dir) else []:
            if framework == "pytorch" and fn.endswith(".pth"):
                names.add(fn)
            elif framework == "tensorflow" and fn.endswith(".keras"):
                names.add(fn)
            elif framework is None and (fn.endswith(".pth") or fn.endswith(".keras")):
                names.add(fn)
        return sorted(names)

    def delete_model(self, name: str) -> bool:
        if ".." in name or "/" in name:
            return False
        fp = os.path.join(self.model_dir, name)
        if os.path.exists(fp):
            try:
                os.remove(fp)
                return True
            except OSError:
                return False
        return False
