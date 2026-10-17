"""Loopback-only HTTP and SSE service for daily alpha-factory summaries."""

import argparse
from collections import OrderedDict
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from itertools import islice
import math
import mimetypes
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
from urllib.parse import unquote, urlsplit
import webbrowser

from . import processes, rules
from .candidates import load_candidate_expressions
from .config import ConfigError, configure, spider_root
from .logtail import Tail, cleanup_logs
from .progress import EMPTY_PROGRESS, load_progress
from .state import FactoryState
from .wq_day import wq_day, wq_window


class PanelRuntime:
    def __init__(self, root, *, day=None, mode="live", today=None, clock=None, progress_path=None, candidate_paths=None,
                 thresholds=None, daily_goal=rules.DAILY_CANDIDATE_GOAL):
        self.root = Path(root).expanduser().resolve()
        self.today = today or date.today
        self.clock = clock or time.time
        self.fixed_day = day is not None
        self.mode = "replay" if self.fixed_day and mode == "live" else mode
        self._process_checks = self.mode == "live"
        self._process_checked_at = None
        self._identity_cache = OrderedDict()
        self._agent_cache = OrderedDict()
        self.progress_path = self.root / "multi_simulation_progress.json" if self.mode == "demo" else (
            Path(progress_path) if progress_path is not None else None)
        self._progress = {}
        self._progress_revision = 0
        self._progress_checked_at = None
        self.candidate_paths = () if self.mode == "demo" else tuple(Path(path) for path in (candidate_paths or ()))
        self.thresholds, self.daily_goal = thresholds, daily_goal
        self._ledger = {}
        self._ledger_revision = 0
        self.day = day if day is not None else wq_day(self.clock())
        self.window = wq_window(self.day)
        self.state = FactoryState(self.day, clock=self.clock, thresholds=self.thresholds, daily_goal=self.daily_goal)
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.stop = threading.Event()
        self.thread = None
        self._open_tails()
        self._cache_key = None
        self._cache = None
        self._payload = None

    def _open_tails(self):
        self.tails = tuple(Tail(self.root / "log" / f"{day.isoformat()}.jsonl", snapshot=self.fixed_day)
                           for day in self.window.local_dates)
        # Keep the latest-file handle available for existing runtime callers.
        self.tail = self.tails[-1]

    @staticmethod
    def _row_time(line):
        value = line.get("ts") if isinstance(line, dict) else None
        if not isinstance(value, bool) and isinstance(value, (int, float)):
            try:
                if math.isfinite(value):
                    return value
            except OverflowError:
                pass
        return float("inf")

    def _read_batch(self):
        rows = []
        for tail in self.tails:
            remaining = rules.MAX_LINES_PER_POLL-len(rows)
            if remaining <= 0:
                break
            for raw in islice(tail.read_lines(), remaining):
                try:
                    rows.append(json.loads(raw) if raw is not None else None)
                except (ValueError, UnicodeError):
                    rows.append(None)
        # Adjacent local files can contain late appends; equal timestamps retain
        # their recorded order so parameter-only starts still precede their ends.
        rows.sort(key=self._row_time)
        return rows

    def _rollover(self):
        new_day = wq_day(self.clock())
        if self.fixed_day or new_day == self.day:
            return
        self.state.close()
        self.day = new_day
        self.window = wq_window(self.day)
        self.state = FactoryState(self.day, clock=self.clock, thresholds=self.thresholds, daily_goal=self.daily_goal)
        # Start from byte zero, including the shared local file: its existing
        # rows can already belong to the new WQ day. State filters by timestamp.
        self._open_tails()
        self._process_checked_at = None
        self._identity_cache.clear()
        self._agent_cache.clear()
        self._progress_checked_at = None

    @staticmethod
    def _remember(cache, key, value):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > rules.PROCESS_CACHE_MAX:
            cache.popitem(last=False)
        return value

    def _identify(self, line):
        if not isinstance(line, dict) or "agent" in line:
            return line
        pid, ppid = line.get("pid"), line.get("ppid")
        if type(pid) is not int or pid <= 0:
            return line
        if ppid is not None and (type(ppid) is not int or ppid < 0):
            return line
        key = (pid, ppid)
        if key in self._identity_cache:
            identity = self._identity_cache[key]
            self._identity_cache.move_to_end(key)
        else:
            identity = {}
            try:
                if processes.process_alive(pid):
                    parent = ppid or processes.parent_pid(pid)
                    if parent:
                        if parent not in self._agent_cache:
                            self._remember(self._agent_cache, parent, processes.parent_agent(parent))
                        else:
                            self._agent_cache.move_to_end(parent)
                        identity = {"ppid": parent, "agent": self._agent_cache[parent]}
            except Exception:
                pass  # Missing metadata must never discard a valid log row.
            self._remember(self._identity_cache, key, identity)
        return {**line, **identity} if identity else line

    def _check_processes(self):
        if not self._process_checks:
            return
        now = self.clock()
        if self._process_checked_at is None or now-self._process_checked_at >= rules.PROCESS_CHECK_SECONDS or now < self._process_checked_at:
            self._process_checked_at = now
            self.state.check_processes(processes.process_alive)

    def poll(self):
        with self.changed:
            previous = (self.day, self.state.revision, self._progress_revision, self._ledger_revision)
            self._rollover()
            for line in self._read_batch():
                in_window = self.window.start <= self._row_time(line) < self.window.end
                self.state.feed(self._identify(line) if self._process_checks and in_window else line)
            self._check_processes()
            now = self.clock()
            if self._progress_checked_at is None or now-self._progress_checked_at >= rules.PROGRESS_POLL_SECONDS or now < self._progress_checked_at:
                self._progress_checked_at = now
                progress = (load_progress(self.progress_path) or {}) if self.progress_path is not None else {}
                if progress != self._progress:
                    self._progress = progress
                    self._progress_revision += 1
                ledger = load_candidate_expressions(self.candidate_paths) if self.candidate_paths else {}
                if ledger != self._ledger:
                    self._ledger = ledger
                    self._ledger_revision += 1
            self.state.refresh()
            if previous != (self.day, self.state.revision, self._progress_revision, self._ledger_revision):
                self.changed.notify_all()

    def payload(self):
        with self.lock:
            self.state.refresh()
            key = (self.day, self.state.revision, self._progress_revision, self._ledger_revision)
            if key != self._cache_key:
                self._cache = self.state.snapshot(self.mode)
                for sim in self._cache["pending_sims"]:
                    sim.update(self._progress.get(sim["sim"], EMPTY_PROGRESS))
                for alpha in [*self._cache["alphas"], *self._cache["review"], self._cache["best"]]:
                    if alpha is not None and alpha["id"] in self._ledger:
                        alpha["expr"] = self._ledger[alpha["id"]]
                self._payload = json.dumps(self._cache, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
                self._cache_key = (self.day, self.state.revision, self._progress_revision, self._ledger_revision)
            return self._cache_key, self._payload

    def snapshot(self):
        return json.loads(self.payload()[1])

    def start(self):
        (self.root / "log").mkdir(parents=True, exist_ok=True)
        cleanup_logs(self.root / "log", self.today())
        self.poll()
        self.thread = threading.Thread(target=self._follow, name="factory-logtail", daemon=True)
        self.thread.start()

    def _follow(self):
        while not self.stop.wait(rules.POLL_SECONDS):
            try:
                self.poll()
            except OSError as error:
                print(f"[SpiderPanel] 日志读取失败，稍后重试: {error}", file=sys.stderr)

    def close(self):
        self.stop.set()
        with self.changed:
            self.changed.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=3)
        with self.lock:
            self.state.close()
            self._identity_cache.clear()
            self._agent_cache.clear()


def make_handler(runtime, web_root=None):
    web_root = Path(web_root or Path(__file__).parent / "web").resolve()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            if getattr(self, "_api_response", False) or getattr(self, "path", "").startswith("/api/"):
                self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _send(self, status, body=b"", content_type="text/plain; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if content_type.split(";", 1)[0] == "text/html":
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                hosts = self.headers.get_all("Host", [])
                expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
                if len(hosts) != 1 or hosts[0] not in expected:
                    self._send(403, b"Forbidden Host")
                    return
                parsed = urlsplit(self.path)
                if parsed.scheme or parsed.netloc:
                    self._send(404)
                    return
                path = unquote(parsed.path, errors="strict")
                self._api_response = path.startswith("/api/")
                if path == "/api/state":
                    self._send(200, runtime.payload()[1], "application/json; charset=utf-8")
                elif path == "/api/stream":
                    self._stream()
                else:
                    self._static(path)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                self.close_connection = True
            except (ValueError, UnicodeError):
                self._send(404)

        def _static(self, path):
            try:
                target = (web_root / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
                if not target.is_relative_to(web_root) or not target.is_file():
                    self._send(404)
                    return
                data = target.read_bytes()
            except (OSError, ValueError):
                self._send(404)
                return
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in ("application/json", "application/javascript"):
                content_type += "; charset=utf-8"
            self._send(200, data, content_type)

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.connection.settimeout(2)
            last_key, last_sent, last_heartbeat = None, -float("inf"), time.monotonic()
            try:
                while not runtime.stop.is_set():
                    key, payload = runtime.payload()
                    now = time.monotonic()
                    if key != last_key and now-last_sent >= rules.SSE_MIN_INTERVAL:
                        self.wfile.write(b"event: state\ndata: " + payload + b"\n\n")
                        self.wfile.flush()
                        last_key, last_sent = key, now
                    if now-last_heartbeat >= rules.SSE_HEARTBEAT_SECONDS:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        last_heartbeat = now
                    with runtime.changed:
                        runtime.changed.wait(timeout=min(0.25, rules.SSE_MIN_INTERVAL, rules.SSE_HEARTBEAT_SECONDS))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                pass
            finally:
                self.close_connection = True

    return Handler


def make_server(runtime, port=0, web_root=None):
    class HTTPServer(ThreadingHTTPServer):
        daemon_threads = True

    return HTTPServer(("127.0.0.1", port), make_handler(runtime, web_root))


def _day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError:
        raise argparse.ArgumentTypeError("日期必须是 YYYY-MM-DD") from None


def _port(value):
    try:
        port = int(value)
        if not 0 <= port <= 65535:
            raise ValueError
        return port
    except ValueError:
        raise argparse.ArgumentTypeError("端口必须是 0–65535 的整数") from None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="本机 WQ Alpha Factory 仪表盘后端")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--day", type=_day, help="重放指定 WQ 日（纽约日期 YYYY-MM-DD）")
    mode.add_argument("--demo", action="store_true", help="在独立临时目录生成演示数据")
    parser.add_argument("--open", action="store_true", help="打开本机浏览器")
    parser.add_argument("--port", type=_port, help="HTTP 端口，0 表示随机分配")
    parser.add_argument("--config", help="指定 JSON 配置文件")
    parser.add_argument("--progress-file", help="只读回测进度注册表路径")
    parser.add_argument("--candidates-file", action="append", help="只读候选台账路径，可重复指定")
    parser.add_argument("--thresholds", help="展示阈值 JSON 文件，覆盖配置中的阈值")
    options = parser.parse_args(argv)
    if options.port is None:
        try:
            options.port = _port(os.environ.get(rules.PANEL_PORT_ENV, str(rules.PANEL_PORT)))
        except argparse.ArgumentTypeError as error:
            parser.error(str(error))
    return options


def main(argv=None):
    options = parse_args(argv)
    try:
        config = configure(options)
    except ConfigError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 1
    root = Path(tempfile.mkdtemp(prefix="wq-alpha-factory-")) if options.demo else spider_root()
    feeder = None
    if options.demo:
        from .demo import DemoFeeder
        feeder = DemoFeeder(root / "log", clock=time.time)
    runtime = PanelRuntime(root, day=options.day, mode="demo" if options.demo else "live",
                           clock=feeder.clock if feeder else None,
                           today=(lambda: date.fromtimestamp(feeder.clock())) if feeder else None,
                           progress_path=config["progress_file"], candidate_paths=config["candidate_files"],
                           thresholds=config["thresholds"], daily_goal=config["daily_goal"])
    httpd = None
    old_handlers = {}
    try:
        try:
            httpd = make_server(runtime, port=options.port)
        except OSError as error:
            print(f"无法监听 127.0.0.1:{options.port}；请检查端口是否被占用或是否允许监听：{error}。"
                  "可用 --port 或环境变量 WQ_PANEL_PORT 换端口。", file=sys.stderr)
            return 1
        if options.demo:
            feeder.start()
        runtime.start()
        url = f"http://127.0.0.1:{httpd.server_port}/"
        print(url, flush=True)
        if options.open:
            webbrowser.open(url)

        def stop(signum, frame):
            threading.Thread(target=httpd.shutdown, daemon=True).start()
        for signum in (signal.SIGINT, signal.SIGTERM):
            old_handlers[signum] = signal.signal(signum, stop)
        httpd.serve_forever(poll_interval=0.1)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        if feeder is not None:
            feeder.stop()
        runtime.close()
        if httpd is not None:
            httpd.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
