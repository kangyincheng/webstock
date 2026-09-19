"""完整流水线：巨潮抓摘帽公告 → 新浪过滤仍ST → 多N涨幅计算 → 保存。"""
import os, json, time, re, csv, sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

PROXY = {"http": os.environ.get("HTTP_PROXY"), "https": os.environ.get("HTTPS_PROXY")}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
N_VALUES = [5, 10, 15, 20]
OUT = "/workspace/backend/data/st_scan_results.json"
os.makedirs(os.path.dirname(OUT), exist_ok=True)

# ============== Part 1: 巨潮抓摘帽公告 ==============
print("[1/4] 巨潮抓摘帽公告...")

def tz_cst(ts_ms):
    from datetime import timezone, timedelta
    tz = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(ts_ms/1000, tz=tz).strftime("%Y-%m-%d")

def crawl_cninfo(keyword, column, max_pages=120):
    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    headers = {
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "http://www.cninfo.com.cn",
        "Referer": "http://www.cninfo.com.cn/new/fulltextSearch",
    }
    results, last_len = [], 0
    for page in range(1, max_pages + 1):
        data = {
            "pageNum": str(page), "pageSize": "30", "column": column,
            "tabName": "fulltext", "searchkey": keyword, "isHLtitle": "true",
        }
        for attempt in range(3):
            try:
                r = requests.post(url, data=data, headers=headers, proxies=PROXY, timeout=20)
                j = r.json()
                break
            except Exception as e:
                if attempt == 2: return results
                time.sleep(2)
        anns = j.get("announcements") or []
        if not anns: break
        results.extend(anns)
        total = j.get("totalRecordNum", 0)
        if len(results) >= total or len(results) == last_len: break
        last_len = len(results)
        time.sleep(0.2)
    return results

all_anns = {}
for kw in ["撤销其他风险警示", "撤销退市风险警示"]:
    for col in ["szse", "sse"]:
        anns = crawl_cninfo(kw, col)
        for a in anns:
            aid = a.get("announcementId")
            if aid and aid not in all_anns: all_anns[aid] = a
        print(f"  kw={kw[:6]} col={col}: +{len(anns)}  累计={len(all_anns)}")

def is_valid_resume(title_html):
    if not title_html: return False
    clean = re.sub(r'<[^>]+>', '', title_html)
    return ("撤销" in clean) and ("风险警示" in clean or "ST" in clean.upper())

stock_candidates = {}
for a in all_anns.values():
    if not is_valid_resume(a.get("announcementTitle")): continue
    code = str(a.get("secCode", ""))
    if not code or code in stock_candidates: continue
    name = re.sub(r'<[^>]+>', '', a.get("secName", ""))
    ts = a.get("announcementTime") or 0
    pub_date = tz_cst(ts) if ts else ""
    stock_candidates[code] = {"股票代码": code, "当前名称": name, "发布日期": pub_date}

cand_list = list(stock_candidates.values())
print(f"候选摘帽股: {len(cand_list)} 只")

# ============== Part 2: 新浪过滤今天仍ST ==============
print("\n[2/4] 新浪过滤今天仍ST的...")
def fetch_sina_all(page_num, num=80):
    url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {"page": str(page_num), "num": str(num), "sort": "symbol", "asc": "1",
              "node": "hs_a", "symbol": "", "_s_r_a": "auto"}
    for _ in range(3):
        try:
            r = requests.get(url, params=params, proxies=PROXY, timeout=15)
            data = r.json()
            if isinstance(data, list): return data
            return []
        except Exception:
            time.sleep(1)
    return []

st_map = {}
page = 1
while True:
    items = fetch_sina_all(page)
    if not items: break
    for it in items:
        code = str(it.get("code", ""))
        name = str(it.get("name", ""))
        if name and "ST" in name.upper(): st_map[code] = name
    page += 1
    time.sleep(0.1)

print(f"今天仍ST的: {len(st_map)} 只")
# 过滤
resumed = [s for s in cand_list if s["股票代码"] not in st_map]
print(f"已摘帽(过滤后): {len(resumed)} 只  (去掉 {len(cand_list)-len(resumed)} 只仍ST)")

# ============== Part 3: 多N涨幅计算 ==============
print(f"\n[3/4] 计算 N={N_VALUES} 交易日涨幅...")

def cn_to_sina(code):
    if code.startswith("6"): return f"sh{code}"
    elif code.startswith("0") or code.startswith("3"): return f"sz{code}"
    elif code.startswith("8") or code.startswith("4"): return f"bj{code}"
    return None

def cn_to_bs(code):
    if code.startswith("6"): return f"sh.{code}"
    elif code.startswith("0") or code.startswith("3"): return f"sz.{code}"
    elif code.startswith("8") or code.startswith("4"): return f"bj.{code}"
    return code

def fetch_kline(code, datalen=5000):
    sym = cn_to_sina(code)
    if not sym: return []
    url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    for _ in range(3):
        try:
            r = requests.get(url, params={"symbol": sym, "scale": "240", "ma": "no", "datalen": str(datalen)},
                           proxies=PROXY, timeout=15)
            data = r.json()
            if isinstance(data, list) and data: return data
            return []
        except: time.sleep(1)
    return []

def fetch_realtime(codes):
    syms = [cn_to_sina(c) for c in codes]
    syms = [s for s in syms if s]
    if not syms: return {}
    url = "http://hq.sinajs.cn/list=" + ",".join(syms)
    result = {}
    try:
        r = requests.get(url, headers={"Referer": "http://finance.sina.com.cn"}, proxies=PROXY, timeout=15)
        for line in r.text.strip().split("\n"):
            m = re.match(r'var hq_str_(\w+)="(.+)"', line.strip())
            if not m: continue
            pure = m.group(1)[2:]
            f = m.group(2).split(",")
            if len(f) >= 4:
                try: result[pure] = float(f[3])
                except: pass
    except: pass
    return result

def find_idx(klines, target):
    if not klines: return None
    dates = [k["day"] for k in klines]
    if target in dates: return dates.index(target), target
    tdt = datetime.strptime(target, "%Y-%m-%d")
    bi, bd = None, 999
    for i, d in enumerate(dates):
        try:
            ad = abs((datetime.strptime(d, "%Y-%m-%d") - tdt).days)
            if ad < bd: bd, bi = ad, i
        except: pass
    if bd > 60: return None
    return bi, dates[bi]

def compute_all(klines, idx):
    if not klines or idx is None: return {}
    n = len(klines)
    try: uc = float(klines[idx]["close"])
    except: return {}
    r = {}
    for nv in N_VALUES:
        ps = max(0, idx - nv)
        if ps < idx:
            try:
                a, b = float(klines[ps]["close"]), float(klines[idx-1]["close"])
                r[f"前{nv}"] = round((b-a)/a*100, 2) if a != 0 else None
            except: r[f"前{nv}"] = None
        else: r[f"前{nv}"] = None
        pe = min(n-1, idx + nv)
        if pe > idx and uc != 0:
            try:
                z = float(klines[pe]["close"])
                r[f"后{nv}"] = round((z-uc)/uc*100, 2)
            except: r[f"后{nv}"] = None
        else: r[f"后{nv}"] = None
    return r

def proc(stock):
    code = stock["股票代码"]
    klines = fetch_kline(code, 5000)
    if not klines: return None
    r = find_idx(klines, stock["发布日期"])
    if r is None: return None
    idx, actual_date = r
    ch = compute_all(klines, idx)
    if not ch: return None
    try: cc = round(float(klines[idx]["close"]), 3)
    except: cc = None
    return {"股票名称": stock["当前名称"], "代码": cn_to_bs(code),
            "_code": code, "结束ST日期": actual_date, "摘帽日收盘价": cc, **ch}

results = []
start = time.time()
with ThreadPoolExecutor(max_workers=12) as ex:
    futs = {ex.submit(proc, s): s for s in resumed}
    done = 0
    for fut in as_completed(futs):
        done += 1
        try:
            r = fut.result()
            if r: results.append(r)
        except: pass
        if done % 100 == 0 or done == len(resumed):
            print(f"  {done}/{len(resumed)}  有效={len(results)}  ({time.time()-start:.1f}s)")
print(f"K线完成: {len(results)} 只  ({time.time()-start:.1f}s)")

# 批量最新价
print("批量获取最新价...")
for i in range(0, len(results), 50):
    batch = [r["_code"] for r in results[i:i+50]]
    m = fetch_realtime(batch)
    for r in results[i:i+50]:
        r["最新价"] = m.get(r["_code"])
        r.pop("_code", None)
    time.sleep(0.3)

results.sort(key=lambda x: x.get("结束ST日期", ""), reverse=True)

# ============== Part 4: 保存 ==============
out = {
    "records": results,
    "logs": [
        f"数据源: 巨潮资讯(公告) + 新浪财经(实时行情+历史K线)",
        f"计算: 摘帽前{N_VALUES}交易日 / 摘帽后{N_VALUES}交易日",
        f"共 {len(results)} 只已摘帽股票",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ],
    "n_values": N_VALUES,
    "pre_select": 15,
    "post_select": 15,
}
with open(OUT, "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\n✅ 已保存: {OUT}  ({len(results)} 只)")

# 统计
for nv in N_VALUES:
    pv = [r[f"前{nv}"] for r in results if r.get(f"前{nv}") is not None]
    qv = [r[f"后{nv}"] for r in results if r.get(f"后{nv}") is not None]
    pa = sum(pv)/len(pv) if pv else 0
    qa = sum(qv)/len(qv) if qv else 0
    print(f"  N={nv:2d}: 前 avg={pa:+6.2f}% (上涨{sum(1 for x in pv if x>0)}/{len(pv)})  |  后 avg={qa:+6.2f}% (上涨{sum(1 for x in qv if x>0)}/{len(qv)})")

print("\n前10条:")
for r in results[:10]:
    print(f"  {r['股票名称']}({r['代码']})  摘帽={r['结束ST日期']}  最新价={r.get('最新价','-')}  "
          f"前5={r['前5']:>7} 前10={r['前10']:>7} 前15={r['前15']:>7} 前20={r['前20']:>7}  "
          f"后5={r['后5']:>7} 后10={r['后10']:>7} 后15={r['后15']:>7} 后20={r['后20']:>7}")
