"""Demo calls use the collector's two phases and an isolated progress registry."""

from collections import defaultdict
from datetime import datetime
import json

from SpiderPanel.demo import DemoFeeder
from SpiderPanel.progress import load_progress
from SpiderPanel.server import PanelRuntime
from SpiderPanel.state import FactoryState
from SpiderPanel.wq_day import wq_day


PUBLIC = {"v", "ts", "t", "role", "pid", "ppid", "agent", "ph"}
PARAMS = {"simulate": {"n"}, "precheck": {"n"}, "result": {"sim"},
          "evaluate": {"sim"}, "prod": {"alpha"}, "save": {"alpha"}}


def call_key(row):
    return row["pid"], row["t"], row.get("sim") if row["role"] in ("result", "evaluate") else row.get("alpha")


def test_demo_history_and_live_calls_pair_and_show_all_inflight_phases(tmp_path):
    now = [datetime(2026, 10, 15, 15).timestamp()]
    root = tmp_path / "demo"
    feeder = DemoFeeder(root / "log", clock=lambda: now[0])
    feeder.seed_history()
    state = FactoryState(wq_day(feeder.clock()), clock=feeder.clock)
    path = root / "log" / "2026-10-15.jsonl"
    position = 0
    calls, phases, kinds = defaultdict(list), set(), set()
    try:
        for second in range(61):
            if second:
                now[0] += 1
            feeder.tick()
            with path.open() as stream:
                stream.seek(position)
                for raw in stream:
                    row = json.loads(raw)
                    assert PUBLIC <= row.keys()
                    key = call_key(row)
                    if row["ph"] == "start":
                        assert row.keys() == PUBLIC | PARAMS[row["role"]]
                        calls[key].append(row["ts"])
                    else:
                        assert row["ph"] == "end" and calls[key], row
                        # Independent demo jobs can overlap in one session;
                        # match their intervals rather than assuming FIFO ends.
                        started = row["ts"]-row["dur"]
                        assert started in calls[key], row
                        calls[key].remove(started)
                    state.feed(row)
                position = stream.tell()
            snap = state.snapshot("demo")
            phases.update(session["phase"] for session in snap["sessions"])
            kinds.update(event["kind"] for event in snap["events"])
        assert state.bad_lines == 0
        assert phases >= {"thinking", "simulating", "evaluating", "prod", "saving"}
        assert kinds >= {"sim_submit_start", "eval_start", "prod_start", "save_start"}
        assert len(state.snapshot("demo")["sessions"]) == 4
    finally:
        state.close()


def test_demo_registry_changes_only_in_its_own_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "demo"
    registry = tmp_path / "sources/multi_simulation_progress.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("unchanged")
    now = [datetime(2026, 10, 15, 15).timestamp()]
    feeder = DemoFeeder(root / "log", clock=lambda: now[0])
    runtime = PanelRuntime(root, mode="demo", progress_path=registry, candidate_paths=(registry,), clock=lambda: now[0],
                           today=lambda: datetime.fromtimestamp(now[0]).date())
    try:
        feeder.tick()
        now[0] += 1
        feeder.tick()
        runtime.poll()
        first = runtime.snapshot()["pending_sims"][0]
        assert first["progress"] == 0 and first["children_total"] == 8
        assert feeder.progress_path == runtime.progress_path == root / registry.name
        now[0] += 3
        feeder.tick()
        progress = load_progress(feeder.progress_path)[first["sim"]]
        assert 0 < progress["progress"] < 1
        assert progress["children_done"] > 0
        now[0] += 2
        feeder.tick()
        runtime.poll()
        assert first["sim"] not in load_progress(feeder.progress_path)
        assert registry.read_text() == "unchanged"
        assert not (tmp_path / "home/.wq_spider").exists()
        assert {p.parent for p in root.rglob("*") if p.is_file()} <= {root, root / "log"}
    finally:
        runtime.close()


def test_demo_inflight_signals_reach_the_scene_during_the_thirty_second_story(tmp_path):
    from test_ongoing_work import CLOCK
    from test_scene_r1 import scene_check

    now = [datetime(2026, 10, 15, 15).timestamp()]
    start = now[0]
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: now[0])
    feeder.seed_history()
    runtime = PanelRuntime(tmp_path, mode="demo", clock=feeder.clock,
                           today=lambda: datetime.fromtimestamp(feeder.clock()).date())
    snapshots = []
    try:
        for second in range(31):
            now[0] = start+second
            feeder.tick()
            runtime.poll()
            snapshots.append(runtime.snapshot())
    finally:
        runtime.close()
    path = tmp_path / "snapshots.json"
    path.write_text(json.dumps(snapshots))
    scene_check(CLOCK + f"const snapshots=JSON.parse((await import('node:fs')).readFileSync({json.dumps(str(path))},'utf8'));\n" + r"""
      const seen=new Set();let previous=null,maxStep=0;
      for(const snapshot of snapshots){
        scene.update(snapshot);
        for(let frame=0;frame<50;frame++){
          advance(20);
          if(scene.work.inspectionBeam)seen.add('inspection');
          if(scene.work.prodPulse)seen.add('prod');
          if(scene.work.savePreviews.size)seen.add('writing');
          if([...scene.work.batchColumns.values()].some(column=>column.g.getAttribute('data-progress-source')==='actual'
              &&column.cells.some(cell=>cell.getAttribute('data-lit')==='true')))seen.add('progress');
          if([...scene.sessionNodes.values()].some(entry=>entry.workThinking))seen.add('thinking');
          const position=scene.spider.positionSurface.positionAt(now);
          if(previous)maxStep=Math.max(maxStep,Math.hypot(position.x-previous.x,position.y-previous.y));
          previous=position;
          assert.ok(scene.layers.promotions.size<=22);assert.ok(doc.frames.size<=1);
        }
      }
      assert.deepEqual([...seen].sort(),['inspection','prod','progress','thinking','writing']);
      assert.ok(maxStep<=12,'Work/result handoffs use the visible continuous position');
    """)
