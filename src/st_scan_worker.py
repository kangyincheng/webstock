"""ST 摘帽扫描子进程工作脚本。

由 STAnalyzer.scan_and_analyze 通过 subprocess 启动（每个进程一个独立的
baostock 会话），不依赖 multiprocessing 的 spawn/fork —— 在 gunicorn /
uvicorn 多线程宿主内也绝对安全。

协议：
  输入：argv = [buffer_start, win_start, win_end, before_days, after_days]
        stdin = JSON 数组 [[code, name], ...]
  输出：stdout 逐行 JSON：
        {"type":"progress","done":N}
        {"type":"result","row":{...}}
        {"type":"fatal","message":"..."}
"""
import json
import sys

from st_analyzer import (_import_baostock, _fetch_kline, _find_last_uncap,
                         _compute_change)


def _emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main():
    buffer_start, win_start, win_end = sys.argv[1], sys.argv[2], sys.argv[3]
    before_days, after_days = int(sys.argv[4]), int(sys.argv[5])
    tasks = json.load(sys.stdin)

    bs = _import_baostock()
    lg = bs.login()
    if lg.error_code != "0":
        _emit({"type": "fatal", "message": f"baostock login failed: {lg.error_msg}"})
        sys.exit(1)

    total = len(tasks)
    done = 0
    try:
        for code, name in tasks:
            row = None
            try:
                df = None
                for _attempt in range(2):  # 失败重试一次
                    df = _fetch_kline(bs, code, buffer_start, win_end)
                    if df is not None:
                        break
                if df is not None and not df.empty:
                    info = _find_last_uncap(df, win_start, win_end)
                    if info:
                        uncap_date, st_start = info
                        chg = _compute_change(df, uncap_date, before_days, after_days)
                        if chg is not None:
                            pre_change, post_change, close, pe, pb = chg
                            row = {
                                "股票名称": name,
                                "代码": code,
                                "开始ST日期": st_start,
                                "结束ST日期": uncap_date,
                                "摘帽前涨幅": round(pre_change, 2),
                                "摘帽后涨幅": round(post_change, 2) if post_change is not None else None,
                                "市盈率": round(pe, 2) if pe is not None else None,
                                "市净率": round(pb, 2) if pb is not None else None,
                                "收盘价": round(close, 3) if close is not None else None,
                            }
            except Exception:
                row = None
            if row is not None:
                _emit({"type": "result", "row": row})
            done += 1
            if done % 50 == 0 or done == total:
                _emit({"type": "progress", "done": done})
    finally:
        try:
            bs.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()
