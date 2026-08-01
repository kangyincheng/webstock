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
- 菜单项：图标 + 文字，悬停/选中态高亮
- 「股票预测」菜单：挂载 StockApp（原先已做好的功能）
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


class NavItem(tk.Frame):
    """单个左侧菜单项（图标 + 文字 + 选中态）。"""

    def __init__(self, parent, key, label, icon, on_click):
        super().__init__(parent, bg=COLOR_ITEM_NORMAL, cursor="hand2")
        self._key = key
        self._label = label
        self._icon = icon
        self._on_click = on_click
        self._active = False

        # 图标
        self._icon_lbl = tk.Label(
            self, text=icon, font=("Segoe UI Emoji", 18),
            bg=COLOR_ITEM_NORMAL, fg=COLOR_TEXT_NORMAL)
        self._icon_lbl.pack(pady=(10, 2))

        # 文字
        self._text_lbl = tk.Label(
            self, text=label, font=("Microsoft YaHei UI", 10),
            bg=COLOR_ITEM_NORMAL, fg=COLOR_TEXT_NORMAL)
        self._text_lbl.pack(pady=(0, 10))

        # 绑定整个组件 + 子元素的点击/悬停
        for w in (self, self._icon_lbl, self._text_lbl):
            w.bind("<Button-1>", self._handle_click)
            w.bind("<Enter>", lambda e: self._on_hover(True))
            w.bind("<Leave>", lambda e: self._on_hover(False))

    def _handle_click(self, _e):
        if self._on_click:
            self._on_click(self._key)

    def _on_hover(self, hovering):
        # 选中态优先，不被悬停覆盖
        if self._active:
            return
        bg = COLOR_ITEM_HOVER if hovering else COLOR_ITEM_NORMAL
        self.config(bg=bg)
        self._icon_lbl.config(bg=bg)
        self._text_lbl.config(bg=bg)

    def set_active(self, active):
        self._active = active
        if active:
            bg, fg = COLOR_ITEM_ACTIVE, COLOR_TEXT_ACTIVE
        else:
            bg, fg = COLOR_ITEM_NORMAL, COLOR_TEXT_NORMAL
        self.config(bg=bg)
        self._icon_lbl.config(bg=bg, fg=fg)
        self._text_lbl.config(bg=bg, fg=fg)


class MainWindow:
    """钉钉式主窗口。

    使用方式：
        root = tk.Tk()
        app = MainWindow(root)
        root.mainloop()
    """

    # 左侧菜单定义：key, 显示名, 图标(emoji), 所属菜单组
    # 组 1：核心功能（钉钉式「工作台」组）
    #   - 股票预测：原 StockApp 功能
    #   - 数据看板：占位
    # 组 2：协作（钉钉式「协作」组）
    #   - 消息、通讯录：占位
    # 组 3：系统（钉钉式「系统」组）
    #   - 设置：占位
    MENU_GROUPS = [
        ("工作台", [
            ("stock", "股票预测", "📈", None),
            ("dashboard", "数据看板", "📊", None),
        ]),
        ("协作", [
            ("message", "消息", "💬", None),
            ("contact", "通讯录", "👥", None),
        ]),
        ("系统", [
            ("settings", "设置", "⚙️", None),
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
        self._nav_items = {}  # key -> NavItem
        self._current_key = None
        # 各内容区（按需懒加载）
        self._stock_app = None

        self._build_layout()

    # ---------------- 布局 ----------------
    def _build_layout(self):
        # 顶部标题栏
        self._build_topbar()

        # 主体：左侧导航 + 右侧内容
        body = tk.Frame(self.root, bg=COLOR_CONTENT_BG)
        body.pack(fill=tk.BOTH, expand=True)

        self._build_sidebar(body)
        self._build_content(body)

    def _build_topbar(self):
        topbar = tk.Frame(self.root, bg=COLOR_TOPBAR_BG, height=56)
        topbar.pack(fill=tk.X)
        topbar.pack_propagate(False)
        # 应用名
        tk.Label(
            topbar, text="🚀  mystock 工作台", font=("Microsoft YaHei UI", 13, "bold"),
            bg=COLOR_TOPBAR_BG, fg="#1F2329").pack(side=tk.LEFT, padx=20)
        # 当前模块名（动态）
        self._topbar_module_var = tk.StringVar(value="股票预测")
        tk.Label(
            topbar, textvariable=self._topbar_module_var,
            font=("Microsoft YaHei UI", 11),
            bg=COLOR_TOPBAR_BG, fg="#4E5969").pack(side=tk.LEFT, padx=8)
        # 右侧用户信息（占位）
        tk.Label(
            topbar, text="jeoj", font=("Microsoft YaHei UI", 10),
            bg=COLOR_TOPBAR_BG, fg="#86909C").pack(side=tk.RIGHT, padx=20)
        # 底部分隔线
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

        # 可滚动菜单区（菜单项多时支持滚动）
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

        # 鼠标滚轮支持
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
            for key, label, icon, _ in items:
                item = NavItem(menu_holder, key, label, icon, on_click=self._on_nav_click)
                item.pack(fill=tk.X, padx=8, pady=2)
                self._nav_items[key] = item

        # 默认选中第一个菜单（股票预测）
        self._on_nav_click("stock")

    def _build_content(self, parent):
        # 右侧内容区容器（切换时清空并挂载对应页面）
        self._content = tk.Frame(parent, bg=COLOR_CONTENT_BG)
        self._content.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

    # ---------------- 菜单切换 ----------------
    def _on_nav_click(self, key):
        if key == self._current_key:
            return
        # 更新选中态
        for k, item in self._nav_items.items():
            item.set_active(k == key)
        self._current_key = key
        # 更新顶部模块名
        label = self._find_label(key)
        if label:
            self._topbar_module_var.set(label)
        # 切换内容区
        self._switch_page(key)

    def _find_label(self, key):
        for _, items in self.MENU_GROUPS:
            for k, label, _icon, _ in items:
                if k == key:
                    return label
        return ""

    def _switch_page(self, key):
        # 清空当前内容
        for child in self._content.winfo_children():
            child.destroy()

        # 懒加载：构造过的页面直接复用
        if key in self._pages:
            self._pages[key].pack(fill=tk.BOTH, expand=True)
            return

        # 首次进入该菜单 -> 构造页面
        if key == "stock":
            page = self._build_stock_page()
        else:
            page = self._build_placeholder_page(key)
        if page is not None:
            self._pages[key] = page
            page.pack(fill=tk.BOTH, expand=True)

    # ---------------- 各页面构造 ----------------
    def _build_stock_page(self):
        """股票预测：挂载原 StockApp（embedded 模式）。"""
        from .gui import StockApp
        page = tk.Frame(self._content, bg=COLOR_CONTENT_BG)
        # StockApp 会把内部 UI 挂到 page 上
        self._stock_app = StockApp(page, embedded=True)
        return page

    def _build_placeholder_page(self, key):
        """占位页面（钉钉式空状态：图标 + 标题 + 提示）。"""
        label = self._find_label(key) or key
        icon_map = {
            "dashboard": "📊",
            "message": "💬",
            "contact": "👥",
            "settings": "⚙️",
        }
        icon = icon_map.get(key, "📦")
        page = tk.Frame(self._content, bg=COLOR_CONTENT_BG)

        # 居中布局
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

        # 钉钉式卡片：在占位页下方放一张「功能规划」卡片
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
