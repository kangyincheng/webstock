"""ST 摘帽数据管理服务：单只股票抓取 + 预计算文件维护。

数据文件: backend/data/st_scan_results.json
{
  "records": [{...单只股票记录...}],
  "logs":    [...],
  "n_values":[5, 10, 15, 20],
}

单只股票处理流程（add_stock）:
  1. 巨潮抓该股票最新的「撤销其他风险警示 / 撤销退市风险警示」公告 -> 发布日期 + 股票名称
  2. 新浪历史 K 线 -> 在公告日附近定位交易日 -> 计算前/后 [5,10,15,20] 涨幅
  3. 新浪实时行情 -> 最新价
  4. 写入文件（代码已存在则覆盖，否则新增），按"结束ST日期"降序保留
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

# backend/app/services/st_data_service.py -> dirname x3 = /workspace/backend
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(_BACKEND_ROOT, "data")
DATA_FILE = os.path.join(DATA_DIR, "st_scan_results.json")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
N_VALUES = [5, 10, 15, 20]


def _proxies() -> Optional[dict]:
    p = (os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
         or os.environ.get("http_proxy") or os.environ.get("https_proxy"))
    return {"http": p, "https": p} if p else None


# ---------------- 数据文件读写 ----------------
def load_data() -> Dict[str, Any]:
    """读取预计算文件，文件不存在或损坏时返回空骨架。"""
    try:
        if os.path.isfile(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict) and isinstance(d.get("records"), list):
                    return d
    except Exception:
        pass
    return {"records": [], "logs": [], "n_values": N_VALUES}


def save_data(data: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    data["n_values"] = N_VALUES
    data.setdefault("logs", [])
    # 维护"最近更新"行（始终在第一位）
    data["logs"] = [l for l in data["logs"] if not str(l).startswith("最近更新:")]
    data["logs"].insert(0, f"最近更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_records() -> List[Dict[str, Any]]:
    return load_data().get("records", [])


# ---------------- 代码格式归一化 ----------------
def normalize_code(raw: str) -> Tuple[str, str, str]:
    """归一化股票代码 -> (6 位纯数字, baostock 格式, sina 格式)。

    接受: 600744 / sh.600744 / sz000975 / sh600744 / SH600744 / 6 位代码
    """
    s = str(raw or "").strip().upper().replace(" ", "")
    pure = re.sub(r"^(SH|SZ|BJ)\.?", "", s)
    if not re.match(r"^\d{6}$", pure):
        raise ValueError(f"无效股票代码: {raw}（需要 6 位数字，可带 sh/sz/bj 前缀）")
    if pure.startswith("6"):
        return pure, f"sh.{pure}", f"sh{pure}"
    if pure.startswith(("0", "3")):
        return pure, f"sz.{pure}", f"sz{pure}"
    if pure.startswith(("8", "4")):
        return pure, f"bj.{pure}", f"bj{pure}"
    return pure, pure, None


# ---------------- 巨潮抓撤销 ST 公告 ----------------
def _tz_cst(ts_ms: int) -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(ts_ms / 1000, tz=tz).strftime("%Y-%m-%d")


def _is_valid_resume(title_html: str) -> bool:
    if not title_html:
        return False
    clean = re.sub(r"<[^>]+>", "", title_html)
    return "撤销" in clean and ("风险警示" in clean or "ST" in clean.upper())


def _get_stock_info(pure_code: str) -> Optional[Dict[str, str]]:
    """从 cninfo topSearch 接口拿股票 orgId + 当前名称（已摘帽后的名字）。"""
    url = "http://www.cninfo.com.cn/new/information/topSearch/query"
    try:
        r = requests.post(url, data={"keyWord": pure_code, "maxNum": "10"},
                          headers={"User-Agent": UA,
                                   "Content-Type": "application/x-www-form-urlencoded"},
                          proxies=_proxies(), timeout=10)
        items = r.json()
        if isinstance(items, list):
            for it in items:
                if str(it.get("code", "")).upper() == pure_code.upper():
                    return {"orgId": str(it.get("orgId", "")),
                            "name": str(it.get("zwjc", "")) or pure_code}
    except Exception:
        pass
    return None


def crawl_cninfo_for_code(pure_code: str) -> Optional[Dict[str, str]]:
    """从巨潮抓该股票最新一条撤销 ST 公告，返回 {发布日期, 股票名称} 或 None。

    cninfo hisAnnouncement 接口的 stock 参数格式 = "code,orgId"
    （orgId 通过 topSearch 接口获取）。
    """
    info = _get_stock_info(pure_code)
    if not info or not info.get("orgId"):
        return None
    org_id = info["orgId"]
    name = info.get("name") or pure_code

    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    headers = {
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "http://www.cninfo.com.cn",
        "Referer": "http://www.cninfo.com.cn/new/fulltextSearch",
    }
    stock_param = f"{pure_code},{org_id}"
    candidates: List[Dict[str, Any]] = []
    for kw in ["撤销其他风险警示", "撤销退市风险警示"]:
        for page in range(1, 4):  # 单只股票最多翻 3 页
            data = {
                "pageNum": str(page), "pageSize": "30", "tabName": "fulltext",
                "searchkey": kw, "isHLtitle": "true", "stock": stock_param,
            }
            j: Dict[str, Any] = {}
            for attempt in range(2):
                try:
                    r = requests.post(url, data=data, headers=headers,
                                      proxies=_proxies(), timeout=15)
                    j = r.json()
                    break
                except Exception:
                    if attempt == 1:
                        j = {}
                        break
                    time.sleep(1)
            anns = j.get("announcements") or []
            if not anns:
                break
            for a in anns:
                if str(a.get("secCode", "")) != pure_code:
                    continue
                if not _is_valid_resume(a.get("announcementTitle")):
                    continue
                ts = a.get("announcementTime") or 0
                candidates.append({
                    "发布日期": _tz_cst(ts) if ts else "",
                    "ts": ts,
                })
            total = j.get("totalRecordNum", 0)
            if page * 30 >= total:
                break
            time.sleep(0.2)
    if not candidates:
        return None
    candidates.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return {"发布日期": candidates[0]["发布日期"], "股票名称": name}


# ---------------- 新浪历史 K 线 / 实时价 ----------------
def fetch_kline(sina_sym: str, datalen: int = 5000) -> List[Dict]:
    if not sina_sym:
        return []
    url = ("http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData")
    for _ in range(3):
        try:
            r = requests.get(url, params={"symbol": sina_sym, "scale": "240",
                                          "ma": "no", "datalen": str(datalen)},
                             proxies=_proxies(), timeout=15)
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception:
            time.sleep(1)
    return []


def fetch_realtime(sina_sym: str) -> Optional[float]:
    if not sina_sym:
        return None
    url = f"http://hq.sinajs.cn/list={sina_sym}"
    try:
        r = requests.get(url, headers={"Referer": "http://finance.sina.com.cn"},
                         proxies=_proxies(), timeout=15)
        m = re.match(r'var hq_str_\w+="(.+)"', r.text.strip())
        if not m:
            return None
        f = m.group(1).split(",")
        if len(f) >= 4:
            try:
                return float(f[3])
            except Exception:
                return None
    except Exception:
        pass
    return None


# ---------------- 摘帽日定位 + 涨幅计算 ----------------
def find_idx(klines: List[Dict], target: str) -> Optional[Tuple[int, str]]:
    if not klines or not target:
        return None
    dates = [k.get("day", "") for k in klines]
    if target in dates:
        return dates.index(target), target
    try:
        tdt = datetime.strptime(target, "%Y-%m-%d")
    except Exception:
        return None
    bi, bd = None, 999
    for i, d in enumerate(dates):
        try:
            ad = abs((datetime.strptime(d, "%Y-%m-%d") - tdt).days)
            if ad < bd:
                bd, bi = ad, i
        except Exception:
            pass
    if bd > 60:
        return None
    return bi, dates[bi]


def compute_all(klines: List[Dict], idx: int) -> Dict[str, Optional[float]]:
    """计算 前/后 [5,10,15,20] 交易日涨幅(%)。

    定义：摘帽日 = idx。
      前 nv 日涨幅 = (klines[idx-1].close - klines[idx-nv].close) / klines[idx-nv].close * 100
      后 nv 日涨幅 = (klines[idx+nv].close - klines[idx].close)   / klines[idx].close   * 100
    """
    if not klines or idx is None or idx < 0 or idx >= len(klines):
        return {}
    n = len(klines)
    try:
        uc = float(klines[idx]["close"])
    except Exception:
        return {}
    out: Dict[str, Optional[float]] = {}
    for nv in N_VALUES:
        ps = max(0, idx - nv)
        if ps < idx:
            try:
                a = float(klines[ps]["close"])
                b = float(klines[idx - 1]["close"])
                out[f"前{nv}"] = round((b - a) / a * 100, 2) if a != 0 else None
            except Exception:
                out[f"前{nv}"] = None
        else:
            out[f"前{nv}"] = None
        pe = min(n - 1, idx + nv)
        if pe > idx and uc != 0:
            try:
                z = float(klines[pe]["close"])
                out[f"后{nv}"] = round((z - uc) / uc * 100, 2)
            except Exception:
                out[f"后{nv}"] = None
        else:
            out[f"后{nv}"] = None
    return out


# ---------------- 单只股票处理 ----------------
def build_record(raw_code: str) -> Dict[str, Any]:
    """抓公告 + K 线 + 实时价 -> 构造一条 record。失败抛 ValueError。"""
    pure, bs, sina = normalize_code(raw_code)
    ann = crawl_cninfo_for_code(pure)
    if not ann:
        raise ValueError(f"巨潮未找到 {pure} 的撤销 ST 公告")
    pub_date = ann["发布日期"]
    name = ann["股票名称"] or pure

    klines = fetch_kline(sina, 5000)
    if not klines:
        raise ValueError(f"新浪历史 K 线获取失败: {sina}")

    r = find_idx(klines, pub_date)
    if r is None:
        raise ValueError(f"K 线中找不到接近公告日 {pub_date} 的交易日")
    idx, actual_date = r
    ch = compute_all(klines, idx)
    if not ch:
        raise ValueError(f"涨幅计算失败 idx={idx}")

    try:
        cc = round(float(klines[idx]["close"]), 3)
    except Exception:
        cc = None

    price = fetch_realtime(sina)
    # PE/PB 暂无来源，保留字段为 None，后续接入其它数据源
    return {
        "股票名称": name,
        "代码": bs,
        "最新价": price,
        "结束ST日期": actual_date,
        "摘帽日收盘价": cc,
        "市盈率": None,
        "市净率": None,
        **ch,
    }


def add_stock(raw_code: str) -> Dict[str, Any]:
    """添加/更新一只股票，返回新 record。"""
    rec = build_record(raw_code)
    data = load_data()
    records: List[Dict[str, Any]] = data.get("records", [])
    # 按 "代码" 去重
    records = [r for r in records if r.get("代码") != rec["代码"]]
    records.append(rec)
    records.sort(key=lambda x: x.get("结束ST日期", "") or "", reverse=True)
    data["records"] = records
    save_data(data)
    return rec


def delete_stock(raw_code: str) -> bool:
    """删除一只股票，返回是否真的删了。"""
    try:
        pure, bs, _ = normalize_code(raw_code)
    except ValueError:
        # 直接按字符串匹配
        pure, bs = raw_code, raw_code
    data = load_data()
    records = data.get("records", [])
    before = len(records)
    records = [r for r in records
               if r.get("代码") not in (bs, pure)
               and r.get("代码", "").replace(".", "") != pure]
    if len(records) == before:
        return False
    data["records"] = records
    save_data(data)
    return True
