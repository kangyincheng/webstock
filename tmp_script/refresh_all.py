#!/usr/bin/env python3
"""ST 股三任务定时刷新脚本

调度计划：
  周一 00:00  随机延迟 0~60min → gen_all.py  生成摘帽数据（ST股统计分析）
  周二 00:00  随机延迟 0~60min → gen_all.py  生成摘帽数据（ST股个股表现）
  周三 00:00  随机延迟 0~60min → scan_all() 生成当前 ST 股（ST股摘帽时间）

运行方式：
  python3 refresh_all.py --daemon              # 守护模式，自动按周一/二/三 0 点触发
  python3 refresh_all.py --run st_analyze      # 手动：只跑摘帽（gen_all.py）
  python3 refresh_all.py --run st_overview     # 手动：只跑摘帽（同 gen_all.py）
  python3 refresh_all.py --run st_time         # 手动：只跑当前 ST（scan_all）
  python3 refresh_all.py --run all              # 手动：跑全部

  cron 版（如需）：
    0 0 * * 1  cd /workspace && python3 tmp_script/refresh_all.py --run st_analyze >> refresh.log 2>&1
    0 0 * * 2  cd /workspace && python3 tmp_script/refresh_all.py --run st_overview >> refresh.log 2>&1
    0 0 * * 3  cd /workspace && python3 tmp_script/refresh_all.py --run st_time    >> refresh.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TASK_ROOT)
LOG_TZ = timezone(timedelta(hours=8))
PID_FILE = "/tmp/webstock_st_refresh.pid"

# 守护调度表：星期几(0=周一..6=周日) → 任务函数
SCHEDULE = {
    0: "st_analyze",    # 周一
    1: "st_overview",   # 周二
    2: "st_time",       # 周三
}


def log(msg: str):
    now = datetime.now(LOG_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


# ==================== 任务实现 ====================

def task_st_analyze() -> bool:
    """周一：gen_all.py 生成摘帽股票 → ST股统计分析"""
    log("▶ [周一] 刷新 ST股统计分析（gen_all.py）")
    gen_all = os.path.join(TASK_ROOT, "tmp_script", "gen_all.py")
    return _run_python_script(gen_all, label="gen_all.py")


def task_st_overview() -> bool:
    """周二：gen_all.py 生成摘帽股票 → ST股个股表现"""
    log("▶ [周二] 刷新 ST股个股表现（gen_all.py）")
    gen_all = os.path.join(TASK_ROOT, "tmp_script", "gen_all.py")
    return _run_python_script(gen_all, label="gen_all.py")


def task_st_time() -> bool:
    """周三：scan_all() → ST股摘帽时间"""
    log("▶ [周三] 刷新 ST股摘帽时间（scan_all）")
    try:
        from backend.app.services import st_time_service
        results = st_time_service.scan_all()
        out_path = os.path.join(TASK_ROOT, "backend", "data", "st_time_results.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"records": results}, f, ensure_ascii=False, indent=2)
        log(f"  ✅ 已保存 {len(results)} 只 -> {out_path}")
        return True
    except Exception as e:
        log(f"  ❌ scan_all 失败: {e}")
        import traceback; traceback.print_exc()
        return False


def _run_python_script(path: str, label: str = "script") -> bool:
    if not os.path.isfile(path):
        log(f"  ⚠ {path} 不存在，跳过"); return False
    try:
        r = subprocess.run(
            [sys.executable, path],
            cwd=TASK_ROOT, capture_output=False, timeout=1800)
        if r.returncode == 0:
            log(f"  ✅ {label} 完成"); return True
        else:
            log(f"  ❌ {label} 退出码 {r.returncode}"); return False
    except subprocess.TimeoutExpired:
        log(f"  ❌ {label} 超时（30分钟）"); return False
    except Exception as e:
        log(f"  ❌ {label} 失败: {e}"); return False


TASK_REGISTRY = {
    "st_analyze": task_st_analyze,
    "st_overview": task_st_overview,
    "st_time": task_st_time,
    "all": lambda: all([task_st_analyze(), task_st_overview(), task_st_time()]),
}


# ==================== 守护模式 ====================

def _next_trigger(now: datetime) -> tuple[datetime, str]:
    """找到下一个调度触发点：周一/二/三 00:00 + 随机延迟，返回 (触发时间, 任务名)"""
    # 计算未来 7 天内的周一/二/三 00:00
    candidates = []
    for day_offset in range(0, 8):
        target_date = (now + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        weekday = target_date.weekday()
        if weekday in SCHEDULE:
            # 加随机延迟 0~60 分钟
            delay = random.randint(0, 3600)
            fire_at = target_date + timedelta(seconds=delay)
            if fire_at > now:
                candidates.append((fire_at, SCHEDULE[weekday]))
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def daemon_loop():
    log("🛡 守护模式启动")
    log(f"  调度：周一→摘帽  周二→摘帽  周三→当前ST")
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    def _stop(signum, frame):
        log(f"收到信号 {signum}，退出"); cleanup(); sys.exit(0)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while True:
        now = datetime.now()
        fire_at, task_name = _next_trigger(now)
        wait_sec = (fire_at - now).total_seconds()
        log(f"📅 下次触发: {fire_at.strftime('%Y-%m-%d %H:%M:%S')}  "
            f"任务=[{task_name}]  等待≈{wait_sec/3600:.1f}h")

        # 分段 sleep 便于响应 SIGTERM
        while wait_sec > 0:
            chunk = min(wait_sec, 300)
            time.sleep(chunk)
            wait_sec -= chunk

        try:
            log("=" * 40)
            TASK_REGISTRY.get(task_name, lambda: None)()
            log("=" * 40)
        except Exception as e:
            log(f"❌ 任务执行异常: {e}")
            import traceback; traceback.print_exc()


def cleanup():
    try: os.remove(PID_FILE)
    except: pass


# ==================== 手动模式 ====================

def run_once(task_name: str, delay: bool = True) -> bool:
    fn = TASK_REGISTRY.get(task_name)
    if not fn:
        log(f"❌ 未知任务: {task_name}"); print(f"可用任务: {list(TASK_REGISTRY.keys())}"); return False
    if delay:
        d = random.randint(0, 3600)
        log(f"⏳ 随机延迟 {d//60}分 {d%60}秒（防IP封禁）"); time.sleep(d)
    return fn()


# ==================== 入口 ====================

def main():
    p = argparse.ArgumentParser(description="WebStock ST 定时刷新")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--daemon", action="store_true", help="守护模式（按周一/二/三自动触发）")
    g.add_argument("--run",    metavar="TASK",  help="手动跑一个任务: st_analyze / st_overview / st_time / all")
    g.add_argument("--now",    action="store_true", help="跑 all 并带随机延迟（兼容旧命令）")
    g.add_argument("--no-delay", action="store_true", help="配合 --run / --now 跳过随机延迟")
    args = p.parse_args()

    if args.daemon:
        daemon_loop()
    elif args.run:
        run_once(args.run, delay=not args.no_delay)
    elif args.now:
        run_once("all", delay=not args.no_delay)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
