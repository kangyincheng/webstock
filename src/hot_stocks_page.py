"""热门股票页面。

布局：
  ┌──────────────────────────────────────────────────┐
  │ 标题：热门股票                                    │
  ├──────────────────────────────────────────────────┤
  │ 参数栏：[交易日____] [排序方式▾] [TOP N____]       │
  │         [加载] [刷新缓存]                          │
  ├──────────────────────────────────────────────────┤
  │ 进度日志                                          │
  ├──────────────────────────────────────────────────┤
  │ 筛选栏：[代码/名称____] [筛选] [重置]              │
  ├──────────────────────────────────────────────────┤
  │ 热门股票表格（点击列头可重排）：                    │
  │  名称 / 代码 / 行业 / 收盘价 / 涨跌幅(%) /         │
  │  成交额(万元) / 成交量(手)                         │
  └──────────────────────────────────────────────────┘

数据源：tushare pro.daily + pro.stock_basic
排序方式：涨幅 / 成交额 / 成交量 三选一
"""
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext, messagebox

import pandas as pd

from .market_data import TushareClient


# Treeview 列定义
TREE_COLUMNS = [
    ("rank",    "排名",       60,  tk.CENTER, False),
    ("name",    "股票名称",   100, tk.W,      False),
    ("code",    "代码",       100, tk.CENTER, False),
    ("industry","行业",       100, tk.W,      False),
    ("close",   "收盘价",      80, tk.E,      True),
    ("pct_chg", "涨跌幅(%)",  110, tk.E,      True),
    ("amount",  "成交额(万元)", 130, tk.E,     True),
    ("vol",     "成交量(手)",   110, tk.E,    True),
]
NUMERIC_COLS = {"close", "pct_chg", "amount", "vol"}


class HotStocksPage:
    """热门股票页面。"""

    SORT_OPTIONS = [
        ("pct_chg", "按涨幅"),
        ("amount",  "按成交额"),
        ("vol",     "按成交量"),
    ]

    def __init__(self, parent):
        self.parent = parent
        self.client = TushareClient(data_dir=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

        self.trade_date_var = tk.StringVar(value="")
        self.sort_var = tk.StringVar(value="pct_chg")
        self.top_n_var = tk.IntVar(value=50)
        self.filter_var = tk.StringVar(value="")

        self._result_df = None   # 全量（按 TOP N 截取后的全市场）
        self._display_df = None  # 当前展示（含筛选/排序后）
        self._loading = False
        self._last_sort_col = "pct_chg"
        self._last_sort_order = "desc"

        self._build_ui()
        self._log("准备就绪。点击「加载」拉取最近交易日热门股票。")

    # ---------------- 布局 ----------------
    def _build_ui(self):
        tk.Label(
            self.parent, text="热门股票",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#F5F6F7", fg="#1F2329", anchor="w"
        ).pack(fill=tk.X, padx=16, pady=(12, 4))
        tk.Label(
            self.parent,
            text="按涨幅 / 成交额 / 成交量排序，取 TOP N 热门股票",
            font=("Microsoft YaHei UI", 10),
            bg="#F5F6F7", fg="#86909C", anchor="w"
        ).pack(fill=tk.X, padx=16, pady=(0, 8))

        # 参数栏
        param_card = tk.Frame(self.parent, bg="#FFFFFF",
                               highlightbackground="#E5E6EB", highlightthickness=1)
        param_card.pack(fill=tk.X, padx=16, pady=4)
        row = tk.Frame(param_card, bg="#FFFFFF")
        row.pack(fill=tk.X, padx=16, pady=10)

        tk.Label(row, text="交易日(YYYYMMDD,留空=最近)", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 6))
        tk.Entry(row, textvariable=self.trade_date_var, width=12,
                 font=("Microsoft YaHei UI", 10),
                 bg="#FAFBFC", relief="flat",
                 highlightbackground="#C8CCD2", highlightthickness=1
                 ).pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(row, text="排序方式", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 4))
        sort_menu = ttk.Combobox(
            row, textvariable=self.sort_var, width=10, state="readonly",
            values=[v for v, _ in self.SORT_OPTIONS])
        sort_menu.pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(row, text="TOP N", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 4))
        tk.Entry(row, textvariable=self.top_n_var, width=6,
                 font=("Microsoft YaHei UI", 10),
                 bg="#FAFBFC", relief="flat",
                 highlightbackground="#C8CCD2", highlightthickness=1
                 ).pack(side=tk.LEFT, padx=(0, 12))

        self.btn_load = tk.Button(
            row, text="加载", command=self._on_load,
            bg="#1677FF", fg="white", relief="flat",
            activebackground="#4096FF", activeforeground="white",
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=14, pady=2, cursor="hand2")
        self.btn_load.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_refresh = tk.Button(
            row, text="刷新缓存", command=self._on_refresh,
            bg="#FFFFFF", fg="#1677FF", relief="flat",
            font=("Microsoft YaHei UI", 10),
            padx=12, pady=2, cursor="hand2",
            highlightbackground="#1677FF", highlightthickness=1)
        self.btn_refresh.pack(side=tk.LEFT, padx=(0, 8))

        self.status_hint = tk.Label(
            row, text="", bg="#FFFFFF",
            font=("Microsoft YaHei UI", 9), fg="#86909C")
        self.status_hint.pack(side=tk.LEFT, padx=12)

        # 进度日志
        log_card = tk.Frame(self.parent, bg="#FFFFFF",
                            highlightbackground="#E5E6EB", highlightthickness=1)
        log_card.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(log_card, text="进度日志", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#4E5969").pack(anchor="w", padx=12, pady=(8, 2))
        self.log_text = scrolledtext.ScrolledText(
            log_card, height=5, font=("Consolas", 9),
            bg="#FAFBFC", fg="#1F2329", relief="flat",
            wrap=tk.WORD, state="disabled")
        self.log_text.pack(fill=tk.X, padx=12, pady=(0, 8))

        # 筛选栏
        self._build_filter_card()
        # 表格
        self._build_table_card()

    def _build_filter_card(self):
        filter_card = tk.Frame(self.parent, bg="#FFFFFF",
                               highlightbackground="#E5E6EB", highlightthickness=1)
        filter_card.pack(fill=tk.X, padx=16, pady=4)
        row = tk.Frame(filter_card, bg="#FFFFFF")
        row.pack(fill=tk.X, padx=16, pady=8)
        tk.Label(row, text="筛选（代码/名称/行业）：", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10),
                 fg="#4E5969").pack(side=tk.LEFT, padx=(0, 6))
        entry = tk.Entry(row, textvariable=self.filter_var, width=30,
                         font=("Microsoft YaHei UI", 10),
                         bg="#FAFBFC", relief="flat",
                         highlightbackground="#C8CCD2", highlightthickness=1)
        entry.pack(side=tk.LEFT, padx=(0, 8))
        entry.bind("<Return>", lambda e: self._on_filter())
        tk.Button(row, text="筛选", command=self._on_filter,
                  bg="#1677FF", fg="white", relief="flat",
                  font=("Microsoft YaHei UI", 10),
                  padx=12, pady=1, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(row, text="重置", command=self._on_reset_filter,
                  bg="#FFFFFF", fg="#4E5969", relief="flat",
                  font=("Microsoft YaHei UI", 10),
                  padx=12, pady=1, cursor="hand2",
                  highlightbackground="#C8CCD2", highlightthickness=1).pack(side=tk.LEFT)
        self.filter_hint = tk.Label(row, text="", bg="#FFFFFF",
                                   font=("Microsoft YaHei UI", 9), fg="#86909C")
        self.filter_hint.pack(side=tk.LEFT, padx=12)

    def _build_table_card(self):
        table_card = tk.Frame(self.parent, bg="#FFFFFF",
                              highlightbackground="#E5E6EB", highlightthickness=1)
        table_card.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 16))
        tk.Label(table_card, text="热门股票榜（点击列头排序）", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#4E5969").pack(anchor="w", padx=12, pady=(8, 2))
        container = tk.Frame(table_card, bg="#FFFFFF")
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        ysb = ttk.Scrollbar(container, orient="vertical")
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb = ttk.Scrollbar(container, orient="horizontal")
        xsb.pack(side=tk.BOTTOM, fill=tk.X)

        style = ttk.Style()
        style.configure("Treeview.Heading",
                        font=("Microsoft YaHei UI", 10, "bold"),
                        background="#F2F3F5", foreground="#1F2329")
        style.configure("Treeview",
                        font=("Microsoft YaHei UI", 10),
                        rowheight=28)

        columns = tuple(k for k, *_ in TREE_COLUMNS)
        self.tree = ttk.Treeview(
            container, columns=columns, show="headings",
            yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        for col_key, label, width, anchor, _ in TREE_COLUMNS:
            cmd = (lambda k=col_key: self._on_header_click(k))
            self.tree.heading(col_key, text=label, command=cmd)
            self.tree.column(col_key, width=width, anchor=anchor)
        self.tree.tag_configure("up", background="#FFF7E6")
        self.tree.tag_configure("down", background="#FFF1F0")
        self.tree.tag_configure("limit_up", background="#FFF1F0", foreground="#CF1322")

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.config(command=self.tree.yview)
        xsb.config(command=self.tree.xview)

    # ---------------- 日志 ----------------
    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        try:
            self.parent.update_idletasks()
        except Exception:
            pass

    # ---------------- 加载 ----------------
    def _on_load(self):
        if self._loading:
            messagebox.showinfo("提示", "加载中，请稍候")
            return
        if not self.client.is_configured():
            messagebox.showerror(
                "未配置 Tushare token",
                "请在项目根目录创建 tushare_token.txt 文件，把 token 写入第一行。\n"
                "（该文件已被 .gitignore 排除，不会被提交到 git）")
            return
        td = self.trade_date_var.get().strip()
        if td and (not td.isdigit() or len(td) != 8):
            messagebox.showerror("日期格式错误", "交易日应为 YYYYMMDD 8 位数字")
            return
        try:
            top_n = int(self.top_n_var.get())
            if top_n <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("参数错误", "TOP N 必须为正整数")
            return

        self._loading = True
        self.btn_load.config(text="加载中...", state="disabled")
        sort_by = self.sort_var.get()
        t = threading.Thread(target=self._load_thread, args=(td, top_n, sort_by), daemon=True)
        t.start()

    def _on_refresh(self):
        td = self.trade_date_var.get().strip()
        deleted = 0
        if td:
            p = os.path.join(self.client.data_dir, f"daily_{td}.csv")
            if os.path.exists(p):
                os.remove(p); deleted += 1
        else:
            for fn in os.listdir(self.client.data_dir):
                if fn.startswith("daily_") and fn.endswith(".csv"):
                    os.remove(os.path.join(self.client.data_dir, fn)); deleted += 1
        sb = os.path.join(self.client.data_dir, "stock_basic.csv")
        if os.path.exists(sb):
            os.remove(sb); deleted += 1
        self._log(f"已清除 {deleted} 个缓存文件")
        if deleted:
            messagebox.showinfo("刷新缓存", f"已清除 {deleted} 个缓存文件，请重新加载")

    def _load_thread(self, td, top_n, sort_by):
        try:
            if td:
                self._log(f"拉取交易日 {td} 全市场行情...")
                daily = self.client.fetch_daily(trade_date=td)
            else:
                self._log("自动查找最近交易日...")
                daily = self.client.fetch_daily()
            if daily is None or daily.empty:
                self.parent.after(0, lambda: messagebox.showwarning("无数据", "未获取到行情数据"))
                return
            actual_td = str(daily["trade_date"].iloc[0]) if "trade_date" in daily.columns else td
            self._log(f"行情：{len(daily)} 条，交易日={actual_td}")
            self._log("拉取股票基本信息...")
            basic = self.client.fetch_stock_basic()
            if basic is None or basic.empty:
                self.parent.after(0, lambda: messagebox.showerror("错误", "拉取股票基本信息失败"))
                return
            df = daily.merge(basic[["ts_code", "name", "industry"]],
                             on="ts_code", how="left")
            df["industry"] = df["industry"].fillna("未分类").replace("", "未分类")
            for c in ["pct_chg", "amount", "vol", "close"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            # 成交额单位转换：千元 -> 万元
            df["amount"] = (df["amount"] / 10.0).round(2)
            # 按 sort_by 降序取 TOP N
            df = df.sort_values(by=sort_by, ascending=False,
                                kind="mergesort").head(top_n).reset_index(drop=True)
            self._result_df = df
            self._last_sort_col = sort_by
            self._last_sort_order = "desc"
            self.parent.after(0, lambda: self._apply_sort_and_render(actual_td))
        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: messagebox.showerror("错误", err))
            self._log(f"加载失败：{err}")
        finally:
            self.parent.after(0, self._load_done)

    def _load_done(self):
        self._loading = False
        self.btn_load.config(text="加载", state="normal")

    # ---------------- 排序 + 筛选 + 渲染 ----------------
    def _on_header_click(self, col_key):
        if self._result_df is None or self._result_df.empty:
            return
        if self._last_sort_col == col_key:
            self._last_sort_order = "desc" if self._last_sort_order == "asc" else "asc"
        else:
            self._last_sort_col = col_key
            self._last_sort_order = "desc" if col_key in NUMERIC_COLS else "asc"
        self._apply_sort_and_render()

    def _apply_sort_and_render(self, trade_date=None):
        if self._result_df is None or self._result_df.empty:
            return
        df = self._result_df.copy()
        # 筛选
        ft = self.filter_var.get().strip()
        if ft:
            mask = self._build_filter_mask(df, ft)
            df = df[mask]
            self.filter_hint.config(text=f"已筛选：显示 {len(df)} 条")
        else:
            self.filter_hint.config(text="")
        # 排序
        if self._last_sort_col:
            asc = (self._last_sort_order == "asc")
            df = df.sort_values(by=self._last_sort_col, ascending=asc,
                                kind="mergesort").reset_index(drop=True)
        self._display_df = df
        self._render(df, trade_date)

    @staticmethod
    def _build_filter_mask(df, text):
        text = text.strip()
        if not text:
            return pd.Series(True, index=df.index)
        m_code = df["ts_code"].astype(str).str.contains(text, case=False, na=False)
        m_name = df["name"].astype(str).str.contains(text, case=False, na=False)
        m_ind = df["industry"].astype(str).str.contains(text, case=False, na=False)
        m_digit6 = pd.Series(False, index=df.index)
        if text.isdigit() and len(text) == 6:
            m_digit6 = df["ts_code"].astype(str).str.contains(text, na=False)
        return m_code | m_name | m_ind | m_digit6

    def _on_filter(self):
        if self._result_df is None or self._result_df.empty:
            messagebox.showinfo("提示", "暂无数据，请先「加载」")
            return
        kw = self.filter_var.get().strip()
        self._log(f"应用筛选：{kw or '(空)'}")
        self._apply_sort_and_render()

    def _on_reset_filter(self):
        self.filter_var.set("")
        if self._result_df is not None:
            self._apply_sort_and_render()
            self._log("已重置筛选")

    def _render(self, df, trade_date=None):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.status_hint.config(text=f"交易日 {trade_date}" if trade_date else "")
        for i, r in df.iterrows():
            pct = r.get("pct_chg")
            try:
                pct_v = float(pct)
            except (TypeError, ValueError):
                pct_v = None
            if pct_v is not None and pct_v >= 9.8:
                tag = "limit_up"
            elif pct_v is not None and pct_v > 0:
                tag = "up"
            elif pct_v is not None and pct_v < 0:
                tag = "down"
            else:
                tag = ""
            self.tree.insert("", tk.END, values=(
                i + 1,
                r.get("name", ""),
                r.get("ts_code", ""),
                r.get("industry", ""),
                r.get("close", ""),
                r.get("pct_chg", ""),
                r.get("amount", ""),
                r.get("vol", ""),
            ), tags=(tag,))
        self._log(f"展示 {len(df)} 条")
