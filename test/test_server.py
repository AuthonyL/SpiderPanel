from contextlib import contextmanager
from datetime import date, datetime
import errno
import http.client
import io
import json
from pathlib import Path
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from SpiderPanel import rules, server
from test_state import DAY, TS, line


def append(root, day, data):
    path = root / "log" / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as file:
        file.write(json.dumps(data, ensure_ascii=False).encode() + b"\n")


@contextmanager
def running(root, **kwargs):
    runtime = server.PanelRuntime(root, **kwargs)
    try:
        httpd = server.make_server(runtime, port=0)
    except PermissionError as error:
        pytest.skip(f"Sandbox denies loopback listen: {error}")
    runtime.start()
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield runtime, httpd.server_port
    finally:
        runtime.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def get(port, path, host=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request("GET", path, headers={"Host": host or f"127.0.0.1:{port}"})
    response = connection.getresponse()
    status, headers, body = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return status, headers, body


def test_state_static_host_and_traversal(tmp_path):
    append(tmp_path, DAY, line("save", alpha="a1", saved=True, passed=True))
    with running(tmp_path, today=lambda: DAY, clock=lambda: TS+10) as (runtime, port):
        status, headers, body = get(port, "/api/state")
        state = json.loads(body)
        assert status == 200 and state["mode"] == "live"
        assert state["totals"]["candidates"] == 1 and len(state["cards"]) == 8
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert get(port, "/")[0] == 200
        assert b'src="/app.js"' in get(port, "/")[2]
        assert b'type="module"' in get(port, "/")[2]
        assert get(port, "/api/state", host=f"localhost:{port}")[0] == 200
        for path in ("/../state.py", "/%2e%2e/state.py", "/%2f..%2fstate.py", "/missing.js"):
            assert get(port, path)[0] == 404
        assert get(port, "/api/state", host=f"evil.example:{port}")[0] == 403
        assert get(port, "/", host="127.0.0.1:1")[0] == 403


def read_state(response):
    while True:
        line_bytes = response.readline()
        if line_bytes.startswith(b"data: "):
            return json.loads(line_bytes[6:])
        if not line_bytes:
            raise AssertionError("SSE ended before a state event")


def test_sse_initial_then_updated_snapshot_within_two_seconds(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rules, "POLL_SECONDS", 0.05)
    with running(tmp_path, today=lambda: DAY, clock=lambda: TS+10) as (runtime, port):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/api/stream")
        response = connection.getresponse()
        assert response.getheader("Content-Type").startswith("text/event-stream")
        first = read_state(response)
        start = time.monotonic()
        append(tmp_path, DAY, line("save", alpha="a1", passed=True, saved=True))
        second = read_state(response)
        elapsed = time.monotonic()-start
        assert 0.9 <= elapsed < 2
        assert second["revision"] > first["revision"] and second["totals"]["candidates"] == 1
        response.close()
        connection.close()
    assert "Traceback" not in capsys.readouterr().err


def test_cross_wq_day_and_replay_stays_on_requested_window(tmp_path):
    now = [TS+10]
    next_day = date(2026, 10, 16)
    append(tmp_path, DAY, line("save", alpha="old", saved=True))
    append(tmp_path, next_day, line("save", ts=TS+86400, alpha="new", saved=True))
    runtime = server.PanelRuntime(tmp_path, clock=lambda: now[0])
    runtime.poll()
    assert runtime.snapshot()["review"][0]["id"] == "old"
    now[0] = TS+86400
    runtime.poll()
    assert runtime.snapshot()["day"] == str(next_day)
    assert runtime.snapshot()["review"][0]["id"] == "new"
    replay = server.PanelRuntime(tmp_path, day=DAY, today=lambda: next_day, clock=lambda: TS+86400)
    replay.poll()
    assert replay.snapshot()["day"] == str(DAY) and replay.snapshot()["mode"] == "replay"


def test_bad_lines_and_half_line_then_next_poll(tmp_path):
    path = tmp_path / "log" / f"{DAY}.jsonl"
    path.parent.mkdir()
    data = json.dumps(line("save", alpha="a", saved=True)).encode()
    path.write_bytes(b"bad json\n" + data[:20])
    runtime = server.PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS+10)
    runtime.poll()
    assert runtime.state.bad_lines == 1 and runtime.snapshot()["totals"]["candidates"] == 0
    with path.open("ab") as file:
        file.write(data[20:] + b"\n")
    runtime.poll()
    assert runtime.snapshot()["totals"]["candidates"] == 1


def test_incomplete_old_day_does_not_block_rollover_forever(tmp_path):
    now = [TS]
    path = tmp_path / "log" / f"{DAY}.jsonl"
    path.parent.mkdir()
    path.write_bytes(b'{"incomplete":')
    runtime = server.PanelRuntime(tmp_path, clock=lambda: now[0])
    runtime.poll()
    now[0] = TS+86400
    append(tmp_path, date(2026, 10, 16), line("save", ts=now[0], alpha="new", saved=True))
    runtime.poll()
    assert runtime.snapshot()["day"] == "2026-10-16"
    assert runtime.snapshot()["totals"]["candidates"] == 1


def test_cli_port_precedence_and_validation(monkeypatch):
    monkeypatch.delenv("WQ_PANEL_PORT", raising=False)
    assert server.parse_args([]).port == 8788
    monkeypatch.setenv("WQ_PANEL_PORT", "8787")
    assert server.parse_args([]).port == 8787
    assert server.parse_args(["--port", "0"]).port == 0
    with pytest.raises(SystemExit):
        server.parse_args(["--port", "65536"])


def test_occupied_port_reports_override_options(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(rules.SPIDER_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(rules.PANEL_PORT_ENV, raising=False)

    def occupied(runtime, *, port):
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(server, "make_server", occupied)
    assert server.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Address already in use" in captured.err
    assert "可用 --port 或环境变量 WQ_PANEL_PORT 换端口" in captured.err


def test_module_entry_point_prints_help():
    import os
    import subprocess
    import sys
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-m", "SpiderPanel.server", "--help"],
                            cwd=Path(__file__).resolve().parents[2], env=env,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0
    assert "--demo" in result.stdout and "--day" in result.stdout and "--port" in result.stdout


def test_symlink_cannot_escape_static_root(tmp_path):
    root = tmp_path / "web"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    (root / "escape.txt").symlink_to(secret)
    runtime = server.PanelRuntime(tmp_path, today=lambda: DAY)
    try:
        httpd = server.make_server(runtime, port=0, web_root=root)
    except PermissionError as error:
        pytest.skip(f"Sandbox denies loopback listen: {error}")
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        assert get(httpd.server_port, "/escape.txt")[0] == 404
    finally:
        runtime.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def memory_request(runtime, path, host="127.0.0.1:8765", writer=None, web_root=None):
    """Exercise the real handler without a listening socket in restricted hosts."""
    handler_type = server.make_handler(runtime, web_root=web_root)
    handler = handler_type.__new__(handler_type)
    handler.server = SimpleNamespace(server_port=8765)
    handler.headers = http.client.HTTPMessage()
    handler.headers["Host"] = host
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET " + path + " HTTP/1.1"
    handler.command, handler.path = "GET", path
    handler.connection = SimpleNamespace(settimeout=lambda timeout: None)
    handler.wfile = writer if writer is not None else io.BytesIO()
    handler.do_GET()
    raw = handler.wfile.getvalue()
    headers, body = raw.split(b"\r\n\r\n", 1)
    status = int(headers.splitlines()[0].split()[1])
    return status, headers, body


def test_real_handler_routes_and_headers_without_a_listener(tmp_path):
    runtime = server.PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS)
    status, headers, body = memory_request(runtime, "/api/state")
    assert status == 200 and len(json.loads(body)["cards"]) == 8
    assert b"Cache-Control: no-store" in headers and b"X-Content-Type-Options: nosniff" in headers
    assert memory_request(runtime, "/")[0] == 200
    assert b'src="/app.js"' in memory_request(runtime, "/")[2]
    assert b'type="module"' in memory_request(runtime, "/")[2]
    assert memory_request(runtime, "/api/state", host="localhost:8765")[0] == 200
    assert memory_request(runtime, "/", host="evil.example:8765")[0] == 403
    assert memory_request(runtime, "/%2e%2e/state.py")[0] == 404
    web = tmp_path / "web"
    web.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    (web / "escape").symlink_to(secret)
    assert memory_request(runtime, "/escape", web_root=web)[0] == 404


def test_html_response_has_content_security_policy_without_a_listener(tmp_path):
    runtime = server.PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS)
    try:
        status, headers, _ = memory_request(runtime, "/")
        assert status == 200
        policy_headers = [header for header in headers.split(b"\r\n")
                          if header.lower().startswith(b"content-security-policy:")]
        assert policy_headers == [
            b"Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; "
            b"img-src 'self' data:; connect-src 'self'"
        ]
        _, api_headers, _ = memory_request(runtime, "/api/state")
        assert b"Content-Security-Policy:" not in api_headers
        assert b"Cache-Control: no-store" in api_headers
        assert b"X-Content-Type-Options: nosniff" in api_headers
    finally:
        runtime.close()


@pytest.mark.parametrize("path, allowed_types", [
    ("/", {"text/html"}),
    ("/app.css", {"text/css"}),
    ("/app.js", {"text/javascript", "application/javascript"}),
    ("/scene.js", {"text/javascript", "application/javascript"}),
    ("/charts.js", {"text/javascript", "application/javascript"}),
    ("/data.js", {"text/javascript", "application/javascript"}),
    ("/spider.js", {"text/javascript", "application/javascript"}),
    ("/silk.js", {"text/javascript", "application/javascript"}),
    ("/narrative.js", {"text/javascript", "application/javascript"}),
    ("/geometry.js", {"text/javascript", "application/javascript"}),
])
def test_real_handler_serves_web_assets_with_correct_content_type(tmp_path, path, allowed_types):
    runtime = server.PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS)
    try:
        status, raw_headers, body = memory_request(runtime, path)
        headers = http.client.parse_headers(io.BytesIO(raw_headers.split(b"\r\n", 1)[1] + b"\r\n\r\n"))
        assert status == 200 and body
        assert headers.get_content_type() in allowed_types
        assert headers.get_content_charset() == "utf-8"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Cache-Control"] is None
    finally:
        runtime.close()


def test_real_sse_handler_throttles_and_sends_update_without_listener(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "POLL_SECONDS", 0.05)
    runtime = server.PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS+10)
    states, stamps = [], []
    class Capture(io.BytesIO):
        def write(self, data):
            result = super().write(data)
            if data.startswith(b"event: state\n"):
                states.append(json.loads(data.split(b"data: ", 1)[1]))
                stamps.append(time.monotonic())
                if len(states) == 1:
                    append(tmp_path, DAY, line("save", alpha="new", saved=True, passed=True))
                else:
                    runtime.stop.set()
            return result
    runtime.start()
    try:
        status, headers, body = memory_request(runtime, "/api/stream", writer=Capture())
        assert status == 200 and b"text/event-stream" in headers
        assert len(states) == 2 and states[1]["totals"]["candidates"] == 1
        assert 0.9 <= stamps[1]-stamps[0] < 2
    finally:
        runtime.close()


def test_sse_heartbeat_and_disconnect_without_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rules, "SSE_HEARTBEAT_SECONDS", 0.01)
    runtime = server.PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS)
    class Capture(io.BytesIO):
        def write(self, data):
            result = super().write(data)
            if data.startswith(b": heartbeat"):
                runtime.stop.set()
            return result
    assert b": heartbeat" in memory_request(runtime, "/api/stream", writer=Capture())[2]
    runtime = server.PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS)
    class Disconnected(io.BytesIO):
        def write(self, data):
            if data.startswith(b"event: state"):
                raise BrokenPipeError
            return super().write(data)
    memory_request(runtime, "/api/stream", writer=Disconnected())
    assert "Traceback" not in capsys.readouterr().err
