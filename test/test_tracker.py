import ast
import asyncio
from datetime import datetime
import inspect
import json
import os
from pathlib import Path
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import get_type_hints

import pytest
pytest.importorskip("mcp.server.fastmcp")
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent

from SpiderPanel import extract, logtail, rules, tracker


@pytest.fixture(autouse=True)
def log_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("WQ_SPIDER_DIR", str(tmp_path))
    monkeypatch.delenv("WQ_SPIDER_DISABLE", raising=False)
    monkeypatch.setattr(tracker, "_warned", False)
    monkeypatch.setattr(tracker, "_agent_cache_pid", None, raising=False)
    monkeypatch.setattr(tracker, "_agent_cache", None, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, '', ''))
    return tmp_path


def rows(log_dir):
    return [json.loads(line) for path in sorted((log_dir / "log").glob("*.jsonl"))
            for line in path.read_text().splitlines()]


def end_rows(log_dir):
    return [row for row in rows(log_dir) if row["ph"] == "end"]


def named(fn, name="check_alpha_prod_correlation"):
    fn.__name__ = name
    return fn


@pytest.mark.parametrize("name,parameter,value,expected,role", [
    ("wqb_create_multi_simulation", "alpha_expressions", ["rank(close)", "volume"], {"n": 2}, "simulate"),
    ("check_expression_group_diversity", "expressions", ["rank(close)"], {"n": 1}, "precheck"),
    ("local_wait_multi_simulation", "multisimulation_url", "https://example.invalid/simulations/wait_sim/?secret=1", {"sim": "wait_sim"}, "result"),
    ("evaluate_simulation_alphas", "simulation_url", "https://example.invalid/simulations/eval_sim/?secret=1", {"sim": "eval_sim"}, "evaluate"),
    ("check_alpha_prod_correlation", "alpha_id", "alpha_prod", {"alpha": "alpha_prod"}, "prod"),
    ("save_candidate_alpha", "alpha_id", "alpha_save", {"alpha": "alpha_save"}, "save"),
])
@pytest.mark.parametrize("as_async", [False, True])
@pytest.mark.parametrize("as_keyword", [False, True])
def test_start_is_appended_before_execution_and_only_has_allowed_arguments(
    log_dir, name, parameter, value, expected, role, as_async, as_keyword,
):
    result = {"private": {"raw": "must stay private"}, "prod": 0.2}
    observed = []

    def body(*args, **kwargs):
        observed.append(rows(log_dir))
        return result

    if as_async:
        async def fn(*args, **kwargs):
            return body(*args, **kwargs)
    else:
        fn = body
    fn.__signature__ = inspect.Signature([
        inspect.Parameter(parameter, inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, default=None),
        inspect.Parameter("extra", inspect.Parameter.KEYWORD_ONLY, default=None),
    ])
    wrapped = tracker.track(named(fn, name))
    for _ in range(2):
        arguments = () if as_keyword else (value,)
        keywords = {parameter: value} if as_keyword else {}
        returned = wrapped(*arguments, **keywords, ctx="private context", extra={"raw": "private"})
        assert (asyncio.run(returned) if as_async else returned) is result

    records = rows(log_dir)
    assert [row["ph"] for row in records] == ["start", "end", "start", "end"]
    assert [len(snapshot) for snapshot in observed] == [1, 3]
    assert all(snapshot[-1]["ph"] == "start" for snapshot in observed)
    for start in records[::2]:
        assert set(start) == {"v", "ts", "t", "role", "pid", "ppid", "agent", "ph", *expected}
        assert {key: start[key] for key in expected} == expected
        assert start["role"] == role and start["t"] == name
        assert start["v"] == 1 and isinstance(start["ts"], int)
        assert (start["pid"], start["ppid"], start["agent"]) == (os.getpid(), os.getppid(), None)


@pytest.mark.parametrize("as_async", [False, True])
@pytest.mark.parametrize("failure", ["extract", "append"])
def test_start_failure_does_not_prevent_original_or_end_record(monkeypatch, log_dir, capsys, as_async, failure):
    result = {"prod": 0.2}
    if failure == "extract":
        def fail(*args):
            raise RuntimeError("start extraction failed")
        monkeypatch.setattr(extract, "start_summary", fail)
    else:
        real_write = tracker.os.write
        def write(fd, data):
            if json.loads(data)["ph"] == "start":
                raise PermissionError("start append denied")
            return real_write(fd, data)
        monkeypatch.setattr(tracker.os, "write", write)
    if as_async:
        async def fn(alpha_id):
            return result
    else:
        def fn(alpha_id):
            return result
    wrapped = tracker.track(named(fn))
    for _ in range(2):
        returned = wrapped("alpha")
        assert (asyncio.run(returned) if as_async else returned) is result
    records = rows(log_dir)
    assert len(records) == 2
    assert all(row["ph"] == "end" and row["prod"] == 0.2 for row in records)
    assert capsys.readouterr().err.count("[SpiderPanel]") == 1


@pytest.mark.parametrize("as_async", [False, True])
def test_start_failure_preserves_original_exception_and_error_end(monkeypatch, log_dir, capsys, as_async):
    error = ValueError("original tool error")
    real_write = tracker.os.write
    def write(fd, data):
        if json.loads(data)["ph"] == "start":
            raise PermissionError("start append denied")
        return real_write(fd, data)
    monkeypatch.setattr(tracker.os, "write", write)
    if as_async:
        async def fn(alpha_id):
            raise error
        call = lambda: asyncio.run(tracker.track(named(fn))("alpha"))
    else:
        def fn(alpha_id):
            raise error
        call = lambda: tracker.track(named(fn))("alpha")
    with pytest.raises(ValueError) as caught:
        call()
    assert caught.value is error
    end, = rows(log_dir)
    assert end["ph"] == "end" and end["ok"] is False
    assert end["err"] == "ValueError: original tool error"
    assert capsys.readouterr().err.count("[SpiderPanel]") == 1


def test_fastmcp_schema_call_results_and_context_transparency(log_dir):
    injected = []

    async def local_wait_multi_simulation(multisimulation_url: str, ctx: "Context" = None) -> "CallToolResult":
        """Wait for a simulation with injected context."""
        injected.append(ctx)
        return CallToolResult(content=[TextContent(type="text", text=json.dumps({
            "status": "pending", "multisimulation_id": multisimulation_url,
        }))])

    def check_expression_group_diversity(expressions: list[str], *, region: str, delay: int = 1) -> dict:
        """Check expressions with keyword-only settings."""
        return {"status": "pass", "region": region, "delay": delay, "expressions": expressions}

    async def check_alpha_prod_correlation(alpha_id: str) -> dict:
        """Return typed prod output."""
        return {"prod": 0.25}

    async def compare():
        plain, wrapped = FastMCP("plain"), FastMCP("wrapped")
        for fn in (local_wait_multi_simulation, check_expression_group_diversity, check_alpha_prod_correlation):
            tracked = tracker.track(fn)
            assert inspect.signature(tracked) == inspect.signature(fn)
            assert get_type_hints(tracked) == get_type_hints(fn)
            assert inspect.iscoroutinefunction(tracked) == inspect.iscoroutinefunction(fn)
            plain.tool()(fn)
            wrapped.tool()(tracked)
        a, b = await plain.list_tools(), await wrapped.list_tools()
        for before, after in zip(a, b, strict=True):
            assert (before.name, before.description, before.inputSchema, before.outputSchema) == (
                after.name, after.description, after.inputSchema, after.outputSchema,
            )
            assert "ctx" not in after.inputSchema.get("properties", {})
        calls = [
            ("local_wait_multi_simulation", {"multisimulation_url": "sim_ctx"}),
            ("check_expression_group_diversity", {"expressions": ["rank(close)"], "region": "USA"}),
            ("check_alpha_prod_correlation", {"alpha_id": "alpha_ctx"}),
        ]
        for name, args in calls:
            assert await wrapped.call_tool(name, args) == await plain.call_tool(name, args)

    asyncio.run(compare())
    assert len(injected) == 2
    assert all(isinstance(ctx, Context) for ctx in injected)
    assert len(end_rows(log_dir)) == 3


@pytest.mark.parametrize("as_mcp", [False, True])
@pytest.mark.parametrize("as_async", [False, True])
def test_direct_return_identity_and_calltoolresult_normalization(log_dir, as_mcp, as_async):
    result = {"prod": 0.123456}
    if as_mcp:
        result = CallToolResult(content=[TextContent(type="text", text=json.dumps(result)),
                                         TextContent(type="text", text='{"prod": 99}')])
    if as_async:
        async def fn(alpha_id: str):
            return result
        returned = asyncio.run(tracker.track(named(fn))("alpha_identity"))
    else:
        def fn(alpha_id: str):
            return result
        returned = tracker.track(named(fn))("alpha_identity")
    assert returned is result
    assert end_rows(log_dir)[0]["prod"] == 0.1235
    assert end_rows(log_dir)[0]["alpha"] == "alpha_identity"


def test_bound_arguments_remove_named_and_other_context(monkeypatch, log_dir):
    captured = []
    start_captured = []
    original_start = extract.start_summary
    def start_summary(name, args):
        start_captured.append(args)
        return original_start(name, args)
    monkeypatch.setattr(extract, "start_summary", start_summary)
    def extractor(args, result):
        captured.append(args)
        return {}
    monkeypatch.setitem(extract.TRACKED, "prod", extractor)
    def fn(alpha_id: str, ctx=None, extra=None, *, flag=True):
        return {}
    wrapped = tracker.track(named(fn))
    wrapped("alpha_pos", Context(), Context(), flag=False)
    wrapped(alpha_id="alpha_kw", ctx="not even a Context", extra=Context())
    assert captured == [{"alpha_id": "alpha_pos", "flag": False}, {"alpha_id": "alpha_kw"}]
    assert start_captured == captured


@pytest.mark.parametrize("as_async", [False, True])
def test_exception_instance_and_message_unchanged(log_dir, as_async):
    error = ValueError("故障" * 200)
    if as_async:
        async def fn(alpha_id):
            raise error
        call = lambda: asyncio.run(tracker.track(named(fn))("alpha_err"))
    else:
        def fn(alpha_id):
            raise error
        call = lambda: tracker.track(named(fn))("alpha_err")
    with pytest.raises(ValueError) as caught:
        call()
    assert caught.value is error
    row, = end_rows(log_dir)
    assert row["ok"] is False
    assert row["err"].startswith("ValueError: 故障")
    assert row["alpha"] == "alpha_err"
    assert len(row["err"]) == 200


@pytest.mark.parametrize("error", [asyncio.CancelledError(), KeyboardInterrupt(), SystemExit(7)])
@pytest.mark.parametrize("as_async", [False, True])
def test_baseexception_leaves_start_without_end(log_dir, error, as_async):
    if as_async:
        async def fn(alpha_id):
            raise error
        call = lambda: asyncio.run(tracker.track(named(fn))("alpha_cancel"))
    else:
        def fn(alpha_id):
            raise error
        call = lambda: tracker.track(named(fn))("alpha_cancel")
    with pytest.raises(type(error)) as caught:
        call()
    assert caught.value is error
    start, = rows(log_dir)
    assert start["ph"] == "start" and start["alpha"] == "alpha_cancel"
    assert "ok" not in start and "dur" not in start


def test_all_logging_failures_warn_once_and_never_change_return(monkeypatch, log_dir, capsys):
    result = {"prod": 0.2}
    def fn(alpha_id):
        return result
    fn = named(fn)
    blocked = log_dir / "blocked"
    blocked.write_text("this is a file, not a directory")
    with monkeypatch.context() as patch:
        patch.setenv("WQ_SPIDER_DIR", str(blocked))
        for _ in range(2):
            assert tracker.track(fn)("alpha") is result
    def fail(args, result):
        raise RuntimeError("extractor failed")
    monkeypatch.setitem(extract.TRACKED, "prod", fail)
    assert tracker.track(fn)("alpha") is result
    monkeypatch.setitem(extract.TRACKED, "prod", lambda args, result: {"prod": object()})
    assert tracker.track(fn)("alpha") is result
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.count("[SpiderPanel]") == 1


def test_logging_failure_cannot_mask_original_exception(monkeypatch, log_dir, capsys):
    error = ValueError("original tool error")
    def fail(*args, **kwargs):
        raise PermissionError("log error")
    monkeypatch.setattr(tracker.os, "open", fail)
    def fn(alpha_id):
        raise error
    with pytest.raises(ValueError) as caught:
        tracker.track(named(fn))("alpha")
    assert caught.value is error
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("[SpiderPanel]") == 1


@pytest.mark.parametrize("failure", ["permission", "extract", "serialization", "invalid_json", "stderr", "timer"])
def test_individual_logging_failure_is_contained(monkeypatch, log_dir, capsys, failure):
    result = {"prod": 0.2}
    def fail(*args, **kwargs):
        raise PermissionError("denied")
    if failure in ("permission", "stderr"):
        monkeypatch.setattr(tracker.os, "open", fail)
        if failure == "stderr":
            monkeypatch.setattr(tracker.sys, "stderr", type("Closed", (), {"write": fail})())
    elif failure == "extract":
        monkeypatch.setitem(extract.TRACKED, "prod", fail)
    elif failure == "serialization":
        monkeypatch.setitem(extract.TRACKED, "prod", lambda args, res: {"prod": object()})
    elif failure == "invalid_json":
        result = CallToolResult(content=[TextContent(type="text", text="not JSON")])
    elif failure == "timer":
        monkeypatch.setattr(tracker.time, "monotonic", fail)
    def fn(alpha_id):
        return result
    wrapped = tracker.track(named(fn))
    assert wrapped("alpha") is result
    assert wrapped("alpha") is result
    captured = capsys.readouterr()
    assert captured.out == ""
    if failure != "stderr":
        assert captured.err.count("[SpiderPanel]") == 1


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE"])
def test_disabled_does_not_log_or_extract(monkeypatch, log_dir, value):
    monkeypatch.setenv("WQ_SPIDER_DISABLE", value)
    def fail(*args):
        pytest.fail("disabled tracking must not extract")
    monkeypatch.setitem(extract.TRACKED, "prod", fail)
    monkeypatch.setattr(extract, "start_summary", fail)
    monkeypatch.setattr(subprocess, "run", fail)
    result = {}
    def fn(alpha_id):
        return result
    assert tracker.track(named(fn))("alpha") is result
    assert not list(log_dir.iterdir())


@pytest.mark.parametrize("as_async", [False, True])
def test_pytest_logs_only_with_explicit_directory(monkeypatch, tmp_path, as_async):
    monkeypatch.delenv("WQ_SPIDER_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = {"prod": 0.2}
    if as_async:
        async def fn(alpha_id):
            return result
    else:
        def fn(alpha_id):
            return result
    wrapped = tracker.track(named(fn))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr(subprocess, "run", run)

    def call():
        returned = wrapped("alpha_test")
        return asyncio.run(returned) if as_async else returned

    assert call() is result
    assert calls == []
    assert not (tmp_path / ".wq_spider").exists()
    explicit_dir = tmp_path / "explicit"
    monkeypatch.setenv("WQ_SPIDER_DIR", str(explicit_dir))
    assert call() is result
    assert end_rows(explicit_dir)[0]["alpha"] == "alpha_test"
    assert len(calls) == 1
    monkeypatch.delenv("WQ_SPIDER_DIR")
    assert call() is result
    assert len(end_rows(explicit_dir)) == 1
    assert len(calls) == 1
    assert not (tmp_path / ".wq_spider").exists()


def test_pytest_empty_directory_value_is_still_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("WQ_SPIDER_DIR", "")
    monkeypatch.chdir(tmp_path)
    result = {"prod": 0.2}
    def fn(alpha_id):
        return result
    assert tracker.track(named(fn))("alpha_empty") is result
    assert end_rows(tmp_path)[0]["alpha"] == "alpha_empty"


def test_non_pytest_keeps_default_home_logging(monkeypatch, tmp_path):
    monkeypatch.delenv("WQ_SPIDER_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = {"prod": 0.2}
    def fn(alpha_id):
        return result
    wrapped = tracker.track(named(fn))
    with monkeypatch.context() as patch:
        patch.delitem(tracker.sys.modules, "pytest")
        returned = wrapped("alpha_production")
    assert returned is result
    assert end_rows(tmp_path / ".wq_spider")[0]["alpha"] == "alpha_production"


def test_untracked_function_is_same_object():
    def untracked():
        return {}
    assert tracker.track(untracked) is untracked


def test_line_limits_tight_expression_then_tail_truncation(log_dir):
    def fn(alpha_expressions):
        return {"status": "submitted", "success": True}
    wrapped = tracker.track(named(fn, "wqb_create_multi_simulation"))
    count = rules.MAX_LINE_BYTES // (rules.EXPR_CHARS_TIGHT * 3) + 1
    wrapped(["中" * rules.EXPR_CHARS] * 12)
    wrapped(["中" * rules.EXPR_CHARS] * count)
    first, second = end_rows(log_dir)
    assert len(first["exprs"]) == 12
    assert all(len(item[1]) == rules.EXPR_CHARS_TIGHT for item in first["exprs"])
    assert "trunc" not in first
    assert len(second["exprs"]) + second["trunc"] == count
    assert second["trunc"] > 0
    for path in (log_dir / "log").glob("*.jsonl"):
        assert all(len(line) <= rules.MAX_LINE_BYTES for line in path.read_bytes().splitlines(keepends=True))


def test_eight_full_expressions_are_recorded_intact(log_dir):
    expressions = [f"rank(close + {i}) + " + "x" * 380 for i in range(8)]
    result = {"status": "submitted", "success": True}
    def fn(alpha_expressions):
        return result
    assert tracker.track(named(fn, "wqb_create_multi_simulation"))(expressions) is result
    row, = end_rows(log_dir)
    assert row["exprs"] == [[extract.expression_hash(expr), expr] for expr in expressions]
    assert "trunc" not in row
    for path in (log_dir / "log").glob("*.jsonl"):
        recorded = list(logtail.Tail(path).read_lines())
        assert all(raw is not None and len(raw) <= rules.MAX_LINE_BYTES for raw in recorded)
        assert [json.loads(raw) for raw in recorded if json.loads(raw)["ph"] == "end"] == [row]


def test_evaluate_drops_checks_before_truncating_alphas(log_dir):
    check = "x" * (rules.MAX_LINE_BYTES // (8 * rules.MAX_FAILED_CHECKS) + 1)
    def fn(simulation_url):
        return {"all_alphas": [{"alpha_id": f"alpha_{i}", "expression": "rank(close)",
                               "failed_checks": [check] * rules.MAX_FAILED_CHECKS} for i in range(8)]}
    tracker.track(named(fn, "evaluate_simulation_alphas"))("sim")
    row, = end_rows(log_dir)
    assert len(row["alphas"]) == 8
    assert all(alpha[5] == [] for alpha in row["alphas"])
    assert "trunc" not in row


def test_alphas_truncation_and_public_field_fallback(log_dir):
    count = rules.MAX_LINE_BYTES // 32 + 1
    def fn(simulation_url):
        return {"all_alphas": [{"alpha_id": f"alpha_{i}", "expression": "rank(close)"} for i in range(count)]}
    tracker.track(named(fn, "evaluate_simulation_alphas"))("sim")
    row, = end_rows(log_dir)
    assert len(row["alphas"]) + row["trunc"] == count
    assert row["trunc"] > 0
    def prod(alpha_id):
        return {"prod": 0.2}
    tracker.track(named(prod))("x" * rules.MAX_LINE_BYTES)
    row = end_rows(log_dir)[-1]
    assert row["trunc"] == -1
    assert set(row) == {"v", "ts", "t", "role", "ph", "ok", "dur", "pid", "ppid", "agent", "trunc"}
    assert row["pid"] == os.getpid()
    assert row["ppid"] == os.getppid()
    assert row["agent"] is None


@pytest.mark.parametrize("command,expected", [('claude --settings=/tmp/Case.settings.json', 'Case'), ('', None)])
def test_parent_agent_is_cached_after_first_log_even_when_unknown(monkeypatch, log_dir, command, expected):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, command, '')
    monkeypatch.setattr(subprocess, 'run', run)
    def fn(alpha_id):
        return {'prod': 0.2}
    wrapped = tracker.track(named(fn))
    wrapped('first')
    wrapped('second')
    assert len(calls) == 1
    assert calls[0] == ['ps', '-o', 'command=', '-p', str(os.getppid())]
    assert [row['agent'] for row in end_rows(log_dir)] == [expected, expected]


def test_parent_agent_timeout_is_cached_and_does_not_change_return(monkeypatch, log_dir, capsys):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired(args, 1)
    monkeypatch.setattr(subprocess, 'run', run)
    result = {'prod': 0.2}
    def fn(alpha_id):
        return result
    wrapped = tracker.track(named(fn))
    assert wrapped('first') is result
    assert wrapped('second') is result
    assert len(calls) == 1
    assert [row['agent'] for row in end_rows(log_dir)] == [None, None]
    assert capsys.readouterr().err == ''


def test_parent_agent_cache_refreshes_after_process_change(monkeypatch, log_dir):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, 'claude' if len(calls) == 1 else 'node @openai/codex/codex/app-server-daemon', '')
    monkeypatch.setattr(subprocess, 'run', run)
    def fn(alpha_id):
        return {'prod': 0.2}
    wrapped = tracker.track(named(fn))
    monkeypatch.setattr(tracker.os, 'getpid', lambda: 100)
    monkeypatch.setattr(tracker.os, 'getppid', lambda: 50)
    wrapped('parent')
    monkeypatch.setattr(tracker.os, 'getpid', lambda: 200)
    monkeypatch.setattr(tracker.os, 'getppid', lambda: 100)
    wrapped('child')
    assert calls == [['ps', '-o', 'command=', '-p', '50'], ['ps', '-o', 'command=', '-p', '100']]
    assert [(row['pid'], row['ppid'], row['agent']) for row in end_rows(log_dir)] == [(100, 50, 'claude'), (200, 100, 'codex')]


def test_parent_agent_lookup_is_shared_by_concurrent_calls(monkeypatch, log_dir):
    entered = threading.Event()
    release = threading.Event()
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(2)
        return subprocess.CompletedProcess(args, 0, 'claude', '')
    monkeypatch.setattr(subprocess, 'run', run)
    def fn(alpha_id):
        return {'prod': 0.2}
    wrapped = tracker.track(named(fn))
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(wrapped, str(i)) for i in range(8)]
        assert entered.wait(2)
        release.set()
        for future in futures:
            future.result()
    assert len(calls) == 1
    assert len(end_rows(log_dir)) == 8
    assert all(row['agent'] == 'claude' for row in end_rows(log_dir))


def test_parent_metadata_failure_remains_inside_logging_boundary(monkeypatch, log_dir, capsys):
    def fail():
        raise RuntimeError('metadata unavailable')
    monkeypatch.setattr(tracker.os, 'getppid', fail)
    result = {'prod': 0.2}
    def fn(alpha_id):
        return result
    wrapped = tracker.track(named(fn))
    assert wrapped('alpha') is result
    assert wrapped('alpha') is result
    assert not rows(log_dir)
    assert capsys.readouterr().err.count('[SpiderPanel]') == 1


def test_shrink_keeps_parent_metadata(monkeypatch, log_dir):
    monkeypatch.setattr(subprocess, 'run', lambda args, **kwargs: subprocess.CompletedProcess(args, 0, 'claude --settings=/tmp/CCS.settings.json', ''))
    def fn(alpha_id):
        return {'prod': 0.2}
    tracker.track(named(fn))('x' * rules.MAX_LINE_BYTES)
    start, end = rows(log_dir)
    assert [start['ph'], end['ph']] == ['start', 'end']
    for row in (start, end):
        assert row['trunc'] == -1
        assert (row['pid'], row['ppid'], row['agent']) == (os.getpid(), os.getppid(), 'CCS')


def test_per_call_directory_local_date_and_multiple_json_lines(monkeypatch, log_dir):
    def fn(alpha_id):
        return {"prod": 0.2}
    wrapped = tracker.track(named(fn))
    epochs = [int(datetime(2026, 2, 3, 23, 59, 59).timestamp()),
              int(datetime(2026, 2, 4, 0, 0, 1).timestamp())]
    for epoch in epochs:
        monkeypatch.setattr(tracker.time, "time", lambda: epoch)
        wrapped("alpha")
        wrapped("alpha")
    assert len(end_rows(log_dir)) == 4
    assert sorted(p.name for p in (log_dir / "log").iterdir()) == ["2026-02-03.jsonl", "2026-02-04.jsonl"]
    for row in end_rows(log_dir):
        assert row["v"] == 1 and row["ok"] is True and row["role"] == "prod"
        assert isinstance(row["ts"], int) and isinstance(row["dur"], float)
    other = log_dir / "other"
    monkeypatch.setenv("WQ_SPIDER_DIR", str(other))
    wrapped("alpha")
    assert len(end_rows(other)) == 1


def test_concurrent_appends_are_complete_lines(log_dir):
    def fn(alpha_id):
        return {"prod": 0.2}
    wrapped = tracker.track(named(fn))
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(wrapped, [f"alpha_{i}" for i in range(40)]))
    assert len(end_rows(log_dir)) == 40
    assert len({row["alpha"] for row in end_rows(log_dir)}) == 40


def test_each_append_is_one_write_and_fd_is_closed(monkeypatch, log_dir):
    writes = []
    real_write = os.write
    def write(fd, data):
        writes.append((fd, data))
        return real_write(fd, data)
    monkeypatch.setattr(tracker.os, "write", write)
    def fn(alpha_id):
        return {"prod": 0.2}
    tracker.track(named(fn))("alpha")
    assert len(writes) == 2
    assert [json.loads(data)["ph"] for _, data in writes] == ["start", "end"]
    for fd, data in writes:
        assert data.endswith(b"\n")
        with pytest.raises(OSError):
            os.fstat(fd)


def test_server_decorator_scope_from_ast():
    selected = os.environ.get("SPIDERPANEL_SERVER_FILE")
    if not selected:
        pytest.skip("未设置外部工具服务器路径")
    path = Path(selected)
    tree = ast.parse(path.read_text())
    tracked = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = node.decorator_list
            if any(isinstance(d, ast.Name) and d.id == "track" for d in decorators):
                tracked.add(node.name)
                assert isinstance(decorators[0], ast.Call)
                assert ast.unparse(decorators[0].func) == "mcp.tool"
                assert ast.unparse(decorators[1]) == "track"
    assert tracked == set(extract.NAME_ROLES)


@pytest.mark.parametrize('role,parameter,argument,result,expected', [
    ('simulate', 'alpha_expressions', ['sample_expression'],
     {'success': True, 'status': 'submitted', 'multisimulation_id': 'sample_sim'}, {'sim': 'sample_sim'}),
    ('result', 'multisimulation_url', 'https://example.invalid/simulations/sample_sim',
     {'status': 'completed', 'alpha_results': []}, {'sim': 'sample_sim'}),
    ('evaluate', 'simulation_url', 'https://example.invalid/simulations/sample_sim',
     {'all_alphas': [], 'has_best': True}, {'sim': 'sample_sim'}),
    ('prod', 'alpha_id', 'sample_alpha', {'prod': .25}, {'alpha': 'sample_alpha', 'prod': .25}),
    ('save', 'alpha_id', 'sample_alpha', {'all_checks_passed': True, 'saved_locally': True},
     {'alpha': 'sample_alpha', 'passed': True, 'saved': True}),
    ('precheck', 'expressions', ['sample_expression'], {'status': 'pass'}, {'status': 'pass', 'n': 1}),
])
@pytest.mark.parametrize('as_async', [False, True])
def test_custom_function_role_preserves_name_and_summary(log_dir, role, parameter, argument, result, expected, as_async):
    if as_async:
        async def custom_tool(**kwargs):
            return result
    else:
        def custom_tool(**kwargs):
            return result
    custom_tool.__signature__ = inspect.Signature([inspect.Parameter(parameter, inspect.Parameter.KEYWORD_ONLY)])
    wrapped = tracker.track(role=role)(custom_tool)
    returned = wrapped(**{parameter: argument})
    assert (asyncio.run(returned) if as_async else returned) is result
    records = rows(log_dir)
    assert [row['ph'] for row in records] == ['start', 'end']
    assert all(row['t'] == 'custom_tool' and row['role'] == role for row in records)
    assert {key: records[-1][key] for key in expected} == expected
    assert records[0] == {**records[0], **extract.start_summary(role, {parameter: argument})}


def test_unknown_role_fails_at_decoration_time():
    with pytest.raises(ValueError, match='role'):
        tracker.track(role='unknown')
