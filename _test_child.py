"""调试：直接测试 spawn 子进程内的 baostock 登录与取数。"""
import multiprocessing


def child(code):
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        return f"{code}: LOGIN FAIL {lg.error_code} {lg.error_msg}"
    try:
        rs = bs.query_history_k_data_plus(
            code, "date,code,close,isST",
            start_date="2025-08-01", end_date="2026-08-28",
            frequency="d", adjustflag="2")
        n = 0
        while rs.error_code == "0" and rs.next():
            rs.get_row_data()
            n += 1
        return f"{code}: ok rows={n} err={rs.error_code} {rs.error_msg}"
    finally:
        try:
            bs.logout()
        except Exception:
            pass


if __name__ == "__main__":
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(2) as p:
        out = p.map(child, ["sh.600744", "sz.002759"])
    for o in out:
        print(o)
