"""ST 恢复上市：找出当前交易中的 ST 股票，找到 ST 开始的日期，
ST 开始日 + 1 个日历年 = 可申请摘帽日。

数据源：
  1. 新浪 VIP 接口拉全市场 A 股实时行情，筛选名称含 ST 的
  2. 巨潮资讯公告接口按股票代码 + 关键词 "实施其他风险警示" 查公告，
     最老的"被实施其他风险警示"公告 = ST 开始日
     （排除进展/提示性/叠加等后续公告）

输出字段：
  股票名称 / 代码 / ST开始日期 / 可申请摘帽日 / 距可申请天数 /
  最新价 / PE / PB / 换手率 / 市值(亿)
"""

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

PROXIES = {"http": os.environ.get("HTTP_PROXY"), "https": os.environ.get("HTTPS_PROXY")}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# ST 开始公告的标题里应包含这些词，表示"第一次被实施"
_START_KEYWORDS = ["实施其他风险警示", "实施退市风险警示"]
# 需要排除的后续公告关键词（仅当标题**没有**已实施的被动句式时才检查）
_EXCLUDE_KEYWORDS = [
    # 专门的风险提示公告（不是正式实施公告，标题以"风险提示公告"结尾）
    "风险提示公告",
    # 进展/后续公告（最常见，必排除）
    "进展公告",
    "实施其他风险警示相关事项的进展",
    "实施退市风险警示相关事项的进展",
    "其他风险警示相关事项进展",
    "退市风险警示相关事项进展",
    # 叠加（不算新 ST 开始）
    "叠加实施", "被叠加实施",
    # 撤销/终止（反向操作）
    "撤销ST", "撤销 ST",
    # 其他明显的后续/操作公告
    "法律意见", "核查意见", "监管函",
]

# 已实施的被动句式：前面不能有"可能/拟/将"等修饰词
# 否则"可能被实施"这种风险提示公告也会被误判
_ACTUAL_IMPLEMENTED_RE = re.compile(
    r"(?:^|[^\s可能将拟])被实施(?:其他风险警示|退市风险警示)"
)

# 撤销 ST（即摘帽）公告的匹配条件：同时包含"撤销" + "风险警示"
_RESOLVE_RE = re.compile(r"撤销.*(?:风险警示|其他特别处理|ST)")
# 撤销公告中的"部分撤销/继续实施/申请撤销"不算真摘帽
_RESOLVE_EXCLUDE = ["部分", "继续实施", "继续被实施", "申请撤销", "可能撤销",
                    "终止实施"]


def _proxies() -> Optional[dict]:
    p = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    return {"http": p, "https": p} if p else None


def _cn_to_bs(code: str) -> str:
    if code.startswith("6"): return f"sh.{code}"
    if code.startswith(("0", "3")): return f"sz.{code}"
    if code.startswith(("8", "4", "9")): return f"bj.{code}"
    return code


def _cn_to_sina(code: str) -> Optional[str]:
    if code.startswith("6"): return f"sh{code}"
    if code.startswith(("0", "3")): return f"sz{code}"
    if code.startswith(("8", "4", "9")): return f"bj{code}"
    return None


def _tz_cst(ts_ms: int) -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(ts_ms / 1000, tz=tz).strftime("%Y-%m-%d")


def _add_one_year(date_str: str) -> str:
    """日期 + 1 个日历年（2 月 29 → 次年 2 月 28）。"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    try:
        nd = d.replace(year=d.year + 1)
    except ValueError:
        nd = d.replace(year=d.year + 1, day=28)
    return nd.strftime("%Y-%m-%d")


# ---------------- 1. 新浪 VIP 拉全市场 A 股 ----------------
def fetch_sina_all() -> List[Dict[str, Any]]:
    """遍历新浪 VIP 接口所有页，返回名称含 ST 的股票。"""
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    items: List[Dict[str, Any]] = []
    page = 1
    while True:
        params = {"page": str(page), "num": "80", "sort": "symbol", "asc": "1",
                  "node": "hs_a", "symbol": "", "_s_r_a": "auto"}
        data: List[Dict[str, Any]] = []
        for _ in range(3):
            try:
                r = requests.get(url, params=params, headers={"User-Agent": UA},
                                 proxies=_proxies(), timeout=15)
                data = r.json()
                if isinstance(data, list):
                    break
                data = []
            except Exception:
                time.sleep(1)
        if not data:
            break
        items.extend(data)
        if len(data) < 80:
            break
        page += 1
        time.sleep(0.1)
    return items


# ---------------- 2. 巨潮查 ST 开始日 ----------------
def _get_stock_info(pure_code: str) -> Optional[Dict[str, str]]:
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


def find_st_start_date(pure_code: str) -> Optional[str]:
    """从巨潮公告里找到"当前这一轮 ST 开始"的日期。

    策略：
      1. 搜"实施其他风险警示" + "实施退市风险警示"，收集所有"ST 开始"公告
      2. 搜"撤销其他风险警示" + "撤销退市风险警示"（即摘帽公告）
      3. 取：所有 ST 开始公告中，日期 **晚于最后一次摘帽公告** 的那条
         （如果没有任何摘帽公告，取最老的 ST 开始公告 — 说明一直 ST）
    """
    info = _get_stock_info(pure_code)
    if not info or not info.get("orgId"):
        return None
    org_id = info["orgId"]
    stock_param = f"{pure_code},{org_id}"

    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    headers = {
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "http://www.cninfo.com.cn",
        "Referer": "http://www.cninfo.com.cn/new/fulltextSearch",
    }

    st_start_ts: List[int] = []      # 所有 ST 开始公告的时间戳
    st_resolve_ts: List[int] = []    # 所有 ST 撤销（摘帽）公告的时间戳

    def _collect(keywords, target_list):
        for kw in keywords:
            for page in range(1, 3):
                data = {
                    "pageNum": str(page), "pageSize": "30", "tabName": "fulltext",
                    "searchkey": kw, "isHLtitle": "true", "stock": stock_param,
                }
                j: Dict[str, Any] = {}
                for _ in range(2):
                    try:
                        r = requests.post(url, data=data, headers=headers,
                                          proxies=_proxies(), timeout=15)
                        j = r.json()
                        break
                    except Exception:
                        time.sleep(1)
                anns = j.get("announcements") or []
                if not anns:
                    break
                for a in anns:
                    if str(a.get("secCode", "")) != pure_code:
                        continue
                    title = re.sub(r"<[^>]+>", "", a.get("announcementTitle", ""))
                    ts = a.get("announcementTime") or 0
                    if ts and _matches_keywords(title, kw):
                        target_list.append(ts)
                time.sleep(0.15)

    _collect(["实施其他风险警示", "实施退市风险警示"], st_start_ts)
    _collect(["撤销其他风险警示", "撤销退市风险警示", "摘帽"], st_resolve_ts)

    if not st_start_ts:
        return None

    last_resolve = max(st_resolve_ts) if st_resolve_ts else 0
    # 取 st_start_ts 中 > last_resolve 的最小那个（即摘帽后第一次 ST）
    candidates = [ts for ts in st_start_ts if ts > last_resolve]
    if candidates:
        best_ts = min(candidates)
    else:
        # 所有 ST 都被撤销过（理论上不该出现），取最老的
        best_ts = min(st_start_ts)

    return _tz_cst(best_ts)


def _matches_keywords(title: str, kw: str) -> bool:
    """粗筛：ST 开始 / 撤销公告的匹配。"""
    if not title:
        return False
    if kw.startswith("实施"):
        # ST 开始公告
        if not any(k in title for k in _START_KEYWORDS):
            return False
        # 如果标题有"已实施"的被动句式 → 直接算真实施公告（忽略排除词）
        # 因为后面的"暨可能被实施"只是后续风险提示
        if _ACTUAL_IMPLEMENTED_RE.search(title):
            return True
        # 没有被动句式的，严格检查排除词（风险提示公告等）
        for excl in _EXCLUDE_KEYWORDS:
            if excl in title:
                return False
        return True
    else:
        # 撤销 / 摘帽公告 — 用正则放宽
        if not (_RESOLVE_RE.search(title) or "摘帽" in title):
            return False
        # 排除"部分撤销"、"继续被实施"等
        for excl in _RESOLVE_EXCLUDE:
            if excl in title:
                return False
        return True


# ---------------- 3. 主流程 ----------------
def scan_all() -> List[Dict[str, Any]]:
    """扫描全市场 ST 股票 → 找 ST 开始日 → 算可申请摘帽日。"""
    print("[ST-Time] 新浪 VIP 拉全市场...")
    all_items = fetch_sina_all()
    print(f"  共 {len(all_items)} 只")

    st_raw = [it for it in all_items if (it.get("name") or "").upper().find("ST") >= 0]
    print(f"[ST-Time] 名称含 ST: {len(st_raw)} 只")

    if not st_raw:
        return []

    # 多线程查每只 ST 的开始日期
    def _proc(it):
        pure = str(it.get("code", ""))
        if not pure:
            return None
        try:
            start_date = find_st_start_date(pure)
        except Exception:
            start_date = None
        if not start_date:
            return None
        reinstate = _add_one_year(start_date)
        trade_val = float(it.get("trade", 0) or 0)
        pe = it.get("per")
        pb = it.get("pb")
        turnover = it.get("turnoverratio")
        mktcap = float(it.get("mktcap", 0) or 0)  # 万元
        return {
            "股票名称": it.get("name", ""),
            "代码": _cn_to_bs(pure),
            "_code": pure,
            "ST开始日期": start_date,
            "可申请摘帽日": reinstate,
            "最新价": trade_val or None,
            "市盈率": float(pe) if pe not in (None, "") else None,
            "市净率": float(pb) if pb not in (None, "") else None,
            "换手率": float(turnover) if turnover not in (None, "") else None,
            "市值亿": round(mktcap / 10000, 2) if mktcap else None,
        }

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_proc, it): it for it in st_raw}
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                r = fut.result()
                if r:
                    results.append(r)
            except Exception:
                pass
            if done % 10 == 0 or done == len(st_raw):
                print(f"  {done}/{len(st_raw)}  有效={len(results)}")

    # 距可申请天数
    today = datetime.now().strftime("%Y-%m-%d")
    for r in results:
        try:
            diff = (datetime.strptime(r["可申请摘帽日"], "%Y-%m-%d")
                    - datetime.strptime(today, "%Y-%m-%d")).days
            r["距可申请天数"] = diff
        except Exception:
            r["距可申请天数"] = None

    # 排序：最接近可申请日的在前
    results.sort(key=lambda x: x.get("距可申请天数") or 99999)
    return results


if __name__ == "__main__":
    import json
    from datetime import datetime
    import os
    results = scan_all()
    out = {
        "records": results,
        "logs": [f"扫描 {len(results)} 只 ST 股票",
                 f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
    }
    os.makedirs("/var/www/webstock/backend/data", exist_ok=True)
    with open("/var/www/webstock/backend/data/st_time_results.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已保存 {len(results)} 只")
