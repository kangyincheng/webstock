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
    0: ["st_analyze", "tender_offer"],     # 周一
    1: ["st_overview", "tender_offer"],    # 周二
    2: ["st_time", "tender_offer"],        # 周三
    3: ["tender_offer"],                   # 周四
    4: ["tender_offer"],                   # 周五
}

# tender_offer 的具体触发时间（每个交易日）
TENDER_TRIGGER_HOUR = 1
TENDER_TRIGGER_MIN = 30


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


def task_tender_offer():
    """每个交易日 01:30：刷新要约收购（A 股 + 港股）"""
    log(">> [交易日] 刷新要约收购（A 股 + 港股）")
    try:
        from backend.app.services.market_service import MarketServices
        ms = MarketServices()
        a_rows = ms.tender_offer("cn")
        h_rows = ms.tender_offer("hk")
        out_path = os.path.join(TASK_ROOT, "backend", "data", "tender_results.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        now_str = datetime.now(LOG_TZ).strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "cn": {"rows": a_rows},
            "hk": {"rows": h_rows},
            "updated_at": now_str,
        }
        tmp = out_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, out_path)
        log("  OK A股=%d 条 港股=%d 条 -> %s" % (len(a_rows), len(h_rows), out_path))
        return True
    except Exception as e:
        log("  FAIL tender_offer: %s" % e)
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
    "tender_offer": task_tender_offer,
    "all": lambda: all([task_st_analyze(), task_st_overview(), task_st_time(), task_tender_offer()]),
}


# ==================== 守护模式 ====================

def _next_triggers(now):
    """找到下一批要触发的任务，返回 [(fire_at, task_name), ...]。

    调度规则：
      - ST 任务（st_analyze/st_overview/st_time）: 周一/二/三 00:00 + 随机延迟 0~60min
      - Tender 任务（tender_offer）: 周一~周五 01:30
    """
    candidates = []
    for day_offset in range(0, 8):
        target_date = (now + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        weekday = target_date.weekday()
        if weekday in SCHEDULE:
            for task_name in SCHEDULE[weekday]:
                if task_name == "tender_offer":
                    # tender 固定 01:30
                    fire_at = target_date.replace(hour=TENDER_TRIGGER_HOUR, minute=TENDER_TRIGGER_MIN)
                else:
                    # ST 任务 00:00 + 随机延迟
                    delay = random.randint(0, 3600)
                    fire_at = target_date + timedelta(seconds=delay)
                if fire_at > now:
                    candidates.append((fire_at, task_name))
    candidates.sort(key=lambda x: x[0])
    # 返回前一个（最小的那个）
    return candidates[0] if candidates else None


def daemon_loop():
    log("!! 守护模式启动")
    log("  调度：周一->摘帽+Tender  周二->摘帽+Tender  周三->当前ST+Tender  周四五->Tender(01:30)")
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
        item = _next_triggers(now)
        if item is None:
            log("!! 没有找到下一个触发点（SCHEDULE 为空？），60s 后重试")
            time.sleep(60)
            continue
        fire_at, task_name = item
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
