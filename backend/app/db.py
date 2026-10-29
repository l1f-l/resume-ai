"""SQLite 持久化层：把会话从「进程内存」搬到磁盘。

设计取舍：
- 用标准库 sqlite3（零额外依赖），每次操作短连接 + WAL，避免线程/协程共享连接。
- 一个大 JSON 列存结构化简历/诊断/面试数据，字段化只保留「查询与恢复必需」的元信息。
- stage_history 单独一张表，方便做流程漏斗分析与审计（也便于测试状态机落库）。
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    stage           TEXT NOT NULL,
    file_name       TEXT,
    pages           INTEGER DEFAULT 0,
    chars           INTEGER DEFAULT 0,
    resume_text     TEXT,
    jd_text         TEXT,
    resume_json     TEXT,
    diagnosis_json  TEXT,
    answers_json    TEXT,
    qa_json         TEXT,
    questions_json  TEXT,
    feedbacks_json  TEXT,
    report_json     TEXT,
    messages_json   TEXT,
    cursor          INTEGER DEFAULT 0,
    llm_mode        TEXT,
    parse_meta_json TEXT,
    created_at      REAL,
    updated_at      REAL
);
CREATE TABLE IF NOT EXISTS stage_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    stage      TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_stage_session ON stage_history(session_id);

-- --------------------------------------------------------------------------
-- Pro 版：多用户 + 岗位池 + 匹配 + 投递
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    display_name  TEXT DEFAULT '',
    phone         TEXT DEFAULT '',
    created_at    REAL NOT NULL,
    last_login_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    company    TEXT NOT NULL,
    city       TEXT DEFAULT '',
    salary_min INTEGER DEFAULT 0,
    salary_max INTEGER DEFAULT 0,
    seniority  TEXT DEFAULT '',
    industry   TEXT DEFAULT '',
    tags       TEXT DEFAULT '[]',
    skills     TEXT DEFAULT '[]',
    jd_text    TEXT NOT NULL,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_city ON jobs(city);
CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(title);
CREATE INDEX IF NOT EXISTS idx_jobs_seniority ON jobs(seniority);

CREATE TABLE IF NOT EXISTS job_matches (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    job_id      TEXT NOT NULL,
    match_score INTEGER DEFAULT 0,
    rank        INTEGER DEFAULT 0,
    source      TEXT DEFAULT 'rag',
    reason      TEXT DEFAULT '',
    report_json TEXT,
    created_at  REAL,
    UNIQUE(session_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_session ON job_matches(session_id, rank);
CREATE INDEX IF NOT EXISTS idx_matches_user ON job_matches(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS applications (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    job_id        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'applied',
    match_score   INTEGER DEFAULT 0,
    email_to      TEXT DEFAULT '',
    email_subject TEXT DEFAULT '',
    email_body    TEXT DEFAULT '',
    mail_status   TEXT DEFAULT 'pending',
    mail_error    TEXT DEFAULT '',
    attachment    TEXT DEFAULT '',
    note          TEXT DEFAULT '',
    created_at    REAL,
    updated_at    REAL,
    UNIQUE(user_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_apps_user ON applications(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS application_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL,
    from_status    TEXT,
    to_status      TEXT NOT NULL,
    note           TEXT DEFAULT '',
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_events ON application_events(application_id);
"""

# 老库升级：只加缺失列，不动已有数据（旧会话 user_id 保持 NULL，不会串到任何账号）
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("sessions", "user_id", "ALTER TABLE sessions ADD COLUMN user_id TEXT"),
    ("sessions", "job_id", "ALTER TABLE sessions ADD COLUMN job_id TEXT"),
)

POST_MIGRATION = """
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at DESC);
"""

JSON_FIELDS = (
    "resume_json",
    "diagnosis_json",
    "answers_json",
    "qa_json",
    "questions_json",
    "feedbacks_json",
    "report_json",
    "messages_json",
    "parse_meta_json",
)


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """幂等升级：缺列才 ALTER，重复启动安全。"""
        for table, column, ddl in MIGRATIONS:
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(ddl)
        conn.executescript(POST_MIGRATION)

    # ------------------------------------------------------------------ #
    # 通用查询辅助（新表用；sessions 仍走 upsert/load 专用路径）
    # ------------------------------------------------------------------ #
    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, params)

    def scalar(self, sql: str, params: tuple = ()) -> Any:
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------ #
    def upsert(self, row: dict[str, Any]) -> None:
        row = dict(row)
        for key in JSON_FIELDS:
            val = row.get(key)
            if val is None or isinstance(val, str):
                continue  # None 保留为 SQL NULL，「null」字符串会被 pydantic 当成数据
            row[key] = json.dumps(val, ensure_ascii=False)
        cols = ", ".join(row.keys())
        marks = ", ".join(f":{k}" for k in row.keys())
        updates = ", ".join(f"{k}=excluded.{k}" for k in row.keys() if k != "id")
        sql = f"INSERT INTO sessions ({cols}) VALUES ({marks}) ON CONFLICT(id) DO UPDATE SET {updates}"
        with self.connect() as conn:
            conn.execute(sql, row)

    def load(self, sid: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,))
            row = cur.fetchone()
        return dict(row) if row else None

    def delete(self, sid: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            conn.execute("DELETE FROM stage_history WHERE session_id = ?", (sid,))

    def count(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])

    def list_recent(self, limit: int = 20, user_id: str | None = None) -> list[dict[str, Any]]:
        cols = "id, stage, file_name, job_id, updated_at, created_at"
        with self.connect() as conn:
            if user_id is None:
                rows = conn.execute(
                    f"SELECT {cols} FROM sessions ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {cols} FROM sessions WHERE user_id = ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    def add_stage(self, sid: str, stage: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO stage_history (session_id, stage, created_at) VALUES (?,?,?)",
                (sid, stage, time.time()),
            )

    def stages(self, sid: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT stage FROM stage_history WHERE session_id = ? ORDER BY id ASC", (sid,)
            ).fetchall()
        return [r["stage"] for r in rows]
