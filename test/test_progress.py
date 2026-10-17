"""Read the simulator registry without importing or touching its writer."""

import json

import pytest

from SpiderPanel import rules
from SpiderPanel.server import PanelRuntime
from test_server import append
from test_state import DAY, TS, line


def write(path, runs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "runs": runs}))


def run(sim="sim", progress=.375):
    return {"multisimulation_location": f"https://example.invalid/simulations/{sim}/",
            "status": "running", "progress": progress,
            "children": [f"https://example.invalid/simulations/c{i}" for i in range(8)],
            "submitted_at": "2026-10-15T12:00:00+08:00", "last_checked_at": "2026-10-15T12:00:30+08:00"}


def test_registry_progress_matches_sim_id_without_changing_aggregates(tmp_path):
    from SpiderPanel.progress import load_progress
    path = tmp_path / "progress.json"
    write(path, [run()])
    assert load_progress(path) == {"sim": {"progress": .375, "children_done": 3, "children_total": 8}}
    append(tmp_path, DAY, line("simulate", status="submitted", sim="sim", exprs=[["h", "rank(close)"]]))
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: TS+10, progress_path=path)
    try:
        runtime.poll()
        snap = runtime.snapshot()
        assert snap["pending_sims"][0]["progress"] == .375
        assert snap["pending_sims"][0]["children_done"] == 3
        assert snap["pending_sims"][0]["children_total"] == 8
        assert snap["totals"]["exprs"] == 1 and len(snap["events"]) == 1
    finally:
        runtime.close()


@pytest.mark.parametrize("content", [None, "{", "[]", '{"version":2,"runs":[]}',
                                    '{"version":1,"runs":null}', b"\xff"])
def test_missing_bad_or_partial_registry_is_silent_and_uses_fallback(tmp_path, capsys, content):
    from SpiderPanel.progress import load_progress
    path = tmp_path / "bad.json"
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif content is not None:
        path.write_text(content)
    assert load_progress(path) is None
    append(tmp_path, DAY, line("simulate", status="submitted", sim="sim", exprs=[]))
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: TS+10, progress_path=path)
    try:
        runtime.poll()
        assert runtime.snapshot()["pending_sims"][0]["progress"] is None
        captured = capsys.readouterr()
        assert captured.out == captured.err == ""
    finally:
        runtime.close()


def test_progress_is_polled_every_five_seconds_and_invalidates_sse_cache(tmp_path):
    now = [TS]
    path = tmp_path / "progress.json"
    write(path, [run(progress=.25)])
    append(tmp_path, DAY, line("simulate", status="submitted", sim="sim", exprs=[]))
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: now[0], progress_path=path)
    try:
        runtime.poll()
        key, _ = runtime.payload()
        write(path, [run(progress=.75)])
        now[0] += 4
        runtime.poll()
        assert runtime.snapshot()["pending_sims"][0]["progress"] == .25
        now[0] += 1
        runtime.poll()
        changed, _ = runtime.payload()
        assert changed != key
        assert runtime.snapshot()["pending_sims"][0]["progress"] == .75
        assert runtime.snapshot()["pending_sims"][0]["children_done"] == 6
        path.unlink()
        now[0] += 5
        runtime.poll()
        assert runtime.snapshot()["pending_sims"][0]["progress"] is None
    finally:
        runtime.close()


def test_registry_unknown_and_malformed_entries_do_not_claim_progress(tmp_path):
    from SpiderPanel.progress import load_progress
    path = tmp_path / "progress.json"
    write(path, [None, {}, run("unknown", None), run("bad", "0.5"), run("outside", 2),
                 {**run("nochildren", .5), "children": None}])
    data = load_progress(path)
    assert data["unknown"] == {"progress": None, "children_done": None, "children_total": 8}
    assert data["bad"]["progress"] is None and data["outside"]["progress"] is None
    assert data["nochildren"] == {"progress": .5, "children_done": None, "children_total": None}


def test_configured_source_is_read_only_and_demo_ignores_it(tmp_path):
    registry = tmp_path / "sources/progress.json"
    write(registry, [run()])
    original = registry.read_bytes()
    live = PanelRuntime(tmp_path / "live", progress_path=registry)
    demo = PanelRuntime(tmp_path / "demo", mode="demo", progress_path=registry)
    try:
        assert live.progress_path == registry
        assert demo.progress_path == tmp_path / "demo/multi_simulation_progress.json"
        live.poll();demo.poll()
        assert registry.read_bytes() == original
        assert list(registry.parent.iterdir()) == [registry]
    finally:
        live.close();demo.close()


def test_unconfigured_sources_are_never_read(tmp_path, monkeypatch):
    from SpiderPanel import server
    def unexpected(*args):
        pytest.fail("未配置时不应读取辅助数据源")
    monkeypatch.setattr(server, "load_progress", unexpected)
    monkeypatch.setattr(server, "load_candidate_expressions", unexpected)
    runtime = PanelRuntime(tmp_path, day=DAY, clock=lambda: TS+10)
    try:
        assert runtime.progress_path is None and runtime.candidate_paths == ()
        runtime.poll()
        assert runtime.snapshot()["pending_sims"] == []
    finally:
        runtime.close()
