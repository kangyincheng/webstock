"""TensorFlow 版的 A 股收盘价预测 GUI。

与 gui.py（PyTorch 版）几乎完全相同，仅替换：
  - trainer: StockTrainer -> TFStockTrainer（模型保存后缀 .keras 而非 .pth）
  - 模型参数统计：model.parameters() -> trainable_weights
  - 窗口标题前缀，便于区分 PyTorch 版

其它：数据参数 / 模型结构选项 / 训练参数 / 图表展示 / 进度条 / 日志
与 PyTorch 版保持完全一致，便于用户横向对比两种框架的训练效果。

注意：Linux 无显示器 (headless) 环境下 GUI 不可用，请使用 Web 接口。
"""
import os
import sys
import threading
import traceback
from datetime import datetime, timedelta

import numpy as np

from .data_loader import StockDataLoader
from .tf_trainer import TFStockTrainer

# ---- GUI 导入守卫：Linux 无显示器/无 tkinter 时优雅降级 ----
try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox, filedialog
    _TK_AVAILABLE = True
except ImportError:
    _TK_AVAILABLE = False

    class _Dummy:
        def __init__(self, *a, **kw): pass
        def __getattr__(self, _): return _Dummy()
        def __call__(self, *a, **kw): return _Dummy()
    tk = _Dummy()
    ttk = scrolledtext = messagebox = filedialog = _Dummy()

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.figure import Figure
    import matplotlib
    matplotlib.rcParams["font.sans-serif"] = [
        "Microsoft YaHei", "Microsoft YaHei UI",  # Windows
        "PingFang SC", "Heiti SC", "STHeiti",     # macOS
        "Noto Sans CJK SC", "Noto Sans CJK",      # Linux
        "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
        "Source Han Sans SC", "Source Han Sans CN",
        "SimHei", "SimSun",                       # Windows 兜底
        "Arial Unicode MS", "DejaVu Sans",        # 最终兜底
    ]
    matplotlib.rcParams["axes.unicode_minus"] = False
    _MPL_TK_AVAILABLE = True
except Exception:
    _MPL_TK_AVAILABLE = False
    from matplotlib.figure import Figure
    FigureCanvasTkAgg = NavigationToolbar2Tk = None


def _display_available() -> bool:
    """检测当前环境是否有图形显示器（Linux 无 DISPLAY 时返回 False）。"""
    if sys.platform == "win32":
        return True
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY"))


FRAMEWORK_TITLE = "(TensorFlow)"


class StockAppTF:
    """A 股收盘价预测系统（TensorFlow 版）。

    使用方式：
      1. 独立窗口：StockAppTF(root) —— root 为 tk.Tk()
      2. 嵌入组件：StockAppTF(parent, embedded=True)
    """

    def __init__(self, root, embedded=False):
        self.root = root
        if not embedded:
            try:
                self.root.title("mystock - A股收盘价预测系统 " + FRAMEWORK_TITLE)
                self.root.geometry("1400x900")
                self.root.minsize(1200, 800)
            except Exception:
                pass

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_loader = StockDataLoader(data_dir=os.path.join(base_dir, "data"))
        # 注意：PyTorch 版存 pth，TensorFlow 版存 keras，model_dir 相同不冲突
        self.trainer = TFStockTrainer(model_dir=os.path.join(base_dir, "models"))

        self._build_ui()
        self._refresh_model_list()

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=8)
        main_frame.pack(fill=tk.BOTH, expand=True)

        param_pane = ttk.Frame(main_frame, width=380)
        param_pane.pack(side=tk.LEFT, fill=tk.Y)
        param_pane.pack_propagate(False)

        result_pane = ttk.Frame(main_frame)
        result_pane.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._build_param_panel(param_pane)
        self._build_result_panel(result_pane)

    def _build_param_panel(self, parent):
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta // 120)), "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)

        row = 0

        ttk.Label(scroll_frame,
                  text=f"══════ 数据参数 {FRAMEWORK_TITLE} ══════",
                  font=("Arial", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1

        ttk.Label(scroll_frame, text="股票代码:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.stock_code_var = tk.StringVar(value="sh.600036")
        ttk.Entry(scroll_frame, textvariable=self.stock_code_var, width=20).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="起始日期:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.start_date_var = tk.StringVar(value="2018-01-01")
        ttk.Entry(scroll_frame, textvariable=self.start_date_var, width=20).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="结束日期:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.end_date_var = tk.StringVar(
            value=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))
        ttk.Entry(scroll_frame, textvariable=self.end_date_var, width=20).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="复权方式:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.adjustflag_var = tk.StringVar(value="2")
        adjust_combo = ttk.Combobox(scroll_frame, textvariable=self.adjustflag_var,
                                    values=["0-不复权", "1-前复权", "2-后复权"],
                                    state="readonly", width=18)
        adjust_combo.grid(row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="数据频率:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.frequency_var = tk.StringVar(value="d")
        freq_combo = ttk.Combobox(scroll_frame, textvariable=self.frequency_var,
                                  values=["d-日K", "w-周K", "m-月K",
                                          "5-5分钟", "15-15分钟", "30-30分钟", "60-60分钟"],
                                  state="readonly", width=18)
        freq_combo.grid(row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="特征列(逗号分隔):").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.feature_cols_var = tk.StringVar(value="open,high,low,close,volume,amount,turn")
        ttk.Entry(scroll_frame, textvariable=self.feature_cols_var, width=30).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="目标列:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.target_col_var = tk.StringVar(value="close")
        ttk.Entry(scroll_frame, textvariable=self.target_col_var, width=20).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="序列长度:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.seq_len_var = tk.IntVar(value=60)
        ttk.Spinbox(scroll_frame, from_=5, to=300, textvariable=self.seq_len_var, width=18).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="训练集比例:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.train_ratio_var = tk.DoubleVar(value=0.8)
        ttk.Spinbox(scroll_frame, from_=0.5, to=0.95, increment=0.05,
                     textvariable=self.train_ratio_var, width=18).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Button(scroll_frame, text="下载并预处理数据",
                   command=self._on_load_data).grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=2, pady=6)
        row += 1

        ttk.Label(scroll_frame, text="══════ 模型参数 ══════",
                  font=("Arial", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(8, 4))
        row += 1

        ttk.Label(scroll_frame, text="模型类型:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.model_type_var = tk.StringVar(value="LSTM")
        model_combo = ttk.Combobox(scroll_frame, textvariable=self.model_type_var,
                                   values=["LSTM", "GRU", "Transformer"],
                                   state="readonly", width=18)
        model_combo.grid(row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="隐藏层大小:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.hidden_size_var = tk.IntVar(value=128)
        ttk.Spinbox(scroll_frame, from_=16, to=512, increment=16,
                     textvariable=self.hidden_size_var, width=18).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="网络层数:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.num_layers_var = tk.IntVar(value=2)
        ttk.Spinbox(scroll_frame, from_=1, to=8,
                    textvariable=self.num_layers_var, width=18).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="Dropout:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.dropout_var = tk.DoubleVar(value=0.2)
        ttk.Spinbox(scroll_frame, from_=0.0, to=0.9, increment=0.05,
                     textvariable=self.dropout_var, width=18).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        self.bidirectional_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(scroll_frame, text="双向 (LSTM/GRU)",
                        variable=self.bidirectional_var).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="Transformer头数:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.nhead_var = tk.IntVar(value=4)
        ttk.Spinbox(scroll_frame, from_=1, to=16,
                    textvariable=self.nhead_var, width=18).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="前馈维度:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.dim_feedforward_var = tk.IntVar(value=256)
        ttk.Spinbox(scroll_frame, from_=64, to=2048, increment=64,
                     textvariable=self.dim_feedforward_var, width=18).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="══════ 训练参数 ══════",
                  font=("Arial", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(8, 4))
        row += 1

        ttk.Label(scroll_frame, text="训练轮数:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.epochs_var = tk.IntVar(value=100)
        ttk.Spinbox(scroll_frame, from_=1, to=5000,
                    textvariable=self.epochs_var, width=18).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="批次大小:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.batch_size_var = tk.IntVar(value=32)
        ttk.Spinbox(scroll_frame, from_=1, to=512,
                    textvariable=self.batch_size_var, width=18).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="学习率:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.learning_rate_var = tk.DoubleVar(value=0.001)
        ttk.Spinbox(scroll_frame, from_=0.00001, to=0.1, increment=0.0001,
                     textvariable=self.learning_rate_var,
                     width=18, format="%.6f").grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="优化器:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.optimizer_var = tk.StringVar(value="Adam")
        opt_combo = ttk.Combobox(scroll_frame, textvariable=self.optimizer_var,
                                  values=["Adam", "SGD", "AdamW"],
                                  state="readonly", width=18)
        opt_combo.grid(row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="损失函数:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.loss_type_var = tk.StringVar(value="MSE")
        loss_combo = ttk.Combobox(scroll_frame, textvariable=self.loss_type_var,
                                   values=["MSE", "MAE", "Huber"],
                                   state="readonly", width=18)
        loss_combo.grid(row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="早停耐心:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.early_stopping_var = tk.IntVar(value=15)
        ttk.Spinbox(scroll_frame, from_=0, to=100,
                    textvariable=self.early_stopping_var, width=18).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Button(scroll_frame, text="开始训练", command=self._on_train).grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=2, pady=6)
        row += 1

        ttk.Label(scroll_frame, text="══════ 模型管理 ══════",
                  font=("Arial", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(8, 4))
        row += 1

        ttk.Label(scroll_frame, text="模型名称:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.model_name_var = tk.StringVar(value="stock_model_tf")
        ttk.Entry(scroll_frame, textvariable=self.model_name_var, width=20).grid(
            row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        ttk.Label(scroll_frame, text="已有模型(.keras):").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.model_list_var = tk.StringVar()
        self.model_combo = ttk.Combobox(scroll_frame, textvariable=self.model_list_var,
                                       state="readonly", width=18)
        self.model_combo.grid(row=row, column=1, sticky="w", padx=2, pady=2)
        row += 1

        btn_frame = ttk.Frame(scroll_frame)
        btn_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(btn_frame, text="保存模型",
                   command=self._on_save_model).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(btn_frame, text="加载模型",
                   command=self._on_load_model).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        ttk.Button(btn_frame, text="删除模型",
                   command=self._on_delete_model).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        row += 1

        ttk.Button(scroll_frame, text="预测并绘图", command=self._on_predict).grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=2, pady=6)
        row += 1

        ttk.Button(scroll_frame, text="刷新模型列表",
                   command=self._refresh_model_list).grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=2, pady=2)
        row += 1

    def _build_result_panel(self, parent):
        top_frame = ttk.Frame(parent)
        top_frame.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(top_frame, text="运行进度:",
                  font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            top_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.progress_label = ttk.Label(top_frame, text="0%")
        self.progress_label.pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(parent, text="日志输出", padding=4)
        log_frame.pack(fill=tk.X, pady=(0, 4))

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=8, wrap=tk.WORD, font=("Consolas", 9))
        self.log_text.pack(fill=tk.X)

        chart_frame = ttk.LabelFrame(parent, text="图表展示", padding=4)
        chart_frame.pack(fill=tk.BOTH, expand=True)

        self.fig = Figure(figsize=(10, 6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        toolbar = NavigationToolbar2Tk(self.canvas, chart_frame)
        toolbar.update()
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)

        self._draw_empty_chart()

    def _draw_empty_chart(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.text(0.5, 0.5, "请先下载数据并训练模型", ha="center", va="center",
                fontsize=14, color="gray", transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
        self.canvas.draw()

    def _log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def _set_progress(self, value, text=None):
        self.progress_var.set(value)
        if text:
            self.progress_label.config(text=text)
        else:
            self.progress_label.config(text=f"{value:.1f}%")
        self.root.update_idletasks()

    def _get_params(self):
        feature_cols = [c.strip() for c in self.feature_cols_var.get().split(",") if c.strip()]
        params = {
            "stock_code": self.stock_code_var.get().strip(),
            "start_date": self.start_date_var.get().strip(),
            "end_date": self.end_date_var.get().strip(),
            "adjustflag": self.adjustflag_var.get().strip().split("-")[0],
            "frequency": self.frequency_var.get().strip().split("-")[0],
            "feature_cols": feature_cols,
            "target_col": self.target_col_var.get().strip(),
            "seq_len": self.seq_len_var.get(),
            "train_ratio": self.train_ratio_var.get(),
            "model_type": self.model_type_var.get().strip(),
            "hidden_size": self.hidden_size_var.get(),
            "num_layers": self.num_layers_var.get(),
            "dropout": self.dropout_var.get(),
            "bidirectional": self.bidirectional_var.get(),
            "nhead": self.nhead_var.get(),
            "d_model": self.hidden_size_var.get(),
            "dim_feedforward": self.dim_feedforward_var.get(),
            "epochs": self.epochs_var.get(),
            "batch_size": self.batch_size_var.get(),
            "learning_rate": self.learning_rate_var.get(),
            "optimizer_type": self.optimizer_var.get().strip(),
            "loss_type": self.loss_type_var.get().strip(),
            "early_stopping_patience": self.early_stopping_var.get(),
        }
        return params

    def _on_model_type_change(self):
        pass

    def _on_load_data(self):
        params = self._get_params()
        threading.Thread(target=self._load_data_thread, args=(params,), daemon=True).start()

    def _load_data_thread(self, params):
        try:
            self._log("开始加载数据...")
            self._set_progress(5, "下载中...")

            def progress_cb(msg):
                self._log(msg)

            self.data_loader.fetch_data(
                stock_code=params["stock_code"],
                start_date=params["start_date"],
                end_date=params["end_date"],
                frequency=params["frequency"],
                adjustflag=params["adjustflag"],
                progress_callback=progress_cb,
            )

            self._set_progress(50, "预处理中...")
            self.data_loader.preprocess(
                feature_cols=params["feature_cols"],
                seq_len=params["seq_len"],
                train_ratio=params["train_ratio"],
                target_col=params["target_col"],
                progress_callback=progress_cb,
            )

            self._set_progress(100, "完成")
            self._log("数据加载完成！")
            self._plot_data_overview()
        except Exception as e:
            self._log(f"错误: {e}")
            traceback.print_exc()
            messagebox.showerror("错误", str(e))

    def _plot_data_overview(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        dates = self.data_loader.get_dates()
        close_prices = self.data_loader.df["close"].values
        seq_len = self.seq_len_var.get()
        train_ratio = self.train_ratio_var.get()
        train_size = int((len(dates) - seq_len) * train_ratio) + seq_len

        ax.plot(dates[:train_size], close_prices[:train_size],
                label="训练集", color="blue", linewidth=0.8)
        ax.plot(dates[train_size:], close_prices[train_size:],
                label="测试集", color="orange", linewidth=0.8)
        ax.set_title(f"{self.stock_code_var.get()} 收盘价走势 {FRAMEWORK_TITLE}")
        ax.set_xlabel("日期")
        ax.set_ylabel("价格")
        ax.legend()
        ax.grid(True, alpha=0.3)

        n = len(dates)
        step = max(1, n // 10)
        ax.set_xticks(dates[::step])
        ax.set_xticklabels(dates[::step], rotation=45, ha="right")

        self.fig.tight_layout()
        self.canvas.draw()

    def _on_train(self):
        if self.data_loader.X_train is None:
            messagebox.showwarning("提示", "请先下载并预处理数据")
            return
        params = self._get_params()
        threading.Thread(target=self._train_thread, args=(params,), daemon=True).start()

    def _train_thread(self, params):
        try:
            self._log("开始构建模型...")
            self._set_progress(0, "初始化...")

            params["input_size"] = len(self.data_loader.feature_cols)
            self.trainer.build_model(params)
            self._log(f"模型类型: {params['model_type']} {FRAMEWORK_TITLE}, "
                      f"参数数: {self.trainer.count_params()}")

            def epoch_cb(epoch, total_epochs, train_loss, val_loss):
                pct = (epoch / total_epochs) * 100
                self._set_progress(pct, f"Epoch {epoch}/{total_epochs}")
                if epoch % max(1, total_epochs // 20) == 0 or epoch == total_epochs:
                    self._log(
                        f"Epoch {epoch}/{total_epochs} - "
                        f"train_loss: {train_loss:.6f}, val_loss: {val_loss:.6f}")

            def progress_cb(msg):
                self._log(msg)

            self.trainer.train(
                X_train=self.data_loader.X_train,
                y_train=self.data_loader.y_train,
                X_val=self.data_loader.X_test,
                y_val=self.data_loader.y_test,
                epochs=params["epochs"],
                batch_size=params["batch_size"],
                learning_rate=params["learning_rate"],
                optimizer_type=params["optimizer_type"],
                loss_type=params["loss_type"],
                early_stopping_patience=params["early_stopping_patience"],
                progress_callback=progress_cb,
                epoch_callback=epoch_cb,
            )

            self._set_progress(100, "训练完成")
            self._log("训练完成！")
            self._plot_training_result()
        except Exception as e:
            self._log(f"训练错误: {e}")
            traceback.print_exc()
            messagebox.showerror("错误", str(e))

    def _plot_training_result(self):
        self.fig.clear()

        ax1 = self.fig.add_subplot(211)
        ax1.plot(self.trainer.train_losses, label="训练损失", color="blue", linewidth=1)
        if self.trainer.val_losses:
            ax1.plot(self.trainer.val_losses, label="验证损失", color="red", linewidth=1)
        ax1.set_title("训练损失曲线 " + FRAMEWORK_TITLE)
        ax1.set_ylabel("Loss")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        ax2 = self.fig.add_subplot(212)
        test_pred = self.trainer.predict(self.data_loader.X_test)
        test_pred_actual = self.data_loader.inverse_transform_close(test_pred)
        y_test_actual = self.data_loader.inverse_transform_close(self.data_loader.y_test)
        test_dates = self.data_loader.get_test_dates(
            seq_len=self.seq_len_var.get(),
            train_ratio=self.train_ratio_var.get())

        ax2.plot(test_dates, y_test_actual, label="实际值", color="blue", linewidth=1)
        ax2.plot(test_dates, test_pred_actual,
                 label="预测值", color="red", linewidth=1, linestyle="--")
        ax2.set_title("测试集预测 vs 实际 " + FRAMEWORK_TITLE)
        ax2.set_xlabel("日期")
        ax2.set_ylabel("价格")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        n = len(test_dates)
        step = max(1, n // 10)
        ax2.set_xticks(test_dates[::step])
        ax2.set_xticklabels(test_dates[::step], rotation=45, ha="right")

        mse = np.mean((test_pred_actual - y_test_actual) ** 2)
        mae = np.mean(np.abs(test_pred_actual - y_test_actual))
        self._log(f"测试集 MSE: {mse:.4f}, MAE: {mae:.4f}")

        self.fig.tight_layout()
        self.canvas.draw()

    def _on_predict(self):
        if self.trainer.model is None:
            messagebox.showwarning("提示", "请先训练或加载模型")
            return
        if self.data_loader.X_test is None:
            messagebox.showwarning("提示", "请先下载并预处理数据")
            return
        threading.Thread(target=self._predict_thread, daemon=True).start()

    def _predict_thread(self):
        try:
            self._log("开始预测...")
            self._set_progress(30, "预测中...")

            train_pred = self.trainer.predict(self.data_loader.X_train)
            test_pred = self.trainer.predict(self.data_loader.X_test)

            train_pred_actual = self.data_loader.inverse_transform_close(train_pred)
            test_pred_actual = self.data_loader.inverse_transform_close(test_pred)
            y_train_actual = self.data_loader.inverse_transform_close(self.data_loader.y_train)
            y_test_actual = self.data_loader.inverse_transform_close(self.data_loader.y_test)

            self._set_progress(70, "绘图中...")
            self._plot_full_prediction(train_pred_actual, test_pred_actual,
                                        y_train_actual, y_test_actual)

            mse = np.mean((test_pred_actual - y_test_actual) ** 2)
            mae = np.mean(np.abs(test_pred_actual - y_test_actual))
            rmse = np.sqrt(mse)
            mape = np.mean(np.abs(
                (test_pred_actual - y_test_actual) / y_test_actual)) * 100

            self._log(f"预测完成！ {FRAMEWORK_TITLE}")
            self._log(f"测试集 MSE:  {mse:.4f}")
            self._log(f"测试集 RMSE: {rmse:.4f}")
            self._log(f"测试集 MAE:  {mae:.4f}")
            self._log(f"测试集 MAPE: {mape:.2f}%")

            last_actual = float(np.array(y_test_actual).flatten()[-1])
            last_pred = float(np.array(test_pred_actual).flatten()[-1])
            self._log(f"最后一日实际收盘价: {last_actual:.2f}, 预测: {last_pred:.2f}")

            self._set_progress(100, "完成")
        except Exception as e:
            self._log(f"预测错误: {e}")
            traceback.print_exc()
            messagebox.showerror("错误", str(e))

    def _plot_full_prediction(self, train_pred, test_pred, y_train, y_test):
        self.fig.clear()
        ax = self.fig.add_subplot(111)

        all_dates = self.data_loader.get_dates()
        seq_len = self.seq_len_var.get()

        train_dates = all_dates[seq_len:seq_len + len(y_train)]
        test_dates = all_dates[seq_len + len(y_train):seq_len + len(y_train) + len(y_test)]

        ax.plot(all_dates, self.data_loader.df["close"].values,
                label="原始数据", color="gray", alpha=0.5, linewidth=0.8)
        ax.plot(train_dates, train_pred.flatten(),
                label="训练集预测", color="blue", linewidth=1)
        ax.plot(test_dates, test_pred.flatten(),
                label="测试集预测", color="red", linewidth=1)

        ax.axvline(x=train_dates[-1], color="green",
                   linestyle="--", alpha=0.7, label="训练/测试分界")

        ax.set_title(f"{self.stock_code_var.get()} 收盘价预测结果 {FRAMEWORK_TITLE}")
        ax.set_xlabel("日期")
        ax.set_ylabel("价格")
        ax.legend()
        ax.grid(True, alpha=0.3)

        n = len(all_dates)
        step = max(1, n // 15)
        ax.set_xticks(all_dates[::step])
        ax.set_xticklabels(all_dates[::step], rotation=45, ha="right")

        self.fig.tight_layout()
        self.canvas.draw()

    def _on_save_model(self):
        if self.trainer.model is None:
            messagebox.showwarning("提示", "没有可保存的模型，请先训练模型")
            return
        model_name = self.model_name_var.get().strip()
        if not model_name:
            messagebox.showwarning("提示", "请输入模型名称")
            return
        try:
            extra = {
                "stock_code": self.stock_code_var.get(),
                "seq_len": self.seq_len_var.get(),
                "target_col": self.target_col_var.get(),
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            path = self.trainer.save_model(model_name,
                                           data_loader=self.data_loader,
                                           extra_info=extra)
            self._log(f"模型已保存到: {path}")
            messagebox.showinfo("成功", f"模型保存成功：\n{path}")
            self._refresh_model_list()
        except Exception as e:
            self._log(f"保存错误: {e}")
            messagebox.showerror("错误", str(e))

    def _on_load_model(self):
        model_name = self.model_list_var.get().strip()
        if not model_name:
            messagebox.showwarning("提示", "请选择要加载的模型")
            return
        try:
            self.trainer.load_model(model_name, data_loader=self.data_loader)
            self._log(f"模型 {model_name} 加载成功！ {FRAMEWORK_TITLE}")
            self._log(f"模型类型: {self.trainer.model_type}")
            total_params = self.trainer.count_params()
            self._log(f"参数数量: {total_params}")
            if self.trainer.train_losses:
                self._log(f"历史训练轮数: {len(self.trainer.train_losses)}")
            messagebox.showinfo("成功", f"模型 {model_name} 加载成功")
        except Exception as e:
            self._log(f"加载错误: {e}")
            traceback.print_exc()
            messagebox.showerror("错误", str(e))

    def _on_delete_model(self):
        model_name = self.model_list_var.get().strip()
        if not model_name:
            messagebox.showwarning("提示", "请选择要删除的模型")
            return
        if not messagebox.askyesno("确认",
                                   f"确定要删除 TensorFlow 模型 {model_name} 吗？"):
            return
        try:
            deleted = self.trainer.delete_model(model_name)
            self._log(f"已删除模型 {model_name}: {deleted}")
            self._refresh_model_list()
        except Exception as e:
            self._log(f"删除错误: {e}")
            messagebox.showerror("错误", str(e))

    def _refresh_model_list(self):
        try:
            models = self.trainer.list_models()
            self.model_combo["values"] = models
            if models:
                self.model_combo.current(0)
            else:
                self.model_list_var.set("")
        except Exception as e:
            print(f"刷新模型列表失败: {e}")


def main():
    if not _TK_AVAILABLE:
        print("=" * 60)
        print("当前环境未安装 tkinter，无法启动桌面 GUI。")
        print("Linux 服务器请使用 Web 接口：")
        print("  1. 启动后端: cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000")
        print("  2. 浏览器访问: http://localhost  或  http://www.jeoj.com")
        print("  3. 或安装 tkinter: sudo dnf install -y python3-tkinter tkinter")
        print("=" * 60)
        return
    if not _display_available():
        print("=" * 60)
        print("当前为无图形界面 (headless) 环境，无法启动桌面 GUI。")
        print("Linux 服务器请使用 Web 接口：")
        print("  启动后端: cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000")
        print("  浏览器访问: http://localhost  或  http://www.jeoj.com")
        print("  如需远程桌面 GUI，请配置 X11 转发或 VNC。")
        print("=" * 60)
        return
    from .main_window import MainWindow
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    app = MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
