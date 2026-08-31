"""调试：复现 ProcessPoolExecutor + initializer 场景下的真实异常。"""
import multiprocessing
import traceback
from concurrent.futures import ProcessPoolExecutor

import sys
sys.path.insert(0, "/workspace/src")
from st_analyzer import _pool_init, _pool_task

task = ("sh.600744", "2025-05-01", "2025-11-04", "2026-08-28", 30, 30, "华银电力")

ctx = multiprocessing.get_context("spawn")
with ProcessPoolExecutor(max_workers=2, mp_context=ctx, initializer=_pool_init) as pool:
    fut = pool.submit(_pool_task, task)
    try:
        r = fut.result(timeout=60)
        print("RESULT:", r)
    except Exception:
        traceback.print_exc()
