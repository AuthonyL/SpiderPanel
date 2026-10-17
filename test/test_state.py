from datetime import date, datetime
import json

import pytest

from SpiderPanel import rules
from SpiderPanel.state import FactoryState
from SpiderPanel.wq_day import wq_window


DAY = date(2026, 10, 15)
TS = wq_window(DAY).start


def line(role, ts=TS, pid=123, **fields):
    tools = {"simulate": "wqb_create_multi_simulation", "result": "local_wait_multi_simulation",
             "evaluate": "evaluate_simulation_alphas", "prod": "check_alpha_prod_correlation",
             "save": "save_candidate_alpha", "precheck": "check_expression_group_diversity"}
    return {"v": 1, "ts": ts, "t": tools.get(role, "bad"), "role": role,
            "ok": True, "dur": 0.0, "pid": pid, **fields}


def submit(state, sim="s1", pid=123, ts=TS):
    state.feed(line("simulate", pid=pid, ts=ts, status="submitted", sim=sim,
                    exprs=[["h1", "rank(close)"], ["h2", "ts_delta(volume, 5)"]],
                    region="ASI", universe="TOP500", delay=1))


def result(state, sim="s1", pid=123, ts=TS+1):
    state.feed(line("result", pid=pid, ts=ts, sim=sim, status="completed",
                    alphas=[["h1", "a1", 1.2, 0.8, 0.2], ["h2", "a2", 1.8, 0.4, 0.3]]))


def evaluate(state, ts=TS+2):
    state.feed(line("evaluate", ts=ts, sim="s1", best="a1", alphas=[
        ["a1", "h1", True, 1.2, 0.8, []], ["a2", "h2", False, 1.8, 0.4, ["fitness"]]]))


def pipeline():
    state = FactoryState(DAY, clock=lambda: TS+10)
    state.feed(line("precheck", status="pass", n=2))
    submit(state)
    result(state)
    evaluate(state)
    state.feed(line("prod", ts=TS+3, alpha="a1", prod=0.65))
    state.feed(line("prod", ts=TS+3, alpha="a2", prod=0.8))
    state.feed(line("save", ts=TS+4, alpha="a1", saved=True, passed=True))
    state.feed(line("save", ts=TS+4, alpha="a2", saved=False, passed=False))
    return state


def test_whole_pipeline_contract_cards_funnel_and_rejects():
    state = pipeline()
    snapshot = state.snapshot("live")
    assert set(snapshot) == {"v", "mode", "day", "generated_at", "revision", "goal", "totals", "cards",
                             "sessions", "alphas", "pending_sims", "funnel", "rejects", "timeline",
                             "best", "review", "events", "thresholds", "sim_typical_seconds", "sessions_ended",
                             "wq_start", "wq_next_reset"}
    assert snapshot["totals"] == {"sessions_active": 1, "sessions_total": 1, "exprs": 2,
                                  "sims_done": 1, "sims_pending": 0, "alphas": 2,
                                  "eval_passed": 1, "candidates": 1, "pending_review": 1}
    assert [c["key"] for c in snapshot["cards"]] == ["generate", "precheck", "simulate", "evaluate", "prod", "candidate", "error", "review"]
    assert [c["value"] for c in snapshot["cards"]] == [2, 0, 1, 1, 2, 1, 0, 1]
    assert [c["progress"] for c in snapshot["cards"]] == [1, 1, 1, 0.5, 0.5, 0.2, 0, 0.2]
    assert all(0 <= c["progress"] <= 1 for c in snapshot["cards"])
    assert [item["count"] for item in snapshot["funnel"]] == [2, 2, 1, 1, 1]
    assert snapshot["rejects"] == {"precheck_fail": 0, "create_fail": 0, "sim_fail": 0,
                                   "eval_fail": 1, "prod_blocked": 1, "save_rejected": 1, "tool_error": 0}
    assert snapshot["goal"] == {"candidates": 1, "target": 5}
    assert snapshot["review"][0]["id"] == "a1"
    assert snapshot["best"]["id"] == "a1"  # Failed/rejected alphas cannot be the qualified best.
    assert all(c["updated_at"] is not None for c in snapshot["cards"] if c["key"] != "error")
    assert snapshot["sessions"][0]["region"] == "ASI"
    json.dumps(snapshot, allow_nan=False)


def test_typical_sim_seconds_is_none_without_wait_durations():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        assert state.snapshot("live")["sim_typical_seconds"] is None
        state.feed(line("precheck", status="pass", dur=42))
        state.feed(line("result", status="pending", t="other_wait", dur=50))
        state.feed(line("simulate", status="submitted", dur=60))
        assert state.snapshot("live")["sim_typical_seconds"] is None
    finally:
        state.close()


def test_typical_sim_seconds_uses_even_median_and_all_wait_outcomes():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        for index, (status, dur) in enumerate((
                ("pending", 2), ("completed", 4), ("failed", 10), ("pending", 20))):
            state.feed(line("result", ts=TS+index, sim=f"s{index}", status=status,
                            dur=dur, ok=status != "failed"))
        snap = state.snapshot("live")
        assert snap["sim_typical_seconds"] == 7
        assert snap["totals"]["sims_done"] == 1
        assert snap["totals"]["sims_pending"] == 2
        assert snap["rejects"]["sim_fail"] == 1
    finally:
        state.close()


def test_typical_sim_seconds_uses_latest_twenty_by_timestamp_with_bounded_storage():
    state = FactoryState(DAY, clock=lambda: TS+100)
    try:
        # Reverse feed order must not make older rows replace newer samples.
        for offset in range(25, 0, -1):
            state.feed(line("result", ts=TS+offset, status="pending", sim="same-batch", dur=offset))
        assert state.snapshot("live")["sim_typical_seconds"] == 15.5
        assert len(state._sim_durations) == 20
        # At equal timestamps the latest arriving rows are the latest calls.
        for _ in range(20):
            state.feed(line("result", ts=TS+25, status="pending", sim="same-batch", dur=100))
        assert state.snapshot("live")["sim_typical_seconds"] == 100
        assert len(state._sim_durations) == 20
    finally:
        state.close()


def test_typical_sim_seconds_ignores_invalid_durations_without_losing_valid_rows():
    state = FactoryState(DAY, clock=lambda: TS+100)
    try:
        state.feed(line("result", status="pending", sim="valid-zero", dur=0))
        state.feed(line("result", ts=TS+1, status="completed", sim="valid-two", dur=2))
        invalid = [None, "12", True, False, -1, float("nan"), float("inf"),
                   -float("inf"), [], {}, 10**400]
        for index, dur in enumerate(invalid):
            state.feed(line("result", ts=TS+index+2, status="pending", sim=f"invalid-{index}", dur=dur))
        missing = line("result", status="pending", sim="missing")
        missing.pop("dur")
        state.feed(missing)
        snap = state.snapshot("live")
        assert snap["sim_typical_seconds"] == 1
        assert snap["totals"]["sims_done"] == 1
        assert snap["totals"]["sims_pending"] == 13
        assert state.bad_lines == 0
        json.dumps(snap, allow_nan=False)
    finally:
        state.close()


def test_typical_sim_seconds_filters_selected_wq_day_and_invalid_rows():
    state = FactoryState(DAY, clock=lambda: TS+100)
    midnight, next_midnight = state.start, state.end
    try:
        for ts, dur in ((midnight, 2), (next_midnight-0.5, 8),
                        (midnight-0.5, 1000), (next_midnight, 2000)):
            state.feed(line("result", ts=ts, status="pending", dur=dur))
        state.feed(line("result", status="pending", dur=3000, pid="invalid"))
        assert state.snapshot("replay")["sim_typical_seconds"] == 5
        assert state.bad_lines == 1
    finally:
        state.close()


def test_typical_sim_seconds_keeps_finite_median_for_large_valid_durations():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        for dur in (1e308, 1e308):
            state.feed(line("result", status="pending", dur=dur))
        snap = state.snapshot("live")
        assert snap["sim_typical_seconds"] == 1e308
        json.dumps(snap, allow_nan=False)
    finally:
        state.close()


def test_simulation_events_include_bounded_batch_context():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        exprs = [[f"h{i}", f"rank(ts_delta(volume, {i + 20}))"] for i in range(10)]
        state.feed(line("simulate", status="submitted", sim="batch", exprs=exprs))
        state.feed(line("result", ts=TS+1, status="completed", sim="batch", alphas=[
            [f"h{i}", f"a{i}", 1.0, 0.5, 0.2] for i in range(10)]))
        state.feed(line("result", ts=TS+2, status="failed", sim="failed-batch", alphas=[], ok=False))
        submitted, completed, failed = state.snapshot("live")["events"]
        assert {key: submitted[key] for key in ("seq", "kind", "pid", "text", "alpha")} == {
            "seq": 1, "kind": "sim_submit", "pid": 123, "text": "提交回测 10 条表达式", "alpha": None}
        assert submitted["sim"] == "batch" and submitted["n"] == 10
        assert submitted["exprs"] == [expr[:24] for _, expr in exprs[:8]]
        assert completed["sim"] == "batch" and completed["n"] == 10
        assert completed["alphas"] == ["a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7"]
        assert failed["kind"] == "sim_fail" and failed["sim"] == "failed-batch"
        assert not ({"n", "alphas", "exprs"} & failed.keys())
    finally:
        state.close()


def test_alpha_events_include_singleton_ids_without_changing_legacy_alpha():
    state = pipeline()
    try:
        events = [event for event in state.snapshot("live")["events"] if event["alpha"]]
        assert {event["kind"] for event in events} == {
            "eval_pass", "eval_fail", "prod_ok", "prod_block", "candidate", "rejected"}
        for event in events:
            assert event["alphas"] == [event["alpha"]]
            assert not ({"sim", "n", "exprs"} & event.keys())
    finally:
        state.close()


def test_event_context_handles_nullable_collector_values():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("simulate", status="submitted", exprs=[[None, None], ["h", "rank(close)"]]))
        state.feed(line("result", status="completed", alphas=[[None, None, None, None, None],
                                                               ["h", "a", 1, 1, 0.2]]))
        submitted, completed = state.snapshot("live")["events"]
        assert submitted["exprs"] == ["rank(close)"] and submitted["n"] == 2
        assert completed["alphas"] == ["a"] and completed["n"] == 2
        assert "sim" not in submitted and "sim" not in completed
    finally:
        state.close()


def test_event_context_does_not_repeat_archived_verdicts_or_grow_event_history(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 1)
    monkeypatch.setattr(rules, "EVENTS_KEEP", 5)
    state = FactoryState(DAY, clock=lambda: TS+100)
    try:
        original = [line("result", sim="old", status="completed", alphas=[["h", "old", 0.1, 0.2, 0.3]]),
                    line("evaluate", ts=TS+1, alphas=[["old", "h", False, 0.1, 0.2, ["sharpe"]]]),
                    line("save", ts=TS+2, alpha="old", saved=False, passed=False)]
        for row in original:
            state.feed(row)
        for i in range(10):
            state.feed(line("result", ts=TS+10+i, sim=f"s{i}", status="completed",
                            alphas=[[f"h{i}", f"a{i}", 0.2, 0.1, 0.3]]))
        before = state.snapshot("live")
        for row in original:
            state.feed({**row, "ts": TS+90})
        after = state.snapshot("live")
        assert after["events"] == before["events"]
        assert len(after["events"]) == 5
        assert all(event["alphas"] == [f"a{i}"] for i, event in enumerate(after["events"], start=5))
        assert after["totals"] == before["totals"]
        assert len(state.alphas) <= 2 and len(state.sims) <= 2
    finally:
        state.close()


@pytest.mark.parametrize("activity", [None, line("result", status="pending", sim="s1")])
def test_precheck_card_has_no_verdict_without_precheck_or_simulate(activity):
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        if activity is not None:
            state.feed(activity)
        card = next(card for card in state.snapshot("live")["cards"] if card["key"] == "precheck")
        assert card["message"] == "暂无预检" and card["updated_at"] is None
    finally:
        state.close()


@pytest.mark.parametrize("role, fields, expected", [
    ("precheck", {"status": "pass"}, "最近一次通过"),
    ("precheck", {"status": "fail"}, "最近一次预检未通过"),
    ("precheck", {"status": "fail", "err": "bad group"}, "bad group"),
    ("precheck", {"ok": False}, "最近一次预检未通过"),
    ("precheck", {"ok": False, "err": "worker failed"}, "worker failed"),
    ("simulate", {"status": "submitted", "sim": "s1"}, "最近一次通过"),
    ("simulate", {"status": "validation_failed"}, "最近一次预检未通过"),
    ("simulate", {"status": "validation_failed", "err": "bad expression"}, "bad expression"),
    ("simulate", {"ok": False}, "最近一次预检未通过"),
    ("simulate", {"ok": False, "err": "submission failed"}, "submission failed"),
])
def test_precheck_card_reports_latest_outcome(role, fields, expected):
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line(role, **fields))
        card = next(card for card in state.snapshot("live")["cards"] if card["key"] == "precheck")
        assert card["message"] == expected
        assert card["updated_at"] == datetime.fromtimestamp(TS).astimezone().isoformat()
    finally:
        state.close()


@pytest.mark.parametrize("events, expected", [
    ([line("precheck", ts=TS+2, status="fail", err="newest failure"),
      line("simulate", ts=TS+1, status="submitted", sim="old")], "newest failure"),
    ([line("simulate", ts=TS+2, status="submitted", sim="new"),
      line("precheck", ts=TS+1, status="fail", err="old failure")], "最近一次通过"),
    ([line("precheck", ts=TS+1, status="fail", err="old failure"),
      line("simulate", ts=TS+2, status="submitted", sim="new")], "最近一次通过"),
    ([line("simulate", ts=TS+1, status="submitted", sim="old"),
      line("precheck", ts=TS+2, status="fail")], "最近一次预检未通过"),
    ([line("precheck", ts=TS+2, status="pass"),
      line("simulate", ts=TS+1, status="validation_failed", err="old submission failure")], "最近一次通过"),
    ([line("simulate", ts=TS+2, status="validation_failed"),
      line("precheck", ts=TS+1, status="pass")], "最近一次预检未通过"),
])
def test_precheck_card_uses_latest_timestamp_across_both_roles(events, expected):
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        for event in events:
            state.feed(event)
        card = next(card for card in state.snapshot("live")["cards"] if card["key"] == "precheck")
        assert card["message"] == expected
        assert card["updated_at"] == datetime.fromtimestamp(TS+2).astimezone().isoformat()
    finally:
        state.close()


def test_status_never_regresses_and_duplicate_result_does_not_double_count():
    state = pipeline()
    result(state, ts=TS+9)
    evaluate(state, ts=TS+8)
    snapshot = state.snapshot("live")
    assert next(a for a in snapshot["alphas"] if a["id"] == "a1")["status"] == "candidate"
    assert next(a for a in snapshot["alphas"] if a["id"] == "a2")["status"] == "rejected"
    assert snapshot["totals"]["sims_done"] == 1 and snapshot["totals"]["alphas"] == 2


def test_expression_backfill_after_results_and_missing_hash():
    state = FactoryState(DAY, clock=lambda: TS+10)
    result(state)
    assert state.snapshot("live")["alphas"][0]["expr"] is None
    submit(state, ts=TS)
    a = {a["id"]: a for a in state.snapshot("live")["alphas"]}
    assert a["a1"]["expr"] == "rank(close)"
    assert state.snapshot("live")["totals"]["sims_pending"] == 0
    state.feed(line("result", status="completed", sim="s2", alphas=[[None, "error_alpha", None, None, None]]))
    assert next(a for a in state.snapshot("live")["alphas"] if a["id"] == "error_alpha")["expr"] is None


def test_sessions_pending_phase_idle_and_old_logs_without_pid():
    now = [TS+2]
    state = FactoryState(DAY, clock=lambda: now[0])
    submit(state)
    state.feed(line("precheck", pid=456, status="pass", n=8))
    old = line("precheck", status="fail", n=8)
    old.pop("pid")
    state.feed(old)
    snap = state.snapshot("live")
    assert [s["pid"] for s in snap["sessions"]] == [123, 456, 0]
    assert [s["shape"] for s in snap["sessions"]] == ["ghost", "square", "circle"]
    assert snap["sessions"][2]["label"] == "未知会话"
    assert snap["sessions"][0]["phase"] == "thinking"  # A completed submit is not an ongoing wait call.
    assert snap["pending_sims"][0]["exprs"] == ["rank(close)", "ts_delta(volume, 5)"]
    revision = state.revision
    now[0] = TS + rules.IDLE_SECONDS + 1
    snap = state.snapshot("live")
    assert snap["totals"]["sessions_active"] == 0
    assert all(s["phase"] == "idle" for s in snap["sessions"])
    assert state.revision > revision


def test_failures_and_tool_errors_are_counted_separately():
    state = FactoryState(DAY, clock=lambda: TS+10)
    state.feed(line("precheck", status="fail", n=8))
    state.feed(line("simulate", status="validation_failed", ok=False, n=8, err="bad group"))
    submit(state)
    state.feed(line("result", sim="s1", status="pending", alphas=[]))
    state.feed(line("result", sim="s1", status="failed", ok=False, err="timeout", alphas=[]))
    state.feed(line("evaluate", ok=False, alphas=[], best=None, err="worker failed"))
    state.feed(line("prod", alpha="a1", prod=None, ok=False, err="offline"))
    state.feed(line("save", alpha="a1", passed=False, saved=False, ok=False, err="disk full"))
    snap = state.snapshot("live")
    assert snap["rejects"]["tool_error"] == 3
    assert snap["rejects"]["sim_fail"] == 1 and snap["rejects"]["create_fail"] == 1
    assert snap["cards"][6]["value"] == 5
    assert snap["cards"][1]["value"] == 2
    assert snap["cards"][1]["progress"] == pytest.approx(1/3)
    assert snap["totals"]["sims_pending"] == 0


def test_timeline_buckets_cumulative_candidates_best_and_event_sequence():
    now = [TS+1800]
    state = FactoryState(DAY, clock=lambda: now[0])
    submit(state)
    result(state)
    evaluate(state)
    state.feed(line("save", ts=TS+901, alpha="a1", saved=True, passed=True))
    snap = state.snapshot("replay")
    assert len(snap["timeline"]) == 3
    assert [b["candidates_cum"] for b in snap["timeline"]] == [0, 1, 1]
    assert snap["timeline"][0]["alphas"] == 2
    assert snap["timeline"][0]["best_sharpe"] == 1.2
    seq = [event["seq"] for event in snap["events"]]
    assert seq == sorted(set(seq))
    assert snap["events"][-1]["kind"] == "candidate"
    assert len(snap["timeline"]) <= 96


def test_memory_limits_keep_all_candidates_and_daily_counters(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 3)
    monkeypatch.setattr(rules, "EVENTS_KEEP", 5)
    state = FactoryState(DAY, clock=lambda: TS+100)
    for i in range(30):
        state.feed(line("result", ts=TS+i, sim=f"s{i}", status="completed", alphas=[[f"h{i}", f"a{i}", i/10, 0.5, 0.2]]))
        if i < 4:
            state.feed(line("save", ts=TS+i, alpha=f"a{i}", saved=True, passed=True))
    snap = state.snapshot("live")
    assert len(snap["review"]) == 4 and len(snap["alphas"]) == 4
    assert snap["totals"]["alphas"] == 30
    assert len(state.alphas) <= 7  # Four candidates plus at most one compaction window.
    assert len(state.sims) <= 6
    assert len(snap["events"]) == 5


def test_pending_simulations_and_phases_survive_cache_eviction(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 2)
    state = FactoryState(DAY, clock=lambda: TS+10)
    submit(state, sim="old", pid=1)
    for i in range(4):
        submit(state, sim=f"s{i}", pid=2)
    snap = state.snapshot("live")
    assert len(state.sims) <= 4
    assert snap["totals"]["sims_pending"] == len(snap["pending_sims"]) == 5
    assert any(sim["sim"] == "old" for sim in state._archive.records("sim", "pending"))
    for sim in snap["pending_sims"]:
        assert {key: sim[key] for key in ("pid", "n", "since")} == {
            "pid": 1 if sim["sim"] == "old" else 2,
            "n": 2, "since": datetime.fromtimestamp(TS).astimezone().isoformat()}
    first = next(s for s in snap["sessions"] if s["pid"] == 1)
    assert first["running_sims"] == 1 and first["phase"] == "thinking"
    result(state, sim="old", pid=1)
    assert state.snapshot("live")["totals"]["sims_pending"] == 4
    state.close()


def test_all_sessions_and_idle_transitions_survive_cache_eviction(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 2)
    now = [TS+10]
    state = FactoryState(DAY, clock=lambda: now[0])
    for pid in range(5):
        state.feed(line("precheck", pid=pid, status="pass", n=8))
    snap = state.snapshot("live")
    assert len(state.sessions) <= 4
    assert snap["totals"]["sessions_total"] == snap["totals"]["sessions_active"] == len(snap["sessions"]) == 5
    assert [s["index"] for s in snap["sessions"]] == [1, 2, 3, 4, 5]
    now[0] += rules.IDLE_SECONDS
    idle = state.snapshot("live")
    assert idle["totals"]["sessions_active"] == 0
    assert idle["revision"] > snap["revision"]
    assert all(s["idle"] for s in idle["sessions"])
    state.close()


@pytest.mark.parametrize("bad", [None, [], {}, line("unknown"), line("prod", alpha="a", prod={}),
                                 line("save", alpha="a", saved="false"), line("result", status="completed", alphas=[None]),
                                 line("simulate", status="submitted", exprs=3), line("prod", ts=float("inf"))])
def test_bad_lines_are_ignored_and_counted(bad):
    state = FactoryState(DAY, clock=lambda: TS)
    state.feed(bad)
    assert state.bad_lines == 1 and state.revision == 0


def test_revision_changes_once_per_feed_and_best_requires_numeric_sharpe():
    state = FactoryState(DAY, clock=lambda: TS+10)
    state.feed(line("precheck", status="pass", n=8))
    assert state.snapshot("live")["revision"] == 1
    state.feed(line("prod", alpha="a", prod=0.5))
    assert state.snapshot("live")["revision"] == 2
    state.feed(line("evaluate", alphas=[["a", None, False, None, None, []]], best=None))
    assert state.snapshot("live")["best"] is None


def test_simulation_identity_survives_process_change():
    state = FactoryState(DAY, clock=lambda: TS+10)
    submit(state, pid=1)
    result(state, pid=2)
    result(state, pid=1, ts=TS+2)
    snap = state.snapshot("live")
    assert snap["totals"]["sims_pending"] == 0
    assert snap["totals"]["sims_done"] == 1


def test_best_is_recomputed_when_previous_winner_changes():
    state = FactoryState(DAY, clock=lambda: TS+10)
    state.feed(line("evaluate", alphas=[["a1", "h1", True, 2.0, 1, []], ["a2", "h2", True, 1.8, 1, []]]))
    state.feed(line("evaluate", ts=TS+1, alphas=[["a1", "h1", True, 1.0, 1, []]]))
    assert state.snapshot("live")["best"]["id"] == "a2"


def test_daily_identity_survives_many_display_compactions(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 3)
    state = FactoryState(DAY, clock=lambda: TS+100)
    for i in range(40):
        state.feed(line("result", ts=TS+i, sim=f"s{i}", status="completed", alphas=[[f"h{i}", f"a{i}", 1, 1, 0.2]]))
    state.feed(line("result", ts=TS+80, sim="s0", status="completed", alphas=[["h0", "a0", 1, 1, 0.2]]))
    snap = state.snapshot("live")
    assert snap["totals"]["alphas"] == 40 and snap["totals"]["sims_done"] == 40
    assert snap["funnel"][1]["count"] == 40
    assert len(state.alphas) <= 6 and len(state.sims) <= 6
    state.close()


def test_stale_prod_counts_the_call_without_overwriting_latest_verdict():
    state = FactoryState(DAY, clock=lambda: TS+10)
    state.feed(line("prod", ts=TS+3, alpha="a", prod=0.8))
    state.feed(line("prod", ts=TS+2, alpha="a", prod=0.2))
    snap = state.snapshot("live")
    assert snap["alphas"][0]["prod"] == 0.8 and snap["alphas"][0]["status"] == "prod_blocked"
    assert snap["cards"][4]["value"] == 2 and snap["cards"][4]["progress"] == 0.5


def test_archived_expression_backfill_survives_hash_cache_eviction(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ALPHAS", 1)
    state = FactoryState(DAY, clock=lambda: TS+100)
    state.feed(line("evaluate", alphas=[["best", "best_hash", True, 2.0, 1, []]]))
    for i in range(3):
        state.feed(line("evaluate", ts=TS+i+1, alphas=[[f"a{i}", f"h{i}", False, 0.2, 0.1, []]]))
    state.feed(line("simulate", ts=TS+10, status="submitted", sim="late", exprs=[["best_hash", "rank(close)"]]))
    assert state.snapshot("live")["best"]["expr"] == "rank(close)"
    for i in range(3):
        state.feed(line("simulate", ts=TS+11+i, status="submitted", sim=f"other{i}", exprs=[[f"other{i}", "rank(volume)"]]))
    assert state.snapshot("live")["best"]["expr"] == "rank(close)"
    state.feed(line("result", ts=TS+20, sim="late", status="completed", alphas=[["best_hash", "best", 0.5, 0.1, 0.2]]))
    assert state.snapshot("live")["best"]["expr"] == "rank(close)"
    state.close()


def test_evaluate_card_message_describes_latest_batch_without_resetting_daily_count():
    state = FactoryState(DAY, clock=lambda: TS+10)
    card = lambda: next(c for c in state.snapshot("live")["cards"] if c["key"] == "evaluate")
    assert card()["message"] == "暂无评估"
    state.feed(line("evaluate", ts=TS, best="winner", alphas=[["winner", "h1", True, 1.8, 0.8, []]]))
    assert card()["value"] == 1
    assert card()["message"] == "最近：winner Sharpe 1.80"
    state.feed(line("evaluate", ts=TS+2, best=None, alphas=[["other", "h2", False, 0.1, 0.2, ["sharpe"]]]))
    assert card()["value"] == 1
    assert card()["message"] == "最近一批无通过"
    state.feed(line("evaluate", ts=TS+1, best="late", alphas=[["late", "h3", True, 1.5, 0.8, []]]))
    assert card()["message"] == "最近一批无通过"
    state.close()


def test_card_metrics_hide_float_artifacts_without_rounding_snapshot_values():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("evaluate", best="LIVE0077", alphas=[
            ["LIVE0077", "h1", True, 1.8000000000000003, 0.4000000000000001, []]]))
        state.feed(line("prod", ts=TS+1, alpha="LIVE0077", prod=0.6000000000000001))
        snap = state.snapshot("live")
        cards = {card["key"]: card for card in snap["cards"]}
        assert cards["evaluate"]["message"] == "最近：LIVE0077 Sharpe 1.80"
        assert cards["prod"]["message"] == "LIVE0077 Prod 0.60"
        assert snap["alphas"][0]["sharpe"] == 1.8000000000000003
        assert snap["alphas"][0]["prod"] == 0.6000000000000001
    finally:
        state.close()


@pytest.mark.parametrize(("prod", "kind", "display"), [
    (0.6000000000000001, "prod_ok", "0.60"),
    (0.7999999999999999, "prod_block", "0.80"),
    (0.0, "prod_ok", "0.00"),
])
def test_prod_event_and_card_use_two_decimal_places(prod, kind, display):
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("prod", alpha="alpha", prod=prod))
        snap = state.snapshot("live")
        assert snap["events"][-1]["kind"] == kind
        assert snap["events"][-1]["text"] == f"alpha Prod {display}"
        assert next(c for c in snap["cards"] if c["key"] == "prod")["message"] == f"alpha Prod {display}"
    finally:
        state.close()


def test_missing_metric_messages_keep_a_placeholder():
    state = FactoryState(DAY, clock=lambda: TS+10)
    try:
        state.feed(line("evaluate", best="alpha", alphas=[["alpha", "h", True, None, None, []]]))
        state.feed(line("prod", ts=TS+1, alpha="alpha", prod=None, err="no data"))
        cards = {card["key"]: card for card in state.snapshot("live")["cards"]}
        assert cards["evaluate"]["message"] == "最近：alpha Sharpe —"
        assert cards["prod"]["message"] == "alpha Prod ?"
    finally:
        state.close()
