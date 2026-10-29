"""岗位池：SQLite 为唯一事实来源，Chroma 独立集合只做语义索引。

设计要点：
- 「不编造岗位」的前提是有一份可枚举的白名单，所以岗位全部落在 SQLite，
  Chroma 只存 id + 向量 + 少量元数据，检索结果一定回查 SQLite 才返回。
- 集合名独立（jobs_hash384），与简历模板集合互不干扰。
- Chroma 不可用时降级为内存余弦，接口完全一致（沿用 rag.py 的 hash-trick 向量）。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .config import settings
from .db import Database
from .jobs_seed import build_jobs
from .services.rag import HashEmbedding, _cosine

log = logging.getLogger("jobs")

COLLECTION = "jobs_hash384"


class JobStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db = Database(db_path or settings.db_path)
        self.embedder = HashEmbedding()
        self._collection = None
        self._ids: list[str] = []
        self._vectors: list[list[float]] = []
        self._loaded = False
        self.backend = "memory"

    # ------------------------------------------------------------------ #
    # 初始化
    # ------------------------------------------------------------------ #
    def seed(self) -> int:
        """幂等导入种子数据，返回库内岗位总数。"""
        existing = int(self.db.scalar("SELECT COUNT(*) FROM jobs") or 0)
        if existing == 0:
            rows = build_jobs()
            now = time.time()
            with self.db.connect() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO jobs "
                    "(id, title, company, city, salary_min, salary_max, seniority, industry, "
                    " tags, skills, jd_text, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            j["id"], j["title"], j["company"], j["city"],
                            j["salary_min"], j["salary_max"], j["seniority"], j["industry"],
                            json.dumps(j["tags"], ensure_ascii=False),
                            json.dumps(j["skills"], ensure_ascii=False),
                            j["jd_text"], now,
                        )
                        for j in rows
                    ],
                )
            log.info("job pool seeded: %d jobs", len(rows))
        count = int(self.db.scalar("SELECT COUNT(*) FROM jobs") or 0)
        self._ensure_index()
        return count

    def _ensure_index(self) -> None:
        if self._loaded:
            return
        rows = self.db.query("SELECT * FROM jobs ORDER BY id")
        docs = [self._embed_text(r) for r in rows]
        self._ids = [r["id"] for r in rows]
        self._vectors = self.embedder(docs) if docs else []

        if settings.rag_enabled and docs:
            try:
                import chromadb  # noqa: PLC0415

                client = chromadb.PersistentClient(path=settings.chroma_dir)
                col = client.get_or_create_collection(
                    name=COLLECTION, metadata={"hnsw:space": "cosine"}
                )
                col.upsert(
                    ids=self._ids,
                    embeddings=self._vectors,
                    documents=docs,
                    metadatas=[
                        {
                            "title": r["title"],
                            "company": r["company"],
                            "city": r["city"] or "",
                            "seniority": r["seniority"] or "",
                            "industry": r["industry"] or "",
                            "salary_min": int(r["salary_min"] or 0),
                            "salary_max": int(r["salary_max"] or 0),
                        }
                        for r in rows
                    ],
                )
                self._collection = col
                self.backend = "chroma"
            except Exception as exc:  # noqa: BLE001 - 缺依赖/目录不可写都降级
                log.warning("job index falls back to memory: %s", exc)
                self._collection = None
                self.backend = "memory"
        self._loaded = True

    @staticmethod
    def _embed_text(row: dict) -> str:
        try:
            skills = "、".join(json.loads(row.get("skills") or "[]"))
        except (TypeError, ValueError):
            skills = ""
        return (
            f"{row.get('title','')} {row.get('company','')} {row.get('city','')} "
            f"{row.get('seniority','')} {row.get('industry','')} "
            f"技能：{skills}\n{(row.get('jd_text') or '')[:1200]}"
        )

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #
    @staticmethod
    def _shape(row: dict | None) -> dict | None:
        if not row:
            return None
        out = dict(row)
        for key in ("tags", "skills"):
            try:
                out[key] = json.loads(out.get(key) or "[]")
            except (TypeError, ValueError):
                out[key] = []
        out["salary"] = f"{out.get('salary_min', 0)}K-{out.get('salary_max', 0)}K"
        return out

    def get(self, job_id: str) -> dict | None:
        return self._shape(self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,)))

    def all(self) -> list[dict]:
        return [self._shape(r) for r in self.db.query("SELECT * FROM jobs ORDER BY id")]  # type: ignore[misc]

    def list(
        self,
        *,
        q: str = "",
        city: str = "",
        seniority: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        where, params = [], []
        if q.strip():
            where.append("(title LIKE ? OR company LIKE ? OR skills LIKE ? OR jd_text LIKE ?)")
            like = f"%{q.strip()}%"
            params += [like, like, like, like]
        if city.strip():
            where.append("city = ?")
            params.append(city.strip())
        if seniority.strip():
            where.append("seniority = ?")
            params.append(seniority.strip())

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM jobs {clause}", tuple(params)) or 0)
        rows = self.db.query(
            f"SELECT * FROM jobs {clause} ORDER BY id LIMIT ? OFFSET ?",
            tuple(params) + (limit, offset),
        )
        return [self._shape(r) for r in rows], total  # type: ignore[misc]

    def filters(self) -> dict:
        cities = [r["city"] for r in self.db.query(
            "SELECT DISTINCT city FROM jobs WHERE city <> '' ORDER BY city"
        )]
        seniorities = [r["seniority"] for r in self.db.query(
            "SELECT DISTINCT seniority FROM jobs WHERE seniority <> '' ORDER BY seniority"
        )]
        return {"cities": cities, "seniorities": seniorities, "total": self.count()}

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM jobs") or 0)

    # ------------------------------------------------------------------ #
    # 语义检索
    # ------------------------------------------------------------------ #
    def search_vector(self, query: str, k: int = 12) -> list[tuple[str, float]]:
        """返回 [(job_id, score)]，score ∈ [0,1]，按相似度降序。"""
        self._ensure_index()
        if not self._ids or not query.strip():
            return []
        qv = self.embedder([query[:2000]])[0]

        if self._collection is not None:
            try:
                res = self._collection.query(
                    query_embeddings=[qv],
                    n_results=min(k, len(self._ids)),
                    include=["distances"],
                )
                ids = res["ids"][0]
                dists = (res.get("distances") or [[0.0] * len(ids)])[0]
                return [(jid, round(max(0.0, 1.0 - float(d)), 4)) for jid, d in zip(ids, dists)]
            except Exception as exc:  # noqa: BLE001
                log.warning("chroma query failed, fallback: %s", exc)

        scored = sorted(
            ((_cosine(qv, self._vectors[i]), self._ids[i]) for i in range(len(self._ids))),
            key=lambda t: -t[0],
        )
        return [(jid, round(s, 4)) for s, jid in scored[:k]]


job_store = JobStore()
