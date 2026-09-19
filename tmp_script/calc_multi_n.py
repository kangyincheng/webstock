#!/usr/bin/env python3
"""重新计算 637 只摘帽股票的前后 N 日涨幅（N∈[5,10,15,20]）。"""
import os, json, time, re, csv, sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

PROXY = {"http": os.environ.get("HTTP_PROXY"), "https": os.environ.get("HTTPS_PROXY")}
N_VALUES = [5, 10, 15, 20]

def cn_code_to_sina(code):
    code = str(code).strip()
    if code.startswith("6"): return f"sh{code}"
    elif code.startswith("0") or code.startswith("3"): return f"sz{code}"
    elif code.startswith("8") or code.startswith("4"): return f"bj{code}"
    return None

def cn_code_to_baostock(code):
    code = str(code).strip()
    if code.startswith("6"): return f"sh.{code}"
    elif code.startswith("0") or code.startswith("3"): return f"sz.{code}"
    elif code.startswith("8") or code.startswith("4"): return f"bj.{code}"
    return code

def fetch_kline(code, datalen=5000):
    sym = cn_code_to_sina(code)
    if not sym: return []
    url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": sym, "scale": "240", "ma": "no", "datalen": str(datalen)}
    for _ in range(3):
        try:
            r = requests.get(url, params=params, proxies=PROXY, timeout=15)
            data = r.json()
            if isinstance(data, list) and data: return data
            return []
        except Exception:
            time.sleep(1)
    return []

def fetch_realtime(codes):
    syms = [cn_code_to_sina(c) for c in codes]
    syms = [s for s in syms if s]
    if not syms: return {}
    url = "http://hq.sinajs.cn/list=" + ",".join(syms)
    headers = {"Referer": "http://finance.sina.com.cn"}
    result = {}
    try:
        r = requests.get(url, headers=headers, proxies=PROXY, timeout=15)
        for line in r.text.strip().split("\n"):
            m = re.match(r'var hq_str_(\w+)="(.+)"', line.strip())
            if not m: continue
            pure_code = m.group(1)[2:]
            fields = m.group(2).split(",")
            if len(fields) < 4: continue
            try: result[pure_code] = float(fields[3])
            except: pass
    except Exception: pass
    return result

def find_uncap_index(klines, uncap_date_str):
    if not klines: return None
    dates = [k["day"] for k in klines]
    if uncap_date_str in dates:
        return dates.index(uncap_date_str), uncap_date_str
    uncap_dt = datetime.strptime(uncap_date_str, "%Y-%m-%d")
    best_idx, best_diff = None, float("inf")
    for i, d in enumerate(dates):
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            ad = abs((dt - uncap_dt).days)
            if ad < best_diff: best_diff, best_idx = ad, i
        except: pass
    if best_diff > 60: return None
    return best_idx, dates[best_idx]

def compute_all_changes(klines, uncap_idx):
    if not klines or uncap_idx is None: return {}
    n = len(klines)
    try: uncap_close = float(klines[uncap_idx]["close"])
    except: return {}

    result = {}
    for nv in N_VALUES:
        pre_start = max(0, uncap_idx - nv)
        if pre_start < uncap_idx:
            try:
                ps = float(klines[pre_start]["close"])
                pe = float(klines[uncap_idx - 1]["close"])
                result[f"前{nv}"] = round((pe - ps) / ps * 100, 2) if ps != 0 else None
            except: result[f"前{nv}"] = None
        else: result[f"前{nv}"] = None

        post_end = min(n - 1, uncap_idx + nv)
        if post_end > uncap_idx and uncap_close != 0:
            try:
                pn = float(klines[post_end]["close"])
                result[f"后{nv}"] = round((pn - uncap_close) / uncap_close * 100, 2)
            except: result[f"后{nv}"] = None
        else: result[f"后{nv}"] = None
    return result

def process_one(stock):
    code = stock["股票代码"]
    name = stock["当前名称"]
    klines = fetch_kline(code, 5000)
    if not klines: return None
    r = find_uncap_index(klines, stock["发布日期"])
    if r is None: return None
    uncap_idx, actual_date = r
    changes = compute_all_changes(klines, uncap_idx)
    if not changes: return None
    try: uncap_close = round(float(klines[uncap_idx]["close"]), 3)
    except: uncap_close = None
    return {
        "股票名称": name, "代码": cn_code_to_baostock(code),
        "纯数字代码": code, "结束ST日期": actual_date,
        "摘帽日收盘价": uncap_close, **changes,
    }

def main():
    with open("/tmp/st_resumed_clean.json") as f:
        stocks = json.load(f)
    print(f"加载 {len(stocks)} 只  N={N_VALUES}")
    print("=" * 70)

    results, start = [], time.time()
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(process_one, s): s for s in stocks}
        done = 0
        for fut in as_completed(futures):
            done += 1
            try:
                rec = fut.result()
                if rec: results.append(rec)
            except: pass
            if done % 100 == 0 or done == len(stocks):
                print(f"  {done}/{len(stocks)}  有效={len(results)}  ({time.time()-start:.1f}s)")

    print(f"\nK线完成 {len(results)} 只  ({time.time()-start:.1f}s)")

    print("批量获取最新价...")
    all_codes = [r["纯数字代码"] for r in results]
    latest = {}
    for i in range(0, len(all_codes), 50):
        batch = all_codes[i:i+50]
        latest.update(fetch_realtime(batch))
        time.sleep(0.3)
    for r in results:
        r["最新价"] = latest.get(r["纯数字代码"])
        r.pop("纯数字代码", None)

    results.sort(key=lambda x: x.get("结束ST日期", ""), reverse=True)

    out = {
        "records": results,
        "logs": [
            f"数据源: 新浪财经历史K线 + 实时行情",
            f"计算: 摘帽前{N_VALUES}交易日 / 摘帽后{N_VALUES}交易日",
            f"共 {len(results)} 只已摘帽股票",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ],
        "n_values": N_VALUES,
    }
    out_json = "/workspace/backend/data/st_scan_results.json"
    with open(out_json, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已保存: {out_json} ({len(results)} 只)")

    if results:
        for nv in N_VALUES:
            pv = [r[f"前{nv}"] for r in results if r.get(f"前{nv}") is not None]
            qv = [r[f"后{nv}"] for r in results if r.get(f"后{nv}") is not None]
            pa = sum(pv)/len(pv) if pv else 0
            qa = sum(qv)/len(qv) if qv else 0
            print(f"  N={nv:2d}: 前 avg={pa:+6.2f}% (上涨{sum(1 for x in pv if x>0)}/{len(pv)})  |  后 avg={qa:+6.2f}% (上涨{sum(1 for x in qv if x>0)}/{len(qv)})")

    print("\n前10条:")
    for r in results[:10]:
        print(f"  {r['股票名称']}({r['代码']})  {r['结束ST日期']}  前5={r['前5']:>7} 前10={r['前10']:>7} 后5={r['后5']:>7} 后10={r['后10']:>7}")

if __name__ == "__main__":
    main()
