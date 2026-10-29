"""投递记录仓储 + 状态机。

状态流转（单向，不可回退，避免看板上出现「邀面 → 已投递」这种倒流）：
    applied ──> interviewing ──> offer
       │             │
       └─────────────┴────────> rejected / withdrawn
每次流转都写一条 application_events，前端时间轴直接读。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .config import settings
from .db import Database

STATUS_LABELS = {
    "applied": "已投递",
    "interviewing": "已邀面",
    "offer": "已发 Offer",
    "rejected": "未通过",
    "withdrawn": "已撤回",
}

TRANSITIONS: dict[str, set[str]] = {
    "applied": {"interviewing", "rejected", "withdrawn"},
    "interviewing": {"offer", "rejected", "withdrawn"},
    "offer": set(),
    "rejected": set(),
    "withdrawn": set(),
}


class ApplicationError(RuntimeError):
    """业务校验失败（重复投递、非法流转），路由层转 409。"""


class ApplicationStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db = Database(db_path or settings.db_path)

    # ------------------------------------------------------------------ #
    def exists(self, user_id: str, job_id: str) -> dict | None:
        return self.db.one(
            "SELECT * FROM applications WHERE user_id = ? AND job_id = ?", (user_id, job_id)
        )

    def create(self, **kw: Any) -> dict:
        if self.exists(kw["user_id"], kw["job_id"]):
            raise ApplicationError("该岗位已投递过，可在投递看板中查看进度")
        app_id = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO applications (id, user_id, session_id, job_id, status, match_score, "
            "email_to, email_subject, email_body, mail_status, mail_error, attachment, note, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                app_id, kw["user_id"], kw["session_id"], kw["job_id"], "applied",
                int(kw.get("match_score") or 0), kw.get("email_to", ""),
                kw.get("email_subject", ""), kw.get("email_body", ""),
                kw.get("mail_status", "pending"), kw.get("mail_error", ""),
                kw.get("attachment", ""), kw.get("note", ""), now, now,
            ),
        )
        self._event(app_id, None, "applied", kw.get("note", "") or "投递成功")
        return self.get(app_id, kw["user_id"]) or {}

    def get(self, app_id: str, user_id: str) -> dict | None:
        row = self.db.one(
            "SELECT a.*, j.title, j.company, j.city, j.salary_min, j.salary_max, j.skills "
            "FROM applications a LEFT JOIN jobs j ON j.id = a.job_id "
            "WHERE a.id = ? AND a.user_id = ?",
            (app_id, user_id),
        )
        return self._shape(row)

    def list(self, user_id: str, status: str | None = None) -> list[dict]:
        sql = (
            "SELECT a.*, j.title, j.company, j.city, j.salary_min, j.salary_max, j.skills "
            "FROM applications a LEFT JOIN jobs j ON j.id = a.job_id WHERE a.user_id = ?"
        )
        params: list[Any] = [user_id]
        if status:
            sql += " AND a.status = ?"
            params.append(status)
        sql += " ORDER BY a.updated_at DESC"
        return [self._shape(r) for r in self.db.query(sql, tuple(params))]  # type: ignore[misc]

    @staticmethod
    def _shape(row: dict | None) -> dict | None:
        if not row:
            return None
        out = dict(row)
        try:
            out["skills"] = json.loads(out.get("skills") or "[]")
        except (TypeError, ValueError):
            out["skills"] = []
        out["salary"] = f"{out.get('salary_min') or 0}K-{out.get('salary_max') or 0}K"
        out["job_title"] = out.get("title") or ""
        out["status_label"] = STATUS_LABELS.get(out.get("status", ""), out.get("status", ""))
        return out

    # ------------------------------------------------------------------ #
    def update_status(self, app_id: str, user_id: str, status: str, note: str = "") -> dict:
        app = self.get(app_id, user_id)
        if not app:
            raise ApplicationError("投递记录不存在")
        src = app["status"]
        if status == src:
            return app
        if status not in TRANSITIONS.get(src, set()):
            allowed = "、".join(STATUS_LABELS[s] for s in TRANSITIONS.get(src, set())) or "无"
            raise ApplicationError(
                f"「{STATUS_LABELS.get(src, src)}」不能变更为"
                f"「{STATUS_LABELS.get(status, status)}」，可选：{allowed}"
            )
        now = time.time()
        self.db.execute(
            "UPDATE applications SET status = ?, note = ?, updated_at = ? WHERE id = ?",
            (status, note or app.get("note", ""), now, app_id),
        )
        self._event(app_id, src, status, note)
        return self.get(app_id, user_id) or {}

    def _event(self, app_id: str, src: str | None, dst: str, note: str) -> None:
        self.db.execute(
            "INSERT INTO application_events (application_id, from_status, to_status, note, created_at) "
            "VALUES (?,?,?,?,?)",
            (app_id, src, dst, (note or "")[:200], time.time()),
        )

    def events(self, app_id: str, user_id: str) -> list[dict]:
        if not self.get(app_id, user_id):
            return []
        rows = self.db.query(
            "SELECT from_status, to_status, note, created_at FROM application_events "
            "WHERE application_id = ? ORDER BY id ASC",
            (app_id,),
        )
        return [
            {**r, "label": STATUS_LABELS.get(r["to_status"], r["to_status"])} for r in rows
        ]

    def summary(self, user_id: str) -> dict:
        rows = self.db.query(
            "SELECT status, COUNT(*) AS n FROM applications WHERE user_id = ? GROUP BY status",
            (user_id,),
        )
        counts = {r["status"]: int(r["n"]) for r in rows}
        total = sum(counts.values())
        applied = counts.get("applied", 0) + counts.get("interviewing", 0) + counts.get("offer", 0)
        interview = counts.get("interviewing", 0) + counts.get("offer", 0)
        return {
            "total": total,
            "applied": counts.get("applied", 0),
            "interviewing": counts.get("interviewing", 0),
            "offer": counts.get("offer", 0),
            "rejected": counts.get("rejected", 0),
            "withdrawn": counts.get("withdrawn", 0),
            "interview_rate": round(interview / applied * 100) if applied else 0,
        }


application_store = ApplicationStore()
