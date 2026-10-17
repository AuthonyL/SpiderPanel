"""Call phases reflect work in progress without changing completed-work totals."""

from datetime import datetime
import json

import pytest

from SpiderPanel import rules
from SpiderPanel.state import FactoryState
from test_state import DAY, TS, line


TOOLS = {
    "simulate": "wqb_create_multi_simulation",
    "precheck": "check_expression_group_diversity",
    "result": "local_wait_multi_simulation",
    "evaluate": "evaluate_simulation_alphas",
    "prod": "check_alpha_prod_correlation",
    "save": "save_candidate_alpha",
}


def start(role, ts=TS, pid=101, ppid=77, **params):
    return {"v": 1, "ts": ts, "t": TOOLS[role], "role": role, "pid": pid,
            "ppid": ppid, "agent": "codex", "ph": "start", **params}


def stamp(ts):
    return datetime.fromtimestamp(ts).astimezone().isoformat()


@pytest.mark.parametrize("role,params,phase,label,event", [
    ("simulate", {"n": 7}, "submitting", "提交中", "sim_submit_start"),
    ("precheck", {"n": 7}, "precheck", "预检中", None),
    ("result", {"sim": "batch"}, "simulating", "等回测", None),
    ("evaluate", {"sim": "batch"}, "evaluating", "评估中", "eval_start"),
    ("prod", {"alpha": "a"}, "prod", "查相关性", "prod_start"),
    ("save", {"alpha": "a"}, "saving", "存候选", "save_start"),
])
def test_starts_show_current_call_without_completed_work(role, params, phase, label, event):
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(start(role, **params))
        snap = state.snapshot("live")
        assert state.bad_lines == 0
        assert snap["revision"] == 1
        session = snap["sessions"][0]
        assert (session["phase"], session["phase_label"], session["idle"]) == (phase, label, False)
        assert session["inflight"] == {
            "tool": TOOLS[role], "since": stamp(TS),
            **{key: value for key, value in params.items() if key in ("sim", "alpha")}}
        assert session["last_seen"] == stamp(TS)
        assert snap["totals"] == {"sessions_active": 1, "sessions_total": 1, "exprs": 0,
                                  "sims_done": 0, "sims_pending": 0, "alphas": 0,
                                  "eval_passed": 0, "candidates": 0, "pending_review": 0}
        assert not any(session["counts"].values())
        assert not any(snap["rejects"].values())
        assert state.calls == state.submits == state.evaluated == state.prod_checks == 0
        assert snap["alphas"] == [] and snap["pending_sims"] == []
        assert snap["best"] is None and snap["sim_typical_seconds"] is None
        assert [item["kind"] for item in snap["events"]] == ([event] if event else [])
        if event:
            item = snap["events"][0]
            assert item["pid"] == 77 and item["ts"] == stamp(TS)
            if role == "simulate":
                assert item["n"] == 7
            elif role == "evaluate":
                assert item["sim"] == "batch" and item["n"] == 0 and item["alphas"] == []
            else:
                assert item["alpha"] == "a" and item["alphas"] == ["a"]
        json.dumps(snap, allow_nan=False)
    finally:
        state.close()


@pytest.mark.parametrize("explicit", [False, True])
def test_matching_end_clears_call_and_counts_business_once(explicit):
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(start("simulate", n=1))
        state.feed(line("simulate", ts=TS+1, pid=101, ppid=77,
                        status="submitted", sim="batch", exprs=[["h", "rank(close)"]],
                        **({"ph": "end"} if explicit else {})))
        snap = state.snapshot("live")
        session = snap["sessions"][0]
        assert session["inflight"] is None
        assert (session["phase"], session["phase_label"]) == ("thinking", "构思中")
        assert snap["totals"]["exprs"] == snap["totals"]["sims_pending"] == 1
        assert state.calls == state.submits == 1
        assert [event["kind"] for event in snap["events"]] == ["sim_submit_start", "sim_submit"]
    finally:
        state.close()


@pytest.mark.parametrize("role,params,outcome", [
    ("precheck", {"n": 2}, {"status": "pass"}),
    ("result", {"sim": "batch"}, {"status": "pending", "dur": 12.0}),
    ("evaluate", {"sim": "batch"}, {"alphas": []}),
    ("prod", {"alpha": "a"}, {"prod": .5}),
    ("save", {"alpha": "a"}, {"saved": True, "passed": True}),
])
def test_every_role_clears_its_matching_end(role, params, outcome):
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(start(role, **params))
        state.feed(line(role, ts=TS+1, pid=101, ppid=77, ph="end", **params, **outcome))
        snap = state.snapshot("live")
        assert snap["sessions"][0]["inflight"] is None
        assert snap["sessions"][0]["phase"] == "thinking"
        assert state.calls == 1
        assert snap["sim_typical_seconds"] == (12.0 if role == "result" else None)
    finally:
        state.close()


def test_start_does_not_change_existing_alpha_status_or_qualified_best():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("evaluate", pid=101, ppid=77, agent="codex", sim="batch",
                        alphas=[["a", "h", True, 2.0, 1.0, []]]))
        before = state.snapshot("live")
        for index, role in enumerate(("evaluate", "prod", "save")):
            state.feed(start(role, ts=TS+index+1, sim="batch") if role == "evaluate"
                       else start(role, ts=TS+index+1, alpha="a"))
        after = state.snapshot("live")
        assert after["alphas"] == before["alphas"]
        assert after["best"] == before["best"]
        assert after["rejects"] == before["rejects"]
        assert after["totals"]["eval_passed"] == 1
    finally:
        state.close()


def test_newest_concurrent_call_is_public_and_older_call_returns_when_it_ends():
    state = FactoryState(DAY, clock=lambda: TS+20)
    try:
        state.feed(start("evaluate", sim="batch"))
        state.feed(start("prod", ts=TS+1, alpha="a"))
        state.feed(start("save", ts=TS+2, alpha="b"))
        assert state.snapshot("live")["sessions"][0]["inflight"]["alpha"] == "b"
        state.feed(line("save", ts=TS+3, pid=101, ppid=77, ph="end", alpha="b", ok=False, err="disk full"))
        snap = state.snapshot("live")
        assert snap["sessions"][0]["inflight"] == {
            "tool": TOOLS["prod"], "since": stamp(TS+1), "alpha": "a"}
        assert snap["sessions"][0]["phase"] == "prod"
        state.feed(line("prod", ts=TS+4, pid=101, ppid=77, ph="end", alpha="a", ok=False, err="offline"))
        assert state.snapshot("live")["sessions"][0]["phase"] == "evaluating"
        state.feed(line("evaluate", ts=TS+5, pid=101, ppid=77, ph="end", sim="batch", ok=False, err="worker failed"))
        session = state.snapshot("live")["sessions"][0]
        assert session["inflight"] is None and session["phase"] == "thinking"
        assert state.calls == 3 and state.rejects["tool_error"] == 3
    finally:
        state.close()


def test_ends_match_validator_tool_and_subject_without_clearing_newer_child():
    state = FactoryState(DAY, clock=lambda: TS+20)
    try:
        state.feed(start("evaluate", sim="old"))
        state.feed(start("evaluate", ts=TS+1, pid=102, sim="new"))
        state.feed(line("evaluate", ts=TS+2, pid=101, ppid=77, ph="end", sim="old", alphas=[]))
        assert state.snapshot("live")["sessions"][0]["inflight"]["sim"] == "new"
        state.feed(start("evaluate", ts=TS+3, pid=102, sim="other"))
        state.feed(line("evaluate", ts=TS+4, pid=102, ppid=77, ph="end", sim="new", alphas=[]))
        assert state.snapshot("live")["sessions"][0]["inflight"]["sim"] == "other"
        state.feed(start("evaluate", ts=TS+6, pid=102, sim="other"))
        state.feed(line("evaluate", ts=TS+5, pid=102, ppid=77, ph="end", sim="other", alphas=[]))
        assert state.snapshot("live")["sessions"][0]["inflight"]["since"] == stamp(TS+6)
        state.feed(line("evaluate", ts=TS+7, pid=102, ppid=77, ph="end", sim="other", alphas=[]))
        assert state.snapshot("live")["sessions"][0]["inflight"] is None
    finally:
        state.close()


def test_inflight_stays_busy_after_fifteen_minutes_and_expires_at_forty():
    now = [TS]
    state = FactoryState(DAY, clock=lambda: now[0])
    try:
        state.feed(start("result", sim="batch"))
        now[0] = TS+2399
        before = state.snapshot("live")
        assert before["sessions"][0]["phase"] == "simulating"
        assert before["sessions"][0]["idle"] is False
        assert before["totals"]["sessions_active"] == 1
        now[0] += 1
        state.refresh()
        after = state.snapshot("live")
        assert after["sessions"][0]["inflight"] is None
        assert after["sessions"][0]["phase"] == "idle"
        assert after["totals"]["sessions_active"] == 0
        assert after["revision"] == before["revision"]+1
        assert state.snapshot("live")["revision"] == after["revision"]
        assert not any(after["rejects"].values())
    finally:
        state.close()


def test_finished_calls_think_for_fifteen_minutes_then_idle():
    now = [TS+900]
    state = FactoryState(DAY, clock=lambda: now[0])
    try:
        state.feed(line("precheck", pid=101, ppid=77, status="pass"))
        active = state.snapshot("live")
        assert active["sessions"][0]["phase"] == "thinking"
        assert active["sessions"][0]["inflight"] is None
        now[0] += 1
        idle = state.snapshot("live")
        assert idle["sessions"][0]["phase"] == "idle"
        assert idle["revision"] > active["revision"]
    finally:
        state.close()


def test_ended_process_clears_archived_calls_and_unknown_lifetime_stays_thirty_minutes(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 1)
    now = [TS+10]
    state = FactoryState(DAY, clock=lambda: now[0])
    try:
        state.feed(start("result", sim="batch"))
        for pid in range(2, 6):
            state.feed(start("precheck", pid=pid, ppid=pid+100))
        assert 77 not in state.sessions
        state.check_processes(lambda pid: pid != 77)
        snap = state.snapshot("live")
        assert 77 not in [session["pid"] for session in snap["sessions"]]
        assert snap["sessions_ended"] == 1
        archived = state._archive.get("session", 77)
        assert not archived.get("_inflight")
        state.feed(start("result", pid=0, ppid=None, sim="unknown"))
        now[0] = TS+1801
        assert 0 not in [session["pid"] for session in state.snapshot("live")["sessions"]]
    finally:
        state.close()


def test_many_archived_calls_expire_without_changing_daily_counts(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 1)
    now = [TS+10]
    state = FactoryState(DAY, clock=lambda: now[0])
    try:
        for pid in range(1, 21):
            state.feed(start("precheck", pid=pid, ppid=pid+100))
        before = state.snapshot("live")
        assert len(before["sessions"]) == 20
        now[0] = TS+2400
        after = state.snapshot("live")
        assert all(session["inflight"] is None and session["idle"] for session in after["sessions"])
        assert after["totals"]["sessions_total"] == 20
        assert after["totals"]["sessions_active"] == 0
        assert after["revision"] > before["revision"]
        assert state.snapshot("live")["revision"] == after["revision"]
        assert all(not session.get("_inflight") for session in state._archive.records("session"))
        assert state.calls == 0
    finally:
        state.close()


def test_eval_start_includes_same_batch_alphas_from_memory_and_archive(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 2)
    state = FactoryState(DAY, clock=lambda: TS+20)
    try:
        state.feed(line("result", pid=101, ppid=77, status="completed", sim="batch",
                        alphas=[[f"h{i}", f"a{i}", 1.0, .5, .2] for i in range(10)]))
        state.feed(line("result", ts=TS+1, pid=101, ppid=77, status="completed", sim="other",
                        alphas=[["other-h", "other-alpha", 1.0, .5, .2]]))
        assert len(state.alphas) < 10
        state.feed(start("evaluate", ts=TS+2, sim="batch"))
        event = state.snapshot("live")["events"][-1]
        assert event["kind"] == "eval_start" and event["sim"] == "batch"
        assert event["n"] == 10
        assert event["alphas"] == ["a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7"]
    finally:
        state.close()


def test_late_parent_metadata_merges_archived_calls_and_aliases(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 1)
    monkeypatch.setattr(rules, "PROCESS_CACHE_MAX", 1)
    state = FactoryState(DAY, clock=lambda: TS+20)
    try:
        state.feed(start("evaluate", pid=101, ppid=None, sim="old"))
        for pid in range(2, 5):
            state.feed(start("precheck", pid=pid, ppid=pid+100))
        assert 101 not in state.sessions
        state.feed(start("prod", ts=TS+1, pid=102, alpha="a"))
        state.feed(line("precheck", ts=TS+2, pid=101, ppid=77, status="pass"))
        session = next(s for s in state.snapshot("live")["sessions"] if s["pid"] == 77)
        assert session["phase"] == "prod"
        state.feed(line("prod", ts=TS+3, pid=102, alpha="a", prod=.5, ph="end"))
        session = next(s for s in state.snapshot("live")["sessions"] if s["pid"] == 77)
        assert session["inflight"] == {"tool": TOOLS["evaluate"], "since": stamp(TS), "sim": "old"}
        state.feed(line("evaluate", ts=TS+4, pid=101, sim="old", alphas=[], ph="end"))
        snap = state.snapshot("live")
        assert next(s for s in snap["sessions"] if s["pid"] == 77)["inflight"] is None
        assert snap["totals"]["sessions_total"] == 4
        assert all(event["pid"] == 77 for event in snap["events"] if event["kind"] in ("eval_start", "prod_start"))
    finally:
        state.close()


@pytest.mark.parametrize("fields", [{"ph": "unknown"}, {"n": -1}, {"n": True}, {"n": "2"}])
def test_malformed_start_rows_are_ignored(fields):
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(start("simulate", **fields))
        assert state.bad_lines == 1 and state.revision == 0
        assert state.snapshot("live")["sessions"] == []
    finally:
        state.close()


def test_unmatched_starts_have_bounded_memory():
    state = FactoryState(DAY, clock=lambda: TS+1000)
    try:
        for index in range(500):
            state.feed(start("evaluate", ts=TS+index, sim=f"batch-{index}"))
        snap = state.snapshot("live")
        assert snap["sessions"][0]["inflight"]["sim"] == "batch-499"
        assert len(json.dumps(state.sessions[77], ensure_ascii=False)) < 30000
        assert snap["totals"]["alphas"] == 0
    finally:
        state.close()
