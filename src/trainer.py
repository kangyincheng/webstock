import os
import json
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from .model import build_model


class StockTrainer:
    def __init__(self, model_dir="models", device=None):
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)
        self.model = None
        self.model_type = None
        self.model_config = {}
        self.train_losses = []
        self.val_losses = []

    def _get_model_config(self, params):
        config = {
            "model_type": params.get("model_type", "LSTM"),
            "input_size": params.get("input_size", 7),
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
        config = self._get_model_config(params)
        self.model_type = config["model_type"]
        self.model_config = config
        self.model = build_model(
            config["model_type"],
            config["input_size"],
            **config,
        ).to(self.device)
        return self.model

    def train(self, X_train, y_train, X_val=None, y_val=None, epochs=100,
              batch_size=32, learning_rate=0.001, optimizer_type="Adam",
              loss_type="MSE", early_stopping_patience=15,
              progress_callback=None, epoch_callback=None):
        if self.model is None:
            raise ValueError("模型未构建，请先调用 build_model")

        train_dataset = TensorDataset(
            torch.from_numpy(X_train).float(),
            torch.from_numpy(y_train).float(),
        )
        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)

        if X_val is not None and y_val is not None:
            val_dataset = TensorDataset(
                torch.from_numpy(X_val).float(),
                torch.from_numpy(y_val).float(),
            )
            val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
        else:
            val_loader = None

        if optimizer_type == "Adam":
            optimizer = torch.optim.Adam(self.model.parameters(), lr=learning_rate)
        elif optimizer_type == "SGD":
            optimizer = torch.optim.SGD(self.model.parameters(), lr=learning_rate, momentum=0.9)
        elif optimizer_type == "AdamW":
            optimizer = torch.optim.AdamW(self.model.parameters(), lr=learning_rate)
        else:
            optimizer = torch.optim.Adam(self.model.parameters(), lr=learning_rate)

        if loss_type == "MSE":
            criterion = nn.MSELoss()
        elif loss_type == "MAE":
            criterion = nn.L1Loss()
        elif loss_type == "Huber":
            criterion = nn.SmoothL1Loss()
        else:
            criterion = nn.MSELoss()

        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=5, verbose=False
        )

        self.train_losses = []
        self.val_losses = []
        best_val_loss = float("inf")
        patience_counter = 0
        best_state = None

        if progress_callback:
            progress_callback(f"开始训练 - 设备: {self.device}, 总轮数: {epochs}")

        for epoch in range(epochs):
            self.model.train()
            total_loss = 0.0
            num_batches = 0

            for batch_X, batch_y in train_loader:
                batch_X = batch_X.to(self.device)
                batch_y = batch_y.to(self.device)

                optimizer.zero_grad()
                outputs = self.model(batch_X)
                loss = criterion(outputs, batch_y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
                optimizer.step()

                total_loss += loss.item()
                num_batches += 1

            avg_train_loss = total_loss / max(num_batches, 1)
            self.train_losses.append(avg_train_loss)

            avg_val_loss = avg_train_loss
            if val_loader is not None:
                self.model.eval()
                val_loss = 0.0
                val_batches = 0
                with torch.no_grad():
                    for batch_X, batch_y in val_loader:
                        batch_X = batch_X.to(self.device)
                        batch_y = batch_y.to(self.device)
                        outputs = self.model(batch_X)
                        loss = criterion(outputs, batch_y)
                        val_loss += loss.item()
                        val_batches += 1
                avg_val_loss = val_loss / max(val_batches, 1)
                self.val_losses.append(avg_val_loss)
                scheduler.step(avg_val_loss)
            else:
                scheduler.step(avg_train_loss)

            if avg_val_loss < best_val_loss:
                best_val_loss = avg_val_loss
                patience_counter = 0
                best_state = {k: v.clone() for k, v in self.model.state_dict().items()}
            else:
                patience_counter += 1

            if epoch_callback:
                epoch_callback(epoch + 1, epochs, avg_train_loss, avg_val_loss)

            if patience_counter >= early_stopping_patience:
                if progress_callback:
                    progress_callback(
                        f"早停触发 - epoch {epoch+1}/{epochs}, 最佳验证损失: {best_val_loss:.6f}"
                    )
                break

        if best_state is not None:
            self.model.load_state_dict(best_state)

        if progress_callback:
            progress_callback(f"训练完成 - 最终训练损失: {self.train_losses[-1]:.6f}")
            if self.val_losses:
                progress_callback(f"最佳验证损失: {best_val_loss:.6f}")

        return self.train_losses, self.val_losses

    def predict(self, X):
        if self.model is None:
            raise ValueError("模型未构建或加载")
        self.model.eval()
        X_tensor = torch.from_numpy(X).float().to(self.device)
        with torch.no_grad():
            predictions = self.model(X_tensor)
        return predictions.cpu().numpy()

    def save_model(self, model_name, data_loader=None, extra_info=None):
        save_path = os.path.join(self.model_dir, f"{model_name}.pth")
        config_path = os.path.join(self.model_dir, f"{model_name}_config.json")

        save_dict = {
            "model_state_dict": self.model.state_dict(),
            "model_type": self.model_type,
            "model_config": self.model_config,
            "train_losses": self.train_losses,
            "val_losses": self.val_losses,
        }

        torch.save(save_dict, save_path)

        config = {
            "model_type": self.model_type,
            "model_config": self.model_config,
            "device": str(self.device),
            "train_losses": self.train_losses,
            "val_losses": self.val_losses,
        }

        if data_loader is not None:
            config["feature_cols"] = data_loader.feature_cols
            config["scaler_min"] = data_loader.scaler.min_.tolist()
            config["scaler_scale"] = data_loader.scaler.scale_.tolist()
            config["scaler_data_min"] = data_loader.scaler.data_min_.tolist()
            config["scaler_data_max"] = data_loader.scaler.data_max_.tolist()

        if extra_info:
            config.update(extra_info)

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        return save_path

    def load_model(self, model_name, data_loader=None):
        save_path = os.path.join(self.model_dir, f"{model_name}.pth")
        config_path = os.path.join(self.model_dir, f"{model_name}_config.json")

        if not os.path.exists(save_path):
            raise FileNotFoundError(f"模型文件不存在: {save_path}")

        checkpoint = torch.load(save_path, map_location=self.device, weights_only=False)
        self.model_type = checkpoint["model_type"]
        self.model_config = checkpoint["model_config"]
        self.train_losses = checkpoint.get("train_losses", [])
        self.val_losses = checkpoint.get("val_losses", [])

        self.model = build_model(
            self.model_type,
            self.model_config["input_size"],
            **self.model_config,
        ).to(self.device)
        self.model.load_state_dict(checkpoint["model_state_dict"])

        if data_loader is not None and os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if "scaler_min" in config and "scaler_scale" in config:
                from sklearn.preprocessing import MinMaxScaler
                n_features = len(config["scaler_min"])
                data_loader.scaler = MinMaxScaler(feature_range=(0, 1))
                data_loader.scaler.min_ = np.array(config["scaler_min"])
                data_loader.scaler.scale_ = np.array(config["scaler_scale"])
                data_loader.scaler.data_min_ = np.array(config.get("scaler_data_min", np.zeros(n_features)))
                data_loader.scaler.data_max_ = np.array(config.get("scaler_data_max", np.ones(n_features)))
                data_loader.scaler.n_features_in_ = n_features
                data_loader.feature_cols = config.get("feature_cols", [])

        return self.model

    def list_models(self):
        models = []
        if not os.path.exists(self.model_dir):
            return models
        for f in os.listdir(self.model_dir):
            if f.endswith(".pth"):
                models.append(f.replace(".pth", ""))
        return sorted(models)

    def delete_model(self, model_name):
        pth_path = os.path.join(self.model_dir, f"{model_name}.pth")
        cfg_path = os.path.join(self.model_dir, f"{model_name}_config.json")
        deleted = []
        if os.path.exists(pth_path):
            os.remove(pth_path)
            deleted.append(pth_path)
        if os.path.exists(cfg_path):
            os.remove(cfg_path)
            deleted.append(cfg_path)
        return deleted
