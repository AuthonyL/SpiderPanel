"""Daily factory aggregation. The HTTP runtime owns the synchronization lock."""

from collections import Counter, OrderedDict, deque
from datetime import datetime
from heapq import heappush, heappushpop
from itertools import chain, islice
import math
import time

from . import rules
from .archive import Archive, qualified
from .thresholds import load_thresholds
from .wq_day import wq_window


ROLES = {"simulate", "result", "evaluate", "prod", "save", "precheck"}
SHAPES = ("ghost", "square", "circle", "hexagon", "triangle", "blob")
COLORS = ("#e8ecf4", "#ff4d5e", "#4f7cff", "#ffab2e", "#ff5fa2", "#3ddc84")
PHASES = {"simulate": ("submitting", "提交中"), "result": ("simulating", "等回测"),
          "evaluate": ("evaluating", "评估中"), "prod": ("prod", "查相关性"),
          "save": ("saving", "存候选"), "precheck": ("precheck", "预检中")}
INFLIGHT_KEEP = 64
STAGES = {"done": 1, "eval_failed": 2, "eval_passed": 2, "prod_blocked": 3,
          "prod_ok": 3, "rejected": 4, "candidate": 5}
ALPHA_FIELDS = ("id", "h", "expr", "sim", "pid", "sharpe", "fitness", "turnover",
                "passed", "failed", "prod", "status", "best", "ts")


def iso(ts):
    return datetime.fromtimestamp(ts).astimezone().isoformat()


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except (ValueError, OverflowError):
        return None


def format_metric(value, missing="—"):
    value = number(value)
    return missing if value is None else f"{value:.2f}"


def _valid(line):
    if not isinstance(line, dict) or not isinstance(line.get("role"), str) or line["role"] not in ROLES:
        return False
    if number(line.get("ts")) is None or line.get("v", 1) != 1:
        return False
    if line.get("ph") not in (None, "start", "end"):
        return False
    try:
        iso(line["ts"])
    except (ValueError, OverflowError, OSError):
        return False
    if type(line.get("pid", 0)) is not int or line.get("pid", 0) < 0:
        return False
    if line.get("ppid") is not None and (type(line["ppid"]) is not int or line["ppid"] < 0):
        return False
    for key in ("ok", "saved", "passed"):
        if line.get(key) is not None and type(line[key]) is not bool:
            return False
    for key in ("t", "status", "sim", "alpha", "err", "region", "universe", "best", "agent"):
        if line.get(key) is not None and not isinstance(line[key], str):
            return False
    if line.get("delay") is not None and type(line["delay"]) is not int:
        return False
    if line.get("prod") is not None and number(line["prod"]) is None:
        return False
    if line.get("ph") == "start":
        return bool(line.get("t")) and (line.get("n") is None or
                (type(line["n"]) is int and line["n"] >= 0))
    role = line["role"]
    key, width = ("exprs", 2) if role == "simulate" else ("alphas", 5 if role == "result" else 6)
    if role in ("simulate", "result", "evaluate"):
        rows = line.get(key, [])
        if not isinstance(rows, list):
            return False
        for row in rows:
            if not isinstance(row, list) or len(row) != width:
                return False
            if any(v is not None and not isinstance(v, str) for v in row[:2]):
                return False
            if role == "result" and any(v is not None and number(v) is None for v in row[2:]):
                return False
            if role == "evaluate":
                if row[2] is not None and type(row[2]) is not bool:
                    return False
                if any(v is not None and number(v) is None for v in row[3:5]):
                    return False
                if not isinstance(row[5], list) or any(not isinstance(v, str) for v in row[5]):
                    return False
    if line.get("ok", True) is not False:
        if role == "precheck" and line.get("status") not in ("pass", "fail"):
            return False
        if role in ("prod", "save") and not line.get("alpha"):
            return False
        if role == "result" and line.get("status") not in ("completed", "pending", "failed"):
            return False
        if role == "simulate" and not line.get("status"):
            return False
    return True


class FactoryState:
    def __init__(self, day, clock=time.time, *, thresholds=None, daily_goal=rules.DAILY_CANDIDATE_GOAL):
        self.day, self.clock = day, clock
        self.revision = self.bad_lines = 0
        self.alphas = OrderedDict()
        self.sims = OrderedDict()
        self.sessions = OrderedDict()
        self.expressions = OrderedDict()
        self.events = deque(maxlen=rules.EVENTS_KEEP)
        self.thresholds = load_thresholds(thresholds)
        self.daily_goal = daily_goal if type(daily_goal) is int and daily_goal > 0 else rules.DAILY_CANDIDATE_GOAL
        self.rejects = dict.fromkeys(("precheck_fail", "create_fail", "sim_fail", "eval_fail",
                                     "prod_blocked", "save_rejected", "tool_error"), 0)
        self.counts = dict.fromkeys(("exprs", "sims_done", "alphas", "eval_passed", "candidates"), 0)
        self.calls = self.submits = self.evaluated = self.prod_checks = self.prod_ok_checks = self.prod_good = 0
        self._session_count = self._seq = self._order = 0
        self._session_index = 0
        self._parent_aliases = OrderedDict()
        self._first = None
        self._archive = Archive()
        self._buckets = {}
        self._last = {}
        self._roles = {}
        self._sim_durations = []
        self._qualified_cache = None
        self._temporal = None
        window = wq_window(day)
        self.start, self.end = window.start, window.end
        self._midnight = self.start
        self._bucket_count = math.ceil((self.end-self.start) / rules.TIMELINE_BUCKET_SECONDS)

    def _stamp(self, key, ts, text):
        if ts >= self._last.get(key, (-math.inf, ""))[0]:
            self._last[key] = (ts, text)

    def _event(self, kind, ts, pid, text, alpha=None, *, sim=None, n=None, alphas=None, exprs=None):
        self._seq += 1
        event = {"seq": self._seq, "ts": iso(ts), "kind": kind, "pid": pid,
                 "text": text[:500], "alpha": alpha}
        if sim:
            event["sim"] = sim
        if n is not None:
            event["n"] = n
        if alpha and kind in ("eval_pass", "eval_fail", "prod_ok", "prod_block", "candidate", "rejected"):
            alphas = (alpha,)
        if alphas is not None:
            event["alphas"] = list(islice((aid for aid in alphas if isinstance(aid, str) and aid), 8))
        if exprs is not None:
            event["exprs"] = list(islice((expr[:24] for expr in exprs if isinstance(expr, str)), 8))
        self.events.append(event)

    def _bucket(self, ts):
        index = max(0, min(self._bucket_count-1, int((ts - self.start) // rules.TIMELINE_BUCKET_SECONDS)))
        if index not in self._buckets:
            self._buckets[index] = {"sims_done": 0, "alphas": 0, "eval_passed": 0,
                                    "candidates": 0, "best_sharpe": None}
        return self._buckets[index]

    def _session(self, pid, ts, role, line):
        if pid not in self.sessions:
            retired = self._archive.pop("session", pid)
            if retired is not None:
                self.sessions[pid] = retired
            else:
                self._session_count += 1
                self._session_index += 1
                self.sessions[pid] = {"pid": pid, "index": self._session_index, "region": None,
                                  "universe": None, "delay": None, "last_expr": None,
                                  "ppid": line.get("ppid") or None, "validator_pid": line.get("pid", 0),
                                  "agent": None, "_ended": False, "_inflight": [],
                                  "_seen": ts, "_role": role,
                                  "counts": dict.fromkeys(("exprs", "alphas", "eval_passed", "candidates"), 0)}
        session = self.sessions[pid]
        if ts >= session["_seen"]:
            session["validator_pid"] = line.get("pid", 0)
            if line.get("ppid"):
                session["ppid"] = line["ppid"]
        if line.get("agent") and (not session.get("agent") or ts >= session["_seen"]):
            session["agent"] = line["agent"].strip()[:120] or None
        if ts >= session["_seen"]:
            session["_seen"], session["_role"] = ts, role
        self.sessions.move_to_end(pid)
        return session

    def _adopt_parent(self, validator, parent):
        if not validator or not parent or validator == parent:
            return
        previous = self.sessions.get(validator)
        archived = previous is None
        if archived:
            previous = self._archive.pop("session", validator)
        if previous is None:
            return
        if previous.get("ppid"):
            if archived:
                self._archive.put("session", validator, previous)
            return  # A terminal PID is not another validator's fallback identity.
        current = self.sessions.get(parent)
        if current is None:
            current = self._archive.pop("session", parent)
        if current is None:
            current = previous
            current["_ended"] = False  # The child's exit says nothing about its parent.
        else:
            self._session_count -= 1
            current["index"] = min(current["index"], previous["index"])
            for key, value in previous["counts"].items():
                current["counts"][key] += value
            for key in ("region", "universe", "delay", "last_expr"):
                if previous[key] is not None and (current[key] is None or previous["_seen"] > current["_seen"]):
                    current[key] = previous[key]
            if previous["_seen"] > current["_seen"]:
                for key in ("_seen", "_role", "validator_pid"):
                    current[key] = previous[key]
            if not current.get("agent"):
                current["agent"] = previous.get("agent")
            current["_inflight"] = self._merge_calls(chain(current.get("_inflight", []),
                                                          previous.get("_inflight", [])))
        self.sessions.pop(validator, None)
        current["pid"], current["ppid"] = parent, parent
        self.sessions[parent] = current
        for cache in (self.alphas, self.sims):
            for value in cache.values():
                if value["pid"] == validator:
                    value["pid"] = parent
        self._archive.reassign_pid(validator, parent)
        self.events = deque(({**event, "pid": parent} if event["pid"] == validator else event
                             for event in self.events), maxlen=rules.EVENTS_KEEP)

    def _identify(self, line):
        validator, parent = line.get("pid", 0), line.get("ppid")
        if not parent and validator:
            parent = self._parent_aliases.get(validator)
            if parent is None:
                alias = self._archive.get("alias", validator)
                parent = alias["pid"] if alias else None
        if parent and validator and validator != parent:
            if self._parent_aliases.get(validator) != parent:
                self._adopt_parent(validator, parent)
                self._archive.put("alias", validator, {"pid": parent})
                self._parent_aliases[validator] = parent
            self._parent_aliases.move_to_end(validator)
            while len(self._parent_aliases) > rules.PROCESS_CACHE_MAX:
                self._parent_aliases.popitem(last=False)
            return {**line, "ppid": parent}
        return line

    def _alpha(self, aid, h, sim, pid, ts):
        if aid not in self.alphas:
            retired = self._archive.pop("alpha", aid)
            if retired is not None:
                self.alphas[aid] = retired
        if aid not in self.alphas:
            self._order += 1
            self.alphas[aid] = {"id": aid, "h": h, "expr": self.expressions.get(h), "sim": sim, "pid": pid,
                                "sharpe": None, "fitness": None, "turnover": None, "passed": None,
                                "failed": [], "prod": None, "status": "done", "best": False,
                                "ts": iso(ts), "_ts": ts, "_order": self._order,
                                "_stage": 0, "_stage_ts": -1e30}
            self.counts["alphas"] += 1
            self.sessions[pid]["counts"]["alphas"] += 1
        alpha = self.alphas[aid]
        if h:
            old_h = alpha["h"]
            alpha["h"] = h
            alpha["expr"] = self.expressions.get(h) or (alpha["expr"] if old_h == h else None)
        if alpha["sim"] is None and sim is not None:
            alpha["sim"] = sim
        if ts >= alpha["_ts"]:
            alpha["_ts"], alpha["ts"] = ts, iso(ts)
        self.alphas.move_to_end(aid)
        return alpha

    def _session_count_add(self, pid, key, delta):
        session = self.sessions.get(pid)
        if session is not None:
            session["counts"][key] += delta
            return
        retired = self._archive.pop("session", pid)
        if retired is not None:
            retired["counts"][key] += delta
            self._archive.put("session", pid, retired)

    @staticmethod
    def _advance(alpha, status, ts):
        stage = STAGES[status]
        if stage > alpha["_stage"] or (stage == alpha["_stage"] and ts >= alpha["_stage_ts"]):
            alpha["status"], alpha["_stage"], alpha["_stage_ts"] = status, stage, ts

    def _simulation(self, line, pid, ts):
        sim = line.get("sim")
        key = sim or f"unknown:{pid}:{ts}"
        if key not in self.sims:
            retired = self._archive.pop("sim", key)
            if retired is not None:
                self.sims[key] = retired
        if key not in self.sims:
            self.sims[key] = {"sim": sim, "pid": pid, "n": 0, "since": iso(ts), "exprs": [], "_status": "pending"}
        self.sims.move_to_end(key)
        return self.sims[key]

    def _error(self, line, ts, pid):
        self.rejects["tool_error"] += 1
        text = line.get("err") or f"{line.get('t', line['role'])} 执行出错"
        self._stamp("error", ts, text)
        self._event("error", ts, pid, text, line.get("alpha"))

    @staticmethod
    def _call_key(call):
        return call["validator_pid"], call["tool"], call.get("sim"), call.get("alpha")

    @classmethod
    def _merge_calls(cls, calls):
        latest = {}
        for call in calls:
            key = cls._call_key(call)
            if key not in latest or (call["_ts"], call["_seq"]) >= (latest[key]["_ts"], latest[key]["_seq"]):
                latest[key] = call
        return sorted(latest.values(), key=lambda call: (call["_ts"], call["_seq"]))[-INFLIGHT_KEEP:]

    def _track_call(self, session, line):
        calls = session.setdefault("_inflight", [])
        if line.get("ph") == "start":
            call = {"validator_pid": line.get("pid", 0), "tool": line["t"],
                    "_role": line["role"], "_ts": line["ts"], "_seq": self.revision+1,
                    **{key: line[key] for key in ("sim", "alpha") if line.get(key)}}
            session["_inflight"] = self._merge_calls(chain(calls, (call,)))
            return
        matches = []
        for index, call in enumerate(calls):
            if call["validator_pid"] != line.get("pid", 0) or call["_ts"] > line["ts"]:
                continue
            if (line.get("t") and call["tool"] != line["t"]) or (not line.get("t") and call["_role"] != line["role"]):
                continue
            if any(call.get(key) and line.get(key) and call[key] != line[key] for key in ("sim", "alpha")):
                continue
            exact = sum(bool(call.get(key) and line.get(key)) for key in ("sim", "alpha"))
            matches.append((exact, call["_ts"], call["_seq"], index))
        if matches:
            calls.pop(max(matches)[-1])

    def _batch_alphas(self, sim):
        first, count = [], 0
        if sim:
            for alpha in chain(self.alphas.values(), self._archive.records("alpha")):
                if alpha.get("sim") == sim:
                    count += 1
                    first = sorted((*first, (alpha["_order"], alpha["id"])))[:8]
        return count, [aid for _, aid in first]

    def _start_event(self, line, ts, pid):
        role = line["role"]
        if role == "simulate":
            n = line.get("n")
            self._event("sim_submit_start", ts, pid, f"开始提交回测 {n if n is not None else '?'} 条表达式", n=n)
        elif role == "evaluate":
            n, alphas = self._batch_alphas(line.get("sim"))
            self._event("eval_start", ts, pid, f"开始评估 {n} 个 alpha",
                        sim=line.get("sim"), n=n, alphas=alphas)
        elif role in ("prod", "save"):
            alpha = line.get("alpha")
            self._event("prod_start" if role == "prod" else "save_start", ts, pid,
                        f"{alpha or 'alpha'} {'开始查相关性' if role == 'prod' else '开始存候选'}",
                        alpha, alphas=(alpha,) if alpha else ())

    def feed(self, line_dict):
        if not _valid(line_dict):
            self.bad_lines += 1
            return
        if not self.start <= line_dict["ts"] < self.end:
            return
        self._qualified_cache = None
        line = self._identify(line_dict)
        ts, pid, role = line["ts"], line.get("ppid") or line.get("pid", 0), line["role"]
        self._first = ts if self._first is None else min(self._first, ts)
        session = self._session(pid, ts, role, line)
        self._roles[role] = max(ts, self._roles.get(role, -math.inf))
        self._track_call(session, line)
        if line.get("ph") == "start":
            self._start_event(line, ts, pid)
            self._trim()
            self.revision += 1
            self._temporal = self._temporal_signature(self.clock())
            return
        self.calls += 1
        if role == "result" and line.get("t") == "local_wait_multi_simulation":
            duration = number(line.get("dur"))
            if duration is not None and duration >= 0:
                # Keep the latest samples even when replay feeds rows out of order.
                sample = (ts, self.calls, duration)
                if len(self._sim_durations) < 20:
                    heappush(self._sim_durations, sample)
                else:
                    heappushpop(self._sim_durations, sample)
        covered = False

        if role in ("precheck", "simulate"):
            success_status = "pass" if role == "precheck" else "submitted"
            passed = line.get("status") == success_status and line.get("ok", True) is not False and not line.get("err")
            message = line.get("err") or ("最近一次通过" if passed else "最近一次预检未通过")
            self._stamp("precheck", ts, message)

        if role == "simulate":
            for key in ("region", "universe", "delay"):
                if line.get(key) is not None and ts >= session["_seen"]:
                    session[key] = line[key]
            if line.get("status") == "submitted":
                exprs = line.get("exprs", [])
                self.submits += 1
                self.counts["exprs"] += len(exprs)
                session["counts"]["exprs"] += len(exprs)
                sim = self._simulation(line, pid, ts)
                sim["n"], sim["exprs"] = len(exprs), [expr for _, expr in exprs]
                for h, expr in exprs:
                    if h and expr:
                        self.expressions[h] = expr
                        self.expressions.move_to_end(h)
                        self._archive.backfill(h, expr)
                        for alpha in self.alphas.values():
                            if alpha["h"] == h:
                                alpha["expr"] = expr
                        if ts >= session["_seen"]:
                            session["last_expr"] = expr
                        self._stamp("generate", ts, expr)
                self._stamp("simulate", ts, f"已提交 {line.get('sim') or '回测'}")
                self._event("sim_submit", ts, pid, f"提交回测 {len(exprs)} 条表达式",
                            sim=line.get("sim"), n=len(exprs), exprs=(expr for _, expr in exprs))
            elif line.get("status"):
                self.rejects["create_fail"] += 1
                text = line.get("err") or line["status"]
                self._stamp("error", ts, text)
                self._event("error", ts, pid, text)
                covered = True
        elif role == "precheck":
            if line.get("status") == "fail":
                self.rejects["precheck_fail"] += 1
                text = line.get("err") or "预检未通过"
                self._event("precheck_fail", ts, pid, text)
                covered = True
        elif role == "result" and line.get("status"):
            sim = self._simulation(line, pid, ts)
            if line["status"] == "failed":
                if sim["_status"] == "pending":
                    sim["_status"] = "failed"
                    self.rejects["sim_fail"] += 1
                    text = line.get("err") or "回测失败"
                    self._stamp("error", ts, text)
                    self._event("sim_fail", ts, pid, text, sim=line.get("sim"))
                covered = True
            elif line["status"] == "completed":
                if sim["_status"] != "done":
                    sim["_status"] = "done"
                    self.counts["sims_done"] += 1
                    self._bucket(ts)["sims_done"] += 1
                    rows = line.get("alphas", [])
                    self._event("sim_done", ts, pid, f"回测完成 {len(rows)} 个 alpha",
                                sim=line.get("sim"), n=len(rows), alphas=(row[1] for row in rows))
                self._stamp("simulate", ts, f"最近完成 {line.get('sim') or '回测'} · {len(line.get('alphas', []))} 个 alpha")
                for h, aid, sharpe, fitness, turnover in line.get("alphas", []):
                    if not aid:
                        continue
                    a = self._alpha(aid, h, line.get("sim"), pid, ts)
                    if a["_stage"] <= 1:
                        a.update(sharpe=number(sharpe), fitness=number(fitness))
                    a["turnover"] = number(turnover)
                    if h and not a.get("_metrics_seen"):
                        a["_metrics_seen"] = True
                        self._bucket(ts)["alphas"] += 1
                    self._advance(a, "done", ts)
        elif role == "evaluate":
            passed_rows = []
            for aid, h, passed, sharpe, fitness, failed in line.get("alphas", []):
                if not aid:
                    continue
                a = self._alpha(aid, h, line.get("sim"), pid, ts)
                if ts < a.get("_eval_ts", -math.inf):
                    continue
                previous = a["passed"]
                if passed is not None:
                    if previous is None:
                        self.evaluated += 1
                    if previous is not passed:
                        delta = int(passed) - int(previous is True)
                        self.counts["eval_passed"] += delta
                        self._session_count_add(a["pid"], "eval_passed", delta)
                        self.rejects["eval_fail"] += int(not passed) - int(previous is False)
                        if passed:
                            self._bucket(ts)["eval_passed"] += 1
                        self._event("eval_pass" if passed else "eval_fail", ts, pid,
                                    f"{aid} {'评估通过' if passed else '未通过：' + ','.join(failed)}", aid)
                    a.update(passed=passed, failed=failed[:rules.MAX_FAILED_CHECKS])
                    self._advance(a, "eval_passed" if passed else "eval_failed", ts)
                a.update(sharpe=number(sharpe), fitness=number(fitness), best=aid == line.get("best"), _eval_ts=ts)
                if passed:
                    passed_rows.append(a)
            best = next((a for a in passed_rows if a["best"]), max(passed_rows, key=lambda a: a["sharpe"] or 0, default=None))
            self._stamp("evaluate", ts, f"最近：{best['id']} Sharpe {format_metric(best['sharpe'])}" if best else "最近一批无通过")
        elif role == "prod" and line.get("alpha"):
            self.prod_checks += 1
            a = self._alpha(line["alpha"], None, None, pid, ts)
            prod = number(line.get("prod"))
            self._stamp("prod", ts, f"{a['id']} Prod {format_metric(prod, '?')}")
            if prod is not None:
                self.prod_ok_checks += int(prod < rules.PROD_LIMIT)
                self.rejects["prod_blocked"] += int(prod >= rules.PROD_LIMIT)
            if prod is not None and ts >= a.get("_prod_ts", -math.inf):
                good = prod < rules.PROD_LIMIT
                self.prod_good += int(good) - int(a.get("_prod_good", False))
                a.update(prod=prod, _prod_good=good, _prod_ts=ts)
                self._advance(a, "prod_ok" if good else "prod_blocked", ts)
                self._event("prod_ok" if good else "prod_block", ts, pid, f"{a['id']} Prod {format_metric(prod)}", a["id"])
        elif role == "save" and line.get("alpha"):
            a = self._alpha(line["alpha"], None, None, pid, ts)
            self._stamp("candidate_activity", ts, "")
            if not line.get("err") and ts >= a.get("_save_ts", -math.inf):
                if line.get("saved") is True or line.get("passed") is False:
                    a["_local_rejected"] = line.get("saved") is not True
                    a["_save_ts"] = ts
            if not line.get("err") and line.get("saved") is True:
                if a["status"] != "candidate":
                    self.counts["candidates"] += 1
                    self._session_count_add(a["pid"], "candidates", 1)
                    self._bucket(ts)["candidates"] += 1
                    self._event("candidate", ts, pid, f"{a['id']} 已存为候选", a["id"])
                self._advance(a, "candidate", ts)
                self._stamp("candidate", ts, a["id"])
                self._stamp("review", ts, "")
            elif not line.get("err") and line.get("passed") is False:
                if not a.get("_rejected_seen"):
                    self.rejects["save_rejected"] += 1
                    a["_rejected_seen"] = True
                    self._event("rejected", ts, pid, f"{a['id']} 本地检查未通过", a["id"])
                self._advance(a, "rejected", ts)
        if not covered and (line.get("err") or line.get("ok") is False):
            self._error(line, ts, pid)
        self._trim()
        self.revision += 1
        self._temporal = self._temporal_signature(self.clock())

    def _qualified_metrics(self):
        if self._qualified_cache is None:
            best, buckets = None, {}
            for alpha in chain((a for a in self.alphas.values() if qualified(a)), self._archive.qualified_alphas()):
                if best is None or alpha["sharpe"] > best["sharpe"]:
                    best = alpha
                index = max(0, min(self._bucket_count-1, int((alpha["_eval_ts"]-self.start)//rules.TIMELINE_BUCKET_SECONDS)))
                buckets[index] = max(buckets.get(index, -math.inf), alpha["sharpe"])
            self._qualified_cache = (best, buckets)
        return self._qualified_cache

    def _all_sessions(self):
        return chain(self.sessions.values(), self._archive.records("session"))

    @staticmethod
    def _ended(session, now):
        return session.get("_ended", False) or (session["pid"] == 0 and now-session["_seen"] > rules.UNKNOWN_SESSION_SECONDS)

    def _ongoing(self, session, now):
        if self._ended(session, now):
            return None
        return max((call for call in session.get("_inflight", [])
                    if now-call["_ts"] < rules.INFLIGHT_SECONDS),
                   key=lambda call: (call["_ts"], call["_seq"]), default=None)

    def _expire_calls(self, now):
        changed = False
        for session in self._all_sessions():
            calls = session.get("_inflight", [])
            live = [] if self._ended(session, now) else [call for call in calls
                                                       if now-call["_ts"] < rules.INFLIGHT_SECONDS]
            if len(live) != len(calls):
                session["_inflight"] = live
                changed = True
                if session["pid"] not in self.sessions:
                    self._archive.put("session", session["pid"], session)
        return changed

    def check_processes(self, is_alive):
        """The server supplies the OS probe; replay and aggregation do no I/O."""
        changed = False
        for session in list(self._all_sessions()):
            if session.get("_ended"):
                continue
            process = session.get("ppid") or session.get("validator_pid") or session["pid"]
            if not process:
                continue
            try:
                ended = not is_alive(process)
            except Exception:
                continue  # An unavailable probe is not evidence of process exit.
            if ended != session.get("_ended", False):
                session["_ended"] = ended
                if ended:
                    session["_inflight"] = []
                changed = True
                if session["pid"] not in self.sessions:
                    self._archive.put("session", session["pid"], session)
        if changed:
            self.revision += 1
            self._temporal = self._temporal_signature(self.clock())

    @staticmethod
    def _labels(sessions):
        names = Counter(s.get("agent") for s in sessions if s.get("agent"))
        seen, labels = Counter(), {}
        for session in sessions:
            agent = session.get("agent")
            if agent:
                seen[agent] += 1
                label = f"{agent} · {seen[agent]}" if names[agent] > 1 else agent
            else:
                label = f"终端 {session['index']}" if session["pid"] else "未知会话"
            labels[session["pid"]] = label
        return labels

    def _trim(self):
        limit = rules.MAX_ALPHAS
        if len(self.alphas) > limit * 2:
            target = max(limit, sum(a["status"] == "candidate" for a in self.alphas.values()))
            for aid in sorted(self.alphas, key=lambda key: self.alphas[key]["_ts"]):
                if len(self.alphas) <= target:
                    break
                if self.alphas[aid]["status"] != "candidate":
                    self._archive.put("alpha", aid, self.alphas.pop(aid))
        for cache in (self.sims, self.sessions):
            if len(cache) > limit * 2:
                for key in list(cache):
                    if len(cache) <= limit:
                        break
                    if cache is self.sims and cache[key]["_status"] == "pending":
                        continue
                    self._archive.put("sim" if cache is self.sims else "session", key, cache.pop(key))
                while len(cache) > limit * 2:
                    key, value = cache.popitem(last=False)
                    self._archive.put("sim" if cache is self.sims else "session", key, value)
        while len(self.expressions) > limit * 2:
            self.expressions.popitem(last=False)

    def _temporal_signature(self, now):
        active, ended = 0, 0
        inflight = []
        for session in self._all_sessions():
            retired = self._ended(session, now)
            ended += retired
            call = self._ongoing(session, now)
            active += not retired and (call is not None or now-session["_seen"] <= rules.IDLE_SECONDS)
            if call is not None:
                inflight.append((session["pid"], self._call_key(call), call["_ts"], call["_seq"]))
        return (active, ended,
                    tuple(sorted(inflight)),
                    tuple((role, 0 <= now - ts <= rules.BUSY_SECONDS) for role, ts in sorted(self._roles.items())),
                    0 <= now - self._last.get("error", (-math.inf, ""))[0] <= rules.BUSY_SECONDS,
                    min(self._bucket_count-1, max(-1, int((now - self.start) // rules.TIMELINE_BUCKET_SECONDS))))

    def refresh(self):
        now = self.clock()
        expired = self._expire_calls(now)
        temporal = self._temporal_signature(now)
        if expired or (self._temporal is not None and temporal != self._temporal):
            self.revision += 1
        self._temporal = temporal

    def close(self):
        self._archive.close()

    @staticmethod
    def _public(alpha):
        return {key: alpha[key] for key in ALPHA_FIELDS}

    def snapshot(self, mode):
        self.refresh()
        now = self.clock()
        all_sessions = sorted(self._all_sessions(), key=lambda item: item["index"])
        labels = self._labels(all_sessions)
        ended = {s["pid"] for s in all_sessions if self._ended(s, now)}
        def public(alpha):
            return {**self._public(alpha), "session_label": labels.get(alpha["pid"], "未知会话")}
        pending = [{k: sim[k] for k in ("sim", "pid", "n", "since", "exprs")}
                   for sim in self.sims.values() if sim["_status"] == "pending" and sim["pid"] not in ended]
        pending.extend({k: sim[k] for k in ("sim", "pid", "n", "since", "exprs")}
                       for sim in self._archive.records("sim", "pending") if sim["pid"] not in ended)
        running_counts = Counter(sim["pid"] for sim in pending)
        sessions = []
        for s in all_sessions:
            if s["pid"] in ended:
                continue
            call = self._ongoing(s, now)
            idle = call is None and now - s["_seen"] > rules.IDLE_SECONDS
            running = running_counts[s["pid"]]
            phase, phase_label = PHASES[call["_role"]] if call is not None else ("idle", "空闲") if idle else ("thinking", "构思中")
            inflight = ({"tool": call["tool"], "since": iso(call["_ts"]),
                         **{key: call[key] for key in ("sim", "alpha") if key in call}}
                        if call is not None else None)
            index = s["index"]
            sessions.append({"pid": s["pid"], "index": index, "label": labels[s["pid"]],
                             "ppid": s.get("ppid"), "validator_pid": s.get("validator_pid", s["pid"]), "agent": s.get("agent"),
                             "shape": SHAPES[(index-1) % 6], "color": COLORS[(index-1) % 6],
                             **{k: s[k] for k in ("region", "universe", "delay", "last_expr")},
                             "phase": phase, "phase_label": phase_label, "idle": idle, "inflight": inflight,
                             "last_seen": iso(s["_seen"]), "running_sims": running, "counts": dict(s["counts"])})
        ordered = sorted(self.alphas.values(), key=lambda a: (a["_ts"], a["_order"]), reverse=True)
        review = [public(a) for a in ordered if a["status"] == "candidate"]
        remaining = max(0, rules.MAX_ALPHAS-len(review))
        alphas = []
        for alpha in ordered:
            if alpha["status"] == "candidate" or remaining:
                alphas.append(public(alpha))
                remaining -= int(alpha["status"] != "candidate")
        active = sum(not s["idle"] for s in sessions)
        best, _ = self._qualified_metrics()
        if best is not None:
            best["expr"] = self.expressions.get(best["h"]) or best["expr"]
        totals = {"sessions_active": active, "sessions_total": self._session_count,
                  **self.counts, "sims_pending": len(pending), "pending_review": self.counts["candidates"]}
        durations = sorted(sample[2] for sample in self._sim_durations)
        typical_seconds = None
        if durations:
            low, high = durations[(len(durations)-1)//2], durations[len(durations)//2]
            typical_seconds = low + (high-low)/2  # Avoid overflow for large finite durations.
        return {"v": 1, "mode": mode, "day": self.day.isoformat(), "generated_at": iso(now), "revision": self.revision,
                "wq_start": iso(self.start), "wq_next_reset": iso(self.end),
                "goal": {"candidates": self.counts["candidates"], "target": self.daily_goal},
                "totals": totals, "cards": self._cards(now, active, len(pending)), "sessions": sessions,
                "alphas": alphas, "pending_sims": pending, "sim_typical_seconds": typical_seconds, "sessions_ended": len(ended),
                "funnel": [{"key": key, "label": label, "count": count} for key, label, count in (
                    ("submit", "提交", self.counts["exprs"]), ("simulate", "回测", sum(b["alphas"] for b in self._buckets.values())),
                    ("evaluate", "评估", self.counts["eval_passed"]), ("prod", "相关性", self.prod_good),
                    ("pick", "候选", self.counts["candidates"]))],
                "rejects": dict(self.rejects), "timeline": self._timeline(now),
                "best": public(best) if best is not None else None,
                "review": review, "events": list(self.events), "thresholds": self.thresholds}

    def _timeline(self, now):
        if now < self.start:
            return []
        end = max(0, min(self._bucket_count-1, int((now-self.start) // rules.TIMELINE_BUCKET_SECONDS)))
        cumulative = 0
        timeline = []
        _, best_buckets = self._qualified_metrics()
        for index in range(end+1):
            bucket = self._buckets.get(index, {})
            cumulative += bucket.get("candidates", 0)
            timeline.append({"t": iso(self._midnight+index*rules.TIMELINE_BUCKET_SECONDS),
                             **{k: bucket.get(k, 0) for k in ("sims_done", "alphas", "eval_passed")},
                             "candidates_cum": cumulative, "best_sharpe": best_buckets.get(index)})
        return timeline

    def _cards(self, now, active, pending):
        def rate(a, b):
            return max(0.0, min(1.0, a / b)) if b else 0.0
        def busy(*roles):
            return any(0 <= now-self._roles.get(role, -math.inf) <= rules.BUSY_SECONDS for role in roles)
        def message(key, default):
            return self._last.get(key, (None, default))[1]
        failures = self.rejects["precheck_fail"] + self.rejects["create_fail"]
        passed_rate = rate(self.submits, self.submits + failures)
        candidates = self.counts["candidates"]
        errors = self.rejects["sim_fail"] + self.rejects["tool_error"] + self.rejects["create_fail"]
        rows = [
            ("generate", "生成", "AI 送去回测的表达式", self.counts["exprs"], "条", passed_rate, bool(active), message("generate", "等待表达式")),
            ("precheck", "预检", "预检与提交失败", failures, "次", passed_rate, busy("precheck", "simulate"), message("precheck", "暂无预检")),
            ("simulate", "回测", "已完成的回测批次", self.counts["sims_done"], "批", rate(self.counts["sims_done"], self.counts["sims_done"]+pending+self.rejects["sim_fail"]), bool(pending), f"回测中 {pending} 批" if pending else message("simulate", "等待回测")),
            ("evaluate", "评估", "评估通过的 alpha", self.counts["eval_passed"], "个", rate(self.counts["eval_passed"], self.evaluated), busy("evaluate"), message("evaluate", "暂无评估")),
            ("prod", "相关性", "Prod Correlation 检查", self.prod_checks, "次", rate(self.prod_ok_checks, self.prod_checks), busy("prod"), message("prod", "等待检查")),
            ("candidate", "候选", "已保存的本地候选", candidates, "个", rate(candidates, self.daily_goal), busy("save"), message("candidate", "暂无候选")),
            ("error", "错误", "提交、回测与工具错误", errors, "次", rate(errors, self.calls), 0 <= now-self._last.get("error", (-math.inf, ""))[0] <= rules.BUSY_SECONDS, message("error", "无错误")),
            ("review", "复核", "等待人工复核", candidates, "个", rate(candidates, self.daily_goal), candidates > 0, f"{candidates} 个候选等你复核"),
        ]
        return [{"key": key, "title": title, "subtitle": subtitle, "value": value, "unit": unit,
                 "progress": progress, "busy": is_busy, "message": text,
                 "updated_at": iso(self._last[key][0]) if key in self._last else None}
                for key, title, subtitle, value, unit, progress, is_busy, text in rows]
