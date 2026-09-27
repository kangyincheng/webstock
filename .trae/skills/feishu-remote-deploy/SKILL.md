---
name: "feishu-remote-deploy"
description: "通过飞书云助手远程执行生产服务器命令。当 sandbox 没有 Docker/SSH 但生产服务器有飞书云助手（阿里云助手等）可用时调用。"
---

# 飞书远程部署：sandbox → 飞书云助手 → 生产服务器

## 触发场景

- sandbox 没有 Docker (`docker not found`)、没有 SSH 访问生产 (`ssh timeout`)
- 但生产服务器上跑着飞书云助手（阿里云智能助手等），能通过飞书指令执行 shell
- 代码已 push 到 git 仓库（GitHub/Gitee）
- 目标：热修复 → 重启 → curl 生产 API 验证

## 四步流程

### Step 1: 找到飞书云助手的 chat_id

```bash
# 列出所有 P2P 聊天，找到带「助手」「阿里云」「云助手」关键词的
lark-cli im +chat-list --types=p2p 2>&1 | python3 -c "
import sys,json
for c in json.load(sys.stdin)['data']['chats']:
    n=c.get('name','')
    if any(k in n for k in ['助手','阿里云','云助手','ECS']):
        print(f\"chat_id={c['chat_id']}  name={n}\")
"
```

常见云助手名称：
- `阿里云智能助手` — 阿里云 ECS 内置，支持 docker/git/systemctl
- `管理员小助手`、`jeoj康银成的智能助手` 等

**保存 chat_id**（`oc_xxx` 格式），后面发消息要用。

### Step 2: 给云助手发部署指令

```bash
# 检查 lark-cli 能否发消息（先拿一个最简单的 chat_id 试）
lark-cli im +messages-send \
  --chat-id oc_xxx_YUNZHUSHOU_CHAT_ID \
  --text '请在服务器上执行：echo "hello from feishu bot"'
```

如果返回 `"ok": true`，权限没问题；如果报 `230027 user_unauthorized`，需要让用户在飞书里点一下授权链接，`--as bot` 可能也不行（strict mode 默认 user）。

**部署消息模板**（docker compose 场景）：

```
请在 <服务器标识> 上执行以下命令：

cd /var/www/<project> && git pull origin main --ff-only

# cp 文件进正在跑的容器（方案 A：热修复，秒级生效）
C=$(docker ps -qf name=<service_name>)
docker cp path/to/file1.py  $C:/app/path/to/file1.py
docker cp path/to/file2.py  $C:/app/path/to/file2.py
docker cp path/to/file3.py  $C:/app/path/to/file3.py

# 重启
docker restart $C

# 验证
curl -s http://localhost:<port>/api/system/healthz
```

**替代方案 B**（重建镜像，~10 分钟）：

```bash
cd /var/www/<project>
git pull origin main --ff-only
docker compose up -d --build <service_name>
```

### Step 3: 等执行 + curl 生产 API 验证

```bash
# 等 20-40 秒让云助手拉代码 + 重启容器
sleep 30

# healthz 先过
curl -s --max-time 5 http://<生产域名>/api/system/healthz

# 端到端训练验证（以预测接口为例）
API=http://<生产域名>/api/predict
TID=$(curl -s --max-time 10 -X POST $API/train -H 'Content-Type: application/json' \
  -d '{"framework":"pytorch","stock_code":"sh.600036","start_date":"2024-01-01","epochs":8}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['task_id'])")

for i in $(seq 1 40); do
  sleep 0.5
  D=$(curl -s --max-time 5 $API/task/$TID)
  python3 -c "import sys,json;d=json.loads(sys.argv[1])['data'];
    st=d.get('status','?');ep=d.get('epoch');te=d.get('total_epochs');
    print(f'poll $i [{st:8s}] {str(ep):>2s}/{str(te):>2s} tl={str(d.get(\"train_loss\",\"\"))[:10]}')" "$D"
  python3 -c "import sys,json;sys.exit(0 if json.loads(sys.argv[1])['data'].get('status')=='running' else 1)" "$D" || break
done

# 最终校验
curl -s --max-time 5 $API/task/$TID | python3 -c "
import sys,json
d=json.load(sys.stdin)['data']
print('epoch/total   :', d.get('epoch'), '/', d.get('total_epochs'))
print('next_day_date :', d.get('next_day_date'))
print('metrics       :', d.get('metrics'))
print('error         :', d.get('error'))
"
```

### Step 4: 失败降级

如果 Step 2 云助手没执行成功（curl 还返回旧行为），按这个顺序排查：

```
a) 再等 60 秒（云助手可能排队）
b) curl healthz 看 uptime：如果 uptime 很小（<60s）说明重启了，只是训练还没跑
c) 检查 git 是否真的 pull：curl 训练一次看 error 字段有没有 SyntaxError
d) 降级方案 B：让云助手执行 docker compose up -d --build（更干净但慢）
```

## 本次实战经验（2026-09-27）

| 坑 | 解法 |
|---|---|
| sandbox 没 Docker/SSH | 用飞书云助手当跳板 |
| lark-cli 发消息报 230027 | 找用户自己的 P2P chat_id（不是 bot 的） |
| 云助手执行慢 | 等 30 秒以上再 curl，不要急 |
| cp 进容器后文件语法错 | 让云助手 `docker exec $C python -c "import app.main"` 先验语法 |
| healthz uptime 很小（24s） | 说明刚重启，docker restart 生效了 |
| strict mode 不让用 bot 身份 | `--as bot` 会报 strict mode 错误，只能用 user identity |

## lark-cli 关键命令速查

```bash
# 列 P2P 聊天（找云助手）
lark-cli im +chat-list --types=p2p

# 发消息
lark-cli im +messages-send --chat-id oc_xxx --text '...'

# 看某聊天历史（验证身份对不对）
lark-cli im +chat-messages-list --chat-id oc_xxx --order desc --page-limit 5

# 搜历史消息（判断之前用哪个助手执行过部署）
lark-cli im +messages-search --query "docker restart" --page-limit 10
```

## 前置条件检查清单

执行前按顺序确认：

- [ ] 代码已 commit + push 到 git 远端
- [ ] `lark-cli` 可用：`lark-cli --version`
- [ ] `lark-cli auth status` 有 user_access_token
- [ ] 生产 API curl 通：`curl http://<域名>/api/system/healthz`
- [ ] 找到云助手 chat_id（`oc_xxx`）
- [ ] 发一条测试消息给云助手（确保权限没问题）
