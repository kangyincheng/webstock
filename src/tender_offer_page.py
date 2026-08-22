"""要约收购页面（A 股要约 / 港股要约 双表）。

布局：
  ┌──────────────────────────────────────────────┐
  │ 标题 / 副标题                                   │
  ├──────────────────────────────────────────────┤
  │ 参数卡：[刷新数据] [导出A股要约CSV]             │
  │          [导出港股要约CSV]                     │
  ├──────────────────────────────────────────────┤
  │ 进度日志                                        │
  ├──────────────────────────────────────────────┤
  │ 【表1：A 股要约】                                │
  │   股票名称 / 股票代码 / 当前股价 / 要约价 /     │
  │   要约溢价(%) / 要约比例(%) / 要约开始日期 /    │
  │   要约结束日期                                  │
  ├──────────────────────────────────────────────┤
  │ 【表2：港股要约】                                │
  │   (相同列)                                      │
  └──────────────────────────────────────────────┘
"""
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext, messagebox, filedialog

import pandas as pd

from .tender_offer_analyzer import TenderOfferAnalyzer


# 两表统一列配置（A 股、港股共用同一套列结构）
COLUMNS = [
    ("name",     "股票名称",     110, tk.CENTER, False),
    ("code",     "股票代码",     110, tk.CENTER, False),
    ("cur_p",    "当前股价",      90, tk.E,      True),
    ("offer_p",  "要约价",        90, tk.E,      True),
    ("premium",  "要约溢价(%)",  100, tk.E,      True),
    ("ratio",    "要约比例(%)",  100, tk.E,      True),
    ("start_dt", "要约开始日期",  115, tk.CENTER, False),
    ("end_dt",   "要约结束日期",  115, tk.CENTER, False),
]
DF_MAP = {
    "name": "股票名称", "code": "股票代码", "cur_p": "当前股价",
    "offer_p": "要约价", "premium": "要约溢价(%)", "ratio": "要约比例(%)",
    "start_dt": "要约开始日期", "end_dt": "要约结束日期",
}


def _setup_tree_style():
    style = ttk.Style()
    style.configure("Treeview.Heading",
                    font=("Microsoft YaHei UI", 10, "bold"),
                    background="#F2F3F5", foreground="#1F2329")
    style.configure("Treeview",
                    font=("Microsoft YaHei UI", 10),
                    rowheight=26)


class TenderOfferPage:
    """要约收购页面（双表：A 股要约 + 港股要约）。

    default_tab:  'a' 页面加载并渲染后，滚动到 A 股要约表顶部；
                  'hk' 则滚动到港股要约表顶部；
                  菜单「A股要约」-> 'a'；「港股要约」-> 'hk'。
    """

    def __init__(self, parent, default_tab="a"):
        self.parent = parent
        self.default_tab = default_tab
        self.analyzer = TenderOfferAnalyzer(data_dir=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

        self._a_df = None
        self._hk_df = None
        self._loading = False

        self._build_ui()
        # 渲染完成（after 回调内部）按 default_tab 滚动到对应表
        self.parent.after(600, self._scroll_to_default)

    # ---------------- 滚动定位到默认表 ----------------
    def _scroll_to_default(self):
        try:
            # 通过在其父 Frame 里 yview_moveto 无法精确跨多个卡片，
            # 改为用 Canvas 式的滚动（当前页面是直接 pack 多个卡片进 parent，
            # parent 外面包 _content，_content 不滚动；所以用标签定位）
            target = self._hk_card if self.default_tab == "hk" else self._a_card
            # 最可靠的做法：把目标表对应的卡片 lift 到顶部（不动其它）。
            # 为了仍保留「上下双表」观感，这里用 focus + 色闪提示
            try:
                target.config(highlightbackground="#1677FF", highlightthickness=3)
                self.parent.after(
                    1400,
                    lambda: target.config(
                        highlightbackground="#E5E6EB", highlightthickness=1))
            except Exception:
                pass
        except Exception:
            pass

    # ---------------- UI 构造 ----------------
    def _build_ui(self):
        tk.Label(
            self.parent, text="要约收购",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#F5F6F7", fg="#1F2329", anchor="w"
        ).pack(fill=tk.X, padx=16, pady=(12, 4))

        tk.Label(
            self.parent,
            text="查看当前将要或正在进行要约收购的 A 股与港股，包含要约价、溢价率、要约比例与起止日期",
            font=("Microsoft YaHei UI", 10),
            bg="#F5F6F7", fg="#86909C", anchor="w"
        ).pack(fill=tk.X, padx=16, pady=(0, 8))

        self._build_param_card()
        self._build_log_card()
        self._build_a_card()
        self._build_hk_card()

        self._log("准备就绪，点击「刷新数据」获取最新要约收购信息")
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

        self.btn_export_a = tk.Button(
            row, text="导出 A 股要约 CSV", command=lambda: self._on_export("a"),
            bg="#FFFFFF", fg="#1677FF", relief="flat",
            activebackground="#F2F3F5", activeforeground="#1677FF",
            font=("Microsoft YaHei UI", 10),
            padx=12, pady=2, cursor="hand2",
            highlightbackground="#1677FF", highlightthickness=1)
        self.btn_export_a.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_export_hk = tk.Button(
            row, text="导出 港股要约 CSV", command=lambda: self._on_export("hk"),
            bg="#FFFFFF", fg="#1677FF", relief="flat",
            activebackground="#F2F3F5", activeforeground="#1677FF",
            font=("Microsoft YaHei UI", 10),
            padx=12, pady=2, cursor="hand2",
            highlightbackground="#1677FF", highlightthickness=1)
        self.btn_export_hk.pack(side=tk.LEFT)

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

    def _build_a_card(self):
        self._a_card = tk.Frame(self.parent, bg="#FFFFFF",
                                highlightbackground="#E5E6EB", highlightthickness=1)
        card = self._a_card
        card.pack(fill=tk.BOTH, expand=True, padx=16, pady=4)
        header = tk.Frame(card, bg="#FFFFFF")
        header.pack(fill=tk.X, padx=12, pady=(8, 0))
        tk.Label(header, text="🇨🇳  A 股要约（正将要或正在要约收购）",
                 bg="#FFFFFF", font=("Microsoft YaHei UI", 11, "bold"),
                 fg="#1677FF").pack(side=tk.LEFT)
        self.lbl_a_count = tk.Label(header, text="", bg="#FFFFFF",
                                    font=("Microsoft YaHei UI", 9),
                                    fg="#86909C")
        self.lbl_a_count.pack(side=tk.RIGHT)
        self._a_tree = self._build_tree(card, height=9)
        self._config_tags(self._a_tree)

    def _build_hk_card(self):
        self._hk_card = tk.Frame(self.parent, bg="#FFFFFF",
                                 highlightbackground="#E5E6EB", highlightthickness=1)
        card = self._hk_card
        card.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 16))
        header = tk.Frame(card, bg="#FFFFFF")
        header.pack(fill=tk.X, padx=12, pady=(8, 0))
        tk.Label(header, text="🇭🇰  港股要约（正将要或正在要约收购）",
                 bg="#FFFFFF", font=("Microsoft YaHei UI", 11, "bold"),
                 fg="#F5222D").pack(side=tk.LEFT)
        self.lbl_hk_count = tk.Label(header, text="", bg="#FFFFFF",
                                     font=("Microsoft YaHei UI", 9),
                                     fg="#86909C")
        self.lbl_hk_count.pack(side=tk.RIGHT)
        self._hk_tree = self._build_tree(card, height=7)
        self._config_tags(self._hk_tree)

    def _build_tree(self, parent, height):
        container = tk.Frame(parent, bg="#FFFFFF")
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        _setup_tree_style()

        ysb = ttk.Scrollbar(container, orient="vertical")
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb = ttk.Scrollbar(container, orient="horizontal")
        xsb.pack(side=tk.BOTTOM, fill=tk.X)

        col_keys = tuple(k for k, *_ in COLUMNS)
        tree = ttk.Treeview(container, columns=col_keys, show="headings",
                            height=height,
                            yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        for key, label, w, anchor, _ in COLUMNS:
            tree.heading(key, text=label)
            tree.column(key, width=w, anchor=anchor, minwidth=50)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.config(command=tree.yview)
        xsb.config(command=tree.xview)
        return tree

    def _config_tags(self, tree):
        # 要约溢价高：浅红；折价（负溢价）：浅绿；比例高：深黄
        tree.tag_configure("prem_high", background="#FFF1F0")   # 溢价 ≥ 15%
        tree.tag_configure("prem_low",  background="#F6FFED")   # 折价 < 0
        tree.tag_configure("ratio_high", background="#FFF7E6")  # 要约比例 ≥ 50%
        tree.tag_configure("ending",   background="#E6FFFB")   # 距离结束 ≤ 5 个交易日

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
        self._log("开始获取 A 股 / 港股要约收购数据 ...")
        t = threading.Thread(target=self._refresh_thread, daemon=True)
        t.start()

    def _refresh_thread(self):
        try:
            a_df, hk_df = self.analyzer.fetch_tender_offers(
                progress_callback=self._log)
            self._a_df = a_df if (a_df is not None and not a_df.empty) else None
            self._hk_df = hk_df if (hk_df is not None and not hk_df.empty) else None
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
        for t in (self._a_tree, self._hk_tree):
            for item in t.get_children():
                t.delete(item)
        self.lbl_a_count.config(text="")
        self.lbl_hk_count.config(text="")

    @staticmethod
    def _fmt(v):
        if v is None:
            return ""
        if isinstance(v, float) and pd.isna(v):
            return ""
        if isinstance(v, float):
            return f"{v:.2f}"
        return v

    @staticmethod
    def _is_ending(end_dt_str):
        try:
            end = datetime.strptime(end_dt_str, "%Y-%m-%d").date()
            today = datetime.now().date()
            return (end - today).days <= 5 and (end - today).days >= -30  # 临近或刚结束
        except Exception:
            return False

    def _render_df(self, tree, df, label):
        n = 0
        if df is None:
            return 0
        for _, r in df.iterrows():
            tags = []
            try:
                prem = float(r.get("要约溢价(%)"))
                if prem >= 15:
                    tags.append("prem_high")
                elif prem < 0:
                    tags.append("prem_low")
            except Exception:
                pass
            try:
                ratio = float(r.get("要约比例(%)"))
                if ratio >= 50:
                    tags.append("ratio_high")
            except Exception:
                pass
            if self._is_ending(str(r.get("要约结束日期", ""))):
                tags.append("ending")
            tree.insert("", tk.END, values=(
                self._fmt(r.get(DF_MAP["name"], "")),
                self._fmt(r.get(DF_MAP["code"], "")),
                self._fmt(r.get(DF_MAP["cur_p"])),
                self._fmt(r.get(DF_MAP["offer_p"])),
                self._fmt(r.get(DF_MAP["premium"])),
                self._fmt(r.get(DF_MAP["ratio"])),
                self._fmt(r.get(DF_MAP["start_dt"], "")),
                self._fmt(r.get(DF_MAP["end_dt"], "")),
            ), tags=tuple(tags))
            n += 1
        label.config(text=f"共 {n} 条")
        return n

    def _render_result(self):
        a_n = self._render_df(self._a_tree, self._a_df, self.lbl_a_count)
        hk_n = self._render_df(self._hk_tree, self._hk_df, self.lbl_hk_count)
        self._log(f"渲染完成：A 股要约 {a_n} 条，港股要约 {hk_n} 条")

    # ---------------- 导出 ----------------
    def _on_export(self, which):
        df = self._a_df if which == "a" else self._hk_df
        name = "A股要约" if which == "a" else "港股要约"
        if df is None or df.empty:
            messagebox.showwarning("提示", f"没有可导出的{name}数据，请先刷新")
            return
        default_name = f"tender_offer_{which}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            title=f"导出{name}CSV",
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
