"""Terminal identity and qualified rankings stay correct across retirement."""

from SpiderPanel import rules
from SpiderPanel.state import FactoryState
from test_state import DAY, TS, line


def test_reconnected_validators_share_parent_identity_and_all_join_keys():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("simulate", pid=101, ppid=77, agent="kimi3", sim="one", status="submitted", exprs=[["h", "rank(close)"]]))
        state.feed(line("result", ts=TS+1, pid=102, ppid=77, agent="kimi3", sim="one", status="completed", alphas=[["h", "a", 1.8, .8, .2]]))
        state.feed(line("simulate", ts=TS+2, pid=102, ppid=77, agent="kimi3", sim="two", status="submitted", exprs=[["h2", "rank(volume)"]]))
        snap = state.snapshot("live")
        assert len(snap["sessions"]) == snap["totals"]["sessions_total"] == 1
        session = snap["sessions"][0]
        assert (session["pid"], session["ppid"], session["validator_pid"], session["label"]) == (77, 77, 102, "kimi3")
        assert session["counts"]["exprs"] == 2 and session["counts"]["alphas"] == 1
        assert snap["alphas"][0]["pid"] == snap["pending_sims"][0]["pid"] == 77
        assert all(event["pid"] == 77 for event in snap["events"])
    finally:
        state.close()


def test_badges_preserve_case_number_duplicate_agents_and_use_terminal_fallback():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        for pid, agent in [(11, "kimi3"), (22, "agent_demo"), (33, "kimi3"), (44, None), (55, "codex")]:
            state.feed(line("precheck", pid=pid, agent=agent, status="pass"))
        assert [s["label"] for s in state.snapshot("live")["sessions"]] == [
            "kimi3 · 1", "agent_demo", "kimi3 · 2", "终端 4", "codex"]
        state.check_processes(lambda pid: pid != 11)
        snap = state.snapshot("live")
        assert [s["pid"] for s in snap["sessions"]] == [22, 33, 44, 55]
        assert next(s["label"] for s in snap["sessions"] if s["pid"] == 33) == "kimi3 · 2"
        assert snap["sessions_ended"] == 1
    finally:
        state.close()


def test_ended_session_removes_seat_and_pending_without_losing_daily_work():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("simulate", pid=101, ppid=77, agent="codex", status="submitted", sim="pending", exprs=[["h", "rank(close)"]]))
        state.feed(line("evaluate", pid=102, ppid=77, agent="codex", alphas=[["a", "h", True, 1.2, .8, []]]))
        state.feed(line("save", pid=102, ppid=77, agent="codex", alpha="a", passed=True, saved=True))
        before = state.snapshot("live")
        probed = []
        state.check_processes(lambda pid: probed.append(pid) or False)
        after = state.snapshot("live")
        assert probed == [77], "Parent lifetime wins over validator lifetime"
        assert after["sessions"] == [] and after["sessions_ended"] == 1
        assert after["pending_sims"] == [] and after["totals"]["sims_pending"] == 0
        assert after["totals"]["sessions_active"] == 0
        for key in ("sessions_total", "exprs", "alphas", "eval_passed", "candidates"):
            assert after["totals"][key] == before["totals"][key]
        assert after["revision"] > before["revision"]
        assert after["alphas"][0]["session_label"] == "codex"
        revision = after["revision"]
        state.check_processes(lambda pid: False)
        assert state.snapshot("live")["revision"] == revision
    finally:
        state.close()


def test_living_idle_session_stays_while_unknown_expires_after_thirty_minutes():
    now = [TS]
    state = FactoryState(DAY, clock=lambda: now[0])
    try:
        legacy = line("precheck", status="pass")
        legacy.pop("pid")
        state.feed(legacy)
        state.feed(line("precheck", pid=10, agent="agent_demo", status="pass"))
        now[0] = TS+1800
        state.check_processes(lambda pid: True)
        snap = state.snapshot("live")
        assert [s["pid"] for s in snap["sessions"]] == [0, 10]
        assert all(s["idle"] for s in snap["sessions"])
        assert snap["sessions"][0]["label"] == "未知会话"
        now[0] += 1
        ended = state.snapshot("live")
        assert [s["pid"] for s in ended["sessions"]] == [10]
        assert ended["sessions_ended"] == 1 and ended["totals"]["sessions_total"] == 2
        assert ended["revision"] > snap["revision"]
    finally:
        state.close()


def test_archived_sessions_keep_badges_retirement_and_counts(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 1)
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        for pid in range(1, 5):
            state.feed(line("precheck", pid=pid, agent="kimi3", status="pass"))
        state.check_processes(lambda pid: pid != 1)
        snap = state.snapshot("live")
        assert snap["sessions_ended"] == 1 and snap["totals"]["sessions_total"] == 4
        assert [s["label"] for s in snap["sessions"]] == ["kimi3 · 2", "kimi3 · 3", "kimi3 · 4"]
        state.feed(line("save", ts=TS+1, pid=2, alpha="a", saved=True, passed=True))
        assert next(s for s in state.snapshot("live")["sessions"] if s["pid"] == 2)["counts"]["candidates"] == 1
    finally:
        state.close()


def test_best_and_timeline_exclude_failed_unchecked_and_blocked_alphas():
    state = FactoryState(DAY, clock=lambda: TS+1800)
    try:
        state.feed(line("result", status="completed", sim="s", alphas=[["h0", "unchecked", 9.0, 5.0, .2]]))
        state.feed(line("evaluate", ts=TS+1, alphas=[
            ["failed", "h1", False, 8.0, 5.0, ["fitness"]],
            ["blocked", "h2", True, 3.0, 1.0, []],
            ["winner", "h3", True, 1.8, 1.0, []]]))
        state.feed(line("prod", ts=TS+2, alpha="blocked", prod=.8))
        snap = state.snapshot("live")
        assert snap["best"]["id"] == "winner" and snap["best"]["sharpe"] == 1.8
        assert snap["timeline"][0]["best_sharpe"] == 1.8
        assert len(snap["alphas"]) == 4
        state.feed(line("save", ts=TS+901, alpha="winner", saved=False, passed=False))
        empty = state.snapshot("live")
        assert empty["best"] is None
        assert all(bucket["best_sharpe"] is None for bucket in empty["timeline"])
    finally:
        state.close()


def test_archived_best_is_qualified_and_recomputed_after_later_block(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 1)
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("evaluate", agent="codex", alphas=[["qualified", "h", True, 2.0, 1.0, []]]))
        for i in range(4):
            state.feed(line("evaluate", ts=TS+i+1, alphas=[[f"bad{i}", f"h{i}", False, 4.0+i, .1, ["fitness"]]]))
        snap = state.snapshot("live")
        assert "qualified" not in state.alphas
        assert snap["best"]["id"] == "qualified" and snap["best"]["session_label"] == "codex"
        assert snap["timeline"][0]["best_sharpe"] == 2.0
        state.feed(line("prod", ts=TS+6, alpha="qualified", prod=.7))
        assert state.snapshot("live")["best"] is None
        assert state.snapshot("live")["timeline"][0]["best_sharpe"] is None
    finally:
        state.close()


def test_later_block_or_local_rejection_disqualifies_a_saved_candidate():
    for reject in ("prod", "save"):
        state = FactoryState(DAY, clock=lambda: TS+10)
        try:
            state.feed(line("evaluate", alphas=[["a", "h", True, 2.0, 1.0, []]]))
            state.feed(line("save", ts=TS+1, alpha="a", saved=True, passed=True))
            assert state.snapshot("live")["best"]["id"] == "a"
            fields = {"prod": .8} if reject == "prod" else {"saved": False, "passed": False}
            state.feed(line(reject, ts=TS+2, alpha="a", **fields))
            snap = state.snapshot("live")
            assert snap["best"] is None
            assert snap["timeline"][0]["best_sharpe"] is None
            assert len(snap["alphas"]) == 1
        finally:
            state.close()


def test_parent_metadata_arriving_late_migrates_every_join_without_losing_work():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("simulate", pid=101, status="submitted", sim="pending", exprs=[["h", "rank(close)"]]))
        state.feed(line("evaluate", ts=TS+1, pid=101, alphas=[["a", "h", True, 1.8, .8, []]]))
        state.feed(line("precheck", ts=TS+2, pid=101, ppid=77, agent="codex", status="pass"))
        state.check_processes(lambda pid: pid == 77)
        snap = state.snapshot("live")
        assert [s["pid"] for s in snap["sessions"]] == [77]
        assert snap["totals"]["sessions_total"] == 1 and snap["sessions_ended"] == 0
        assert snap["pending_sims"][0]["pid"] == snap["best"]["pid"] == 77
        assert all(event["pid"] == 77 for event in snap["events"])
        assert snap["sessions"][0]["counts"]["exprs"] == 1
        assert snap["best"]["session_label"] == "codex"
    finally:
        state.close()


def test_late_parent_merges_existing_terminal_counts_and_preserves_unique_indexes():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("simulate", pid=101, region="ASI", universe="TOP500", delay=1,
                        status="submitted", sim="one", exprs=[["h", "rank(close)"]]))
        state.feed(line("simulate", pid=102, ppid=77, agent="agent_demo", status="submitted", sim="two", exprs=[["h2", "rank(volume)"]]))
        state.feed(line("precheck", ts=TS+1, pid=101, ppid=77, agent="agent_demo", status="pass"))
        state.feed(line("precheck", ts=TS+2, pid=999, agent="codex", status="pass"))
        snap = state.snapshot("live")
        assert snap["totals"]["sessions_total"] == 2
        assert [s["pid"] for s in snap["sessions"]] == [77, 999]
        assert len({s["index"] for s in snap["sessions"]}) == 2
        assert snap["sessions"][0]["counts"]["exprs"] == snap["totals"]["exprs"] == 2
        assert snap["sessions"][0]["region"] == "ASI" and snap["sessions"][0]["delay"] == 1
        assert {sim["pid"] for sim in snap["pending_sims"]} == {77}
    finally:
        state.close()


def test_late_parent_rekeys_archived_pending_alphas_and_sessions(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 1)
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("simulate", pid=101, status="submitted", sim="old", exprs=[["h", "rank(close)"]]))
        state.feed(line("evaluate", pid=101, alphas=[["old-alpha", "h", True, 2.0, 1.0, []]]))
        for i in range(3):
            state.feed(line("simulate", ts=TS+i+1, pid=i+1, status="submitted", sim=f"s{i}", exprs=[]))
            state.feed(line("evaluate", ts=TS+i+1, pid=i+1, alphas=[[f"bad{i}", None, False, .1, .1, []]]))
        assert 101 not in state.sessions and "old-alpha" not in state.alphas
        state.feed(line("precheck", ts=TS+5, pid=101, ppid=77, agent="codex", status="pass"))
        snap = state.snapshot("live")
        assert len(snap["sessions"]) == snap["totals"]["sessions_total"] == 4
        assert 101 not in [s["pid"] for s in snap["sessions"]]
        assert snap["best"]["pid"] == 77 and snap["best"]["session_label"] == "codex"
        assert next(sim for sim in snap["pending_sims"] if sim["sim"] == "old")["pid"] == 77
        assert next(s for s in snap["sessions"] if s["pid"] == 77)["counts"]["eval_passed"] == 1
    finally:
        state.close()


def test_missing_agent_can_be_filled_from_older_metadata_without_regressing_phase():
    state = FactoryState(DAY, clock=lambda: TS+20)
    try:
        state.feed(line("precheck", ts=TS+10, pid=102, ppid=77, agent=None, status="pass"))
        state.feed(line("precheck", pid=101, ppid=77, agent="kimi3", status="pass"))
        assert state.snapshot("live")["sessions"][0]["label"] == "kimi3"
        assert state.snapshot("live")["sessions"][0]["validator_pid"] == 102
    finally:
        state.close()


def test_retired_pid_is_not_revived_without_new_work_if_pid_is_reused():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("precheck", pid=101, agent="codex", status="pass"))
        state.check_processes(lambda pid: False)
        assert state.snapshot("live")["sessions_ended"] == 1
        state.check_processes(lambda pid: True)
        assert state.snapshot("live")["sessions_ended"] == 1
        assert state.snapshot("live")["sessions"] == []
    finally:
        state.close()


def test_late_legacy_rows_keep_using_the_known_parent_identity():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("simulate", pid=101, status="submitted", sim="pending", exprs=[["h", "rank(close)"]]))
        state.feed(line("precheck", ts=TS+2, pid=101, ppid=77, agent="codex", status="pass"))
        state.feed(line("result", ts=TS+1, pid=101, status="completed", sim="pending", alphas=[["h", "a", 1.8, .8, .2]]))
        snap = state.snapshot("live")
        assert snap["totals"]["sessions_total"] == 1
        assert [s["pid"] for s in snap["sessions"]] == [77]
        assert snap["alphas"][0]["pid"] == 77
        assert snap["sessions"][0]["ppid"] == 77
        assert all(event["pid"] == 77 for event in snap["events"])
    finally:
        state.close()


def test_parent_aliases_survive_bounded_memory_eviction(monkeypatch):
    monkeypatch.setattr(rules, "PROCESS_CACHE_MAX", 1)
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        for pid in (101, 102, 103):
            state.feed(line("precheck", pid=pid, ppid=pid+1000, agent="codex", status="pass"))
        state.feed(line("save", pid=101, ts=TS+1, alpha="late", saved=True, passed=True))
        snap = state.snapshot("live")
        assert snap["totals"]["sessions_total"] == 3
        assert snap["alphas"][0]["pid"] == 1101
        assert snap["alphas"][0]["session_label"] == "codex · 1"
        assert len(state._parent_aliases) <= 1
    finally:
        state.close()
