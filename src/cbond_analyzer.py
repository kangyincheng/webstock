"""可转债数据分析。

数据源：优先使用 tushare（需要配置 token），无 token 时使用内置演示数据。

包含三类数据：
  1. 当日可申购可转债（打新申购）
  2. 当日上市的新可转债（新股上市）
  3. 已向交易所提交发行申请的可转债（发审进度）

核心字段：
  - 转债代码 / 转债名称
  - 对应正股代码 / 正股名称 / 正股价
  - 债发行价（一般 100 元）
  - 转股价
  - 转股价值 = (发行价 / 转股价) × 正股价
  - 可转债溢价率 = (转债现价 - 转股价值) / 转股价值 × 100%
"""
import os
import random
from datetime import datetime, timedelta

import pandas as pd


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _try_import_tushare():
    """尝试导入 tushare 并返回 pro 接口，失败返回 None。"""
    try:
        import tushare as ts
        token = os.environ.get("TUSHARE_TOKEN") or ts.get_token()
        if not token:
            return None
        ts.set_token(token)
        return ts.pro_api()
    except Exception:
        return None


def _try_import_baostock():
    try:
        import baostock as bs
        return bs
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Mock 数据：当 tushare 不可用时，用于演示 UI 渲染
# ---------------------------------------------------------------------------

def _build_mock_subscribe(today):
    """生成当日可申购可转债的 mock 数据。"""
    random.seed(hash(today) % (2**31))
    sample = [
        ("118000.SH", "示例转债1", "正股科技", "688001.SH", 125.6, 100.0, 120.5,),
        ("123456.SZ", "示例转债2", "创新医疗", "002345.SZ", 18.32, 100.0, 20.00,),
        ("110050.SH", "示例转债3", "华能新材", "601050.SH", 8.65, 100.0, 8.80,),
        ("127050.SZ", "示例转债4", "东方精工", "002550.SZ", 6.42, 100.0, 6.50,),
        ("118030.SH", "示例转债5", "中联数智", "688350.SH", 42.80, 100.0, 40.00,),
    ]
    rows = []
    for code, name, stock_name, stock_code, stock_price, issue_price, conv_price in sample:
        conv_value = round((issue_price / conv_price) * stock_price, 2)
        premium = round(((issue_price - conv_value) / conv_value) * 100, 2)
        rows.append({
            "转债代码": code,
            "转债名称": name,
            "申购日期": today,
            "正股代码": stock_code,
            "正股名称": stock_name,
            "正股价": stock_price,
            "债发行价": issue_price,
            "转股价": conv_price,
            "转股价值": conv_value,
            "可转债溢价率(%)": premium,
            "配售代码": code.replace("118", "764").replace("123", "380").replace("110", "764").replace("127", "783"),
            "申购上限(万元)": round(random.uniform(50, 200), 1),
        })
    cols = ["转债代码", "转债名称", "申购日期", "正股代码", "正股名称", "正股价",
            "债发行价", "转股价", "转股价值", "可转债溢价率(%)", "配售代码", "申购上限(万元)"]
    return pd.DataFrame(rows, columns=cols)


def _build_mock_listing(today):
    """生成当日上市可转债的 mock 数据。"""
    random.seed((hash(today) + 7) % (2**31))
    sample = [
        ("118020.SH", "新上市转债A", "北方华创", "002371.SZ", 320.5, 100.0, 298.0, 135.2),
        ("123400.SZ", "新上市转债B", "恒瑞医药", "600276.SH", 45.6, 100.0, 42.0, 118.6),
        ("110040.SH", "新上市转债C", "长江电力", "600900.SH", 28.3, 100.0, 26.5, 112.4),
    ]
    rows = []
    for code, name, stock_name, stock_code, stock_price, issue_price, conv_price, bond_price in sample:
        conv_value = round((issue_price / conv_price) * stock_price, 2)
        premium = round(((bond_price - conv_value) / conv_value) * 100, 2)
        rows.append({
            "转债代码": code,
            "转债名称": name,
            "上市日期": today,
            "正股代码": stock_code,
            "正股名称": stock_name,
            "正股价": stock_price,
            "债发行价": issue_price,
            "转股价": conv_price,
            "转股价值": conv_value,
            "转债开盘价": bond_price,
            "可转债溢价率(%)": premium,
            "首日涨幅(%)": round(((bond_price - issue_price) / issue_price) * 100, 2),
        })
    cols = ["转债代码", "转债名称", "上市日期", "正股代码", "正股名称", "正股价",
            "债发行价", "转股价", "转股价值", "转债开盘价", "可转债溢价率(%)", "首日涨幅(%)"]
    return pd.DataFrame(rows, columns=cols)


def _build_mock_review():
    """生成转债发审进度的 mock 数据。"""
    random.seed(42)
    stages = [
        "董事会预案", "股东大会通过", "发审委受理", "发审委问询",
        "发审委通过", "证监会核准", "发行中", "已完成",
    ]
    sample = [
        ("恒瑞转债2", "123xxx.SZ", "恒瑞医药", "600276.SH", 45.6, 100.0, 42.0, 5, 80),
        ("长电转债", "110xxx.SH", "长江电力", "600900.SH", 28.3, 100.0, 26.5, 3, 60),
        ("华友转债2", "127xxx.SZ", "华友钴业", "603799.SH", 58.2, 100.0, 55.0, 4, 70),
        ("科大转债", "128xxx.SZ", "科大讯飞", "002230.SZ", 52.1, 100.0, 50.0, 2, 40),
        ("宁德转债2", "123xxx.SZ", "宁德时代", "300750.SZ", 198.5, 100.0, 180.0, 6, 90),
        ("北方转债", "118xxx.SH", "北方华创", "002371.SZ", 320.5, 100.0, 298.0, 1, 20),
        ("隆基转债2", "113xxx.SH", "隆基绿能", "601012.SH", 22.8, 100.0, 20.0, 7, 98),
        ("药明转债", "113xxx.SH", "药明康德", "603259.SH", 68.4, 100.0, 65.0, 0, 10),
    ]
    rows = []
    for name, code, stock_name, stock_code, stock_price, issue_price, conv_price, stage_idx, progress in sample:
        conv_value = round((issue_price / conv_price) * stock_price, 2)
        premium = round(((issue_price - conv_value) / conv_value) * 100, 2)
        rows.append({
            "转债代码": code,
            "转债名称": name,
            "发审阶段": stages[stage_idx],
            "审核进度(%)": progress,
            "正股代码": stock_code,
            "正股名称": stock_name,
            "正股价": stock_price,
            "债发行价": issue_price,
            "转股价": conv_price,
            "转股价值": conv_value,
            "可转债溢价率(%)": premium,
            "受理日期": (datetime.now() - timedelta(days=random.randint(5, 120))).strftime("%Y-%m-%d"),
            "预计发行日期": (datetime.now() + timedelta(days=random.randint(10, 90))).strftime("%Y-%m-%d"),
        })
    cols = ["转债代码", "转债名称", "发审阶段", "审核进度(%)", "正股代码", "正股名称", "正股价",
            "债发行价", "转股价", "转股价值", "可转债溢价率(%)", "受理日期", "预计发行日期"]
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# 主分析器类
# ---------------------------------------------------------------------------

class ConvertibleBondAnalyzer:
    """可转债数据分析器。

    使用方式：
        az = ConvertibleBondAnalyzer()
        sub_df, list_df = az.fetch_new_ipo(progress_callback=print)
        review_df = az.fetch_review(progress_callback=print)
    """

    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._pro = _try_import_tushare()
        self._bs = _try_import_baostock()

    # ---------------- 正股价补充 ----------------
    def _fill_stock_price(self, df, code_col="正股代码", price_col="正股价"):
        """通过 baostock 补充/刷新正股最新价格（不可用则保留原值）。"""
        if df is None or df.empty or self._bs is None:
            return df
        try:
            lg = self._bs.login()
            if lg.error_code != "0":
                return df
        except Exception:
            return df
        try:
            for idx, row in df.iterrows():
                code = row.get(code_col)
                if not code:
                    continue
                # tushare 代码格式转换：sh.600000 -> 600000.SH
                bs_code = self._to_bs_code(code)
                if not bs_code:
                    continue
                try:
                    # 取最近 5 个交易日
                    end = datetime.now().strftime("%Y-%m-%d")
                    start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
                    rs = self._bs.query_history_k_data_plus(
                        bs_code, "date,close",
                        start_date=start, end_date=end,
                        frequency="d", adjustflag="2")
                    rows = []
                    while rs.error_code == "0" and rs.next():
                        rows.append(rs.get_row_data())
                    if rows:
                        last_close = float(rows[-1][1])
                        df.at[idx, price_col] = last_close
                except Exception:
                    continue
        finally:
            try:
                self._bs.logout()
            except Exception:
                pass
        return df

    @staticmethod
    def _to_bs_code(code):
        """把 600000.SH / 000001.SZ 转成 sh.600000 / sz.000001。"""
        if not code or "." not in code:
            return None
        num, suffix = code.split(".", 1)
        suffix = suffix.lower()
        if suffix in ("sh", "sz"):
            return f"{suffix}.{num}"
        return None

    # ---------------- 可转债打新 / 上市 ----------------
    def fetch_new_ipo(self, progress_callback=None):
        """获取当日可转债打新 + 上市数据。

        Returns:
            (subscribe_df, listing_df)
            subscribe_df: 当日可申购可转债表
            listing_df: 当日上市可转债表
        """
        today = _today_str()

        def log(msg):
            if progress_callback:
                progress_callback(msg)

        sub_df = None
        list_df = None

        if self._pro is not None:
            log("尝试从 Tushare 获取可转债打新/上市数据 ...")
            try:
                # cb_issue 新债发行
                issue = self._pro.cb_issue(start_date=today.replace("-", ""),
                                           end_date=today.replace("-", ""))
                if issue is not None and not issue.empty:
                    sub_df = self._map_subscribe_from_tushare(issue)
                    sub_df = self._fill_stock_price(sub_df)
                    sub_df = self._compute_conv_metrics(sub_df)
            except Exception as e:
                log(f"Tushare 打新数据获取失败: {e}")

            try:
                # cb_list 新债上市
                lst = self._pro.cb_list(start_date=today.replace("-", ""),
                                        end_date=today.replace("-", ""))
                if lst is not None and not lst.empty:
                    list_df = self._map_listing_from_tushare(lst)
                    list_df = self._fill_stock_price(list_df)
                    list_df = self._compute_conv_metrics(list_df, bond_price_col="转债开盘价")
            except Exception as e:
                log(f"Tushare 上市数据获取失败: {e}")
        else:
            log("未配置 TUSHARE_TOKEN，将使用演示数据")

        if sub_df is None or sub_df.empty:
            log("使用演示申购数据 ...")
            sub_df = _build_mock_subscribe(today)
        if list_df is None or list_df.empty:
            log("使用演示上市数据 ...")
            list_df = _build_mock_listing(today)

        log(f"当日可申购 {len(sub_df)} 只，当日上市 {len(list_df)} 只")
        return sub_df, list_df

    # ---------------- 可转债发审进度 ----------------
    def fetch_review(self, progress_callback=None):
        """获取已提交发行申请的可转债发审进度。"""
        def log(msg):
            if progress_callback:
                progress_callback(msg)

        review_df = None
        if self._pro is not None:
            log("尝试从 Tushare 获取可转债发审进度数据 ...")
            try:
                # cb_call 可转债发行公告 / 发审进度
                # tushare 的 cb_call_back / cb_call 需要根据文档调整
                today = datetime.now().strftime("%Y%m%d")
                start = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
                cb = self._pro.cb_call(start_date=start, end_date=today)
                if cb is not None and not cb.empty:
                    review_df = self._map_review_from_tushare(cb)
                    review_df = self._fill_stock_price(review_df)
                    review_df = self._compute_conv_metrics(review_df)
            except Exception as e:
                log(f"Tushare 发审数据获取失败: {e}")
        else:
            log("未配置 TUSHARE_TOKEN，将使用演示数据")

        if review_df is None or review_df.empty:
            log("使用演示发审数据 ...")
            review_df = _build_mock_review()

        # 按发审阶段 + 审核进度排序
        stage_order = {
            "董事会预案": 0, "股东大会通过": 1, "发审委受理": 2, "发审委问询": 3,
            "发审委通过": 4, "证监会核准": 5, "发行中": 6, "已完成": 7,
        }
        review_df["_stage_order"] = review_df["发审阶段"].map(
            lambda s: stage_order.get(s, 99))
        review_df = review_df.sort_values(
            by=["_stage_order", "审核进度(%)"],
            ascending=[True, False]).drop(columns=["_stage_order"]).reset_index(drop=True)

        log(f"共 {len(review_df)} 条可转债发审记录")
        return review_df

    # ---------------- Tushare 字段映射 ----------------
    @staticmethod
    def _map_subscribe_from_tushare(df):
        """将 tushare cb_issue 字段映射到标准列。"""
        out = pd.DataFrame()
        # 字段名根据 tushare 实际文档可能有差异，这里尽力兼容
        col_map = {
            "ts_code": "转债代码",
            "bond_code": "转债代码",
            "cb_code": "转债代码",
            "ts_name": "转债名称",
            "bond_name": "转债名称",
            "cb_name": "转债名称",
            "s_code": "正股代码",
            "stk_code": "正股代码",
            "stock_code": "正股代码",
            "s_name": "正股名称",
            "stk_name": "正股名称",
            "stock_name": "正股名称",
            "issue_date": "申购日期",
            "sub_date": "申购日期",
            "issue_price": "债发行价",
            "par": "债发行价",
            "conv_price": "转股价",
            "convert_price": "转股价",
            "match_price": "配售代码",
            "uplimit": "申购上限(万元)",
        }
        for src, dst in col_map.items():
            if src in df.columns and dst not in out.columns:
                out[dst] = df[src]
        # 日期格式化
        for dc in ("申购日期",):
            if dc in out.columns:
                out[dc] = pd.to_datetime(out[dc], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
        # 缺失默认值
        out["债发行价"] = out.get("债发行价", pd.Series([100.0] * len(out)))
        return out

    @staticmethod
    def _map_listing_from_tushare(df):
        col_map = {
            "ts_code": "转债代码", "bond_code": "转债代码",
            "ts_name": "转债名称", "bond_name": "转债名称",
            "s_code": "正股代码", "stk_code": "正股代码",
            "s_name": "正股名称", "stk_name": "正股名称",
            "list_date": "上市日期",
            "issue_price": "债发行价", "par": "债发行价",
            "conv_price": "转股价", "convert_price": "转股价",
            "open": "转债开盘价", "first_open": "转债开盘价",
        }
        out = pd.DataFrame()
        for src, dst in col_map.items():
            if src in df.columns and dst not in out.columns:
                out[dst] = df[src]
        if "上市日期" in out.columns:
            out["上市日期"] = pd.to_datetime(out["上市日期"], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
        out["债发行价"] = out.get("债发行价", pd.Series([100.0] * len(out)))
        return out

    @staticmethod
    def _map_review_from_tushare(df):
        col_map = {
            "ts_code": "转债代码", "bond_code": "转债代码",
            "ts_name": "转债名称", "bond_name": "转债名称",
            "s_code": "正股代码", "stk_code": "正股代码",
            "s_name": "正股名称", "stk_name": "正股名称",
            "status": "发审阶段", "stage": "发审阶段", "review_status": "发审阶段",
            "progress": "审核进度(%)",
            "accept_date": "受理日期",
            "plan_issue_date": "预计发行日期",
            "issue_price": "债发行价", "par": "债发行价",
            "conv_price": "转股价", "convert_price": "转股价",
        }
        out = pd.DataFrame()
        for src, dst in col_map.items():
            if src in df.columns and dst not in out.columns:
                out[dst] = df[src]
        for dc in ("受理日期", "预计发行日期"):
            if dc in out.columns:
                out[dc] = pd.to_datetime(out[dc], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
        out["债发行价"] = out.get("债发行价", pd.Series([100.0] * len(out)))
        # 审核进度缺失的话根据阶段估算
        if "审核进度(%)" not in out.columns:
            stage_prog = {"董事会预案": 10, "股东大会通过": 25, "发审委受理": 40,
                          "发审委问询": 55, "发审委通过": 70, "证监会核准": 85,
                          "发行中": 95, "已完成": 100}
            out["审核进度(%)"] = out["发审阶段"].map(lambda s: stage_prog.get(s, 50))
        return out

    # ---------------- 转股价值 / 溢价率计算 ----------------
    @staticmethod
    def _compute_conv_metrics(df, bond_price_col=None):
        """计算转股价值和可转债溢价率。

        bond_price_col: 转债现价列名；None 则用债发行价作为转债现价
        """
        df = df.copy()
        issue = pd.to_numeric(df.get("债发行价", 100.0), errors="coerce").fillna(100.0)
        conv_p = pd.to_numeric(df.get("转股价"), errors="coerce")
        stock_p = pd.to_numeric(df.get("正股价"), errors="coerce")
        # 转债现价
        if bond_price_col and bond_price_col in df.columns:
            bond_p = pd.to_numeric(df[bond_price_col], errors="coerce")
        else:
            bond_p = issue

        # 转股价值 = (发行价 / 转股价) × 正股价
        conv_value = (issue / conv_p) * stock_p
        # 可转债溢价率 = (转债现价 - 转股价值) / 转股价值 × 100
        premium = (bond_p - conv_value) / conv_value * 100

        df["转股价值"] = conv_value.round(2)
        df["可转债溢价率(%)"] = premium.round(2)
        return df
