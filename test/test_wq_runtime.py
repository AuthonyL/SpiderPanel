"""Timestamp-window reads over local-day tracker files without a listener."""

from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

from SpiderPanel import processes, rules
from SpiderPanel.server import PanelRuntime, parse_args
from SpiderPanel.wq_day import wq_window
from test_server import append
from test_state import line
from test_wq_day import shanghai_local


SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 10, 15)


def stamp(day, hour, minute=0, second=0):
    return datetime(2026, 10, day, hour, minute, second, tzinfo=SHANGHAI).timestamp()


def save(root, ts, identity):
    append(root, datetime.fromtimestamp(ts).date(),
           line("save", ts=ts, alpha=identity, passed=True, saved=True))


def test_default_runtime_uses_clock_ny_day_and_local_today_only_for_cleanup(tmp_path, shanghai_local):
    now = stamp(16, 0, 1)
    runtime = PanelRuntime(tmp_path, mode="demo", clock=lambda: now, today=lambda: date(2001, 1, 1))
    try:
        assert runtime.day == DAY
        assert tuple(tail.path.name for tail in runtime.tails) == ("2026-10-15.jsonl", "2026-10-16.jsonl")
        assert runtime.snapshot()["day"] == "2026-10-15"
    finally:
        runtime.close()


def test_initial_load_reads_both_local_files_and_filters_adjacent_wq_days(tmp_path, shanghai_local):
    window = wq_window(DAY)
    for ts, identity in ((window.start-1, "before"), (window.start, "start"),
                         (stamp(16, 0, 1), "second-file"), (window.end-1, "last"),
                         (window.end, "after")):
        save(tmp_path, ts, identity)
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: window.end+60)
    try:
        runtime.poll()
        snapshot = runtime.snapshot()
        assert snapshot["totals"]["candidates"] == 3
        assert {row["id"] for row in snapshot["review"]} == {"start", "second-file", "last"}
        assert runtime.state.bad_lines == 0
    finally:
        runtime.close()


def test_local_midnight_follows_new_file_without_resetting_wq_state(tmp_path, shanghai_local):
    now = [stamp(15, 23, 59, 59)]
    save(tmp_path, now[0], "before-midnight")
    runtime = PanelRuntime(tmp_path, mode="demo", clock=lambda: now[0])
    try:
        runtime.poll()
        state = runtime.state
        key, _ = runtime.payload()
        now[0] = stamp(16, 0, 0, 1)
        save(tmp_path, now[0], "after-midnight")
        runtime.poll()
        assert runtime.state is state and runtime.day == DAY
        assert runtime.snapshot()["totals"]["candidates"] == 2
        assert runtime.payload()[0] != key
    finally:
        runtime.close()


def test_wq_reset_reloads_shared_local_file_even_with_old_half_line(tmp_path, shanghai_local):
    window = wq_window(DAY)
    now = [window.end-1]
    save(tmp_path, window.start+1, "yesterday")
    save(tmp_path, window.end-1, "last-old")
    # A complete new-window row can already be in the shared local file.
    save(tmp_path, window.end+1, "already-new")
    old_file = tmp_path / "log" / "2026-10-15.jsonl"
    with old_file.open("ab") as stream:
        stream.write(b'{"old-incomplete":')
    runtime = PanelRuntime(tmp_path, mode="demo", clock=lambda: now[0])
    try:
        runtime.poll()
        old_state = runtime.state
        assert runtime.snapshot()["totals"]["candidates"] == 2
        now[0] = window.end+2
        runtime.poll()
        snapshot = runtime.snapshot()
        assert runtime.state is not old_state and runtime.day == date(2026, 10, 16)
        assert snapshot["totals"]["candidates"] == 1
        assert snapshot["review"][0]["id"] == "already-new"
        assert runtime.state.bad_lines == 0
    finally:
        runtime.close()


def test_cli_replay_freezes_both_file_sizes_and_keeps_requested_wq_day(tmp_path, shanghai_local):
    options = parse_args(["--day", "2026-10-15"])
    first, second = stamp(15, 23), stamp(16, 1)
    save(tmp_path, first, "first")
    save(tmp_path, second, "second")
    runtime = PanelRuntime(tmp_path, day=options.day, clock=lambda: stamp(17, 14))
    try:
        save(tmp_path, second+1, "appended-later")
        runtime.poll()
        runtime.poll()
        snapshot = runtime.snapshot()
        assert snapshot["day"] == "2026-10-15" and snapshot["mode"] == "replay"
        assert snapshot["totals"]["candidates"] == 2
        assert {row["id"] for row in snapshot["review"]} == {"first", "second"}
    finally:
        runtime.close()


def test_backlog_budget_is_shared_and_all_rows_are_polled_later(tmp_path, shanghai_local, monkeypatch):
    monkeypatch.setattr(rules, "MAX_LINES_PER_POLL", 3)
    for index in range(5):
        save(tmp_path, stamp(15, 23)+index, f"first-{index}")
    for index in range(5):
        save(tmp_path, stamp(16, 1)+index, f"second-{index}")
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: stamp(16, 10))
    try:
        counts = []
        for _ in range(5):
            runtime.poll()
            counts.append(runtime.snapshot()["totals"]["candidates"])
        assert counts == [3, 6, 9, 10, 10]
        assert all(tail.offset == tail.path.stat().st_size for tail in runtime.tails)
    finally:
        runtime.close()


def test_half_line_survives_local_midnight_while_new_file_is_read(tmp_path, shanghai_local):
    now = [stamp(15, 23, 59, 59)]
    root = tmp_path / "log"
    root.mkdir()
    path = root / "2026-10-15.jsonl"
    data = json.dumps(line("save", ts=now[0], alpha="half", saved=True, passed=True)).encode()
    path.write_bytes(data[:20])
    runtime = PanelRuntime(tmp_path, mode="demo", clock=lambda: now[0])
    try:
        runtime.poll()
        now[0] = stamp(16, 0, 0, 1)
        save(tmp_path, now[0], "complete-new-file")
        runtime.poll()
        assert runtime.snapshot()["totals"]["candidates"] == 1
        with path.open("ab") as stream:
            stream.write(data[20:]+b"\n")
        runtime.poll()
        assert runtime.snapshot()["totals"]["candidates"] == 2
        assert runtime.state.bad_lines == 0
    finally:
        runtime.close()


def test_loaded_batch_sorts_timestamps_stably_and_keeps_bad_rows(tmp_path, shanghai_local):
    ts = stamp(15, 18)
    rows = [line("precheck", ts=ts+1, status="pass", ph="end"),
            line("precheck", ts=ts, ph="start", n=8),
            line("precheck", ts=ts+1, ph="start", n=8)]
    for row in rows:
        append(tmp_path, DAY, row)
    path = tmp_path / "log" / "2026-10-15.jsonl"
    with path.open("ab") as stream:
        stream.write(b'bad json\n{"ts":NaN,"role":"precheck"}\n')
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: ts+10)
    observed = []
    original = runtime.state.feed
    def feed(row):
        observed.append(row)
        original(row)
    runtime.state.feed = feed
    try:
        runtime.poll()
        assert observed[:3] == [rows[1], rows[0], rows[2]]
        assert runtime.state.bad_lines == 2
        json.dumps(runtime.snapshot(), allow_nan=False)
    finally:
        runtime.close()


def test_outside_window_rows_do_not_probe_their_processes(tmp_path, shanghai_local, monkeypatch):
    window = wq_window(DAY)
    probes = []
    monkeypatch.setattr(processes, "process_alive", lambda pid: probes.append(pid) or True)
    for ts in (window.start-1, window.end):
        append(tmp_path, datetime.fromtimestamp(ts).date(),
               line("precheck", ts=ts, pid=999, status="pass"))
    append(tmp_path, DAY, line("precheck", ts=window.start+1, pid=101,
                               ppid=77, agent="codex", status="pass"))
    runtime = PanelRuntime(tmp_path, clock=lambda: window.start+2)
    try:
        runtime.poll()
        assert probes == [77]
        assert runtime.state.bad_lines == 0
        assert len(runtime.snapshot()["sessions"]) == 1
    finally:
        runtime.close()
