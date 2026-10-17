"""Synthetic daily summaries written only to the explicitly supplied directory."""

from datetime import datetime
import heapq
import json
import os
from pathlib import Path
import random
import threading
import time

from .extract import expression_hash
from . import rules
from .wq_day import wq_window


TOOLS = {"simulate": "wqb_create_multi_simulation", "result": "local_wait_multi_simulation",
         "evaluate": "evaluate_simulation_alphas", "prod": "check_alpha_prod_correlation",
         "save": "save_candidate_alpha", "precheck": "check_expression_group_diversity"}
SESSIONS = {4101: ("USA", "TOP3000"), 4102: ("ASI", "TOP500"), 4103: ("EUR", "TOP2500"),
            4104: ("USA", "TOP3000")}
ONBOARDING_SECONDS = 28
AGENTS = {4101: "codex", 4102: "kimi3", 4103: "agent_demo", 4104: "claude"}


class DemoFeeder:
    def __init__(self, log_dir, clock=time.time):
        self.log_dir = Path(log_dir)
        # During the first three hours of a WQ day, use the previous WQ day
        # with a fixed three-hour clock offset so the seed is entirely history.
        actual = clock()
        offset = 3*3600 if actual-wq_window(now=actual).start < 3*3600 else 0
        self.clock = lambda: clock()-offset
        self.random = random.Random(71)
        self.stop_event = threading.Event()
        self.thread = None
        self._seeded = False
        self._start = self.clock()
        self.window = wq_window(now=self._start)
        self._counter = 0
        self._queue_seq = 0
        self._queue = []
        self._onboarding_cycle = None
        self._scripted_pending = {}
        self._scripted_calls = []
        self.progress_path = self.log_dir.parent / "multi_simulation_progress.json"
        self._progress_runs = {}
        self._deadlines = {}
        self._next = {4101: self._start+31, 4102: self._start+33}
        self._lock = threading.Lock()

    def _row(self, role, ts, pid, **fields):
        return {"v": rules.LOG_VERSION, "ts": int(ts), "t": TOOLS[role], "role": role,
                "ph": "end", "ok": True, "dur": 0.0, "pid": pid,
                "ppid": pid, "agent": AGENTS[pid], **fields}

    @staticmethod
    def _key(row):
        subject = row.get("sim") if row["role"] in ("result", "evaluate") else row.get("alpha")
        return row["pid"], row["t"], subject

    @staticmethod
    def _start_row(end, ts):
        start = {key: end[key] for key in ("v", "t", "role", "pid", "ppid", "agent")}
        start.update(ts=int(ts), ph="start")
        role = end["role"]
        if role in ("simulate", "precheck"):
            start["n"] = len(end["exprs"]) if "exprs" in end else end.get("n", 0)
        elif role in ("result", "evaluate"):
            start["sim"] = end.get("sim")
        else:
            start["alpha"] = end.get("alpha")
        return start

    def _pairs(self, ends, floor=None):
        """Give each synthetic call a real interval, using parameter-only starts."""
        rows, submitted, results, previous = [], {}, {}, {}
        for end in sorted(ends, key=lambda row: row["ts"]):
            role, ts = end["role"], end["ts"]
            if role == "result":
                since = submitted.get(end.get("sim"), ts-1)+1
                results[end.get("sim")] = ts
                self._deadlines[end["sim"]] = ts
            elif role == "evaluate":
                since = max(results.get(end.get("sim"), ts-8)+1, ts-7)
            else:
                since = ts-{"precheck": 1, "simulate": 1, "prod": 3, "save": 4}[role]
            key = (end["pid"], end["t"])
            since = min(ts, max(since, previous.get(key, since), floor if floor is not None else since))
            start = self._start_row(end, since)
            end["dur"] = float(ts-start["ts"])
            rows.extend((start, end))
            previous[key] = ts
            if role == "simulate" and end.get("status") == "submitted":
                submitted[end["sim"]] = ts
        return sorted(rows, key=lambda row: row["ts"])

    def _batch(self, ts, pid, scale=1, *, floor=None):
        return self._pairs(self._batch_ends(ts, pid, scale), floor=floor)

    def _batch_ends(self, ts, pid, scale=1):
        self._counter += 1
        batch = self._counter
        rows = []
        if self.random.random() < 0.05:
            return [self._row("precheck", ts, pid, status="fail", n=8)]
        rows.append(self._row("precheck", ts, pid, status="pass", n=8))
        region, universe = SESSIONS[pid]
        sim = f"DEMO_SIM_{pid}_{batch}"
        if self.random.random() < 0.02:
            rows.append(self._row("simulate", ts+1/scale, pid, status="validation_failed", sim=None,
                                  n=8, err="DEMO 表达式组检查未通过", ok=False,
                                  region=region, universe=universe, delay=1))
            return rows
        fields = ("close", "volume", "returns", "vwap", "cap", "high", "low", "close")
        exprs = [[expression_hash(expr), expr] for expr in (
            f"rank(ts_delta({field}, {5+(batch+i)%25}))" for i, field in enumerate(fields))]
        rows.append(self._row("simulate", ts+1/scale, pid, status="submitted", sim=sim,
                              exprs=exprs, region=region, universe=universe, delay=1))
        done = ts+self.random.uniform(30, 90)/scale
        if self.random.random() < 0.06:
            rows.append(self._row("result", done, pid, sim=sim, status="failed", alphas=[],
                                  err="DEMO 回测失败", ok=False))
            return rows
        alphas, evaluations = [], []
        passed_alphas = []
        for i, (h, _) in enumerate(exprs):
            aid = f"DEMO{pid}_{batch:04}_{i}"
            passed = self.random.random() < 0.065
            sharpe = round(self.random.uniform(1.3, 2.2) if passed else max(-1, min(1.2, self.random.gauss(0.2, 0.5))), 4)
            fitness = round(self.random.uniform(0.65, 1.4) if passed else self.random.uniform(-0.3, 0.6), 4)
            turnover = round(self.random.uniform(0.04, 0.65), 4)
            alphas.append([h, aid, sharpe, fitness, turnover])
            evaluations.append([aid, h, passed, sharpe, fitness, [] if passed else ["sharpe", "fitness"]])
            if passed:
                passed_alphas.append((aid, sharpe))
        best = max(passed_alphas, key=lambda item: item[1])[0] if passed_alphas else None
        rows.append(self._row("result", done, pid, sim=sim, status="completed", alphas=alphas))
        rows.append(self._row("evaluate", done+6/scale, pid, sim=sim, alphas=evaluations, best=best))
        for i, (aid, _) in enumerate(passed_alphas):
            if self.random.random() < 0.65:
                prod = round(self.random.uniform(0.15, 0.95), 4)
                stamp = done+(12+i)/scale
                rows.append(self._row("prod", stamp, pid, alpha=aid, prod=prod))
                if prod < rules.PROD_LIMIT and self.random.random() < 0.6:
                    saved = self.random.random() > 0.08
                    rows.append(self._row("save", stamp+6/scale, pid, alpha=aid, passed=saved, saved=saved))
        return rows

    def _onboarding(self, cycle):
        """Each 28-second cycle gives a newly opened page a full live story."""
        start, pid = self._start+cycle*ONBOARDING_SECONDS, 4101
        suffix = f"_C{cycle}" if cycle else ""
        sim = f"DEMO_SIM_ONBOARD_MAIN{suffix}"
        failed_sim = f"DEMO_SIM_ONBOARD_FAILED{suffix}"
        expressions = ["rank(ts_delta(close, 12))", "rank(ts_delta(volume, 7))",
                       "rank(ts_delta(vwap, 18))", "rank(ts_delta(returns, 9))",
                       "rank(ts_delta(high, 6))", "rank(ts_delta(low, 14))",
                       "rank(ts_delta(cap, 21))", "rank(ts_delta(close, 26))"]
        exprs = [[expression_hash(expr), expr] for expr in expressions]
        metrics = [(1.82, 1.10, 0.22), (0.31, 0.18, 0.43),
                   (1.63, 0.92, 0.29), (1.51, 0.84, 0.31),
                   (0.47, 0.23, 0.38), (-0.16, -0.08, 0.51),
                   (0.72, 0.36, 0.27), (0.25, 0.14, 0.45)]
        alphas = [[h, f"DEMO_ONBOARD_{i}{suffix}", *metrics[i]] for i, (h, _) in enumerate(exprs)]
        rows = [self._row("precheck", start, pid, status="pass", n=8),
                self._row("simulate", start+1, pid, status="submitted", sim=sim, exprs=exprs,
                          region="USA", universe="TOP3000", delay=1),
                self._row("precheck", start+3, 4102, status="pass", n=1),
                self._row("simulate", start+4, 4102, status="submitted", sim=failed_sim,
                          exprs=[[expression_hash("rank(ts_delta(volume, 13))"), "rank(ts_delta(volume, 13))"]],
                          region="ASI", universe="TOP500", delay=1),
                self._row("result", start+6, pid, sim=sim, status="completed", alphas=alphas)]
        # Give inspection time to reach the first alpha. Keep the blocked
        # alpha's Prod outcome before the next evaluation to avoid a return trip.
        for i, second in ((0, 15), (1, 16), (2, 17), (3, 21)):
            h, aid, sharpe, fitness, _ = alphas[i]
            passed = i != 1
            rows.append(self._row("evaluate", start+second, pid, sim=sim, best=aid if passed else None,
                                  alphas=[[aid, h, passed, sharpe, fitness,
                                           [] if passed else ["sharpe", "fitness"]]]))
        rows.extend([
            self._row("prod", start+20, pid, alpha=alphas[2][1], prod=0.84),
            self._row("prod", start+23, pid, alpha=alphas[0][1], prod=0.42),
            self._row("save", start+26, pid, alpha=alphas[0][1], passed=True, saved=True),
            self._row("prod", start+25, pid, alpha=alphas[3][1], prod=0.55),
            self._row("save", start+27, pid, alpha=alphas[3][1], passed=False, saved=False),
            self._row("result", start+27, 4102, sim=failed_sim, status="failed",
                      alphas=[], err="DEMO 回测失败", ok=False),
            self._row("precheck", start+3, 4102, status="fail", n=8),
        ])
        return self._pairs(rows, floor=start)

    def _append(self, row, scripted=False):
        data = json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        if len(data) > rules.MAX_LINE_BYTES:
            raise ValueError("demo summary exceeds tracker byte budget")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"{datetime.fromtimestamp(row['ts']).date().isoformat()}.jsonl"
        with self._lock:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                if os.write(fd, data) != len(data):
                    raise OSError("incomplete demo append")
            finally:
                os.close(fd)
        if scripted:
            if row["ph"] == "start":
                self._scripted_calls.append(row)
            else:
                key = self._key(row)
                match = next((i for i, call in enumerate(self._scripted_calls) if self._key(call) == key), None)
                if match is not None:
                    self._scripted_calls.pop(match)
        sim = row.get("sim")
        if row["ph"] == "end" and sim:
            if row["role"] == "simulate" and row.get("status") == "submitted":
                stamp = datetime.fromtimestamp(row["ts"]).astimezone().isoformat()
                self._progress_runs[sim] = {
                    "multisimulation_location": f"https://demo.invalid/simulations/{sim}",
                    "status": "RUNNING", "progress": 0.0,
                    "children": [f"https://demo.invalid/simulations/{sim}_{i}" for i in range(len(row.get("exprs", [])))],
                    "submitted_at": stamp, "last_checked_at": stamp, "_ts": row["ts"]}
            elif row["role"] == "result" and row.get("status") in ("completed", "failed"):
                self._progress_runs.pop(sim, None)
                self._deadlines.pop(sim, None)
        if row["ph"] == "end" and sim and sim.startswith("DEMO_SIM_ONBOARD_"):
            if row["role"] == "simulate" and row.get("status") == "submitted":
                self._scripted_pending[sim] = row["pid"]
            elif row["role"] == "result" and row.get("status") in ("completed", "failed"):
                self._scripted_pending.pop(sim, None)

    def _write_progress(self, now):
        runs = []
        for sim, run in self._progress_runs.items():
            since, deadline = run["_ts"], self._deadlines.get(sim)
            progress = max(0.0, min(.95, (now-since)/max(1, deadline-since))) if deadline is not None else None
            runs.append({**{key: value for key, value in run.items() if key != "_ts"},
                         "progress": progress,
                         "last_checked_at": datetime.fromtimestamp(now).astimezone().isoformat()})
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.progress_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"version": 1, "runs": runs}, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.progress_path)

    def _close_scripted(self, now):
        # A skipped story must not leave an orphan start or a permanent batch.
        for sim, pid in tuple(self._scripted_pending.items()):
            key = (pid, TOOLS["result"], sim)
            if not any(self._key(call) == key for call in self._scripted_calls):
                end = self._row("result", now, pid, sim=sim)
                self._append(self._start_row(end, now), scripted=True)
        for call in tuple(self._scripted_calls):
            role = call["role"]
            fields = {key: call[key] for key in ("sim", "alpha", "n") if key in call}
            fields.update(ok=False, dur=float(int(now)-call["ts"]),
                          err="DEMO 时钟跳跃，结束过期演示回测" if role == "result" else "DEMO 时钟跳跃，结束过期演示调用")
            if role == "result":
                fields.update(status="failed", alphas=[])
            elif role == "simulate":
                fields.update(status="validation_failed", sim=None)
            elif role == "precheck":
                fields["status"] = "fail"
            elif role == "evaluate":
                fields.update(alphas=[], best=None)
            elif role == "prod":
                fields["prod"] = None
            else:
                fields.update(passed=False, saved=False)
            self._append(self._row(role, now, call["pid"], **fields), scripted=True)

    def seed_history(self):
        if self._seeded:
            return
        now = self._start
        rows = []
        for i, pid in enumerate((4101, 4102, 4103)):
            ts = max(self.window.start, now-3*3600)+i*45
            end = now-rules.IDLE_SECONDS-90 if pid == 4103 else now-120
            while ts < end:
                rows.extend(row for row in self._batch(ts, pid, floor=self.window.start)
                            if self.window.start <= row["ts"] <= now and row["ts"] < self.window.end)
                ts += self.random.uniform(6*60, 10*60)
            if pid == 4103:
                # This session stops here and turns idle during live playback.
                rows.extend(self._pairs([self._row("precheck", now-rules.IDLE_SECONDS+30, pid, status="pass", n=8)],
                                        floor=self.window.start))
        for row in sorted(rows, key=lambda row: row["ts"]):
            self._append(row)
        self._seeded = True
        self._write_progress(now)

    def tick(self):
        now = self.clock()
        cycle = max(0, int((now-self._start)//ONBOARDING_SECONDS))
        if cycle != self._onboarding_cycle:
            self._close_scripted(now)
            # A clock jump skips old stories instead of replaying their backlog.
            for _, _, row, old_cycle in self._queue:
                if old_cycle is not None and row["role"] == "result":
                    self._deadlines.pop(row.get("sim"), None)
            self._queue = [entry for entry in self._queue if entry[3] is None]
            heapq.heapify(self._queue)
            for row in self._onboarding(cycle):
                self._queue_seq += 1
                heapq.heappush(self._queue, (row["ts"], self._queue_seq, row, cycle))
            self._onboarding_cycle = cycle
        if now-self._start >= 60 and 4104 not in self._next:
            self._next[4104] = now
        for pid, next_time in list(self._next.items()):
            if now >= next_time:
                for row in self._batch(now, pid, scale=6):
                    self._queue_seq += 1
                    heapq.heappush(self._queue, (row["ts"], self._queue_seq, row, None))
                self._next[pid] = now+self.random.uniform(6, 10)
        while self._queue and self._queue[0][0] <= now:
            _, _, row, scripted_cycle = heapq.heappop(self._queue)
            self._append(row, scripted=scripted_cycle is not None)
        self._write_progress(now)

    def start(self):
        self.seed_history()
        self.thread = threading.Thread(target=self._run, name="factory-demo", daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            self.tick()
            self.stop_event.wait(1)

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=3)
