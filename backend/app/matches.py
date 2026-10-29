"""匹配记录仓储：Top3 推荐结果与岗位级报告快照。

为什么要快照：报告是 LLM 生成的有成本产物，前端刷新、回看历史都应直接读库，
不该重复调用模型；同时便于「同一岗位二次诊断」时做覆盖而不是堆积脏数据。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .config import settings
from .db import Database
from .schemas import MatchItem, MatchReport


class MatchStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db = Database(db_path or settings.db_path)

    # ------------------------------------------------------------------ #
    def save_ranking(self, user_id: str, session_id: str, items: list[MatchItem]) -> None:
        """重算推荐前先清掉旧的推荐位（保留用户手动选的 rank=0 记录）。"""
        self.db.execute(
            "DELETE FROM job_matches WHERE session_id = ? AND rank > 0 AND report_json IS NULL",
            (session_id,),
        )
        now = time.time()
        with self.db.connect() as conn:
            for item in items:
                conn.execute(
                    "INSERT INTO job_matches (id, user_id, session_id, job_id, match_score, rank, "
                    "source, reason, report_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(session_id, job_id) DO UPDATE SET "
                    "match_score=excluded.match_score, rank=excluded.rank, "
                    "reason=excluded.reason, source='rag'",
                    (
                        uuid.uuid4().hex[:12], user_id, session_id, item.job.id,
                        item.score, item.rank, "rag", item.reason, None, now,
                    ),
                )

    def save_report(self, user_id: str, session_id: str, report: MatchReport,
                    *, rank: int = 0) -> None:
        now = time.time()
        payload = report.model_dump_json()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM job_matches WHERE session_id = ? AND job_id = ?",
                (session_id, report.job_id),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE job_matches SET report_json = ?, match_score = ?, created_at = ? "
                    "WHERE id = ?",
                    (payload, report.match_score, now, row["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO job_matches (id, user_id, session_id, job_id, match_score, rank, "
                    "source, reason, report_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        uuid.uuid4().hex[:12], user_id, session_id, report.job_id,
                        report.match_score, rank, "manual", "", payload, now,
                    ),
                )

    def latest_report(self, session_id: str, job_id: str) -> MatchReport | None:
        row = self.db.one(
            "SELECT report_json FROM job_matches WHERE session_id = ? AND job_id = ?",
            (session_id, job_id),
        )
        if not row or not row.get("report_json"):
            return None
        try:
            return MatchReport.model_validate_json(row["report_json"])
        except ValueError:
            return None

    def current_report(self, session_id: str) -> MatchReport | None:
        row = self.db.one(
            "SELECT report_json FROM job_matches WHERE session_id = ? AND report_json IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        )
        if not row or not row.get("report_json"):
            return None
        try:
            return MatchReport.model_validate_json(row["report_json"])
        except ValueError:
            return None

    def list_ranking(self, session_id: str) -> list[dict]:
        rows = self.db.query(
            "SELECT m.job_id, m.match_score, m.rank, m.reason, m.report_json, "
            "j.title, j.company, j.city, j.seniority, j.salary_min, j.salary_max, j.skills "
            "FROM job_matches m LEFT JOIN jobs j ON j.id = m.job_id "
            "WHERE m.session_id = ? ORDER BY m.rank ASC, m.match_score DESC",
            (session_id,),
        )
        out = []
        for r in rows:
            try:
                skills = json.loads(r.get("skills") or "[]")
            except (TypeError, ValueError):
                skills = []
            out.append(
                {
                    "job_id": r["job_id"],
                    "title": r.get("title") or "",
                    "company": r.get("company") or "",
                    "city": r.get("city") or "",
                    "seniority": r.get("seniority") or "",
                    "salary": f"{r.get('salary_min') or 0}K-{r.get('salary_max') or 0}K",
                    "skills": skills,
                    "match_score": int(r.get("match_score") or 0),
                    "rank": int(r.get("rank") or 0),
                    "reason": r.get("reason") or "",
                    "has_report": bool(r.get("report_json")),
                }
            )
        return out

    def session_scores(self, session_id: str) -> dict[str, int]:
        rows = self.db.query(
            "SELECT job_id, match_score FROM job_matches WHERE session_id = ?", (session_id,)
        )
        return {r["job_id"]: int(r["match_score"] or 0) for r in rows}


match_store = MatchStore()
