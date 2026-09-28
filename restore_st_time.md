# ST股距可申请天数 bug 修复 & 数据恢复

## 问题根因（两个独立 bug）

### Bug 1：market.py 缓存命中跳过重算（代码逻辑）
`GET /api/market/st/time` 端点逻辑：先查 Redis 缓存 → 命中就直接 return，
跳过了后面的 `距可申请天数` 实时重算。而 JSON/缓存里的天数是快照值，
可能是错误日期算出来的。

**修复**：抽 `_recalc_days()` 统一重算函数，缓存命中/文件加载/实时扫描
三个入口都调用，不信任任何预存值。显式用 CST 时区。

### Bug 2：production scan_all() 扫不出巨潮公告数据（网络）
sandbox 有 `HTTP_PROXY=http://127.0.0.1:18080`，巨潮 API 正常。
production 没代理，`requests.post(巨潮API)` 超时/被限流，只扫出 8 条。
sandbox 同样的代码能扫 197 条有日期的。

**修复**：用 sandbox 扫出的正确 JSON 覆盖 production 的数据文件。

---

## 生产部署步骤（在 8.130.158.196 上执行）

### Step 1：备份
```bash
APP=$(find /opt /var/www -maxdepth 4 -type d -name webstock 2>/dev/null | head -1)
cd "$APP"
cp backend/data/st_time_results.json backend/data/st_time_results.json.bak.$(date +%s)
cp backend/app/routers/market.py backend/app/routers/market.py.bak.$(date +%s)
cp backend/app/services/st_time_service.py backend/app/services/st_time_service.py.bak.$(date +%s)
```

### Step 2：恢复原始代码（git）
```bash
cd "$APP"
git checkout HEAD -- backend/app/routers/market.py backend/app/services/st_time_service.py
```

### Step 3：patch market.py（sandbox 已验证正确）
用 sandbox 上的 market.py 覆盖 production 的。或者手动 patch：
- 在 `_ST_TIME_FILE` 定义后、`@router.get` 前插入 `_recalc_days()` 函数
- 缓存命中分支也调 `_recalc_days(records)`
- 内联重算代码替换为 `_recalc_days(records)`

### Step 4：覆盖 JSON 数据文件
sandbox 上 `/tmp/st_time_fixed.json` 是正确数据，用 scp/rsync/HTTP 传到 production。

### Step 5：清缓存 + 重启
```bash
redis-cli FLUSHALL
SN=$(systemctl list-units --type=service --all | grep -i webstock | awk '{print $1}' | head -1)
systemctl restart "$SN"
sleep 5
```

### Step 6：验证
```bash
curl -s http://localhost:8000/api/market/st/time | python3 -c "
import sys,json
from datetime import datetime
d=json.load(sys.stdin)
r=d['data']['records']
wd=[x for x in r if x.get('可申请摘帽日')]
print(f'有日期={len(wd)}, 期望>100')
today=datetime.now().strftime('%Y-%m-%d')
errs=0
for x in wd:
    exp=(datetime.strptime(x['可申请摘帽日'],'%Y-%m-%d')-datetime.strptime(today,'%Y-%m-%d')).days
    if x.get('距可申请天数')!=exp: errs+=1
print(f'天数错误={errs}, 期望=0')
# *ST元道 应该有
yd=[x for x in r if '元道' in x['股票名称']]
print(f'*ST元道 天数={yd[0][\"距可申请天数\"] if yd else \"无\"}, 期望=358')
"
```

---

## 代码变更摘要

### market.py（新增 26 行，删除 13 行）
```python
def _recalc_days(records: list) -> None:
    """实时重算距可申请天数，不信任任何预存值。"""
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

st_time 路由三处改动：
- 缓存命中：先 `_recalc_days()` 再 return
- 文件加载：`_recalc_days()` 替代内联重算
- 实时扫描：结果也调 `_recalc_days()`

### st_time_service.py（2 行改 3 行）
```python
_cst = timezone(timedelta(hours=8))
today = datetime.now(_cst).strftime("%Y-%m-%d")
```
