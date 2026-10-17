from datetime import date, datetime
import json
from pathlib import Path

import pytest

from SpiderPanel import rules
from SpiderPanel.demo import DemoFeeder
from SpiderPanel.state import FactoryState
from SpiderPanel.wq_day import wq_day, wq_window


def test_demo_history_and_live_lines_are_valid_and_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    now = [datetime(2026, 10, 15, 15).timestamp()]
    log_dir = tmp_path / "isolated-demo" / "log"
    feeder = DemoFeeder(log_dir, clock=lambda: now[0])
    feeder.seed_history()
    feeder.tick()
    now[0] += 61
    feeder.tick()
    state = FactoryState(wq_day(feeder.clock()), clock=feeder.clock)
    rows = []
    for path in sorted(log_dir.glob("*.jsonl")):
        for raw in path.read_bytes().splitlines(keepends=True):
            assert len(raw) <= rules.MAX_LINE_BYTES
            row = json.loads(raw)
            assert {"v", "ts", "t", "role", "ph", "pid", "ppid", "agent"} <= set(row)
            if row["ph"] == "end":
                assert {"ok", "dur"} <= set(row)
            state.feed(row)
            rows.append(row)
        assert state.bad_lines == 0
    assert min(row["ts"] for row in rows) < now[0]-2*3600
    snap = state.snapshot("demo")
    assert len(snap["sessions"]) == 4
    assert any(s["idle"] for s in snap["sessions"])
    assert {s["region"] for s in snap["sessions"]} >= {"USA", "ASI", "EUR"}
    assert all(a["id"].startswith("DEMO") for a in snap["alphas"])
    assert 0.04 <= snap["totals"]["eval_passed"] / snap["totals"]["alphas"] <= 0.12
    assert not (tmp_path / ".wq_spider").exists()
    state.close()


def test_demo_thread_stops_cleanly(tmp_path):
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: datetime(2026, 10, 15, 15).timestamp())
    feeder.start()
    feeder.stop()
    assert not feeder.thread.is_alive()


def test_first_thirty_live_seconds_cover_each_factory_outcome_without_event_flood(tmp_path):
    start = datetime(2026, 10, 15, 15).timestamp()
    now = [start]
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: now[0])
    feeder.seed_history()
    state = FactoryState(wq_day(feeder.clock()), clock=feeder.clock)
    path = tmp_path / "log" / "2026-10-15.jsonl"
    historical_rows = path.read_text().splitlines()
    for raw in historical_rows:
        state.feed(json.loads(raw))
    baseline_seq = state.snapshot("demo")["events"][-1]["seq"]
    seen_rows = len(historical_rows)
    events_by_second = {}
    live_rows = []
    try:
        for second in range(31):
            now[0] = start+second
            feeder.tick()
            rows = path.read_text().splitlines()
            for raw in rows[seen_rows:]:
                row = json.loads(raw)
                assert row["ts"] <= now[0]
                state.feed(row)
                live_rows.append(row)
            seen_rows = len(rows)
            events_by_second[second] = [event for event in state.snapshot("demo")["events"]
                                       if event["seq"] > baseline_seq]
        live_events = events_by_second[30]
        assert {event["kind"] for event in live_events} >= {
            "sim_submit", "sim_done", "eval_pass", "eval_fail", "prod_block", "candidate",
            "precheck_fail", "sim_fail", "prod_ok", "rejected"}
        outcome_events = [event for event in live_events if not event["kind"].endswith("_start")]
        assert 10 <= len(outcome_events) <= 16
        assert {event["kind"] for event in live_events} >= {"sim_submit_start", "eval_start", "prod_start", "save_start"}
        assert sum(event["kind"] == "eval_fail" for event in live_events) <= 2
        assert len({event["ts"] for event in live_events}) >= 10
        assert all(event["kind"].endswith("_start") for event in events_by_second[0])
        assert any(event["kind"] == "precheck_fail" for event in events_by_second[3])
        assert not any(event["kind"] == "precheck_fail" for event in events_by_second[2])
        assert any(event["seq"] not in {old["seq"] for old in events_by_second[24]}
                   for event in live_events)
        assert state.bad_lines == 0
        main_submit = next(row for row in live_rows if row["role"] == "simulate" and row["ph"] == "end"
                           and row["sim"] == "DEMO_SIM_ONBOARD_MAIN")
        main_result = next(row for row in live_rows if row["role"] == "result" and row["ph"] == "end"
                           and row["sim"] == "DEMO_SIM_ONBOARD_MAIN")
        assert len(main_submit["exprs"]) == len(main_result["alphas"]) == 8
        assert sum(len(row["alphas"]) for row in live_rows if row["role"] == "evaluate" and row["ph"] == "end") == 4
        assert next(event for event in live_events if event["kind"] == "sim_done")["n"] == 8
        snap = state.snapshot("demo")
        assert len(snap["sessions"]) == 3
        assert 0.04 <= snap["totals"]["eval_passed"] / snap["totals"]["alphas"] <= 0.12
        for row in live_rows:
            assert {"v", "ts", "t", "role", "ph", "pid", "ppid", "agent"} <= row.keys()
            if row["ph"] == "end":
                assert {"ok", "dur"} <= row.keys()
            assert len(json.dumps(row, ensure_ascii=False).encode()) <= rules.MAX_LINE_BYTES
    finally:
        state.close()


@pytest.mark.parametrize("open_delay", [4, 20, 40])
def test_delayed_page_open_still_observes_every_outcome_in_thirty_seconds(tmp_path, open_delay):
    start = datetime(2026, 10, 15, 15).timestamp()
    now = [start]
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: now[0])
    feeder.seed_history()
    state = FactoryState(wq_day(feeder.clock()), clock=feeder.clock)
    path = tmp_path / "log" / "2026-10-15.jsonl"
    position, last_seq, observed = 0, 0, []
    try:
        for second in range(open_delay+31):
            now[0] = start+second
            feeder.tick()
            with path.open() as stream:
                stream.seek(position)
                for raw in stream:
                    state.feed(json.loads(raw))
                position = stream.tell()
            events = state.snapshot("demo")["events"]
            if second > open_delay:
                observed.extend(event for event in events if event["seq"] > last_seq)
            last_seq = events[-1]["seq"]
        assert {event["kind"] for event in observed} >= {
            "sim_submit", "sim_done", "eval_pass", "eval_fail", "prod_block", "candidate",
            "precheck_fail", "sim_fail", "prod_ok", "rejected"}
        next_cycle = "_C1" if open_delay < 28 else "_C2"
        assert any(event.get("sim") == f"DEMO_SIM_ONBOARD_MAIN{next_cycle}"
                   for event in observed if event["kind"] == "sim_submit")
        later_alphas = [aid for event in observed for aid in event.get("alphas", []) if "_C" in aid]
        assert later_alphas and all(aid.startswith("DEMO_ONBOARD_") for aid in later_alphas)
    finally:
        state.close()


def test_demo_clock_jump_schedules_only_current_onboarding_cycle(tmp_path):
    start = datetime(2026, 10, 15, 15).timestamp()
    now = [start]
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: now[0])
    feeder.tick()
    path = tmp_path / "log" / "2026-10-15.jsonl"
    initial_rows = len(path.read_text().splitlines())
    for jump in (3600, 7200, 10800):
        now[0] = start+jump
        feeder.tick()
        rows = [json.loads(raw) for raw in path.read_text().splitlines()[initial_rows:]]
        scripted = [row for row in rows if "ONBOARD" in (row.get("sim") or row.get("alpha") or "")]
        cycle = jump // 28
        assert scripted
        assert all(row["ts"] >= start+cycle*28 for row in scripted)
        cleanup = [row for row in scripted if row.get("err", "").startswith("DEMO 时钟跳跃，结束过期演示")]
        closing = {DemoFeeder._key(row) for row in cleanup}
        # A submitted batch whose wait had not begun gets a parameter-only
        # start immediately before its clock-jump closure.
        cleanup.extend(row for row in scripted if row["ph"] == "start" and DemoFeeder._key(row) in closing)
        current = [row for row in scripted if row not in cleanup]
        assert current and all((row.get("sim") or row["alpha"]).endswith(f"_C{cycle}") for row in current)
        assert all(row["ok"] is False for row in cleanup if row["ph"] == "end")
        wait_cleanup = [row for row in cleanup if row["role"] == "result" and row["ph"] == "end"]
        assert len(wait_cleanup) <= 2 and all(row["status"] == "failed" for row in wait_cleanup)
        assert len(scripted) < 40 and len(feeder._queue) < 200  # Two phases per call.
        assert len(feeder._scripted_pending) <= 2
        initial_rows += len(rows)


def test_demo_clock_jump_closes_previously_submitted_scripted_simulations(tmp_path):
    start = datetime(2026, 10, 15, 15).timestamp()
    now = [start]
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: now[0])
    state = FactoryState(wq_day(feeder.clock()), clock=feeder.clock)
    path = tmp_path / "log" / "2026-10-15.jsonl"
    position = 0
    try:
        for second in (0, 1, 4, 3600):
            now[0] = start+second
            feeder.tick()
            with path.open() as stream:
                stream.seek(position)
                for raw in stream:
                    state.feed(json.loads(raw))
                position = stream.tell()
            if second == 4:
                assert {sim["sim"] for sim in state.snapshot("demo")["pending_sims"]} == {
                    "DEMO_SIM_ONBOARD_MAIN", "DEMO_SIM_ONBOARD_FAILED"}
        snapshot = state.snapshot("demo")
        assert not {"DEMO_SIM_ONBOARD_MAIN", "DEMO_SIM_ONBOARD_FAILED"} & {
            sim["sim"] for sim in snapshot["pending_sims"]}
        closures = [json.loads(raw) for raw in path.read_text().splitlines()
                    if "DEMO 时钟跳跃，结束过期演示回测" in raw]
        assert {row["sim"] for row in closures} == {"DEMO_SIM_ONBOARD_MAIN", "DEMO_SIM_ONBOARD_FAILED"}
        assert all(row["role"] == "result" and row["status"] == "failed" and row["ok"] is False
                   and row["alphas"] == [] and row["ts"] == start+3600 for row in closures)
        assert state.bad_lines == 0 and len(feeder._queue) < 200
        assert len(feeder._scripted_pending) <= 2
    finally:
        state.close()


def test_third_demo_session_becomes_idle_during_playback(tmp_path):
    now = [datetime(2026, 10, 15, 15).timestamp()]
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: now[0])
    feeder.seed_history()
    state = FactoryState(wq_day(feeder.clock()), clock=feeder.clock)
    for path in (tmp_path / "log").glob("*.jsonl"):
        for raw in path.read_text().splitlines():
            state.feed(json.loads(raw))
    third = lambda: next(s for s in state.snapshot("demo")["sessions"] if s["pid"] == 4103)
    assert third()["idle"] is False
    now[0] += 61
    assert third()["idle"] is True
    state.close()


def test_local_midnight_demo_keeps_three_hours_across_local_log_files(tmp_path):
    from SpiderPanel.server import PanelRuntime
    actual = datetime(2026, 10, 15, 0, 1).timestamp()
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: actual)
    assert feeder.clock() == actual
    feeder.seed_history()
    feeder.tick()
    runtime = PanelRuntime(tmp_path, mode="demo", clock=lambda: feeder.clock()+61,
                           today=lambda: datetime.fromtimestamp(feeder.clock()).date())
    runtime.poll()
    snap = runtime.snapshot()
    assert len(snap["sessions"]) == 3 and len(snap["timeline"]) >= 12
    assert any(s["idle"] for s in snap["sessions"])
    assert snap["day"] == wq_day(actual).isoformat()
    assert len(list((tmp_path / "log").glob("*.jsonl"))) == 2
    assert all(row["ts"] <= actual for p in (tmp_path / "log").glob("*.jsonl")
               for row in map(json.loads, p.read_text().splitlines()))
    runtime.close()


def test_demo_near_wq_reset_uses_prior_window_without_future_or_outside_rows(tmp_path):
    from zoneinfo import ZoneInfo
    actual = datetime(2026, 10, 15, 0, 1, tzinfo=ZoneInfo("America/New_York")).timestamp()
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: actual)
    feeder.seed_history()
    window = wq_window(now=feeder.clock())
    rows = [json.loads(raw) for path in (tmp_path / "log").glob("*.jsonl")
            for raw in path.read_text().splitlines()]
    assert window.day == date(2026, 10, 14)
    assert feeder.clock() == actual-3*3600
    assert min(row["ts"] for row in rows) <= feeder.clock()-3*3600
    assert all(window.start <= row["ts"] < window.end and row["ts"] <= actual for row in rows)


def test_demo_seed_clamps_call_starts_at_exact_three_hours_after_wq_reset(tmp_path):
    from zoneinfo import ZoneInfo
    actual = datetime(2026, 10, 15, 3, tzinfo=ZoneInfo("America/New_York")).timestamp()
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: actual)
    feeder.seed_history()
    rows = [json.loads(raw) for path in (tmp_path / "log").glob("*.jsonl")
            for raw in path.read_text().splitlines()]
    assert feeder.clock() == actual
    assert min(row["ts"] for row in rows) == feeder.window.start
    assert all(feeder.window.start <= row["ts"] < feeder.window.end for row in rows)
