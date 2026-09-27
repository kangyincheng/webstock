---
name: "fastapi-async-task-debug"
description: "排雷 FastAPI 后台线程异步任务的进度推送问题。当进度条不实时更新、WebSocket 无推送、训练/扫描结束后 epoch 字段丢失或返回占位符时调用。"
---

# FastAPI 异步后台任务进度推送排雷

本 skill 总结了本项目中"前端进度条不更新 + 后端返回占位符"这类组合 bug 的完整排查与修复经验。触发场景：训练/扫描/长耗时任务提交后，前端进度条卡死、WebSocket 无数据、训练结束后某些字段（如 epoch、next_day_date）显示占位符。

## 标准架构（四层）

```
POST /api/task           → 立即返回 task_id（非阻塞）
      ↓
loop.run_in_executor     → 后台线程跑 run_training / run_scan
      ↓
progress_cb(payload)     → 回调里同时：
                              ① ws_progress_adapter(task_id) → WS 推送
                              ② _TASK_RESULT[task_id].update(msg) → 字典存进度
      ↓
GET /api/task/{id}       → 前端每 1.5s 轮询兜底
```

## 排雷清单（按概率排序）

### 坑 1：task_id 内外不一致 —— epoch/进度永远丢失

- **症状**：POST 返回的 task_id 和 run_training 内部 progress_cb 用的 task_id 不是同一个；`_TASK_RESULT` 里有两个 key，前端 poll 的那个只有 `status='running'`，另一个存着完整 epoch。
- **根因**：`run_training` 内部又 `uuid.uuid4().hex[:10]` 生成了一个新 task_id，和外层 POST 返回的不一致。
- **修法**：让 run_training 接受可选 task_id 参数，外层传了就用它。

```python
# train_service.py
def run_training(self, params, progress_cb=None, task_id=None):
    task_id = task_id or uuid.uuid4().hex[:10]  # ← 关键
    ...

# routers/predict.py _bg_run()
result = ts.run_training(params.dict(), progress_cb=_real_cb, task_id=task_id)  # ← 传进去
```

### 坑 2：后台线程里拿不到 event loop —— WS 推送永久失效

- **症状**：WebSocket 连接建立成功但永远收不到消息；`broadcast_progress` 里 `get_running_loop()` 抛 RuntimeError，被 except 吞掉。
- **根因**：后台训练线程不是 asyncio 线程，没有 running loop。
- **修法**：模块级捕获 event loop，用 `call_soon_threadsafe` 跨线程。

```python
# ws_bus.py
_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None

async def ws_endpoint(websocket, task_id):
    global _MAIN_LOOP
    if _MAIN_LOOP is None:
        _MAIN_LOOP = asyncio.get_running_loop()  # 第一个 WS 连接时 capture
    ...

def broadcast_progress(task_id, payload):
    loop = _MAIN_LOOP  # 后台线程安全读取
    if loop is None: return  # 还没 WS 连接，纯靠轮询兜底
    loop.call_soon_threadsafe(lambda: ...)
```

### 坑 3：训练结束 result 覆盖了 epoch 字段 —— 进度条永远不显示 100%

- **症状**：训练进行中 poll 能看到 epoch 增长（因为 progress_cb 在写），但刚结束那次 poll epoch 突然变 null，前端卡在 0%。
- **根因**：`run_training` 返回的 result dict 里**根本没有** epoch/total_epochs/train_loss 这些字段（它们只在 progress_cb 的 payload 里），`_bg_run` 里 `cur.update(result)` 把 progress_cb 推的值抹掉了。
- **修法**：update 后从 train_losses 长度反推补回。

```python
# routers/predict.py _bg_run()
result = ts.run_training(...)
with _TASK_LOCK:
    cur = _TASK_RESULT.get(task_id, {})
    cur.update(result)           # ← 会把 epoch 覆盖掉！
    cur["status"] = result.get("status", "success")
    # ↓↓ 必须补回 ↓↓
    losses = result.get("train_losses") or []
    if losses:
        cur["epoch"] = len(losses)
        cur["total_epochs"] = len(losses)
        cur["train_loss"] = losses[-1]
        cur["val_loss"] = (result.get("val_losses") or [None])[-1]
```

### 坑 4：Gunicorn 多 worker —— 轮询永远 miss

- **症状**：POST 由 worker A 处理（_TASK_RESULT 写在 A），GET /task/{id} 被负载均衡到 worker B（B 里没有这个 key），返回"任务不存在"。
- **修法**：`WORKERS=1` 或 Gunicorn 用 `--preload` + 单 worker。Webpack dev 模式下 reload 也用 1 worker。

### 坑 5：交易日历每次现查 baostock —— 慢 + 断网就失败

- **症状**：训练结束后 `next_day_date` 显示占位符 "下一交易日"，其实不是逻辑错，是 baostock 网络不通导致 `_find_next_trade_date` 返回 None。
- **修法**：三级缓存（内存 → JSON 文件 → baostock），TTL 365 天。

```python
# train_service.py
_TRADE_DAYS_CACHE = None  # 模块级内存
_TRADE_CAL_PATH = "backend/data/trade_calendar.json"

def _load_trade_calendar(force_refresh=False):
    global _TRADE_DAYS_CACHE
    if _TRADE_DAYS_CACHE is not None and not force_refresh:
        return _TRADE_DAYS_CACHE          # 1) 内存命中
    if os.path.isfile(_TRADE_CAL_PATH) and not force_refresh:
        # 2) 读磁盘，检查 updated 距今 < 365 天
        ... return 从 JSON 加载
    # 3) 从 baostock 拉过去1年 ~ 后2年
    bs.login(); rs = bs.query_trade_dates(...); bs.logout()
    写 JSON + 回填内存
```

## 端到端诊断脚本（curl + python）

每次改动后先跑这个，能 30 秒内定位是哪一层坏了：

```bash
# 1) 提交训练 → 立即返回 task_id
API=http://127.0.0.1:8000/api/predict
TID=$(curl -s -X POST $API/train -H 'Content-Type: application/json' \
  -d '{"framework":"pytorch","stock_code":"sh.600036","epochs":20}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['task_id'])")
echo "task_id=$TID"

# 2) 轮询 → 看 epoch 有没有实时变化
for i in $(seq 1 40); do
  sleep 0.35
  curl -s $API/task/$TID | python -c "
import sys,json
d=json.load(sys.stdin)['data']
st=d.get('status',''); ep=d.get('epoch'); te=d.get('total_epochs')
print(f'poll $i  [{st:8s}]  {str(ep):>2s}/{str(te):>2s}  stage={d.get("stage",""):7s}  tl={str(d.get("train_loss",""))[:10]}')
"
  [[ $(curl -s $API/task/$TID | python -c "import sys,json; print(json.load(sys.stdin)['data'].get('status',''))") != "running" ]] && break
done

# 3) 最终字段完整性
curl -s $API/task/$TID | python -c "
import sys,json
d=json.load(sys.stdin)['data']
print('epoch/total     :', d.get('epoch'), '/', d.get('total_epochs'))
print('next_day_date   :', d.get('next_day_date'), '✓' if isinstance(d.get('next_day_date'),str) else '✗')
print('next_day_pred   :', d.get('next_day_pred'))
print('metrics         :', d.get('metrics'))
print('train_losses len:', len(d.get('train_losses') or []))
"
```

## 快速定位速查表

| 现象 | 看哪 | 可能原因 |
|---|---|---|
| `_TASK_RESULT` 里有两个 key | `grep -n "_TASK_RESULT" routers/predict.py` | task_id 内外不一致 |
| 后台线程 epoch cb 正常但 poll 里没有 | 同上 + 看 run_training 签名 | run_training 返回 dict 没 epoch 字段 |
| poll 里 epoch 从有突然变 None | `_bg_run` 结束段 | `update(result)` 覆盖掉了 |
| WS 连接成功但永远收不到消息 | `grep -n "get_running_loop\|_MAIN_LOOP" ws_bus.py` | event loop 没 capture |
| 轮询返回"任务不存在" | `ps -ef \| grep gunicorn` | workers > 1 |
| `next_day_date` 是占位符 | `cat backend/data/trade_calendar.json` | baostock 网络不通或缓存过期 |
