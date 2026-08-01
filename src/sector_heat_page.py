"""板块热度页面。

布局：
  ┌──────────────────────────────────────────────────┐
  │ 标题：板块热度                                    │
  ├──────────────────────────────────────────────────┤
  │ 参数栏：[交易日____] [加载] [刷新缓存]            │
  ├──────────────────────────────────────────────────┤
  │ 进度日志                                          │
  ├──────────────────────────────────────────────────┤
  │ 板块热度表格（按平均涨幅排序，点击列头可重排）：    │
  │  板块名 / 成分股数 / 平均涨幅(%) / 总成交额(万) /  │
  │  上涨家数 / 下跌家数 / 涨停家数                  │
  └──────────────────────────────────────────────────┘

数据源：tushare pro.daily + pro.stock_basic（按 industry 字段分组）
"""
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext, messagebox

import pandas as pd

from .market_data import TushareClient


# Treeview 列定义（col_key, 表头, 宽度, 对齐, 是否数值列）
TREE_COLUMNS = [
    ("rank",     "排名",          60,  tk.CENTER, False),
    ("industry", "板块名称",      140, tk.W,      False),
    ("count",    "成分股数",       80,  tk.CENTER, True),
    ("avg_chg",  "平均涨幅(%)",    120, tk.E,      True),
    ("med_chg",  "中位涨幅(%)",    120, tk.E,      True),
    ("amount",   "总成交额(万元)", 130, tk.E,      True),
    ("up_cnt",   "上涨家数",       90,  tk.CENTER, True),
    ("down_cnt", "下跌家数",       90,  tk.CENTER, True),
    ("limit_up", "涨停家数",       80,  tk.CENTER, True),
]
COL_TO_LABEL = {k: v for k, v, *_ in TREE_COLUMNS}
NUMERIC_COLS = {k for k, _, _, _, is_num in TREE_COLUMNS if is_num}


class SectorHeatPage:
    """板块热度页面。"""

    def __init__(self, parent):
        self.parent = parent
        self.client = TushareClient(data_dir=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

        # 参数
        self.trade_date_var = tk.StringVar(value="")  # 空表示最近交易日
        self._result_df = None
        self._display_df = None
        self._loading = False

        # 排序状态
        self._last_sort_col = "avg_chg"
        self._last_sort_order = "desc"

        self._build_ui()
        self._log("准备就绪。点击「加载」拉取最近交易日板块数据。")

    # ---------------- 布局 ----------------
    def _build_ui(self):
        tk.Label(
            self.parent, text="板块热度",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#F5F6F7", fg="#1F2329", anchor="w"
        ).pack(fill=tk.X, padx=16, pady=(12, 4))
        tk.Label(
            self.parent,
            text="按行业分组，统计当日平均涨幅 / 总成交额 / 上涨下跌家数 / 涨停家数",
            font=("Microsoft YaHei UI", 10),
            bg="#F5F6F7", fg="#86909C", anchor="w"
        ).pack(fill=tk.X, padx=16, pady=(0, 8))

        # 参数栏
        param_card = tk.Frame(self.parent, bg="#FFFFFF",
                               highlightbackground="#E5E6EB", highlightthickness=1)
        param_card.pack(fill=tk.X, padx=16, pady=4)
        row = tk.Frame(param_card, bg="#FFFFFF")
        row.pack(fill=tk.X, padx=16, pady=10)
        tk.Label(row, text="交易日（YYYYMMDD，留空=最近交易日）", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 6))
        tk.Entry(row, textvariable=self.trade_date_var, width=14,
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

        # 表格
        table_card = tk.Frame(self.parent, bg="#FFFFFF",
                              highlightbackground="#E5E6EB", highlightthickness=1)
        table_card.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 16))
        tk.Label(table_card, text="板块热度榜（点击列头排序）", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#4E5969").pack(anchor="w", padx=12, pady=(8, 2))
        self._build_table(table_card)

    def _build_table(self, parent):
        container = tk.Frame(parent, bg="#FFFFFF")
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
        # 行底色
        self.tree.tag_configure("up", background="#FFF7E6")
        self.tree.tag_configure("down", background="#FFF1F0")
        self.tree.tag_configure("flat", background="#F5F6F7")

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
        # 校验 token
        if not self.client.is_configured():
            messagebox.showerror(
                "未配置 Tushare token",
                "请在项目根目录创建 tushare_token.txt 文件，把 token 写入第一行。\n"
                "（该文件已被 .gitignore 排除，不会被提交到 git）")
            return
        td = self.trade_date_var.get().strip()
        if td and (not td.isdigit() or len(td) != 8):
            messagebox.showerror("日期格式错误", "交易日应为 YYYYMMDD 8 位数字（如 20260731）")
            return

        self._loading = True
        self.btn_load.config(text="加载中...", state="disabled")
        t = threading.Thread(target=self._load_thread, args=(td,), daemon=True)
        t.start()

    def _on_refresh(self):
        """刷新缓存：删除当日的 daily_xxx.csv 与 stock_basic.csv。"""
        td = self.trade_date_var.get().strip()
        deleted = []
        if td:
            p = os.path.join(self.client.data_dir, f"daily_{td}.csv")
            if os.path.exists(p):
                os.remove(p)
                deleted.append(p)
        else:
            # 清掉所有 daily_ 缓存
            for fn in os.listdir(self.client.data_dir):
                if fn.startswith("daily_") and fn.endswith(".csv"):
                    os.remove(os.path.join(self.client.data_dir, fn))
                    deleted.append(fn)
        sb = os.path.join(self.client.data_dir, "stock_basic.csv")
        if os.path.exists(sb):
            os.remove(sb)
            deleted.append("stock_basic.csv")
        self._log(f"已清除 {len(deleted)} 个缓存文件")
        if deleted:
            messagebox.showinfo("刷新缓存", f"已清除 {len(deleted)} 个缓存文件，请重新加载")

    def _load_thread(self, td):
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
            self._log("拉取股票基本信息（含 industry 字段）...")
            basic = self.client.fetch_stock_basic()
            if basic is None or basic.empty:
                self.parent.after(0, lambda: messagebox.showerror("错误", "拉取股票基本信息失败"))
                return
            self._log(f"基本信息：{len(basic)} 条")
            df = self._aggregate(daily, basic)
            self._result_df = df
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

    # ---------------- 聚合 ----------------
    @staticmethod
    def _aggregate(daily, basic):
        """按 industry 分组聚合板块热度。"""
        # 合并：daily + basic（按 ts_code）
        merged = daily.merge(basic[["ts_code", "name", "industry"]],
                             on="ts_code", how="left")
        # 缺 industry 的归为「未分类」
        merged["industry"] = merged["industry"].fillna("未分类").replace("", "未分类")
        # 数值化
        for c in ["pct_chg", "amount"]:
            merged[c] = pd.to_numeric(merged[c], errors="coerce")

        # 涨停判断：A股 ±10%（ST/科创板/创业板更复杂，这里近似用 9.8% 阈值）
        merged["is_limit_up"] = (merged["pct_chg"] >= 9.8).astype(int)
        merged["is_up"] = (merged["pct_chg"] > 0).astype(int)
        merged["is_down"] = (merged["pct_chg"] < 0).astype(int)

        grp = merged.groupby("industry", as_index=False).agg(
            count=("ts_code", "count"),
            avg_chg=("pct_chg", "mean"),
            med_chg=("pct_chg", "median"),
            amount=("amount", "sum"),
            up_cnt=("is_up", "sum"),
            down_cnt=("is_down", "sum"),
            limit_up=("is_limit_up", "sum"),
        )
        # 转换 amount 单位：tushare amount 单位是千元，转万元
        grp["amount"] = (grp["amount"] / 10.0).round(2)
        # 涨幅保留 2 位
        grp["avg_chg"] = grp["avg_chg"].round(2)
        grp["med_chg"] = grp["med_chg"].round(2)
        # 默认按平均涨幅降序
        grp = grp.sort_values("avg_chg", ascending=False).reset_index(drop=True)
        return grp

    # ---------------- 排序 + 渲染 ----------------
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
        col = self._last_sort_col
        asc = (self._last_sort_order == "asc")
        df = df.sort_values(by=col, ascending=asc, kind="mergesort").reset_index(drop=True)
        self._display_df = df
        self._render(df, trade_date)

    def _render(self, df, trade_date=None):
        for item in self.tree.get_children():
            self.tree.delete(item)
        hint = f"交易日 {trade_date}" if trade_date else ""
        self.status_hint.config(text=hint)
        for i, r in df.iterrows():
            avg = r.get("avg_chg")
            try:
                avg_v = float(avg)
            except (TypeError, ValueError):
                avg_v = None
            tag = ("up" if (avg_v is not None and avg_v > 0) else
                   "down" if (avg_v is not None and avg_v < 0) else "flat")
            self.tree.insert("", tk.END, values=(
                i + 1,
                r.get("industry", ""),
                int(r.get("count", 0)),
                r.get("avg_chg", ""),
                r.get("med_chg", ""),
                r.get("amount", ""),
                int(r.get("up_cnt", 0)),
                int(r.get("down_cnt", 0)),
                int(r.get("limit_up", 0)),
            ), tags=(tag,))
        self._log(f"展示 {len(df)} 个板块")
