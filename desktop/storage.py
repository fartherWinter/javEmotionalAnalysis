from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .domain import AppError, Snapshot, clean


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    account TEXT NOT NULL, session TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(account, session));
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, account TEXT NOT NULL, session TEXT NOT NULL,
                    topic TEXT NOT NULL, content TEXT NOT NULL, evidence TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS memory_topic ON memories(account, session, topic);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def profile(self, account: str, session: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT data FROM profiles WHERE account=? AND session=?", (account, session)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_profile(self, account: str, session: str, profile: dict) -> None:
        data = {k: clean(str(profile.get(k, ""))) for k in ("relationship", "notes", "style")}
        with self.connect() as db:
            db.execute("INSERT INTO profiles VALUES(?,?,?) ON CONFLICT(account,session) DO UPDATE SET data=excluded.data",
                       (account, session, json.dumps(data, ensure_ascii=False)))

    def contacts(self) -> list[tuple[str, str]]:
        with self.connect() as db:
            return db.execute("SELECT account,session FROM profiles UNION SELECT account,session FROM memories").fetchall()

    def memories(self, account: str, session: str) -> list[dict]:
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM memories WHERE account=? AND session=? ORDER BY pinned DESC, updated DESC",
                              (account, session)).fetchall()
        return [{**dict(row), "evidence": json.loads(row["evidence"])} for row in rows]

    def confirm(self, snapshot: Snapshot, candidate: dict, replace_id: str | None = None) -> None:
        refs = candidate.get("evidence_refs", [])
        evidence_map = {ref: (source, excerpt) for ref, source, excerpt in snapshot.evidence}
        if not refs or any(ref not in evidence_map for ref in refs):
            raise AppError("记忆证据不属于本次选择的消息")
        topic = clean(candidate["topic"]).strip().casefold()
        content = clean(candidate["content"]).strip()
        if not topic or not content:
            raise AppError("记忆主题和内容不能为空")
        evidence = [{"source_id": evidence_map[r][0], "excerpt": evidence_map[r][1][:300]} for r in refs]
        with self.connect() as db:
            if replace_id:
                found = db.execute("SELECT id FROM memories WHERE id=? AND account=? AND session=?",
                                   (replace_id, snapshot.account, snapshot.session)).fetchone()
                if not found:
                    raise AppError("待替换记忆已不存在，请刷新")
                db.execute("DELETE FROM memories WHERE id=?", (replace_id,))
            try:
                db.execute("INSERT INTO memories VALUES(?,?,?,?,?,?,?,?)", (
                    uuid.uuid4().hex, snapshot.account, snapshot.session, topic, content,
                    json.dumps(evidence, ensure_ascii=False), 0, time.time()))
            except sqlite3.IntegrityError:
                raise AppError("同主题记忆已存在，请明确选择替换或拒绝") from None

    def edit(self, account: str, session: str, memory_id: str, content: str, pinned: bool) -> None:
        if not content.strip():
            raise AppError("记忆内容不能为空")
        with self.connect() as db:
            db.execute("UPDATE memories SET content=?,pinned=?,updated=? WHERE id=? AND account=? AND session=?",
                       (clean(content), int(pinned), time.time(), memory_id, account, session))

    def delete(self, account: str, session: str, memory_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM memories WHERE id=? AND account=? AND session=?", (memory_id, account, session))

    def delete_profile(self, account: str, session: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM profiles WHERE account=? AND session=?", (account, session))
