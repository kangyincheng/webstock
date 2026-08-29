"""要约收购数据分析。

数据源优先级：
  1) Tushare（如 cb_issue/equity_tenderoffer 等接口） —— 可获取 A 股要约信息
  2) 集思录 https://www.jisilu.cn/data/taoligu/#cna 网页抓取（HTML/JSON）
  3) 内置 mock 演示数据（上面两者不可用时用于 UI 渲染）

核心字段（A 股要约 / 港股要约 两张表统一列）：
  股票名称 / 股票代码 / 当前股价 / 要约价 / 要约溢价(%) /
  要约比例(%) / 要约开始日期 / 要约结束日期
"""
import os
import random
import re
from datetime import datetime, timedelta

import pandas as pd


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _try_import_tushare():
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
# 网页抓取：集思录 套利股/要约
# ---------------------------------------------------------------------------

def _pick(cell, *candidates, default=None):
    """从 cell 里按候选字段名取第一个非空（非 "-"）值。"""
    for c in candidates:
        if c in cell and cell[c] not in (None, "", "-"):
            return cell[c]
    return default


def _fetch_jisilu_tender(market="cn", progress_callback=None):
    """从集思录获取 A 股或港股要约/套利数据。

    market: 'cn' A股 / 'hk' 港股
    返回： DataFrame 或 None（失败）

    接口（JSON，无需登录）：
      A股  https://www.jisilu.cn/data/taoligu/astock_arbitrage_list/
      港股 https://www.jisilu.cn/data/taoligu/hk_arbitrage_list/
    返回格式：{"page":1,"rows":[{"id":..,"cell":{...}}]}
    """
    def log(msg):
        if progress_callback:
            progress_callback(msg)
    try:
        import urllib.request
        import json
    except Exception as e:
        log(f"集思录抓取：依赖模块缺少 {e}")
        return None

    urls = {
        "cn": ["https://www.jisilu.cn/data/taoligu/astock_arbitrage_list/"],
        "hk": ["https://www.jisilu.cn/data/taoligu/hk_arbitrage_list/"],
    }
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124 Safari/537.36"),
        "Accept": "application/json,text/html,*/*;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.jisilu.cn/data/taoligu/",
    }

    for url in urls.get(market, []):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read().decode("utf-8", errors="ignore")
            df = _parse_jisilu(data, market)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            log(f"集思录抓取 {url} 失败：{e}")
    return None


def _parse_jisilu(text, market):
    """解析集思录返回的 JSON：{"page":1,"rows":[{"id":..,"cell":{...}}]}。"""
    import json
    try:
        obj = json.loads(text)
    except Exception:
        return None
    rows_data = None
    if isinstance(obj, dict):
        rows_data = obj.get("rows") or obj.get("data") or obj.get("result")
    if not isinstance(rows_data, list):
        return None
    if market == "cn":
        return _build_cn_rows(rows_data)
    if market == "hk":
        return _build_hk_rows(rows_data)
    return None


def _build_cn_rows(rows_data):
    """A股要约/套利（集思录 astock_arbitrage_list，多为换股合并/要约）。"""
    rows = []
    for r in rows_data:
        cell = r.get("cell") if isinstance(r, dict) else r
        if not isinstance(cell, dict):
            continue
        name = _pick(cell, "stock_nm", "stock_name", "name")
        code = _pick(cell, "stock_id", "stock_code", "code")
        if not name or not code:
            continue
        rows.append({
            "股票名称": str(name).strip(),
            "股票代码": _std_code(str(code).strip(), "cn"),
            "当前股价": _to_float(_pick(cell, "price", "last_price", "close")),
            "安全价": _to_float(_pick(cell, "safe_price", "choose_price")),
            "折价率(%)": _to_float(_pick(cell, "discount_rt", "choose_discount_rt")),
            "类型": _pick(cell, "type_cd", "type", default="-") or "-",
            "描述": _pick(cell, "descr", "description", default="-") or "-",
        })
    if not rows:
        return None
    return pd.DataFrame(rows)


def _build_hk_rows(rows_data):
    """港股要约/私有化（集思录 hk_arbitrage_list）。"""
    rows = []
    for r in rows_data:
        cell = r.get("cell") if isinstance(r, dict) else r
        if not isinstance(cell, dict):
            continue
        name = _pick(cell, "stock_nm", "stock_name", "name")
        code = _pick(cell, "stock_code", "code")
        if not name or not code:
            continue
        rows.append({
            "股票名称": str(name).strip(),
            "股票代码": _std_code(str(code).strip(), "hk"),
            "当前股价": _to_float(_pick(cell, "price", "last_price", "close")),
            "要约价": _to_float(_pick(cell, "redeem_price", "tender_price", "offer_price")),
            "要约溢价(%)": _to_float(_pick(cell, "arbitrage_space", "premium", "premium_rate")),
            "进度": _pick(cell, "process", default="-") or "-",
            "要约人": _pick(cell, "offeror", default="-") or "-",
            "方式": _pick(cell, "way", default="-") or "-",
            "公告日期": _fmt_date(_pick(cell, "release_date", "announce_date")),
            "描述": _pick(cell, "descr", "description", default="-") or "-",
        })
    if not rows:
        return None
    return pd.DataFrame(rows)


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("%", "").replace("元", "").strip()
    if s == "" or s == "-":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _fmt_date(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s == "-":
        return None
    # 20250105 / 2025-01-05 / 2025/01/05
    s = s.replace("/", "-").replace(".", "-")
    if re.match(r"^\d{8}$", s):
        try:
            return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
        except Exception:
            return s
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")
        except Exception:
            return s
    return s


def _std_code(code, market):
    """标准化代码显示格式。"""
    code = code.strip()
    if market == "cn":
        if re.match(r"^\d{6}$", code):
            # A 股：6 开头 sh，0/3 开头 sz
            if code.startswith(("6", "9")):
                return f"{code}.SH"
            return f"{code}.SZ"
        # baostock 风格 sh.600000 -> 600000.SH
        m = re.match(r"^(sh|sz)\.(\d{6})$", code, re.I)
        if m:
            return f"{m.group(2)}.{m.group(1).upper()}"
    if market == "hk":
        if re.match(r"^\d{4,5}$", code):
            return f"{int(code):05d}.HK"
        if re.match(r"^(hk)\.(\d+)$", code, re.I):
            m = re.match(r"^(hk)\.(\d+)$", code, re.I)
            return f"{int(m.group(2)):05d}.HK"
    return code


# ---------------------------------------------------------------------------
# Mock 数据（A 股/港股 要约收购 示例）
# ---------------------------------------------------------------------------

def _build_mock_a():
    random.seed(42)
    sample = [
        ("云南白药",   "000538.SZ", 58.20,  59.74, 60.0,  "2026-08-10", "2026-09-05"),
        ("万科A",       "000002.SZ",  8.60,   9.20, 40.0,  "2026-08-01", "2026-08-29"),
        ("华夏银行",   "600015.SH",  5.12,   5.38, 30.0,  "2026-07-25", "2026-08-22"),
        ("东方集团",   "600811.SH",  3.45,   3.95, 20.0,  "2026-08-05", "2026-09-02"),
        ("淮河能源",   "600575.SH",  2.86,   3.20, 51.0,  "2026-08-15", "2026-09-12"),
    ]
    return _assemble_tender_rows(sample)


def _build_mock_hk():
    random.seed(7)
    sample = [
        ("腾讯控股",  "00700.HK",  312.0, 340.0, 45.0, "2026-08-08", "2026-09-18"),
        ("阿里巴巴-W", "09988.HK",   92.4,  98.5, 35.0, "2026-07-28", "2026-08-30"),
        ("美团-W",    "03690.HK",  138.0, 148.0, 50.0, "2026-08-12", "2026-09-25"),
        ("金沙中国",  "01928.HK",   22.6,  25.0, 28.0, "2026-08-03", "2026-08-28"),
    ]
    return _assemble_tender_rows(sample)


def _assemble_tender_rows(sample):
    rows = []
    for name, code, cur_p, offer_p, ratio, sdt, edt in sample:
        # 要约溢价 = (要约价 − 当前价) / 当前价 × 100
        try:
            premium = round(((offer_p - cur_p) / cur_p) * 100, 2)
        except Exception:
            premium = None
        rows.append({
            "股票名称": name,
            "股票代码": code,
            "当前股价": cur_p,
            "要约价": offer_p,
            "要约溢价(%)": premium,
            "要约比例(%)": ratio,
            "要约开始日期": sdt,
            "要约结束日期": edt,
        })
    cols = ["股票名称", "股票代码", "当前股价", "要约价", "要约溢价(%)",
            "要约比例(%)", "要约开始日期", "要约结束日期"]
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# 主分析器类
# ---------------------------------------------------------------------------

class TenderOfferAnalyzer:
    """要约收购分析器。

    使用方式：
        az = TenderOfferAnalyzer()
        a_df, h_df = az.fetch_tender_offers(progress_callback=print)
        # a_df: A 股要约表；h_df: 港股要约表
    """

    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._pro = _try_import_tushare()
        self._bs = _try_import_baostock()

    # ---------------- 正股价补充（baostock 只支持 A 股） ----------------
    def _fill_a_stock_prices(self, df):
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
                code = str(row.get("股票代码", ""))
                m = re.match(r"^(\d{6})\.(SH|SZ)$", code, re.I)
                if not m:
                    continue
                num, suffix = m.groups()
                bs_code = f"{suffix.lower()}.{num}"
                try:
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
                        df.at[idx, "当前股价"] = last_close
                        offer = row.get("要约价")
                        try:
                            df.at[idx, "要约溢价(%)"] = round(
                                (float(offer) - last_close) / last_close * 100, 2)
                        except Exception:
                            pass
                except Exception:
                    continue
        finally:
            try:
                self._bs.logout()
            except Exception:
                pass
        return df

    # ---------------- 主入口 ----------------
    def fetch_tender_offers(self, progress_callback=None):
        """返回 (A 股要约 DataFrame, 港股要约 DataFrame)。"""
        def log(msg):
            if progress_callback:
                progress_callback(msg)

        # -------- A 股要约 --------
        a_df = None
        # 1) Tushare
        if self._pro is not None:
            log("尝试从 Tushare 获取 A 股要约数据 ...")
            try:
                today = datetime.now().strftime("%Y%m%d")
                start = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")
                # tushare 的要约收购接口字段名以其官方文档为准；这里尝试多个可能
                for api_name, kwargs in [
                    ("eq_tenderoffer", dict(start_date=start, end_date=today)),
                    ("tenderoffer", dict(start_date=start, end_date=today)),
                    ("equity_tenderoffer", dict(start_date=start, end_date=today)),
                ]:
                    try:
                        fn = getattr(self._pro, api_name, None)
                        if fn is None:
                            continue
                        df = fn(**kwargs)
                        if df is not None and not df.empty:
                            a_df = self._map_from_tushare(df)
                            break
                    except Exception:
                        continue
            except Exception as e:
                log(f"Tushare A 股要约获取失败: {e}")
        if a_df is None or a_df.empty:
            # 2) 集思录
            log("尝试从集思录抓取 A 股要约数据 ...")
            try:
                a_df = _fetch_jisilu_tender("cn", progress_callback=log)
            except Exception as e:
                log(f"集思录 A 股要约抓取失败: {e}")
        if a_df is not None and not a_df.empty:
            a_df = self._fill_a_stock_prices(a_df)
            a_df = self._ensure_premium(a_df)
        else:
            a_df = _build_mock_a()
            log("使用 A 股要约演示数据")

        # -------- 港股要约 --------
        h_df = None
        try:
            log("尝试从集思录抓取港股要约数据 ...")
            h_df = _fetch_jisilu_tender("hk", progress_callback=log)
        except Exception as e:
            log(f"集思录港股要约抓取失败: {e}")
        if h_df is not None and not h_df.empty:
            h_df = self._ensure_premium(h_df)
        else:
            h_df = _build_mock_hk()
            log("使用港股要约演示数据")

        # 两表统一按「要约溢价(%)」降序（高溢价排前）
        for df in (a_df, h_df):
            col = "要约溢价(%)"
            if col in df.columns:
                sv = pd.to_numeric(df[col], errors="coerce")
                df = df.assign(_s=sv, _na=sv.isna()).sort_values(
                    by=["_na", "_s"], ascending=[True, False], kind="mergesort"
                ).drop(columns=["_s", "_na"]).reset_index(drop=True)
            # 给外层重新赋值：因为 df 只是局部引用
            # 所以下面 return 用 a/h 变量分别接收
        if "要约溢价(%)" in a_df.columns:
            sv = pd.to_numeric(a_df["要约溢价(%)"], errors="coerce")
            a_df = a_df.assign(_s=sv, _na=sv.isna()).sort_values(
                by=["_na", "_s"], ascending=[True, False], kind="mergesort"
            ).drop(columns=["_s", "_na"]).reset_index(drop=True)
        if "要约溢价(%)" in h_df.columns:
            sv = pd.to_numeric(h_df["要约溢价(%)"], errors="coerce")
            h_df = h_df.assign(_s=sv, _na=sv.isna()).sort_values(
                by=["_na", "_s"], ascending=[True, False], kind="mergesort"
            ).drop(columns=["_s", "_na"]).reset_index(drop=True)

        log(f"获取完成：A 股要约 {len(a_df)} 条，港股要约 {len(h_df)} 条")
        return a_df, h_df

    # ---------------- 工具方法 ----------------
    @staticmethod
    def _ensure_premium(df):
        """若表中有 要约价 与 当前价 但溢价缺失/为 None，则补算。"""
        if df is None or df.empty:
            return df
        if "要约价" not in df.columns or "当前股价" not in df.columns:
            return df  # 缺要约价/当前价则跳过，避免给 A 股表注入空 要约溢价(%) 列
        df = df.copy()
        cur = pd.to_numeric(df.get("当前股价"), errors="coerce")
        offer = pd.to_numeric(df.get("要约价"), errors="coerce")
        exist = pd.to_numeric(df.get("要约溢价(%)"), errors="coerce")
        # 存在且非 NaN 的保留；否则重算
        calc = ((offer - cur) / cur * 100).round(2)
        df["要约溢价(%)"] = exist.where(exist.notna(), calc)
        return df

    @staticmethod
    def _map_from_tushare(df):
        col_map = {
            "ts_code": "股票代码",
            "name": "股票名称", "sec_name": "股票名称", "ts_name": "股票名称",
            "cur_price": "当前股价", "close": "当前股价", "price": "当前股价",
            "tender_price": "要约价", "offer_price": "要约价",
            "premium_rate": "要约溢价(%)", "premium": "要约溢价(%)",
            "tender_ratio": "要约比例(%)", "offer_ratio": "要约比例(%)", "ratio": "要约比例(%)",
            "tender_start": "要约开始日期", "start_date": "要约开始日期",
            "tender_end": "要约结束日期", "end_date": "要约结束日期",
        }
        out = pd.DataFrame()
        for src, dst in col_map.items():
            if src in df.columns and dst not in out.columns:
                out[dst] = df[src]
        # 代码规范化
        if "股票代码" in out.columns:
            out["股票代码"] = out["股票代码"].astype(str).map(
                lambda c: _std_code(c, "cn")
            )
        for dc in ("要约开始日期", "要约结束日期"):
            if dc in out.columns:
                out[dc] = pd.to_datetime(out[dc], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
        # 保证列齐全
        for c in ["股票名称", "股票代码", "当前股价", "要约价", "要约溢价(%)",
                  "要约比例(%)", "要约开始日期", "要约结束日期"]:
            if c not in out.columns:
                out[c] = None
        return out[["股票名称", "股票代码", "当前股价", "要约价", "要约溢价(%)",
                    "要约比例(%)", "要约开始日期", "要约结束日期"]]
