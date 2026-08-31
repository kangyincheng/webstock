"""通过 HTTP CONNECT 代理隧道访问 baostock，验证 query_all_stock 历史名称行为。"""
import socket

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
print("login:", lg.error_code, lg.error_msg)
if lg.error_code != "0":
    raise SystemExit(1)


def snap(day):
    rs = bs.query_all_stock(day=day)
    print(f"--- query_all_stock({day}) err={rs.error_code} {rs.error_msg}")
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    print("rows:", len(rows), "fields:", rs.fields)
    return rows


# 最新交易日 与 9个月前
latest = snap("2026-08-28")
old = snap("2025-12-04")

st_latest = [r for r in latest if "ST" in str(r[2]).upper()]
st_old = [r for r in old if "ST" in str(r[2]).upper()]
print("latest ST count:", len(st_latest), "sample:", st_latest[:5])
print("old ST count:", len(st_old), "sample:", st_old[:5])

# 关键验证：old 快照里名称是否与 latest 完全一致（判断是否返回"当前名称"）
latest_map = {r[0]: r[2] for r in latest}
same = diff = 0
diff_samples = []
for r in old:
    nm_new = latest_map.get(r[0])
    if nm_new is None:
        continue
    if nm_new == r[2]:
        same += 1
    else:
        diff += 1
        if len(diff_samples) < 20:
            diff_samples.append((r[0], r[2], nm_new))
print(f"名称相同: {same}, 名称不同: {diff}")
print("名称不同样本:", diff_samples)

bs.logout()
