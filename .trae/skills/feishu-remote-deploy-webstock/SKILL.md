---
name: "feishu-remote-deploy-webstock"
description: "Webstock 项目专属：通过飞书阿里云智能助手远程部署 production。Invoke when sandbox 需更新 jeoj.com 但没 SSH/没 Docker，或用户说‘通过飞书更新网站’。"
---

# Webstock 飞书远程部署

**项目**：webstock（jeoj.com）  
**生产机**：8.130.158.196 · Alibaba Cloud Linux 3 · baremetal（systemd）  
**sandbox 限制**：无 Docker、SSH 22 端口被墙（但 HTTP 代理可达）  
**桥接方案**：sandbox → `lark-cli` 发消息 → 阿里云智能助手 → production shell

---

## 项目文件地图

```
/opt/webstock/
├── backend/app/
│   ├── routers/
│   │   ├── market.py          ← ST摘帽时间 / 市场数据
│   │   └── cbond.py           ← 要约收购 / 可转债
│   ├── services/
│   │   ├── st_time_service.py ← ST 摘帽扫描（新浪+巨潮）
│   │   └── market_service.py  ← 市场服务（含 tender_offer）
│   ├── cache.py               ← Redis 缓存层
│   └── main.py                ← FastAPI 入口（gunicorn）
├── backend/data/              ← 预计算 JSON 挂这个目录
│   ├── st_time_results.json
│   └── tender_results.json
├── frontend/                  ← 前端源码（生产由 nginx 托管 dist/）
├── tmp_script/refresh_all.py  ← 定时守护进程
└── docker-compose.yml
```

**systemd 服务名**：`webstock` + `nginx` + `redis`（baremetal 模式）  
**API 基础路径**：`/api/`（健康检查 `/api/system/healthz`）  
**域名**：`www.jeoj.com`（HTTPS 301 from HTTP）

---

## 四步部署流程

### Step 0：前置确认（每次部署前必做）

```bash
# 0a. sandbox 环境
lark-cli --version                  # 要有 1.0.93+
lark-cli auth status                # 要有 user_access_token（不是 bot）

# 0b. 生产可达（sandbox 有 HTTP 代理 127.0.0.1:18080）
curl -s https://www.jeoj.com/api/system/healthz | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'uptime={d[\"data\"][\"uptime\"]}s')"

# 0c. 代码已 push 到 GitHub（kangyincheng/webstock main 分支）
git diff --stat                     # 本地有改动就要 commit + push
curl -s https://raw.githubusercontent.com/kangyincheng/webstock/main/backend/app/routers/market.py | md5sum
md5sum < backend/app/routers/market.py   # 两者要一致

# 0d. 数据文件（不在 git 的，比如 tender_results.json）要上传飞书云盘
lark-cli drive +upload --file backend/data/tender_results.json --name "tender_results.json"
# 输出：file_token=xxxxxx  ← 记下，后面指令里要用
```

### Step 1：确认云助手 chat_id

```bash
lark-cli im +chat-list --types=p2p | python3 -c "
import sys,json
for c in json.load(sys.stdin)['data']['chats']:
    n=c.get('name','')
    if any(k in n for k in ['阿里云','智能助手','ECS']):
        print(f\"chat_id={c['chat_id']}  name={n}\")
"
```

**常用**：`oc_696e2b6db667a44301ba9abef5b0057b`（阿里云智能助手）

### Step 2：组装部署指令 + 发送

**指令模板**（每次替换 `GIT_FILES` 里的文件列表、`FEISHU_FILE_TOKENS` 里的 token）：

```
请在 jeoj.com 生产服务器（8.130.158.196）上执行：

echo "=== Webstock 部署 START ==="
cd /opt/webstock

# 1. 拉代码
git fetch --depth=1 origin && git reset --hard origin/main 2>&1 | tail -3

# 2. 下载数据文件（飞书云盘）
lark-cli drive +download --file-token <TOKEN1> --output /opt/webstock/backend/data/<FILE1> 2>&1 || echo "DOWNLOAD_FAIL_1"
lark-cli drive +download --file-token <TOKEN2> --output /opt/webstock/backend/data/<FILE2> 2>&1 || echo "DOWNLOAD_FAIL_2"

# 3. 清 Redis + 重启
redis-cli FLUSHALL 2>/dev/null || echo "redis_skip"
systemctl stop webstock 2>/dev/null || true
sleep 2
systemctl start webstock
sleep 3
systemctl is-active webstock && echo "WEBSTOCK_OK" || { echo "WEBSTOCK_FAIL"; journalctl -u webstock -n 20 --no-pager; exit 1; }

# 4. 端到端验证
curl -s http://127.0.0.1:8000/api/system/healthz
echo ""

echo "=== Webstock 部署 END ==="
```

**发送命令**：

```bash
lark-cli im +messages-send \
  --chat-id oc_696e2b6db667a44301ba9abef5b0057b \
  --text "$(cat /tmp/deploy_msg.txt)" 2>&1
```

### Step 3：等待 + curl 验证（关键！）

```bash
sleep 60   # 云助手排队 + 执行 + systemd 重启 = 至少 45~60s

# healthz 先看 uptime（变小 = 刚重启成功）
curl -s https://www.jeoj.com/api/system/healthz | python3 -c "
import sys,json;d=json.load(sys.stdin);
print(f'uptime={d[\"data\"][\"uptime\"]}s  ok={d[\"data\"][\"ok\"]}')"

# 业务接口验证（根据本次改了什么接口测什么）
curl -s https://www.jeoj.com/api/market/st/time | python3 -c "
import sys,json;d=json.load(sys.stdin);r=d['data']['records'];
print(f'total={len(r)} cache_hit={d.get(\"cache_hit\")}')
# 根据具体需求加排序验证/字段验证
"

# 要约收购
curl -s -X POST https://www.jeoj.com/api/cbond/tender \
  -H 'Content-Type: application/json' -d '{"market":"cn"}' | python3 -c "
import sys,json;d=json.load(sys.stdin);
print(f'A股={len(d[\"data\"][\"rows\"])}条  updated_at={d[\"data\"].get(\"updated_at\")}')"
```

---

## 紧急修复指令（当 webstock 挂了返回 502 时）

**触发表象**：`curl https://www.jeoj.com` 返回 502 Bad Gateway，`uptime` 很大说明没重启。

```
紧急！Webstock 502 Bad Gateway，立即执行：

echo "=== 紧急修复 START ==="

# 1. 查状态
systemctl status webstock --no-pager | head -20
journalctl -u webstock -n 50 --no-pager 2>&1 | tail -30

# 2. 手动 import 验证（排除语法错误）
cd /opt/webstock
python3 -c "import sys; sys.path.insert(0,'.'); from backend.app.main import app; print('✅ import OK')" 2>&1 | tail -10

# 3. 强杀重启
systemctl stop webstock 2>/dev/null || true
sleep 2
redis-cli FLUSHALL 2>/dev/null || true
systemctl start webstock
sleep 4

# 4. 轮询等起来
for i in 1 2 3 4 5 6 7 8 9 10; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/api/system/healthz 2>/dev/null)
  [ "$CODE" = "200" ] && echo "✅ OK (attempt $i)" && break
  echo "  waiting... ($i)"
  sleep 2
done

echo "=== 紧急修复 END ==="
```

---

## 常见问题 & 解法

| 现象 | 可能原因 | 解法 |
|------|---------|------|
| `git push` 失败（sandbox 没 GitHub token） | sandbox 无凭据 | 改完 commit 后用 GitHub 网页手动 push，或让用户本地 push |
| API 还是旧行为 | 云助手没重启 webstock / Redis 缓存没清 | 发紧急修复指令强制 FLUSHALL + systemctl restart |
| 502 Bad Gateway | webstock 挂了（可能语法错误或依赖缺失） | 发紧急修复指令，先看 journalctl 日志 |
| `redis-cli` 不存在 | baremetal 可能没装 redis-cli | 跳过 FLUSHALL 那行，webstock 进程重启后内存缓存自动清 |
| nginx 502 但 webstock 正常 | nginx 配置了端口代理 | 检查 nginx 日志 `journalctl -u nginx -n 30` |
| 云助手指令没执行（排队） | 阿里云助手可能排队 30~60s | 再等一下，uptime 变小说明重启过了 |
| lark-cli `drive +download` 在生产没装 | 生产没装 lark-cli | 指令里要先判断 `which lark-cli`，没有就手动生成数据 |
| `st_time_service.scan_all()` 在生产巨潮被封 | 生产服务器 IP 被巨潮封 | 改用 sandbox 生成 `st_time_results.json` 上传飞书云盘，生产只读 |

---

## 当前活跃的飞书云盘文件

| 用途 | file_token | 本地源路径 | 更新频率 |
|------|-----------|-----------|---------|
| 要约收购预计算 | `MoLWbeGDFo3n5vxi2xmcbvkMnke` | `backend/data/tender_results.json` | 每个交易日 01:30（定时任务） |
| ST 摘帽时间（已写死 cron 刷新，一般不用手动传） | — | `backend/data/st_time_results.json` | 周三由 scan_all 定时刷新 |

上传命令模板：
```bash
lark-cli drive +upload --file <LOCAL_PATH> --name "<REMOTE_FILENAME>"
# 输出里的 file_token 要记下来
```

生产下载命令模板：
```bash
lark-cli drive +download --file-token <TOKEN> --output /opt/webstock/backend/data/<FILENAME>
```

---

## Sandbox 本地先跑一遍（推荐！）

每次改完先在 sandbox 验证代码逻辑正确：

```bash
# 后端逻辑验证
python3 -c "
import sys; sys.path.insert(0, '.')
# 根据改了什么测什么
from backend.app.routers.market import _recalc_days
# 手动构造数据测排序
"

# 数据生成（tender / st_time 等）
python3 -c "
import sys, os, json
sys.path.insert(0, '.'); os.chdir('/workspace')
from src.tender_offer_analyzer import TenderOfferAnalyzer
# 或 from backend.app.services.st_time_service import scan_all
"

# 前端 build
cd frontend && npm run build  # 生成 dist/

# git commit + push（如果有 GitHub 凭据）
git add -A && git commit -m "feat: ..." && git push origin main
```

**在 sandbox 验证完再发飞书指令** — 省得在 production 上试错导致 502 挂掉。

---

## 部署完成 Checklist

- [ ] `healthz` uptime 变小（< 60s = 刚重启）
- [ ] **本次改动的核心接口**返回正确数据
- [ ] 有本地预计算文件的接口：`updated_at` 字段正常
- [ ] 前端相关接口不报错（如果改了前端）
- [ ] Redis 缓存清干净了（`cache_hit=True` 时也要验证内容对）

---

## 项目路径约定（skill 内不可写死绝对路径）

部署指令里的项目根目录**统一用 `/opt/webstock`**（阿里云 ECS baremetal 模式下的固定路径）。

sandbox 内开发路径是 `/workspace`，**两个路径映射**：

| sandbox（开发） | production（运行） |
|----------------|-------------------|
| `/workspace/backend/app/...` | `/opt/webstock/backend/app/...` |
| `/workspace/backend/data/...` | `/opt/webstock/backend/data/...` |
| `/workspace/tmp_script/...` | `/opt/webstock/tmp_script/...` |
