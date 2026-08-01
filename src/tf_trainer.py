"""TensorFlow Keras 版本的 StockTrainer。

接口与 trainer.StockTrainer 保持一致（build_model/train/predict/save/load/delete/list），
便于 gui.py 只需替换 import 和少量参数适配即可复用。
"""
import json
import os

import numpy as np


MODEL_SUFFIX = ".keras"  # Keras 原生格式（推荐）


def _import_tf():
    try:
        import tensorflow as tf  # noqa: F401
        return tf
    except ImportError:
        raise ImportError(
            "未安装 tensorflow，请先执行：pip install tensorflow>=2.10.0")


class TFStockTrainer:
    """TensorFlow Keras 版本训练器。

    方法、字段、返回形状与 StockTrainer 对齐：
      - build_model(params)
      - train(X_train, y_train, X_val, y_val, epochs, batch_size, ...) -> (train_losses, val_losses)
      - predict(X) -> np.ndarray, shape (N, 1)
      - save_model(name, data_loader, extra_info) -> save_path
      - load_model(name, data_loader)
      - list_models() / delete_model(name)
    """

    def __init__(self, model_dir="models", device=None):
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)
        # TensorFlow 版本由用户在系统级配置（CPU/GPU），这里仅记录
        self.device = device
        self.model = None
        self.model_type = None
        self.model_config = {}
        self.train_losses = []
        self.val_losses = []
        # TF 回调中用到
        self._progress_cb = None
        self._epoch_cb = None

    def _get_model_config(self, params):
        config = {
            "model_type": params.get("model_type", "LSTM"),
            "input_size": params.get("input_size", 7),
            "seq_len": params.get("seq_len", 60),
            "hidden_size": params.get("hidden_size", 128),
            "num_layers": params.get("num_layers", 2),
            "dropout": params.get("dropout", 0.2),
            "bidirectional": params.get("bidirectional", False),
            "d_model": params.get("d_model", 128),
            "nhead": params.get("nhead", 4),
            "dim_feedforward": params.get("dim_feedforward", 256),
        }
        return config

    def build_model(self, params):
        from .tf_model import build_model
        config = self._get_model_config(params)
        self.model_type = config["model_type"]
        self.model_config = config
        model_kwargs = {k: v for k, v in config.items()
                        if k not in ("model_type", "input_size", "seq_len")}
        self.model = build_model(
            config["model_type"],
            config["input_size"],
            seq_len=config["seq_len"],
            **model_kwargs,
        )
        return self.model

    def train(self, X_train, y_train, X_val=None, y_val=None, epochs=100,
              batch_size=32, learning_rate=0.001, optimizer_type="Adam",
              loss_type="MSE", early_stopping_patience=15,
              progress_callback=None, epoch_callback=None):
        tf = _import_tf()
        if self.model is None:
            raise ValueError("模型未构建，请先调用 build_model")

        # 1) 优化器
        optimizer = self._make_optimizer(optimizer_type, learning_rate)

        # 2) 损失函数
        loss_fn = self._make_loss(loss_type)

        # 3) 编译
        self.model.compile(optimizer=optimizer, loss=loss_fn)

        # 4) 回调
        self._progress_cb = progress_callback
        self._epoch_cb = epoch_callback
        callbacks = []

        class ReportCb(tf.keras.callbacks.Callback):
            def on_train_begin(this_self, logs=None):
                if progress_callback:
                    progress_callback(
                        f"开始训练 - 总轮数: {epochs}")

            def on_epoch_end(this_self, epoch, logs=None):
                logs = logs or {}
                train_loss = float(logs.get("loss", 0.0))
                val_loss = float(logs.get("val_loss", train_loss))
                self.train_losses.append(train_loss)
                self.val_losses.append(val_loss)
                if epoch_callback:
                    epoch_callback(epoch + 1, epochs, train_loss, val_loss)

        callbacks.append(ReportCb())

        if early_stopping_patience and early_stopping_patience > 0:
            monitor = "val_loss" if (X_val is not None and y_val is not None) else "loss"
            callbacks.append(tf.keras.callbacks.EarlyStopping(
                monitor=monitor,
                patience=early_stopping_patience,
                restore_best_weights=True,
                mode="min",
                verbose=0,
            ))
        callbacks.append(tf.keras.callbacks.ReduceLROnPlateau(
            monitor=("val_loss" if (X_val is not None and y_val is not None) else "loss"),
            factor=0.5, patience=5, mode="min", verbose=0,
        ))

        # 5) 训练
        self.train_losses = []
        self.val_losses = []
        validation_data = None
        if X_val is not None and y_val is not None:
            validation_data = (X_val, y_val)

        # 减少 TF 详细日志
        verbose = 0
        try:
            self.model.fit(
                X_train, y_train,
                batch_size=batch_size,
                epochs=epochs,
                validation_data=validation_data,
                callbacks=callbacks,
                shuffle=True,
                verbose=verbose,
            )
        except Exception:
            raise

        if progress_callback:
            if self.train_losses:
                progress_callback(f"训练完成 - 最终训练损失: {self.train_losses[-1]:.6f}")
            if self.val_losses:
                progress_callback(f"最佳验证损失: {min(self.val_losses):.6f}")

        return self.train_losses, self.val_losses

    def predict(self, X):
        if self.model is None:
            raise ValueError("模型未构建或加载")
        # predict 返回 (N,1)
        y = self.model.predict(X, verbose=0)
        return np.asarray(y, dtype=np.float32).reshape(-1, 1)

    # ---------------- 保存 / 加载 ----------------
    def save_model(self, model_name, data_loader=None, extra_info=None):
        if self.model is None:
            raise ValueError("没有可保存的模型，请先训练模型")
        save_path = os.path.join(self.model_dir, f"{model_name}{MODEL_SUFFIX}")
        config_path = os.path.join(self.model_dir, f"{model_name}_config.json")

        # 用 Keras 原生格式保存，兼容后续加载
        self.model.save(save_path, include_optimizer=False)

        config = {
            "framework": "tensorflow",
            "model_type": self.model_type,
            "model_config": self.model_config,
            "train_losses": self.train_losses,
            "val_losses": self.val_losses,
        }
        if data_loader is not None:
            config["feature_cols"] = list(data_loader.feature_cols)
            try:
                config["scaler_min"] = data_loader.scaler.min_.tolist()
                config["scaler_scale"] = data_loader.scaler.scale_.tolist()
                config["scaler_data_min"] = data_loader.scaler.data_min_.tolist()
                config["scaler_data_max"] = data_loader.scaler.data_max_.tolist()
            except Exception:
                pass
        if extra_info:
            config.update(extra_info)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return save_path

    def load_model(self, model_name, data_loader=None):
        tf = _import_tf()
        save_path = os.path.join(self.model_dir, f"{model_name}{MODEL_SUFFIX}")
        config_path = os.path.join(self.model_dir, f"{model_name}_config.json")
        if not os.path.exists(save_path):
            raise FileNotFoundError(f"模型文件不存在: {save_path}")

        # Keras 自定义层需注意 positional_encoding 内的常数
        self.model = tf.keras.models.load_model(save_path, compile=False)

        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            self.model_type = config.get("model_type", self.model_type)
            self.model_config = config.get("model_config", self.model_config)
            self.train_losses = config.get("train_losses", [])
            self.val_losses = config.get("val_losses", [])
            if data_loader is not None:
                from sklearn.preprocessing import MinMaxScaler
                smin = config.get("scaler_min")
                sscale = config.get("scaler_scale")
                if smin is not None and sscale is not None:
                    n = len(smin)
                    data_loader.scaler = MinMaxScaler(feature_range=(0, 1))
                    data_loader.scaler.min_ = np.asarray(smin)
                    data_loader.scaler.scale_ = np.asarray(sscale)
                    data_loader.scaler.data_min_ = np.asarray(
                        config.get("scaler_data_min", np.zeros(n)))
                    data_loader.scaler.data_max_ = np.asarray(
                        config.get("scaler_data_max", np.ones(n)))
                    data_loader.scaler.n_features_in_ = n
                data_loader.feature_cols = config.get("feature_cols",
                                                      data_loader.feature_cols)
        return self.model

    def list_models(self):
        models = []
        if not os.path.exists(self.model_dir):
            return models
        for f in os.listdir(self.model_dir):
            if f.endswith(MODEL_SUFFIX):
                models.append(f[:-len(MODEL_SUFFIX)])
        return sorted(models)

    def delete_model(self, model_name):
        kp = os.path.join(self.model_dir, f"{model_name}{MODEL_SUFFIX}")
        cp = os.path.join(self.model_dir, f"{model_name}_config.json")
        deleted = []
        if os.path.exists(kp):
            import shutil
            if os.path.isdir(kp):
                shutil.rmtree(kp)
            else:
                os.remove(kp)
            deleted.append(kp)
        if os.path.exists(cp):
            os.remove(cp)
            deleted.append(cp)
        return deleted

    # ---------------- 辅助 ----------------
    def count_params(self):
        """返回总参数量（仅用于日志）。"""
        if self.model is None:
            return 0
        return int(sum(np.prod(w.shape) for w in self.model.trainable_weights))

    @staticmethod
    def _make_optimizer(name, lr):
        tf = _import_tf()
        name = (name or "Adam").lower()
        if name == "adam":
            return tf.keras.optimizers.Adam(learning_rate=lr)
        if name == "adamw":
            return tf.keras.optimizers.AdamW(learning_rate=lr)
        if name == "sgd":
            return tf.keras.optimizers.SGD(learning_rate=lr, momentum=0.9)
        return tf.keras.optimizers.Adam(learning_rate=lr)

    @staticmethod
    def _make_loss(name):
        tf = _import_tf()
        name = (name or "MSE").lower()
        if name == "mse":
            return tf.keras.losses.MeanSquaredError()
        if name == "mae":
            return tf.keras.losses.MeanAbsoluteError()
        if name == "huber":
            return tf.keras.losses.Huber()
        return tf.keras.losses.MeanSquaredError()
