"""自选股页面。

布局：
  ┌──────────────────────────────────────────────────┐
  │ 标题：自选股                                      │
  ├──────────────────────────────────────────────────┤
  │ 参数栏：[添加自选股] [编辑] [删除] [刷新行情]     │
  │         [导出CSV] [立即检查到期]                  │
  ├──────────────────────────────────────────────────┤
  │ 进度日志                                          │
  ├──────────────────────────────────────────────────┤
  │ 筛选栏：[代码/名称____] [筛选] [重置]             │
  ├──────────────────────────────────────────────────┤
  │ 自选股表格（点击列头排序）：                       │
  │  名称 / 代码 / 买入日期 / 买入价 / 当前价 /       │
  │  收益(%) / 备注 / 到期事件 / 到期日期              │
  │  ※ 有到期事件的行红色底重点显示                   │
  └──────────────────────────────────────────────────┘

存储：本地 JSON 文件 data/favorites.json
事件到期：后台线程每 60 秒检查，到期弹框提醒 + 红色高亮
当前价：通过 baostock 批量拉取最新收盘价
"""
import json
import os
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk, scrolledtext, messagebox, filedialog

import pandas as pd


# Treeview 列定义（col_key, 表头, 宽度, 对齐, 是否数值列）
TREE_COLUMNS = [
    ("name",          "股票名称",   100, tk.W,      False),
    ("code",          "代码",       100, tk.CENTER, False),
    ("buy_date",      "买入日期",   100, tk.CENTER, False),
    ("buy_price",     "买入价",      90, tk.E,      True),
    ("current_price", "当前价",      90, tk.E,      True),
    ("profit_pct",    "收益(%)",    100, tk.E,      True),
    ("note",          "备注",      200, tk.W,      False),
    ("event_title",   "到期事件",  160, tk.W,      False),
    ("event_due",     "到期日期",  110, tk.CENTER, False),
]
NUMERIC_COLS = {"buy_price", "current_price", "profit_pct"}


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _parse_date(s):
    """解析 YYYY-MM-DD，失败返回 None。"""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


class FavoriteStocksPage:
    """自选股页面。"""

    CHECK_INTERVAL = 60  # 后台检查间隔（秒）

    def __init__(self, parent):
        self.parent = parent
        self.data_dir = os.path.join(_project_root(), "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.json_path = os.path.join(self.data_dir, "favorites.json")

        # 自选股列表（dict 列表）
        self._stocks = []
        # 当前展示 DataFrame
        self._display_df = None
        self._loading = False
        # 已提醒事件集合（避免重复弹框），key = code|due_date|title
        self._reminded = set()

        # 筛选
        self.filter_var = tk.StringVar(value="")

        # 排序状态
        self._last_sort_col = "buy_date"
        self._last_sort_order = "desc"

        self._build_ui()
        self._load_data()
        self._log("准备就绪。点击「添加自选股」录入持仓，事件到期会自动弹框提醒。")
        # 启动后台到期检查线程
        self._stop_flag = threading.Event()
        self._checker = threading.Thread(
            target=self._check_loop, daemon=True)
        self._checker.start()

    # ---------------- 布局 ----------------
    def _build_ui(self):
        tk.Label(
            self.parent, text="自选股",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#F5F6F7", fg="#1F2329", anchor="w"
        ).pack(fill=tk.X, padx=16, pady=(12, 4))
        tk.Label(
            self.parent,
            text="本地管理自选股：买入日期 / 买入价 / 当前价 / 收益 / 备注 / 事件到期提醒（红色高亮）",
            font=("Microsoft YaHei UI", 10),
            bg="#F5F6F7", fg="#86909C", anchor="w"
        ).pack(fill=tk.X, padx=16, pady=(0, 8))

        # 参数栏
        param_card = tk.Frame(self.parent, bg="#FFFFFF",
                              highlightbackground="#E5E6EB", highlightthickness=1)
        param_card.pack(fill=tk.X, padx=16, pady=4)
        row = tk.Frame(param_card, bg="#FFFFFF")
        row.pack(fill=tk.X, padx=16, pady=10)

        tk.Button(row, text="添加自选股", command=self._on_add,
                  bg="#1677FF", fg="white", relief="flat",
                  activebackground="#4096FF", activeforeground="white",
                  font=("Microsoft YaHei UI", 10, "bold"),
                  padx=12, pady=2, cursor="hand2").pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(row, text="编辑", command=self._on_edit,
                  bg="#FFFFFF", fg="#1677FF", relief="flat",
                  font=("Microsoft YaHei UI", 10),
                  padx=12, pady=2, cursor="hand2",
                  highlightbackground="#1677FF", highlightthickness=1
                  ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(row, text="删除", command=self._on_delete,
                  bg="#FFFFFF", fg="#CF1322", relief="flat",
                  font=("Microsoft YaHei UI", 10),
                  padx=12, pady=2, cursor="hand2",
                  highlightbackground="#CF1322", highlightthickness=1
                  ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(row, text="刷新行情", command=self._on_refresh_price,
                  bg="#FFFFFF", fg="#1677FF", relief="flat",
                  font=("Microsoft YaHei UI", 10),
                  padx=12, pady=2, cursor="hand2",
                  highlightbackground="#1677FF", highlightthickness=1
                  ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(row, text="立即检查到期", command=self._check_now,
                  bg="#FFFFFF", fg="#FA8C16", relief="flat",
                  font=("Microsoft YaHei UI", 10),
                  padx=12, pady=2, cursor="hand2",
                  highlightbackground="#FA8C16", highlightthickness=1
                  ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(row, text="导出 CSV", command=self._on_export,
                  bg="#FFFFFF", fg="#4E5969", relief="flat",
                  font=("Microsoft YaHei UI", 10),
                  padx=12, pady=2, cursor="hand2",
                  highlightbackground="#C8CCD2", highlightthickness=1
                  ).pack(side=tk.LEFT, padx=(0, 8))

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
        tk.Label(row, text="筛选（代码/名称）：", bg="#FFFFFF",
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
        tk.Label(table_card, text="自选股列表（红色行=有事件到期，双击行可编辑）",
                 bg="#FFFFFF",
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
        # 红色高亮（到期行）
        self.tree.tag_configure("due", background="#FFF1F0", foreground="#CF1322")
        # 普通行间隔
        self.tree.tag_configure("even", background="#FFFFFF")
        self.tree.tag_configure("odd", background="#FAFBFC")

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.config(command=self.tree.yview)
        xsb.config(command=self.tree.xview)
        # 双击编辑
        self.tree.bind("<Double-Button-1>", lambda e: self._on_edit())

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

    # ---------------- 数据持久化 ----------------
    def _load_data(self):
        if not os.path.exists(self.json_path):
            self._stocks = []
            self._render()
            return
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._stocks = data.get("stocks", []) if isinstance(data, dict) else []
        except Exception as e:
            self._log(f"读取 favorites.json 失败：{e}")
            self._stocks = []
        self._render()

    def _save_data(self):
        try:
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump({"stocks": self._stocks}, f,
                          ensure_ascii=False, indent=2)
        except Exception as e:
            self._log(f"保存 favorites.json 失败：{e}")

    # ---------------- 添加 / 编辑 / 删除 ----------------
    def _on_add(self):
        dlg = StockEditDialog(self.parent, title="添加自选股")
        self.parent.wait_window(dlg.top)
        if dlg.result is not None:
            # 去重：同 code 不允许重复
            codes = {s.get("code") for s in self._stocks}
            if dlg.result.get("code") in codes:
                messagebox.showwarning("重复", f"已存在该股票：{dlg.result.get('code')}")
                return
            dlg.result["current_price"] = dlg.result.get("current_price") or None
            self._stocks.append(dlg.result)
            self._save_data()
            self._log(f"已添加：{dlg.result.get('name','')} {dlg.result.get('code')}")
            self._render()

    def _on_edit(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一行")
            return
        try:
            idx = int(sel[0][1:])  # iid 形如 "r5"
        except Exception:
            idx = -1
        if idx < 0 or idx >= len(self._stocks):
            messagebox.showinfo("提示", "无法定位该行")
            return
        stock = self._stocks[idx]
        dlg = StockEditDialog(self.parent, title="编辑自选股", stock=stock)
        self.parent.wait_window(dlg.top)
        if dlg.result is not None:
            dlg.result["current_price"] = dlg.result.get("current_price") or stock.get("current_price")
            self._stocks[idx] = dlg.result
            self._save_data()
            self._log(f"已更新：{dlg.result.get('name','')} {dlg.result.get('code')}")
            self._render()

    def _on_delete(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一行")
            return
        try:
            idx = int(sel[0][1:])  # iid 形如 "r5"
        except Exception:
            idx = -1
        if idx < 0 or idx >= len(self._stocks):
            return
        stock = self._stocks[idx]
        if not messagebox.askyesno("确认删除",
                                   f"确认删除自选股？\n{stock.get('name','')} {stock.get('code','')}"):
            return
        self._stocks.pop(idx)
        self._save_data()
        self._log(f"已删除：{stock.get('name','')} {stock.get('code','')}")
        self._render()

    # ---------------- 刷新行情（baostock）----------------
    def _on_refresh_price(self):
        if self._loading:
            messagebox.showinfo("提示", "刷新中，请稍候")
            return
        if not self._stocks:
            messagebox.showinfo("提示", "暂无自选股，请先添加")
            return
        self._loading = True
        self.status_hint.config(text="刷新行情中...")
        t = threading.Thread(target=self._refresh_thread, daemon=True)
        t.start()

    def _refresh_thread(self):
        try:
            import baostock as bs
        except ImportError:
            self.parent.after(0, lambda: messagebox.showerror(
                "错误", "未安装 baostock，请执行：pip install baostock"))
            return
        try:
            lg = bs.login()
            if lg.error_code != "0":
                raise RuntimeError(f"baostock 登录失败：{lg.error_msg}")
            end_date = _today_str()
            start_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
            updated = 0
            total = len(self._stocks)
            for i, stock in enumerate(self._stocks, 1):
                code = stock.get("code", "")
                if not code:
                    continue
                try:
                    rs = bs.query_history_k_data_plus(
                        code, "date,close",
                        start_date=start_date, end_date=end_date,
                        frequency="d", adjustflag="2")
                    rows = []
                    while rs.error_code == "0" and rs.next():
                        rows.append(rs.get_row_data())
                    if rows:
                        last_close = float(rows[-1][1])
                        stock["current_price"] = round(last_close, 3)
                        updated += 1
                except Exception:
                    pass
                self.parent.after(0, lambda i=i, t=total: self.status_hint.config(
                    text=f"刷新行情 {i}/{t}"))
                time.sleep(0.05)
            bs.logout()
            self.parent.after(0, lambda: self._log(f"行情刷新完成，更新 {updated}/{total} 只"))
        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: messagebox.showerror("刷新失败", err))
            self.parent.after(0, lambda: self._log(f"刷新失败：{err}"))
        finally:
            self.parent.after(0, self._refresh_done)

    def _refresh_done(self):
        self._loading = False
        self.status_hint.config(text="")
        self._save_data()
        self._render()

    # ---------------- 到期检查 ----------------
    def _check_loop(self):
        """后台循环：每 CHECK_INTERVAL 秒检查一次到期事件。"""
        while not self._stop_flag.is_set():
            try:
                # 页面已销毁则退出线程，避免持续报错
                if not self.parent.winfo_exists():
                    return
                self._scan_due(silent=True)
            except Exception:
                pass
            # 分段睡眠，便于及时退出
            for _ in range(self.CHECK_INTERVAL):
                if self._stop_flag.is_set():
                    return
                time.sleep(1)

    def _check_now(self):
        """立即检查到期事件（手动触发，会弹框）。"""
        self._scan_due(silent=False)
        self._render()

    def _scan_due(self, silent=False):
        """扫描所有自选股的到期事件。

        silent=True 时，仅更新表格高亮（不弹框，除非首次发现到期）；
        silent=False 时（手动触发），所有到期事件都弹框提醒。
        """
        today = datetime.now().date()
        due_list = []  # [(stock, event)]
        for stock in self._stocks:
            for ev in stock.get("events", []) or []:
                due = _parse_date(ev.get("due_date", ""))
                if due is None:
                    continue
                if due <= today:
                    key = f"{stock.get('code','')}|{ev.get('due_date','')}|{ev.get('title','')}"
                    due_list.append((stock, ev, key))

        # 弹框提醒
        if due_list:
            msgs = []
            new_found = False
            for stock, ev, key in due_list:
                if key not in self._reminded:
                    new_found = True
                    self._reminded.add(key)
                msgs.append(
                    f"• {stock.get('name','')}（{stock.get('code','')}）"
                    f"：{ev.get('title','')}  到期日 {ev.get('due_date','')}")
            if (not silent and due_list) or new_found:
                text = "\n".join(msgs)
                self.parent.after(0, lambda t=text: messagebox.showwarning(
                    "事件到期提醒", "以下自选股事件已到期：\n\n" + t))
                self.parent.after(0, lambda: self._log(
                    f"发现 {len(due_list)} 条到期事件，已弹框提醒"))
        else:
            if not silent:
                self.parent.after(0, lambda: messagebox.showinfo(
                    "到期检查", "暂无到期事件"))
            self.parent.after(0, lambda: self._log("到期检查完成：无到期事件"))

    # ---------------- 渲染 ----------------
    def _build_display_df(self):
        """由 self._stocks 构造展示用 DataFrame。"""
        rows = []
        for idx, stock in enumerate(self._stocks):
            buy_price = stock.get("buy_price")
            cur = stock.get("current_price")
            # 收益率
            profit = None
            try:
                bp = float(buy_price) if buy_price not in (None, "") else None
                cp = float(cur) if cur not in (None, "") else None
                if bp and cp and bp > 0:
                    profit = round((cp - bp) / bp * 100.0, 2)
            except Exception:
                profit = None
            # 取最近到期的到期事件
            today = datetime.now().date()
            due_events = []
            for ev in stock.get("events", []) or []:
                d = _parse_date(ev.get("due_date", ""))
                if d is not None and d <= today:
                    due_events.append((d, ev))
            event_title = ""
            event_due = ""
            if due_events:
                due_events.sort(key=lambda x: x[0])
                d, ev = due_events[0]
                event_title = ev.get("title", "")
                event_due = ev.get("due_date", "")
            rows.append({
                "name": stock.get("name", ""),
                "code": stock.get("code", ""),
                "buy_date": stock.get("buy_date", ""),
                "buy_price": buy_price,
                "current_price": cur,
                "profit_pct": profit,
                "note": stock.get("note", ""),
                "event_title": event_title,
                "event_due": event_due,
                "_due": bool(due_events),
                "_orig_idx": idx,
            })
        df = pd.DataFrame(rows) if rows else None
        return df

    def _render(self):
        df = self._build_display_df()
        if df is not None:
            # 应用筛选
            ft = self.filter_var.get().strip()
            if ft:
                mask = self._build_filter_mask(df, ft)
                df = df[mask]
                self.filter_hint.config(text=f"已筛选：显示 {len(df)} 条")
            else:
                self.filter_hint.config(text="")
            # 应用排序
            if self._last_sort_col and not df.empty:
                asc = (self._last_sort_order == "asc")
                df = df.sort_values(by=self._last_sort_col, ascending=asc,
                                    kind="mergesort").reset_index(drop=True)
        self._display_df = df
        # 渲染
        for item in self.tree.get_children():
            self.tree.delete(item)
        if df is None or df.empty:
            self.status_hint.config(text=f"共 0 只自选股")
            return
        for i, r in df.iterrows():
            # 原始索引（用于编辑/删除定位），用 iid 存储，tags 只用于样式
            orig_idx = int(r.get("_orig_idx", 0))
            is_due = bool(r.get("_due", False))
            tag = "due" if is_due else ("even" if i % 2 == 0 else "odd")
            iid = f"r{orig_idx}"
            self.tree.insert("", tk.END, iid=iid, values=(
                r.get("name", ""),
                r.get("code", ""),
                r.get("buy_date", ""),
                r.get("buy_price", ""),
                r.get("current_price", ""),
                r.get("profit_pct", ""),
                r.get("note", ""),
                r.get("event_title", ""),
                r.get("event_due", ""),
            ), tags=(tag,))
        self.status_hint.config(text=f"共 {len(df)} 只自选股")

    @staticmethod
    def _build_filter_mask(df, text):
        text = text.strip()
        if not text:
            return pd.Series(True, index=df.index)
        m_code = df["code"].astype(str).str.contains(text, case=False, na=False)
        m_name = df["name"].astype(str).str.contains(text, case=False, na=False)
        return m_code | m_name

    def _on_filter(self):
        if not self._stocks:
            messagebox.showinfo("提示", "暂无自选股")
            return
        self._render()
        self._log(f"应用筛选：{self.filter_var.get().strip() or '(空)'}")

    def _on_reset_filter(self):
        self.filter_var.set("")
        self._render()
        self._log("已重置筛选")

    # ---------------- 列头排序 ----------------
    def _on_header_click(self, col_key):
        if not self._stocks:
            return
        if self._last_sort_col == col_key:
            self._last_sort_order = "desc" if self._last_sort_order == "asc" else "asc"
        else:
            self._last_sort_col = col_key
            self._last_sort_order = "desc" if col_key in NUMERIC_COLS else "asc"
        self._render()

    # ---------------- 导出 ----------------
    def _on_export(self):
        if self._display_df is None or self._display_df.empty:
            messagebox.showinfo("提示", "暂无数据可导出")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
            initialfile=f"favorites_{_today_str().replace('-','')}.csv")
        if not path:
            return
        try:
            df = self._display_df.drop(columns=["_due", "_orig_idx"], errors="ignore")
            df.to_csv(path, index=False, encoding="utf-8-sig")
            self._log(f"已导出：{path}")
            messagebox.showinfo("导出成功", f"已保存到：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))


class StockEditDialog:
    """自选股添加/编辑弹框（Toplevel）。

    字段：代码、名称、买入日期、买入价、当前价、备注、事件列表（标题+到期日期）
    """

    def __init__(self, parent, title="自选股", stock=None):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.geometry("460x620")
        self.top.resizable(False, False)
        self.top.transient(parent)
        self.top.grab_set()

        # 字段变量
        self.code_var = tk.StringVar(value=stock.get("code", "") if stock else "")
        self.name_var = tk.StringVar(value=stock.get("name", "") if stock else "")
        self.buy_date_var = tk.StringVar(
            value=stock.get("buy_date", _today_str()) if stock else _today_str())
        self.buy_price_var = tk.StringVar(
            value=str(stock.get("buy_price", "")) if stock and stock.get("buy_price") is not None else "")
        self.current_price_var = tk.StringVar(
            value=str(stock.get("current_price", "")) if stock and stock.get("current_price") is not None else "")
        self.note_var = tk.StringVar(value=stock.get("note", "") if stock else "")
        # 事件列表：[(title_var, due_var), ...]
        self._events = []
        if stock and stock.get("events"):
            for ev in stock["events"]:
                self._events.append((
                    tk.StringVar(value=ev.get("title", "")),
                    tk.StringVar(value=ev.get("due_date", "")),
                ))

        self._build_ui()
        if self._events:
            self._render_events()

    def _build_ui(self):
        container = tk.Frame(self.top, bg="#FFFFFF", padx=20, pady=16)
        container.pack(fill=tk.BOTH, expand=True)

        # 基本字段
        form = tk.Frame(container, bg="#FFFFFF")
        form.pack(fill=tk.X)

        self._add_field(form, "股票代码 *", self.code_var, 0,
                        hint="baostock 格式，如 sh.600036 / sz.000001")
        self._add_field(form, "股票名称", self.name_var, 1)
        self._add_field(form, "买入日期 *", self.buy_date_var, 2,
                        hint="YYYY-MM-DD")
        self._add_field(form, "买入价 *", self.buy_price_var, 3,
                        hint="数字，如 35.20")
        self._add_field(form, "当前价", self.current_price_var, 4,
                        hint="可留空，点「刷新行情」自动获取")
        self._add_field(form, "备注", self.note_var, 5)

        # 事件区
        evt_frame = tk.Frame(container, bg="#FFFFFF")
        evt_frame.pack(fill=tk.X, pady=(12, 0))
        tk.Label(evt_frame, text="自定义事件（到期提醒）",
                 bg="#FFFFFF", fg="#1F2329",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        tk.Label(evt_frame, text="到期日 <= 今日时触发弹框 + 红色高亮",
                 bg="#FFFFFF", fg="#86909C",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        # 事件列表容器（可滚动）
        evt_list_wrap = tk.Frame(container, bg="#FFFFFF",
                                 highlightbackground="#E5E6EB", highlightthickness=1)
        evt_list_wrap.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.evt_list = tk.Frame(evt_list_wrap, bg="#FFFFFF")
        self.evt_list.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 事件操作按钮
        evt_btns = tk.Frame(container, bg="#FFFFFF")
        evt_btns.pack(fill=tk.X, pady=(6, 0))
        tk.Button(evt_btns, text="+ 添加事件", command=self._add_event,
                  bg="#1677FF", fg="white", relief="flat",
                  font=("Microsoft YaHei UI", 9),
                  padx=10, pady=1, cursor="hand2").pack(side=tk.LEFT)

        # 底部按钮
        btns = tk.Frame(self.top, bg="#F5F6F7")
        btns.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Button(btns, text="取消", command=self._on_cancel,
                  bg="#FFFFFF", fg="#4E5969", relief="flat",
                  font=("Microsoft YaHei UI", 10),
                  padx=20, pady=6, cursor="hand2",
                  highlightbackground="#C8CCD2", highlightthickness=1
                  ).pack(side=tk.RIGHT, padx=(8, 16), pady=12)
        tk.Button(btns, text="保存", command=self._on_save,
                  bg="#1677FF", fg="white", relief="flat",
                  font=("Microsoft YaHei UI", 10, "bold"),
                  padx=20, pady=6, cursor="hand2").pack(side=tk.RIGHT, pady=12)

    def _add_field(self, parent, label, var, row, hint=""):
        tk.Label(parent, text=label, bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10),
                 fg="#4E5969").grid(row=row * 2, column=0, sticky="w", pady=(8 if row else 0, 0))
        tk.Entry(parent, textvariable=var, width=36,
                 font=("Microsoft YaHei UI", 10),
                 bg="#FAFBFC", relief="flat",
                 highlightbackground="#C8CCD2", highlightthickness=1
                 ).grid(row=row * 2 + 1, column=0, sticky="ew", pady=(2, 0))
        if hint:
            tk.Label(parent, text=hint, bg="#FFFFFF",
                     font=("Microsoft YaHei UI", 8),
                     fg="#86909C").grid(row=row * 2 + 1, column=1, sticky="w", padx=(8, 0))
        parent.grid_columnconfigure(0, weight=1)

    # ---------------- 事件编辑 ----------------
    def _add_event(self):
        self._events.append((tk.StringVar(value=""), tk.StringVar(value="")))
        self._render_events()

    def _render_events(self):
        for w in self.evt_list.winfo_children():
            w.destroy()
        if not self._events:
            tk.Label(self.evt_list, text="（暂无事件，点「+ 添加事件」）",
                     bg="#FFFFFF", fg="#86909C",
                     font=("Microsoft YaHei UI", 9)).pack(anchor="w")
            return
        for i, (title_var, due_var) in enumerate(self._events):
            row = tk.Frame(self.evt_list, bg="#FFFFFF")
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=f"{i + 1}.", bg="#FFFFFF",
                     font=("Microsoft YaHei UI", 9), fg="#86909C", width=3
                     ).pack(side=tk.LEFT)
            tk.Entry(row, textvariable=title_var, width=14,
                     font=("Microsoft YaHei UI", 9),
                     bg="#FAFBFC", relief="flat",
                     highlightbackground="#C8CCD2", highlightthickness=1
                     ).pack(side=tk.LEFT, padx=(0, 4))
            tk.Entry(row, textvariable=due_var, width=12,
                     font=("Microsoft YaHei UI", 9),
                     bg="#FAFBFC", relief="flat",
                     highlightbackground="#C8CCD2", highlightthickness=1
                     ).pack(side=tk.LEFT, padx=(0, 4))
            tk.Label(row, text="YYYY-MM-DD", bg="#FFFFFF",
                     font=("Microsoft YaHei UI", 8), fg="#86909C"
                     ).pack(side=tk.LEFT, padx=(0, 6))
            btn = tk.Button(row, text="删", width=2,
                            command=lambda i=i: self._del_event(i),
                            bg="#FFFFFF", fg="#CF1322", relief="flat",
                            font=("Microsoft YaHei UI", 8),
                            cursor="hand2",
                            highlightbackground="#CF1322", highlightthickness=1)
            btn.pack(side=tk.LEFT)

    def _del_event(self, idx):
        if 0 <= idx < len(self._events):
            self._events.pop(idx)
            self._render_events()

    # ---------------- 保存 / 取消 ----------------
    def _on_save(self):
        code = self.code_var.get().strip()
        buy_date = self.buy_date_var.get().strip()
        buy_price_str = self.buy_price_var.get().strip()
        if not code:
            messagebox.showwarning("参数错误", "请填写股票代码")
            return
        if not _parse_date(buy_date):
            messagebox.showwarning("参数错误", "买入日期格式应为 YYYY-MM-DD")
            return
        try:
            buy_price = float(buy_price_str) if buy_price_str else None
            if buy_price is not None and buy_price <= 0:
                raise ValueError
        except Exception:
            messagebox.showwarning("参数错误", "买入价应为正数")
            return
        cur_str = self.current_price_var.get().strip()
        cur = None
        if cur_str:
            try:
                cur = float(cur_str)
            except Exception:
                messagebox.showwarning("参数错误", "当前价应为数字")
                return
        # 校验事件日期
        events = []
        for title_var, due_var in self._events:
            t = title_var.get().strip()
            d = due_var.get().strip()
            if not t and not d:
                continue
            if not t:
                messagebox.showwarning("参数错误", "事件标题不能为空")
                return
            if not _parse_date(d):
                messagebox.showwarning("参数错误",
                                       f"事件「{t}」的到期日期格式应为 YYYY-MM-DD")
                return
            events.append({"title": t, "due_date": d})

        self.result = {
            "code": code,
            "name": self.name_var.get().strip(),
            "buy_date": buy_date,
            "buy_price": buy_price,
            "current_price": cur,
            "note": self.note_var.get().strip(),
            "events": events,
        }
        self.top.destroy()

    def _on_cancel(self):
        self.result = None
        self.top.destroy()
