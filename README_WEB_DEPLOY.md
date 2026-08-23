# webstock · A 股智能分析平台

> 原项目为基于 **PyTorch + TensorFlow + Tkinter 桌面版** 的 A 股收盘价预测系统。
> 现改造为 **FastAPI + Vue3 + Nginx + Redis 的 Web 架构**，可直接部署在 **Alibaba Cloud Linux 3.2104 LTS 64 位**，目标是 **客户端访问速度最快**。

---

## 一、架构总览（客户端最快）

```
┌─────────────────────────────────────────────────────────────┐
│                    客户端（浏览器）                          │
│   ECharts 图表 + Element Plus UI + 路由 Hash 模式          │
│   WebSocket 收训练进度 · 启用 gzip/brotli                   │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTPS (keepalive 65s)
          ┌────────────▼─────────────┐
          │ Nginx (最前层，监听 80/443)│ ← 性能关键点
          │  · 静态资源强缓存 1y 哈希  │   · assets immutble
          │  · brotli + gzip 双压缩   │   · open_file_cache
          │  · 静态资源直接从磁盘回源   │   · 不进 Python
          │  · 上游 API 连接池 64 条   │   · keepalive
          │  · WS Upgrade 正确转发    │   · 3600s 超时
          └┬───────────┬──────────────┘
           │ /api/*    │ /ws/*       │ /assets/*、/index.html（直接回）
  ┌────────▼──┐  ┌─────▼──────┐
  │ FastAPI   │  │ WebSocket  │
  │ Gunicorn  │  │ （同一进程）│
  │ Workers=N │  │ 广播训练进度│
  └┬──┬──────┬┘  └────────────┘
   │  │      │
   │  │      └► SQLite：自选股 + 事件（1 文件，0 运维）
   │  └────────► Redis：  行情缓存（15m~6h TTL，无 Redis 自动降级内存 LRU）
   └───────────► baostock / tushare（外部）
```

**性能关键决策：**
| 决策 | 影响 |
|---|---|
| **Nginx 最前层** 托管静态资源 + `/api` 反代 + `/ws` 升级 | 首屏资源回源 **不进 Python**，静态 QPS > 10k/s |
| `gzip + brotli` 双重压缩，`assets/*` 永久缓存 + immutable | bundle 下载体积 -70%，二次访问 0 字节 |
| API 上游 keepalive 64 条连接池 | 避免 3 次握手，首字节时间 -40% |
| **Redis 缓存**（ST/板块/热门/可转债等 6 小时、温度计 15 分钟） | 重复点击**毫秒级**返回，不打满 baostock/tushare |
| 自选股 **SQLite**（索引 code、due_date） + 后台线程刷价 | 持久化 + 查询 O(logN)，比 JSON 文件稳 |
| 训练走 `run_in_executor`（线程池） + `/ws/train/{task_id}` 推送 | 长任务不阻塞事件循环，UI 实时 Loss |
| Vite `manualChunks`：vue/element/echarts 三分 + `esbuild minify` | 200KB gzip 左右首屏，CDN 更易命中 |
| Nginx：`sendfile tcp_nopush tcp_nodelay aio threads` | 小文件零拷贝，大文件异步 IO |

---

## 二、目录结构（改造后）

```
/workspace
├── main.py                         # 原 Tkinter 入口（保留，桌面版仍可运行）
├── requirements.txt                # 完整依赖
│
├── 📁 src/                         # ✅ 核心业务代码（不删，保留双用）
│   ├── data_loader.py / model.py / trainer.py / tf_model.py / tf_trainer.py
│   ├── st_analyzer.py / st_reinstate_analyzer.py
│   ├── market_thermometer.py / market_data.py (TushareClient)
│   ├── cbond_analyzer.py / tender_offer_analyzer.py
│   └── *_page.py (原 Tkinter UI，保留)
│
├── 🆕 backend/                      # ✨ Web 后端（FastAPI）
│   ├── requirements.txt             # 仅 Web 端依赖（推荐用这个）
│   ├── run_dev.py                   # 开发启动 uvicorn --reload
│   ├── data/                        # 行情/自选/缓存
│   ├── models/                      # 训练好的 .pth / .keras
│   └── app/
│       ├── main.py                  # FastAPI + WebSocket 广播
│       ├── cache.py                 # Redis → 内存 LRU 自动降级
│       ├── schemas/                 # Pydantic 请求/响应模型
│       ├── services/
│       │   ├── train_service.py     # 封装 PyTorch/TF 训练流程
│       │   ├── market_service.py    # 纯业务（ST/温度计/板块/热门/CBond/要约）
│       │   └── favorites_service.py # 自选股 SQLite（CRUD+事件）
│       └── routers/
│           ├── system.py            # healthz version cache-clear
│           ├── predict.py           # /api/predict/train · models CRUD
│           ├── market.py            # st / st-reinstate / thermometer / sector-heat / hot-stocks
│           ├── cbond.py             # subscribe / listing / review / tender
│           └── favorites.py         # 自选 CRUD + 刷价 + 查事件
│
├── 🆕 frontend/                     # ✨ Web 前端（Vue 3 + Vite）
│   ├── package.json / vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.js / App.vue / style.css
│       ├── router/ (hash history · SPA fallback 最稳)
│       ├── api/  (axios 封装)
│       └── views/ （8 个页面）
│           ├── Dashboard.vue        # 看板：温度计 + 板块 Top20 柱 + 热门散点
│           ├── Predict.vue          # 训练/预测 + WebSocket 实时 Loss
│           ├── STPage.vue           # ST 摘帽 / ST 恢复
│           ├── CBond.vue            # 可转债 Tabs
│           ├── Tender.vue           # 要约 A股/港股
│           ├── SectorHeat.vue       # 板块热度表
│           ├── HotStocks.vue        # 热门股票表
│           └── Favorites.vue        # 自选股 CRUD / 事件 / 行情刷新
│
├── 🆕 deploy/                       # ✨ 部署配置
│   ├── nginx/webstock.conf          # 高性能 Nginx（gzip/brotli/缓存/连接池）
│   └── systemd/webstock.service     # 裸机部署的 Systemd unit（含安全加固）
│
├── 🆕 Dockerfile                    # 多阶段构建（Python 依赖 → 前端构建 → Runtime）
├── 🆕 docker-compose.yml            # nginx + webstock + redis 三容器
└── 🆕 deploy-alinux3.sh             # ⭐ 一键部署（Docker 或 裸机）
```

---

## 三、**推荐** 部署方式 A：Docker Compose（最省心）

### 1. 把整个项目放到服务器

```bash
ssh root@<阿里云ECS公网IP>
mkdir -p /opt/webstock && cd /opt/webstock
# 方法1：rsync 传本地
# 方法2：git clone https://github.com/kangyincheng/webstock.git
```

### 2. 一键部署（Docker 模式）

```bash
cd /opt/webstock
chmod +x deploy-alinux3.sh
./deploy-alinux3.sh \
    --mode=docker \
    --http-port=80 \
    --workers=$(nproc) \
    --tushare=你的TUSHARE_TOKEN
```

脚本会自动：
- 装 Docker CE（阿里云镜像源）
- 写 `.env`
- `docker compose build`（多阶段，首推 10~20 分钟）
- `docker compose up -d`（Nginx + FastAPI + Redis）

### 3. 完成

浏览器访问：
- 用公网 IP：`http://<ECS 公网 IP>`
- ECS 安全组请放行 **TCP 80**（以及 443，之后上 HTTPS 用）

查看状态：
```bash
cd /opt/webstock
docker compose ps
docker compose logs -f --tail 200 webstock
```

---

## 四、部署方式 B：裸机（宿主机 Systemd，更省资源）

```bash
cd /opt/webstock
./deploy-alinux3.sh --mode=baremetal \
    --tushare=TOKEN \
    --workers=$(nproc)
```

脚本自动：
- 装 Python 3.11 / Redis / Nginx（Alinux 3 dnf 源）
- 写虚拟环境 `.venv` + 安装全部依赖
- 前端 `npm i && npm run build`（需要 Node，没装就提示你本地构建好 rsync dist）
- 建 `webstock` 系统用户 + 写 `/etc/systemd/system/webstock.service`
- 配置 Nginx `/etc/nginx/conf.d/webstock.conf`（upstream=127.0.0.1:8000）
- 放行 firewalld 80/443

常用命令：
```bash
sudo systemctl status  webstock     # 看状态
sudo journalctl -u webstock -f      # 实时日志
sudo systemctl restart webstock     # 重启后端
sudo systemctl reload  nginx        # Nginx 热重载
curl http://127.0.0.1:8000/api/system/healthz
```

---

## 五、进一步加速（建议）

### 5.1 HTTPS + HTTP/2（关键加速）
1. 用 `certbot --nginx` 申请 Let's Encrypt 免费证书
2. Nginx 取消 `webstock.conf` 中 443 server 的注释，`ssl_certificate` 指 `cert.pem / privkey.pem`
3. 再 `sudo systemctl reload nginx`
4. 浏览器端：HTTP/2 默认多路复用，首屏并发快 2~5x

### 5.2 阿里云 CDN（静态资源全球加速）
把 `frontend/dist/assets/*` 的整个目录域名 CNAME 到 CDN，
并把 `index.html` 里的 `<script src="/assets/*.js">` 改为 CDN 全路径，**静态加速全球可达 10~50ms**。

### 5.3 缓存预热
部署后手工调用：
```bash
curl -X POST http://127.0.0.1:8000/api/market/sector-heat -d '{"trade_date":""}'
curl -X POST http://127.0.0.1:8000/api/market/hot-stocks -d '{"sort_by":"amount","top_n":50}'
curl https://127.0.0.1/api/cbond/subscribe ...
```
用户首次打开就是热数据。

### 5.4 ECS 规格建议
| 并发用户 | 规格 | 预算 |
|---|---|---|
| 1~20 人 | ecs.g7.large（2C4G） | 便宜 |
| 20~100 | ecs.g7.xlarge（4C8G） | 推荐 |
| 100+ 并发训练 | 8C16G + 挂 SWAP 20G | TF/PT 内存吃紧 |

---

## 六、本地开发

```bash
# 后端（FastAPI，8000 端口，自动 reload）
cd /workspace
pip install -r backend/requirements.txt
python backend/run_dev.py

# 前端（Vite，5173，自动代理 /api → 8000）
cd frontend
npm install
npm run dev
# 打开 http://localhost:5173
```

---

## 七、原桌面版（保留）

```bash
pip install -r requirements.txt
python main.py
```

---

## 八、API 速查

| Method | Path | 说明 |
|---|---|---|
| GET    | `/api/system/healthz` | 健康检查 |
| GET    | `/api/system/version` | 版本/架构/目标系统 |
| DELETE | `/api/system/cache?pattern=webstock:*` | 清空缓存 |
| POST   | `/api/predict/train` | 启动训练（Body=PredictParams） |
| WS     | `/ws/train/{task_id}` | 训练进度实时推送 |
| GET    | `/api/predict/task/{task_id}` | 任务结果快照 |
| GET/POST/DEL | `/api/favorites*` | 自选股 CRUD/刷新/查事件 |
| POST   | `/api/market/st/scan` | ST 摘帽扫描 |
| POST   | `/api/market/st-reinstate/scan` | ST 恢复上市 |
| GET    | `/api/market/thermometer` | 市场温度计 |
| POST   | `/api/market/sector-heat` | 板块热度 |
| POST   | `/api/market/hot-stocks` | 热门股票 |
| POST   | `/api/cbond/subscribe` | 当日可申购转债 |
| POST   | `/api/cbond/listing` | 当日上市转债 |
| POST   | `/api/cbond/review` | 转债发审进度 |
| POST   | `/api/cbond/tender` | 要约收购（A/港） |
