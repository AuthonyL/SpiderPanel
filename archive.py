"""Disposable disk index for details evicted from the daily in-memory view."""

import json
import sqlite3
import weakref

from . import rules


QUALIFIED_STATUSES = {"eval_passed", "prod_ok", "candidate"}


def qualified(alpha):
    return (alpha.get("passed") is True and alpha.get("status") in QUALIFIED_STATUSES
            and "_eval_ts" in alpha and alpha.get("sharpe") is not None
            and (alpha.get("prod") is None or alpha["prod"] < rules.PROD_LIMIT)
            and not alpha.get("_local_rejected", False))


class Archive:
    def __init__(self):
        self.db = None
        self._finalizer = None

    def _open(self):
        if self.db is None:
            # Empty filename is SQLite's temporary on-disk database. It is
            # deleted on close. Runtime's state lock also protects this handle.
            self.db = sqlite3.connect("", isolation_level=None, check_same_thread=False)
            self._finalizer = weakref.finalize(self, self.db.close)
            self.db.execute("PRAGMA cache_size=-256")
            self.db.execute("PRAGMA journal_mode=OFF")
            self.db.execute("PRAGMA synchronous=OFF")
            self.db.execute("CREATE TABLE retired(kind TEXT, id TEXT, payload TEXT, sharpe REAL, h TEXT, seen REAL, status TEXT, PRIMARY KEY(kind,id))")
            self.db.execute("CREATE INDEX best_alpha ON retired(kind, sharpe)")
            self.db.execute("CREATE INDEX alpha_hash ON retired(kind, h)")
            self.db.execute("CREATE INDEX session_seen ON retired(kind, seen)")
            self.db.execute("CREATE INDEX sim_status ON retired(kind, status)")
        return self.db

    def put(self, kind, key, value):
        sharpe = value.get("sharpe") if kind == "alpha" and qualified(value) else None
        h = value.get("h") if kind == "alpha" else None
        seen = value.get("_seen") if kind == "session" else None
        status = value.get("_status") if kind == "sim" else None
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        self._open().execute("INSERT OR REPLACE INTO retired VALUES(?,?,?,?,?,?,?)", (kind, str(key), payload, sharpe, h, seen, status))

    def records(self, kind, status=None):
        if self.db is None:
            return
        if status is None:
            cursor = self.db.execute("SELECT payload FROM retired WHERE kind=?", (kind,))
        else:
            cursor = self.db.execute("SELECT payload FROM retired WHERE kind=? AND status=?", (kind, status))
        while rows := cursor.fetchmany(64):
            for (payload,) in rows:
                yield json.loads(payload)

    def active_sessions(self, cutoff):
        if self.db is None:
            return 0
        return self.db.execute("SELECT COUNT(*) FROM retired WHERE kind='session' AND seen>=?", (cutoff,)).fetchone()[0]

    def backfill(self, h, expr):
        if self.db is None:
            return
        cursor = self.db.execute("SELECT id,payload FROM retired WHERE kind='alpha' AND h=?", (h,))
        while rows := cursor.fetchmany(64):
            for key, payload in rows:
                value = json.loads(payload)
                value["expr"] = expr
                payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                self.db.execute("UPDATE retired SET payload=? WHERE kind='alpha' AND id=?", (payload, key))

    def get(self, kind, key):
        if self.db is None:
            return None
        row = self.db.execute("SELECT payload FROM retired WHERE kind=? AND id=?", (kind, str(key))).fetchone()
        return json.loads(row[0]) if row else None

    def pop(self, kind, key):
        value = self.get(kind, key)
        if value is not None:
            self.db.execute("DELETE FROM retired WHERE kind=? AND id=?", (kind, str(key)))
        return value

    def reassign_pid(self, previous, current):
        """Move archived joins when late metadata identifies a validator's parent."""
        if self.db is None:
            return
        for kind in ("alpha", "sim"):
            cursor = self.db.execute("SELECT id,payload FROM retired WHERE kind=?", (kind,))
            while rows := cursor.fetchmany(64):
                for key, payload in rows:
                    value = json.loads(payload)
                    if value.get("pid") == previous:
                        value["pid"] = current
                        self.put(kind, key, value)

    def best(self):
        if self.db is None:
            return None
        row = self.db.execute("SELECT payload FROM retired WHERE kind='alpha' AND sharpe IS NOT NULL ORDER BY sharpe DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def qualified_alphas(self):
        if self.db is None:
            return
        cursor = self.db.execute("SELECT payload FROM retired WHERE kind='alpha' AND sharpe IS NOT NULL")
        while rows := cursor.fetchmany(64):
            for (payload,) in rows:
                yield json.loads(payload)

    def close(self):
        if self._finalizer is not None:
            self._finalizer()
            self._finalizer = None
            self.db = None
