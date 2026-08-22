"""可转债发审进度页面。

布局：
  ┌──────────────────────────────────────────────┐
  │ 标题 / 副标题                                   │
  ├──────────────────────────────────────────────┤
  │ 参数卡：[刷新数据] [导出CSV]  [发审阶段筛选]   │
  ├──────────────────────────────────────────────┤
  │ 进度日志                                        │
  ├──────────────────────────────────────────────┤
  │ 筛选卡：转债/正股代码名称关键字 [筛选][重置]   │
  ├──────────────────────────────────────────────┤
  │ 结果表格：                                      │
  │   转债代码/转债名称/发审阶段/审核进度(%)/      │
  │   正股代码/正股名称/正股价/债发行价/           │
  │   转股价/转股价值/溢价率/受理日期/预计发行日   │
  │   (点击列头可排序)                              │
  └──────────────────────────────────────────────┘
"""
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext, messagebox, filedialog

import pandas as pd

from .cbond_analyzer import ConvertibleBondAnalyzer


# Treeview 列配置
REVIEW_COLUMNS = [
    ("cb_code",   "转债代码",     100, tk.CENTER, False),
    ("cb_name",   "转债名称",     110, tk.CENTER, False),
    ("stage",     "发审阶段",     110, tk.CENTER, False),
    ("progress",  "审核进度(%)",  100, tk.CENTER, True),
    ("stk_code",  "正股代码",     100, tk.CENTER, False),
    ("stk_name",  "正股名称",     100, tk.CENTER, False),
    ("stk_price", "正股价",        80, tk.E,      True),
    ("issue_p",   "债发行价",      80, tk.E,      True),
    ("conv_p",    "转股价",        80, tk.E,      True),
    ("conv_val",  "转股价值",      85, tk.E,      True),
    ("premium",   "溢价率(%)",     90, tk.E,      True),
    ("accept_dt", "受理日期",     105, tk.CENTER, False),
    ("plan_dt",   "预计发行日期",  110, tk.CENTER, False),
]

REVIEW_DF_MAP = {
    "cb_code": "转债代码", "cb_name": "转债名称", "stage": "发审阶段",
    "progress": "审核进度(%)",
    "stk_code": "正股代码", "stk_name": "正股名称", "stk_price": "正股价",
    "issue_p": "债发行价", "conv_p": "转股价", "conv_val": "转股价值",
    "premium": "可转债溢价率(%)",
    "accept_dt": "受理日期", "plan_dt": "预计发行日期",
}

NUMERIC_COLS = {"progress", "stk_price", "issue_p", "conv_p", "conv_val", "premium"}

STAGE_ORDER = ["董事会预案", "股东大会通过", "发审委受理", "发审委问询",
               "发审委通过", "证监会核准", "发行中", "已完成"]


def _setup_tree_style():
    style = ttk.Style()
    style.configure("Treeview.Heading",
                    font=("Microsoft YaHei UI", 10, "bold"),
                    background="#F2F3F5", foreground="#1F2329")
    style.configure("Treeview",
                    font=("Microsoft YaHei UI", 10),
                    rowheight=26)


class CBondReviewPage:
    """可转债发审进度页面。"""

    def __init__(self, parent):
        self.parent = parent
        self.analyzer = ConvertibleBondAnalyzer(data_dir=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

        self._result_df = None
        self._display_df = None
        self._loading = False

        # 筛选
        self.filter_var = tk.StringVar(value="")
        self.stage_filter_var = tk.StringVar(value="全部")

        # 排序
        self._last_sort_col = "stage"
        self._last_sort_order = "asc"

        self._build_ui()

    # ---------------- UI ----------------
    def _build_ui(self):
        title = tk.Label(
            self.parent, text="可转债发审进度",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#F5F6F7", fg="#1F2329", anchor="w")
        title.pack(fill=tk.X, padx=16, pady=(12, 4))

        subtitle = tk.Label(
            self.parent,
            text="查看已向交易所提交发行申请的可转债，含发审阶段、审核进度、对应正股与估值指标",
            font=("Microsoft YaHei UI", 10),
            bg="#F5F6F7", fg="#86909C", anchor="w")
        subtitle.pack(fill=tk.X, padx=16, pady=(0, 8))

        self._build_param_card()
        self._build_log_card()
        self._build_filter_card()
        self._build_table_card()

        self._log("准备就绪，点击「刷新数据」获取最新可转债发审进度")
        self.parent.after(300, self._on_refresh)

    def _build_param_card(self):
        card = tk.Frame(self.parent, bg="#FFFFFF",
                        highlightbackground="#E5E6EB", highlightthickness=1)
        card.pack(fill=tk.X, padx=16, pady=4)
        row = tk.Frame(card, bg="#FFFFFF")
        row.pack(fill=tk.X, padx=16, pady=12)

        self.btn_refresh = tk.Button(
            row, text="刷新数据", command=self._on_refresh,
            bg="#1677FF", fg="white", relief="flat",
            activebackground="#4096FF", activeforeground="white",
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=14, pady=2, cursor="hand2")
        self.btn_refresh.pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(row, text="发审阶段：", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 4))
        stage_opts = ["全部"] + STAGE_ORDER
        self.stage_combo = ttk.Combobox(
            row, textvariable=self.stage_filter_var,
            values=stage_opts, width=14, state="readonly")
        self.stage_combo.pack(side=tk.LEFT, padx=(0, 16))
        self.stage_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_sort_filter_render())

        self.btn_export = tk.Button(
            row, text="导出 CSV", command=self._on_export,
            bg="#FFFFFF", fg="#1677FF", relief="flat",
            activebackground="#F2F3F5", activeforeground="#1677FF",
            font=("Microsoft YaHei UI", 10),
            padx=12, pady=2, cursor="hand2",
            highlightbackground="#1677FF", highlightthickness=1)
        self.btn_export.pack(side=tk.LEFT)

    def _build_log_card(self):
        card = tk.Frame(self.parent, bg="#FFFFFF",
                        highlightbackground="#E5E6EB", highlightthickness=1)
        card.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(card, text="进度日志", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#4E5969").pack(anchor="w", padx=12, pady=(8, 2))
        self.log_text = scrolledtext.ScrolledText(
            card, height=5, font=("Consolas", 9),
            bg="#FAFBFC", fg="#1F2329", relief="flat",
            wrap=tk.WORD, state="disabled")
        self.log_text.pack(fill=tk.X, padx=12, pady=(0, 8))

    def _build_filter_card(self):
        card = tk.Frame(self.parent, bg="#FFFFFF",
                        highlightbackground="#E5E6EB", highlightthickness=1)
        card.pack(fill=tk.X, padx=16, pady=4)
        row = tk.Frame(card, bg="#FFFFFF")
        row.pack(fill=tk.X, padx=16, pady=10)

        tk.Label(row, text="关键字（转债/正股代码或名称）：",
                 bg="#FFFFFF", font=("Microsoft YaHei UI", 10),
                 fg="#4E5969").pack(side=tk.LEFT, padx=(0, 6))
        entry = tk.Entry(
            row, textvariable=self.filter_var, width=36,
            font=("Microsoft YaHei UI", 10),
            bg="#FAFBFC", highlightbackground="#C8CCD2", highlightthickness=1,
            relief="flat")
        entry.pack(side=tk.LEFT, padx=(0, 8))
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

        self.filter_hint = tk.Label(row, text="", bg="#FFFFFF",
                                    font=("Microsoft YaHei UI", 9), fg="#86909C")
        self.filter_hint.pack(side=tk.LEFT, padx=12)

    def _build_table_card(self):
        card = tk.Frame(self.parent, bg="#FFFFFF",
                        highlightbackground="#E5E6EB", highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 16))
        header = tk.Frame(card, bg="#FFFFFF")
        header.pack(fill=tk.X, padx=12, pady=(8, 2))
        tk.Label(header, text="可转债发审列表（点击列头可排序）",
                 bg="#FFFFFF", font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#4E5969").pack(side=tk.LEFT)
        self.lbl_count = tk.Label(header, text="", bg="#FFFFFF",
                                  font=("Microsoft YaHei UI", 9),
                                  fg="#86909C")
        self.lbl_count.pack(side=tk.RIGHT)
        self._build_tree(card)

    def _build_tree(self, parent):
        container = tk.Frame(parent, bg="#FFFFFF")
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        _setup_tree_style()

        ysb = ttk.Scrollbar(container, orient="vertical")
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb = ttk.Scrollbar(container, orient="horizontal")
        xsb.pack(side=tk.BOTTOM, fill=tk.X)

        col_keys = tuple(k for k, *_ in REVIEW_COLUMNS)
        self.tree = ttk.Treeview(
            container, columns=col_keys, show="headings",
            yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        for key, label, w, anchor, _ in REVIEW_COLUMNS:
            cmd = (lambda k=key: self._on_header_click(k))
            self.tree.heading(key, text=label, command=cmd)
            self.tree.column(key, width=w, anchor=anchor, minwidth=50)

        # 标签
        self.tree.tag_configure("premium_pos", background="#FFF1F0")
        self.tree.tag_configure("premium_neg", background="#F6FFED")
        # 发审后期阶段重点突出
        self.tree.tag_configure("stage_late", background="#FFF7E6")
        self.tree.tag_configure("stage_early", background="#E6F7FF")

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

    # ---------------- 刷新 ----------------
    def _on_refresh(self):
        if self._loading:
            messagebox.showinfo("提示", "数据加载中，请稍候")
            return
        self._loading = True
        self.btn_refresh.config(text="加载中...", state="disabled")
        self._clear_tree()
        self._log("开始获取可转债发审进度数据 ...")

        t = threading.Thread(target=self._refresh_thread, daemon=True)
        t.start()

    def _refresh_thread(self):
        try:
            df = self.analyzer.fetch_review(progress_callback=self._log)
            self._result_df = df if (df is not None and not df.empty) else None
            self.parent.after(0, self._apply_sort_filter_render)
        except Exception as e:
            self._log(f"获取失败：{e}")
            self.parent.after(0, lambda: messagebox.showerror("错误", str(e)))
        finally:
            self.parent.after(0, self._refresh_done)

    def _refresh_done(self):
        self._loading = False
        self.btn_refresh.config(text="刷新数据", state="normal")

    # ---------------- 列头排序 ----------------
    def _on_header_click(self, col_key):
        if self._result_df is None or self._result_df.empty:
            return
        if self._last_sort_col == col_key:
            self._last_sort_order = "desc" if self._last_sort_order == "asc" else "asc"
        else:
            self._last_sort_col = col_key
            self._last_sort_order = "desc" if col_key in NUMERIC_COLS else "asc"
        self._apply_sort_filter_render()

    # ---------------- 筛选/排序/渲染 统一入口 ----------------
    def _apply_sort_filter_render(self):
        if self._result_df is None or self._result_df.empty:
            self._display_df = None
            self._clear_tree()
            self.filter_hint.config(text="")
            self.lbl_count.config(text="共 0 条")
            self._log("暂无可转债发审数据")
            return

        df = self._result_df.copy()

        # 1) 发审阶段下拉筛选
        stage = self.stage_filter_var.get()
        if stage and stage != "全部":
            df = df[df["发审阶段"].astype(str) == stage]

        # 2) 关键字筛选（转债/正股代码或名称）
        kw = self.filter_var.get().strip()
        if kw:
            m1 = df["转债代码"].astype(str).str.contains(kw, case=False, na=False)
            m2 = df["转债名称"].astype(str).str.contains(kw, case=False, na=False)
            m3 = df["正股代码"].astype(str).str.contains(kw, case=False, na=False)
            m4 = df["正股名称"].astype(str).str.contains(kw, case=False, na=False)
            if kw.isdigit() and len(kw) == 6:
                m5 = df["正股代码"].astype(str).str.extract(
                    r"([0-9]{6})", expand=False).fillna("").str.contains(kw, na=False)
            else:
                m5 = pd.Series(False, index=df.index)
            df = df[m1 | m2 | m3 | m4 | m5]
            self.filter_hint.config(text=f"筛选后 {len(df)} 条")
        else:
            self.filter_hint.config(text="")

        # 3) 排序
        col_key = self._last_sort_col
        if col_key:
            df_col = REVIEW_DF_MAP[col_key]
            ascending = (self._last_sort_order == "asc")
            if col_key == "stage":
                # 发审阶段按自定义顺序
                order_map = {s: i for i, s in enumerate(STAGE_ORDER)}
                df = df.assign(_ord=df[df_col].map(lambda s: order_map.get(str(s), 999)))
                prog_col = REVIEW_DF_MAP["progress"]
                df = df.sort_values(
                    by=["_ord", prog_col],
                    ascending=[ascending, False], kind="mergesort").drop(columns=["_ord"])
            elif col_key in NUMERIC_COLS:
                sv = pd.to_numeric(df[df_col], errors="coerce")
                df = df.assign(_s=sv, _na=sv.isna())
                df = df.sort_values(
                    by=["_na", "_s"], ascending=[True, ascending], kind="mergesort")
                df = df.drop(columns=["_s", "_na"])
            else:
                sv = df[df_col].fillna("").astype(str)
                df = df.assign(_s=sv, _na=sv == "")
                df = df.sort_values(
                    by=["_na", "_s"], ascending=[True, ascending], kind="mergesort")
                df = df.drop(columns=["_s", "_na"])

        self._display_df = df.reset_index(drop=True)
        self._render_to_tree(self._display_df)

    @staticmethod
    def _fmt(v):
        if v is None:
            return ""
        if isinstance(v, float) and pd.isna(v):
            return ""
        if isinstance(v, float):
            return f"{v:.2f}"
        return v

    def _render_to_tree(self, df):
        self._clear_tree()
        if df is None or df.empty:
            return
        late_stages = {"证监会核准", "发行中", "已完成"}
        early_stages = {"董事会预案", "股东大会通过"}
        for _, r in df.iterrows():
            tags = []
            # 溢价率
            try:
                p = float(r.get("可转债溢价率(%)"))
                tags.append("premium_pos" if p > 0 else "premium_neg")
            except Exception:
                pass
            # 发审阶段
            try:
                s = str(r.get("发审阶段", ""))
                if s in late_stages:
                    tags.append("stage_late")
                elif s in early_stages:
                    tags.append("stage_early")
            except Exception:
                pass

            self.tree.insert("", tk.END, values=(
                self._fmt(r.get(REVIEW_DF_MAP["cb_code"], "")),
                self._fmt(r.get(REVIEW_DF_MAP["cb_name"], "")),
                self._fmt(r.get(REVIEW_DF_MAP["stage"], "")),
                self._fmt(r.get(REVIEW_DF_MAP["progress"])),
                self._fmt(r.get(REVIEW_DF_MAP["stk_code"], "")),
                self._fmt(r.get(REVIEW_DF_MAP["stk_name"], "")),
                self._fmt(r.get(REVIEW_DF_MAP["stk_price"])),
                self._fmt(r.get(REVIEW_DF_MAP["issue_p"])),
                self._fmt(r.get(REVIEW_DF_MAP["conv_p"])),
                self._fmt(r.get(REVIEW_DF_MAP["conv_val"])),
                self._fmt(r.get(REVIEW_DF_MAP["premium"])),
                self._fmt(r.get(REVIEW_DF_MAP["accept_dt"], "")),
                self._fmt(r.get(REVIEW_DF_MAP["plan_dt"], "")),
            ), tags=tuple(tags))
        total = len(self._result_df) if self._result_df is not None else 0
        shown = len(df)
        self.lbl_count.config(text=f"显示 {shown}/{total} 条")
        self._log(f"渲染完成：显示 {shown}/{total} 条")

    def _clear_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _on_filter(self):
        if self._result_df is None:
            messagebox.showinfo("提示", "暂无数据，请先「刷新数据」")
            return
        self._apply_sort_filter_render()

    def _on_reset_filter(self):
        self.filter_var.set("")
        self.stage_filter_var.set("全部")
        if self._result_df is not None:
            self._apply_sort_filter_render()

    # ---------------- 导出 ----------------
    def _on_export(self):
        data = self._display_df if (self._display_df is not None and not self._display_df.empty) \
            else self._result_df
        if data is None or data.empty:
            messagebox.showwarning("提示", "没有可导出的数据，请先刷新")
            return
        default_name = f"cbond_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            title="导出可转债发审 CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            data.to_csv(path, index=False, encoding="utf-8-sig")
            self._log(f"已导出 {len(data)} 条 → {path}")
            messagebox.showinfo("成功", f"已导出 {len(data)} 条到：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
