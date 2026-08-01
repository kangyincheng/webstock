from .data_loader import StockDataLoader
from .model import StockLSTM, StockTransformer
from .trainer import StockTrainer


def __getattr__(name):
    """懒加载较重或可选的子模块，避免 numpy/baostock 缺失时整个包无法导入。"""
    if name == "STAnalyzer":
        from .st_analyzer import STAnalyzer
        return STAnalyzer
    if name == "MainWindow":
        from .main_window import MainWindow
        return MainWindow
    if name == "StockApp":
        from .gui import StockApp
        return StockApp
    if name == "STPerformancePage":
        from .st_page import STPerformancePage
        return STPerformancePage
    raise AttributeError(f"module 'src' has no attribute {name!r}")
