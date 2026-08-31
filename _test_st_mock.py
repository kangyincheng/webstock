"""用模拟 baostock 数据端到端测试 STAnalyzer.scan_and_analyze（临时测试脚本）。"""
import sys, types
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, "/workspace/src")

# ---------- 构造假 baostock ----------
bs = types.ModuleType("baostock")

TODAY = datetime.now()

def _wd(d):
    """把日期调整到最近的工作日（含当天向前找）。"""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d

LATEST = _wd(TODAY)                       # 最新交易日
START_TARGET = TODAY - timedelta(days=300)  # months_back=10
OLD_SNAP = _wd(START_TARGET)              # 旧快照交易日
BUFFER = TODAY - timedelta(days=390)      # months_back+3

UNCAP = _wd(TODAY - timedelta(days=60))   # 摘帽日
ST_START = _wd(OLD_SNAP + timedelta(days=5))

def daterange(a, b):
    out, d = [], a
    while d <= b:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out

ALL_DAYS = daterange(_wd(BUFFER), LATEST)

# 全市场快照
def _snapshot(day_str):
    d = datetime.strptime(day_str, "%Y-%m-%d")
    is_old = d <= OLD_SNAP + timedelta(days=2)
    rows = []
    # sh.600744: 旧名带ST，新名不带ST -> 应被识别为摘帽
    name744 = "*ST华银" if is_old else "华银电力"
    rows.append({"code": "sh.600744", "tradeStatus": "1", "code_name": name744})
    # sz.000001: 一直正常
    rows.append({"code": "sz.000001", "tradeStatus": "1", "code_name": "平安银行"})
    # sh.600000: 一直ST（未摘帽）
    rows.append({"code": "sh.600000", "tradeStatus": "1", "code_name": "*ST浦发"})
    return pd.DataFrame(rows)

class FakeRS:
    def __init__(self, df, error_code="0", error_msg="success"):
        self._df = df
        self.error_code = error_code
        self.error_msg = error_msg
        self.fields = list(df.columns) if df is not None else []
        self._i = 0
    def get_data(self):
        return self._df.copy() if self._df is not None else pd.DataFrame()
    def next(self):
        if self._df is None or self._i >= len(self._df):
            return False
        self._i += 1
        return True
    def get_row_data(self):
        return [str(v) for v in self._df.iloc[self._i - 1].tolist()]

def query_all_stock(day=None):
    return FakeRS(_snapshot(day))

def query_history_k_data_plus(code, fields, start_date, end_date,
                              frequency="d", adjustflag="2"):
    rows = []
    for i, day in enumerate(ALL_DAYS):
        if day < start_date or day > end_date:
            continue
        is_st = 1 if day < UNCAP.strftime("%Y-%m-%d") else 0
        close = 10.0 + 0.01 * i
        rows.append({
            "date": day, "code": code,
            "close": f"{close:.2f}", "preclose": f"{close-0.01:.2f}",
            "pctChg": "0.10", "isST": str(is_st),
            "peTTM": "35.5", "pbMRQ": "2.1",
        })
    df = pd.DataFrame(rows)
    return FakeRS(df)

def login():
    class L:
        error_code = "0"; error_msg = "success"
    return L()

def logout():
    pass

bs.query_all_stock = query_all_stock
bs.query_history_k_data_plus = query_history_k_data_plus
bs.login = login
bs.logout = logout
sys.modules["baostock"] = bs

# ---------- 运行分析器 ----------
from st_analyzer import STAnalyzer

logs = []
az = STAnalyzer(data_dir="/tmp/stdata")
df = az.scan_and_analyze(months_back=10, before_days=30, after_days=30,
                         progress_callback=lambda m: logs.append(m))

print("=== LOGS ===")
for l in logs:
    print(" ", l)
print("=== RESULT ===")
print(df.to_string() if df is not None else "None")
print("rows:", 0 if df is None else len(df))
