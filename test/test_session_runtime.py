"""OS identity recovery and ten-second retirement through the real log reader."""

from SpiderPanel import processes, rules
from SpiderPanel.server import PanelRuntime
from test_server import append
from test_state import DAY, TS, line


def test_live_runtime_names_existing_validators_and_caches_parent_commands(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(processes, "process_alive", lambda pid: True)
    monkeypatch.setattr(processes, "parent_pid", lambda pid: calls.append(("parent", pid)) or 77)
    monkeypatch.setattr(processes, "parent_agent", lambda pid: calls.append(("agent", pid)) or "kimi3")
    for i, pid in enumerate([101, 102, 101]):
        append(tmp_path, DAY, line("precheck", pid=pid, ts=TS+i, status="pass"))
    runtime = PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS+10)
    try:
        runtime.poll()
        snap = runtime.snapshot()
        assert len(snap["sessions"]) == 1
        assert snap["sessions"][0]["pid"] == 77 and snap["sessions"][0]["label"] == "kimi3"
        assert snap["totals"]["sessions_total"] == 1
        assert calls == [("parent", 101), ("agent", 77), ("parent", 102)]
        append(tmp_path, DAY, line("precheck", pid=102, ts=TS+5, status="pass"))
        runtime.poll()
        assert len(calls) == 3
    finally:
        runtime.close()


def test_logged_agent_wins_and_parent_lifetime_is_checked_every_ten_seconds(tmp_path, monkeypatch):
    now, live, probes = [TS], [True], []
    monkeypatch.setattr(processes, "process_alive", lambda pid: probes.append(pid) or live[0])
    def no_ps(*args):
        raise AssertionError("Explicit agent metadata must not trigger ps")
    monkeypatch.setattr(processes, "parent_pid", no_ps)
    monkeypatch.setattr(processes, "parent_agent", no_ps)
    append(tmp_path, DAY, line("simulate", pid=101, ppid=77, agent="agent_demo", status="submitted", sim="pending", exprs=[["h", "rank(close)"]]))
    runtime = PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: now[0])
    try:
        runtime.poll()
        assert probes == [77]
        assert runtime.snapshot()["sessions"][0]["label"] == "agent_demo"
        before = runtime.snapshot()
        now[0] += 9
        live[0] = False
        runtime.poll()
        assert probes == [77] and len(runtime.snapshot()["sessions"]) == 1
        now[0] += 1
        runtime.poll()
        snap = runtime.snapshot()
        assert probes == [77, 77] and snap["sessions"] == []
        assert snap["sessions_ended"] == 1 and snap["pending_sims"] == []
        assert snap["totals"]["exprs"] == before["totals"]["exprs"] == 1
        assert snap["revision"] > before["revision"]
    finally:
        runtime.close()


def test_dead_legacy_pid_is_retired_and_does_not_trigger_ps(tmp_path, monkeypatch):
    monkeypatch.setattr(processes, "process_alive", lambda pid: False)
    def no_ps(*args):
        raise AssertionError("Do not inspect a dead validator")
    monkeypatch.setattr(processes, "parent_pid", no_ps)
    append(tmp_path, DAY, line("precheck", pid=123, status="fail"))
    runtime = PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS+10)
    try:
        runtime.poll()
        snap = runtime.snapshot()
        assert snap["sessions"] == [] and snap["sessions_ended"] == 1
        assert snap["totals"]["sessions_total"] == snap["rejects"]["precheck_fail"] == 1
    finally:
        runtime.close()


def test_identity_lookup_failure_is_cached_without_losing_events(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(processes, "process_alive", lambda pid: True)
    monkeypatch.setattr(processes, "parent_pid", lambda pid: 77)
    monkeypatch.setattr(processes, "parent_agent", lambda pid: calls.append(pid) or None)
    append(tmp_path, DAY, line("precheck", pid=101, status="fail"))
    append(tmp_path, DAY, line("precheck", pid=101, ts=TS+1, status="fail"))
    runtime = PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS+10)
    try:
        runtime.poll()
        snap = runtime.snapshot()
        assert calls == [77] and snap["sessions"][0]["label"] == "终端 1"
        assert snap["rejects"]["precheck_fail"] == 2 and len(snap["events"]) == 2
    finally:
        runtime.close()


def test_demo_and_replay_do_not_probe_virtual_or_historical_processes(tmp_path, monkeypatch):
    def no_process(*args):
        raise AssertionError("Demo and replay do not consult local processes")
    monkeypatch.setattr(processes, "process_alive", no_process)
    monkeypatch.setattr(processes, "parent_pid", no_process)
    monkeypatch.setattr(processes, "parent_agent", no_process)
    append(tmp_path, DAY, line("precheck", pid=4101, status="pass"))
    for options in ({"mode": "demo"}, {"day": DAY}):
        runtime = PanelRuntime(tmp_path, today=lambda: DAY, clock=lambda: TS+10, **options)
        try:
            runtime.poll()
            assert len(runtime.snapshot()["sessions"]) == 1
            assert runtime.snapshot()["sessions_ended"] == 0
        finally:
            runtime.close()
