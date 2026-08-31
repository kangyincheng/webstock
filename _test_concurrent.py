"""测试 baostock 多会话并发是否可行。"""
import socket, time
from concurrent.futures import ThreadPoolExecutor

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

codes = [f"sh.60{str(i).zfill(4)}" for i in range(0, 40)]


def worker(code):
    import baostock as b
    lg = b.login()
    if lg.error_code != "0":
        return code, -1, lg.error_msg
    try:
        rs = b.query_history_k_data_plus(
            code, "date,code,isST",
            start_date="2025-08-01", end_date="2026-08-28",
            frequency="d", adjustflag="2")
        n = 0
        while rs.error_code == "0" and rs.next():
            rs.get_row_data()
            n += 1
        return code, n, rs.error_msg
    finally:
        try:
            b.logout()
        except Exception:
            pass


t0 = time.time()
with ThreadPoolExecutor(max_workers=8) as ex:
    results = list(ex.map(worker, codes))
dt = time.time() - t0
ok = sum(1 for _, n, e in results if n >= 0)
err = [(c, e) for c, n, e in results if n < 0]
print(f"8 线程并发 40 只：{dt:.2f}s，成功 {ok}，失败 {err[:3]}")
print(f"推算全市场 5500 只 ≈ {dt/40*5500/60:.1f} 分钟")
