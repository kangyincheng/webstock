"""基准测试：baostock 日K查询速度 + 验证 isST 1->0 检测真实摘帽股。"""
import socket, time

PROXY = ("127.0.0.1", 18080)
_orig_connect = socket.socket.connect


def patched_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(address, tuple) and host not in ("127.0.0.1", "localhost"):
        _orig_connect(self, PROXY)
        req = (f"CONNECT {address[0]}:{address[1]} HTTP/1.1\r\n"
               f"Host: {address[0]}:{address[1]}\r\n\r\n").encode()
        self.sendall(req)
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.recv(4096)
            if not chunk:
                break
            resp += chunk
        first = resp.split(b"\r\n", 1)[0]
        if b" 200" not in first:
            raise ConnectionError(f"CONNECT failed: {first!r}")
        return
    return _orig_connect(self, address)


socket.socket.connect = patched_connect

import baostock as bs

lg = bs.login()
assert lg.error_code == "0", lg.error_msg

# 1) 测速：20 只股票，13 个月日K
codes = ["sh.600000", "sh.600036", "sz.000001", "sz.000002", "sh.601318",
         "sz.300750", "sh.688981", "sh.600519", "sz.002594", "sh.601899",
         "sz.000858", "sh.600030", "sh.601166", "sz.002415", "sh.600276",
         "sz.300059", "sh.601012", "sz.002475", "sh.600809", "sz.000568"]
t0 = time.time()
nrows = 0
for c in codes:
    rs = bs.query_history_k_data_plus(
        c, "date,code,close,isST",
        start_date="2025-08-01", end_date="2026-08-28",
        frequency="d", adjustflag="2")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    nrows += len(rows)
dt = time.time() - t0
print(f"20 只耗时 {dt:.2f}s，平均每只 {dt/20*1000:.0f}ms，行数 {nrows}")
print(f"推算全市场 5500 只单线程 ≈ {dt/20*5500/60:.1f} 分钟")

# 2) 验证 isST 检测：找几只真实摘帽股
#    从当前 ST 股列表里挑几个老 ST，再看有没有 1->0
def find_transitions(code, start, end):
    rs = bs.query_history_k_data_plus(
        code, "date,code,close,isST",
        start_date=start, end_date=end, frequency="d", adjustflag="2")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    trans = []
    for i in range(1, len(rows)):
        if rows[i-1][3] == "1" and rows[i][3] == "0":
            trans.append(("uncap", rows[i][0]))
        elif rows[i-1][3] == "0" and rows[i][3] == "1":
            trans.append(("cap", rows[i][0]))
    return rows, trans

# 华银电力 2024 年摘帽（已知案例），以及随机测试几只在 2025-11 ~ 2026-08 窗口
for code in ["sh.600744", "sz.000975", "sh.600084", "sz.002759"]:
    rows, trans = find_transitions(code, "2024-01-01", "2026-08-28")
    print(code, "rows:", len(rows), "transitions:", trans[:6])

bs.logout()
