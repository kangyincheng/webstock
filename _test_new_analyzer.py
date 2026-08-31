"""端到端测试新版 STAnalyzer（真实 baostock，经代理隧道）。

代理补丁由 _test_sitepatch/sitecustomize.py 提供（PYTHONPATH 注入，
父进程与 spawn 子进程均自动生效）。

注意：spawn 多进程要求主模块有 __main__ 保护，否则子进程重导入会递归。
"""
import sys, time

sys.path.insert(0, "/workspace/src")


def main():
    from st_analyzer import STAnalyzer
    t0 = time.time()
    az = STAnalyzer(data_dir="/tmp/stdata2")
    df = az.scan_and_analyze(months_back=10, before_days=30, after_days=30,
                             progress_callback=lambda m: print(m),
                             workers=8)
    dt = time.time() - t0
    print(f"\n=== 耗时 {dt:.1f}s，结果 {len(df)} 行 ===")
    print(df.head(20).to_string())


if __name__ == "__main__":
    main()
