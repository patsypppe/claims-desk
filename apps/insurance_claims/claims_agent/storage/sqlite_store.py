"""SQLite-backed session and lockout stores (durable across restarts). Same interfaces as the in-memory ones."""
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from claims_agent.sessions import LOCKOUT_WINDOW_S, UnknownSessionError
from claims_agent.state import ConversationState


class _Db:
    def __init__(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("CREATE TABLE IF NOT EXISTS sessions (sid TEXT PRIMARY KEY, state TEXT NOT NULL, "
                               "last_seen REAL NOT NULL)")
            self._conn.execute("CREATE TABLE IF NOT EXISTS lockout_failures (party_id TEXT NOT NULL, ts REAL NOT NULL)")

    def run(self, sql: str, args: tuple = ()) -> list:
        with self._lock, self._conn:
            return self._conn.execute(sql, args).fetchall()


class SqliteSessionStore:
    def __init__(self, path: Path, ttl_seconds: int = 1800, now: Callable[[], float] = time.time) -> None:
        self._db, self.ttl_seconds, self.now = _Db(path), ttl_seconds, now

    def create(self, channel_token: str | None = None) -> str:
        sid = uuid.uuid4().hex
        self.save(ConversationState(session_id=sid, channel_token=channel_token))
        return sid

    def get(self, sid: str) -> ConversationState:
        rows = self._db.run("SELECT state, last_seen FROM sessions WHERE sid = ?", (sid,))
        if not rows:
            raise UnknownSessionError(sid)
        state_json, last_seen = rows[0]
        if self.now() - last_seen > self.ttl_seconds:
            self.drop(sid)
            raise UnknownSessionError(sid)
        return ConversationState.model_validate_json(state_json)

    def save(self, state: ConversationState) -> None:
        self._db.run("INSERT INTO sessions (sid, state, last_seen) VALUES (?, ?, ?) ON CONFLICT(sid) DO UPDATE "
                     "SET state = excluded.state, last_seen = excluded.last_seen",
                     (state.session_id, state.model_dump_json(), self.now()))

    def drop(self, sid: str) -> None:
        self._db.run("DELETE FROM sessions WHERE sid = ?", (sid,))

    def prune(self) -> int:
        cutoff = self.now() - self.ttl_seconds
        count = self._db.run("SELECT COUNT(*) FROM sessions WHERE last_seen < ?", (cutoff,))[0][0]
        self._db.run("DELETE FROM sessions WHERE last_seen < ?", (cutoff,))
        return count


class SqliteLockoutRegistry:
    def __init__(self, path: Path, now: Callable[[], float] = time.time) -> None:
        self._db, self.now = _Db(path), now

    def record_failure(self, party_id: str) -> None:
        self._db.run("INSERT INTO lockout_failures (party_id, ts) VALUES (?, ?)", (party_id, self.now()))

    def is_locked(self, party_id: str, threshold: int) -> bool:
        cutoff = self.now() - LOCKOUT_WINDOW_S
        self._db.run("DELETE FROM lockout_failures WHERE ts < ?", (cutoff,))
        rows = self._db.run("SELECT COUNT(*) FROM lockout_failures WHERE party_id = ? AND ts >= ?", (party_id, cutoff))
        return rows[0][0] >= threshold

    @property
    def failures(self) -> dict[str, list[float]]:  # parity with the in-memory registry (tests/debug)
        out: dict[str, list[float]] = {}
        for party, ts in self._db.run("SELECT party_id, ts FROM lockout_failures"):
            out.setdefault(party, []).append(ts)
        return out
