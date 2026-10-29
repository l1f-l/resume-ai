"""手动跑一遍全链路的脚本（开发自检用）：
python -m scripts.smoke
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("MOCK_STREAM_DELAY", "0")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

BASE = Path(__file__).resolve().parent.parent


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        ev, data = "message", {}
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip() or "{}")
        events.append((ev, data))
    return events


def main() -> None:
    c = TestClient(app)
    print("health:", c.get("/api/health").json())

    with open(BASE / "samples/sample_resume.pdf", "rb") as f:
        r = c.post(
            "/api/sessions",
            files={"file": ("sample_resume.pdf", f, "application/pdf")},
            data={"jd": (BASE / "samples/sample_jd.txt").read_text(encoding="utf-8")},
        )
    print("upload:", r.status_code)
    sid = r.json()["session_id"]
    print("resume:", json.dumps(r.json()["resume"], ensure_ascii=False)[:300])

    t0 = time.time()
    r = c.post(f"/api/sessions/{sid}/analyze")
    evs = parse_sse(r.text)
    dx = next(d for e, d in evs if e == "diagnosis")
    print(f"analyze {time.time()-t0:.2f}s score={dx['match_score']} gaps={len(dx['gap_questions'])}")
    print("templates:", [t["title"] for t in dx["retrieved_templates"]])
    print("q1:", dx["gap_questions"][0]["question"])

    answers = [
        "活动覆盖 320 万用户，带动 GMV 提升 28%",
        "推送触达的转化率从 2.1% 提升到 3.4%",
        "项目提前 2 周上线，节省约 40 人天",
        "留存看板服务 60 多名运营，日均查看 300 次",
    ]
    for i, ans in enumerate(answers, 1):
        r = c.post(f"/api/sessions/{sid}/chat", json={"message": ans})
        evs = parse_sse(r.text)
        kinds = [e for e, _ in evs]
        print(f"chat#{i}: {r.status_code} events={sorted(set(kinds))}")
        if "rewrite" in kinds:
            rw = next(d for e, d in evs if e == "rewrite")
            print("rewrite bullets:", len(rw["bullets"]))
            print("sample:", rw["bullets"][0]["optimized"])
        elif "gap" in kinds:
            print("next q:", next(d for e, d in evs if e == "gap")["question"])

    sess = c.get(f"/api/sessions/{sid}").json()
    print("stage:", sess["stage"], "score:", sess["match_score"])

    r = c.post(f"/api/sessions/{sid}/interview/start")
    evs = parse_sse(r.text)
    qs = next(d for e, d in evs if e == "questions")["questions"]
    print("questions:", [q["question"][:30] for q in qs])

    for i in range(len(qs)):
        r = c.post(
            f"/api/sessions/{sid}/interview/answer",
            json={"answer": "当时业务日活 200 万，我负责引导链路改版，先做了用户分层调研，"
                            "再设计了 3 档任务体系并推动 A/B 实验，最终 7 日留存从 31% 提升到 39%。"},
        )
        evs = parse_sse(r.text)
        fb = next((d for e, d in evs if e == "feedback"), None)
        print(f"answer#{i+1}:", fb["score"] if fb else None, [e for e, _ in evs if e in ("report", "question")])

    sess = c.get(f"/api/sessions/{sid}").json()
    print("report:", sess["report"]["overall"], sess["report"]["level"])

    h = c.get(f"/api/sessions/{sid}/export?format=html")
    print("html:", h.status_code, len(h.content), h.headers.get("content-disposition"))
    p = c.get(f"/api/sessions/{sid}/export?format=pdf")
    print("pdf:", p.status_code, len(p.content), p.content[:5])
    (BASE / "samples/out_resume.pdf").write_bytes(p.content)
    (BASE / "samples/out_resume.html").write_text(h.content.decode("utf-8"), encoding="utf-8")


if __name__ == "__main__":
    main()
