#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ST 股三任务定时刷新脚本（Python 3.6 兼容版）

调度计划：
  周一 00:00  随机延迟 0~60min -> gen_all.py  生成摘帽数据（ST股统计分析）
  周二 00:00  随机延迟 0~60min -> gen_all.py  生成摘帽数据（ST股个股表现）
  周三 00:00  随机延迟 0~60min -> scan_all() 生成当前 ST 股（ST股摘帽时间）

运行方式：
  python3 refresh_all.py --daemon              # 守护模式
  python3 refresh_all.py --run st_analyze      # 手动：只跑摘帽
  python3 refresh_all.py --run st_time         # 手动：只跑当前 ST
  python3 refresh_all.py --run all             # 手动：跑全部

  cron 版（如需）：
    0 0 * * 1  cd /var/www/webstock && python3 tmp_script/refresh_all.py --run st_analyze >> refresh.log 2>&1
    0 0 * * 2  cd /var/www/webstock && python3 tmp_script/refresh_all.py --run st_overview >> refresh.log 2>&1
    0 0 * * 3  cd /var/www/webstock && python3 tmp_script/refresh_all.py --run st_time    >> refresh.log 2>&1
"""
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

SCHEDULE = {
    0: "st_analyze",    # 周一
    1: "st_overview",   # 周二
    2: "st_time",       # 周三
}


def log(msg):
    now = datetime.now(LOG_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print("[%s] %s" % (now, msg), flush=True)


def task_st_analyze():
    """周一：gen_all.py"""
    log(">> [周一] 刷新 ST股统计分析（gen_all.py）")
    gen_all = os.path.join(TASK_ROOT, "tmp_script", "gen_all.py")
    return _run_python_script(gen_all, label="gen_all.py")


def task_st_overview():
    """周二：gen_all.py"""
    log(">> [周二] 刷新 ST股个股表现（gen_all.py）")
    gen_all = os.path.join(TASK_ROOT, "tmp_script", "gen_all.py")
    return _run_python_script(gen_all, label="gen_all.py")


def task_st_time():
    """周三：scan_all()"""
    log(">> [周三] 刷新 ST股摘帽时间（scan_all）")
    try:
        from backend.app.services import st_time_service
        results = st_time_service.scan_all()
        out_path = os.path.join(TASK_ROOT, "backend", "data", "st_time_results.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"records": results}, f, ensure_ascii=False, indent=2)
        log("  OK 已保存 %d 只 -> %s" % (len(results), out_path))
        return True
    except Exception as e:
        log("  FAIL scan_all: %s" % e)
        import traceback; traceback.print_exc()
        return False


def _run_python_script(path, label="script"):
    if not os.path.isfile(path):
        log("  SKIP %s 不存在" % path)
        return False
    try:
        r = subprocess.run(
            [sys.executable, path],
            cwd=TASK_ROOT, capture_output=False, timeout=1800)
        if r.returncode == 0:
            log("  OK %s 完成" % label)
            return True
        else:
            log("  FAIL %s 退出码 %s" % (label, r.returncode))
            return False
    except subprocess.TimeoutExpired:
        log("  FAIL %s 超时（30分钟）" % label)
        return False
    except Exception as e:
        log("  FAIL %s: %s" % (label, e))
        return False


TASK_REGISTRY = {
    "st_analyze": task_st_analyze,
    "st_overview": task_st_overview,
    "st_time": task_st_time,
    "all": lambda: all([task_st_analyze(), task_st_overview(), task_st_time()]),
}


# ==================== 守护模式 ====================

def _next_trigger(now):
    """找到下一个调度触发点，返回 (触发时间, 任务名)"""
    candidates = []
    for day_offset in range(0, 8):
        target_date = (now + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        weekday = target_date.weekday()
        if weekday in SCHEDULE:
            delay = random.randint(0, 3600)
            fire_at = target_date + timedelta(seconds=delay)
            if fire_at > now:
                candidates.append((fire_at, SCHEDULE[weekday]))
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def daemon_loop():
    log("!! 守护模式启动")
    log("  调度：周一->摘帽  周二->摘帽  周三->当前ST")
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    def _stop(signum, frame):
        log("收到信号 %s，退出" % signum)
        cleanup()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while True:
        now = datetime.now()
        fire_at, task_name = _next_trigger(now)
        wait_sec = (fire_at - now).total_seconds()
        log("下次触发: %s  任务=[%s]  等待~%.1fh" % (
            fire_at.strftime("%Y-%m-%d %H:%M:%S"), task_name, wait_sec / 3600))

        while wait_sec > 0:
            chunk = min(wait_sec, 300)
            time.sleep(chunk)
            wait_sec -= chunk

        try:
            log("=" * 40)
            fn = TASK_REGISTRY.get(task_name)
            if fn:
                fn()
            log("=" * 40)
        except Exception as e:
            log("FAIL 任务异常: %s" % e)
            import traceback; traceback.print_exc()


def cleanup():
    try:
        os.remove(PID_FILE)
    except Exception:
        pass


# ==================== 手动模式 ====================

def run_once(task_name, delay=True):
    fn = TASK_REGISTRY.get(task_name)
    if not fn:
        log("FAIL 未知任务: %s" % task_name)
        print("可用任务: %s" % list(TASK_REGISTRY.keys()))
        return False
    if delay:
        d = random.randint(0, 3600)
        log("等待 %d分 %d秒（防IP封禁）" % (d // 60, d % 60))
        time.sleep(d)
    return fn()


# ==================== 入口 ====================

def main():
    p = argparse.ArgumentParser(description="WebStock ST 定时刷新")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--daemon", action="store_true", help="守护模式（按周一/二/三自动触发）")
    g.add_argument("--run", metavar="TASK", help="手动跑: st_analyze / st_overview / st_time / all")
    g.add_argument("--now", action="store_true", help="跑 all 并带随机延迟（兼容旧命令）")
    p.add_argument("--no-delay", action="store_true", help="配合 --run / --now 跳过随机延迟")
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
