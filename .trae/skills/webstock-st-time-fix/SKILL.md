---
name: "webstock-st-time-fix"
description: "ST股「距可申请天数」实时计算 + sandbox 代理部署流程。当生产 ST 股天数显示错误、数据文件需要更新、或 sandbox→production SSH 隧道被墙时调用。"
---

# ST 股「距可申请天数」实时计算 + 代理部署

本 skill 沉淀 webstock 项目中 **ST 股摘帽时间模块** 的完整修复经验：从代码 bug 定位、sandbox 生成数据、到 production 部署的全链路。

## 触发场景

- **生产 bug**：`/api/market/st/time` 返回的「距可申请天数」显示旧值（如 4 天而非正确的 350+ 天）
- **数据不全**：JSON 里只有 8 条有「可申请摘帽日」，应该有 200+ 条
- **sandbox 网络受限**：不能直接 SSH production，但有 HTTP 代理（127.0.0.1:18080）
- **巨潮 API 被封**：production 上巨潮空响应，需要从 sandbox 生成数据再传过去

---

## Part 1：代码修复（market.py + st_time_service.py）

### 根因

```
JSON 文件里存了预计算的「距可申请天数」快照
       ↓
时间流逝，快照变旧（4 天前 = 当时是 4 天，今天应该是 4-N 天）
       ↓
缓存命中路径直接 return cached（带旧天数）
       ↓
前端看到错误值
```

### 修复方案

**核心思路：JSON 只存数据源，天数每次请求时实时算。**

#### 1. market.py 加 `_recalc_days()`

```python
def _recalc_days(records: list) -> None:
    """实时重算每条记录的「距可申请天数」（原地修改）。"""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _cst = _tz(_td(hours=8))
    today_str = _dt.now(_cst).strftime("%Y-%m-%d")
    for r in records:
        apply = r.get("可申请摘帽日")
        if apply and isinstance(apply, str):
            try:
                r["距可申请天数"] = (
                    _dt.strptime(apply, "%Y-%m-%d")
                    - _dt.strptime(today_str, "%Y-%m-%d")
                ).days
            except Exception:
                r["距可申请天数"] = None
        else:
            r["距可申请天数"] = None
```

**强制用 CST（UTC+8）** 是因为 sandbox UTC 时区会让 `datetime.now()` 算成 UTC 日期，和国内时区差 8 小时。

#### 2. 缓存命中路径也要重算

```python
cached = cache.get_json(cache_key)

if cached is not None:
    records = cached.get("records") or []
    _recalc_days(records)          # ← 缓存也重算！
    cached["records"] = records
    return DataResponse(
        data=cached, cache_hit=True,
        message="使用缓存（距可申请天数已实时重算）"
    )
```

#### 3. 预计算路径也要重算（scan_all 刷新写文件时）

```python
records = pre["records"]
_recalc_days(records)               # ← 重算覆盖预计算值
```

### 修改位置一览

| 文件 | 行号/位置 | 改动 |
|---|---|---|
| `backend/app/routers/market.py` | 新函数 | 加 `_recalc_days()` |
| `backend/app/routers/market.py` | 缓存命中分支 | `cached["records"]` 取出来 → `_recalc_days()` → 塞回去 |
| `backend/app/routers/market.py` | 预计算写 JSON 前 | `_recalc_days(records)` 覆盖旧值 |
| `backend/app/services/st_time_service.py` | `scan_all()` 尾部 | 显式 CST 算 today |

### 验证

```python
# 本地快速验证 _recalc_days 逻辑
from datetime import datetime, timezone, timedelta
cst = timezone(timedelta(hours=8))
today = datetime.now(cst).strftime("%Y-%m-%d")  # 必须 CST
print(f"CST today: {today}")
# 对比 API 返回的距可申请天数 = (可申请摘帽日 - today).days
```

---

## Part 2：sandbox 生成数据（203 条 → 197 有日期）

production 上巨潮 API 可能被封，需要在 sandbox（巨潮可达）跑完再传。

### 步骤

```bash
cd /workspace
docker exec webstock-webstock-1 python3 -c "
import sys, os
sys.path.insert(0, '/app'); os.chdir('/app')
from app.services.st_time_service import scan_all
results = scan_all()
print(f'共 {len(results)} 只, {len([r for r in results if r.get(chr(21407)+chr(30003)+chr(25104)+chr(30003)+chr(26085))])} 有日期')
import json
with open('backend/data/st_time_results.json','w',encoding='utf-8') as f:
    json.dump({'records': results}, f, ensure_ascii=False, indent=2)
"
```

### scan_all 内部逻辑（防坑）

```
新浪 VIP hs_a (5568只)
  → filter name.upper().find('ST') >= 0  → 203只 ST/*ST
  → 每只查巨潮公告找 ST 开始日 (max_workers=4)
  → add_one_year() 算可申请摘帽日
  → CST today 算距可申请天数
  → 超期过滤：距可申请天数 < -365 的清掉日期
```

### ST 股数据源说明

**新浪财经没有 ST 板块专用 API**。新浪 VIP Market_Center 的 `node=ST` / `node=*ST` / `node=st_danjian` 等全部返回 `[]`。新浪财经自己也是用"全市场 `node=hs_a` + 名字含 ST filter"的方式。

所以当前实现已经和新浪财经 ST 板块完全对齐：
- 新浪 ST 股数 = 203
- sandbox 生成的 JSON = 203
- 交集 = 203（0 漏 0 多）

---

## Part 3：sandbox → production 部署（代理隧道）

### 场景

- sandbox 不能直连 production SSH 22 端口（timeout）
- sandbox 有 HTTP 代理：`127.0.0.1:18080`（环境变量 `HTTPS_PROXY` 已设）
- production 有 docker compose（服务名 `webstock-webstock-1` / `webstock-redis-1` / `webstock-nginx-1`）
- 已经装好了 `paramiko` + `scp`（`pip install paramiko scp`）

### 方案：HTTP CONNECT 隧道 + paramiko SSH + SFTPClient

Python 脚本模板：

```python
import socket, os, paramiko

HOST, USER, PWD = "PROD_IP", "root", "PROD_PWD"
PROXY_HOST, PROXY_PORT = "127.0.0.1", 18080
LOCAL_FILE = "/path/to/local.json"
REMOTE_PATH = "/opt/webstock/backend/data/st_time_results.json"

# 1. socket 连代理
sock = socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=10)

# 2. HTTP CONNECT 隧道
sock.sendall(f"CONNECT {HOST}:22 HTTP/1.1\r\nHost: {HOST}:22\r\n\r\n".encode())
resp = b""
while b"\r\n\r\n" not in resp:
    resp += sock.recv(4096)
assert b"200" in resp, f"代理拒绝: {resp[:100]}"

# 3. paramiko SSH
transport = paramiko.Transport(sock)
transport.start_client()
transport.auth_password(username=USER, password=PWD)

# 4. SFTPClient 传文件
sftp = paramiko.SFTPClient.from_transport(transport)
sftp.put(LOCAL_FILE, REMOTE_PATH)
sftp.close()

# 5. 远程执行（进容器覆盖 + 清缓存 + 重启）
cmd = """cd /opt/webstock
C=$(docker ps -qf 'name=webstock.*webstock')
[ -n "$C" ] && docker cp backend/data/st_time_results.json $C:/app/backend/data/st_time_results.json
docker exec webstock-redis-1 redis-cli FLUSHALL 2>/dev/null
docker restart "$C" 2>/dev/null
sleep 8
curl -s http://localhost:8000/api/market/st/time
"""
chan = transport.open_session()
chan.exec_command(cmd)
out = chan.recv(65536).decode()
# ... 循环 recv 直到 exit_status_ready

transport.close()
sock.close()
```

### 备选方案（如果代理 SSH 也不行）

| 方案 | 适用场景 | 命令 |
|---|---|---|
| 飞书云助手 | sandbox 没 SSH 但生产有阿里云助手 | `lark-cli im +messages-send` |
| 飞书云盘下载 | 生产能跑 `lark-cli` | `lark-cli drive +download --file-token XXX` |
| sandbox HTTP server | 生产能 curl sandbox | `curl http://SANDBOX_IP:8080/file.json` |
| SSH + sshpass | sandbox 有 apt 权限 | `apt install sshpass && sshpass -p X scp ...` |

### 飞书云盘上传文件

```bash
# sandbox 上传 JSON 到飞书云盘
lark-cli drive +upload --file /tmp/file.json --name "file.json"
# 返回 file_token，发给云助手让它在生产执行 drive +download
```

---

## Part 4：生产验证 Checklist

```bash
# 1. 清掉 Redis 缓存后第一次请求
redis-cli FLUSHALL 2>/dev/null
curl -s http://localhost:8000/api/market/st/time | python3 -c "
import sys,json
d=json.load(sys.stdin);r=d['data']['records']
wd=[x for x in r if x.get('可申请摘帽日')]
print('cache_hit=',d.get('cache_hit'),'总=',len(r),'有日期=',len(wd))
assert d.get('cache_hit')==False, '第一次请求应该 cache_hit=False'
assert len(wd) > 100, f'有日期不够: {len(wd)}'
"

# 2. 第二次请求（验证缓存命中也重算）
curl -s http://localhost:8000/api/market/st/time | python3 -c "
import sys,json
d=json.load(sys.stdin);r=d['data']['records']
wd=[x for x in r if x.get('可申请摘帽日')]
print('cache_hit=',d.get('cache_hit'),'有日期=',len(wd))
assert d.get('cache_hit')==True
assert d.get('message','').find('已实时重算') >= 0, '缓存消息没提示重算'
"

# 3. 天数正确性（必须用 CST）
curl -s http://localhost:8000/api/market/st/time | python3 -c "
import sys,json
from datetime import datetime,timezone,timedelta
cst=timezone(timedelta(hours=8))
today=datetime.now(cst).strftime('%Y-%m-%d')
d=json.load(sys.stdin);r=d['data']['records']
errs=0
for x in r:
    if x.get('可申请摘帽日'):
        exp=(datetime.strptime(x['可申请摘帽日'],'%Y-%m-%d')-datetime.strptime(today,'%Y-%m-%d')).days
        if x.get('距可申请天数')!=exp: errs+=1
print('天数错误=',errs,'CST today=',today)
assert errs==0
"
```

---

## 铁律 & 踩过的坑

| 坑 | 后果 | 解法 |
|---|---|---|
| JSON 里存预计算的距可申请天数 | 每天变旧 | JSON 只存数据源，天数 serve-time 算 |
| 缓存命中跳过天数重算 | 7 天内全是旧值 | `cached.get("records")` → `_recalc_days()` → 塞回去 |
| sandbox UTC 时区 | `datetime.now()` 算出昨天 | 所有日期计算显式 `timezone(timedelta(hours=8))` |
| 巨潮多线程 4 worker 被封 IP | 生产 scan_all 卡住 | sandbox 生成数据再传，或 max_workers=1 |
| 远程命令引号嵌套（ssh + bash + python -c） | bash syntax error | 写成脚本 → 上传 → 远程执行；或用 paramiko `exec_command` |
| sandbox 直连 production SSH timeout | 部署直接失败 | HTTP CONNECT 代理隧道 + paramiko（上面 Part 3） |
| `git pull` 提前了 deploy.sh 的差异判断 | 部署脚本跳过构建重启 | 别在 deploy.sh 前手动 pull |

## 项目文件地图

```
backend/app/
  routers/market.py        ← _recalc_days + st_time 端点（缓存/预计算路径都要重算）
  services/st_time_service.py  ← fetch_sina_all, scan_all, find_st_start_date
data/
  st_time_results.json     ← 预计算 JSON（只存股票数据，天数由 serve-time 重算）
tmp_script/
  refresh_all.py           ← 周调度：周三跑 scan_all() 写 JSON
docker-compose.yml         ← 服务名 webstock-webstock-1 / webstock-redis-1 / nginx
```
