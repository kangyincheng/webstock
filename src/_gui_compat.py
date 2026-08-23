"""GUI 兼容层：统一处理 tkinter / matplotlib TkAgg 后端导入。

在 Linux 无显示器 (headless) 或未安装 tkinter 的环境下，
import 这些模块不会崩溃，而是用 _Dummy 占位。
真正的 GUI 启动入口在 main() 中通过 _display_available() 做二次检查。
"""
import os
import sys

# ---- tkinter 导入守卫 ----
try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox, filedialog
    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False

    class _Dummy:
        """无 tkinter 时的占位对象，任何属性/调用都返回 _Dummy()。"""

        def __init__(self, *a, **kw):
            pass

        def __getattr__(self, _):
            return _Dummy()

        def __call__(self, *a, **kw):
            return _Dummy()

        def __bool__(self):
            return False

    tk = _Dummy()
    ttk = scrolledtext = messagebox = filedialog = _Dummy()

# ---- matplotlib TkAgg 后端导入守卫 ----
try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.figure import Figure
    import matplotlib
    MPL_TK_AVAILABLE = True
except Exception:
    MPL_TK_AVAILABLE = False
    try:
        from matplotlib.figure import Figure
    except ImportError:
        Figure = None
    FigureCanvasTkAgg = None
    NavigationToolbar2Tk = None


def display_available() -> bool:
    """检测当前环境是否有图形显示器。

    - Windows / macOS：始终返回 True
    - Linux：检查 DISPLAY 环境变量是否存在
    """
    if sys.platform == "win32":
        return True
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY"))


# 跨平台中文字体候选列表（按优先级排序）
_CJK_FONT_CANDIDATES = [
    # Windows
    "Microsoft YaHei UI", "Microsoft YaHei",
    # macOS
    "PingFang SC", "Heiti SC", "STHeiti",
    # Linux 常见中文字体
    "Noto Sans CJK SC", "Noto Sans CJK",
    "Source Han Sans SC", "Source Han Sans CN",
    "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei Mono",
    # Windows 兜底
    "SimHei", "SimSun",
]


def pick_cjk_font() -> str:
    """返回一个当前平台可用的中文字体名。

    - 在 Tk root 已创建后调用会枚举系统字体列表挑选；
    - 若 Tk 不可用或尚未初始化，则返回按平台预设的默认字体。
    """
    if sys.platform == "win32":
        default = "Microsoft YaHei UI"
    elif sys.platform == "darwin":
        default = "PingFang SC"
    else:
        default = "Noto Sans CJK SC"

    if not TK_AVAILABLE:
        return default
    try:
        from tkinter import font as _tkfont
        # 若 default root 已存在，families() 能拿到真实字体列表
        if tk._default_root is None:
            return default
        available = set(_tkfont.families())
        for name in _CJK_FONT_CANDIDATES:
            if name in available:
                return name
    except Exception:
        pass
    return default


def can_run_gui() -> bool:
    """是否可以启动桌面 GUI：tkinter 已安装 且 有显示器。"""
    return TK_AVAILABLE and display_available()


def print_headless_hint():
    """在 headless 环境下打印 Web 接口使用提示。"""
    print("=" * 60)
    if not TK_AVAILABLE:
        print("当前环境未安装 tkinter，无法启动桌面 GUI。")
        print("如需桌面 GUI，请安装：")
        print("  sudo dnf install -y python3-tkinter tkinter")
    else:
        print("当前为无图形界面 (headless) 环境，无法启动桌面 GUI。")
        print("如需远程桌面 GUI，请配置 X11 转发或 VNC。")
    print()
    print("Linux 服务器请使用 Web 接口：")
    print("  1. 启动后端:")
    print("     cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000")
    print("  2. 浏览器访问:")
    print("     http://localhost  或  http://www.jeoj.com")
    print("=" * 60)
