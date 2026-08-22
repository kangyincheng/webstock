"""可转债打新上市页面。

布局（上下双表）：
  ┌────────────────────────────────────────────────┐
  │ 标题 / 副标题                                   │
  ├────────────────────────────────────────────────┤
  │ 参数卡：[刷新数据] [导出CSV]                    │
  ├────────────────────────────────────────────────┤
  │ 进度日志                                        │
  ├────────────────────────────────────────────────┤
  │ 【表1：当日可申购可转债】（表格 + 滚动条）      │
  │   转债代码/转债名称/申购日期/正股代码/正股名称  │
  │   /正股价/债发行价/转股价/转股价值/溢价率/      │
  │   配售代码/申购上限                             │
  ├────────────────────────────────────────────────┤
  │ 【表2：当日上市新可转债】（表格 + 滚动条）      │
  │   转债代码/转债名称/上市日期/正股代码/正股名称  │
  │   /正股价/债发行价/转股价/转股价值/转债开盘价   │
  │   /溢价率/首日涨幅                              │
  └────────────────────────────────────────────────┘
"""
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext, messagebox, filedialog

import pandas as pd

from .cbond_analyzer import ConvertibleBondAnalyzer


# ---------------- 可申购表列配置 ----------------
# (col_key, label, width, anchor, is_numeric)
SUB_COLUMNS = [
    ("cb_code",   "转债代码",     100, tk.CENTER, False),
    ("cb_name",   "转债名称",     110, tk.CENTER, False),
    ("sub_date",  "申购日期",     105, tk.CENTER, False),
    ("stk_code",  "正股代码",     100, tk.CENTER, False),
    ("stk_name",  "正股名称",     100, tk.CENTER, False),
    ("stk_price", "正股价",        80, tk.E,      True),
    ("issue_p",   "债发行价",      80, tk.E,      True),
    ("conv_p",    "转股价",        80, tk.E,      True),
    ("conv_val",  "转股价值",      85, tk.E,      True),
    ("premium",   "溢价率(%)",     90, tk.E,      True),
    ("match_code","配售代码",      100, tk.CENTER, False),
    ("uplimit",   "申购上限(万元)", 110, tk.E,    True),
]
SUB_DF_MAP = {
    "cb_code": "转债代码", "cb_name": "转债名称", "sub_date": "申购日期",
    "stk_code": "正股代码", "stk_name": "正股名称", "stk_price": "正股价",
    "issue_p": "债发行价", "conv_p": "转股价", "conv_val": "转股价值",
    "premium": "可转债溢价率(%)", "match_code": "配售代码", "uplimit": "申购上限(万元)",
}

# ---------------- 上市表列配置 ----------------
LIST_COLUMNS = [
    ("cb_code",   "转债代码",    100, tk.CENTER, False),
    ("cb_name",   "转债名称",    110, tk.CENTER, False),
    ("list_date", "上市日期",    105, tk.CENTER, False),
    ("stk_code",  "正股代码",    100, tk.CENTER, False),
    ("stk_name",  "正股名称",    100, tk.CENTER, False),
    ("stk_price", "正股价",       80, tk.E,      True),
    ("issue_p",   "债发行价",     80, tk.E,      True),
    ("conv_p",    "转股价",       80, tk.E,      True),
    ("conv_val",  "转股价值",     85, tk.E,      True),
    ("open_p",    "转债开盘价",    90, tk.E,      True),
    ("premium",   "溢价率(%)",    90, tk.E,      True),
    ("chg_pct",   "首日涨幅(%)", 100, tk.E,      True),
]
LIST_DF_MAP = {
    "cb_code": "转债代码", "cb_name": "转债名称", "list_date": "上市日期",
    "stk_code": "正股代码", "stk_name": "正股名称", "stk_price": "正股价",
    "issue_p": "债发行价", "conv_p": "转股价", "conv_val": "转股价值",
    "open_p": "转债开盘价", "premium": "可转债溢价率(%)", "chg_pct": "首日涨幅(%)",
}


def _setup_tree_style():
    style = ttk.Style()
    style.configure("Treeview.Heading",
                    font=("Microsoft YaHei UI", 10, "bold"),
                    background="#F2F3F5", foreground="#1F2329")
    style.configure("Treeview",
                    font=("Microsoft YaHei UI", 10),
                    rowheight=26)


class CBondIpoPage:
    """可转债打新上市页面（双表）。"""

    def __init__(self, parent):
        self.parent = parent
        self.analyzer = ConvertibleBondAnalyzer(data_dir=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

        self._sub_df = None
        self._list_df = None
        self._loading = False

        self._build_ui()

    # ---------------- UI 构造 ----------------
    def _build_ui(self):
        title = tk.Label(
            self.parent, text="可转债打新上市",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#F5F6F7", fg="#1F2329", anchor="w")
        title.pack(fill=tk.X, padx=16, pady=(12, 4))

        subtitle = tk.Label(
            self.parent,
            text="查看当日可申购可转债与当日上市新可转债，含对应正股、转股价、溢价率等关键指标",
            font=("Microsoft YaHei UI", 10),
            bg="#F5F6F7", fg="#86909C", anchor="w")
        subtitle.pack(fill=tk.X, padx=16, pady=(0, 8))

        self._build_param_card()
        self._build_log_card()
        self._build_sub_card()
        self._build_list_card()

        self._log("准备就绪，点击「刷新数据」获取最新可转债打新/上市信息")
        # 页面加载后自动刷新一次
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
        self.btn_refresh.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_export_sub = tk.Button(
            row, text="导出申购表", command=lambda: self._on_export("sub"),
            bg="#FFFFFF", fg="#1677FF", relief="flat",
            activebackground="#F2F3F5", activeforeground="#1677FF",
            font=("Microsoft YaHei UI", 10),
            padx=12, pady=2, cursor="hand2",
            highlightbackground="#1677FF", highlightthickness=1)
        self.btn_export_sub.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_export_list = tk.Button(
            row, text="导出上市表", command=lambda: self._on_export("list"),
            bg="#FFFFFF", fg="#1677FF", relief="flat",
            activebackground="#F2F3F5", activeforeground="#1677FF",
            font=("Microsoft YaHei UI", 10),
            padx=12, pady=2, cursor="hand2",
            highlightbackground="#1677FF", highlightthickness=1)
        self.btn_export_list.pack(side=tk.LEFT)

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

    def _build_sub_card(self):
        card = tk.Frame(self.parent, bg="#FFFFFF",
                        highlightbackground="#E5E6EB", highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True, padx=16, pady=4)
        header = tk.Frame(card, bg="#FFFFFF")
        header.pack(fill=tk.X, padx=12, pady=(8, 0))
        tk.Label(header, text="📋 当日可申购可转债",
                 bg="#FFFFFF", font=("Microsoft YaHei UI", 11, "bold"),
                 fg="#1677FF").pack(side=tk.LEFT)
        self.lbl_sub_count = tk.Label(header, text="", bg="#FFFFFF",
                                      font=("Microsoft YaHei UI", 9),
                                      fg="#86909C")
        self.lbl_sub_count.pack(side=tk.RIGHT)
        self._sub_tree = self._build_tree(card, SUB_COLUMNS, height=9)
        self._config_tags(self._sub_tree)

    def _build_list_card(self):
        card = tk.Frame(self.parent, bg="#FFFFFF",
                        highlightbackground="#E5E6EB", highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 16))
        header = tk.Frame(card, bg="#FFFFFF")
        header.pack(fill=tk.X, padx=12, pady=(8, 0))
        tk.Label(header, text="🎉 当日上市新可转债",
                 bg="#FFFFFF", font=("Microsoft YaHei UI", 11, "bold"),
                 fg="#F5222D").pack(side=tk.LEFT)
        self.lbl_list_count = tk.Label(header, text="", bg="#FFFFFF",
                                       font=("Microsoft YaHei UI", 9),
                                       fg="#86909C")
        self.lbl_list_count.pack(side=tk.RIGHT)
        self._list_tree = self._build_tree(card, LIST_COLUMNS, height=7)
        self._config_tags(self._list_tree, is_list=True)

    def _build_tree(self, parent, columns, height):
        container = tk.Frame(parent, bg="#FFFFFF")
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        _setup_tree_style()

        ysb = ttk.Scrollbar(container, orient="vertical")
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb = ttk.Scrollbar(container, orient="horizontal")
        xsb.pack(side=tk.BOTTOM, fill=tk.X)

        col_keys = tuple(k for k, *_ in columns)
        tree = ttk.Treeview(container, columns=col_keys, show="headings",
                            height=height,
                            yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        for key, label, w, anchor, _ in columns:
            tree.heading(key, text=label)
            tree.column(key, width=w, anchor=anchor, minwidth=50)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.config(command=tree.yview)
        xsb.config(command=tree.xview)
        return tree

    def _config_tags(self, tree, is_list=False):
        # 溢价率标签：正溢价浅红，负溢价浅绿
        tree.tag_configure("premium_pos", background="#FFF1F0")
        tree.tag_configure("premium_neg", background="#F6FFED")
        if is_list:
            tree.tag_configure("chg_big", background="#FFF7E6")  # 首日大涨

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
        self._clear_trees()
        self._log("开始获取可转债打新/上市数据 ...")

        t = threading.Thread(target=self._refresh_thread, daemon=True)
        t.start()

    def _refresh_thread(self):
        try:
            sub_df, list_df = self.analyzer.fetch_new_ipo(
                progress_callback=self._log)
            self._sub_df = sub_df if (sub_df is not None and not sub_df.empty) else None
            self._list_df = list_df if (list_df is not None and not list_df.empty) else None
            self.parent.after(0, self._render_result)
        except Exception as e:
            self._log(f"获取失败：{e}")
            self.parent.after(0, lambda: messagebox.showerror("错误", str(e)))
        finally:
            self.parent.after(0, self._refresh_done)

    def _refresh_done(self):
        self._loading = False
        self.btn_refresh.config(text="刷新数据", state="normal")

    # ---------------- 渲染 ----------------
    def _clear_trees(self):
        for t in (self._sub_tree, self._list_tree):
            for item in t.get_children():
                t.delete(item)
        self.lbl_sub_count.config(text="")
        self.lbl_list_count.config(text="")

    @staticmethod
    def _fmt(v):
        if v is None:
            return ""
        if isinstance(v, float) and pd.isna(v):
            return ""
        if isinstance(v, float):
            return f"{v:.2f}"
        return v

    def _render_result(self):
        # 渲染申购表
        sub_n = 0
        if self._sub_df is not None:
            for _, r in self._sub_df.iterrows():
                premium = r.get("可转债溢价率(%)")
                try:
                    prem_val = float(premium)
                    tag = "premium_pos" if prem_val > 0 else "premium_neg"
                except Exception:
                    tag = ""
                self._sub_tree.insert("", tk.END, values=(
                    self._fmt(r.get(SUB_DF_MAP["cb_code"], "")),
                    self._fmt(r.get(SUB_DF_MAP["cb_name"], "")),
                    self._fmt(r.get(SUB_DF_MAP["sub_date"], "")),
                    self._fmt(r.get(SUB_DF_MAP["stk_code"], "")),
                    self._fmt(r.get(SUB_DF_MAP["stk_name"], "")),
                    self._fmt(r.get(SUB_DF_MAP["stk_price"])),
                    self._fmt(r.get(SUB_DF_MAP["issue_p"])),
                    self._fmt(r.get(SUB_DF_MAP["conv_p"])),
                    self._fmt(r.get(SUB_DF_MAP["conv_val"])),
                    self._fmt(r.get(SUB_DF_MAP["premium"])),
                    self._fmt(r.get(SUB_DF_MAP["match_code"], "")),
                    self._fmt(r.get(SUB_DF_MAP["uplimit"])),
                ), tags=(tag,))
                sub_n += 1
        self.lbl_sub_count.config(text=f"共 {sub_n} 只")

        # 渲染上市表
        list_n = 0
        if self._list_df is not None:
            for _, r in self._list_df.iterrows():
                premium = r.get("可转债溢价率(%)")
                chg = r.get("首日涨幅(%)")
                try:
                    pv = float(premium)
                    tags = ["premium_pos" if pv > 0 else "premium_neg"]
                except Exception:
                    tags = []
                try:
                    if float(chg) >= 20:
                        tags.append("chg_big")
                except Exception:
                    pass
                self._list_tree.insert("", tk.END, values=(
                    self._fmt(r.get(LIST_DF_MAP["cb_code"], "")),
                    self._fmt(r.get(LIST_DF_MAP["cb_name"], "")),
                    self._fmt(r.get(LIST_DF_MAP["list_date"], "")),
                    self._fmt(r.get(LIST_DF_MAP["stk_code"], "")),
                    self._fmt(r.get(LIST_DF_MAP["stk_name"], "")),
                    self._fmt(r.get(LIST_DF_MAP["stk_price"])),
                    self._fmt(r.get(LIST_DF_MAP["issue_p"])),
                    self._fmt(r.get(LIST_DF_MAP["conv_p"])),
                    self._fmt(r.get(LIST_DF_MAP["conv_val"])),
                    self._fmt(r.get(LIST_DF_MAP["open_p"])),
                    self._fmt(r.get(LIST_DF_MAP["premium"])),
                    self._fmt(r.get(LIST_DF_MAP["chg_pct"])),
                ), tags=tuple(tags))
                list_n += 1
        self.lbl_list_count.config(text=f"共 {list_n} 只")
        self._log(f"渲染完成：申购 {sub_n} 只，上市 {list_n} 只")

    # ---------------- 导出 ----------------
    def _on_export(self, which):
        df = self._sub_df if which == "sub" else self._list_df
        name = "申购表" if which == "sub" else "上市表"
        if df is None or df.empty:
            messagebox.showwarning("提示", f"没有可导出的{name}数据，请先刷新")
            return
        default_name = f"cbond_{which}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            title=f"导出可转债{name}CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            df.to_csv(path, index=False, encoding="utf-8-sig")
            self._log(f"已导出 {name} {len(df)} 条 → {path}")
            messagebox.showinfo("成功", f"已导出 {name} {len(df)} 条到：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
