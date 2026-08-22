"""mystock 源码包。

顶层模块采用懒加载：data_loader / model / trainer / gui 等较重或带可选依赖
（torch / tensorflow / baostock）的子模块仅在真正访问时才 import，
确保 numpy / sklearn / torch 等任一缺失时，主窗口仍可启动。
"""


def __getattr__(name):
    """懒加载子模块，避免 torch/baostock 等缺失时整个包无法导入。"""
    _LAZY = {
        "StockDataLoader": ".data_loader",
        "StockLSTM": ".model",
        "StockGRU": ".model",
        "StockTransformer": ".model",
        "StockTrainer": ".trainer",
        "StockApp": ".gui",
        "STAnalyzer": ".st_analyzer",
        "STPerformancePage": ".st_page",
        "STReinstateAnalyzer": ".st_reinstate_analyzer",
        "STReinstatePage": ".st_reinstate_page",
        "MainWindow": ".main_window",
        "SectorHeatPage": ".sector_heat_page",
        "HotStocksPage": ".hot_stocks_page",
        "FavoriteStocksPage": ".favorite_stocks_page",
        "TushareClient": ".market_data",
        "StockAppTF": ".tf_gui",
        "TFStockTrainer": ".tf_trainer",
    }
    if name in _LAZY:
        import importlib
        mod_name = _LAZY[name]
        mod = importlib.import_module(mod_name, __name__)
        return getattr(mod, name)
    raise AttributeError(f"module 'src' has no attribute {name!r}")
