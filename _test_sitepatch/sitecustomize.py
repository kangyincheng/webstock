"""测试专用：让 spawn 出来的子进程也走 HTTP CONNECT 代理隧道访问 baostock。
通过 PYTHONPATH 指向本目录，Python 启动时自动导入 sitecustomize。"""
import os
import socket

PROXY_HOST = os.environ.get("BS_PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.environ.get("BS_PROXY_PORT", "18080"))

_orig_connect = socket.socket.connect


def patched_connect(self, address):
    if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "localhost"):
        _orig_connect(self, (PROXY_HOST, PROXY_PORT))
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
