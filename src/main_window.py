"""钉钉式主窗口。

布局：
  ┌──────────────────────────────────────────────┐
  │ 顶部标题栏（应用名 + 当前模块）              │
  ├─────────┬────────────────────────────────────┤
  │ 左侧    │                                    │
  │ 导航栏  │      右侧内容区                    │
  │ (图标+  │   (点击菜单切换显示内容)           │
  │  文字)  │                                    │
  │         │                                    │
  └─────────┴────────────────────────────────────┘

- 左侧导航栏：深色背景，宽度 200px，带分隔的菜单组
- 菜单支持父子层级：父菜单点击展开/收起子菜单（▶/▼ 箭头指示）
- 「股票预测」挂在「工作台 → 股票」父菜单下，作为子菜单
- 其它菜单：占位页面，留作后续扩展（钉钉式工作台/消息/通讯录/数据看板/设置）
"""

import tkinter as tk
from tkinter import ttk


# 钉钉风格配色
COLOR_NAV_BG = "#2E2F33"          # 左侧导航栏背景（深灰）
COLOR_NAV_BG_DARKER = "#26282C"   # 菜单组标题区
COLOR_ITEM_NORMAL = "#3A3C40"     # 菜单项默认背景
COLOR_ITEM_HOVER = "#4A4D52"      # 菜单项悬停背景
COLOR_ITEM_ACTIVE = "#1677FF"     # 选中项背景（钉钉蓝）
COLOR_TEXT_NORMAL = "#C8CCD2"     # 菜单项默认文字色
COLOR_TEXT_ACTIVE = "#FFFFFF"     # 选中项文字色
COLOR_TEXT_GROUP = "#7A7F87"      # 菜单组标题色
COLOR_TOPBAR_BG = "#FFFFFF"      # 顶部标题栏背景
COLOR_TOPBAR_BORDER = "#E5E6EB"
COLOR_CONTENT_BG = "#F5F6F7"      # 右侧内容区背景
COLOR_SUB_INDENT = "#37393E"      # 子菜单项背景（略深，体现层级）


class NavItem(tk.Frame):
    """单个左侧菜单项（水平布局：图标 + 文字，可选箭头）。

    可作为：
      - 普通菜单项（无箭头）
      - 子菜单项（indent=True，缩进显示，无图标）
    """

    def __init__(self, parent, key, label, icon="", on_click=None,
                 indent=False, show_arrow=False, on_arrow_toggle=None):
        super().__init__(parent, bg=COLOR_ITEM_NORMAL, cursor="hand2")
        self._key = key
        self._label = label
        self._icon = icon
        self._on_click = on_click
        self._active = False
        self._indent = indent
        self._show_arrow = show_arrow
        self._on_arrow_toggle = on_arrow_toggle
        self._expanded = False

        # 水平布局容器
        row = tk.Frame(self, bg=COLOR_ITEM_NORMAL)
        row.pack(fill=tk.X, pady=6)

        # 子菜单缩进
        if indent:
            tk.Frame(row, width=24, bg=COLOR_ITEM_NORMAL).pack(side=tk.LEFT)

        # 图标（子菜单项不显示图标，留位保持对齐）
        if icon:
            self._icon_lbl = tk.Label(
                row, text=icon, font=("Segoe UI Emoji", 14),
                bg=COLOR_ITEM_NORMAL, fg=COLOR_TEXT_NORMAL, width=2)
            self._icon_lbl.pack(side=tk.LEFT, padx=(10, 8))
        else:
            # 子菜单项用一个圆点表示
            dot = tk.Label(
                row, text="•", font=("Microsoft YaHei UI", 12),
                bg=COLOR_ITEM_NORMAL, fg=COLOR_TEXT_GROUP, width=2)
            dot.pack(side=tk.LEFT, padx=(10, 8))

        # 文字
        self._text_lbl = tk.Label(
            row, text=label, font=("Microsoft YaHei UI", 10),
            bg=COLOR_ITEM_NORMAL, fg=COLOR_TEXT_NORMAL)
        self._text_lbl.pack(side=tk.LEFT, expand=True, fill=tk.X, pady=2)

        # 展开箭头（父菜单用）
        self._arrow_lbl = None
        if show_arrow:
            self._arrow_lbl = tk.Label(
                row, text="▶", font=("Microsoft YaHei UI", 9),
                bg=COLOR_ITEM_NORMAL, fg=COLOR_TEXT_NORMAL)
            self._arrow_lbl.pack(side=tk.RIGHT, padx=10)

        # 收集需要绑定事件的组件
        self._widgets = [self, row, self._text_lbl]
        if icon:
            self._widgets.append(self._icon_lbl)
        if self._arrow_lbl is not None:
            self._widgets.append(self._arrow_lbl)

        for w in self._widgets:
            w.bind("<Button-1>", self._handle_click)
            w.bind("<Enter>", lambda e: self._on_hover(True))
            w.bind("<Leave>", lambda e: self._on_hover(False))

    def _handle_click(self, _e):
        # 父菜单：点击切换展开/收起
        if self._show_arrow and self._on_arrow_toggle:
            self._expanded = not self._expanded
            if self._arrow_lbl is not None:
                self._arrow_lbl.config(text="▼" if self._expanded else "▶")
            self._on_arrow_toggle(self._key, self._expanded)
            return
        # 普通菜单项 / 子菜单项：触发选中
        if self._on_click:
            self._on_click(self._key)

    def _on_hover(self, hovering):
        if self._active:
            return
        bg = COLOR_ITEM_HOVER if hovering else COLOR_ITEM_NORMAL
        self._apply_bg(bg, COLOR_TEXT_NORMAL)

    def set_active(self, active):
        self._active = active
        if active:
            self._apply_bg(COLOR_ITEM_ACTIVE, COLOR_TEXT_ACTIVE)
        else:
            self._apply_bg(COLOR_ITEM_NORMAL, COLOR_TEXT_NORMAL)

    def _apply_bg(self, bg, fg):
        """统一更新自身及所有子组件的背景/前景色。"""
        self.config(bg=bg)
        for w in self.winfo_children():
            w.config(bg=bg)
        # 文字 + 图标 + 箭头颜色
        self._text_lbl.config(bg=bg, fg=fg)
        if self._icon and hasattr(self, "_icon_lbl"):
            self._icon_lbl.config(bg=bg, fg=fg)
        if self._arrow_lbl is not None:
            self._arrow_lbl.config(bg=bg, fg=fg)

    def set_expanded(self, expanded):
        """外部直接设置展开状态（不触发回调）。"""
        self._expanded = expanded
        if self._arrow_lbl is not None:
            self._arrow_lbl.config(text="▼" if expanded else "▶")


class MainWindow:
    """钉钉式主窗口。

    使用方式：
        root = tk.Tk()
        app = MainWindow(root)
        root.mainloop()
    """

    # 左侧菜单定义：按组组织，每组内可有「普通项」或「可展开父菜单 + 子项」
    # 每条记录是一个 dict：
    #   {"type": "item",   "key":.., "label":.., "icon":..}
    #   {"type": "parent", "key":.., "label":.., "icon":..,
    #    "children": [ {"key":.., "label":..}, ... ]}
    # 组 1：工作台 —— 「股票」父菜单下挂「股票预测」子菜单
    # 组 2：协作 —— 消息、通讯录（占位）
    # 组 3：系统 —— 设置（占位）
    MENU_GROUPS = [
        ("工作台", [
            {"type": "parent", "key": "stock", "label": "股票", "icon": "📈", "children": [
                {"key": "stock_predict", "label": "pytorch股票预测"},
                {"key": "stock_predict_tf", "label": "tensorflow股票预测"},
                {"key": "st_performance", "label": "ST股票表现"},
                {"key": "st_reinstate", "label": "ST股票转正"},
                {"key": "favorite_stocks", "label": "自选股"},
                {"key": "sector_heat", "label": "板块热度"},
                {"key": "hot_stocks", "label": "热门股票"},
            ]},
            {"type": "item", "key": "dashboard", "label": "数据看板", "icon": "📊"},
        ]),
        ("协作", [
            {"type": "item", "key": "message", "label": "消息", "icon": "💬"},
            {"type": "item", "key": "contact", "label": "通讯录", "icon": "👥"},
        ]),
        ("系统", [
            {"type": "item", "key": "settings", "label": "设置", "icon": "⚙️"},
        ]),
    ]

    def __init__(self, root):
        self.root = root
        self.root.title("mystock - 股票分析工作台")
        self.root.geometry("1400x900")
        self.root.minsize(1200, 800)
        self.root.configure(bg=COLOR_CONTENT_BG)

        # 当前已构造的内容页面缓存（key -> widget）
        self._pages = {}
        self._nav_items = {}     # key -> NavItem（叶子项）
        self._nav_parents = {}   # key -> NavItem（父菜单项）
        self._sub_containers = {}  # parent_key -> Frame（子菜单容器）
        self._current_key = None
        self._stock_app = None

        self._build_layout()

    # ---------------- 布局 ----------------
    def _build_layout(self):
        self._build_topbar()
        body = tk.Frame(self.root, bg=COLOR_CONTENT_BG)
        body.pack(fill=tk.BOTH, expand=True)
        # 先建内容区，再建侧边栏：侧边栏末尾会触发默认菜单选中并渲染页面，
        # 此时 _content 必须已存在
        self._build_content(body)
        self._build_sidebar(body)

    def _build_topbar(self):
        topbar = tk.Frame(self.root, bg=COLOR_TOPBAR_BG, height=56)
        topbar.pack(fill=tk.X)
        topbar.pack_propagate(False)
        tk.Label(
            topbar, text="🚀  mystock 工作台", font=("Microsoft YaHei UI", 13, "bold"),
            bg=COLOR_TOPBAR_BG, fg="#1F2329").pack(side=tk.LEFT, padx=20)
        self._topbar_module_var = tk.StringVar(value="股票预测")
        tk.Label(
            topbar, textvariable=self._topbar_module_var,
            font=("Microsoft YaHei UI", 11),
            bg=COLOR_TOPBAR_BG, fg="#4E5969").pack(side=tk.LEFT, padx=8)
        tk.Label(
            topbar, text="jeoj", font=("Microsoft YaHei UI", 10),
            bg=COLOR_TOPBAR_BG, fg="#86909C").pack(side=tk.RIGHT, padx=20)
        tk.Frame(self.root, bg=COLOR_TOPBAR_BORDER, height=1).pack(fill=tk.X)

    def _build_sidebar(self, parent):
        sidebar = tk.Frame(parent, bg=COLOR_NAV_BG, width=200)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # 应用 logo / 标题区
        logo_frame = tk.Frame(sidebar, bg=COLOR_NAV_BG_DARKER, height=48)
        logo_frame.pack(fill=tk.X)
        logo_frame.pack_propagate(False)
        tk.Label(
            logo_frame, text="主菜单", font=("Microsoft YaHei UI", 11, "bold"),
            bg=COLOR_NAV_BG_DARKER, fg=COLOR_TEXT_NORMAL).pack(pady=12)

        # 可滚动菜单区
        canvas = tk.Canvas(sidebar, bg=COLOR_NAV_BG, highlightthickness=0, bd=0)
        scroll_y = ttk.Scrollbar(sidebar, orient="vertical", command=canvas.yview)
        menu_holder = tk.Frame(canvas, bg=COLOR_NAV_BG)

        menu_holder.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=menu_holder, anchor="nw", width=200)
        canvas.configure(yscrollcommand=scroll_y.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        # 渲染菜单组
        for group_name, items in self.MENU_GROUPS:
            tk.Label(
                menu_holder, text=group_name, anchor="w",
                font=("Microsoft YaHei UI", 9),
                bg=COLOR_NAV_BG, fg=COLOR_TEXT_GROUP).pack(
                fill=tk.X, padx=12, pady=(12, 4))
            for entry in items:
                self._render_menu_entry(menu_holder, entry)

        # 默认展开「股票」父菜单并选中「pytorch股票预测」
        if "stock" in self._nav_parents:
            self._nav_parents["stock"].set_expanded(True)
            self._show_sub_container("stock", True)
        self._on_nav_click("stock_predict")

    def _render_menu_entry(self, holder, entry):
        """渲染单条菜单项（普通项 / 父菜单 + 子项）。"""
        etype = entry.get("type", "item")
        if etype == "parent":
            parent_key = entry["key"]
            # 父菜单项（带箭头）
            parent_item = NavItem(
                holder, parent_key, entry["label"], icon=entry.get("icon", ""),
                show_arrow=True,
                on_arrow_toggle=self._on_parent_toggle)
            parent_item.pack(fill=tk.X, padx=8, pady=2)
            self._nav_parents[parent_key] = parent_item

            # 子菜单容器（默认隐藏）
            sub = tk.Frame(holder, bg=COLOR_NAV_BG)
            sub.pack(fill=tk.X, padx=8, pady=0)
            # 用 pack_forget 隐藏，展开时再 pack
            sub.pack_forget()
            self._sub_containers[parent_key] = sub

            # 渲染子项
            for child in entry.get("children", []):
                child_item = NavItem(
                    sub, child["key"], child["label"], icon="",
                    indent=True, on_click=self._on_nav_click)
                child_item.pack(fill=tk.X, pady=1)
                self._nav_items[child["key"]] = child_item
        else:
            # 普通菜单项
            item = NavItem(
                holder, entry["key"], entry["label"],
                icon=entry.get("icon", ""), on_click=self._on_nav_click)
            item.pack(fill=tk.X, padx=8, pady=2)
            self._nav_items[entry["key"]] = item

    def _on_parent_toggle(self, parent_key, expanded):
        """父菜单展开/收起时显示/隐藏其子菜单容器。"""
        self._show_sub_container(parent_key, expanded)

    def _show_sub_container(self, parent_key, show):
        sub = self._sub_containers.get(parent_key)
        if sub is None:
            return
        if show:
            # 在父菜单项之后插入显示
            sub.pack(fill=tk.X, padx=8, pady=0)
        else:
            sub.pack_forget()

    def _build_content(self, parent):
        self._content = tk.Frame(parent, bg=COLOR_CONTENT_BG)
        self._content.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

    # ---------------- 菜单切换 ----------------
    def _on_nav_click(self, key):
        if key == self._current_key:
            return
        # 更新所有叶子项选中态（父菜单不参与选中）
        for k, item in self._nav_items.items():
            item.set_active(k == key)
        self._current_key = key
        label = self._find_label(key)
        if label:
            self._topbar_module_var.set(label)
        self._switch_page(key)

    def _find_label(self, key):
        """在菜单定义中查找 key 对应的 label（含子菜单）。"""
        for _, items in self.MENU_GROUPS:
            for entry in items:
                if entry.get("type") == "parent":
                    if entry["key"] == key:
                        return entry["label"]
                    for child in entry.get("children", []):
                        if child["key"] == key:
                            # 子菜单显示「父级 / 子级」便于定位
                            return f"{entry['label']} / {child['label']}"
                else:
                    if entry["key"] == key:
                        return entry["label"]
        return ""

    def _switch_page(self, key):
        # 清空当前内容
        for child in self._content.winfo_children():
            child.destroy()

        if key in self._pages:
            self._pages[key].pack(fill=tk.BOTH, expand=True)
            return

        if key == "stock_predict":
            page = self._build_stock_page()
        elif key == "stock_predict_tf":
            page = self._build_stock_page_tf()
        elif key == "st_performance":
            page = self._build_st_performance_page()
        elif key == "st_reinstate":
            page = self._build_st_reinstate_page()
        elif key == "sector_heat":
            page = self._build_sector_heat_page()
        elif key == "hot_stocks":
            page = self._build_hot_stocks_page()
        elif key == "favorite_stocks":
            page = self._build_favorite_stocks_page()
        else:
            page = self._build_placeholder_page(key)
        if page is not None:
            self._pages[key] = page
            page.pack(fill=tk.BOTH, expand=True)

    # ---------------- 各页面构造 ----------------
    def _build_stock_page(self):
        """pytorch 股票预测：挂载原 StockApp（embedded 模式）。"""
        from .gui import StockApp
        page = tk.Frame(self._content, bg=COLOR_CONTENT_BG)
        self._stock_app = StockApp(page, embedded=True)
        return page

    def _build_stock_page_tf(self):
        """tensorflow 股票预测：挂载 StockAppTF（embedded 模式）。"""
        from .tf_gui import StockAppTF
        page = tk.Frame(self._content, bg=COLOR_CONTENT_BG)
        StockAppTF(page, embedded=True)
        return page

    def _build_st_performance_page(self):
        """ST股票表现：挂载 STPerformancePage（参数输入 + 结果表格）。"""
        from .st_page import STPerformancePage
        page = tk.Frame(self._content, bg=COLOR_CONTENT_BG)
        STPerformancePage(page)
        return page

    def _build_st_reinstate_page(self):
        """ST股票转正：挂载 STReinstatePage（ST 起始/转正日期 + 行情估值指标）。"""
        from .st_reinstate_page import STReinstatePage
        page = tk.Frame(self._content, bg=COLOR_CONTENT_BG)
        STReinstatePage(page)
        return page

    def _build_sector_heat_page(self):
        """板块热度：挂载 SectorHeatPage（按行业聚合板块热度榜）。"""
        from .sector_heat_page import SectorHeatPage
        page = tk.Frame(self._content, bg=COLOR_CONTENT_BG)
        SectorHeatPage(page)
        return page

    def _build_hot_stocks_page(self):
        """热门股票：挂载 HotStocksPage（按涨幅/成交额/成交量排序）。"""
        from .hot_stocks_page import HotStocksPage
        page = tk.Frame(self._content, bg=COLOR_CONTENT_BG)
        HotStocksPage(page)
        return page

    def _build_favorite_stocks_page(self):
        """自选股：挂载 FavoriteStocksPage（本地管理 + 事件到期提醒）。"""
        from .favorite_stocks_page import FavoriteStocksPage
        page = tk.Frame(self._content, bg=COLOR_CONTENT_BG)
        FavoriteStocksPage(page)
        return page

    def _build_placeholder_page(self, key):
        """占位页面（钉钉式空状态：图标 + 标题 + 提示）。"""
        label = self._find_label(key) or key
        icon_map = {
            "dashboard": "📊",
            "message": "💬",
            "contact": "👥",
            "settings": "⚙️",
            "stock": "📈",
        }
        icon = icon_map.get(key, "📦")
        page = tk.Frame(self._content, bg=COLOR_CONTENT_BG)

        center = tk.Frame(page, bg=COLOR_CONTENT_BG)
        center.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        tk.Label(
            center, text=icon, font=("Segoe UI Emoji", 64),
            bg=COLOR_CONTENT_BG, fg="#86909C").pack(pady=(0, 16))
        tk.Label(
            center, text=label, font=("Microsoft YaHei UI", 20, "bold"),
            bg=COLOR_CONTENT_BG, fg="#1F2329").pack(pady=(0, 8))
        tk.Label(
            center, text="该模块正在建设中，敬请期待",
            font=("Microsoft YaHei UI", 11),
            bg=COLOR_CONTENT_BG, fg="#86909C").pack()

        card = tk.Frame(page, bg="#FFFFFF", bd=0, highlightbackground=COLOR_TOPBAR_BORDER,
                        highlightthickness=1)
        card.place(relx=0.5, rely=0.78, anchor=tk.CENTER, width=420)
        tk.Label(
            card, text="功能规划", font=("Microsoft YaHei UI", 12, "bold"),
            bg="#FFFFFF", fg="#1F2329").pack(anchor="w", padx=20, pady=(14, 6))
        tips = {
            "dashboard": "• 多支股票横向对比\n• 关键指标雷达图\n• 自选股看板",
            "message": "• 预测完成通知\n• 模型异常告警\n• 与团队成员协作",
            "contact": "• 策略共享\n• 团队成员列表\n• 权限管理",
            "settings": "• 数据源配置\n• 主题切换\n• 缓存清理",
            "stock": "• 股票预测（已在子菜单中）\n• ST 股票表现\n• 板块热度 / 热门股票",
        }.get(key, "• 即将上线")
        tk.Label(
            card, text=tips, font=("Microsoft YaHei UI", 10),
            bg="#FFFFFF", fg="#4E5969", justify="left").pack(
            anchor="w", padx=20, pady=(0, 14))
        return page


if __name__ == "__main__":
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()
