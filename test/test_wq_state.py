"""Whole WQ-window aggregates, including DST and bounded historical storage."""

from datetime import date, datetime
import json

import pytest

from SpiderPanel.state import FactoryState
from SpiderPanel.wq_day import wq_window
from test_state import DAY, TS, line


@pytest.mark.parametrize("day, buckets", [(date(2026, 3, 8), 92),
                                        (DAY, 96), (date(2026, 11, 1), 100)])
def test_timeline_starts_at_wq_midnight_and_spans_the_actual_dst_window(day, buckets):
    window = wq_window(day)
    state = FactoryState(day, clock=lambda: window.end+1)
    try:
        # No truncation of the first or last hour on the 25-hour autumn day.
        for offset, aid in ((1801, "early"), (window.end-window.start-1, "last")):
            state.feed(line("result", ts=window.start+offset, sim=aid, status="completed",
                            dur=offset, alphas=[[aid, aid, 1.2, .8, .2]]))
        snapshot = state.snapshot("replay")
        assert len(snapshot["timeline"]) == buckets
        assert datetime.fromisoformat(snapshot["timeline"][0]["t"]).timestamp() == window.start
        assert snapshot["timeline"][0]["sims_done"] == 0
        assert snapshot["timeline"][2]["sims_done"] == 1
        assert snapshot["timeline"][-1]["sims_done"] == 1
        assert datetime.fromisoformat(snapshot["wq_start"]).timestamp() == window.start
        assert datetime.fromisoformat(snapshot["wq_next_reset"]).timestamp() == window.end
    finally:
        state.close()


def test_window_filter_applies_to_every_daily_stat_and_ignores_rows_quietly():
    state = FactoryState(DAY, clock=lambda: TS+86400)
    try:
        for ts in (state.start-1, state.end):
            for row in (line("precheck", ts=ts, status="fail"),
                        line("simulate", ts=ts, status="submitted", exprs=[["h", "rank(close)"]]),
                        line("result", ts=ts, status="completed", dur=900, alphas=[["h", "outside", 9, 2, .2]]),
                        line("evaluate", ts=ts, alphas=[["outside", "h", False, 9, 2, ["sharpe"]]]),
                        line("prod", ts=ts, alpha="outside", prod=.99),
                        line("save", ts=ts, alpha="outside", saved=True)):
                state.feed(row)
        state.feed(line("result", ts=state.start, sim="inside", status="completed", dur=50,
                        alphas=[["h", "inside", 1.8, .8, .2]]))
        state.feed(line("evaluate", ts=state.end-.1, alphas=[["inside", "h", True, 1.8, .8, []]]))
        snapshot = state.snapshot("replay")
        assert state.bad_lines == 0 and state.calls == 2
        assert snapshot["totals"]["sessions_total"] == 1
        assert snapshot["totals"]["sims_done"] == 1 and snapshot["totals"]["exprs"] == 0
        assert snapshot["best"]["id"] == "inside"
        assert snapshot["review"] == [] and snapshot["sim_typical_seconds"] == 50
        assert not any(snapshot["rejects"].values())
        assert "fail_reasons" not in snapshot and "prod_stats" not in snapshot
        assert next(card for card in snapshot["cards"] if card["key"] == "prod")["value"] == 0
        assert snapshot["sessions_ended"] == 0
        assert state.revision < 10
    finally:
        state.close()


def test_future_replay_cache_refreshes_when_first_wq_bucket_begins(tmp_path):
    from SpiderPanel.server import PanelRuntime
    window = wq_window(DAY)
    now = [window.start-1]
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: now[0])
    try:
        first, payload = runtime.payload()
        assert json.loads(payload)["timeline"] == []
        now[0] = window.start+1
        runtime.poll()
        key, payload = runtime.payload()
        assert first != key
        assert len(json.loads(payload)["timeline"]) == 1
    finally:
        runtime.close()
