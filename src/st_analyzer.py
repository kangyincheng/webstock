"""ST 股票摘帽分析。

数据源：baostock。

核心策略（isST 转折检测法）：
  1. 拉取最新交易日全市场 A 股代码与当前名称
  2. 多子进程并行拉取每只股票的日 K，用 isST 字段在窗口内定位最近一次摘帽日（isST 1->0）
  3. 对每只摘帽股计算摘帽前 N 天 / 摘帽后 N 天涨跌幅，并取摘帽日收盘价、peTTM、pbMRQ

为什么不用「历史名称比对」：
  实测 baostock query_all_stock(day=历史日期) 返回的是每只股票的**当前最新名称**
  （相隔 9 个月的两个快照名称差异恒为 0），因此「N 个月前名称含 ST、现在不含 ST」
  的比对永远得到 0 只摘帽股。必须以日 K isST 由 1 变 0 作为摘帽判据。

为什么用 subprocess 而不是 multiprocessing 进程池：
  baostock 基于全局 socket，无法多线程共享，只能多进程并行；而
  multiprocessing 的 spawn 会重导入宿主 __main__（gunicorn/uvicorn 下危险），
  fork 在多线程宿主内可能死锁。独立子进程（st_scan_worker.py）最稳妥。

字段定义：
  isST = 1 表示当日处于 ST/*ST 状态；isST = 0 表示正常
"""
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse

import pandas as pd


# ---------------- 受限网络自动隧道（baostock 裸 TCP 不走 HTTP_PROXY）----------------
_PROXY_PATCH_APPLIED = False


def _ensure_proxy_tunnel():
    """baostock 用裸 TCP 连接 public-api.baostock.com:10030，不认 HTTP_PROXY。

    在受限网络（如沙箱，直连超时）中，自动把 socket.connect 改走 HTTP CONNECT
    隧道。策略：
      1. 快速探测 baostock 服务器是否可直连（3s 超时）——可达则不做任何事，
         保证直连环境（生产服务器）零影响；
      2. 不可达且配置了代理（BS_PROXY_HOST/BS_PROXY_PORT 优先，
         否则解析 HTTP_PROXY）时，安装全局 socket.connect 隧道补丁。

    模块导入时调用一次，主进程与 subprocess 子进程（worker 导入本模块）均生效。
    """
    global _PROXY_PATCH_APPLIED
    if _PROXY_PATCH_APPLIED:
        return
    _PROXY_PATCH_APPLIED = True

    # 1) 探测直连
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("public-api.baostock.com", 10030))
        s.close()
        return  # 直连可用，无需补丁
    except Exception:
        pass

    # 2) 解析代理地址
    host = os.environ.get("BS_PROXY_HOST", "")
    port = os.environ.get("BS_PROXY_PORT", "")
    if not host or not port:
        proxy_url = (os.environ.get("HTTP_PROXY")
                     or os.environ.get("http_proxy") or "")
        if proxy_url:
            if "//" not in proxy_url:
                proxy_url = "http://" + proxy_url
            p = urlparse(proxy_url)
            host = p.hostname or ""
            port = str(p.port or "")
    if not host or not port:
        return
    try:
        port_int = int(port)
    except ValueError:
        return

    _orig_connect = socket.socket.connect
    _local = {"127.0.0.1", "localhost", "::1"}

    def _patched_connect(self, address):
        if isinstance(address, tuple) and address and address[0] not in _local:
            _orig_connect(self, (host, port_int))
            req = (f"CONNECT {address[0]}:{address[1]} HTTP/1.1\r\n"
                   f"Host: {address[0]}:{address[1]}\r\n\r\n").encode()
            self.sendall(req)
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = self.recv(4096)
                if not chunk:
                    break
                resp += chunk
            first = resp.split(b"\r\n", 1)[0]
            if b" 200" not in first:
                raise ConnectionError(f"CONNECT failed: {first!r}")
            return
        return _orig_connect(self, address)

    socket.socket.connect = _patched_connect


_ensure_proxy_tunnel()


def _import_baostock():
    try:
        import baostock as bs
        return bs
    except ImportError:
        raise ImportError("未安装 baostock 模块，请先执行：pip install baostock")


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _months_ago(months):
    """获取 N 个月前的日期字符串。"""
    today = datetime.now()
    # 近似：每月按 30 天
    target = today - timedelta(days=30 * months)
    return target.strftime("%Y-%m-%d")


def _name_has_st(name):
    """判断股票名称是否包含 ST 标识（ST / *ST / S*ST 等）。"""
    if not name:
        return False
    return "ST" in str(name).upper()


# 日 K 线查询字段（含 isST 与估值指标）
KLINE_FIELDS = "date,code,close,isST,peTTM,pbMRQ"


# ---------------- baostock 数据拉取（模块级，供子进程复用）----------------
def _fetch_kline(bs, code, start_date, end_date):
    """拉取日 K。出错返回 None；无数据返回空 DataFrame。"""
    rs = bs.query_history_k_data_plus(
        code,
        KLINE_FIELDS,
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="2",  # 前复权
    )
    if rs.error_code != "0":
        return None
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=rs.fields)
    for col in ["close", "isST", "peTTM", "pbMRQ"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _find_last_uncap(df, win_start, win_end):
    """在 [win_start, win_end] 窗口内找出最近一次摘帽日（isST 由 1 -> 0）。

    返回 (uncap_date, st_start_date) 或 None：
      - uncap_date: 窗口内最后一次 isST 1->0 的交易日
      - st_start_date: 紧邻该次摘帽的 ST 段起始日（最近一次 0->1；
        若 ST 段起点早于窗口，则取窗口内最早的 isST=1 日期近似）
    """
    if df is None or df.empty or "isST" not in df.columns:
        return None
    df = df.sort_values("date").reset_index(drop=True)
    mask = (df["date"] >= win_start) & (df["date"] <= win_end)
    w = df[mask].reset_index(drop=True)
    if w.empty:
        return None
    # 找最后一次 isST 由 1 变 0 的位置
    uncap_idx = None
    for i in range(1, len(w)):
        if w.loc[i - 1, "isST"] == 1 and w.loc[i, "isST"] == 0:
            uncap_idx = i  # 持续覆盖以取最近一次
    if uncap_idx is None:
        return None  # 窗口内无摘帽事件
    uncap_date = w.loc[uncap_idx, "date"]
    # 紧邻摘帽的 ST 段起始日：摘帽日前最近一次 0->1
    st_start = None
    for i in range(uncap_idx - 1, 0, -1):
        if w.loc[i - 1, "isST"] == 0 and w.loc[i, "isST"] == 1:
            st_start = w.loc[i, "date"]
            break
    if st_start is None:
        # ST 段起点早于窗口：取摘帽前窗口内最早的 isST=1 日期近似
        pre = w.iloc[:uncap_idx]
        pre_mask = pre["isST"] == 1
        if pre_mask.any():
            st_start = pre.loc[pre_mask, "date"].iloc[0]
        else:
            return None
    return uncap_date, st_start


def _compute_change(df, uncap_date, before_days, after_days):
    """计算摘帽前 N 天 / 后 N 天涨跌幅。

    返回 (pre_change_pct, post_change_pct, close_at_uncap, pe_at_uncap, pb_at_uncap)。
    若数据不足返回 None。
    """
    if df is None or df.empty:
        return None
    df = df.sort_values("date").reset_index(drop=True)
    # 找摘帽日的位置
    idx_list = df.index[df["date"] == uncap_date].tolist()
    if not idx_list:
        return None
    uncap_idx = idx_list[0]

    # 摘帽前 N 天
    start_pre = max(0, uncap_idx - before_days)
    if start_pre >= uncap_idx:
        return None
    pre_close_start = df.loc[start_pre, "close"]
    pre_close_end = df.loc[uncap_idx - 1, "close"]
    if pd.isna(pre_close_start) or pd.isna(pre_close_end) or pre_close_start == 0:
        return None
    pre_change = (pre_close_end - pre_close_start) / pre_close_start * 100.0

    # 摘帽后 N 天
    end_post = min(len(df) - 1, uncap_idx + after_days)
    if end_post <= uncap_idx:
        post_change = 0.0
    else:
        post_close_start = df.loc[uncap_idx, "close"]
        post_close_end = df.loc[end_post, "close"]
        if pd.isna(post_close_start) or pd.isna(post_close_end) or post_close_start == 0:
            post_change = None
        else:
            post_change = (post_close_end - post_close_start) / post_close_start * 100.0

    # 摘帽日的估值与收盘价
    row_uncap = df.loc[uncap_idx]
    close_at_uncap = row_uncap.get("close")
    pe_at_uncap = row_uncap.get("peTTM")
    pb_at_uncap = row_uncap.get("pbMRQ")
    # 处理 NaN
    if pd.isna(pe_at_uncap):
        pe_at_uncap = None
    if pd.isna(pb_at_uncap):
        pb_at_uncap = None
    if pd.isna(close_at_uncap):
        close_at_uncap = None
    return pre_change, post_change, close_at_uncap, pe_at_uncap, pb_at_uncap


# ---------------- 子进程并行扫描（subprocess，宿主安全）----------------
_WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "st_scan_worker.py")


def _run_workers(tasks, buffer_start, win_start, win_end,
                 before_days, after_days, workers, log):
    """把 tasks 均分给 workers 个子进程，汇总结果。

    tasks: [(code, name), ...]
    返回 (results, failed_count)
    """
    import json
    import threading

    n = max(1, min(workers, len(tasks)))
    chunks = [[] for _ in range(n)]
    for i, t in enumerate(tasks):
        chunks[i % n].append(t)

    results = []
    failed = [0]
    done_total = [0]
    lock = threading.Lock()

    def run_one(chunk):
        if not chunk:
            return
        argv = [sys.executable, _WORKER_SCRIPT,
                buffer_start, win_start, win_end,
                str(before_days), str(after_days)]
        payload = json.dumps(chunk, ensure_ascii=False)
        try:
            proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
            out, _ = proc.communicate(input=payload, timeout=1500)
        except Exception as e:
            with lock:
                failed[0] += len(chunk)
            log(f"子进程异常：{e}")
            return
        if proc.returncode != 0:
            with lock:
                failed[0] += len(chunk)
            return
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            mtype = msg.get("type")
            if mtype == "result":
                with lock:
                    results.append(msg["row"])
            elif mtype == "progress":
                with lock:
                    done_total[0] += msg.get("done", 0) - _last_done.get(id(chunk), 0)
                    _last_done[id(chunk)] = msg.get("done", 0)
                    if done_total[0] % 500 < 50 or done_total[0] >= total_tasks:
                        log(f"进度 {min(done_total[0], total_tasks)}/{total_tasks}  "
                            f"已找到 {len(results)} 只摘帽股")
            elif mtype == "fatal":
                log(f"子进程致命错误：{msg.get('message')}")

    _last_done = {}
    total_tasks = sum(len(c) for c in chunks)
    threads = [threading.Thread(target=run_one, args=(c,), daemon=True)
               for c in chunks]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, failed[0]


class STAnalyzer:
    """ST 摘帽分析器（isST 转折检测法）。

    使用方式：
        analyzer = STAnalyzer(data_dir="data")
        df = analyzer.scan_and_analyze(
            months_back=10, before_days=30, after_days=30,
            progress_callback=print)
    """

    KLINE_FIELDS = KLINE_FIELDS

    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    # ---------------- baostock 登录/登出 ----------------
    def _login(self):
        bs = _import_baostock()
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"Baostock login failed: {lg.error_msg}")
        return bs

    def _logout(self, bs):
        try:
            bs.logout()
        except Exception:
            pass

    # ---------------- 全市场 A 股 + 名称（按日期快照）----------------
    def _get_all_stock_with_names(self, bs, target_date, max_lookback=15):
        """获取指定日期（或最近交易日）全市场 A 股代码与名称。

        注意：baostock 对历史日期返回的也是当前名称，这里只用它取代码清单
        与确定窗口边界交易日。

        返回 (name_map, actual_date)：
          name_map = {code: name}（仅 A 股主板/创业板/科创板，排除指数、基金）
          actual_date = 实际命中的交易日字符串（YYYY-MM-DD）
        """
        base = datetime.strptime(target_date, "%Y-%m-%d")
        for back in range(max_lookback):
            day = (base - timedelta(days=back)).strftime("%Y-%m-%d")
            rs = bs.query_all_stock(day=day)
            if rs.error_code != "0":
                continue
            # 手动迭代取数，避免依赖 ResultSet.get_data（其内部 df.append
            # 在 pandas>=2.0 已移除）
            rows = []
            try:
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
            except Exception:
                rows = []
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=rs.fields)
            if df.empty or "code" not in df.columns:
                continue
            mask = df["code"].astype(str).str.match(r"^(sh\.6|sh\.688|sz\.0|sz\.3)")
            df_a = df[mask]
            if df_a.empty:
                continue
            name_col = next(
                (c for c in df_a.columns if "name" in c.lower()), None)
            name_map = {}
            for _, r in df_a.iterrows():
                code = str(r["code"])
                name = str(r[name_col]) if (name_col and name_col in df_a.columns) else ""
                name_map[code] = name
            return name_map, day
        return {}, target_date

    # 保留旧接口别名（桌面端/测试可能引用）
    @staticmethod
    def _find_uncap_date_in_window(df, start_date, end_date):
        return _find_last_uncap(df, start_date, end_date)

    @staticmethod
    def _compute_change(df, uncap_date, before_days, after_days):
        return _compute_change(df, uncap_date, before_days, after_days)

    # ---------------- 主入口：扫描并分析 ----------------
    def scan_and_analyze(self, months_back=10, before_days=30, after_days=30,
                         progress_callback=None, workers=None):
        """扫描最近 N 个月内摘帽的 ST 股，计算摘帽前/后涨跌幅。

        策略：
          1. 拉取最新交易日全市场 A 股代码（含当前名称）
          2. 多进程并行拉取每只股票日 K，用 isST 1->0 转折定位窗口内最近一次摘帽日
          3. 计算摘帽前/后 N 个交易日涨跌幅与摘帽日估值指标

        Args:
            months_back: 摘帽事件回溯的月数（默认 10）
            before_days: 摘帽前 N 个交易日（默认 30）
            after_days: 摘帽后 N 个交易日（默认 30）
            progress_callback: 回调函数 (msg) -> None
            workers: 并行进程数（默认取环境变量 ST_SCAN_WORKERS 或 6）

        Returns:
            DataFrame，列：股票名称, 代码, 开始ST日期, 结束ST日期,
                          摘帽前涨幅, 摘帽后涨幅, 市盈率, 市净率, 收盘价
        """
        today = _today_str()
        start_target = _months_ago(months_back)
        # 为了计算摘帽前 N 天，K 线再多回溯 3 个月作为缓冲
        buffer_start = _months_ago(months_back + 3)

        def log(msg):
            if progress_callback:
                progress_callback(msg)

        log("登录 baostock ...")
        bs = self._login()
        try:
            # 1. 最新交易日全市场 A 股（代码 + 当前名称）
            log(f"获取最新交易日全市场股票名称（目标 {today}）...")
            latest_map, end_date = self._get_all_stock_with_names(bs, today)
            log(f"最新交易日 {end_date}：共 {len(latest_map)} 只 A 股")
            if not latest_map:
                raise RuntimeError("获取最新交易日全市场股票列表失败（baostock 不可达？）")

            # 2. 确定窗口起始交易日（N 个月前）
            log(f"定位 {months_back} 个月前的起始交易日（目标 {start_target}）...")
            _, start_date = self._get_all_stock_with_names(bs, start_target)
            log(f"摘帽检测窗口：{start_date} ~ {end_date}（依据日K isST 1->0 转折）")
        finally:
            self._logout(bs)

        if workers is None:
            try:
                workers = int(os.environ.get("ST_SCAN_WORKERS", "8"))
            except ValueError:
                workers = 8
        workers = max(1, min(workers, 16))

        codes = sorted(latest_map.keys())
        total = len(codes)
        log(f"开始并行扫描 {total} 只股票（并行度 {workers}）...")
        tasks = [(c, latest_map[c]) for c in codes]

        results, failed = _run_workers(
            tasks, buffer_start, start_date, end_date,
            before_days, after_days, workers, log)

        if failed:
            log(f"扫描结束：{failed} 只股票取数失败（已跳过）")
        log(f"扫描完成，共找到 {len(results)} 只摘帽 ST 股")

        cols = ["股票名称", "代码", "开始ST日期", "结束ST日期",
                "摘帽前涨幅", "摘帽后涨幅", "市盈率", "市净率", "收盘价"]
        if not results:
            return pd.DataFrame(columns=cols)
        df_out = pd.DataFrame(results, columns=cols)
        # 按摘帽日倒序
        df_out = df_out.sort_values("结束ST日期", ascending=False).reset_index(drop=True)
        return df_out
