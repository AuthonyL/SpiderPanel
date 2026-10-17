"""Best-effort daily JSONL summaries, without changing the tool interface."""

from datetime import datetime
from functools import wraps
import inspect
import json
import os
from pathlib import Path
import sys
import threading
import time

from . import extract
from .processes import parent_agent
from .rules import (
    DISABLE_ENV, ERR_CHARS, EXPR_CHARS_TIGHT, LOG_VERSION,
    MAX_LINE_BYTES, SPIDER_DIR_ENV,
)


_COMMON = ("v", "ts", "t", "role", "ph", "ok", "dur", "pid", "ppid", "agent", "err")
_warned = False
_warning_lock = threading.Lock()
_agent_cache_pid = None
_agent_cache = None
_agent_lock = threading.Lock()


def _reset_agent_cache():
    # A fork can inherit a lock held by a thread that no longer exists.
    global _agent_cache_pid, _agent_cache, _agent_lock
    _agent_cache_pid = None
    _agent_cache = None
    _agent_lock = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_agent_cache)


def _cached_parent_agent(pid, ppid):
    global _agent_cache_pid, _agent_cache
    with _agent_lock:
        if _agent_cache_pid != pid:
            _agent_cache = parent_agent(ppid)
            _agent_cache_pid = pid
        return _agent_cache


def _warn_once():
    global _warned
    try:
        with _warning_lock:
            if _warned:
                return
            _warned = True
        print("[SpiderPanel] summary logging failed", file=sys.stderr)
    except Exception:
        pass


def _start():
    try:
        if os.environ.get(DISABLE_ENV, "").strip().lower() in ("1", "true", "yes"):
            return None
        if "pytest" in sys.modules and SPIDER_DIR_ENV not in os.environ:
            return None
        return time.monotonic()
    except Exception:
        _warn_once()
        return None


def _mcp_instance(value, module_name, class_name):
    # Reuse loaded MCP types without adding a third-party runtime dependency.
    cls = getattr(sys.modules.get(module_name), class_name, None)
    return isinstance(cls, type) and isinstance(value, cls)


def _normalize(result):
    if _mcp_instance(result, "mcp.types", "CallToolResult"):
        for content in result.content:
            if getattr(content, "type", None) == "text":
                return json.loads(content.text)
        return None
    return result


def _encode(summary):
    return json.dumps(summary, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _fit_line(summary):
    def fits(line):
        # Include the trailing newline in the byte budget.
        return len(line) + 1 <= MAX_LINE_BYTES

    line = _encode(summary)
    if fits(line):
        return line

    for row in summary.get("exprs", []):
        if isinstance(row[1], str):
            row[1] = row[1][:EXPR_CHARS_TIGHT]
    line = _encode(summary)
    if fits(line):
        return line

    if summary["role"] == "evaluate":
        for row in summary.get("alphas", []):
            row[5] = []
    line = _encode(summary)
    if fits(line):
        return line

    removed = 0
    for key in ("exprs", "alphas"):
        items = summary.get(key, [])
        while items:
            items.pop()
            removed += 1
            summary["trunc"] = removed
            line = _encode(summary)
            if fits(line):
                return line

    summary = {key: summary[key] for key in _COMMON if key in summary}
    summary["trunc"] = -1
    return _encode(summary)


def _arguments(fn, args, kwargs):
    bound = inspect.signature(fn).bind_partial(*args, **kwargs)
    return {
        key: value for key, value in bound.arguments.items()
        if key != "ctx" and not _mcp_instance(value, "mcp.server.fastmcp", "Context")
    }


def _summary(fn, role, phase):
    pid, ppid = os.getpid(), os.getppid()
    return {
        "v": LOG_VERSION, "ts": int(time.time()), "t": fn.__name__,
        "role": role, "ph": phase,
        "pid": pid, "ppid": ppid, "agent": _cached_parent_agent(pid, ppid),
    }


def _append(summary):
    line = _fit_line(summary)
    directory = Path(os.environ.get(SPIDER_DIR_ENV, "~/.wq_spider")).expanduser() / "log"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{datetime.fromtimestamp(summary['ts']).date().isoformat()}.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        data = line + b"\n"
        if os.write(fd, data) != len(data):
            raise OSError("incomplete SpiderPanel append")
    finally:
        os.close(fd)


def _record_start(fn, role, args, kwargs, started):
    if started is None:
        return
    try:
        summary = _summary(fn, role, "start")
        summary.update(extract.start_summary(role, _arguments(fn, args, kwargs)))
        _append(summary)
    except Exception:
        _warn_once()


def _record(fn, role, extractor, args, kwargs, started, result=None, error=None):
    if started is None:
        return
    try:
        elapsed = round(time.monotonic() - started, 1)
        summary = _summary(fn, role, "end")
        summary.update(ok=error is None, dur=elapsed)
        if error is None:
            summary.update(extractor(_arguments(fn, args, kwargs), _normalize(result)))
        else:
            summary["err"] = f"{type(error).__name__}: {error}"[:ERR_CHARS]
            # Keep the parameter identity on errors too, so a concurrent call
            # of the same tool cannot close the wrong sim/alpha in the panel.
            try:
                identifiers = extract.start_summary(role, _arguments(fn, args, kwargs))
                summary.update({key: value for key, value in identifiers.items() if key in ("sim", "alpha")})
            except Exception:
                _warn_once()
        _append(summary)
    except Exception:
        _warn_once()


def track(fn=None, *, role=None):
    """Wrap a built-in name or explicit role, preserving returns and errors."""
    if role is not None and (not isinstance(role, str) or role not in extract.TRACKED):
        raise ValueError(f"unknown tracking role: {role!r}")
    if fn is None:
        return lambda function: track(function, role=role)
    role = role if role is not None else extract.NAME_ROLES.get(fn.__name__)
    extractor = extract.TRACKED.get(role)
    if extractor is None:
        return fn

    if inspect.iscoroutinefunction(fn):
        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            started = _start()
            _record_start(fn, role, args, kwargs, started)
            try:
                result = await fn(*args, **kwargs)
            except Exception as error:
                _record(fn, role, extractor, args, kwargs, started, error=error)
                raise
            _record(fn, role, extractor, args, kwargs, started, result=result)
            return result
        return async_wrapper

    @wraps(fn)
    def sync_wrapper(*args, **kwargs):
        started = _start()
        _record_start(fn, role, args, kwargs, started)
        try:
            result = fn(*args, **kwargs)
        except Exception as error:
            _record(fn, role, extractor, args, kwargs, started, error=error)
            raise
        _record(fn, role, extractor, args, kwargs, started, result=result)
        return result
    return sync_wrapper
