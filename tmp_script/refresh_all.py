#!/usr/bin/env python3
"""每周日 0 点随机延迟后刷新 ST 摘帽 + ST 恢复上市两个数据文件。

运行方式：
  1. 手动立即刷新：  python3 refresh_all.py --now
  2. 后台守护运行：  nohup python3 refresh_all.py --daemon > refresh.log 2>&1 &
     （守护模式会自己算下一个周日 0 点 + 随机延迟，循环等待触发）
  3. 交给 crontab：  在 crontab 里加：
       0 0 * * 0  cd /workspace && python3 /workspace/tmp_script/refresh_all.py --now >> /workspace/tmp_script/refresh.log 2>&1

随机延迟：0-60 分钟（避免集中访问新浪/巨潮被封 IP）
"""
from __future__ import annotations

import argparse
import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TASK_ROOT)

PID_FILE = "/tmp/webstock_refresh.pid"

LOG_TZ = timezone(timedelta(hours=8))


def log(msg: str):
    now = datetime.now(LOG_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


# ==================== 两个刷新任务 ====================

def refresh_st_delisted() -> bool:
    """刷新 ST 摘帽股票数据（跑 gen_all.py）。"""
    log("▶ ST 摘帽股票刷新开始")
    gen_all_path = os.path.join(TASK_ROOT, "tmp_script", "gen_all.py")
    if not os.path.isfile(gen_all_path):
        log(f"  ⚠ {gen_all_path} 不存在，跳过摘帽刷新")
        return True
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, gen_all_path],
            cwd=TASK_ROOT, capture_output=False, timeout=1800)  # 30 分钟
        if result.returncode == 0:
            log("  ✅ gen_all.py 完成")
            return True
        else:
            log(f"  ❌ gen_all.py 退出码 {result.returncode}")
            return False
    except subprocess.TimeoutExpired:
        log("  ❌ gen_all.py 超时（30分钟）")
        return False
    except Exception as e:
        log(f"  ❌ ST 摘帽刷新失败: {e}")
        import traceback; traceback.print_exc()
        return False


def refresh_st_reinstate() -> bool:
    """刷新当前 ST 股票 + 可申请摘帽日。"""
    log("▶ ST 恢复上市刷新开始")
    try:
        from backend.app.services import st_time_service
        results = st_time_service.scan_all()
        out = {"records": results, "logs": [f"扫描 {len(results)} 只", datetime.now(LOG_TZ).strftime("%Y-%m-%d %H:%M:%S")]}
        out_path = os.path.join(TASK_ROOT, "backend", "data", "st_time_results.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        import json
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        log(f"  ✅ 已保存 {len(results)} 只 -> {out_path}")
        return True
    except Exception as e:
        log(f"  ❌ ST 恢复上市刷新失败: {e}")
        import traceback; traceback.print_exc()
        return False


def run_once():
    log("=" * 50)
    log("🔄 定时刷新任务启动")
    delay = random.randint(0, 3600)  # 0-60 分钟随机延迟
    if delay > 0:
        log(f"⏳ 随机延迟 {delay // 60} 分 {delay % 60} 秒（防止 IP 被封）")
        time.sleep(delay)

    ok1 = refresh_st_delisted()
    ok2 = refresh_st_reinstate()
    log(f"🏁 刷新完成：摘帽={'✅' if ok1 else '❌'}  恢复上市={'✅' if ok2 else '❌'}")
    log("=" * 50)


# ==================== 守护模式 ====================

def next_sunday_midnight(now: datetime) -> datetime:
    """下一个周日 00:00（本地时间）。"""
    # weekday: 0=周一 6=周日
    days_ahead = (6 - now.weekday()) % 7
    target = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    if target <= now:
        target += timedelta(days=7)
    return target


def daemon_loop():
    """无限循环：算下一次触发时间 → 等待 → 执行 → 再算。"""
    log("🛡 守护模式启动，pid =", os.getpid())
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    def _stop(signum, frame):
        log(f"收到信号 {signum}，退出守护循环")
        try: os.remove(PID_FILE)
        except: pass
        sys.exit(0)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while True:
        now = datetime.now()
        target = next_sunday_midnight(now)
        delay = random.randint(0, 3600)
        run_at = target + timedelta(seconds=delay)
        wait_sec = (run_at - now).total_seconds()

        log(f"📅 下次执行时间: {run_at.strftime('%Y-%m-%d %H:%M:%S')} "
            f"(距现在 {wait_sec/3600:.1f} 小时)")

        # 分段 sleep 便于响应终止信号
        while wait_sec > 0:
            chunk = min(wait_sec, 300)  # 最多 5 分钟
            time.sleep(chunk)
            wait_sec -= chunk

        try:
            run_once()
        except Exception as e:
            log(f"❌ run_once 异常: {e}")
            import traceback; traceback.print_exc()
        # 执行完继续循环


# ==================== 入口 ====================

def main():
    parser = argparse.ArgumentParser(description="WebStock 定时刷新")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--now", action="store_true", help="立即执行一次（带随机延迟）")
    g.add_argument("--no-delay", action="store_true", help="立即执行且不延迟")
    g.add_argument("--daemon", action="store_true", help="守护模式（每周日自动触发）")
    args = parser.parse_args()

    if args.daemon:
        daemon_loop()
    elif args.no_delay:
        log("⏩ --no-delay，跳过随机延迟")
        refresh_st_delisted()
        refresh_st_reinstate()
    elif args.now:
        run_once()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
