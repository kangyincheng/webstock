"""ST 股票转正页面。

布局：
  ┌──────────────────────────────────────────────┐
  │ 参数栏：[最近__月] [量比窗口__日]             │
  │         [开始扫描] [导出CSV]                  │
  ├──────────────────────────────────────────────┤
  │ 进度日志（多行文本）                          │
  ├──────────────────────────────────────────────┤
  │ 筛选栏：[股票代码/名称输入框] [筛选] [重置]  │
  ├──────────────────────────────────────────────┤
  │ 结果表格（支持列头点击排序）:                  │
  │   股票名称 / 代码 / ST开始日期 /              │
  │   ST转正日期 / 股价 / 净资产 /                │
  │   市盈率 / 市净率 / 量比 / 换手              │
  │   （ST转正日期列默认降序，可升/降切换）       │
  └──────────────────────────────────────────────┘
"""
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext, messagebox, filedialog

import pandas as pd

from .st_reinstate_analyzer import STReinstateAnalyzer


# Treeview 列 key 与表头配置
# (col_key, label, width, anchor, is_numeric)
TREE_COLUMNS = [
    ("name",       "股票名称",   100, tk.CENTER, False),
    ("code",       "代码",       100, tk.CENTER, False),
    ("st_start",   "ST开始日期", 110, tk.CENTER, False),
    ("reinstate",  "ST转正日期", 120, tk.CENTER, False),  # 默认降序可切换
    ("price",      "股价",        80, tk.E,      True),
    ("bps",        "净资产",      90, tk.E,      True),
    ("pe",         "市盈率",      80, tk.E,      True),
    ("pb",         "市净率",      80, tk.E,      True),
    ("vol_ratio",  "量比",        80, tk.E,      True),
    ("turnover",   "换手",        80, tk.E,      True),
]

# Treeview 列 key -> DataFrame 列名
COL_TO_DF = {
    "name":      "股票名称",
    "code":      "代码",
    "st_start":  "ST开始日期",
    "reinstate": "ST转正日期",
    "price":     "股价",
    "bps":       "净资产",
    "pe":        "市盈率",
    "pb":        "市净率",
    "vol_ratio": "量比",
    "turnover":  "换手",
}

# 哪些列是数值列（排序时按 float，None 放最后）
NUMERIC_COLS = {"price", "bps", "pe", "pb", "vol_ratio", "turnover"}


class STReinstatePage:
    """ST 股票转正页面。"""

    def __init__(self, parent):
        self.parent = parent
        self.analyzer = STReinstateAnalyzer(data_dir=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

        # 参数默认值
        self.months_var = tk.IntVar(value=12)
        self.vr_days_var = tk.IntVar(value=5)

        # 筛选框
        self.filter_var = tk.StringVar(value="")

        # 全量结果（未筛选）
        self._result_df = None
        # 当前展示中的 DataFrame（排序 + 筛选后的结果）
        self._display_df = None
        self._scanning = False

        # 排序状态
        self._sort_state = {}
        self._last_sort_col = "reinstate"  # 默认按 ST转正日期
        self._last_sort_order = "desc"    # 默认降序

        self._build_ui()

    # ---------------- 布局 ----------------
    def _build_ui(self):
        title = tk.Label(
            self.parent, text="ST 股票转正分析",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#F5F6F7", fg="#1F2329", anchor="w")
        title.pack(fill=tk.X, padx=16, pady=(12, 4))

        subtitle = tk.Label(
            self.parent,
            text="扫描最近 N 个月内出现 ST 状态的股票，列出 ST 开始/转正日期与最新行情、估值、量比、换手指标",
            font=("Microsoft YaHei UI", 10),
            bg="#F5F6F7", fg="#86909C", anchor="w")
        subtitle.pack(fill=tk.X, padx=16, pady=(0, 8))

        self._build_param_card()
        self._build_log_card()
        self._build_filter_card()
        self._build_table_card()

        self._log("准备就绪，点击「开始扫描」拉取数据")

    def _build_param_card(self):
        param_card = tk.Frame(self.parent, bg="#FFFFFF",
                              highlightbackground="#E5E6EB", highlightthickness=1)
        param_card.pack(fill=tk.X, padx=16, pady=4)

        row = tk.Frame(param_card, bg="#FFFFFF")
        row.pack(fill=tk.X, padx=16, pady=12)

        tk.Label(row, text="最近（月）", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 4))
        tk.Entry(row, textvariable=self.months_var, width=6,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 16))

        tk.Label(row, text="量比窗口（天）", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 4))
        tk.Entry(row, textvariable=self.vr_days_var, width=6,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 16))

        self.btn_scan = tk.Button(
            row, text="开始扫描", command=self._on_scan,
            bg="#1677FF", fg="white", relief="flat",
            activebackground="#4096FF", activeforeground="white",
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=14, pady=2, cursor="hand2")
        self.btn_scan.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_export = tk.Button(
            row, text="导出 CSV", command=self._on_export,
            bg="#FFFFFF", fg="#1677FF", relief="flat",
            activebackground="#F2F3F5", activeforeground="#1677FF",
            font=("Microsoft YaHei UI", 10),
            padx=14, pady=2, cursor="hand2",
            highlightbackground="#1677FF", highlightthickness=1)
        self.btn_export.pack(side=tk.LEFT, padx=(0, 8))

    def _build_log_card(self):
        log_card = tk.Frame(self.parent, bg="#FFFFFF",
                            highlightbackground="#E5E6EB", highlightthickness=1)
        log_card.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(log_card, text="进度日志", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#4E5969").pack(anchor="w", padx=12, pady=(8, 2))
        self.log_text = scrolledtext.ScrolledText(
            log_card, height=6, font=("Consolas", 9),
            bg="#FAFBFC", fg="#1F2329", relief="flat",
            wrap=tk.WORD, state="disabled")
        self.log_text.pack(fill=tk.X, padx=12, pady=(0, 8))

    def _build_filter_card(self):
        """筛选栏：股票代码/名称输入 + 筛选/重置按钮。"""
        filter_card = tk.Frame(self.parent, bg="#FFFFFF",
                               highlightbackground="#E5E6EB", highlightthickness=1)
        filter_card.pack(fill=tk.X, padx=16, pady=4)

        row = tk.Frame(filter_card, bg="#FFFFFF")
        row.pack(fill=tk.X, padx=16, pady=10)

        tk.Label(row, text="筛选（代码/名称）：", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10),
                 fg="#4E5969").pack(side=tk.LEFT, padx=(0, 6))

        entry = tk.Entry(
            row, textvariable=self.filter_var, width=30,
            font=("Microsoft YaHei UI", 10),
            bg="#FAFBFC", highlightbackground="#C8CCD2", highlightthickness=1,
            relief="flat")
        entry.pack(side=tk.LEFT, padx=(0, 8))
        # 回车即筛选
        entry.bind("<Return>", lambda e: self._on_filter())

        tk.Button(
            row, text="筛选", command=self._on_filter,
            bg="#1677FF", fg="white", relief="flat",
            activebackground="#4096FF", activeforeground="white",
            font=("Microsoft YaHei UI", 10),
            padx=12, pady=1, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(
            row, text="重置", command=self._on_reset_filter,
            bg="#FFFFFF", fg="#4E5969", relief="flat",
            activebackground="#F2F3F5", activeforeground="#1F2329",
            font=("Microsoft YaHei UI", 10),
            padx=12, pady=1, cursor="hand2",
            highlightbackground="#C8CCD2", highlightthickness=1).pack(side=tk.LEFT)

        self.filter_hint = tk.Label(
            row, text="", bg="#FFFFFF",
            font=("Microsoft YaHei UI", 9), fg="#86909C")
        self.filter_hint.pack(side=tk.LEFT, padx=12)

    def _build_table_card(self):
        table_card = tk.Frame(self.parent, bg="#FFFFFF",
                              highlightbackground="#E5E6EB", highlightthickness=1)
        table_card.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 16))
        tk.Label(table_card, text="ST 股票转正列表（点击列头可排序，ST转正日期可升/降序）",
                 bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#4E5969").pack(anchor="w", padx=12, pady=(8, 2))
        self._build_table(table_card)

    def _build_table(self, parent):
        # 表格容器（带滚动条）
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

        # 给每个列头绑定点击排序事件
        for col_key, label, width, anchor, _is_num in TREE_COLUMNS:
            cmd = (lambda k=col_key: self._on_header_click(k))
            self.tree.heading(col_key, text=label, command=cmd)
            self.tree.column(col_key, width=width, anchor=anchor)

        # 已转正绿底，仍 ST 红底
        self.tree.tag_configure("reinstate", background="#E6FFFB")
        self.tree.tag_configure("still_st",  background="#FFF1F0")

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

    # ---------------- 扫描 ----------------
    def _on_scan(self):
        if self._scanning:
            messagebox.showinfo("提示", "扫描进行中，请稍候")
            return
        try:
            months = int(self.months_var.get())
            vr_days = int(self.vr_days_var.get())
            if months <= 0 or vr_days <= 0:
                raise ValueError("参数必须为正整数")
        except Exception:
            messagebox.showerror("参数错误", "请输入有效的正整数参数")
            return

        self._clear_table()
        self._log(f"开始扫描：最近 {months} 月，量比窗口 {vr_days} 日")

        self._scanning = True
        self.btn_scan.config(text="扫描中...", state="disabled")

        t = threading.Thread(target=self._scan_thread,
                             args=(months, vr_days), daemon=True)
        t.start()

    def _scan_thread(self, months, vr_days):
        try:
            df = self.analyzer.scan_and_analyze(
                months_back=months, volume_ratio_days=vr_days,
                progress_callback=self._log)
            self._result_df = df if (df is not None and not df.empty) else None
            self._sort_state.clear()
            # 重置为默认排序：ST转正日期降序
            self._last_sort_col = "reinstate"
            self._last_sort_order = "desc"
            self.parent.after(0, lambda: self._apply_sort_and_render())
        except Exception as e:
            self.parent.after(0, lambda: messagebox.showerror("错误", str(e)))
            self._log(f"扫描失败：{e}")
        finally:
            self.parent.after(0, self._scan_done)

    def _scan_done(self):
        self._scanning = False
        self.btn_scan.config(text="开始扫描", state="normal")

    # ---------------- 列头排序 ----------------
    def _on_header_click(self, col_key):
        """点击列头触发排序：同一列反复点击时切换升/降序，不同列默认降序。"""
        if self._result_df is None or self._result_df.empty:
            return
        if self._last_sort_col == col_key:
            self._last_sort_order = "desc" if self._last_sort_order == "asc" else "asc"
        else:
            self._last_sort_col = col_key
            # 数值列默认降序；ST转正日期默认降序；其余文本列默认升序
            self._last_sort_order = "desc" if (col_key in NUMERIC_COLS or col_key == "reinstate") else "asc"
        self._sort_state[col_key] = self._last_sort_order
        self._apply_sort_and_render()

    def _apply_sort_and_render(self):
        """基于 self._result_df 应用筛选 + 排序，然后渲染表格。"""
        if self._result_df is None or self._result_df.empty:
            self._display_df = None
            self._clear_table()
            self._log("未找到符合条件的 ST 股")
            return

        df = self._result_df.copy()

        # 1) 应用代码/名称筛选
        filter_text = self.filter_var.get().strip()
        if filter_text:
            mask = self._build_filter_mask(df, filter_text)
            df = df[mask]
            self.filter_hint.config(text=f"已筛选：显示 {len(df)} 条")
        else:
            self.filter_hint.config(text="")

        # 2) 应用排序
        if self._last_sort_col is not None and self._last_sort_col:
            df_col = COL_TO_DF[self._last_sort_col]
            ascending = (self._last_sort_order == "asc")
            if self._last_sort_col in NUMERIC_COLS:
                # 数值列：None 放最后
                sort_series = pd.to_numeric(df[df_col], errors="coerce")
                sort_series_isna = sort_series.isna()
                df_sorted = df.assign(_sort_val=sort_series, _sort_isna=sort_series_isna)
                df_sorted = df_sorted.sort_values(
                    by=["_sort_isna", "_sort_val"],
                    ascending=[True, ascending], kind="mergesort")
                df = df_sorted.drop(columns=["_sort_val", "_sort_isna"])
            else:
                # 字符串/日期：None/空值放最后
                sort_series = df[df_col].fillna("").astype(str)
                sort_isna = sort_series == ""
                df_sorted = df.assign(_sort_val=sort_series, _sort_isna=sort_isna)
                df_sorted = df_sorted.sort_values(
                    by=["_sort_isna", "_sort_val"],
                    ascending=[True, ascending], kind="mergesort")
                df = df_sorted.drop(columns=["_sort_val", "_sort_isna"])

        self._display_df = df.reset_index(drop=True)
        self._render_df_to_tree(self._display_df)

    @staticmethod
    def _build_filter_mask(df, text):
        """按 text 筛选代码/名称。"""
        text = text.strip()
        if not text:
            return pd.Series(True, index=df.index)
        code_col = df["代码"].astype(str)
        name_col = df["股票名称"].astype(str)
        m_code = code_col.str.contains(text, case=False, na=False)
        m_name = name_col.str.contains(text, case=False, na=False)
        # 如果输入 6 位纯数字，也匹配代码去掉 sh./sz. 后的部分
        m_digit6 = pd.Series(False, index=df.index)
        if text.isdigit() and len(text) == 6:
            code_suffix = code_col.str.extract(r"([0-9]{6})", expand=False)
            m_digit6 = code_suffix.fillna("").str.contains(text, na=False)
        return m_code | m_name | m_digit6

    # ---------------- 筛选 ----------------
    def _on_filter(self):
        if self._result_df is None or self._result_df.empty:
            messagebox.showinfo("提示", "暂无数据，请先「开始扫描」")
            return
        keyword = self.filter_var.get().strip()
        if not keyword:
            self._log("筛选关键词为空，显示全部结果")
        else:
            self._log(f"应用筛选：代码/名称包含「{keyword}」")
        self._apply_sort_and_render()

    def _on_reset_filter(self):
        self.filter_var.set("")
        if self._result_df is not None:
            self._apply_sort_and_render()
            self._log("已重置筛选")
        else:
            self.filter_hint.config(text="")

    # ---------------- 渲染 ----------------
    def _clear_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    @staticmethod
    def _fmt(v):
        if v is None:
            return ""
        if isinstance(v, float) and pd.isna(v):
            return ""
        return v

    def _render_df_to_tree(self, df):
        self._clear_table()
        if df is None or df.empty:
            return
        total = len(df)
        shown = 0
        for _, r in df.iterrows():
            reinstate = r.get("ST转正日期")
            # None 或 NaN 视为仍 ST
            if reinstate is None or (isinstance(reinstate, float) and pd.isna(reinstate)) or reinstate == "":
                tag = "still_st"
            else:
                tag = "reinstate"
            self.tree.insert("", tk.END, values=(
                self._fmt(r.get("股票名称", "")),
                self._fmt(r.get("代码", "")),
                self._fmt(r.get("ST开始日期", "")),
                self._fmt(r.get("ST转正日期", "")),
                self._fmt(r.get("股价")),
                self._fmt(r.get("净资产")),
                self._fmt(r.get("市盈率")),
                self._fmt(r.get("市净率")),
                self._fmt(r.get("量比")),
                self._fmt(r.get("换手")),
            ), tags=(tag,))
            shown += 1
        self._log(f"展示 {shown}/{total} 条结果")

    def _render_result(self, df):
        # 旧方法兼容：交给统一入口
        self._result_df = df if (df is not None and not df.empty) else None
        self._apply_sort_and_render()

    # ---------------- 导出 ----------------
    def _on_export(self):
        if self._display_df is None or self._display_df.empty:
            if self._result_df is None or self._result_df.empty:
                messagebox.showwarning("提示", "没有可导出的数据，请先扫描")
                return
            data_to_export = self._result_df
        else:
            data_to_export = self._display_df
        default_name = f"st_reinstate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            title="导出 CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            data_to_export.to_csv(path, index=False, encoding="utf-8-sig")
            self._log(f"已导出 {len(data_to_export)} 条 → {path}")
            messagebox.showinfo("成功", f"已导出 {len(data_to_export)} 条数据到：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
