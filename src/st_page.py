"""ST 股票表现页面。

布局：
  ┌──────────────────────────────────────────────┐
  │ 参数栏：[最近__月] [摘帽前__天] [摘帽后__天]  │
  │         [开始扫描] [导出CSV]                │
  ├──────────────────────────────────────────────┤
  │ 进度日志（多行文本）                         │
  ├──────────────────────────────────────────────┤
  │ 结果表格：股票名称 / 代码 / 开始ST日期 /      │
  │           结束ST日期 / 摘帽前涨幅 / 摘帽后涨幅│
  │           / 市盈率 / 市净率 / 收盘价         │
  └──────────────────────────────────────────────┘
"""
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, scrolledtext, messagebox, filedialog

from .st_analyzer import STAnalyzer


class STPerformancePage:
    """ST 股票表现页面。

    使用方式：
        page = tk.Frame(parent)
        STPerformancePage(page)
    """

    def __init__(self, parent):
        self.parent = parent
        self.analyzer = STAnalyzer(data_dir=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))

        # 参数默认值
        self.months_var = tk.IntVar(value=10)
        self.before_var = tk.IntVar(value=30)
        self.after_var = tk.IntVar(value=30)

        # 当前结果 DataFrame
        self._result_df = None
        self._scanning = False
        self._cancel = False

        self._build_ui()

    # ---------------- 布局 ----------------
    def _build_ui(self):
        # 标题
        title = tk.Label(
            self.parent, text="ST 股票摘帽表现分析",
            font=("Microsoft YaHei UI", 14, "bold"),
            bg="#F5F6F7", fg="#1F2329", anchor="w")
        title.pack(fill=tk.X, padx=16, pady=(12, 4))

        subtitle = tk.Label(
            self.parent,
            text="扫描最近 N 个月内摘帽的 ST 股，计算摘帽前/后股价涨跌幅与估值指标",
            font=("Microsoft YaHei UI", 10),
            bg="#F5F6F7", fg="#86909C", anchor="w")
        subtitle.pack(fill=tk.X, padx=16, pady=(0, 8))

        # 参数栏（卡片样式）
        param_card = tk.Frame(self.parent, bg="#FFFFFF",
                               highlightbackground="#E5E6EB", highlightthickness=1)
        param_card.pack(fill=tk.X, padx=16, pady=4)

        row = tk.Frame(param_card, bg="#FFFFFF")
        row.pack(fill=tk.X, padx=16, pady=12)

        # 最近 N 个月
        tk.Label(row, text="最近（月）", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 4))
        tk.Entry(row, textvariable=self.months_var, width=6,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 16))

        # 摘帽前 N 天
        tk.Label(row, text="摘帽前（天）", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 4))
        tk.Entry(row, textvariable=self.before_var, width=6,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 16))

        # 摘帽后 N 天
        tk.Label(row, text="摘帽后（天）", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 4))
        tk.Entry(row, textvariable=self.after_var, width=6,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(0, 16))

        # 按钮组
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

        # 进度日志
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

        # 结果表格
        table_card = tk.Frame(self.parent, bg="#FFFFFF",
                              highlightbackground="#E5E6EB", highlightthickness=1)
        table_card.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 16))
        tk.Label(table_card, text="摘帽 ST 股列表", bg="#FFFFFF",
                 font=("Microsoft YaHei UI", 10, "bold"),
                 fg="#4E5969").pack(anchor="w", padx=12, pady=(8, 2))
        self._build_table(table_card)

        # 初始空表格提示
        self._log("准备就绪，点击「开始扫描」拉取数据")

    def _build_table(self, parent):
        columns = ("name", "code", "st_start", "st_end",
                   "pre_change", "post_change", "pe", "pb", "close")
        headers = {
            "name": "股票名称", "code": "代码", "st_start": "开始ST日期",
            "st_end": "结束ST日期", "pre_change": "摘帽前涨幅(%)",
            "post_change": "摘帽后涨幅(%)", "pe": "市盈率",
            "pb": "市净率", "close": "收盘价",
        }
        widths = {
            "name": 110, "code": 100, "st_start": 110, "st_end": 110,
            "pre_change": 120, "post_change": 120, "pe": 90, "pb": 90, "close": 90,
        }
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

        self.tree = ttk.Treeview(
            container, columns=columns, show="headings",
            yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], anchor=tk.CENTER)
        # 涨幅列右对齐
        self.tree.column("pre_change", anchor=tk.E)
        self.tree.column("post_change", anchor=tk.E)
        self.tree.column("pe", anchor=tk.E)
        self.tree.column("pb", anchor=tk.E)
        self.tree.column("close", anchor=tk.E)
        # 交替行颜色
        self.tree.tag_configure("up", background="#FFF7E6")    # 摘帽后上涨
        self.tree.tag_configure("down", background="#FFF1F0")  # 摘帽后下跌

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
        self.parent.update_idletasks()

    # ---------------- 扫描 ----------------
    def _on_scan(self):
        if self._scanning:
            messagebox.showinfo("提示", "扫描进行中，请稍候")
            return
        try:
            months = int(self.months_var.get())
            before = int(self.before_var.get())
            after = int(self.after_var.get())
            if months <= 0 or before <= 0 or after <= 0:
                raise ValueError("参数必须为正整数")
        except Exception:
            messagebox.showerror("参数错误", "请输入有效的正整数参数")
            return

        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._log(f"开始扫描：最近 {months} 月，摘帽前 {before} 天，摘帽后 {after} 天")

        self._scanning = True
        self._cancel = False
        self.btn_scan.config(text="扫描中...", state="disabled")

        # 后台线程跑分析
        t = threading.Thread(target=self._scan_thread,
                             args=(months, before, after), daemon=True)
        t.start()

    def _scan_thread(self, months, before, after):
        try:
            df = self.analyzer.scan_and_analyze(
                months_back=months, before_days=before, after_days=after,
                progress_callback=self._log)
            self._result_df = df
            self.parent.after(0, lambda: self._render_result(df))
        except Exception as e:
            self.parent.after(0, lambda: messagebox.showerror("错误", str(e)))
            self._log(f"扫描失败：{e}")
        finally:
            self.parent.after(0, self._scan_done)

    def _scan_done(self):
        self._scanning = False
        self.btn_scan.config(text="开始扫描", state="normal")

    def _render_result(self, df):
        if df is None or df.empty:
            self._log("未找到符合条件的摘帽 ST 股")
            return
        for _, r in df.iterrows():
            post_chg = r.get("摘帽后涨幅")
            tag = "up" if (post_chg is not None and post_chg >= 0) else "down"
            self.tree.insert("", tk.END, values=(
                r.get("股票名称", ""),
                r.get("代码", ""),
                r.get("开始ST日期", ""),
                r.get("结束ST日期", ""),
                r.get("摘帽前涨幅", ""),
                r.get("摘帽后涨幅", ""),
                "" if r.get("市盈率") is None else r.get("市盈率"),
                "" if r.get("市净率") is None else r.get("市净率"),
                "" if r.get("收盘价") is None else r.get("收盘价"),
            ), tags=(tag,))
        self._log(f"已展示 {len(df)} 条结果")

    # ---------------- 导出 ----------------
    def _on_export(self):
        if self._result_df is None or self._result_df.empty:
            messagebox.showwarning("提示", "没有可导出的数据，请先扫描")
            return
        default_name = f"st_uncap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(
            title="导出 CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            self._result_df.to_csv(path, index=False, encoding="utf-8-sig")
            self._log(f"已导出：{path}")
            messagebox.showinfo("成功", f"已导出：\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
