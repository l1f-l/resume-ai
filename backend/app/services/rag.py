"""RAG：用 Chroma 持久化「优秀简历模板」片段，按 JD 做语义检索。

关键取舍：向量化不依赖在线 Embedding API，也不下载 ONNX 模型，而是用
确定性哈希词袋向量（hash-trick TF），离线可跑、结果稳定可测。
Chroma 不可用时自动降级为内存余弦检索，接口完全一致。
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from ..config import settings
from ..schemas import TemplateHit

DIM = 384


class HashEmbedding:
    """轻量确定性 embedding：中英文 n-gram 哈希到固定维度。"""

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 - Chroma 协议
        return [self._one(text) for text in input]

    @staticmethod
    def _tokens(text: str) -> list[str]:
        text = (text or "").lower()
        latin = re.findall(r"[a-z][a-z0-9.+#/-]{1,20}", text)
        cjk = re.findall(r"[\u4e00-\u9fa5]{2,4}", re.sub(r"[^\u4e00-\u9fa5]", " ", text))
        # 中文补充单字，提升短查询召回
        single = re.findall(r"[\u4e00-\u9fa5]", re.sub(r"[^\u4e00-\u9fa5]", " ", text))
        return latin + cjk + single

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        for tok in self._tokens(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
            vec[h % DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class TemplateStore:
    def __init__(self, template_dir: Path | None = None) -> None:
        self.dir = template_dir or (settings.data_dir / "templates")
        self.embedder = HashEmbedding()
        self._docs: list[dict] = []
        self._vectors: list[list[float]] = []
        self._collection = None
        self.backend = "memory"
        self._loaded = False

    # ------------------------------------------------------------------ #
    def _load_docs(self) -> None:
        self._docs = []
        if not self.dir.exists():
            return
        for path in sorted(self.dir.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            meta: dict[str, str] = {}
            body = raw
            if raw.startswith("---"):
                _, front, body = raw.split("---", 2)
                for line in front.strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
            title = meta.get("title") or path.stem
            tags = meta.get("tags", "")
            text = f"{title} {tags}\n{body.strip()}"
            self._docs.append(
                {
                    "id": path.stem,
                    "title": title,
                    "tags": tags,
                    "text": text,
                    "snippet": _condense(body),
                }
            )

    def _ensure_index(self) -> None:
        if self._loaded:
            return
        self._load_docs()
        self._vectors = self.embedder([d["text"] for d in self._docs]) if self._docs else []
        if settings.rag_enabled and self._docs:
            try:
                import chromadb  # noqa: PLC0415

                client = chromadb.PersistentClient(path=settings.chroma_dir)
                # 不依赖 Chroma 的默认 embedding（会下载 ONNX 模型），我们自己算向量
                self._collection = client.get_or_create_collection(
                    name="resume_templates_hash384",
                    metadata={"hnsw:space": "cosine"},
                )
                self._collection.upsert(
                    ids=[d["id"] for d in self._docs],
                    embeddings=self._vectors,
                    documents=[d["text"] for d in self._docs],
                    metadatas=[{"title": d["title"], "tags": d["tags"]} for d in self._docs],
                )
                self.backend = "chroma"
            except Exception:  # noqa: BLE001 - 缺依赖/目录不可写都降级
                self._collection = None
                self.backend = "memory"
        self._loaded = True

    # ------------------------------------------------------------------ #
    def search(self, query: str, k: int = 3) -> list[TemplateHit]:
        self._ensure_index()
        if not self._docs:
            return []
        if self._collection is not None:
            try:
                qv = self.embedder([query])[0]
                res = self._collection.query(
                    query_embeddings=[qv],
                    n_results=min(k, len(self._docs)),
                    include=["metadatas", "documents", "distances"],
                )
                hits: list[TemplateHit] = []
                for i, doc_id in enumerate(res["ids"][0]):
                    dist = (res.get("distances") or [[0.0]])[0][i] if res.get("distances") else 0.0
                    meta = (res.get("metadatas") or [[{}]])[0][i] or {}
                    body = (res.get("documents") or [[""]])[0][i] or ""
                    hits.append(
                        TemplateHit(
                            id=doc_id,
                            title=str(meta.get("title") or doc_id),
                            snippet=_condense(body),
                            score=round(max(0.0, 1.0 - float(dist)), 4),
                            source=f"chroma:{self.backend}",
                        )
                    )
                if hits:
                    return hits
            except Exception:  # noqa: BLE001
                pass

        qv = self.embedder([query])[0]
        scored = sorted(
            ((_cosine(qv, self._vectors[i]), d) for i, d in enumerate(self._docs)),
            key=lambda t: -t[0],
        )
        return [
            TemplateHit(id=d["id"], title=d["title"], snippet=d["snippet"], score=round(s, 4),
                        source="memory:cosine")
            for s, d in scored[:k]
        ]

    def size(self) -> int:
        self._ensure_index()
        return len(self._docs)


def _condense(text: str, limit: int = 220) -> str:
    body = re.sub(r"^---.*?---", "", text, flags=re.S).strip()
    body = re.sub(r"\s+", " ", body)
    return body[:limit] + ("…" if len(body) > limit else "")


store = TemplateStore()
